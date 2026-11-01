import uuid

from django.core.exceptions import ValidationError
from django.db import models


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
        ArtifactRecord, related_name="evidence_runs", on_delete=models.PROTECT
    )
    manifest_artifact = models.ForeignKey(
        ArtifactRecord, related_name="manifest_runs", on_delete=models.PROTECT
    )
    state_artifact = models.ForeignKey(
        ArtifactRecord, related_name="state_runs", on_delete=models.PROTECT
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
