from django.core.management.base import BaseCommand

from services.workflows import execute_next_job


class Command(BaseCommand):
    help = "Execute admitted jobs with one foreground worker."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--once", action="store_true", help="Run at most one job.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum jobs per invocation.")

    def handle(self, *args, **options) -> None:
        limit = 1 if options["once"] else max(0, options["limit"])
        processed = 0
        while processed < limit:
            job = execute_next_job()
            if job is None:
                break
            processed += 1
            self.stdout.write(f"{job.id} {job.state}")
        self.stdout.write(self.style.SUCCESS(f"Processed {processed} job(s)."))
