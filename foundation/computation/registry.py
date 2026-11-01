"""Explicit method registry and declaration dispatch."""

from typing import Any

from foundation.contracts.errors import ComputationError
from foundation.reconstruction.records import ReconstructedState

from .graph_neighborhood import NEIGHBOR_METHOD, graph_neighborhood_mean
from .time_window import TIME_WINDOW_METHOD, time_window_mean

SUPPORTED_METHODS = {TIME_WINDOW_METHOD, NEIGHBOR_METHOD}


def execute_method(state: ReconstructedState, declaration: dict[str, Any]) -> dict[str, Any]:
    common = {
        "state": state,
        "variable_id": declaration["variable_id"],
        "unit": declaration["unit"],
        "start": declaration["temporal_scope"]["start"],
        "end": declaration["temporal_scope"]["end"],
        "missing_policy": declaration["missing_policy"],
    }
    if declaration["method"] == TIME_WINDOW_METHOD:
        return time_window_mean(**common, target_sensors=tuple(declaration["target_sensors"]))
    if declaration["method"] == NEIGHBOR_METHOD:
        return graph_neighborhood_mean(
            **common,
            target_sensor=declaration["target_sensors"][0],
            max_hops=declaration["method_parameters"]["max_hops"],
        )
    raise ComputationError("Unsupported deterministic method.")
