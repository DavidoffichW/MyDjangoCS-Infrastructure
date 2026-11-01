"""Structural closure of a raw investigation declaration."""

from collections.abc import Mapping
from typing import Any

from foundation.contracts.canonical import normalize_timestamp
from foundation.contracts.errors import AdmissionError
from foundation.contracts.identities import identity_for
from foundation.contracts.numeric_policy import NUMERIC_POLICY

from .contracts import INVESTIGATION_SCHEMA, OUTPUT_SCHEMA, Investigation


def close_investigation(raw: Mapping[str, Any]) -> Investigation:
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
            "structural", "UNSUPPORTED_POLICY", "Numeric or output policy is unsupported."
        )
    try:
        start = normalize_timestamp(temporal["start"])
        end = normalize_timestamp(temporal["end"])
        normalized_parameters = tuple(
            sorted((str(key), int(value)) for key, value in parameters.items())
        )
        normalized_budget = tuple(sorted((str(key), int(value)) for key, value in budget.items()))
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
    return Investigation(
        identity=str(identity_for("investigation", INVESTIGATION_SCHEMA, declaration)),
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
