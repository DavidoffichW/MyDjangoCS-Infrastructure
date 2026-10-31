from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from django.test import SimpleTestCase


class ProcessCrashRecoveryTests(SimpleTestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="reliability-crash-")
        self.root = Path(self.temporary.name)
        self.database = self.root / "probe.sqlite3"
        self.environment = {
            **os.environ,
            "DJANGO_DB_PATH": str(self.database),
            "DJANGO_DEBUG": "0",
        }
        initialized = self.run_probe("initialize")
        identity = json.loads(initialized.stdout)
        self.job_id = identity["job_id"]
        self.input_digest = identity["input_digest"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(self, action: str, *extra: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "workflows.tests.subprocess_scenarios",
            action,
            *extra,
        ]

    def run_probe(self, action: str, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.command(action, *extra),
            check=True,
            capture_output=True,
            env=self.environment,
            text=True,
            timeout=20,
        )

    def inspect(self) -> dict:
        result = self.run_probe("inspect", "--job-id", self.job_id)
        return json.loads(result.stdout)

    def terminate_at_marker(self, action: str) -> int:
        marker = self.root / f"{action}.marker"
        process = subprocess.Popen(
            self.command(
                action,
                "--job-id",
                self.job_id,
                "--marker",
                str(marker),
            ),
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not marker.exists():
            if process.poll() is None:
                process.kill()
            stdout, stderr = process.communicate(timeout=5)
            self.fail(f"crash marker was not reached\nstdout: {stdout}\nstderr: {stderr}")
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        return process.returncode

    def assert_identity_unchanged(self, state: dict) -> None:
        self.assertEqual(state["input_digest"], self.input_digest)
        self.assertEqual(state["command_version"], "reliability-lab.command/1")
        self.assertEqual(state["workflow_snapshot"]["command_version"], state["command_version"])

    def test_process_exit_before_claim_commit_rolls_back_every_claim_record(self) -> None:
        returncode = self.terminate_at_marker("crash-before-claim-commit")
        state = self.inspect()

        self.assertNotEqual(returncode, 0)
        self.assertEqual(state["state"], "admitted")
        self.assertEqual(state["job_attempts"], 0)
        self.assertEqual(state["attempts"], [])
        self.assertEqual([event["to_state"] for event in state["events"]], ["admitted"])
        self.assert_identity_unchanged(state)

    def test_process_exit_after_claim_fails_closed_until_recovery(self) -> None:
        returncode = self.terminate_at_marker("crash-after-claim")
        running = self.inspect()

        self.assertNotEqual(returncode, 0)
        self.assertEqual(running["state"], "running")
        self.assertEqual(running["result"], None)
        self.assertEqual(running["attempts"][0]["state"], "running")
        self.run_probe("age", "--job-id", self.job_id)
        self.run_probe("recover")
        recovered = self.inspect()
        self.assertEqual(recovered["state"], "interrupted")
        self.assertEqual(recovered["attempts"][0]["state"], "interrupted")
        self.assert_identity_unchanged(recovered)

    def test_process_termination_during_calculation_leaves_no_result(self) -> None:
        returncode = self.terminate_at_marker("crash-during-calculation")
        running = self.inspect()

        self.assertNotEqual(returncode, 0)
        self.assertEqual(running["state"], "running")
        self.assertEqual(running["result"], None)
        self.assertEqual(running["result_digest"], "")
        self.assertEqual(
            [event["to_state"] for event in running["events"]], ["admitted", "running"]
        )

    def test_process_termination_before_finalization_leaves_no_result(self) -> None:
        returncode = self.terminate_at_marker("crash-before-finalization")
        running = self.inspect()

        self.assertNotEqual(returncode, 0)
        self.assertEqual(running["state"], "running")
        self.assertEqual(running["result"], None)
        self.assertEqual(running["result_digest"], "")
        self.assertEqual(running["attempts"][0]["state"], "running")

    def test_process_exit_after_success_commit_preserves_one_result(self) -> None:
        returncode = self.terminate_at_marker("crash-after-success")
        succeeded = self.inspect()

        self.assertNotEqual(returncode, 0)
        self.assertEqual(succeeded["state"], "succeeded")
        self.assertEqual(succeeded["result"]["values"], ["2", "4"])
        self.assertTrue(succeeded["result_digest"])
        self.assertEqual(succeeded["attempts"][0]["state"], "succeeded")
        self.assertEqual(
            [event["to_state"] for event in succeeded["events"]],
            ["admitted", "running", "succeeded"],
        )
        self.run_probe("recover")
        self.assertEqual(self.inspect(), succeeded)

    def test_process_termination_during_recovery_rolls_back_reconciliation(self) -> None:
        self.terminate_at_marker("crash-after-claim")
        self.run_probe("age", "--job-id", self.job_id)
        returncode = self.terminate_at_marker("recovery-window")
        running = self.inspect()

        self.assertNotEqual(returncode, 0)
        self.assertEqual(running["state"], "running")
        self.assertEqual(running["attempts"][0]["state"], "running")
        self.run_probe("recover")
        recovered = self.inspect()
        self.assertEqual(recovered["state"], "interrupted")
        self.assertEqual(recovered["attempts"][0]["state"], "interrupted")

    def test_independent_processes_replay_to_identical_results(self) -> None:
        copied = self.run_probe("admit-copy", "--job-id", self.job_id)
        copy_id = json.loads(copied.stdout)["job_id"]

        original = json.loads(self.run_probe("execute", "--job-id", self.job_id).stdout)
        replayed = json.loads(self.run_probe("execute", "--job-id", copy_id).stdout)

        self.assertEqual(original["result"], replayed["result"])
        self.assertEqual(original["result_digest"], replayed["result_digest"])
        self.assertEqual(original["input_digest"], replayed["input_digest"])
