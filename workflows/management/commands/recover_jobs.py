from django.core.management.base import BaseCommand, CommandError

from workflows.services import InvalidTransition, recover_stale_jobs


class Command(BaseCommand):
    help = "Mark stale running jobs as interrupted for explicit operator retry."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--older-than-seconds", type=int, default=60)
        parser.add_argument(
            "--confirm-worker-stopped",
            action="store_true",
            help="Confirm out-of-band that the owning worker no longer runs.",
        )

    def handle(self, *args, **options) -> None:
        age = options["older_than_seconds"]
        if age < 0:
            raise CommandError("--older-than-seconds cannot be negative")
        try:
            recovered = recover_stale_jobs(
                age,
                confirmed_worker_stopped=options["confirm_worker_stopped"],
            )
        except InvalidTransition as exc:
            raise CommandError(str(exc)) from exc
        for job_id in recovered:
            self.stdout.write(f"recovered {job_id}")
        self.stdout.write(self.style.SUCCESS(f"Recovered {len(recovered)} job(s)."))
