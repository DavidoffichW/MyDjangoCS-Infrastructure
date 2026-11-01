"""Structural and identity verification for reconstructed state."""

from foundation.contracts.errors import IntegrityError
from foundation.contracts.identities import identity_for

from .records import STATE_SCHEMA, ReconstructedState


def verify_state(state: ReconstructedState) -> None:
    expected = str(identity_for("semantic-state", STATE_SCHEMA, state.semantic_dict()))
    if state.identity != expected:
        raise IntegrityError("Reconstructed state identity does not match its semantic content.")
    entity_ids = {item.identity for item in state.entities}
    if len(entity_ids) != len(state.entities):
        raise IntegrityError("Reconstructed entity identities are not unique.")
    if any(
        item.source_entity not in entity_ids or item.target_entity not in entity_ids
        for item in state.edges
    ):
        raise IntegrityError("Reconstructed state contains a dangling relationship.")
    if any(item.entity_identity not in entity_ids for item in state.observations):
        raise IntegrityError("Reconstructed observation refers to an unknown entity.")
