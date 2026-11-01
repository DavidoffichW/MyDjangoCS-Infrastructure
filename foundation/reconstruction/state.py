"""Pure semantic reconstruction and strict state loading."""

from collections.abc import Mapping
from typing import Any

from foundation.contracts.errors import IntegrityError, SchemaError
from foundation.contracts.identities import identity_for

from .records import (
    STATE_SCHEMA,
    DeclaredManifest,
    Edge,
    Entity,
    ReconstructedState,
    RegisteredEvidence,
    StateObservation,
)
from .verification import verify_state


def reconstruct_state(
    evidence: RegisteredEvidence, manifest: DeclaredManifest
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
