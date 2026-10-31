from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from threading import RLock
from typing import Any
from uuid import UUID

from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import ExecutionAttempt, Job, JobEvent, Workflow, WorkflowStep

COMMAND_VERSION = "reliability-lab.command/1"
MAX_STEPS = 20
MAX_INPUT_VALUES = 100
MAX_ABS_INPUT_VALUE = Decimal("1000000000")
MAX_INPUT_DECIMAL_PLACES = 18
EXECUTION_PRECISION = 28
EXECUTION_ROUNDING = ROUND_HALF_EVEN
SQLITE_BUSY_RETRIES = 20
SQLITE_BUSY_DELAY_SECONDS = 0.01
_SQLITE_WRITE_LOCK = RLock()


class WorkflowValidationError(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


class DatabaseBusy(RuntimeError):
    pass


class InjectedOperationFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class AdmissionResult:
    job: Job
    duplicate: bool


def _retry_sqlite_busy(operation):
    for retry in range(SQLITE_BUSY_RETRIES + 1):
        try:
            return operation()
        except OperationalError as exc:
            is_busy = connection.vendor == "sqlite" and "locked" in str(exc).lower()
            if not is_busy:
                raise
            if retry == SQLITE_BUSY_RETRIES:
                raise DatabaseBusy(
                    "SQLite could not acquire its bounded authoritative write window."
                ) from exc
            time.sleep(SQLITE_BUSY_DELAY_SECONDS * (retry + 1))


@contextmanager
def _authoritative_write():
    """Serialize short SQLite writes without making every request an eager writer."""
    if connection.vendor != "sqlite":
        with transaction.atomic():
            yield
        return

    with _SQLITE_WRITE_LOCK:
        if connection.in_atomic_block:
            with transaction.atomic():
                yield
            return
        with connection.cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()


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
    current_revision = Workflow.objects.values_list("revision", flat=True).get(pk=workflow.pk)
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
    if not idempotency_key or len(idempotency_key) > 100:
        raise WorkflowValidationError("The idempotency key must contain 1 to 100 characters.")
    validated = validate_workflow(workflow, values)

    def admit_once() -> AdmissionResult:
        try:
            with _authoritative_write():
                existing = _find_existing(idempotency_key, validated["input_digest"])
                if existing:
                    return existing
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

    return _retry_sqlite_busy(admit_once)


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


def _record_transition(job: Job, previous: str, reason: str) -> None:
    JobEvent.objects.create(
        job=job,
        sequence=job.revision + 1,
        from_state=previous,
        to_state=job.state,
        reason=reason,
    )


def claim_job(job_id: UUID) -> tuple[UUID, int]:
    def claim_once() -> tuple[UUID, int]:
        with _authoritative_write():
            updated = Job.objects.filter(pk=job_id, state=Job.State.ADMITTED).update(
                state=Job.State.RUNNING,
                attempts=F("attempts") + 1,
                revision=F("revision") + 1,
                failure_code="",
                failure_message="",
                updated_at=timezone.now(),
            )
            if updated != 1:
                state = Job.objects.filter(pk=job_id).values_list("state", flat=True).first()
                if state is None:
                    raise Job.DoesNotExist(job_id)
                raise InvalidTransition(f"Cannot transition a job from {state} to running.")
            job = Job.objects.get(pk=job_id)
            attempt_number = job.attempts
            ExecutionAttempt.objects.create(
                job=job,
                number=attempt_number,
                state=Job.State.RUNNING,
                evidence={"input_digest": job.input_digest},
            )
            _record_transition(job, Job.State.ADMITTED, "single worker claimed job")
        return job.id, attempt_number

    return _retry_sqlite_busy(claim_once)


def claim_next_job() -> tuple[UUID, int] | None:
    while True:
        next_id = (
            Job.objects.filter(state=Job.State.ADMITTED)
            .order_by("created_at", "id")
            .values_list("id", flat=True)
            .first()
        )
        if next_id is None:
            return None
        try:
            return claim_job(next_id)
        except InvalidTransition:
            continue


def _run_operations(job: Job, attempt_number: int) -> dict[str, Any]:
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


def _finish_job(
    job_id: UUID,
    attempt_number: int,
    *,
    result: dict[str, Any] | None = None,
    failure_code: str = "",
    failure_message: str = "",
) -> Job:
    result_hash = digest(result) if result is not None else ""

    def finish_once() -> Job:
        with _authoritative_write():
            target = Job.State.SUCCEEDED if result is not None else Job.State.FAILED
            updates = {
                "state": target,
                "revision": F("revision") + 1,
                "updated_at": timezone.now(),
                "result": result,
                "result_digest": result_hash,
                "failure_code": "" if result is not None else failure_code,
                "failure_message": "" if result is not None else failure_message[:240],
            }
            updated = Job.objects.filter(
                pk=job_id,
                state=Job.State.RUNNING,
                attempts=attempt_number,
            ).update(**updates)
            if updated != 1:
                raise InvalidTransition("The execution attempt is no longer authoritative.")
            job = Job.objects.get(pk=job_id)
            attempt = ExecutionAttempt.objects.get(job=job, number=attempt_number)
            if attempt.state != Job.State.RUNNING or attempt.finished_at is not None:
                raise InvalidTransition("The execution attempt is already complete.")
            attempt.state = target
            attempt.finished_at = timezone.now()
            if result is not None:
                attempt.evidence = {**attempt.evidence, "result_digest": result_hash}
            else:
                attempt.evidence = {**attempt.evidence, "failure_code": failure_code}
            attempt.save(update_fields=["state", "evidence", "finished_at"])
            _record_transition(
                job,
                Job.State.RUNNING,
                "deterministic execution completed" if result is not None else "execution failed",
            )
        return job

    return _retry_sqlite_busy(finish_once)


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
    next_job = Job.objects.filter(state=Job.State.ADMITTED).order_by("created_at", "id").first()
    if next_job is None:
        return None
    if next_job.admission_id:
        from .scientific_services import execute_scientific_job

        return execute_scientific_job(next_job.id)
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
    def requeue_once() -> Job:
        with _authoritative_write():
            current = Job.objects.get(pk=job_id)
            if Job.State.ADMITTED not in _ALLOWED_TRANSITIONS.get(current.state, set()):
                raise InvalidTransition(
                    f"Cannot transition a job from {current.state} to admitted."
                )
            previous = current.state
            updated = Job.objects.filter(
                pk=job_id,
                state=previous,
                revision=current.revision,
            ).update(
                state=Job.State.ADMITTED,
                revision=F("revision") + 1,
                failure_code="",
                failure_message="",
                owner_token="",
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise InvalidTransition("The job changed before retry admission.")
            job = Job.objects.get(pk=job_id)
            _record_transition(job, previous, "operator requested controlled retry")
        return job

    return _retry_sqlite_busy(requeue_once)


def recover_stale_jobs(
    max_age_seconds: int,
    *,
    confirmed_worker_stopped: bool = False,
) -> list[UUID]:
    if not confirmed_worker_stopped:
        raise InvalidTransition(
            "Age alone does not prove worker termination; explicit confirmation is required."
        )
    cutoff = timezone.now() - timedelta(seconds=max_age_seconds)
    candidate_ids = list(
        Job.objects.filter(state=Job.State.RUNNING, updated_at__lte=cutoff).values_list(
            "id", flat=True
        )
    )
    recovered: list[UUID] = []
    for job_id in candidate_ids:

        def recover_once(target_job_id: UUID = job_id) -> bool:
            with _authoritative_write():
                current = Job.objects.get(pk=target_job_id)
                if current.state != Job.State.RUNNING or current.updated_at > cutoff:
                    return False
                updated = Job.objects.filter(
                    pk=target_job_id,
                    state=Job.State.RUNNING,
                    attempts=current.attempts,
                    revision=current.revision,
                    updated_at__lte=cutoff,
                ).update(
                    state=Job.State.INTERRUPTED,
                    revision=F("revision") + 1,
                    failure_code="INTERRUPTED",
                    failure_message="Execution stopped before a result was committed.",
                    owner_token="",
                    updated_at=timezone.now(),
                )
                if updated != 1:
                    return False
                job = Job.objects.get(pk=target_job_id)
                attempt = job.execution_attempts.get(number=job.attempts)
                if attempt.state != Job.State.RUNNING or attempt.finished_at is not None:
                    raise InvalidTransition("The running attempt cannot be recovered safely.")
                attempt.state = Job.State.INTERRUPTED
                attempt.finished_at = timezone.now()
                attempt.evidence = {**attempt.evidence, "failure_code": "INTERRUPTED"}
                attempt.save(update_fields=["state", "finished_at", "evidence"])
                _record_transition(
                    job,
                    Job.State.RUNNING,
                    "stale running attempt recovered after interruption",
                )
            return True

        if _retry_sqlite_busy(recover_once):
            recovered.append(job_id)
    return recovered
