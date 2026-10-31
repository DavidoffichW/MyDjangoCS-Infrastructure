from decimal import Decimal

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from workflows.models import Job, Workflow, WorkflowStep
from workflows.services import add_step, admit_job, execute_job


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
        self.assertContains(page_miss, "<!doctype html>")
        self.assertNotContains(fragment_miss, "<!doctype html>")

    def test_mutable_job_state_is_never_served_as_result(self) -> None:
        job = admit_job(self.workflow, [Decimal("1")], "not-finished").job
        response = self.client.get(reverse("job-result", args=[job.id]))
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("X-Lab-Cache", response.headers)
