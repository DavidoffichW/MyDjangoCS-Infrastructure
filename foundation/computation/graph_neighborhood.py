"""Declared deterministic one-hop graph-neighborhood mean."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from foundation.contracts.canonical import canonical_decimal
from foundation.contracts.errors import ComputationError
from foundation.contracts.numeric_policy import NUMERIC_POLICY, render_result_decimal
from foundation.reconstruction.records import ReconstructedState

from .selection import select_observations

NEIGHBOR_METHOD = "graph-neighborhood-mean/1"


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
    selected = select_observations(
        state,
        sensor_ids=set(weights),
        variable_id=variable_id,
        unit=unit,
        start=start,
        end=end,
    )
    missing_count = sum(item.missing for item in selected)
    weighted = [
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
            value = render_result_decimal(numerator / denominator)
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
