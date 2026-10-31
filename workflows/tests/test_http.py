from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.core.cache import cache
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from workflows.models import Job, Workflow, WorkflowStep
from workflows.services import add_step, admit_job, claim_job, execute_job, recover_stale_jobs


class ConcurrentHttpTests(TransactionTestCase):
    reset_sequences = True

    def test_double_execute_returns_one_success_and_one_controlled_conflict(self) -> None:
        workflow = Workflow.objects.create(name="Concurrent HTTP")
        add_step(workflow, operation=WorkflowStep.Operation.SUMMARIZE, parameter=None)
        job = admit_job(workflow, [Decimal("1")], "concurrent-http").job
        gate = Barrier(2)

        def execute() -> tuple[str, object]:
            connections.close_all()
            gate.wait(timeout=5)
            try:
                response = Client().post(
                    reverse("job-execute", args=[job.id]),
                    headers={"HX-Request": "true"},
                )
                return "response", response.status_code
            except Exception as exc:
                return type(exc).__name__, str(exc)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: execute(), range(2)))

        self.assertEqual(sorted(outcome[1] for outcome in outcomes), [200, 409], outcomes)


@override_settings(ROOT_URLCONF="workflows.tests.test_urls")
class MiddlewareFailureTests(TestCase):
    def test_view_exception_is_converted_inside_trace_middleware(self) -> None:
        client = Client(raise_request_exception=False)
        response = client.get("/exception/")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.headers["X-Lab-Trace"],
            "trace.enter>guard.pass>view.raise>trace.exit",
        )
        self.assertRegex(response.headers["X-Correlation-ID"], r"^[0-9a-f]{32}$")

    @override_settings(
        MIDDLEWARE=[
            "django.middleware.security.SecurityMiddleware",
            "reliability_lab.middleware.RequestTraceMiddleware",
            "workflows.tests.test_support.RaisingMiddleware",
        ]
    )
    def test_inner_middleware_exception_is_converted_and_traced(self) -> None:
        client = Client(raise_request_exception=False)
        response = client.get("/echo/")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.headers["X-Lab-Trace"],
            "trace.enter>middleware.raise>trace.exit",
        )

    def test_concurrent_requests_keep_correlation_context_isolated(self) -> None:
        identifiers = [f"request-{index}" for index in range(8)]

        def request(identifier: str) -> tuple[str, str]:
            response = Client().get("/echo/", headers={"X-Correlation-ID": identifier})
            return response.headers["X-Correlation-ID"], response.headers["X-Lab-Trace"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(request, identifiers))

        self.assertEqual([item[0] for item in responses], identifiers)
        self.assertEqual(
            {item[1] for item in responses},
            {"trace.enter>guard.pass>view.echo>trace.exit"},
        )


class MiddlewareAndHttpTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.workflow = Workflow.objects.create(name="HTTP experiment")
        add_step(
            self.workflow,
            operation=WorkflowStep.Operation.SCALE,
            parameter=Decimal("2"),
        )

    def test_request_trace_records_order_and_correlation(self) -> None:
        response = self.client.get(
            reverse("home"),
            headers={"X-Correlation-ID": "experiment-42"},
        )
        self.assertEqual(response.headers["X-Correlation-ID"], "experiment-42")
        self.assertEqual(
            response.headers["X-Lab-Trace"],
            "trace.enter>guard.pass>view.home>trace.exit",
        )
        self.assertIn("app;dur=", response.headers["Server-Timing"])

    def test_invalid_correlation_id_is_not_reflected(self) -> None:
        response = self.client.get(
            reverse("home"),
            headers={"X-Correlation-ID": "bad value\nsecond-header"},
        )
        self.assertNotEqual(response.headers["X-Correlation-ID"], "bad value\nsecond-header")
        self.assertEqual(len(response.headers["X-Correlation-ID"]), 32)

    def test_middleware_can_short_circuit_before_view(self) -> None:
        response = self.client.get(reverse("home"), headers={"X-Lab-Short-Circuit": "1"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.headers["X-Lab-Trace"],
            "trace.enter>guard.block>trace.exit",
        )

    def test_htmx_step_submission_returns_fragment(self) -> None:
        response = self.client.post(
            reverse("step-new", args=[self.workflow.id]),
            {"operation": "summarize", "parameter": ""},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="step-editor"')
        self.assertNotContains(response, "<!doctype html>")
        self.assertEqual(self.workflow.steps.count(), 2)

    def test_invalid_dynamic_form_is_visible_and_not_persisted(self) -> None:
        response = self.client.post(
            reverse("step-new", args=[self.workflow.id]),
            {"operation": "scale", "parameter": ""},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This operation requires a parameter")
        self.assertEqual(self.workflow.steps.count(), 1)

    def test_csrf_is_required_for_state_change(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        detail = csrf_client.get(reverse("workflow-detail", args=[self.workflow.id]))
        token = detail.cookies["csrftoken"].value
        rejected = csrf_client.post(
            reverse("step-new", args=[self.workflow.id]),
            {"operation": "summarize", "parameter": ""},
        )
        accepted = csrf_client.post(
            reverse("step-new", args=[self.workflow.id]),
            {"operation": "summarize", "parameter": "", "csrfmiddlewaretoken": token},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(
            rejected.headers["X-Lab-Trace"],
            "trace.enter>guard.pass>trace.exit",
        )

    def test_duplicate_and_conflicting_posts_have_distinct_outcomes(self) -> None:
        url = reverse("workflow-admit", args=[self.workflow.id])
        first = self.client.post(
            url,
            {"input_values": "1, 2", "idempotency_key": "http-duplicate"},
            headers={"HX-Request": "true"},
        )
        duplicate = self.client.post(
            url,
            {"input_values": "1.0, 2.0", "idempotency_key": "http-duplicate"},
            headers={"HX-Request": "true"},
        )
        conflict = self.client.post(
            url,
            {"input_values": "9", "idempotency_key": "http-duplicate"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertContains(duplicate, "Existing authoritative job returned")
        self.assertEqual(conflict.status_code, 409)
        self.assertContains(conflict, "already bound to different input", status_code=409)
        self.assertEqual(Job.objects.count(), 1)

    def test_result_cache_separates_full_page_and_htmx_fragment(self) -> None:
        job = admit_job(self.workflow, [Decimal("1"), Decimal("2")], "cache-test").job
        job = execute_job(job.id)
        url = reverse("job-result", args=[job.id])

        page_miss = self.client.get(url)
        page_hit = self.client.get(url)
        fragment_miss = self.client.get(url, headers={"HX-Request": "true"})
        fragment_hit = self.client.get(url, headers={"HX-Request": "true"})

        self.assertEqual(page_miss.headers["X-Lab-Cache"], "MISS")
        self.assertEqual(page_hit.headers["X-Lab-Cache"], "HIT")
        self.assertEqual(fragment_miss.headers["X-Lab-Cache"], "MISS")
        self.assertEqual(fragment_hit.headers["X-Lab-Cache"], "HIT")
        self.assertIn("HX-Request", page_miss.headers["Vary"])
        self.assertEqual(page_miss.headers["Cache-Control"], "private, max-age=60")
        self.assertContains(page_miss, "<!doctype html>")
        self.assertNotContains(fragment_miss, "<!doctype html>")

    def test_mutable_job_state_is_never_served_as_result(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "not-finished").job
        response = self.client.get(reverse("job-result", args=[job.id]))
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("X-Lab-Cache", response.headers)

    def test_cache_reset_and_distinct_immutable_results_do_not_cross_contaminate(self) -> None:
        first = execute_job(admit_job(self.workflow, [Decimal("1")], "cache-first").job.id)
        second = execute_job(admit_job(self.workflow, [Decimal("9")], "cache-second").job.id)
        first_url = reverse("job-result", args=[first.id])
        second_url = reverse("job-result", args=[second.id])

        first_miss = self.client.get(first_url)
        second_miss = self.client.get(second_url)
        first_hit = self.client.get(first_url)
        cache.clear()
        first_after_reset = self.client.get(first_url)

        self.assertEqual(first_miss.headers["X-Lab-Cache"], "MISS")
        self.assertEqual(second_miss.headers["X-Lab-Cache"], "MISS")
        self.assertEqual(first_hit.headers["X-Lab-Cache"], "HIT")
        self.assertEqual(first_after_reset.headers["X-Lab-Cache"], "MISS")
        self.assertContains(first_miss, "2")
        self.assertContains(second_miss, "18")

    def test_failed_and_interrupted_jobs_never_enter_result_cache(self) -> None:
        failing_workflow = Workflow.objects.create(name="Cache failure")
        add_step(
            failing_workflow,
            operation=WorkflowStep.Operation.FAIL_ONCE,
            parameter=None,
        )
        failed = execute_job(admit_job(failing_workflow, [Decimal("1")], "cache-failed").job.id)
        interrupted = admit_job(self.workflow, [Decimal("2")], "cache-interrupted").job
        claim_job(interrupted.id)
        Job.objects.filter(pk=interrupted.id).update(
            updated_at=timezone.now() - timedelta(minutes=5)
        )
        recover_stale_jobs(0)

        for job in (failed, interrupted):
            response = self.client.get(reverse("job-result", args=[job.id]))
            self.assertEqual(response.status_code, 409)
            self.assertNotIn("X-Lab-Cache", response.headers)
