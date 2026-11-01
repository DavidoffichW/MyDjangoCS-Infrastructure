"""Immutable records carried through deterministic reconstruction."""

from dataclasses import dataclass
from typing import Any

from foundation.schema.evidence import EvidenceBundle

MANIFEST_SCHEMA = "mydjangocs.manifest/1"
STATE_SCHEMA = "mydjangocs.state/1"


@dataclass(frozen=True, slots=True)
class RegisteredEvidence:
    bundle: EvidenceBundle
    content_identity: str
    provenance_identity: str
    canonical_payload: bytes


@dataclass(frozen=True, slots=True)
class DeclaredManifest:
    identity: str
    evidence_content_identity: str
    evidence_provenance_identity: str
    rules: tuple[tuple[str, str], ...]
    schema_version: str = MANIFEST_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_content_identity": self.evidence_content_identity,
            "evidence_provenance_identity": self.evidence_provenance_identity,
            "identity": self.identity,
            "rules": dict(self.rules),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class Entity:
    identity: str
    sensor_id: str
    entity_type: str = "fictional_sensor"

    def to_dict(self) -> dict[str, str]:
        return {
            "entity_type": self.entity_type,
            "identity": self.identity,
            "sensor_id": self.sensor_id,
        }


@dataclass(frozen=True, slots=True)
class Edge:
    identity: str
    source_entity: str
    target_entity: str
    relationship_type: str
    weight: str

    def to_dict(self) -> dict[str, str]:
        return {
            "identity": self.identity,
            "relationship_type": self.relationship_type,
            "source_entity": self.source_entity,
            "target_entity": self.target_entity,
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class StateObservation:
    entity_identity: str
    sensor_id: str
    timestamp: str
    variable_id: str
    value: str | None
    unit: str
    missing: bool
    quality: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_identity": self.entity_identity,
            "missing": self.missing,
            "quality": self.quality,
            "sensor_id": self.sensor_id,
            "timestamp": self.timestamp,
            "unit": self.unit,
            "value": self.value,
            "variable_id": self.variable_id,
        }


@dataclass(frozen=True, slots=True)
class ReconstructedState:
    identity: str
    manifest_identity: str
    entities: tuple[Entity, ...]
    edges: tuple[Edge, ...]
    observations: tuple[StateObservation, ...]
    schema_version: str = STATE_SCHEMA

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "edges": [item.to_dict() for item in self.edges],
            "entities": [item.to_dict() for item in self.entities],
            "observations": [item.to_dict() for item in self.observations],
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.semantic_dict(),
            "identity": self.identity,
            "manifest_identity": self.manifest_identity,
        }
