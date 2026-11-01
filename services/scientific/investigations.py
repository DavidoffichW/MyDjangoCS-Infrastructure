"""Scientific declaration defaults and idempotent durable admission."""

import os
from typing import Any

from django.db import IntegrityError as DatabaseIntegrityError

from foundation.computation import TIME_WINDOW_METHOD
from foundation.contracts.errors import AdmissionError
from foundation.contracts.numeric_policy import NUMERIC_POLICY
from foundation.governance.contracts import INVESTIGATION_SCHEMA, OUTPUT_SCHEMA
from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from services.workflows.contracts import IdempotencyConflict
from workflows.models import AdmissionRecord, InvestigationRecord, Job, JobEvent, ResearchRun

from .artifacts import load_state_by_identity
from .composition import foundation_api
from .contracts import ScientificAdmissionResult

SCIENTIFIC_COMMAND_VERSION = "mydjangocs.scientific-command/1"


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
        "temporal_scope": {"end": "2026-01-01T03:00:00Z", "start": "2026-01-01T00:00:00Z"},
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
    research_run: ResearchRun, declaration: dict[str, Any], idempotency_key: str
) -> ScientificAdmissionResult:
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 100:
        raise AdmissionError("structural", "INVALID_IDEMPOTENCY_KEY", "A bounded key is required.")
    admission, _ = foundation_api().admit(declaration, load_state_by_identity)

    def persist() -> ScientificAdmissionResult:
        with authoritative_write():
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

    return retry_sqlite_busy(persist)
