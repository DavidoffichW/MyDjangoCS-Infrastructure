"""Typed failures exposed by the deterministic foundation."""


class FoundationError(ValueError):
    """Base class for rejected foundation inputs and operations."""


class CanonicalizationError(FoundationError):
    """Input cannot be represented by the restricted canonical profile."""


class SchemaError(FoundationError):
    """Evidence or a versioned contract is structurally invalid."""


class IntegrityError(FoundationError):
    """Stored or reconstructed content does not match its identity."""


class ComputationError(FoundationError):
    """A declared deterministic computation cannot be evaluated."""


class MemoryContractError(RuntimeError):
    """Managed-memory ownership or lifecycle contract was violated."""


class BorrowConflict(MemoryContractError):
    """A requested borrow conflicts with an active borrow."""


class StaleHandle(MemoryContractError):
    """A handle no longer identifies a live allocation generation."""


class ArtifactError(RuntimeError):
    """Artifact publication or verification failed."""


class AdmissionError(FoundationError):
    """An investigation failed a named verification stage."""

    def __init__(self, stage: str, code: str, message: str) -> None:
        self.stage = stage
        self.code = code
        super().__init__(message)
