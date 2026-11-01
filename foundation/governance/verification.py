"""Semantic, method, and resource verification stages."""

from foundation.computation import NEIGHBOR_METHOD, SUPPORTED_METHODS, TIME_WINDOW_METHOD
from foundation.contracts.errors import AdmissionError
from foundation.reconstruction import ReconstructedState

from .contracts import Investigation

MAX_TARGETS = 100
MAX_SELECTED_RECORDS = 5_000


def verify_investigation(investigation: Investigation, state: ReconstructedState) -> None:
    sensors = {item.sensor_id for item in state.entities}
    variables = {(item.variable_id, item.unit) for item in state.observations}
    if not set(investigation.target_sensors) <= sensors:
        raise AdmissionError("semantic", "UNKNOWN_TARGET", "A target is absent from the state.")
    if (investigation.variable_id, investigation.unit) not in variables:
        raise AdmissionError("semantic", "UNKNOWN_VARIABLE", "Variable and unit are incompatible.")
    if investigation.start > investigation.end:
        raise AdmissionError("semantic", "INVALID_WINDOW", "Temporal start must not exceed end.")
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
            "method", "INVALID_MISSING_POLICY", "Missing-data policy is unsupported."
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
