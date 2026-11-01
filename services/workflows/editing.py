"""Transactional workflow-step editing and revision control."""

from decimal import Decimal

from django.db import transaction
from django.db.models import F, Max

from workflows.models import Workflow, WorkflowStep

from .contracts import MAX_STEPS, WorkflowValidationError


def add_step(workflow: Workflow, *, operation: str, parameter: Decimal | None) -> WorkflowStep:
    with transaction.atomic():
        locked = Workflow.objects.select_for_update().get(pk=workflow.pk)
        last = locked.steps.aggregate(maximum=Max("position"))["maximum"] or 0
        if last >= MAX_STEPS:
            raise WorkflowValidationError(f"A workflow may contain at most {MAX_STEPS} operations.")
        step = WorkflowStep.objects.create(
            workflow=locked, position=last + 1, operation=operation, parameter=parameter
        )
        Workflow.objects.filter(pk=locked.pk).update(revision=F("revision") + 1)
    return step


def update_step(step: WorkflowStep, *, operation: str, parameter: Decimal | None) -> None:
    with transaction.atomic():
        locked = WorkflowStep.objects.select_for_update().select_related("workflow").get(pk=step.pk)
        locked.operation = operation
        locked.parameter = parameter
        locked.save(update_fields=["operation", "parameter", "updated_at"])
        Workflow.objects.filter(pk=locked.workflow_id).update(revision=F("revision") + 1)


def remove_step(step: WorkflowStep) -> None:
    with transaction.atomic():
        locked = WorkflowStep.objects.select_for_update().select_related("workflow").get(pk=step.pk)
        workflow_id, position = locked.workflow_id, locked.position
        locked.delete()
        WorkflowStep.objects.filter(workflow_id=workflow_id, position__gt=position).update(
            position=F("position") - 1
        )
        Workflow.objects.filter(pk=workflow_id).update(revision=F("revision") + 1)


def move_step(step: WorkflowStep, direction: str) -> None:
    delta = -1 if direction == "up" else 1 if direction == "down" else 0
    if not delta:
        raise WorkflowValidationError("Direction must be 'up' or 'down'.")
    with transaction.atomic():
        locked = WorkflowStep.objects.select_for_update().select_related("workflow").get(pk=step.pk)
        try:
            target = WorkflowStep.objects.select_for_update().get(
                workflow_id=locked.workflow_id, position=locked.position + delta
            )
        except WorkflowStep.DoesNotExist:
            return
        original_position = locked.position
        locked.position = 0
        locked.save(update_fields=["position", "updated_at"])
        target.position = original_position
        target.save(update_fields=["position", "updated_at"])
        locked.position = original_position + delta
        locked.save(update_fields=["position", "updated_at"])
        Workflow.objects.filter(pk=locked.workflow_id).update(revision=F("revision") + 1)
