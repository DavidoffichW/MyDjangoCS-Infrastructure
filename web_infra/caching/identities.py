"""Cache identities remain subordinate to authoritative results."""

from services.scientific.results import result_cache_identity
from workflows.models import Job


def result_representation_key(job: Job, variant: str) -> str:
    identity = (
        result_cache_identity(job, variant)
        if job.admission_id
        else f"legacy:{job.id}:{job.result_digest}:{variant}"
    )
    return f"result:{identity}"
