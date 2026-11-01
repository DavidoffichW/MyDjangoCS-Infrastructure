from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections
from django.test import TransactionTestCase

from infrastructure.orchestration import claim_job
from infrastructure.orchestration.finalization import finish_workflow_job
from services.workflows import (
    IdempotencyConflict,
    InvalidTransition,
    WorkflowValidationError,
    add_step,
    admit_job,
    canonical_decimal,
    canonical_json_bytes,
    digest,
    execute_job,
    move_step,
    requeue_job,
    validate_workflow,
)
from services.workflows.contracts import EXECUTION_PRECISION, EXECUTION_ROUNDING
from workflows.models import ExecutionAttempt, Job, JobEvent, Workflow, WorkflowStep


class AdversarialTransactionTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self) -> None:
        self.workflow = Workflow.objects.create(name="Adversarial workflow")
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

    def run_competing(self, *functions):
        barrier = threading.Barrier(len(functions))

        def invoke(function):
            connections.close_all()
            barrier.wait(timeout=5)
            try:
                return ("ok", function())
            except Exception as exc:  # evidence includes the concrete failure class
                return ("error", type(exc).__name__, str(exc))
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            return list(executor.map(invoke, functions))

    def test_identical_concurrent_admission_returns_one_authoritative_job(self) -> None:
        workflow_id = self.workflow.id

        def submit():
            workflow = Workflow.objects.get(pk=workflow_id)
            return admit_job(workflow, [Decimal("1"), Decimal("2")], "concurrent-key")

        outcomes = self.run_competing(submit, submit)

        self.assertTrue(all(outcome[0] == "ok" for outcome in outcomes), outcomes)
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual({outcome[1].job.id for outcome in outcomes}, {Job.objects.get().id})
        self.assertEqual(sorted(outcome[1].duplicate for outcome in outcomes), [False, True])
        self.assertEqual(JobEvent.objects.count(), 1)

    def test_conflicting_concurrent_admission_has_one_winner_and_one_conflict(self) -> None:
        workflow_id = self.workflow.id

        def submit(value):
            def operation():
                workflow = Workflow.objects.get(pk=workflow_id)
                return admit_job(workflow, [Decimal(value)], "conflicting-key")

            return operation

        outcomes = self.run_competing(submit("1"), submit("2"))

        self.assertEqual(sum(outcome[0] == "ok" for outcome in outcomes), 1, outcomes)
        errors = [outcome for outcome in outcomes if outcome[0] == "error"]
        self.assertEqual(errors[0][1], IdempotencyConflict.__name__, outcomes)
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(JobEvent.objects.count(), 1)

    def test_competing_claims_have_one_controlled_winner(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "claim-key").job

        outcomes = self.run_competing(lambda: claim_job(job.id), lambda: claim_job(job.id))

        self.assertEqual(sum(outcome[0] == "ok" for outcome in outcomes), 1, outcomes)
        errors = [outcome for outcome in outcomes if outcome[0] == "error"]
        self.assertEqual(errors[0][1], InvalidTransition.__name__, outcomes)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.RUNNING)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.execution_attempts.count(), 1)
        self.assertEqual(
            list(job.events.values_list("to_state", flat=True)),
            [Job.State.ADMITTED, Job.State.RUNNING],
        )

    def test_competing_execution_requests_have_one_successful_attempt(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "competing-execution").job

        outcomes = self.run_competing(lambda: execute_job(job.id), lambda: execute_job(job.id))

        self.assertEqual(
            sum(
                outcome[0] == "ok" and outcome[1].state == Job.State.SUCCEEDED
                for outcome in outcomes
            ),
            1,
            outcomes,
        )
        errors = [outcome for outcome in outcomes if outcome[0] == "error"]
        self.assertEqual(errors[0][1], InvalidTransition.__name__, outcomes)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.SUCCEEDED)
        self.assertEqual(job.execution_attempts.count(), 1)

    def test_reordered_operations_change_command_identity(self) -> None:
        original = admit_job(self.workflow, [Decimal("1")], "ordered").job
        second = self.workflow.steps.get(position=2)
        move_step(second, "up")
        reordered = admit_job(self.workflow, [Decimal("1")], "reordered").job

        self.assertNotEqual(original.input_digest, reordered.input_digest)
        self.assertNotEqual(original.workflow_snapshot, reordered.workflow_snapshot)

    def test_workflow_mutation_does_not_change_admitted_snapshot(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "immutable-snapshot").job
        admitted_snapshot = job.workflow_snapshot
        first = self.workflow.steps.get(position=1)
        first.parameter = Decimal("9")
        first.save(update_fields=["parameter"])

        job.refresh_from_db()
        self.assertEqual(job.workflow_snapshot, admitted_snapshot)
        self.assertEqual(execute_job(job.id).result["values"], ["2"])

    def test_direct_admitted_command_mutation_is_rejected(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "immutable-row").job
        job.input_values = ["999"]
        with self.assertRaises((ValidationError, IntegrityError)):
            job.save(update_fields=["input_values"])
        with self.assertRaises(IntegrityError):
            Job.objects.filter(pk=job.id).update(input_values=["999"])

    def test_repeated_retry_has_one_controlled_winner(self) -> None:
        failure_workflow = Workflow.objects.create(name="Retry workflow")
        add_step(
            failure_workflow,
            operation=WorkflowStep.Operation.FAIL_ONCE,
            parameter=None,
        )
        job = execute_job(admit_job(failure_workflow, [Decimal("1")], "retry-key").job.id)
        self.assertEqual(job.state, Job.State.FAILED)

        outcomes = self.run_competing(lambda: requeue_job(job.id), lambda: requeue_job(job.id))

        self.assertEqual(sum(outcome[0] == "ok" for outcome in outcomes), 1, outcomes)
        errors = [outcome for outcome in outcomes if outcome[0] == "error"]
        self.assertEqual(errors[0][1], InvalidTransition.__name__, outcomes)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.ADMITTED)
        self.assertEqual(job.events.filter(to_state=Job.State.ADMITTED).count(), 2)

    def test_attempt_and_event_history_is_monotonic_after_retry(self) -> None:
        workflow = Workflow.objects.create(name="Attempt history")
        add_step(workflow, operation=WorkflowStep.Operation.FAIL_ONCE, parameter=None)
        job = admit_job(workflow, [Decimal("1")], "attempt-history").job

        execute_job(job.id)
        requeue_job(job.id)
        execute_job(job.id)
        job.refresh_from_db()

        attempts = list(job.execution_attempts.values_list("number", "state", "finished_at"))
        self.assertEqual([attempt[0] for attempt in attempts], [1, 2])
        self.assertEqual([attempt[1] for attempt in attempts], ["failed", "succeeded"])
        self.assertTrue(all(attempt[2] is not None for attempt in attempts))
        events = list(job.events.values_list("sequence", "to_state"))
        self.assertEqual([event[0] for event in events], sorted({event[0] for event in events}))
        self.assertEqual(
            [event[1] for event in events],
            ["admitted", "running", "failed", "admitted", "running", "succeeded"],
        )

    def test_admission_rolls_back_if_event_write_fails(self) -> None:
        with (
            patch(
                "services.workflows.admission.JobEvent.objects.create",
                side_effect=RuntimeError("fault"),
            ),
            self.assertRaisesRegex(RuntimeError, "fault"),
        ):
            admit_job(self.workflow, [Decimal("1")], "rollback-admission")

        self.assertFalse(Job.objects.filter(idempotency_key="rollback-admission").exists())
        self.assertFalse(JobEvent.objects.exists())

    def test_finalization_rolls_back_if_attempt_write_fails(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "rollback-finalize").job
        _, attempt_number = claim_job(job.id)
        result = {"evidence": [], "summary": None, "values": ["2"]}

        with (
            patch.object(ExecutionAttempt, "save", side_effect=RuntimeError("fault")),
            self.assertRaisesRegex(RuntimeError, "fault"),
        ):
            finish_workflow_job(job.id, attempt_number, result=result)

        job.refresh_from_db()
        attempt = job.execution_attempts.get(number=attempt_number)
        self.assertEqual(job.state, Job.State.RUNNING)
        self.assertIsNone(job.result)
        self.assertEqual(job.result_digest, "")
        self.assertEqual(attempt.state, Job.State.RUNNING)
        self.assertEqual(job.events.filter(to_state=Job.State.SUCCEEDED).count(), 0)

    def test_success_without_result_is_rejected_by_database(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "invalid-success").job
        with self.assertRaises(IntegrityError):
            Job.objects.filter(pk=job.id).update(state=Job.State.SUCCEEDED)


class CanonicalAndNumericTests(TransactionTestCase):
    def setUp(self) -> None:
        self.workflow = Workflow.objects.create(name="Numeric limits")
        add_step(
            self.workflow,
            operation=WorkflowStep.Operation.SUMMARIZE,
            parameter=None,
        )

    def test_canonical_json_has_stable_order_and_codepoint_exact_unicode(self) -> None:
        self.assertEqual(digest({"b": 2, "a": 1}), digest({"a": 1, "b": 2}))
        self.assertNotEqual(digest({"text": "é"}), digest({"text": "e\u0301"}))

    def test_decimal_normalization_handles_negative_zero(self) -> None:
        self.assertEqual(canonical_decimal(Decimal("-0.000")), "0")
        self.assertEqual(canonical_decimal(Decimal("1.2300")), "1.23")

    def test_reference_decimal_calculation_uses_declared_rounding(self) -> None:
        workflow = Workflow.objects.create(name="Rounding")
        add_step(
            workflow,
            operation=WorkflowStep.Operation.SCALE,
            parameter=Decimal("0.333333"),
        )
        job = execute_job(admit_job(workflow, [Decimal("3")], "rounding").job.id)
        with localcontext() as context:
            context.prec = EXECUTION_PRECISION
            context.rounding = ROUND_HALF_EVEN
            expected = Decimal("3") * Decimal("0.333333")
        self.assertEqual(job.result["values"], [format(expected.normalize(), "f")])
        self.assertEqual(EXECUTION_ROUNDING, ROUND_HALF_EVEN)

    def test_non_finite_and_oversized_inputs_are_rejected_before_admission(self) -> None:
        for invalid in (
            [],
            [Decimal("NaN")],
            [Decimal("Infinity")],
            [Decimal("1000000001")],
            [Decimal("1E-1000")],
            [Decimal("1")] * 101,
        ):
            with (
                self.subTest(invalid=str(invalid[:2])),
                self.assertRaises(WorkflowValidationError),
            ):
                validate_workflow(self.workflow, invalid)

    def test_canonical_json_rejects_non_finite_binary_floats(self) -> None:
        with self.assertRaises(ValueError):
            canonical_json_bytes({"value": float("nan")})
