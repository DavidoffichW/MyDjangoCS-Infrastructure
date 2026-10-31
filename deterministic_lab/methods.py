"""Small deterministic numerical methods with explicit scientific policies."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from .canonical import canonical_decimal
from .errors import ComputationError
from .reconstruction import ReconstructedState

NUMERIC_POLICY = {
    "decimal_precision": 28,
    "output_scale": 6,
    "rounding": "ROUND_HALF_EVEN",
    "version": "mydjangocs.numeric-policy/1",
}
TIME_WINDOW_METHOD = "time-window-mean/1"
NEIGHBOR_METHOD = "graph-neighborhood-mean/1"
SUPPORTED_METHODS = {TIME_WINDOW_METHOD, NEIGHBOR_METHOD}


def _render(value: Decimal) -> str:
    quantum = Decimal(1).scaleb(-NUMERIC_POLICY["output_scale"])
    return canonical_decimal(value.quantize(quantum, rounding=ROUND_HALF_EVEN))


def _selected(
    state: ReconstructedState,
    *,
    sensor_ids: set[str],
    variable_id: str,
    unit: str,
    start: str,
    end: str,
) -> list:
    return [
        item
        for item in state.observations
        if item.sensor_id in sensor_ids
        and item.variable_id == variable_id
        and item.unit == unit
        and start <= item.timestamp <= end
    ]


def time_window_mean(
    state: ReconstructedState,
    *,
    target_sensors: tuple[str, ...],
    variable_id: str,
    unit: str,
    start: str,
    end: str,
    missing_policy: str,
) -> dict[str, Any]:
    if missing_policy not in {"exclude", "propagate"}:
        raise ComputationError("Unsupported missing-data policy.")
    selected = _selected(
        state,
        sensor_ids=set(target_sensors),
        variable_id=variable_id,
        unit=unit,
        start=start,
        end=end,
    )
    if not selected:
        raise ComputationError("Investigation selected no observations.")
    outputs = []
    with localcontext() as context:
        context.prec = NUMERIC_POLICY["decimal_precision"]
        context.rounding = ROUND_HALF_EVEN
        for sensor_id in sorted(target_sensors):
            sensor_rows = [item for item in selected if item.sensor_id == sensor_id]
            missing_count = sum(item.missing for item in sensor_rows)
            values = [Decimal(item.value) for item in sensor_rows if item.value is not None]
            value = None
            if values and not (missing_policy == "propagate" and missing_count):
                value = _render(sum(values, Decimal(0)) / len(values))
            outputs.append(
                {
                    "available_count": len(values),
                    "missing_count": missing_count,
                    "sensor_id": sensor_id,
                    "value": value,
                }
            )
    return {
        "method": TIME_WINDOW_METHOD,
        "missing_policy": missing_policy,
        "numeric_policy": NUMERIC_POLICY,
        "results": outputs,
        "unit": unit,
        "variable_id": variable_id,
        "window": {"end": end, "start": start},
    }


def graph_neighborhood_mean(
    state: ReconstructedState,
    *,
    target_sensor: str,
    variable_id: str,
    unit: str,
    start: str,
    end: str,
    missing_policy: str,
    max_hops: int,
) -> dict[str, Any]:
    if max_hops != 1:
        raise ComputationError("Method version 1 supports exactly one graph hop.")
    if missing_policy not in {"exclude", "propagate"}:
        raise ComputationError("Unsupported missing-data policy.")
    entity_by_sensor = {item.sensor_id: item.identity for item in state.entities}
    if target_sensor not in entity_by_sensor:
        raise ComputationError("Target sensor does not exist in the state.")
    target_entity = entity_by_sensor[target_sensor]
    sensor_by_entity = {identity: sensor for sensor, identity in entity_by_sensor.items()}
    weights = {target_sensor: Decimal(1)}
    for edge in state.edges:
        if edge.source_entity == target_entity:
            weights[sensor_by_entity[edge.target_entity]] = Decimal(edge.weight)
        elif edge.target_entity == target_entity:
            weights[sensor_by_entity[edge.source_entity]] = Decimal(edge.weight)
    selected = _selected(
        state,
        sensor_ids=set(weights),
        variable_id=variable_id,
        unit=unit,
        start=start,
        end=end,
    )
    missing_count = sum(item.missing for item in selected)
    weighted: list[tuple[Decimal, Decimal]] = [
        (Decimal(item.value), weights[item.sensor_id])
        for item in selected
        if item.value is not None
    ]
    value = None
    with localcontext() as context:
        context.prec = NUMERIC_POLICY["decimal_precision"]
        context.rounding = ROUND_HALF_EVEN
        if weighted and not (missing_policy == "propagate" and missing_count):
            numerator = sum((item * weight for item, weight in weighted), Decimal(0))
            denominator = sum((weight for _, weight in weighted), Decimal(0))
            value = _render(numerator / denominator)
    return {
        "available_count": len(weighted),
        "max_hops": max_hops,
        "method": NEIGHBOR_METHOD,
        "missing_count": missing_count,
        "missing_policy": missing_policy,
        "numeric_policy": NUMERIC_POLICY,
        "target_sensor": target_sensor,
        "unit": unit,
        "value": value,
        "variable_id": variable_id,
        "weights": {key: canonical_decimal(weights[key]) for key in sorted(weights)},
        "window": {"end": end, "start": start},
    }


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
        return time_window_mean(
            **common,
            target_sensors=tuple(declaration["target_sensors"]),
        )
    if declaration["method"] == NEIGHBOR_METHOD:
        return graph_neighborhood_mean(
            **common,
            target_sensor=declaration["target_sensors"][0],
            max_hops=declaration["method_parameters"]["max_hops"],
        )
    raise ComputationError("Unsupported deterministic method.")
