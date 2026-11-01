"""Deterministic execution of admitted workflow command snapshots."""

from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID

from infrastructure.orchestration.claims import claim_job, claim_next_job
from infrastructure.orchestration.finalization import finish_workflow_job
from workflows.models import Job, WorkflowStep

from .contracts import (
    EXECUTION_PRECISION,
    EXECUTION_ROUNDING,
    InjectedOperationFailure,
    WorkflowValidationError,
)
from .validation import canonical_decimal, digest


def run_operations(job: Job, attempt_number: int) -> dict[str, Any]:
    values = [Decimal(value) for value in job.input_values]
    summary: dict[str, Any] | None = None
    evidence = []
    with localcontext() as context:
        context.prec = EXECUTION_PRECISION
        context.rounding = EXECUTION_ROUNDING
        for step in job.workflow_snapshot["steps"]:
            operation = step["operation"]
            parameter = Decimal(step["parameter"]) if step["parameter"] is not None else None
            if operation == WorkflowStep.Operation.VALIDATE_NONNEGATIVE:
                if any(value < 0 for value in values):
                    raise WorkflowValidationError("A value failed the non-negative check.")
            elif operation == WorkflowStep.Operation.SCALE:
                values = [value * parameter for value in values]
            elif operation == WorkflowStep.Operation.OFFSET:
                values = [value + parameter for value in values]
            elif operation == WorkflowStep.Operation.SUMMARIZE:
                total = sum(values, Decimal(0))
                summary = {
                    "count": len(values),
                    "mean": canonical_decimal(total / len(values)),
                    "sum": canonical_decimal(total),
                }
            elif operation == WorkflowStep.Operation.FAIL_ONCE:
                if attempt_number == 1:
                    raise InjectedOperationFailure(
                        "The controlled first-attempt failure was triggered."
                    )
            else:
                raise WorkflowValidationError(f"Unsupported operation: {operation}")
            evidence.append(
                {
                    "operation": operation,
                    "output_digest": digest([canonical_decimal(value) for value in values]),
                    "position": step["position"],
                }
            )
    return {
        "evidence": evidence,
        "summary": summary,
        "values": [canonical_decimal(value) for value in values],
    }


def _run_claimed(job: Job, attempt_number: int) -> Job:
    try:
        result = run_operations(job, attempt_number)
    except InjectedOperationFailure as exc:
        return finish_workflow_job(
            job.id, attempt_number, failure_code="INJECTED_FAILURE", failure_message=str(exc)
        )
    except WorkflowValidationError as exc:
        return finish_workflow_job(
            job.id, attempt_number, failure_code="OPERATION_REJECTED", failure_message=str(exc)
        )
    except Exception:
        return finish_workflow_job(
            job.id,
            attempt_number,
            failure_code="EXECUTION_ERROR",
            failure_message="The operation failed unexpectedly.",
        )
    return finish_workflow_job(job.id, attempt_number, result=result)


def execute_job(job_id: UUID) -> Job:
    claimed_id, attempt_number = claim_job(job_id)
    return _run_claimed(Job.objects.get(pk=claimed_id), attempt_number)


def execute_next_job() -> Job | None:
    next_job = Job.objects.filter(state=Job.State.ADMITTED).order_by("created_at", "id").first()
    if next_job is None:
        return None
    if next_job.admission_id:
        from services.scientific.jobs import execute_scientific_job

        return execute_scientific_job(next_job.id)
    claimed = claim_next_job()
    if not claimed:
        return None
    job_id, attempt_number = claimed
    return _run_claimed(Job.objects.get(pk=job_id), attempt_number)
