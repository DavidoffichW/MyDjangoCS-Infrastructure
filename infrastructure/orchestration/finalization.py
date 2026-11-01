"""Atomic completion of workflow execution attempts."""

import hashlib
from typing import Any
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from foundation.contracts.canonical import canonical_bytes
from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from workflows.models import ExecutionAttempt, Job

from .errors import InvalidTransition
from .events import record_transition


def finish_workflow_job(
    job_id: UUID,
    attempt_number: int,
    *,
    result: dict[str, Any] | None = None,
    failure_code: str = "",
    failure_message: str = "",
) -> Job:
    result_hash = hashlib.sha256(canonical_bytes(result)).hexdigest() if result is not None else ""

    def finish_once() -> Job:
        with authoritative_write():
            target = Job.State.SUCCEEDED if result is not None else Job.State.FAILED
            updated = Job.objects.filter(
                pk=job_id, state=Job.State.RUNNING, attempts=attempt_number
            ).update(
                state=target,
                revision=F("revision") + 1,
                updated_at=timezone.now(),
                result=result,
                result_digest=result_hash,
                failure_code="" if result is not None else failure_code,
                failure_message="" if result is not None else failure_message[:240],
            )
            if updated != 1:
                raise InvalidTransition("The execution attempt is no longer authoritative.")
            job = Job.objects.get(pk=job_id)
            attempt = ExecutionAttempt.objects.get(job=job, number=attempt_number)
            if attempt.state != Job.State.RUNNING or attempt.finished_at is not None:
                raise InvalidTransition("The execution attempt is already complete.")
            attempt.state = target
            attempt.finished_at = timezone.now()
            attempt.evidence = {
                **attempt.evidence,
                **(
                    {"result_digest": result_hash}
                    if result is not None
                    else {"failure_code": failure_code}
                ),
            }
            attempt.save(update_fields=["state", "evidence", "finished_at"])
            record_transition(
                job,
                Job.State.RUNNING,
                "deterministic execution completed" if result is not None else "execution failed",
            )
        return job

    return retry_sqlite_busy(finish_once)
