"""Domain-separated identities for the laboratory contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_bytes

IDENTITY_SCHEME = "mydjangocs.identity/1"


@dataclass(frozen=True, slots=True)
class Identity:
    kind: str
    digest: str

    def __str__(self) -> str:
        return f"{self.kind}:sha256:{self.digest}"

    @classmethod
    def parse(cls, value: str) -> Identity:
        kind, algorithm, digest = value.rsplit(":", 2)
        if algorithm != "sha256" or len(digest) != 64:
            raise ValueError("Identity must use a 64-character SHA-256 digest.")
        int(digest, 16)
        return cls(kind=kind, digest=digest)


def identity_from_bytes(kind: str, schema: str, payload: bytes) -> Identity:
    prefix = b"mydjangocs\x00" + kind.encode("ascii") + b"\x00" + schema.encode("ascii") + b"\x00"
    return Identity(kind, hashlib.sha256(prefix + payload).hexdigest())


def identity_for(kind: str, schema: str, payload: Any) -> Identity:
    return identity_from_bytes(kind, schema, canonical_bytes(payload))
