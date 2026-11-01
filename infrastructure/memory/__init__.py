"""Bounded ownership, borrowing, and generation-safe handles."""

from .arena import MemoryArena
from .borrowing import Borrow
from .handles import Handle

__all__ = ["Borrow", "Handle", "MemoryArena"]
