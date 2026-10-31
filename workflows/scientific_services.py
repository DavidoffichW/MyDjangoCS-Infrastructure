"""Django control-plane integration for the deterministic foundation."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError as DatabaseIntegrityError
from django.db.models import F
from django.utils import timezone

from deterministic_lab.api import ExecutionResult, FoundationAPI
from deterministic_lab.canonical import canonical_bytes, parse_json_strict
from deterministic_lab.corpus import reference_evidence
from deterministic_lab.errors import AdmissionError, ArtifactError, FoundationError
from deterministic_lab.governance import INVESTIGATION_SCHEMA, OUTPUT_SCHEMA, Admission
from deterministic_lab.identities import identity_for
from deterministic_lab.methods import NUMERIC_POLICY, TIME_WINDOW_METHOD
from deterministic_lab.store import ArtifactRef

from .models import (
    AdmissionRecord,
    ArtifactRecord,
    ExecutionAttempt,
    InvestigationRecord,
    Job,
    JobEvent,
    ResearchRun,
)
from .services import (
    IdempotencyConflict,
    InvalidTransition,
    _authoritative_write,
    _record_transition,
    _retry_sqlite_busy,
)

SCIENTIFIC_COMMAND_VERSION = "mydjangocs.scientific-command/1"


@dataclass(frozen=True, slots=True)
class ScientificAdmissionResult:
    job: Job
    investigation: InvestigationRecord
    duplicate: bool


@dataclass(frozen=True, slots=True)
class ScientificClaim:
    job_id: UUID
    attempt_number: int
    claim_generation: int
    owner_token: str
    attempt_identity: str


def foundation_api() -> FoundationAPI:
    return FoundationAPI(Path(settings.ARTIFACT_STORE_ROOT))


def _artifact_reference(record: ArtifactRecord) -> ArtifactRef:
    return ArtifactRef(
        identity=record.identity,
        artifact_type=record.artifact_type,
        schema_version=record.schema_version,
        size=record.size,
        payload_digest=record.payload_digest,
    )


def register_artifact(
    reference: ArtifactRef,
    *,
    metadata: dict[str, Any] | None = None,
) -> ArtifactRecord:
    defaults = {
        "artifact_type": reference.artifact_type,
        "schema_version": reference.schema_version,
        "payload_digest": reference.payload_digest,
        "size": reference.size,
        "state": ArtifactRecord.State.REGISTERED,
        "metadata": metadata or {},
        "verified_at": timezone.now(),
    }
    record = ArtifactRecord.objects.filter(identity=reference.identity).first()
    if record is None:
        record = ArtifactRecord.objects.create(identity=reference.identity, **defaults)
    else:
        actual = (
            record.artifact_type,
            record.schema_version,
            record.payload_digest,
            record.size,
        )
        expected = (
            reference.artifact_type,
            reference.schema_version,
            reference.payload_digest,
            reference.size,
        )
        if actual != expected:
            raise InvalidTransition(
                "Artifact identity is already registered with different metadata."
            )
        if record.state != ArtifactRecord.State.REGISTERED:
            record.state = ArtifactRecord.State.REGISTERED
            record.verified_at = timezone.now()
            record.save(update_fields=["state", "verified_at"])
    return record


def seed_reference_run() -> tuple[ResearchRun, bool]:
    api = foundation_api()
    evidence, manifest, state, artifacts = api.build_state(reference_evidence())
    if os.environ.get("LAB_CRASH_POINT") == "after_state_artifact_publication":
        os._exit(87)

    def register() -> tuple[ResearchRun, bool]:
        with _authoritative_write():
            evidence_record = register_artifact(
                artifacts.evidence,
                metadata={
                    "content_identity": evidence.content_identity,
                    "provenance_identity": evidence.provenance_identity,
                },
            )
            manifest_record = register_artifact(
                artifacts.manifest,
                metadata={"manifest_identity": manifest.identity},
            )
            state_record = register_artifact(
                artifacts.state,
                metadata={"state_identity": state.identity},
            )
            run = ResearchRun.objects.filter(manifest_identity=manifest.identity).first()
            created = run is None
            if run is None:
                run = ResearchRun.objects.create(
                    manifest_identity=manifest.identity,
                    name="Fictional measurement network",
                    evidence_content_identity=evidence.content_identity,
                    evidence_provenance_identity=evidence.provenance_identity,
                    state_identity=state.identity,
                    evidence_artifact=evidence_record,
                    manifest_artifact=manifest_record,
                    state_artifact=state_record,
                    summary={
                        "anomalous_observations": sum(
                            item.quality == "anomalous" for item in state.observations
                        ),
                        "entities": len(state.entities),
                        "missing_observations": sum(item.missing for item in state.observations),
                        "observations": len(state.observations),
                        "relationships": len(state.edges),
                    },
                )
        return run, created

    return _retry_sqlite_busy(register)


def load_state_by_identity(state_identity: str):
    run = ResearchRun.objects.select_related("state_artifact").filter(
        state_identity=state_identity
    ).first()
    if run is None or run.state_artifact.state != ArtifactRecord.State.REGISTERED:
        raise KeyError(state_identity)
    return foundation_api().load_state(_artifact_reference(run.state_artifact))


def default_investigation(run: ResearchRun) -> dict[str, Any]:
    return {
        "method": TIME_WINDOW_METHOD,
        "method_parameters": {},
        "missing_policy": "exclude",
        "numeric_policy": NUMERIC_POLICY,
        "output_schema": OUTPUT_SCHEMA,
        "resource_budget": {"max_records": 100, "max_targets": 4},
        "schema_version": INVESTIGATION_SCHEMA,
        "state_identity": run.state_identity,
        "target_sensors": ["sensor_alpha", "sensor_bravo"],
        "temporal_scope": {
            "end": "2026-01-01T03:00:00Z",
            "start": "2026-01-01T00:00:00Z",
        },
        "unit": "synthetic_unit",
        "variable_id": "signal",
    }


def _existing_job(idempotency_key: str, computation_identity: str) -> Job | None:
    existing = Job.objects.filter(idempotency_key=idempotency_key).first()
    if existing is None:
        return None
    if not existing.admission_id or existing.admission.computation_identity != computation_identity:
        raise IdempotencyConflict("That idempotency key is bound to a different computation.")
    return existing


def admit_investigation(
    research_run: ResearchRun,
    declaration: dict[str, Any],
    idempotency_key: str,
) -> ScientificAdmissionResult:
    if not idempotency_key or len(idempotency_key) > 100:
        raise AdmissionError("structural", "INVALID_IDEMPOTENCY_KEY", "A bounded key is required.")
    admission, _ = foundation_api().admit(declaration, load_state_by_identity)

    def persist() -> ScientificAdmissionResult:
        with _authoritative_write():
            existing = _existing_job(idempotency_key, admission.computation_identity)
            if existing is not None:
                return ScientificAdmissionResult(existing, existing.admission.investigation, True)
            investigation = InvestigationRecord.objects.filter(
                identity=admission.investigation_identity
            ).first()
            if investigation is None:
                investigation = InvestigationRecord.objects.create(
                    identity=admission.investigation_identity,
                    research_run=research_run,
                    declaration=admission.declaration,
                    state=InvestigationRecord.State.ADMITTED,
                )
            admission_record = AdmissionRecord.objects.filter(identity=admission.identity).first()
            if admission_record is None:
                admission_record = AdmissionRecord.objects.create(
                    identity=admission.identity,
                    investigation=investigation,
                    state_identity=admission.state_identity,
                    computation_identity=admission.computation_identity,
                    declaration=admission.declaration,
                    resource_envelope=admission.declaration["resource_budget"],
                    authorization_state=admission.authorization_state,
                )
            try:
                job = Job.objects.create(
                    workflow=None,
                    admission=admission_record,
                    idempotency_key=idempotency_key,
                    command_version=SCIENTIFIC_COMMAND_VERSION,
                    input_digest=admission.computation_identity.rsplit(":", 1)[-1],
                    workflow_snapshot=admission.declaration,
                    input_values=[],
                )
            except DatabaseIntegrityError:
                raced = _existing_job(idempotency_key, admission.computation_identity)
                if raced is None:
                    raise
                return ScientificAdmissionResult(raced, raced.admission.investigation, True)
            JobEvent.objects.create(
                job=job,
                sequence=1,
                from_state="",
                to_state=Job.State.ADMITTED,
                reason="verified scientific investigation admitted",
            )
            if os.environ.get("LAB_CRASH_POINT") == "before_admission_commit":
                os._exit(88)
        return ScientificAdmissionResult(job, investigation, False)

    return _retry_sqlite_busy(persist)


def claim_scientific_job(job_id: UUID) -> ScientificClaim:
    def claim() -> ScientificClaim:
        with _authoritative_write():
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
            _record_transition(job, Job.State.ADMITTED, "fenced scientific worker claimed job")
        return ScientificClaim(
            job_id=current.id,
            attempt_number=attempt_number,
            claim_generation=generation,
            owner_token=owner_token,
            attempt_identity=attempt_identity,
        )

    return _retry_sqlite_busy(claim)


def _admission_from_record(record: AdmissionRecord) -> Admission:
    return Admission(
        identity=record.identity,
        investigation_identity=record.investigation.identity,
        state_identity=record.state_identity,
        computation_identity=record.computation_identity,
        declaration=record.declaration,
        authorization_state=record.authorization_state,
    )


def finalize_scientific_result(claim: ScientificClaim, result: ExecutionResult) -> Job:
    def finalize() -> Job:
        with _authoritative_write():
            artifact = register_artifact(
                result.artifact,
                metadata={"result_identity": result.identity},
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
                job=job,
                number=claim.attempt_number,
                owner_token=claim.owner_token,
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
            _record_transition(job, Job.State.RUNNING, "verified result artifact committed")
        return job

    return _retry_sqlite_busy(finalize)


def _fail_scientific_job(claim: ScientificClaim, code: str, message: str) -> Job:
    def fail() -> Job:
        with _authoritative_write():
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
            _record_transition(job, Job.State.RUNNING, "scientific execution failed closed")
        return job

    return _retry_sqlite_busy(fail)


def execute_scientific_job(job_id: UUID) -> Job:
    claim = claim_scientific_job(job_id)
    job = Job.objects.select_related("admission__investigation").get(pk=job_id)
    try:
        state = load_state_by_identity(job.admission.state_identity)
        if os.environ.get("LAB_CRASH_POINT") == "before_result_publication":
            os._exit(89)
        result = foundation_api().execute(_admission_from_record(job.admission), state)
        if os.environ.get("LAB_CRASH_POINT") == "after_artifact_publication":
            os._exit(91)
        finalized = finalize_scientific_result(claim, result)
        if os.environ.get("LAB_CRASH_POINT") == "after_result_commit":
            os._exit(93)
        return finalized
    except (FoundationError, ArtifactError) as exc:
        return _fail_scientific_job(claim, "FOUNDATION_REJECTED", str(exc))
    except InvalidTransition:
        raise
    except Exception:
        return _fail_scientific_job(
            claim,
            "EXECUTION_ERROR",
            "Scientific execution failed unexpectedly.",
        )


def interrupt_scientific_job(
    job_id: UUID,
    *,
    owner_token: str,
    confirmed_worker_stopped: bool,
) -> Job:
    if not confirmed_worker_stopped:
        raise InvalidTransition("Recovery requires explicit confirmation that the worker stopped.")

    def interrupt() -> Job:
        with _authoritative_write():
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
            _record_transition(job, Job.State.RUNNING, "owner-confirmed worker interruption")
            if os.environ.get("LAB_CRASH_POINT") == "during_scientific_recovery":
                os._exit(94)
        return job

    return _retry_sqlite_busy(interrupt)


def reconcile_artifacts(*, quarantine_orphans: bool = False) -> dict[str, list[str]]:
    api = foundation_api()
    registered = {record.identity: record for record in ArtifactRecord.objects.all()}
    registered_digests = {identity.rsplit(":", 1)[-1] for identity in registered}
    store_digests = set(api.store.iter_digests())
    report: dict[str, list[str]] = {"corrupt": [], "missing": [], "orphans": [], "verified": []}
    for identity, record in registered.items():
        reference = _artifact_reference(record)
        try:
            api.store.verify(reference)
        except ArtifactError:
            record.state = (
                ArtifactRecord.State.CORRUPT
                if api.store.path_for(reference).exists()
                else ArtifactRecord.State.MISSING
            )
            record.verified_at = timezone.now()
            record.save(update_fields=["state", "verified_at"])
            report[record.state].append(identity)
        else:
            record.state = ArtifactRecord.State.REGISTERED
            record.verified_at = timezone.now()
            record.save(update_fields=["state", "verified_at"])
            report["verified"].append(identity)
    for digest in sorted(store_digests - registered_digests):
        report["orphans"].append(digest)
        if quarantine_orphans:
            api.store.quarantine_digest(digest)
    return report


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
    payload = parse_json_strict(foundation_api().store.load(_artifact_reference(record)))
    if payload.get("identity") != job.result.get("identity"):
        raise InvalidTransition("Result artifact and job identity disagree.")
    return payload


def publication_payload(result: ExecutionResult) -> bytes:
    """Expose the exact bytes registered for a result artifact in tests and diagnostics."""
    return canonical_bytes({**result.payload, "identity": result.identity})
