"""Scoped mediated access to memory owned by an arena."""

from __future__ import annotations

from typing import Protocol

from foundation.contracts.errors import MemoryContractError

from .handles import Handle


class ArenaOwner(Protocol):
    def _read(self, token: Borrow, offset: int, length: int | None) -> bytes: ...

    def _write(self, token: Borrow, offset: int, data: bytes) -> None: ...


class Borrow:
    """A scoped token that never exposes a writable memoryview."""

    def __init__(self, arena: ArenaOwner, handle: Handle, writable: bool) -> None:
        self._arena = arena
        self._handle = handle
        self._writable = writable
        self._active = True

    def read(self, offset: int = 0, length: int | None = None) -> bytes:
        return self._arena._read(self, offset, length)

    def write(self, offset: int, data: bytes) -> None:
        if not self._writable:
            raise MemoryContractError("A shared borrow cannot write.")
        self._arena._write(self, offset, data)

    def _expire(self) -> None:
        self._active = False
