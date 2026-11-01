"""Shared bounded observation selection for declared computations."""

from foundation.reconstruction.records import ReconstructedState


def select_observations(
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
