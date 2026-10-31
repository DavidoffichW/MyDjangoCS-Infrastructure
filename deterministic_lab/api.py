"""Stable Python API composing foundation contracts and artifact preservation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, parse_json_strict
from .governance import Admission, VerificationPipeline
from .identities import identity_for
from .methods import execute_method
from .reconstruction import (
    DeclaredManifest,
    ReconstructedState,
    RegisteredEvidence,
    declare_manifest,
    load_state,
    reconstruct_state,
    register_evidence,
    verify_state,
)
from .store import ArtifactRef, ContentAddressedStore

API_VERSION = "mydjangocs.foundation-api/1"


@dataclass(frozen=True, slots=True)
class ExperimentArtifacts:
    evidence: ArtifactRef
    manifest: ArtifactRef
    state: ArtifactRef


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    payload: dict[str, Any]
    identity: str
    artifact: ArtifactRef


class FoundationAPI:
    """Django-independent authority for evidence, state and pure computation."""

    def __init__(self, store_root: Path) -> None:
        self.store = ContentAddressedStore(store_root)

    def register_evidence(self, raw: dict[str, Any]) -> tuple[RegisteredEvidence, ArtifactRef]:
        registered = register_evidence(raw)
        reference = self.store.publish(
            "evidence",
            registered.bundle.schema_version,
            registered.canonical_payload,
        )
        return registered, reference

    def declare_manifest(
        self, evidence: RegisteredEvidence
    ) -> tuple[DeclaredManifest, ArtifactRef]:
        manifest = declare_manifest(evidence)
        reference = self.store.publish(
            "manifest",
            manifest.schema_version,
            canonical_bytes(manifest.to_dict()),
        )
        return manifest, reference

    def reconstruct_state(
        self,
        evidence: RegisteredEvidence,
        manifest: DeclaredManifest,
    ) -> tuple[ReconstructedState, ArtifactRef]:
        state = reconstruct_state(evidence, manifest)
        reference = self.store.publish(
            "state",
            state.schema_version,
            canonical_bytes(state.to_dict()),
        )
        return state, reference

    def build_state(
        self, raw: dict[str, Any]
    ) -> tuple[
        RegisteredEvidence,
        DeclaredManifest,
        ReconstructedState,
        ExperimentArtifacts,
    ]:
        evidence, evidence_ref = self.register_evidence(raw)
        manifest, manifest_ref = self.declare_manifest(evidence)
        state, state_ref = self.reconstruct_state(evidence, manifest)
        return evidence, manifest, state, ExperimentArtifacts(evidence_ref, manifest_ref, state_ref)

    def load_state(self, reference: ArtifactRef) -> ReconstructedState:
        raw = parse_json_strict(self.store.load(reference))
        state = load_state(raw)
        verify_state(state)
        return state

    def admit(
        self,
        declaration: dict[str, Any],
        state_loader,
    ) -> tuple[Admission, ReconstructedState]:
        return VerificationPipeline(state_loader).admit(declaration)

    def execute(self, admission: Admission, state: ReconstructedState) -> ExecutionResult:
        verify_state(state)
        if admission.state_identity != state.identity:
            raise ValueError("Admission is not bound to the supplied state.")
        result = execute_method(state, admission.declaration)
        payload = {
            "admission_identity": admission.identity,
            "computation_identity": admission.computation_identity,
            "output_schema": "mydjangocs.result/1",
            "result": result,
            "state_identity": state.identity,
        }
        identity = str(identity_for("result", "mydjangocs.result/1", payload))
        artifact = self.store.publish(
            "result",
            "mydjangocs.result/1",
            canonical_bytes({**payload, "identity": identity}),
        )
        return ExecutionResult(payload=payload, identity=identity, artifact=artifact)
