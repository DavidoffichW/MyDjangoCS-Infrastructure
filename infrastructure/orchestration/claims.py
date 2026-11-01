"""Atomic conditional claims for a single-worker SQLite queue."""

from uuid import UUID

from django.db.models import F
from django.utils import timezone

from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from workflows.models import ExecutionAttempt, Job

from .errors import InvalidTransition
from .events import record_transition


def claim_job(job_id: UUID) -> tuple[UUID, int]:
    def claim_once() -> tuple[UUID, int]:
        with authoritative_write():
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
            ExecutionAttempt.objects.create(
                job=job,
                number=job.attempts,
                state=Job.State.RUNNING,
                evidence={"input_digest": job.input_digest},
            )
            record_transition(job, Job.State.ADMITTED, "single worker claimed job")
        return job.id, job.attempts

    return retry_sqlite_busy(claim_once)


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
