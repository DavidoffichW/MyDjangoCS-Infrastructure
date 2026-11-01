"""Versioned investigation and admission records."""

from dataclasses import dataclass
from typing import Any

from foundation.contracts.numeric_policy import NUMERIC_POLICY

INVESTIGATION_SCHEMA = "mydjangocs.investigation/1"
ADMISSION_SCHEMA = "mydjangocs.admission/1"
OUTPUT_SCHEMA = "mydjangocs.result/1"


@dataclass(frozen=True, slots=True)
class Investigation:
    identity: str
    state_identity: str
    target_sensors: tuple[str, ...]
    variable_id: str
    unit: str
    start: str
    end: str
    method: str
    method_parameters: tuple[tuple[str, int], ...]
    missing_policy: str
    resource_budget: tuple[tuple[str, int], ...]
    output_schema: str = OUTPUT_SCHEMA
    schema_version: str = INVESTIGATION_SCHEMA

    def declaration(self, *, include_identity: bool = False) -> dict[str, Any]:
        result = {
            "method": self.method,
            "method_parameters": dict(self.method_parameters),
            "missing_policy": self.missing_policy,
            "numeric_policy": NUMERIC_POLICY,
            "output_schema": self.output_schema,
            "resource_budget": dict(self.resource_budget),
            "schema_version": self.schema_version,
            "state_identity": self.state_identity,
            "target_sensors": list(self.target_sensors),
            "temporal_scope": {"end": self.end, "start": self.start},
            "unit": self.unit,
            "variable_id": self.variable_id,
        }
        if include_identity:
            result["identity"] = self.identity
        return result


@dataclass(frozen=True, slots=True)
class Admission:
    identity: str
    investigation_identity: str
    state_identity: str
    computation_identity: str
    declaration: dict[str, Any]
    authorization_state: str = "admitted"
    schema_version: str = ADMISSION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_state": self.authorization_state,
            "computation_identity": self.computation_identity,
            "declaration": self.declaration,
            "identity": self.identity,
            "investigation_identity": self.investigation_identity,
            "schema_version": self.schema_version,
            "state_identity": self.state_identity,
        }
