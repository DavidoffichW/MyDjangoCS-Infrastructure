"""Portable naming, content identity, and bounded-read checks."""

import hashlib
import re
from pathlib import Path

from foundation.contracts.errors import ArtifactError
from foundation.contracts.identities import identity_from_bytes
from foundation.contracts.preservation import ArtifactRef

_PORTABLE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def validate_contract(artifact_type: str, schema_version: str) -> None:
    if not _PORTABLE_NAME.fullmatch(artifact_type):
        raise ArtifactError("Artifact type is not a portable bounded name.")
    if not schema_version or len(schema_version) > 100 or "\x00" in schema_version:
        raise ArtifactError("Artifact schema version is invalid.")


def path_for_digest(objects: Path, digest: str) -> Path:
    if len(digest) != 64:
        raise ArtifactError("Artifact digest must contain 64 hexadecimal characters.")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ArtifactError("Artifact digest is not hexadecimal.") from exc
    path = (objects / digest[:2] / f"{digest}.block").resolve()
    if objects != path and objects not in path.parents:
        raise ArtifactError("Artifact path escapes the managed store.")
    return path


def reference_for(artifact_type: str, schema_version: str, payload: bytes) -> ArtifactRef:
    identity = str(identity_from_bytes("artifact", f"{artifact_type}:{schema_version}", payload))
    return ArtifactRef(
        identity=identity,
        artifact_type=artifact_type,
        schema_version=schema_version,
        size=len(payload),
        payload_digest=hashlib.sha256(payload).hexdigest(),
    )


def read_bounded(path: Path, max_bytes: int) -> bytes:
    if not path.is_file():
        raise ArtifactError("Artifact is missing from the managed store.")
    if path.stat().st_size > max_bytes:
        raise ArtifactError("Stored artifact exceeds the configured read limit.")
    output = bytearray()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            output.extend(chunk)
            if len(output) > max_bytes:
                raise ArtifactError("Stored artifact exceeded the read limit.")
    return bytes(output)


def verify_payload(reference: ArtifactRef, payload: bytes) -> None:
    if len(payload) != reference.size:
        raise ArtifactError("Stored artifact size does not match its reference.")
    if hashlib.sha256(payload).hexdigest() != reference.payload_digest:
        raise ArtifactError("Stored artifact payload checksum mismatch.")
    actual = reference_for(reference.artifact_type, reference.schema_version, payload)
    if actual != reference:
        raise ArtifactError("Stored artifact identity does not match its contract.")
