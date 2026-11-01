"""Fenced scientific claims, execution, and explicit interruption."""

import os
import secrets
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from foundation.contracts.errors import ArtifactError, FoundationError
from foundation.contracts.identities import identity_for
from foundation.governance import Admission
from infrastructure.orchestration.errors import InvalidTransition
from infrastructure.orchestration.events import record_transition
from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from workflows.models import AdmissionRecord, ExecutionAttempt, Job

from .artifacts import load_state_by_identity
from .composition import foundation_api
from .contracts import ScientificClaim
from .results import fail_scientific_job, finalize_scientific_result


def claim_scientific_job(job_id: UUID) -> ScientificClaim:
    def claim() -> ScientificClaim:
        with authoritative_write():
            current = Job.objects.select_related("admission").get(pk=job_id)
            if current.admission_id is None or current.state != Job.State.ADMITTED:
                raise InvalidTransition("Scientific job is not available for claim.")
            owner_token = secrets.token_hex(24)
            generation = current.claim_generation + 1
            attempt_number = current.attempts + 1
            attempt_identity = str(
                identity_for(
                    "execution-attempt",
                    "mydjangocs.execution-attempt/1",
                    {
                        "claim_generation": generation,
                        "job_id": str(current.id),
                        "owner_token": owner_token,
                    },
                )
            )
            updated = Job.objects.filter(
                pk=current.pk,
                state=Job.State.ADMITTED,
                claim_generation=current.claim_generation,
                revision=current.revision,
            ).update(
                state=Job.State.RUNNING,
                attempts=attempt_number,
                claim_generation=generation,
                owner_token=owner_token,
                revision=F("revision") + 1,
                failure_code="",
                failure_message="",
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise InvalidTransition("Scientific job claim lost its authoritative race.")
            job = Job.objects.get(pk=current.pk)
            ExecutionAttempt.objects.create(
                job=job,
                number=attempt_number,
                state=Job.State.RUNNING,
                evidence={
                    "admission_identity": current.admission_id,
                    "computation_identity": current.admission.computation_identity,
                },
                attempt_identity=attempt_identity,
                claim_generation=generation,
                owner_token=owner_token,
                heartbeat_at=timezone.now(),
            )
            record_transition(job, Job.State.ADMITTED, "fenced scientific worker claimed job")
        return ScientificClaim(
            current.id, attempt_number, generation, owner_token, attempt_identity
        )

    return retry_sqlite_busy(claim)


def admission_from_record(record: AdmissionRecord) -> Admission:
    return Admission(
        identity=record.identity,
        investigation_identity=record.investigation.identity,
        state_identity=record.state_identity,
        computation_identity=record.computation_identity,
        declaration=record.declaration,
        authorization_state=record.authorization_state,
    )


def execute_scientific_job(job_id: UUID) -> Job:
    claim = claim_scientific_job(job_id)
    job = Job.objects.select_related("admission__investigation").get(pk=job_id)
    try:
        state = load_state_by_identity(job.admission.state_identity)
        if os.environ.get("LAB_CRASH_POINT") == "before_result_publication":
            os._exit(89)
        result = foundation_api().execute(admission_from_record(job.admission), state)
        if os.environ.get("LAB_CRASH_POINT") == "after_artifact_publication":
            os._exit(91)
        finalized = finalize_scientific_result(claim, result)
        if os.environ.get("LAB_CRASH_POINT") == "after_result_commit":
            os._exit(93)
        return finalized
    except (FoundationError, ArtifactError) as exc:
        return fail_scientific_job(claim, "FOUNDATION_REJECTED", str(exc))
    except InvalidTransition:
        raise
    except Exception:
        return fail_scientific_job(
            claim, "EXECUTION_ERROR", "Scientific execution failed unexpectedly."
        )


def interrupt_scientific_job(
    job_id: UUID, *, owner_token: str, confirmed_worker_stopped: bool
) -> Job:
    if not confirmed_worker_stopped:
        raise InvalidTransition("Recovery requires explicit confirmation that the worker stopped.")

    def interrupt() -> Job:
        with authoritative_write():
            current = Job.objects.get(pk=job_id)
            if current.state != Job.State.RUNNING or current.owner_token != owner_token:
                raise InvalidTransition("Attempt ownership changed before recovery.")
            updated = Job.objects.filter(
                pk=job_id,
                state=Job.State.RUNNING,
                owner_token=owner_token,
                claim_generation=current.claim_generation,
            ).update(
                state=Job.State.INTERRUPTED,
                revision=F("revision") + 1,
                failure_code="INTERRUPTED",
                failure_message="Owner-confirmed worker termination interrupted execution.",
                owner_token="",
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise InvalidTransition("Recovery lost attempt ownership.")
            job = Job.objects.get(pk=job_id)
            attempt = ExecutionAttempt.objects.get(job=job, number=job.attempts)
            attempt.state = Job.State.INTERRUPTED
            attempt.finished_at = timezone.now()
            attempt.evidence = {**attempt.evidence, "failure_code": "INTERRUPTED"}
            attempt.save(update_fields=["state", "finished_at", "evidence"])
            record_transition(job, Job.State.RUNNING, "owner-confirmed worker interruption")
            if os.environ.get("LAB_CRASH_POINT") == "during_scientific_recovery":
                os._exit(94)
        return job

    return retry_sqlite_busy(interrupt)
