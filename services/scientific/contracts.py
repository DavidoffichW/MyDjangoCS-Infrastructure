"""Application-level records for scientific admission and fenced claims."""

from dataclasses import dataclass
from uuid import UUID

from workflows.models import InvestigationRecord, Job


@dataclass(frozen=True, slots=True)
class ScientificAdmissionResult:
    job: Job
    investigation: InvestigationRecord
    duplicate: bool


@dataclass(frozen=True, slots=True)
class ScientificClaim:
    job_id: UUID
    attempt_number: int
    claim_generation: int
    owner_token: str
    attempt_identity: str
