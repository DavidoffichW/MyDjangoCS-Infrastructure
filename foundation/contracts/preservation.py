"""Narrow composition contract between scientific authority and preservation."""

from dataclasses import dataclass
from typing import Protocol


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


class ArtifactStore(Protocol):
    """Storage operations required by the stable foundation API."""

    def publish(self, artifact_type: str, schema_version: str, payload: bytes) -> ArtifactRef: ...

    def load(self, reference: ArtifactRef) -> bytes: ...
