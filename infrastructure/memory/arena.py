"""Bounded in-process memory arena and ownership state machine."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock

from foundation.contracts.errors import BorrowConflict, MemoryContractError, StaleHandle

from .borrowing import Borrow
from .handles import Handle

_ELEMENT_SIZES = {"u8": 1, "i64": 8, "f64": 8}


@dataclass(slots=True)
class _Allocation:
    generation: int
    element_type: str
    count: int
    data: bytearray
    state: str = "mutable"
    readers: int = 0
    writer: bool = False


class MemoryArena:
    """A bounded arena with generation-safe handles and scoped borrows."""

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        if max_bytes <= 0:
            raise MemoryContractError("Arena quota must be positive.")
        self.max_bytes = max_bytes
        self.allocated_bytes = 0
        self._allocations: dict[int, _Allocation] = {}
        self._generations: dict[int, int] = {}
        self._free_slots: list[int] = []
        self._next_slot = 0
        self._lock = RLock()

    def allocate(self, element_type: str, count: int) -> Handle:
        if element_type not in _ELEMENT_SIZES:
            raise MemoryContractError("Unsupported arena element type.")
        if not isinstance(count, int) or count <= 0:
            raise MemoryContractError("Allocation count must be a positive integer.")
        size = _ELEMENT_SIZES[element_type] * count
        with self._lock:
            if self.allocated_bytes + size > self.max_bytes:
                raise MemoryContractError("Arena allocation would exceed its byte quota.")
            slot = self._free_slots.pop() if self._free_slots else self._next_slot
            if slot == self._next_slot:
                self._next_slot += 1
            generation = self._generations.get(slot, 0) + 1
            self._generations[slot] = generation
            self._allocations[slot] = _Allocation(
                generation=generation,
                element_type=element_type,
                count=count,
                data=bytearray(size),
            )
            self.allocated_bytes += size
            return Handle(slot=slot, generation=generation)

    def _allocation(self, handle: Handle) -> _Allocation:
        allocation = self._allocations.get(handle.slot)
        if allocation is None or allocation.generation != handle.generation:
            raise StaleHandle("Handle does not identify a live allocation generation.")
        return allocation

    @contextmanager
    def shared(self, handle: Handle) -> Iterator[Borrow]:
        with self._lock:
            allocation = self._allocation(handle)
            if allocation.state == "released" or allocation.writer:
                raise BorrowConflict("Shared borrow conflicts with exclusive access.")
            allocation.readers += 1
            token = Borrow(self, handle, writable=False)
        try:
            yield token
        finally:
            with self._lock:
                if token._active:
                    allocation = self._allocation(handle)
                    allocation.readers -= 1
                    token._expire()

    @contextmanager
    def exclusive(self, handle: Handle) -> Iterator[Borrow]:
        with self._lock:
            allocation = self._allocation(handle)
            if allocation.state != "mutable":
                raise MemoryContractError("Only mutable allocations can be borrowed for writing.")
            if allocation.writer or allocation.readers:
                raise BorrowConflict("Exclusive borrow requires no active readers or writer.")
            allocation.writer = True
            token = Borrow(self, handle, writable=True)
        try:
            yield token
        finally:
            with self._lock:
                if token._active:
                    allocation = self._allocation(handle)
                    allocation.writer = False
                    token._expire()

    def _checked_token(self, token: Borrow) -> _Allocation:
        if not token._active or token._arena is not self:
            raise MemoryContractError("Borrow token has expired or belongs to another arena.")
        return self._allocation(token._handle)

    def _read(self, token: Borrow, offset: int, length: int | None) -> bytes:
        with self._lock:
            allocation = self._checked_token(token)
            if offset < 0 or offset > len(allocation.data):
                raise MemoryContractError("Read offset is outside the allocation.")
            size = len(allocation.data) - offset if length is None else length
            if size < 0 or offset + size > len(allocation.data):
                raise MemoryContractError("Read range is outside the allocation.")
            return bytes(allocation.data[offset : offset + size])

    def _write(self, token: Borrow, offset: int, data: bytes) -> None:
        with self._lock:
            allocation = self._checked_token(token)
            if not token._writable or allocation.state != "mutable":
                raise MemoryContractError("Borrow does not authorize mutation.")
            if not isinstance(data, bytes):
                raise MemoryContractError("Writes must use owned immutable bytes.")
            if offset < 0 or offset + len(data) > len(allocation.data):
                raise MemoryContractError("Write range is outside the allocation.")
            allocation.data[offset : offset + len(data)] = data

    def seal(self, handle: Handle) -> bytes:
        with self._lock:
            allocation = self._allocation(handle)
            if allocation.readers or allocation.writer:
                raise BorrowConflict("Allocation cannot be sealed while borrowed.")
            if allocation.state != "mutable":
                raise MemoryContractError("Only a mutable allocation can be sealed.")
            allocation.state = "sealed"
            return bytes(allocation.data)

    def release(self, handle: Handle) -> None:
        with self._lock:
            allocation = self._allocation(handle)
            if allocation.readers or allocation.writer:
                raise BorrowConflict("Allocation cannot be released while borrowed.")
            size = len(allocation.data)
            allocation.state = "released"
            del self._allocations[handle.slot]
            self._free_slots.append(handle.slot)
            self.allocated_bytes -= size

    def describe(self, handle: Handle) -> dict[str, int | str | bool]:
        with self._lock:
            allocation = self._allocation(handle)
            return {
                "bytes": len(allocation.data),
                "element_type": allocation.element_type,
                "generation": allocation.generation,
                "readers": allocation.readers,
                "state": allocation.state,
                "writer": allocation.writer,
            }
