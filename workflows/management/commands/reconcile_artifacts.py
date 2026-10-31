from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from workflows.scientific_services import reconcile_artifacts


class Command(BaseCommand):
    help = "Verify registered artifacts and report missing, corrupt, and orphaned blocks."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--quarantine-orphans",
            action="store_true",
            help="Move unregistered blocks into managed quarantine after reporting them.",
        )

    def handle(self, *args, **options) -> None:
        report = reconcile_artifacts(quarantine_orphans=options["quarantine_orphans"])
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
