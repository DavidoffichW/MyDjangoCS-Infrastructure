"""Canonical evidence admission and provenance identity."""

from collections.abc import Mapping
from typing import Any

from foundation.contracts.canonical import canonical_bytes
from foundation.contracts.identities import identity_for
from foundation.reconstruction.records import RegisteredEvidence
from foundation.schema.evidence import EvidenceBundle


def register_evidence(raw: Mapping[str, Any]) -> RegisteredEvidence:
    bundle = EvidenceBundle.from_mapping(raw)
    content_identity = str(
        identity_for("evidence-content", bundle.schema_version, bundle.semantic_dict())
    )
    provenance_identity = str(
        identity_for(
            "evidence-provenance",
            "mydjangocs.provenance/1",
            {"content_identity": content_identity, **bundle.provenance_dict()},
        )
    )
    return RegisteredEvidence(
        bundle=bundle,
        content_identity=content_identity,
        provenance_identity=provenance_identity,
        canonical_payload=canonical_bytes(bundle.to_dict()),
    )
