from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


class ScientificProcessCrashTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="scientific-crash-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = {
            **os.environ,
            "DJANGO_DB_PATH": str(self.root / "probe.sqlite3"),
            "DJANGO_DEBUG": "0",
            "LAB_ARTIFACT_STORE": str(self.root / "artifacts"),
        }

    def command(self, action: str, *extra: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "workflows.tests.scientific_subprocess_scenarios",
            action,
            *extra,
        ]

    def run_probe(
        self,
        action: str,
        *extra: str,
        crash_point: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        environment = dict(self.environment)
        if crash_point:
            environment["LAB_CRASH_POINT"] = crash_point
        return subprocess.run(
            self.command(action, *extra),
            check=check,
            capture_output=True,
            env=environment,
            text=True,
            timeout=25,
        )

    def initialize(self) -> str:
        result = self.run_probe("initialize")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1])["job_id"]

    def inspect(self, job_id: str | None = None) -> dict:
        extra = ("--job-id", job_id) if job_id else ()
        return json.loads(self.run_probe("inspect", *extra).stdout)

    def test_state_publication_without_database_registration_is_reconciled_as_orphan(self):
        self.run_probe("migrate")
        crashed = self.run_probe(
            "seed",
            crash_point="after_state_artifact_publication",
            check=False,
        )
        self.assertEqual(crashed.returncode, 87)
        inventory = self.inspect()
        self.assertEqual(inventory["runs"], 0)
        self.assertEqual(inventory["artifact_records"], 0)
        self.assertEqual(len(inventory["store_digests"]), 3)
        report = json.loads(self.run_probe("reconcile").stdout)
        self.assertEqual(len(report["orphans"]), 3)

    def test_admission_process_death_rolls_back_all_authority_rows(self):
        self.run_probe("migrate")
        self.run_probe("seed")
        crashed = self.run_probe(
            "admit",
            crash_point="before_admission_commit",
            check=False,
        )
        self.assertEqual(crashed.returncode, 88)
        inventory = self.inspect()
        self.assertEqual(inventory["jobs"], 0)
        self.assertEqual(inventory["admissions"], 0)
        self.assertEqual(inventory["investigations"], 0)

    def test_death_before_result_publication_fails_closed(self):
        job_id = self.initialize()
        crashed = self.run_probe(
            "execute",
            "--job-id",
            job_id,
            crash_point="before_result_publication",
            check=False,
        )
        self.assertEqual(crashed.returncode, 89)
        state = self.inspect(job_id)
        self.assertEqual(state["job"]["state"], "running")
        self.assertEqual(state["job"]["result"], None)
        self.assertEqual(len(state["store_digests"]), 3)

    def test_published_result_without_database_commit_is_recoverable_orphan(self):
        job_id = self.initialize()
        crashed = self.run_probe(
            "execute",
            "--job-id",
            job_id,
            crash_point="after_artifact_publication",
            check=False,
        )
        self.assertEqual(crashed.returncode, 91)
        state = self.inspect(job_id)
        self.assertEqual(state["job"]["state"], "running")
        self.assertEqual(state["artifact_records"], 3)
        self.assertEqual(len(state["store_digests"]), 4)
        report = json.loads(self.run_probe("reconcile").stdout)
        self.assertEqual(len(report["orphans"]), 1)

        self.run_probe("recover", "--job-id", job_id)
        self.run_probe("requeue", "--job-id", job_id)
        executed = json.loads(self.run_probe("execute", "--job-id", job_id).stdout)
        self.assertEqual(executed["state"], "succeeded")
        self.assertEqual(
            self.inspect(job_id)["job"]["result"]["identity"],
            executed["result_identity"],
        )

    def test_process_death_after_result_commit_preserves_one_success(self):
        job_id = self.initialize()
        crashed = self.run_probe(
            "execute",
            "--job-id",
            job_id,
            crash_point="after_result_commit",
            check=False,
        )
        self.assertEqual(crashed.returncode, 93)
        state = self.inspect(job_id)
        self.assertEqual(state["job"]["state"], "succeeded")
        self.assertTrue(state["job"]["result_artifact_identity"])
        self.assertEqual([item["state"] for item in state["attempts"]], ["succeeded"])
        self.assertEqual(
            [item["to_state"] for item in state["events"]],
            ["admitted", "running", "succeeded"],
        )

    def test_process_death_during_recovery_rolls_back_interruption(self):
        job_id = self.initialize()
        self.run_probe(
            "execute",
            "--job-id",
            job_id,
            crash_point="before_result_publication",
            check=False,
        )
        crashed = self.run_probe(
            "recover",
            "--job-id",
            job_id,
            crash_point="during_scientific_recovery",
            check=False,
        )
        self.assertEqual(crashed.returncode, 94)
        self.assertEqual(self.inspect(job_id)["job"]["state"], "running")
        recovered = json.loads(self.run_probe("recover", "--job-id", job_id).stdout)
        self.assertEqual(recovered["state"], "interrupted")
