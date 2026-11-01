"""Declared deterministic time-window mean."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from foundation.contracts.errors import ComputationError
from foundation.contracts.numeric_policy import NUMERIC_POLICY, render_result_decimal
from foundation.reconstruction.records import ReconstructedState

from .selection import select_observations

TIME_WINDOW_METHOD = "time-window-mean/1"


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
    selected = select_observations(
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
                value = render_result_decimal(sum(values, Decimal(0)) / len(values))
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
