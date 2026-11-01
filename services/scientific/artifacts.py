"""Scientific artifact registration, reference-run seeding, and state loading."""

import os
from typing import Any

from django.utils import timezone

from foundation.contracts.preservation import ArtifactRef
from foundation.fixtures import reference_evidence
from infrastructure.orchestration.errors import InvalidTransition
from infrastructure.persistence import authoritative_write, retry_sqlite_busy
from infrastructure.persistence.reconciliation import reconcile_artifact_records
from workflows.models import ArtifactRecord, ResearchRun

from .composition import foundation_api


def artifact_reference(record: ArtifactRecord) -> ArtifactRef:
    return ArtifactRef(
        identity=record.identity,
        artifact_type=record.artifact_type,
        schema_version=record.schema_version,
        size=record.size,
        payload_digest=record.payload_digest,
    )


def register_artifact(
    reference: ArtifactRef, *, metadata: dict[str, Any] | None = None
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
        return ArtifactRecord.objects.create(identity=reference.identity, **defaults)
    actual = (record.artifact_type, record.schema_version, record.payload_digest, record.size)
    expected = (
        reference.artifact_type,
        reference.schema_version,
        reference.payload_digest,
        reference.size,
    )
    if actual != expected:
        raise InvalidTransition("Artifact identity is already registered with different metadata.")
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
        with authoritative_write():
            evidence_record = register_artifact(
                artifacts.evidence,
                metadata={
                    "content_identity": evidence.content_identity,
                    "provenance_identity": evidence.provenance_identity,
                },
            )
            manifest_record = register_artifact(
                artifacts.manifest, metadata={"manifest_identity": manifest.identity}
            )
            state_record = register_artifact(
                artifacts.state, metadata={"state_identity": state.identity}
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

    return retry_sqlite_busy(register)


def load_state_by_identity(state_identity: str):
    run = (
        ResearchRun.objects.select_related("state_artifact")
        .filter(state_identity=state_identity)
        .first()
    )
    if run is None or run.state_artifact.state != ArtifactRecord.State.REGISTERED:
        raise KeyError(state_identity)
    return foundation_api().load_state(artifact_reference(run.state_artifact))


def reconcile_artifacts(*, quarantine_orphans: bool = False) -> dict[str, list[str]]:
    store = foundation_api().store
    return reconcile_artifact_records(
        ArtifactRecord.objects,
        store,
        artifact_reference,
        quarantine_orphans=quarantine_orphans,
    )
