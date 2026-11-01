"""Idempotent admission of immutable workflow command snapshots."""

from decimal import Decimal

from django.db import IntegrityError

from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from workflows.models import Job, JobEvent, Workflow

from .contracts import (
    COMMAND_VERSION,
    AdmissionResult,
    IdempotencyConflict,
    WorkflowValidationError,
)
from .validation import validate_workflow


def _find_existing(idempotency_key: str, input_digest: str) -> AdmissionResult | None:
    try:
        existing = Job.objects.get(idempotency_key=idempotency_key)
    except Job.DoesNotExist:
        return None
    if existing.input_digest != input_digest:
        raise IdempotencyConflict("That idempotency key is already bound to different input.")
    return AdmissionResult(existing, duplicate=True)


def admit_job(workflow: Workflow, values: list[Decimal], idempotency_key: str) -> AdmissionResult:
    if not idempotency_key or len(idempotency_key) > 100:
        raise WorkflowValidationError("The idempotency key must contain 1 to 100 characters.")
    validated = validate_workflow(workflow, values)

    def admit_once() -> AdmissionResult:
        try:
            with authoritative_write():
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

    return retry_sqlite_busy(admit_once)
