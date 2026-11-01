from __future__ import annotations

import argparse
import json
import os
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reliability_lab.settings")

import django

django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from infrastructure.orchestration import claim_job  # noqa: E402
from services.workflows import (  # noqa: E402
    add_step,
    admit_job,
    execute_job,
    recover_stale_jobs,
)
from workflows.models import Job, Workflow, WorkflowStep  # noqa: E402


def initialize() -> None:
    call_command("migrate", verbosity=0, interactive=False)
    workflow = Workflow.objects.create(name="Crash experiment")
    add_step(workflow, operation=WorkflowStep.Operation.SCALE, parameter=Decimal("2"))
    add_step(workflow, operation=WorkflowStep.Operation.SUMMARIZE, parameter=None)
    job = admit_job(workflow, [Decimal("1"), Decimal("2")], "crash-experiment").job
    print(json.dumps({"job_id": str(job.id), "input_digest": job.input_digest}), flush=True)


def inspect(job_id: str) -> None:
    job = Job.objects.get(pk=job_id)
    print(
        json.dumps(
            {
                "attempts": list(
                    job.execution_attempts.values("number", "state", "finished_at", "evidence")
                ),
                "command_version": job.command_version,
                "events": list(job.events.values("sequence", "from_state", "to_state", "reason")),
                "failure_code": job.failure_code,
                "input_digest": job.input_digest,
                "job_attempts": job.attempts,
                "result": job.result,
                "result_digest": job.result_digest,
                "revision": job.revision,
                "state": job.state,
                "workflow_snapshot": job.workflow_snapshot,
            },
            default=str,
            sort_keys=True,
        ),
        flush=True,
    )


def signal(marker: str) -> None:
    Path(marker).write_text("ready", encoding="utf-8")


def crash_before_claim_commit(job_id: str, marker: str) -> None:
    with transaction.atomic():
        claim_job(job_id)
        signal(marker)
        os._exit(81)


def crash_after_claim(job_id: str, marker: str) -> None:
    claim_job(job_id)
    signal(marker)
    os._exit(82)


def crash_during_calculation(job_id: str, marker: str) -> None:
    import services.workflows.execution as execution

    def calculation_window(job, attempt_number):
        signal(marker)
        time.sleep(30)
        return {"evidence": [], "summary": None, "values": job.input_values}

    execution.run_operations = calculation_window
    execute_job(job_id)


def crash_before_finalization(job_id: str, marker: str) -> None:
    import services.workflows.execution as execution

    def finalization_window(*args, **kwargs):
        signal(marker)
        time.sleep(30)

    execution.finish_workflow_job = finalization_window
    execute_job(job_id)


def crash_after_success(job_id: str, marker: str) -> None:
    execute_job(job_id)
    signal(marker)
    os._exit(83)


def age(job_id: str) -> None:
    Job.objects.filter(pk=job_id).update(updated_at=timezone.now() - timedelta(minutes=5))


def recovery_window(job_id: str, marker: str) -> None:
    with transaction.atomic():
        recover_stale_jobs(0, confirmed_worker_stopped=True)
        signal(marker)
        time.sleep(30)


def recover() -> None:
    print(
        json.dumps([str(item) for item in recover_stale_jobs(0, confirmed_worker_stopped=True)]),
        flush=True,
    )


def admit_copy(job_id: str) -> None:
    source = Job.objects.get(pk=job_id)
    copy = admit_job(
        source.workflow,
        [Decimal(value) for value in source.input_values],
        "independent-replay-copy",
    ).job
    print(json.dumps({"job_id": str(copy.id)}), flush=True)


def execute(job_id: str) -> None:
    execute_job(job_id)
    inspect(job_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action")
    parser.add_argument("--job-id")
    parser.add_argument("--marker")
    args = parser.parse_args()

    actions = {
        "initialize": lambda: initialize(),
        "inspect": lambda: inspect(args.job_id),
        "crash-before-claim-commit": lambda: crash_before_claim_commit(args.job_id, args.marker),
        "crash-after-claim": lambda: crash_after_claim(args.job_id, args.marker),
        "crash-during-calculation": lambda: crash_during_calculation(args.job_id, args.marker),
        "crash-before-finalization": lambda: crash_before_finalization(args.job_id, args.marker),
        "crash-after-success": lambda: crash_after_success(args.job_id, args.marker),
        "age": lambda: age(args.job_id),
        "recovery-window": lambda: recovery_window(args.job_id, args.marker),
        "recover": lambda: recover(),
        "admit-copy": lambda: admit_copy(args.job_id),
        "execute": lambda: execute(args.job_id),
    }
    actions[args.action]()


if __name__ == "__main__":
    main()
