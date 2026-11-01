"""Fenced result finalization and verified read representations."""

from typing import Any

from django.db.models import F
from django.utils import timezone

from foundation import ExecutionResult
from foundation.contracts.canonical import canonical_bytes, parse_json_strict
from foundation.contracts.identities import identity_for
from infrastructure.orchestration.errors import InvalidTransition
from infrastructure.orchestration.events import record_transition
from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from workflows.models import ArtifactRecord, ExecutionAttempt, Job

from .artifacts import artifact_reference, register_artifact
from .composition import foundation_api
from .contracts import ScientificClaim


def finalize_scientific_result(claim: ScientificClaim, result: ExecutionResult) -> Job:
    def finalize() -> Job:
        with authoritative_write():
            artifact = register_artifact(
                result.artifact, metadata={"result_identity": result.identity}
            )
            updated = Job.objects.filter(
                pk=claim.job_id,
                state=Job.State.RUNNING,
                attempts=claim.attempt_number,
                claim_generation=claim.claim_generation,
                owner_token=claim.owner_token,
            ).update(
                state=Job.State.SUCCEEDED,
                revision=F("revision") + 1,
                result={**result.payload, "identity": result.identity},
                result_digest=artifact.payload_digest,
                result_artifact_identity=artifact.identity,
                owner_token="",
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise InvalidTransition("Stale scientific attempt cannot finalize this job.")
            job = Job.objects.get(pk=claim.job_id)
            attempt = ExecutionAttempt.objects.get(
                job=job, number=claim.attempt_number, owner_token=claim.owner_token
            )
            if attempt.state != Job.State.RUNNING or attempt.finished_at is not None:
                raise InvalidTransition("Scientific attempt is already terminal.")
            attempt.state = Job.State.SUCCEEDED
            attempt.finished_at = timezone.now()
            attempt.evidence = {
                **attempt.evidence,
                "result_artifact_identity": artifact.identity,
                "result_identity": result.identity,
            }
            attempt.save(update_fields=["state", "finished_at", "evidence"])
            record_transition(job, Job.State.RUNNING, "verified result artifact committed")
        return job

    return retry_sqlite_busy(finalize)


def fail_scientific_job(claim: ScientificClaim, code: str, message: str) -> Job:
    def fail() -> Job:
        with authoritative_write():
            updated = Job.objects.filter(
                pk=claim.job_id,
                state=Job.State.RUNNING,
                attempts=claim.attempt_number,
                claim_generation=claim.claim_generation,
                owner_token=claim.owner_token,
            ).update(
                state=Job.State.FAILED,
                revision=F("revision") + 1,
                failure_code=code,
                failure_message=message[:240],
                owner_token="",
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise InvalidTransition("Stale scientific attempt cannot fail this job.")
            job = Job.objects.get(pk=claim.job_id)
            attempt = ExecutionAttempt.objects.get(job=job, number=claim.attempt_number)
            attempt.state = Job.State.FAILED
            attempt.finished_at = timezone.now()
            attempt.evidence = {**attempt.evidence, "failure_code": code}
            attempt.save(update_fields=["state", "finished_at", "evidence"])
            record_transition(job, Job.State.RUNNING, "scientific execution failed closed")
        return job

    return retry_sqlite_busy(fail)


def result_cache_identity(job: Job, variant: str) -> str:
    if job.state != Job.State.SUCCEEDED or not job.result_artifact_identity:
        raise InvalidTransition("Verified scientific result is not available for caching.")
    return str(
        identity_for(
            "http-result",
            "mydjangocs.http-result/1",
            {
                "job_id": str(job.id),
                "representation": variant,
                "result_artifact_identity": job.result_artifact_identity,
            },
        )
    )


def verify_scientific_result(job: Job) -> dict[str, Any]:
    if job.state != Job.State.SUCCEEDED or not job.result_artifact_identity:
        raise InvalidTransition("Verified scientific result is not available.")
    try:
        record = ArtifactRecord.objects.get(pk=job.result_artifact_identity)
    except ArtifactRecord.DoesNotExist as exc:
        raise InvalidTransition("Result artifact registration is missing.") from exc
    if record.state != ArtifactRecord.State.REGISTERED:
        raise InvalidTransition("Result artifact is not in a verified state.")
    payload = parse_json_strict(foundation_api().store.load(artifact_reference(record)))
    if payload.get("identity") != job.result.get("identity"):
        raise InvalidTransition("Result artifact and job identity disagree.")
    return payload


def publication_payload(result: ExecutionResult) -> bytes:
    return canonical_bytes({**result.payload, "identity": result.identity})
