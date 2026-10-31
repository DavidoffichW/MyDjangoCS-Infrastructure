from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Workflow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name


class WorkflowStep(models.Model):
    class Operation(models.TextChoices):
        VALIDATE_NONNEGATIVE = "validate_nonnegative", "Validate non-negative values"
        SCALE = "scale", "Scale every value"
        OFFSET = "offset", "Offset every value"
        SUMMARIZE = "summarize", "Calculate summary"
        FAIL_ONCE = "fail_once", "Inject one controlled failure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(Workflow, related_name="steps", on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    operation = models.CharField(max_length=32, choices=Operation.choices)
    parameter = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "position"],
                name="workflow_step_position_unique",
            )
        ]


class ArtifactRecord(models.Model):
    class State(models.TextChoices):
        REGISTERED = "registered", "Registered"
        MISSING = "missing", "Missing"
        CORRUPT = "corrupt", "Corrupt"

    identity = models.CharField(primary_key=True, max_length=128)
    artifact_type = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=100)
    payload_digest = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.REGISTERED)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "identity"]


class ResearchRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    evidence_content_identity = models.CharField(max_length=128)
    evidence_provenance_identity = models.CharField(max_length=128)
    manifest_identity = models.CharField(max_length=128, unique=True)
    state_identity = models.CharField(max_length=128)
    evidence_artifact = models.ForeignKey(
        ArtifactRecord,
        related_name="evidence_runs",
        on_delete=models.PROTECT,
    )
    manifest_artifact = models.ForeignKey(
        ArtifactRecord,
        related_name="manifest_runs",
        on_delete=models.PROTECT,
    )
    state_artifact = models.ForeignKey(
        ArtifactRecord,
        related_name="state_runs",
        on_delete=models.PROTECT,
    )
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]

    IMMUTABLE_FIELDS = (
        "evidence_content_identity",
        "evidence_provenance_identity",
        "manifest_identity",
        "state_identity",
        "evidence_artifact_id",
        "manifest_artifact_id",
        "state_artifact_id",
    )

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            stored = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS).first()
            if stored and any(
                stored[field] != getattr(self, field) for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Research-run authority fields are immutable.")
        super().save(*args, **kwargs)


class InvestigationRecord(models.Model):
    class State(models.TextChoices):
        VERIFIED = "verified", "Verified"
        ADMITTED = "admitted", "Admitted"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity = models.CharField(max_length=128, unique=True)
    research_run = models.ForeignKey(
        ResearchRun,
        related_name="investigations",
        on_delete=models.PROTECT,
    )
    declaration = models.JSONField()
    state = models.CharField(max_length=16, choices=State.choices)
    rejection_stage = models.CharField(max_length=32, blank=True)
    rejection_code = models.CharField(max_length=64, blank=True)
    rejection_message = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]


class AdmissionRecord(models.Model):
    identity = models.CharField(primary_key=True, max_length=128)
    investigation = models.OneToOneField(
        InvestigationRecord,
        related_name="admission",
        on_delete=models.PROTECT,
    )
    state_identity = models.CharField(max_length=128)
    computation_identity = models.CharField(max_length=128, unique=True)
    declaration = models.JSONField()
    resource_envelope = models.JSONField()
    authorization_state = models.CharField(max_length=16, default="admitted")
    created_at = models.DateTimeField(auto_now_add=True)

    IMMUTABLE_FIELDS = (
        "investigation_id",
        "state_identity",
        "computation_identity",
        "declaration",
        "resource_envelope",
        "authorization_state",
    )

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            stored = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS).first()
            if stored and any(
                stored[field] != getattr(self, field) for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Admission records are immutable.")
        super().save(*args, **kwargs)


class Job(models.Model):
    class State(models.TextChoices):
        ADMITTED = "admitted", "Admitted"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        INTERRUPTED = "interrupted", "Interrupted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        related_name="jobs",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    admission = models.ForeignKey(
        AdmissionRecord,
        related_name="jobs",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=100, unique=True)
    command_version = models.CharField(max_length=40)
    input_digest = models.CharField(max_length=64)
    workflow_snapshot = models.JSONField()
    input_values = models.JSONField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.ADMITTED)
    attempts = models.PositiveIntegerField(default=0)
    revision = models.PositiveIntegerField(default=0)
    result = models.JSONField(null=True, blank=True)
    result_digest = models.CharField(max_length=64, blank=True)
    result_artifact_identity = models.CharField(max_length=128, blank=True)
    claim_generation = models.PositiveIntegerField(default=0)
    owner_token = models.CharField(max_length=64, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    state__in=[
                        "admitted",
                        "running",
                        "succeeded",
                        "failed",
                        "interrupted",
                    ]
                ),
                name="job_state_valid",
            ),
            models.CheckConstraint(
                condition=(Q(state="succeeded", result__isnull=False) & ~Q(result_digest=""))
                | (~Q(state="succeeded") & Q(result__isnull=True) & Q(result_digest="")),
                name="job_result_matches_success_state",
            ),
            models.CheckConstraint(
                condition=(Q(workflow__isnull=False) & Q(admission__isnull=True))
                | (Q(workflow__isnull=True) & Q(admission__isnull=False)),
                name="job_has_one_command_authority",
            ),
            models.CheckConstraint(
                condition=~Q(state="succeeded")
                | Q(admission__isnull=True)
                | ~Q(result_artifact_identity=""),
                name="scientific_success_has_artifact",
            ),
        ]

    IMMUTABLE_COMMAND_FIELDS = (
        "workflow_id",
        "admission_id",
        "command_version",
        "input_digest",
        "workflow_snapshot",
        "input_values",
    )

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            stored = (
                type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_COMMAND_FIELDS).first()
            )
            if stored is not None:
                changed = [
                    field
                    for field in self.IMMUTABLE_COMMAND_FIELDS
                    if stored[field] != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        f"Admitted command fields are immutable: {', '.join(changed)}."
                    )
        super().save(*args, **kwargs)


class ExecutionAttempt(models.Model):
    job = models.ForeignKey(Job, related_name="execution_attempts", on_delete=models.CASCADE)
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16)
    evidence = models.JSONField(default=dict)
    attempt_identity = models.CharField(max_length=128, blank=True)
    claim_generation = models.PositiveIntegerField(default=0)
    owner_token = models.CharField(max_length=64, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "number"],
                name="job_attempt_number_unique",
            ),
            models.CheckConstraint(
                condition=Q(state__in=["running", "succeeded", "failed", "interrupted"]),
                name="execution_attempt_state_valid",
            ),
            models.CheckConstraint(
                condition=Q(state="running", finished_at__isnull=True)
                | (~Q(state="running") & Q(finished_at__isnull=False)),
                name="execution_attempt_finish_matches_state",
            ),
        ]


class JobEvent(models.Model):
    job = models.ForeignKey(Job, related_name="events", on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField()
    from_state = models.CharField(max_length=16, blank=True)
    to_state = models.CharField(max_length=16)
    reason = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["job", "sequence"], name="job_event_sequence_unique")
        ]
