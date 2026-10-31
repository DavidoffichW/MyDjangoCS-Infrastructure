"""Investigation closure, resource admission and computation identity."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import normalize_timestamp
from .errors import AdmissionError
from .identities import identity_for
from .methods import NEIGHBOR_METHOD, NUMERIC_POLICY, SUPPORTED_METHODS, TIME_WINDOW_METHOD
from .reconstruction import ReconstructedState, verify_state

INVESTIGATION_SCHEMA = "mydjangocs.investigation/1"
ADMISSION_SCHEMA = "mydjangocs.admission/1"
OUTPUT_SCHEMA = "mydjangocs.result/1"
MAX_TARGETS = 100
MAX_SELECTED_RECORDS = 5_000


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


class VerificationPipeline:
    """Five explicit admission stages with typed, stable rejection codes."""

    def __init__(self, state_loader: Callable[[str], ReconstructedState]) -> None:
        self.state_loader = state_loader

    def _structure(self, raw: Mapping[str, Any]) -> Investigation:
        required = {
            "schema_version",
            "state_identity",
            "target_sensors",
            "variable_id",
            "unit",
            "temporal_scope",
            "method",
            "method_parameters",
            "missing_policy",
            "numeric_policy",
            "resource_budget",
            "output_schema",
        }
        if set(raw) != required or raw.get("schema_version") != INVESTIGATION_SCHEMA:
            raise AdmissionError(
                "structural", "INVALID_CONTRACT", "Investigation fields are incomplete."
            )
        targets = raw["target_sensors"]
        if (
            not isinstance(targets, list)
            or not targets
            or any(not isinstance(item, str) for item in targets)
        ):
            raise AdmissionError("structural", "INVALID_TARGETS", "Target sensors are required.")
        if len(targets) != len(set(targets)):
            raise AdmissionError("structural", "DUPLICATE_TARGET", "Target sensors must be unique.")
        temporal = raw["temporal_scope"]
        if not isinstance(temporal, Mapping) or set(temporal) != {"start", "end"}:
            raise AdmissionError("structural", "INVALID_TIME", "Temporal scope is incomplete.")
        parameters = raw["method_parameters"]
        budget = raw["resource_budget"]
        if not isinstance(parameters, Mapping) or not isinstance(budget, Mapping):
            raise AdmissionError(
                "structural", "INVALID_POLICY", "Method and budget policies are required."
            )
        if raw["numeric_policy"] != NUMERIC_POLICY or raw["output_schema"] != OUTPUT_SCHEMA:
            raise AdmissionError(
                "structural",
                "UNSUPPORTED_POLICY",
                "Numeric or output policy is unsupported.",
            )
        try:
            start = normalize_timestamp(temporal["start"])
            end = normalize_timestamp(temporal["end"])
            normalized_parameters = tuple(
                sorted((str(key), int(value)) for key, value in parameters.items())
            )
            normalized_budget = tuple(
                sorted((str(key), int(value)) for key, value in budget.items())
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AdmissionError(
                "structural", "INVALID_POLICY", "Time, method, or budget values are invalid."
            ) from exc
        declaration = {
            **raw,
            "method_parameters": dict(parameters),
            "resource_budget": dict(budget),
            "target_sensors": sorted(targets),
            "temporal_scope": {"end": end, "start": start},
        }
        identity = str(identity_for("investigation", INVESTIGATION_SCHEMA, declaration))
        return Investigation(
            identity=identity,
            state_identity=str(raw["state_identity"]),
            target_sensors=tuple(sorted(targets)),
            variable_id=str(raw["variable_id"]),
            unit=str(raw["unit"]),
            start=start,
            end=end,
            method=str(raw["method"]),
            method_parameters=normalized_parameters,
            missing_policy=str(raw["missing_policy"]),
            resource_budget=normalized_budget,
        )

    def verify(self, raw: Mapping[str, Any]) -> tuple[Investigation, ReconstructedState]:
        investigation = self._structure(raw)
        try:
            state = self.state_loader(investigation.state_identity)
            verify_state(state)
        except Exception as exc:
            raise AdmissionError(
                "state", "STATE_UNAVAILABLE", "Verified state is unavailable."
            ) from exc
        sensors = {item.sensor_id for item in state.entities}
        variables = {(item.variable_id, item.unit) for item in state.observations}
        if not set(investigation.target_sensors) <= sensors:
            raise AdmissionError("semantic", "UNKNOWN_TARGET", "A target is absent from the state.")
        if (investigation.variable_id, investigation.unit) not in variables:
            raise AdmissionError(
                "semantic", "UNKNOWN_VARIABLE", "Variable and unit are incompatible."
            )
        if investigation.start > investigation.end:
            raise AdmissionError(
                "semantic", "INVALID_WINDOW", "Temporal start must not exceed end."
            )
        if investigation.method not in SUPPORTED_METHODS:
            raise AdmissionError("method", "UNSUPPORTED_METHOD", "Method version is unsupported.")
        parameters = dict(investigation.method_parameters)
        if investigation.method == TIME_WINDOW_METHOD and parameters:
            raise AdmissionError(
                "method", "UNEXPECTED_PARAMETERS", "Time-window mean takes no parameters."
            )
        if investigation.method == NEIGHBOR_METHOD and parameters != {"max_hops": 1}:
            raise AdmissionError("method", "INVALID_PARAMETERS", "Graph mean requires max_hops=1.")
        if investigation.missing_policy not in {"exclude", "propagate"}:
            raise AdmissionError(
                "method",
                "INVALID_MISSING_POLICY",
                "Missing-data policy is unsupported.",
            )
        budget = dict(investigation.resource_budget)
        if set(budget) != {"max_records", "max_targets"}:
            raise AdmissionError("resource", "INCOMPLETE_BUDGET", "Resource budget is incomplete.")
        if (
            not 1 <= budget["max_targets"] <= MAX_TARGETS
            or len(investigation.target_sensors) > budget["max_targets"]
        ):
            raise AdmissionError("resource", "TARGET_BUDGET", "Target budget is exceeded.")
        selected = [
            item
            for item in state.observations
            if item.sensor_id in investigation.target_sensors
            and investigation.start <= item.timestamp <= investigation.end
        ]
        if (
            not 1 <= budget["max_records"] <= MAX_SELECTED_RECORDS
            or len(selected) > budget["max_records"]
        ):
            raise AdmissionError("resource", "RECORD_BUDGET", "Record budget is exceeded.")
        return investigation, state

    def admit(self, raw: Mapping[str, Any]) -> tuple[Admission, ReconstructedState]:
        investigation, state = self.verify(raw)
        computation_payload = {
            "investigation_identity": investigation.identity,
            "method": investigation.method,
            "numeric_policy": NUMERIC_POLICY,
            "state_identity": state.identity,
        }
        computation_identity = str(
            identity_for("computation", "mydjangocs.computation/1", computation_payload)
        )
        admission_payload = {
            "authorization_state": "admitted",
            "computation_identity": computation_identity,
            "investigation_identity": investigation.identity,
            "schema_version": ADMISSION_SCHEMA,
            "state_identity": state.identity,
        }
        admission = Admission(
            identity=str(identity_for("admission", ADMISSION_SCHEMA, admission_payload)),
            investigation_identity=investigation.identity,
            state_identity=state.identity,
            computation_identity=computation_identity,
            declaration=investigation.declaration(include_identity=True),
        )
        return admission, state
