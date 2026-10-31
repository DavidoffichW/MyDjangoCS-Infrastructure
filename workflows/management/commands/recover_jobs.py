from django.core.management.base import BaseCommand, CommandError

from workflows.services import recover_stale_jobs


class Command(BaseCommand):
    help = "Mark stale running jobs as interrupted for explicit operator retry."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--older-than-seconds", type=int, default=60)

    def handle(self, *args, **options) -> None:
        age = options["older_than_seconds"]
        if age < 0:
            raise CommandError("--older-than-seconds cannot be negative")
        recovered = recover_stale_jobs(age)
        for job_id in recovered:
            self.stdout.write(f"recovered {job_id}")
        self.stdout.write(self.style.SUCCESS(f"Recovered {len(recovered)} job(s)."))
