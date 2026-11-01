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
                fields=["workflow", "position"], name="workflow_step_position_unique"
            )
        ]
