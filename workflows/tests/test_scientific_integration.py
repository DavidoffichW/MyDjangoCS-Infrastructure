from __future__ import annotations

import tempfile
from pathlib import Path

from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase

from foundation.contracts.errors import AdmissionError
from services.scientific.artifacts import (
    artifact_reference,
    reconcile_artifacts,
    seed_reference_run,
)
from services.scientific.composition import foundation_api
from services.scientific.investigations import admit_investigation, default_investigation
from services.scientific.jobs import (
    admission_from_record,
    claim_scientific_job,
    execute_scientific_job,
    interrupt_scientific_job,
)
from services.scientific.results import finalize_scientific_result, result_cache_identity
from services.workflows import IdempotencyConflict, InvalidTransition, requeue_job
from workflows.models import AdmissionRecord, ArtifactRecord, Job, ResearchRun


class ScientificIntegrationTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = self.settings(ARTIFACT_STORE_ROOT=Path(self.directory.name))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.run, _ = seed_reference_run()

    def admit(self, key="scientific-key", declaration=None):
        return admit_investigation(
            self.run,
            declaration or default_investigation(self.run),
            key,
        )

    def test_reference_run_is_restart_safe_and_artifacts_are_registered(self):
        again, created = seed_reference_run()
        self.assertFalse(created)
        self.assertEqual(again.id, self.run.id)
        self.assertEqual(ArtifactRecord.objects.count(), 3)
        state = foundation_api().load_state(artifact_reference(self.run.state_artifact))
        self.assertEqual(state.identity, self.run.state_identity)
        self.assertEqual(self.run.summary["observations"], 16)
        self.assertEqual(self.run.summary["missing_observations"], 1)

    def test_complete_investigation_executes_persists_and_replays(self):
        admitted = self.admit()
        job = execute_scientific_job(admitted.job.id)
        self.assertEqual(job.state, Job.State.SUCCEEDED)
        self.assertTrue(job.result_artifact_identity)
        self.assertEqual(job.result["state_identity"], self.run.state_identity)
        self.assertTrue(ArtifactRecord.objects.filter(pk=job.result_artifact_identity).exists())

        replay = self.admit(key="scientific-replay")
        replayed_job = execute_scientific_job(replay.job.id)
        self.assertEqual(replayed_job.result["identity"], job.result["identity"])
        self.assertEqual(replayed_job.result_artifact_identity, job.result_artifact_identity)
        self.assertNotEqual(
            result_cache_identity(job, "page"),
            result_cache_identity(replayed_job, "page"),
        )

    def test_duplicate_and_conflicting_idempotency_are_explicit(self):
        first = self.admit()
        duplicate = self.admit()
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(first.job.id, duplicate.job.id)
        changed = default_investigation(self.run)
        changed["missing_policy"] = "propagate"
        with self.assertRaises(IdempotencyConflict):
            self.admit(declaration=changed)

    def test_incomplete_investigation_is_rejected_before_persistence(self):
        with self.assertRaises(AdmissionError) as raised:
            self.admit(declaration={"schema_version": "mydjangocs.investigation/1"})
        self.assertEqual(raised.exception.stage, "structural")
        self.assertEqual(Job.objects.count(), 0)
        self.assertEqual(AdmissionRecord.objects.count(), 0)

    def test_stale_attempt_cannot_finalize_after_owner_confirmed_recovery(self):
        admitted = self.admit()
        first_claim = claim_scientific_job(admitted.job.id)
        job = Job.objects.select_related("admission__investigation").get(pk=admitted.job.id)
        state = foundation_api().load_state(artifact_reference(self.run.state_artifact))
        result = foundation_api().execute(admission_from_record(job.admission), state)

        interrupt_scientific_job(
            job.id,
            owner_token=first_claim.owner_token,
            confirmed_worker_stopped=True,
        )
        requeue_job(job.id)
        second_claim = claim_scientific_job(job.id)
        with self.assertRaises(InvalidTransition):
            finalize_scientific_result(first_claim, result)
        finalized = finalize_scientific_result(second_claim, result)
        self.assertEqual(finalized.state, Job.State.SUCCEEDED)
        self.assertEqual(finalized.attempts, 2)

    def test_recovery_requires_positive_worker_termination_confirmation(self):
        admitted = self.admit()
        claim = claim_scientific_job(admitted.job.id)
        with self.assertRaises(InvalidTransition):
            interrupt_scientific_job(
                admitted.job.id,
                owner_token=claim.owner_token,
                confirmed_worker_stopped=False,
            )
        admitted.job.refresh_from_db()
        self.assertEqual(admitted.job.state, Job.State.RUNNING)

    def test_database_guards_immutable_admission_and_result_evidence(self):
        admitted = self.admit()
        with self.assertRaises(DatabaseError), transaction.atomic():
            AdmissionRecord.objects.filter(pk=admitted.job.admission_id).update(
                state_identity="changed"
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.filter(pk=admitted.job.id).update(
                state=Job.State.SUCCEEDED,
                result={"invalid": True},
                result_digest="0" * 64,
                result_artifact_identity="",
            )

    def test_reconciliation_reports_corruption_and_orphans_without_deleting(self):
        api = foundation_api()
        state_reference = artifact_reference(self.run.state_artifact)
        api.store.path_for(state_reference).write_bytes(b"corrupt")
        orphan = api.store.publish("result", "mydjangocs.result/1", b"orphan")
        report = reconcile_artifacts()
        self.assertIn(self.run.state_artifact_id, report["corrupt"])
        self.assertIn(orphan.digest, report["orphans"])
        self.assertTrue(api.store.path_for(orphan).exists())
        self.run.state_artifact.refresh_from_db()
        self.assertEqual(self.run.state_artifact.state, ArtifactRecord.State.CORRUPT)

    def test_run_authority_fields_cannot_be_bulk_mutated(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            ResearchRun.objects.filter(pk=self.run.id).update(state_identity="changed")
