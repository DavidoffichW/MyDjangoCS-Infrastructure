"""Strict fictional evidence schema used by the deterministic experiment."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from foundation.contracts.canonical import canonical_decimal, normalize_timestamp
from foundation.contracts.errors import SchemaError

EVIDENCE_SCHEMA = "mydjangocs.evidence/1"
RELATIONSHIP_SCHEMA = "mydjangocs.relationship/1"
MAX_OBSERVATIONS = 5_000
MAX_RELATIONSHIPS = 10_000
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_QUALITY = {"observed", "anomalous", "missing"}


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SchemaError(f"{field} must be a bounded portable identifier.")
    return value


@dataclass(frozen=True, slots=True)
class Observation:
    source_id: str
    sensor_id: str
    timestamp: str
    variable_id: str
    value: str | None
    unit: str
    missing: bool
    quality: str
    provenance: tuple[tuple[str, str], ...]
    schema_version: str = EVIDENCE_SCHEMA

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Observation:
        required = {
            "schema_version",
            "source_id",
            "sensor_id",
            "timestamp",
            "variable_id",
            "value",
            "unit",
            "missing",
            "quality",
            "provenance",
        }
        if set(raw) != required:
            raise SchemaError("Observation fields must exactly match evidence schema v1.")
        if raw["schema_version"] != EVIDENCE_SCHEMA:
            raise SchemaError("Unsupported evidence schema version.")
        missing = raw["missing"]
        if not isinstance(missing, bool):
            raise SchemaError("missing must be a boolean.")
        value = raw["value"]
        if missing != (value is None):
            raise SchemaError(
                "Missing observations must use null and only missing observations may."
            )
        canonical_value = None if value is None else canonical_decimal(str(value))
        quality = raw["quality"]
        if quality not in _QUALITY or (missing and quality != "missing"):
            raise SchemaError("Observation quality is inconsistent with missingness.")
        provenance_raw = raw["provenance"]
        if not isinstance(provenance_raw, Mapping) or not provenance_raw:
            raise SchemaError("provenance must be a non-empty string mapping.")
        if any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in provenance_raw.items()
        ):
            raise SchemaError("provenance keys and values must be strings.")
        return cls(
            source_id=_identifier(raw["source_id"], "source_id"),
            sensor_id=_identifier(raw["sensor_id"], "sensor_id"),
            timestamp=normalize_timestamp(raw["timestamp"]),
            variable_id=_identifier(raw["variable_id"], "variable_id"),
            value=canonical_value,
            unit=_identifier(raw["unit"], "unit"),
            missing=missing,
            quality=quality,
            provenance=tuple(sorted(provenance_raw.items())),
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "missing": self.missing,
            "quality": self.quality,
            "sensor_id": self.sensor_id,
            "timestamp": self.timestamp,
            "unit": self.unit,
            "value": self.value,
            "variable_id": self.variable_id,
        }

    def provenance_dict(self) -> dict[str, Any]:
        return {
            "provenance": dict(self.provenance),
            "source_id": self.source_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.semantic_dict(),
            **self.provenance_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class Relationship:
    source_sensor: str
    target_sensor: str
    relationship_type: str
    weight: str
    schema_version: str = RELATIONSHIP_SCHEMA

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Relationship:
        required = {
            "schema_version",
            "source_sensor",
            "target_sensor",
            "relationship_type",
            "weight",
        }
        if set(raw) != required or raw["schema_version"] != RELATIONSHIP_SCHEMA:
            raise SchemaError("Relationship fields must exactly match relationship schema v1.")
        source = _identifier(raw["source_sensor"], "source_sensor")
        target = _identifier(raw["target_sensor"], "target_sensor")
        if source == target:
            raise SchemaError("Self relationships are not supported by this experiment.")
        weight = canonical_decimal(str(raw["weight"]), max_abs=Decimal("1"), max_places=6)
        if Decimal(weight) <= 0:
            raise SchemaError("Relationship weights must be greater than zero and at most one.")
        return cls(
            source_sensor=min(source, target),
            target_sensor=max(source, target),
            relationship_type=_identifier(raw["relationship_type"], "relationship_type"),
            weight=weight,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "relationship_type": self.relationship_type,
            "schema_version": self.schema_version,
            "source_sensor": self.source_sensor,
            "target_sensor": self.target_sensor,
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    observations: tuple[Observation, ...]
    relationships: tuple[Relationship, ...]
    schema_version: str = "mydjangocs.evidence-bundle/1"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvidenceBundle:
        if set(raw) != {"schema_version", "observations", "relationships"}:
            raise SchemaError("Evidence bundle fields do not match schema v1.")
        if raw["schema_version"] != "mydjangocs.evidence-bundle/1":
            raise SchemaError("Unsupported evidence bundle schema.")
        observations_raw = raw["observations"]
        relationships_raw = raw["relationships"]
        if not isinstance(observations_raw, list) or not observations_raw:
            raise SchemaError("Evidence bundle requires at least one observation.")
        if len(observations_raw) > MAX_OBSERVATIONS:
            raise SchemaError(f"Evidence exceeds {MAX_OBSERVATIONS} observations.")
        if not isinstance(relationships_raw, list) or len(relationships_raw) > MAX_RELATIONSHIPS:
            raise SchemaError("Relationship collection is invalid or exceeds its limit.")
        observations = tuple(
            sorted(
                (Observation.from_mapping(item) for item in observations_raw),
                key=lambda item: (
                    item.sensor_id,
                    item.timestamp,
                    item.variable_id,
                    item.source_id,
                ),
            )
        )
        relationships = tuple(
            sorted(
                (Relationship.from_mapping(item) for item in relationships_raw),
                key=lambda item: (
                    item.source_sensor,
                    item.target_sensor,
                    item.relationship_type,
                ),
            )
        )
        observation_keys = [
            (item.source_id, item.sensor_id, item.timestamp, item.variable_id)
            for item in observations
        ]
        if len(observation_keys) != len(set(observation_keys)):
            raise SchemaError("Duplicate observation identity is not permitted.")
        relation_keys = [
            (item.source_sensor, item.target_sensor, item.relationship_type)
            for item in relationships
        ]
        if len(relation_keys) != len(set(relation_keys)):
            raise SchemaError("Duplicate relationships are not permitted.")
        sensors = {item.sensor_id for item in observations}
        if any(
            item.source_sensor not in sensors or item.target_sensor not in sensors
            for item in relationships
        ):
            raise SchemaError("Relationships must not refer to unknown sensors.")
        return cls(observations=observations, relationships=relationships)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.semantic_dict() for item in self.observations],
            "relationships": [item.to_dict() for item in self.relationships],
            "schema_version": self.schema_version,
        }

    def provenance_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.provenance_dict() for item in self.observations],
            "schema_version": "mydjangocs.provenance/1",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "relationships": [item.to_dict() for item in self.relationships],
            "schema_version": self.schema_version,
        }
