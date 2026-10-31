from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from workflows.models import Job, Workflow, WorkflowStep
from workflows.services import (
    IdempotencyConflict,
    InvalidTransition,
    add_step,
    admit_job,
    claim_job,
    execute_job,
    execute_next_job,
    move_step,
    recover_stale_jobs,
    remove_step,
    requeue_job,
    validate_workflow,
)


class WorkflowServiceTests(TestCase):
    def setUp(self) -> None:
        self.workflow = Workflow.objects.create(name="Deterministic sample")

    def add_standard_steps(self) -> None:
        add_step(
            self.workflow,
            operation=WorkflowStep.Operation.SCALE,
            parameter=Decimal("2"),
        )
        add_step(
            self.workflow,
            operation=WorkflowStep.Operation.SUMMARIZE,
            parameter=None,
        )

    def test_step_order_move_and_delete_remain_contiguous(self) -> None:
        self.add_standard_steps()
        first, second = self.workflow.steps.all()

        move_step(second, "up")
        self.assertEqual(
            list(self.workflow.steps.values_list("operation", "position")),
            [(WorkflowStep.Operation.SUMMARIZE, 1), (WorkflowStep.Operation.SCALE, 2)],
        )

        remove_step(first)
        self.assertEqual(list(self.workflow.steps.values_list("position", flat=True)), [1])

    def test_validation_produces_stable_content_identity(self) -> None:
        self.add_standard_steps()
        first = validate_workflow(self.workflow, [Decimal("1.0"), Decimal("2.00")])
        second = validate_workflow(self.workflow, [Decimal("1"), Decimal("2")])
        self.assertEqual(first["input_digest"], second["input_digest"])
        self.assertEqual(first["values"], ["1", "2"])
        self.workflow.refresh_from_db()
        self.assertEqual(first["snapshot"]["workflow_revision"], self.workflow.revision)

    def test_duplicate_admission_returns_same_authoritative_job(self) -> None:
        self.add_standard_steps()
        first = admit_job(self.workflow, [Decimal("1"), Decimal("2")], "same-command")
        second = admit_job(self.workflow, [Decimal("1.0"), Decimal("2.0")], "same-command")
        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.job.id, second.job.id)
        self.assertEqual(Job.objects.count(), 1)

    def test_idempotency_key_conflict_is_explicit(self) -> None:
        self.add_standard_steps()
        admit_job(self.workflow, [Decimal("1")], "conflict")
        with self.assertRaisesRegex(IdempotencyConflict, "different input"):
            admit_job(self.workflow, [Decimal("2")], "conflict")

    def test_deterministic_jobs_replay_to_identical_result(self) -> None:
        self.add_standard_steps()
        first = admit_job(self.workflow, [Decimal("1"), Decimal("2")], "replay-1").job
        second = admit_job(self.workflow, [Decimal("1"), Decimal("2")], "replay-2").job

        first = execute_job(first.id)
        second = execute_job(second.id)

        self.assertEqual(first.state, Job.State.SUCCEEDED)
        self.assertEqual(first.result, second.result)
        self.assertEqual(first.result_digest, second.result_digest)
        self.assertEqual(first.result["values"], ["2", "4"])
        self.assertEqual(first.result["summary"], {"count": 2, "mean": "3", "sum": "6"})

    def test_injected_failure_requires_controlled_retry(self) -> None:
        add_step(
            self.workflow,
            operation=WorkflowStep.Operation.FAIL_ONCE,
            parameter=None,
        )
        add_step(
            self.workflow,
            operation=WorkflowStep.Operation.OFFSET,
            parameter=Decimal("1"),
        )
        job = admit_job(self.workflow, [Decimal("2")], "fail-once").job

        job = execute_job(job.id)
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertEqual(job.failure_code, "INJECTED_FAILURE")

        requeue_job(job.id)
        job = execute_job(job.id)
        self.assertEqual(job.state, Job.State.SUCCEEDED)
        self.assertEqual(job.result["values"], ["3"])
        self.assertEqual(job.attempts, 2)

    def test_stale_running_job_is_recovered_but_not_automatically_retried(self) -> None:
        self.add_standard_steps()
        job = admit_job(self.workflow, [Decimal("1")], "interrupted").job
        claim_job(job.id)
        Job.objects.filter(pk=job.id).update(updated_at=timezone.now() - timedelta(minutes=5))

        recovered = recover_stale_jobs(60)
        job.refresh_from_db()

        self.assertEqual(recovered, [job.id])
        self.assertEqual(job.state, Job.State.INTERRUPTED)
        self.assertEqual(job.failure_code, "INTERRUPTED")
        requeue_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.ADMITTED)

    def test_invalid_transition_does_not_change_successful_job(self) -> None:
        self.add_standard_steps()
        job = admit_job(self.workflow, [Decimal("1")], "finished").job
        job = execute_job(job.id)
        with self.assertRaises(InvalidTransition):
            requeue_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.SUCCEEDED)

    def test_worker_records_unexpected_failures_without_leaving_running_state(self) -> None:
        self.add_standard_steps()
        job = admit_job(self.workflow, [Decimal("1")], "worker-error").job

        with patch(
            "workflows.services._run_operations", side_effect=RuntimeError("private detail")
        ):
            result = execute_next_job()

        self.assertEqual(result.id, job.id)
        self.assertEqual(result.state, Job.State.FAILED)
        self.assertEqual(result.failure_code, "EXECUTION_ERROR")
        self.assertEqual(result.failure_message, "The operation failed unexpectedly.")
        self.assertNotIn("private detail", result.failure_message)
