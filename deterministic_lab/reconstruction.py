"""Immutable semantic reconstruction from validated fictional evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_bytes
from .errors import IntegrityError, SchemaError
from .identities import identity_for
from .schema import EvidenceBundle

MANIFEST_SCHEMA = "mydjangocs.manifest/1"
STATE_SCHEMA = "mydjangocs.state/1"
RECONSTRUCTION_RULES = (
    ("entity_rule", "sensor-identity-v1"),
    ("missing_value_rule", "preserve-null-v1"),
    ("relationship_rule", "undirected-explicit-v1"),
)


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


def register_evidence(raw: Mapping[str, Any]) -> RegisteredEvidence:
    bundle = EvidenceBundle.from_mapping(raw)
    content_identity = str(
        identity_for("evidence-content", bundle.schema_version, bundle.semantic_dict())
    )
    provenance_identity = str(
        identity_for(
            "evidence-provenance",
            "mydjangocs.provenance/1",
            {
                "content_identity": content_identity,
                **bundle.provenance_dict(),
            },
        )
    )
    return RegisteredEvidence(
        bundle=bundle,
        content_identity=content_identity,
        provenance_identity=provenance_identity,
        canonical_payload=canonical_bytes(bundle.to_dict()),
    )


def declare_manifest(evidence: RegisteredEvidence) -> DeclaredManifest:
    payload = {
        "evidence_content_identity": evidence.content_identity,
        "evidence_provenance_identity": evidence.provenance_identity,
        "rules": dict(RECONSTRUCTION_RULES),
        "schema_version": MANIFEST_SCHEMA,
    }
    return DeclaredManifest(
        identity=str(identity_for("manifest", MANIFEST_SCHEMA, payload)),
        evidence_content_identity=evidence.content_identity,
        evidence_provenance_identity=evidence.provenance_identity,
        rules=RECONSTRUCTION_RULES,
    )


def reconstruct_state(
    evidence: RegisteredEvidence,
    manifest: DeclaredManifest,
) -> ReconstructedState:
    if manifest.evidence_content_identity != evidence.content_identity:
        raise IntegrityError("Manifest does not bind the supplied evidence content.")
    if manifest.evidence_provenance_identity != evidence.provenance_identity:
        raise IntegrityError("Manifest does not bind the supplied evidence provenance.")
    sensor_ids = sorted({item.sensor_id for item in evidence.bundle.observations})
    entities = tuple(
        Entity(
            identity=str(
                identity_for(
                    "entity",
                    "mydjangocs.entity/1",
                    {"entity_type": "fictional_sensor", "sensor_id": sensor_id},
                )
            ),
            sensor_id=sensor_id,
        )
        for sensor_id in sensor_ids
    )
    entity_by_sensor = {item.sensor_id: item.identity for item in entities}
    edges = tuple(
        Edge(
            identity=str(
                identity_for(
                    "relationship",
                    "mydjangocs.relationship-state/1",
                    {
                        "relationship_type": relation.relationship_type,
                        "source_entity": entity_by_sensor[relation.source_sensor],
                        "target_entity": entity_by_sensor[relation.target_sensor],
                        "weight": relation.weight,
                    },
                )
            ),
            source_entity=entity_by_sensor[relation.source_sensor],
            target_entity=entity_by_sensor[relation.target_sensor],
            relationship_type=relation.relationship_type,
            weight=relation.weight,
        )
        for relation in evidence.bundle.relationships
    )
    observations = tuple(
        StateObservation(
            entity_identity=entity_by_sensor[item.sensor_id],
            sensor_id=item.sensor_id,
            timestamp=item.timestamp,
            variable_id=item.variable_id,
            value=item.value,
            unit=item.unit,
            missing=item.missing,
            quality=item.quality,
        )
        for item in evidence.bundle.observations
    )
    semantic = {
        "edges": [item.to_dict() for item in edges],
        "entities": [item.to_dict() for item in entities],
        "observations": [item.to_dict() for item in observations],
        "schema_version": STATE_SCHEMA,
    }
    state = ReconstructedState(
        identity=str(identity_for("semantic-state", STATE_SCHEMA, semantic)),
        manifest_identity=manifest.identity,
        entities=entities,
        edges=edges,
        observations=observations,
    )
    verify_state(state)
    return state


def verify_state(state: ReconstructedState) -> None:
    expected = str(identity_for("semantic-state", STATE_SCHEMA, state.semantic_dict()))
    if state.identity != expected:
        raise IntegrityError("Reconstructed state identity does not match its semantic content.")
    entity_ids = {item.identity for item in state.entities}
    if len(entity_ids) != len(state.entities):
        raise IntegrityError("Reconstructed entity identities are not unique.")
    if any(
        item.source_entity not in entity_ids or item.target_entity not in entity_ids
        for item in state.edges
    ):
        raise IntegrityError("Reconstructed state contains a dangling relationship.")
    if any(item.entity_identity not in entity_ids for item in state.observations):
        raise IntegrityError("Reconstructed observation refers to an unknown entity.")


def load_state(raw: Mapping[str, Any]) -> ReconstructedState:
    required = {
        "identity",
        "manifest_identity",
        "entities",
        "edges",
        "observations",
        "schema_version",
    }
    if set(raw) != required or raw["schema_version"] != STATE_SCHEMA:
        raise SchemaError("Stored state does not match state schema v1.")
    try:
        state = ReconstructedState(
            identity=str(raw["identity"]),
            manifest_identity=str(raw["manifest_identity"]),
            entities=tuple(Entity(**item) for item in raw["entities"]),
            edges=tuple(Edge(**item) for item in raw["edges"]),
            observations=tuple(StateObservation(**item) for item in raw["observations"]),
        )
    except (KeyError, TypeError) as exc:
        raise SchemaError("Stored state fields are invalid.") from exc
    verify_state(state)
    return state
