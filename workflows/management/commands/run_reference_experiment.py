from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from services.scientific import (
    admit_investigation,
    default_investigation,
    execute_scientific_job,
    seed_reference_run,
    verify_scientific_result,
)
from workflows.models import Job


class Command(BaseCommand):
    help = "Run and replay the fictional end-to-end deterministic experiment."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--idempotency-prefix",
            default="reference-experiment",
            help="Bounded prefix used for the primary run and independent replay.",
        )

    def handle(self, *args, **options) -> None:
        prefix = options["idempotency_prefix"]
        if not prefix or len(prefix) > 80:
            self.stderr.write("The idempotency prefix must contain 1 to 80 characters.")
            raise SystemExit(2)
        research_run, _ = seed_reference_run()
        declaration = default_investigation(research_run)
        outcomes = []
        for suffix in ("primary", "replay"):
            admitted = admit_investigation(
                research_run,
                declaration,
                f"{prefix}-{suffix}",
            )
            job = admitted.job
            if job.state == Job.State.ADMITTED:
                job = execute_scientific_job(job.id)
            payload = verify_scientific_result(job)
            outcomes.append(
                {
                    "attempts": job.attempts,
                    "job_id": str(job.id),
                    "result_identity": payload["identity"],
                    "state": job.state,
                }
            )
        output = {
            "manifest_identity": research_run.manifest_identity,
            "replay_identical": outcomes[0]["result_identity"] == outcomes[1]["result_identity"],
            "runs": outcomes,
            "state_identity": research_run.state_identity,
        }
        self.stdout.write(json.dumps(output, indent=2, sort_keys=True))
