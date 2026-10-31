from __future__ import annotations

import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from deterministic_lab.api import FoundationAPI
from deterministic_lab.canonical import canonical_bytes
from deterministic_lab.corpus import reference_evidence
from deterministic_lab.memory import MemoryArena
from workflows.scientific_services import default_investigation


def _milliseconds(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    return {
        "iterations": len(samples),
        "median_ms": round(statistics.median(samples) * 1000, 6),
        "p95_ms": round(p95 * 1000, 6),
    }


class _Run:
    state_identity: str


class Command(BaseCommand):
    help = "Measure fixed foundation operations; this is not a scalability benchmark."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--iterations", type=int, default=25)

    def handle(self, *args, **options) -> None:
        iterations = options["iterations"]
        if iterations < 5 or iterations > 1000:
            raise CommandError("--iterations must be between 5 and 1000")
        with tempfile.TemporaryDirectory(prefix="deterministic-benchmark-") as temporary:
            api = FoundationAPI(Path(temporary))
            evidence = reference_evidence()
            cold_started = time.perf_counter()
            _, _, state, artifacts = api.build_state(evidence)
            cold_build = time.perf_counter() - cold_started
            run = _Run()
            run.state_identity = state.identity
            declaration = default_investigation(run)
            admission, _ = api.admit(declaration, lambda identity: state)
            result = api.execute(admission, state)

            canonical_samples = []
            reconstruction_samples = []
            execution_samples = []
            arena_samples = []
            artifact_read_samples = []
            for _ in range(iterations):
                started = time.perf_counter()
                canonical_bytes(declaration)
                canonical_samples.append(time.perf_counter() - started)

                started = time.perf_counter()
                api.build_state(evidence)
                reconstruction_samples.append(time.perf_counter() - started)

                started = time.perf_counter()
                api.execute(admission, state)
                execution_samples.append(time.perf_counter() - started)

                started = time.perf_counter()
                arena = MemoryArena(max_bytes=4096)
                handle = arena.allocate("u8", 4096)
                with arena.exclusive(handle) as borrow:
                    borrow.write(0, bytes(4096))
                arena.seal(handle)
                arena.release(handle)
                arena_samples.append(time.perf_counter() - started)

                started = time.perf_counter()
                api.store.load(result.artifact)
                artifact_read_samples.append(time.perf_counter() - started)

            output = {
                "artifact_read": _milliseconds(artifact_read_samples),
                "canonical_declaration": _milliseconds(canonical_samples),
                "cold_state_build_ms": round(cold_build * 1000, 6),
                "foundation_execution": _milliseconds(execution_samples),
                "memory_arena_4k": _milliseconds(arena_samples),
                "state_build_existing_store": _milliseconds(reconstruction_samples),
                "workload": {
                    "entities": len(state.entities),
                    "observations": len(state.observations),
                    "relationships": len(state.edges),
                    "result_bytes": result.artifact.size,
                    "state_bytes": artifacts.state.size,
                },
            }
            self.stdout.write(json.dumps(output, indent=2, sort_keys=True))
