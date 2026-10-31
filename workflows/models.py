from __future__ import annotations

import uuid

from django.db import models


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


class Job(models.Model):
    class State(models.TextChoices):
        ADMITTED = "admitted", "Admitted"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        INTERRUPTED = "interrupted", "Interrupted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(Workflow, related_name="jobs", on_delete=models.PROTECT)
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
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]


class ExecutionAttempt(models.Model):
    job = models.ForeignKey(Job, related_name="execution_attempts", on_delete=models.CASCADE)
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16)
    evidence = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "number"],
                name="job_attempt_number_unique",
            )
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
