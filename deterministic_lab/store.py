"""Bounded local immutable content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ArtifactError
from .identities import identity_from_bytes

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_PORTABLE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    identity: str
    artifact_type: str
    schema_version: str
    size: int
    payload_digest: str

    @property
    def digest(self) -> str:
        return self.identity.rsplit(":", 1)[-1]


class ContentAddressedStore:
    def __init__(self, root: Path, *, max_artifact_bytes: int = MAX_ARTIFACT_BYTES) -> None:
        self.root = root.resolve()
        self.objects = self.root / "objects"
        self.quarantine = self.root / "quarantine"
        self.max_artifact_bytes = max_artifact_bytes
        self.objects.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)

    def _validate_contract(self, artifact_type: str, schema_version: str) -> None:
        if not _PORTABLE_NAME.fullmatch(artifact_type):
            raise ArtifactError("Artifact type is not a portable bounded name.")
        if not schema_version or len(schema_version) > 100 or "\x00" in schema_version:
            raise ArtifactError("Artifact schema version is invalid.")

    def _path_for_digest(self, digest: str) -> Path:
        if len(digest) != 64:
            raise ArtifactError("Artifact digest must contain 64 hexadecimal characters.")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ArtifactError("Artifact digest is not hexadecimal.") from exc
        path = (self.objects / digest[:2] / f"{digest}.block").resolve()
        if self.objects != path and self.objects not in path.parents:
            raise ArtifactError("Artifact path escapes the managed store.")
        return path

    def path_for(self, reference: ArtifactRef) -> Path:
        return self._path_for_digest(reference.digest)

    def _reference(self, artifact_type: str, schema_version: str, payload: bytes) -> ArtifactRef:
        identity = str(
            identity_from_bytes("artifact", f"{artifact_type}:{schema_version}", payload)
        )
        return ArtifactRef(
            identity=identity,
            artifact_type=artifact_type,
            schema_version=schema_version,
            size=len(payload),
            payload_digest=hashlib.sha256(payload).hexdigest(),
        )

    def publish(self, artifact_type: str, schema_version: str, payload: bytes) -> ArtifactRef:
        self._validate_contract(artifact_type, schema_version)
        if not isinstance(payload, bytes):
            raise ArtifactError("Artifact payload must be immutable bytes.")
        if not payload or len(payload) > self.max_artifact_bytes:
            raise ArtifactError("Artifact payload is empty or exceeds its configured limit.")
        reference = self._reference(artifact_type, schema_version, payload)
        final_path = self.path_for(reference)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            if self.load(reference) != payload:
                raise ArtifactError("Existing artifact path does not contain identical content.")
            return reference
        descriptor, staged_name = tempfile.mkstemp(prefix=".stage-", dir=final_path.parent)
        staged = Path(staged_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(staged, final_path)
            except FileExistsError:
                if self.load(reference) != payload:
                    raise ArtifactError(
                        "Concurrent publication produced conflicting content."
                    ) from None
            except OSError as exc:
                raise ArtifactError("Atomic artifact publication is unavailable.") from exc
        finally:
            staged.unlink(missing_ok=True)
        return reference

    def _read_bounded(self, path: Path) -> bytes:
        if not path.is_file():
            raise ArtifactError("Artifact is missing from the managed store.")
        if path.stat().st_size > self.max_artifact_bytes:
            raise ArtifactError("Stored artifact exceeds the configured read limit.")
        output = bytearray()
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                output.extend(chunk)
                if len(output) > self.max_artifact_bytes:
                    raise ArtifactError("Stored artifact exceeded the read limit.")
        return bytes(output)

    def load(self, reference: ArtifactRef) -> bytes:
        self._validate_contract(reference.artifact_type, reference.schema_version)
        payload = self._read_bounded(self.path_for(reference))
        if len(payload) != reference.size:
            raise ArtifactError("Stored artifact size does not match its reference.")
        if hashlib.sha256(payload).hexdigest() != reference.payload_digest:
            raise ArtifactError("Stored artifact payload checksum mismatch.")
        if self._reference(reference.artifact_type, reference.schema_version, payload) != reference:
            raise ArtifactError("Stored artifact identity does not match its contract.")
        return payload

    def verify(self, reference: ArtifactRef) -> bool:
        self.load(reference)
        return True

    def iter_digests(self) -> tuple[str, ...]:
        return tuple(sorted(path.stem for path in self.objects.glob("*/*.block")))

    def quarantine_digest(self, digest: str) -> Path:
        source = self._path_for_digest(digest)
        if not source.exists():
            raise ArtifactError("Cannot quarantine a missing artifact.")
        target = (self.quarantine / source.name).resolve()
        if self.quarantine not in target.parents:
            raise ArtifactError("Quarantine path escapes the managed store.")
        os.replace(source, target)
        return target
