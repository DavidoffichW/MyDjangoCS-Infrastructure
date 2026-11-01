"""Ordered durable job transition evidence."""

from workflows.models import Job, JobEvent


def record_transition(job: Job, previous: str, reason: str) -> None:
    JobEvent.objects.create(
        job=job,
        sequence=job.revision + 1,
        from_state=previous,
        to_state=job.state,
        reason=reason,
    )
