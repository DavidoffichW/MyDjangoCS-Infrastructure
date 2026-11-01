"""Atomic first-writer-wins publication of immutable artifact bytes."""

import os
import tempfile
from pathlib import Path

from foundation.contracts.errors import ArtifactError


def publish_bytes(final_path: Path, payload: bytes, existing_loader) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        if existing_loader() != payload:
            raise ArtifactError("Existing artifact path does not contain identical content.")
        return
    descriptor, staged_name = tempfile.mkstemp(prefix=".stage-", dir=final_path.parent)
    staged = Path(staged_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staged, final_path)
        except FileExistsError:
            if existing_loader() != payload:
                raise ArtifactError(
                    "Concurrent publication produced conflicting content."
                ) from None
        except OSError as exc:
            raise ArtifactError("Atomic artifact publication is unavailable.") from exc
    finally:
        staged.unlink(missing_ok=True)
