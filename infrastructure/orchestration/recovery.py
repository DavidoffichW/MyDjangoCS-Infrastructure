"""Explicit retry admission and operator-confirmed interruption recovery."""

from datetime import timedelta
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from workflows.models import Job

from .errors import InvalidTransition
from .events import record_transition

_ALLOWED_TRANSITIONS = {
    Job.State.ADMITTED: {Job.State.RUNNING},
    Job.State.RUNNING: {Job.State.SUCCEEDED, Job.State.FAILED, Job.State.INTERRUPTED},
    Job.State.FAILED: {Job.State.ADMITTED},
    Job.State.INTERRUPTED: {Job.State.ADMITTED},
    Job.State.SUCCEEDED: set(),
}


def requeue_job(job_id: UUID) -> Job:
    def requeue_once() -> Job:
        with authoritative_write():
            current = Job.objects.get(pk=job_id)
            if Job.State.ADMITTED not in _ALLOWED_TRANSITIONS.get(current.state, set()):
                raise InvalidTransition(
                    f"Cannot transition a job from {current.state} to admitted."
                )
            previous = current.state
            updated = Job.objects.filter(
                pk=job_id, state=previous, revision=current.revision
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
            record_transition(job, previous, "operator requested controlled retry")
        return job

    return retry_sqlite_busy(requeue_once)


def recover_stale_jobs(
    max_age_seconds: int, *, confirmed_worker_stopped: bool = False
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
            with authoritative_write():
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
                record_transition(
                    job, Job.State.RUNNING, "stale running attempt recovered after interruption"
                )
            return True

        if retry_sqlite_busy(recover_once):
            recovered.append(job_id)
    return recovered
