import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Workflow",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("revision", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="WorkflowStep",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("position", models.PositiveIntegerField()),
                (
                    "operation",
                    models.CharField(
                        choices=[
                            ("validate_nonnegative", "Validate non-negative values"),
                            ("scale", "Scale every value"),
                            ("offset", "Offset every value"),
                            ("summarize", "Calculate summary"),
                            ("fail_once", "Inject one controlled failure"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "parameter",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "workflow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="workflows.workflow",
                    ),
                ),
            ],
            options={"ordering": ["position", "id"]},
        ),
        migrations.CreateModel(
            name="Job",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=100, unique=True)),
                ("command_version", models.CharField(max_length=40)),
                ("input_digest", models.CharField(max_length=64)),
                ("workflow_snapshot", models.JSONField()),
                ("input_values", models.JSONField()),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("admitted", "Admitted"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("interrupted", "Interrupted"),
                        ],
                        default="admitted",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("revision", models.PositiveIntegerField(default=0)),
                ("result", models.JSONField(blank=True, null=True)),
                ("result_digest", models.CharField(blank=True, max_length=64)),
                ("failure_code", models.CharField(blank=True, max_length=64)),
                ("failure_message", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "workflow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jobs",
                        to="workflows.workflow",
                    ),
                ),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="ExecutionAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.PositiveIntegerField()),
                ("state", models.CharField(max_length=16)),
                ("evidence", models.JSONField(default=dict)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="execution_attempts",
                        to="workflows.job",
                    ),
                ),
            ],
            options={"ordering": ["number"]},
        ),
        migrations.CreateModel(
            name="JobEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("sequence", models.PositiveIntegerField()),
                ("from_state", models.CharField(blank=True, max_length=16)),
                ("to_state", models.CharField(max_length=16)),
                ("reason", models.CharField(max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="workflows.job",
                    ),
                ),
            ],
            options={"ordering": ["sequence"]},
        ),
        migrations.AddConstraint(
            model_name="workflowstep",
            constraint=models.UniqueConstraint(
                fields=("workflow", "position"),
                name="workflow_step_position_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="executionattempt",
            constraint=models.UniqueConstraint(
                fields=("job", "number"),
                name="job_attempt_number_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="jobevent",
            constraint=models.UniqueConstraint(
                fields=("job", "sequence"),
                name="job_event_sequence_unique",
            ),
        ),
    ]
