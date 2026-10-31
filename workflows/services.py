from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import ExecutionAttempt, Job, JobEvent, Workflow, WorkflowStep

COMMAND_VERSION = "reliability-lab.command/1"
MAX_STEPS = 20


class WorkflowValidationError(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


class InjectedOperationFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class AdmissionResult:
    job: Job
    duplicate: bool


def canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def workflow_snapshot(workflow: Workflow) -> dict[str, Any]:
    steps = list(workflow.steps.all())
    if not steps:
        raise WorkflowValidationError("Add at least one operation before admission.")
    if len(steps) > MAX_STEPS:
        raise WorkflowValidationError(f"A workflow may contain at most {MAX_STEPS} operations.")
    expected_positions = list(range(1, len(steps) + 1))
    if [step.position for step in steps] != expected_positions:
        raise WorkflowValidationError("Step positions must be contiguous and start at one.")

    serialized_steps = []
    for step in steps:
        parameter = canonical_decimal(step.parameter) if step.parameter is not None else None
        serialized_steps.append(
            {
                "operation": step.operation,
                "parameter": parameter,
                "position": step.position,
            }
        )
    return {
        "command_version": COMMAND_VERSION,
        "steps": serialized_steps,
        "workflow_revision": workflow.revision,
    }


def validate_workflow(workflow: Workflow, values: list[Decimal]) -> dict[str, Any]:
    snapshot = workflow_snapshot(workflow)
    canonical_values = [canonical_decimal(value) for value in values]
    return {
        "input_digest": digest({"snapshot": snapshot, "values": canonical_values}),
        "snapshot": snapshot,
        "values": canonical_values,
    }


def _find_existing(idempotency_key: str, input_digest: str) -> AdmissionResult | None:
    try:
        existing = Job.objects.get(idempotency_key=idempotency_key)
    except Job.DoesNotExist:
        return None
    if existing.input_digest != input_digest:
        raise IdempotencyConflict("That idempotency key is already bound to different input.")
    return AdmissionResult(existing, duplicate=True)


def admit_job(
    workflow: Workflow,
    values: list[Decimal],
    idempotency_key: str,
) -> AdmissionResult:
    validated = validate_workflow(workflow, values)
    existing = _find_existing(idempotency_key, validated["input_digest"])
    if existing:
        return existing

    try:
        with transaction.atomic():
            job = Job.objects.create(
                workflow=workflow,
                idempotency_key=idempotency_key,
                command_version=COMMAND_VERSION,
                input_digest=validated["input_digest"],
                workflow_snapshot=validated["snapshot"],
                input_values=validated["values"],
            )
            JobEvent.objects.create(
                job=job,
                sequence=1,
                from_state="",
                to_state=Job.State.ADMITTED,
                reason="validated command admitted",
            )
    except IntegrityError:
        raced = _find_existing(idempotency_key, validated["input_digest"])
        if raced:
            return raced
        raise
    return AdmissionResult(job, duplicate=False)


def add_step(workflow: Workflow, *, operation: str, parameter: Decimal | None) -> WorkflowStep:
    with transaction.atomic():
        locked = Workflow.objects.select_for_update().get(pk=workflow.pk)
        last = locked.steps.aggregate(maximum=Max("position"))["maximum"] or 0
        if last >= MAX_STEPS:
            raise WorkflowValidationError(f"A workflow may contain at most {MAX_STEPS} operations.")
        step = WorkflowStep.objects.create(
            workflow=locked,
            position=last + 1,
            operation=operation,
            parameter=parameter,
        )
        Workflow.objects.filter(pk=locked.pk).update(revision=F("revision") + 1)
    return step


def update_step(step: WorkflowStep, *, operation: str, parameter: Decimal | None) -> None:
    with transaction.atomic():
        locked = WorkflowStep.objects.select_for_update().select_related("workflow").get(pk=step.pk)
        locked.operation = operation
        locked.parameter = parameter
        locked.save(update_fields=["operation", "parameter", "updated_at"])
        Workflow.objects.filter(pk=locked.workflow_id).update(revision=F("revision") + 1)


def remove_step(step: WorkflowStep) -> None:
    with transaction.atomic():
        locked = WorkflowStep.objects.select_for_update().select_related("workflow").get(pk=step.pk)
        workflow_id = locked.workflow_id
        position = locked.position
        locked.delete()
        WorkflowStep.objects.filter(workflow_id=workflow_id, position__gt=position).update(
            position=F("position") - 1
        )
        Workflow.objects.filter(pk=workflow_id).update(revision=F("revision") + 1)


def move_step(step: WorkflowStep, direction: str) -> None:
    delta = -1 if direction == "up" else 1 if direction == "down" else 0
    if not delta:
        raise WorkflowValidationError("Direction must be 'up' or 'down'.")
    with transaction.atomic():
        locked = WorkflowStep.objects.select_for_update().select_related("workflow").get(pk=step.pk)
        target_position = locked.position + delta
        try:
            target = WorkflowStep.objects.select_for_update().get(
                workflow_id=locked.workflow_id,
                position=target_position,
            )
        except WorkflowStep.DoesNotExist:
            return
        original_position = locked.position
        locked.position = 0
        locked.save(update_fields=["position", "updated_at"])
        target.position = original_position
        target.save(update_fields=["position", "updated_at"])
        locked.position = target_position
        locked.save(update_fields=["position", "updated_at"])
        Workflow.objects.filter(pk=locked.workflow_id).update(revision=F("revision") + 1)


_ALLOWED_TRANSITIONS = {
    Job.State.ADMITTED: {Job.State.RUNNING},
    Job.State.RUNNING: {Job.State.SUCCEEDED, Job.State.FAILED, Job.State.INTERRUPTED},
    Job.State.FAILED: {Job.State.ADMITTED},
    Job.State.INTERRUPTED: {Job.State.ADMITTED},
    Job.State.SUCCEEDED: set(),
}


def _transition_locked(job: Job, target: str, reason: str, **updates: Any) -> Job:
    if target not in _ALLOWED_TRANSITIONS.get(job.state, set()):
        raise InvalidTransition(f"Cannot transition a job from {job.state} to {target}.")
    previous = job.state
    job.state = target
    job.revision += 1
    for field, value in updates.items():
        setattr(job, field, value)
    update_fields = ["state", "revision", "updated_at", *updates]
    job.save(update_fields=update_fields)
    sequence = (job.events.aggregate(maximum=Max("sequence"))["maximum"] or 0) + 1
    JobEvent.objects.create(
        job=job,
        sequence=sequence,
        from_state=previous,
        to_state=target,
        reason=reason,
    )
    return job


def claim_job(job_id: UUID) -> tuple[UUID, int]:
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job_id)
        attempt_number = job.attempts + 1
        _transition_locked(
            job,
            Job.State.RUNNING,
            "single worker claimed job",
            attempts=attempt_number,
            failure_code="",
            failure_message="",
        )
        ExecutionAttempt.objects.create(
            job=job,
            number=attempt_number,
            state=Job.State.RUNNING,
            evidence={"input_digest": job.input_digest},
        )
    return job.id, attempt_number


def claim_next_job() -> tuple[UUID, int] | None:
    next_id = (
        Job.objects.filter(state=Job.State.ADMITTED)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
        .first()
    )
    return claim_job(next_id) if next_id else None


def _run_operations(job: Job, attempt_number: int) -> dict[str, Any]:
    values = [Decimal(value) for value in job.input_values]
    summary: dict[str, Any] | None = None
    evidence = []
    with localcontext() as context:
        context.prec = 28
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


def _finish_job(
    job_id: UUID,
    attempt_number: int,
    *,
    result: dict[str, Any] | None = None,
    failure_code: str = "",
    failure_message: str = "",
) -> Job:
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job_id)
        if job.state != Job.State.RUNNING or job.attempts != attempt_number:
            raise InvalidTransition("The execution attempt is no longer authoritative.")
        attempt = ExecutionAttempt.objects.select_for_update().get(
            job=job,
            number=attempt_number,
        )
        if result is not None:
            result_hash = digest(result)
            _transition_locked(
                job,
                Job.State.SUCCEEDED,
                "deterministic execution completed",
                result=result,
                result_digest=result_hash,
            )
            attempt.state = Job.State.SUCCEEDED
            attempt.evidence = {**attempt.evidence, "result_digest": result_hash}
        else:
            _transition_locked(
                job,
                Job.State.FAILED,
                "execution failed",
                failure_code=failure_code,
                failure_message=failure_message[:240],
            )
            attempt.state = Job.State.FAILED
            attempt.evidence = {**attempt.evidence, "failure_code": failure_code}
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=["state", "evidence", "finished_at"])
    return job


def execute_job(job_id: UUID) -> Job:
    claimed_id, attempt_number = claim_job(job_id)
    job = Job.objects.get(pk=claimed_id)
    try:
        result = _run_operations(job, attempt_number)
    except InjectedOperationFailure as exc:
        return _finish_job(
            job.id,
            attempt_number,
            failure_code="INJECTED_FAILURE",
            failure_message=str(exc),
        )
    except WorkflowValidationError as exc:
        return _finish_job(
            job.id,
            attempt_number,
            failure_code="OPERATION_REJECTED",
            failure_message=str(exc),
        )
    except Exception:
        return _finish_job(
            job.id,
            attempt_number,
            failure_code="EXECUTION_ERROR",
            failure_message="The operation failed unexpectedly.",
        )
    return _finish_job(job.id, attempt_number, result=result)


def execute_next_job() -> Job | None:
    claimed = claim_next_job()
    if not claimed:
        return None
    job_id, attempt_number = claimed
    job = Job.objects.get(pk=job_id)
    try:
        result = _run_operations(job, attempt_number)
    except InjectedOperationFailure as exc:
        return _finish_job(
            job.id,
            attempt_number,
            failure_code="INJECTED_FAILURE",
            failure_message=str(exc),
        )
    except WorkflowValidationError as exc:
        return _finish_job(
            job.id,
            attempt_number,
            failure_code="OPERATION_REJECTED",
            failure_message=str(exc),
        )
    except Exception:
        return _finish_job(
            job.id,
            attempt_number,
            failure_code="EXECUTION_ERROR",
            failure_message="The operation failed unexpectedly.",
        )
    return _finish_job(job.id, attempt_number, result=result)


def requeue_job(job_id: UUID) -> Job:
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job_id)
        return _transition_locked(
            job,
            Job.State.ADMITTED,
            "operator requested controlled retry",
            failure_code="",
            failure_message="",
        )


def recover_stale_jobs(max_age_seconds: int) -> list[UUID]:
    cutoff = timezone.now() - timedelta(seconds=max_age_seconds)
    candidate_ids = list(
        Job.objects.filter(state=Job.State.RUNNING, updated_at__lte=cutoff).values_list(
            "id", flat=True
        )
    )
    recovered: list[UUID] = []
    for job_id in candidate_ids:
        with transaction.atomic():
            job = Job.objects.select_for_update().get(pk=job_id)
            if job.state != Job.State.RUNNING or job.updated_at > cutoff:
                continue
            _transition_locked(
                job,
                Job.State.INTERRUPTED,
                "stale running attempt recovered after interruption",
                failure_code="INTERRUPTED",
                failure_message="Execution stopped before a result was committed.",
            )
            attempt = job.execution_attempts.get(number=job.attempts)
            attempt.state = Job.State.INTERRUPTED
            attempt.finished_at = timezone.now()
            attempt.evidence = {**attempt.evidence, "failure_code": "INTERRUPTED"}
            attempt.save(update_fields=["state", "finished_at", "evidence"])
            recovered.append(job.id)
    return recovered
