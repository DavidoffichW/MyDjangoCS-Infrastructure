"""Explicit verification pipeline and admission identity."""

from collections.abc import Callable, Mapping
from typing import Any

from foundation.contracts.errors import AdmissionError
from foundation.contracts.identities import identity_for
from foundation.contracts.numeric_policy import NUMERIC_POLICY
from foundation.reconstruction import ReconstructedState, verify_state

from .closure import close_investigation
from .contracts import ADMISSION_SCHEMA, Admission, Investigation
from .verification import verify_investigation


class VerificationPipeline:
    """Structural, state, semantic, method, and resource admission stages."""

    def __init__(self, state_loader: Callable[[str], ReconstructedState]) -> None:
        self.state_loader = state_loader

    def verify(self, raw: Mapping[str, Any]) -> tuple[Investigation, ReconstructedState]:
        investigation = close_investigation(raw)
        try:
            state = self.state_loader(investigation.state_identity)
            verify_state(state)
        except Exception as exc:
            raise AdmissionError(
                "state", "STATE_UNAVAILABLE", "Verified state is unavailable."
            ) from exc
        verify_investigation(investigation, state)
        return investigation, state

    def admit(self, raw: Mapping[str, Any]) -> tuple[Admission, ReconstructedState]:
        investigation, state = self.verify(raw)
        computation_payload = {
            "investigation_identity": investigation.identity,
            "method": investigation.method,
            "numeric_policy": NUMERIC_POLICY,
            "state_identity": state.identity,
        }
        computation_identity = str(
            identity_for("computation", "mydjangocs.computation/1", computation_payload)
        )
        admission_payload = {
            "authorization_state": "admitted",
            "computation_identity": computation_identity,
            "investigation_identity": investigation.identity,
            "schema_version": ADMISSION_SCHEMA,
            "state_identity": state.identity,
        }
        admission = Admission(
            identity=str(identity_for("admission", ADMISSION_SCHEMA, admission_payload)),
            investigation_identity=investigation.identity,
            state_identity=state.identity,
            computation_identity=computation_identity,
            declaration=investigation.declaration(include_identity=True),
        )
        return admission, state
