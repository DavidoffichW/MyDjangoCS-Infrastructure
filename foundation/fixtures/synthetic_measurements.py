"""Completely fictional deterministic evidence used by the public experiment."""

from __future__ import annotations

from typing import Any

from foundation.schema.evidence import EVIDENCE_SCHEMA, RELATIONSHIP_SCHEMA


def reference_evidence(*, source_id: str = "synthetic_source_a") -> dict[str, Any]:
    sensors = ("sensor_alpha", "sensor_bravo", "sensor_charlie", "sensor_delta")
    periods = (
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        "2026-01-01T02:00:00Z",
        "2026-01-01T03:00:00Z",
    )
    values: dict[tuple[str, str], str | None] = {
        ("sensor_alpha", periods[0]): "10.0",
        ("sensor_alpha", periods[1]): "11.0",
        ("sensor_alpha", periods[2]): "12.0",
        ("sensor_alpha", periods[3]): "13.0",
        ("sensor_bravo", periods[0]): "20.0",
        ("sensor_bravo", periods[1]): "21.0",
        ("sensor_bravo", periods[2]): None,
        ("sensor_bravo", periods[3]): "23.0",
        ("sensor_charlie", periods[0]): "30.0",
        ("sensor_charlie", periods[1]): "31.0",
        ("sensor_charlie", periods[2]): "32.0",
        ("sensor_charlie", periods[3]): "48.0",
        ("sensor_delta", periods[0]): "40.0",
        ("sensor_delta", periods[1]): "41.0",
        ("sensor_delta", periods[2]): "42.0",
        ("sensor_delta", periods[3]): "43.0",
    }
    observations = []
    for sensor in sensors:
        for timestamp in periods:
            value = values[(sensor, timestamp)]
            observations.append(
                {
                    "missing": value is None,
                    "provenance": {
                        "generator": "independent-fictional-corpus",
                        "revision": "1",
                    },
                    "quality": (
                        "missing"
                        if value is None
                        else "anomalous"
                        if sensor == "sensor_charlie" and timestamp == periods[3]
                        else "observed"
                    ),
                    "schema_version": EVIDENCE_SCHEMA,
                    "sensor_id": sensor,
                    "source_id": source_id,
                    "timestamp": timestamp,
                    "unit": "synthetic_unit",
                    "value": value,
                    "variable_id": "signal",
                }
            )
    relationships = [
        ("sensor_alpha", "sensor_bravo", "1"),
        ("sensor_bravo", "sensor_charlie", "0.8"),
        ("sensor_charlie", "sensor_delta", "1"),
        ("sensor_alpha", "sensor_delta", "0.4"),
    ]
    return {
        "observations": observations,
        "relationships": [
            {
                "relationship_type": "linked",
                "schema_version": RELATIONSHIP_SCHEMA,
                "source_sensor": source,
                "target_sensor": target,
                "weight": weight,
            }
            for source, target, weight in relationships
        ],
        "schema_version": "mydjangocs.evidence-bundle/1",
    }


def invalid_evidence_cases() -> dict[str, dict[str, Any]]:
    missing_value = reference_evidence()
    missing_value["observations"][0] = {
        **missing_value["observations"][0],
        "missing": False,
        "value": None,
    }
    dangling = reference_evidence()
    dangling["relationships"][0] = {
        **dangling["relationships"][0],
        "target_sensor": "sensor_unknown",
    }
    wrong_schema = reference_evidence()
    wrong_schema["observations"][0] = {
        **wrong_schema["observations"][0],
        "schema_version": "unsupported/9",
    }
    return {
        "inconsistent_missingness": missing_value,
        "dangling_relationship": dangling,
        "unsupported_schema": wrong_schema,
    }
