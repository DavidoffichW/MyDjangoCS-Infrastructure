from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

from django.test import Client, TestCase
from django.urls import reverse

from workflows.models import Job
from workflows.scientific_services import (
    _artifact_reference,
    default_investigation,
    foundation_api,
    seed_reference_run,
)


def form_payload(key="browser-science"):
    return {
        "end": "2026-01-01T03:00:00Z",
        "idempotency_key": key,
        "max_records": "100",
        "max_targets": "4",
        "method": "time-window-mean/1",
        "missing_policy": "exclude",
        "start": "2026-01-01T00:00:00Z",
        "target_sensors": ["sensor_alpha", "sensor_bravo"],
    }


class ScientificHttpTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = self.settings(ARTIFACT_STORE_ROOT=Path(self.directory.name))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.run, _ = seed_reference_run()

    def test_browser_path_opens_state_admits_executes_and_reads_result(self):
        response = self.client.get(reverse("lab-run", args=[self.run.id]))
        self.assertContains(response, "Verified semantic state")
        self.assertContains(response, self.run.state_identity)

        response = self.client.post(
            reverse("lab-admit", args=[self.run.id]),
            form_payload(),
            follow=True,
        )
        self.assertContains(response, "Current authoritative state")
        job = Job.objects.get()
        self.assertEqual(job.state, Job.State.ADMITTED)

        response = self.client.post(
            reverse("scientific-job-execute", args=[job.id]),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.SUCCEEDED)

        first = self.client.get(reverse("job-result", args=[job.id]))
        second = self.client.get(reverse("job-result", args=[job.id]))
        fragment = self.client.get(
            reverse("job-result", args=[job.id]),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(first.headers["X-Lab-Cache"], "MISS")
        self.assertEqual(second.headers["X-Lab-Cache"], "HIT")
        self.assertEqual(fragment.headers["X-Lab-Cache"], "MISS")
        self.assertContains(first, job.result["identity"])

    def test_htmx_admission_returns_bounded_fragment(self):
        response = self.client.post(
            reverse("lab-admit", args=[self.run.id]),
            form_payload("htmx-science"),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admission committed")
        self.assertNotContains(response, "<!doctype html>")

    def test_versioned_api_requires_csrf_and_returns_structured_envelopes(self):
        client = Client(enforce_csrf_checks=True)
        page = client.get(reverse("lab-run", args=[self.run.id]))
        self.assertEqual(page.status_code, 200)
        token = client.cookies["csrftoken"].value
        payload = json.dumps(
            {
                "declaration": default_investigation(self.run),
                "idempotency_key": "api-science",
            },
            separators=(",", ":"),
        )
        rejected = Client(enforce_csrf_checks=True).post(
            reverse("api-admit", args=[self.run.id]),
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 403)
        admitted = client.post(
            reverse("api-admit", args=[self.run.id]),
            data=payload,
            content_type="application/json",
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(admitted.status_code, 201)
        self.assertTrue(admitted.json()["ok"])
        self.assertEqual(admitted.json()["api_version"], "mydjangocs.http-api/1")

        duplicate = client.post(
            reverse("api-admit", args=[self.run.id]),
            data=payload,
            content_type="application/json",
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["data"]["duplicate"])

    def test_api_rejects_duplicate_json_keys_and_incomplete_closure(self):
        duplicate_keys = (
            '{"declaration":{},"declaration":{},"idempotency_key":"duplicate-json"}'
        )
        response = self.client.post(
            reverse("api-admit", args=[self.run.id]),
            data=duplicate_keys,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_JSON")

        response = self.client.post(
            reverse("api-admit", args=[self.run.id]),
            data=json.dumps(
                {
                    "declaration": {"schema_version": "mydjangocs.investigation/1"},
                    "idempotency_key": "incomplete",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_CONTRACT")

        invalid_key = self.client.post(
            reverse("api-admit", args=[self.run.id]),
            data=json.dumps(
                {"declaration": default_investigation(self.run), "idempotency_key": 42}
            ),
            content_type="application/json",
        )
        self.assertEqual(invalid_key.status_code, 422)
        self.assertEqual(invalid_key.json()["error"]["code"], "INVALID_IDEMPOTENCY_KEY")

    def test_missing_api_resources_use_versioned_error_envelopes(self):
        state = self.client.get(reverse("api-state", args=[uuid4()]))
        result = self.client.get(reverse("api-job-result", args=[uuid4()]))
        self.assertEqual(state.status_code, 404)
        self.assertEqual(state.json()["error"]["code"], "RUN_NOT_FOUND")
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json()["error"]["code"], "JOB_NOT_FOUND")

    def test_corrupt_result_artifact_fails_closed_before_cache(self):
        self.client.post(reverse("lab-admit", args=[self.run.id]), form_payload())
        job = Job.objects.get()
        self.client.post(reverse("scientific-job-execute", args=[job.id]))
        job.refresh_from_db()
        record = job.result_artifact_identity
        artifact = job.admission.investigation.research_run.state_artifact
        result_record = type(artifact).objects.get(pk=record)
        reference = foundation_api().store.path_for(_artifact_reference(result_record))
        reference.write_bytes(b"corrupt")
        response = self.client.get(reverse("job-result", args=[job.id]))
        self.assertEqual(response.status_code, 409)

    def test_state_api_returns_verified_semantic_payload(self):
        response = self.client.get(reverse("api-state", args=[self.run.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["identity"], self.run.state_identity)
