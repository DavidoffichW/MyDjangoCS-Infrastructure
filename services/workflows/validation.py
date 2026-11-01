"""Canonical workflow snapshots and numeric input validation."""

import hashlib
from decimal import Decimal
from typing import Any

from foundation.contracts.canonical import canonical_bytes
from workflows.models import Workflow

from .contracts import (
    COMMAND_VERSION,
    MAX_ABS_INPUT_VALUE,
    MAX_INPUT_DECIMAL_PLACES,
    MAX_INPUT_VALUES,
    MAX_STEPS,
    WorkflowValidationError,
)


def canonical_decimal(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_bytes(value)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def workflow_snapshot(workflow: Workflow) -> dict[str, Any]:
    current_revision = Workflow.objects.values_list("revision", flat=True).get(pk=workflow.pk)
    steps = list(workflow.steps.all())
    if not steps:
        raise WorkflowValidationError("Add at least one operation before admission.")
    if len(steps) > MAX_STEPS:
        raise WorkflowValidationError(f"A workflow may contain at most {MAX_STEPS} operations.")
    if [step.position for step in steps] != list(range(1, len(steps) + 1)):
        raise WorkflowValidationError("Step positions must be contiguous and start at one.")
    serialized_steps = [
        {
            "operation": step.operation,
            "parameter": canonical_decimal(step.parameter) if step.parameter is not None else None,
            "position": step.position,
        }
        for step in steps
    ]
    return {
        "command_version": COMMAND_VERSION,
        "steps": serialized_steps,
        "workflow_revision": current_revision,
    }


def validate_input_values(values: list[Decimal]) -> None:
    if not values:
        raise WorkflowValidationError("Enter at least one numerical value.")
    if len(values) > MAX_INPUT_VALUES:
        raise WorkflowValidationError(f"At most {MAX_INPUT_VALUES} values are allowed.")
    for value in values:
        if not value.is_finite():
            raise WorkflowValidationError("NaN and infinite values are not allowed.")
        if abs(value) > MAX_ABS_INPUT_VALUE:
            raise WorkflowValidationError(
                f"Values must be between {-MAX_ABS_INPUT_VALUE} and {MAX_ABS_INPUT_VALUE}."
            )
        if value.as_tuple().exponent < -MAX_INPUT_DECIMAL_PLACES:
            raise WorkflowValidationError(
                f"Values may use at most {MAX_INPUT_DECIMAL_PLACES} decimal places."
            )


def validate_workflow(workflow: Workflow, values: list[Decimal]) -> dict[str, Any]:
    validate_input_values(values)
    snapshot = workflow_snapshot(workflow)
    canonical_values = [canonical_decimal(value) for value in values]
    return {
        "input_digest": digest({"snapshot": snapshot, "values": canonical_values}),
        "snapshot": snapshot,
        "values": canonical_values,
    }
