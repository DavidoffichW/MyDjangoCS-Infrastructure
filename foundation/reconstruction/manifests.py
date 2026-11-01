"""Declared rules binding evidence to one reconstruction contract."""

from foundation.contracts.identities import identity_for

from .records import MANIFEST_SCHEMA, DeclaredManifest, RegisteredEvidence

RECONSTRUCTION_RULES = (
    ("entity_rule", "sensor-identity-v1"),
    ("missing_value_rule", "preserve-null-v1"),
    ("relationship_rule", "undirected-explicit-v1"),
)


def declare_manifest(evidence: RegisteredEvidence) -> DeclaredManifest:
    payload = {
        "evidence_content_identity": evidence.content_identity,
        "evidence_provenance_identity": evidence.provenance_identity,
        "rules": dict(RECONSTRUCTION_RULES),
        "schema_version": MANIFEST_SCHEMA,
    }
    return DeclaredManifest(
        identity=str(identity_for("manifest", MANIFEST_SCHEMA, payload)),
        evidence_content_identity=evidence.content_identity,
        evidence_provenance_identity=evidence.provenance_identity,
        rules=RECONSTRUCTION_RULES,
    )
