"""Bounded local content-addressed artifact store."""

import os
from pathlib import Path

from foundation.contracts.errors import ArtifactError
from foundation.contracts.preservation import ArtifactRef

from .integrity import (
    path_for_digest,
    read_bounded,
    reference_for,
    validate_contract,
    verify_payload,
)
from .publication import publish_bytes

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class ContentAddressedStore:
    def __init__(self, root: Path, *, max_artifact_bytes: int = MAX_ARTIFACT_BYTES) -> None:
        self.root = root.resolve()
        self.objects = self.root / "objects"
        self.quarantine = self.root / "quarantine"
        self.max_artifact_bytes = max_artifact_bytes
        self.objects.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)

    def path_for(self, reference: ArtifactRef) -> Path:
        return path_for_digest(self.objects, reference.digest)

    def publish(self, artifact_type: str, schema_version: str, payload: bytes) -> ArtifactRef:
        validate_contract(artifact_type, schema_version)
        if not isinstance(payload, bytes):
            raise ArtifactError("Artifact payload must be immutable bytes.")
        if not payload or len(payload) > self.max_artifact_bytes:
            raise ArtifactError("Artifact payload is empty or exceeds its configured limit.")
        reference = reference_for(artifact_type, schema_version, payload)
        final_path = self.path_for(reference)
        publish_bytes(final_path, payload, lambda: self.load(reference))
        return reference

    def load(self, reference: ArtifactRef) -> bytes:
        validate_contract(reference.artifact_type, reference.schema_version)
        payload = read_bounded(self.path_for(reference), self.max_artifact_bytes)
        verify_payload(reference, payload)
        return payload

    def verify(self, reference: ArtifactRef) -> bool:
        self.load(reference)
        return True

    def iter_digests(self) -> tuple[str, ...]:
        return tuple(sorted(path.stem for path in self.objects.glob("*/*.block")))

    def quarantine_digest(self, digest: str) -> Path:
        source = path_for_digest(self.objects, digest)
        if not source.exists():
            raise ArtifactError("Cannot quarantine a missing artifact.")
        target = (self.quarantine / source.name).resolve()
        if self.quarantine not in target.parents:
            raise ArtifactError("Quarantine path escapes the managed store.")
        os.replace(source, target)
        return target
