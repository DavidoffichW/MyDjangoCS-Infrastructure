from __future__ import annotations

import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

from django.test import SimpleTestCase
from hypothesis import given
from hypothesis import strategies as st

from foundation.binary.observations import HEADER, decode_observations, encode_observations
from foundation.contracts.errors import (
    ArtifactError,
    BorrowConflict,
    IntegrityError,
    MemoryContractError,
    SchemaError,
    StaleHandle,
)
from foundation.evidence import register_evidence
from foundation.fixtures import reference_evidence
from infrastructure.memory import MemoryArena
from infrastructure.preservation import ContentAddressedStore


class MemoryArenaTests(SimpleTestCase):
    def test_complete_lifecycle_and_generation_reuse(self):
        arena = MemoryArena(max_bytes=32)
        first = arena.allocate("u8", 8)
        with arena.exclusive(first) as writer:
            writer.write(0, b"evidence")
        self.assertEqual(arena.seal(first), b"evidence")
        with arena.shared(first) as reader:
            self.assertEqual(reader.read(), b"evidence")
        arena.release(first)
        second = arena.allocate("u8", 8)
        self.assertEqual(second.slot, first.slot)
        self.assertGreater(second.generation, first.generation)
        with self.assertRaises(StaleHandle):
            arena.describe(first)

    def test_readers_conflict_with_writer_and_release(self):
        arena = MemoryArena(max_bytes=32)
        handle = arena.allocate("u8", 8)
        with (
            arena.shared(handle),
            arena.shared(handle),
            self.assertRaises(BorrowConflict),
            arena.exclusive(handle),
        ):
            pass
        with arena.shared(handle), self.assertRaises(BorrowConflict):
            arena.release(handle)

    def test_expired_borrow_cannot_access_or_mutate(self):
        arena = MemoryArena(max_bytes=32)
        handle = arena.allocate("u8", 8)
        with arena.exclusive(handle) as writer:
            writer.write(0, b"12345678")
        with self.assertRaises(MemoryContractError):
            writer.write(0, b"x")
        arena.seal(handle)
        with self.assertRaises(MemoryContractError), arena.exclusive(handle):
            pass

    def test_exception_releases_borrow_state(self):
        arena = MemoryArena(max_bytes=32)
        handle = arena.allocate("u8", 8)
        with self.assertRaisesRegex(RuntimeError, "injected"), arena.exclusive(handle):
            raise RuntimeError("injected")
        with arena.exclusive(handle) as writer:
            writer.write(0, b"recover!")

    def test_cross_thread_readers_are_allowed_and_writer_is_rejected(self):
        arena = MemoryArena(max_bytes=32)
        handle = arena.allocate("u8", 8)
        barrier_results = []
        readers_ready = Barrier(5)
        readers_release = Barrier(5)

        def reader():
            with arena.shared(handle) as token:
                barrier_results.append(token.read())
                readers_ready.wait(timeout=5)
                readers_release.wait(timeout=5)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(reader) for _ in range(4)]
            readers_ready.wait(timeout=5)
            with self.assertRaises(BorrowConflict), arena.exclusive(handle):
                pass
            readers_release.wait(timeout=5)
            for future in futures:
                future.result(timeout=5)
        self.assertEqual(len(barrier_results), 4)

    @given(st.binary(min_size=1, max_size=64))
    def test_owned_bytes_round_trip_property(self, payload):
        arena = MemoryArena(max_bytes=64)
        handle = arena.allocate("u8", len(payload))
        with arena.exclusive(handle) as writer:
            writer.write(0, payload)
        arena.seal(handle)
        with arena.shared(handle) as reader:
            self.assertEqual(reader.read(), payload)
        arena.release(handle)
        self.assertEqual(arena.allocated_bytes, 0)


class BinaryFormatTests(SimpleTestCase):
    def setUp(self):
        self.observations = register_evidence(reference_evidence()).bundle.observations

    def test_binary_round_trip_has_explicit_header_and_checksum(self):
        encoded = encode_observations(self.observations)
        decoded = decode_observations(encoded)
        self.assertEqual(len(decoded), len(self.observations))
        self.assertEqual(decoded[0].sensor_id, "sensor_alpha")
        payload = encoded[HEADER.size :]
        self.assertEqual(hashlib.sha256(payload).digest(), HEADER.unpack_from(encoded)[5])

    def test_checksum_and_length_corruption_are_rejected(self):
        encoded = bytearray(encode_observations(self.observations))
        encoded[-1] ^= 0x01
        with self.assertRaises(IntegrityError):
            decode_observations(bytes(encoded))
        with self.assertRaises(SchemaError):
            decode_observations(bytes(encoded[:-1]))

    def test_sub_millisecond_timestamp_is_rejected_instead_of_truncated(self):
        observation = self.observations[0]
        with self.assertRaises(SchemaError):
            encode_observations([replace(observation, timestamp="2026-01-01T00:00:00.000001Z")])


class ArtifactStoreTests(SimpleTestCase):
    def test_publication_is_idempotent_restart_safe_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_store = ContentAddressedStore(root)
            first = first_store.publish("state", "state/1", b"immutable-state")
            self.assertEqual(first_store.publish("state", "state/1", b"immutable-state"), first)
            restarted = ContentAddressedStore(root)
            self.assertEqual(restarted.load(first), b"immutable-state")
            self.assertEqual(restarted.iter_digests(), (first.digest,))

    def test_corruption_is_never_silently_substituted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ContentAddressedStore(Path(directory))
            reference = store.publish("result", "result/1", b"verified-result")
            store.path_for(reference).write_bytes(b"corrupt")
            with self.assertRaises(ArtifactError):
                store.load(reference)
            quarantined = store.quarantine_digest(reference.digest)
            self.assertTrue(quarantined.is_file())
            self.assertFalse(store.path_for(reference).exists())

    def test_bounds_and_contract_names_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ContentAddressedStore(Path(directory), max_artifact_bytes=4)
            with self.assertRaises(ArtifactError):
                store.publish("result", "result/1", b"12345")
            with self.assertRaises(ArtifactError):
                store.publish("../escape", "result/1", b"1")
