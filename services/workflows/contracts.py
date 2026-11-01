"""Workflow command limits, errors, and admission result."""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from workflows.models import Job

COMMAND_VERSION = "reliability-lab.command/1"
MAX_STEPS = 20
MAX_INPUT_VALUES = 100
MAX_ABS_INPUT_VALUE = Decimal("1000000000")
MAX_INPUT_DECIMAL_PLACES = 18
EXECUTION_PRECISION = 28
EXECUTION_ROUNDING = ROUND_HALF_EVEN


class WorkflowValidationError(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


class InjectedOperationFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class AdmissionResult:
    job: Job
    duplicate: bool
