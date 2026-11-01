"""Stable identity for one live allocation generation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Handle:
    slot: int
    generation: int
