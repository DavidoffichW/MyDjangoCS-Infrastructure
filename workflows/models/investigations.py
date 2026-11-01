import uuid

from django.core.exceptions import ValidationError
from django.db import models

from .artifacts import ResearchRun


class InvestigationRecord(models.Model):
    class State(models.TextChoices):
        VERIFIED = "verified", "Verified"
        ADMITTED = "admitted", "Admitted"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity = models.CharField(max_length=128, unique=True)
    research_run = models.ForeignKey(
        ResearchRun, related_name="investigations", on_delete=models.PROTECT
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
        InvestigationRecord, related_name="admission", on_delete=models.PROTECT
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
