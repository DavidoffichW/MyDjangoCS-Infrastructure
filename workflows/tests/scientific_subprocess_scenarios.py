from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reliability_lab.settings")

import django

django.setup()

from django.core.management import call_command  # noqa: E402

from services.scientific import (  # noqa: E402
    admit_investigation,
    default_investigation,
    execute_scientific_job,
    interrupt_scientific_job,
    reconcile_artifacts,
    seed_reference_run,
)
from services.scientific.composition import foundation_api  # noqa: E402
from services.workflows import requeue_job  # noqa: E402
from workflows.models import (  # noqa: E402
    AdmissionRecord,
    ArtifactRecord,
    InvestigationRecord,
    Job,
    ResearchRun,
)


def emit(value) -> None:
    print(json.dumps(value, default=str, sort_keys=True), flush=True)


def migrate() -> None:
    call_command("migrate", verbosity=0, interactive=False)
    emit({"migrated": True})


def seed() -> None:
    run, created = seed_reference_run()
    emit({"created": created, "run_id": str(run.id), "state_identity": run.state_identity})


def admit() -> None:
    run = ResearchRun.objects.get()
    result = admit_investigation(run, default_investigation(run), "scientific-crash-probe")
    emit({"job_id": str(result.job.id), "state_identity": run.state_identity})


def initialize() -> None:
    call_command("migrate", verbosity=0, interactive=False)
    seed()
    admit()


def inspect(job_id: str | None) -> None:
    job = Job.objects.filter(pk=job_id).first() if job_id else None
    emit(
        {
            "admissions": AdmissionRecord.objects.count(),
            "artifact_records": ArtifactRecord.objects.count(),
            "attempts": (
                list(
                    job.execution_attempts.values(
                        "number",
                        "state",
                        "attempt_identity",
                        "claim_generation",
                        "finished_at",
                    )
                )
                if job
                else []
            ),
            "events": list(job.events.values("sequence", "to_state")) if job else [],
            "investigations": InvestigationRecord.objects.count(),
            "job": (
                {
                    "claim_generation": job.claim_generation,
                    "owner_token": job.owner_token,
                    "result": job.result,
                    "result_artifact_identity": job.result_artifact_identity,
                    "state": job.state,
                }
                if job
                else None
            ),
            "jobs": Job.objects.count(),
            "runs": ResearchRun.objects.count(),
            "store_digests": list(foundation_api().store.iter_digests()),
        }
    )


def execute(job_id: str) -> None:
    job = execute_scientific_job(job_id)
    emit({"result_identity": job.result["identity"], "state": job.state})


def recover(job_id: str) -> None:
    job = Job.objects.get(pk=job_id)
    recovered = interrupt_scientific_job(
        job.id,
        owner_token=job.owner_token,
        confirmed_worker_stopped=True,
    )
    emit({"state": recovered.state})


def requeue(job_id: str) -> None:
    emit({"state": requeue_job(job_id).state})


def reconcile() -> None:
    emit(reconcile_artifacts())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action")
    parser.add_argument("--job-id")
    args = parser.parse_args()
    actions = {
        "admit": lambda: admit(),
        "execute": lambda: execute(args.job_id),
        "initialize": lambda: initialize(),
        "inspect": lambda: inspect(args.job_id),
        "migrate": lambda: migrate(),
        "reconcile": lambda: reconcile(),
        "recover": lambda: recover(args.job_id),
        "requeue": lambda: requeue(args.job_id),
        "seed": lambda: seed(),
    }
    actions[args.action]()


if __name__ == "__main__":
    main()
