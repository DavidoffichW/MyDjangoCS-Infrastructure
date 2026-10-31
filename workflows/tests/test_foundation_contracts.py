from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

from django.test import SimpleTestCase

from deterministic_lab.canonical import (
    CanonicalizationError,
    canonical_bytes,
    canonical_decimal,
    normalize_timestamp,
    parse_json_strict,
)
from deterministic_lab.corpus import invalid_evidence_cases, reference_evidence
from deterministic_lab.governance import (
    INVESTIGATION_SCHEMA,
    OUTPUT_SCHEMA,
    AdmissionError,
    VerificationPipeline,
)
from deterministic_lab.identities import identity_for
from deterministic_lab.methods import (
    NEIGHBOR_METHOD,
    NUMERIC_POLICY,
    TIME_WINDOW_METHOD,
    graph_neighborhood_mean,
    time_window_mean,
)
from deterministic_lab.reconstruction import (
    declare_manifest,
    load_state,
    reconstruct_state,
    register_evidence,
)
from deterministic_lab.schema import SchemaError

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "conformance_vectors.json").read_text(encoding="utf-8")
)


def build_state(source_id: str = "synthetic_source_a"):
    evidence = register_evidence(reference_evidence(source_id=source_id))
    manifest = declare_manifest(evidence)
    return evidence, manifest, reconstruct_state(evidence, manifest)


def investigation(state_identity: str, **overrides):
    value = {
        "method": TIME_WINDOW_METHOD,
        "method_parameters": {},
        "missing_policy": "exclude",
        "numeric_policy": NUMERIC_POLICY,
        "output_schema": OUTPUT_SCHEMA,
        "resource_budget": {"max_records": 100, "max_targets": 4},
        "schema_version": INVESTIGATION_SCHEMA,
        "state_identity": state_identity,
        "target_sensors": ["sensor_alpha", "sensor_bravo"],
        "temporal_scope": {
            "end": "2026-01-01T03:00:00Z",
            "start": "2026-01-01T00:00:00Z",
        },
        "unit": "synthetic_unit",
        "variable_id": "signal",
    }
    value.update(overrides)
    return value


class CanonicalContractTests(SimpleTestCase):
    def test_independent_golden_canonical_vector_and_identity(self):
        vector = GOLDEN["canonical"]
        self.assertEqual(canonical_bytes(vector["input"]), vector["bytes_utf8"].encode())
        self.assertEqual(
            str(identity_for("golden", "mydjangocs.golden/1", vector["input"])),
            vector["identity"],
        )

    def test_duplicate_keys_floats_and_invalid_unicode_are_rejected(self):
        with self.assertRaises(CanonicalizationError):
            parse_json_strict('{"a":1,"a":2}')
        with self.assertRaises(CanonicalizationError):
            parse_json_strict('{"value":1.5}')
        with self.assertRaises(CanonicalizationError):
            canonical_bytes({"value": "\ud800"})

    def test_decimal_policy_normalizes_signed_zero_without_rounding(self):
        self.assertEqual(canonical_decimal("-0.000"), "0")
        self.assertEqual(canonical_decimal("1200.3400"), "1200.34")
        with self.assertRaises(CanonicalizationError):
            canonical_decimal("NaN")

    def test_fractional_timestamp_normalization_preserves_utc_precision(self):
        self.assertEqual(
            normalize_timestamp("2026-01-01T03:00:00.123400+03:00"),
            "2026-01-01T00:00:00.1234Z",
        )


class ReconstructionContractTests(SimpleTestCase):
    def test_provenance_changes_without_changing_semantic_state(self):
        first_evidence, first_manifest, first_state = build_state("synthetic_source_a")
        second_evidence, second_manifest, second_state = build_state("synthetic_source_b")
        self.assertEqual(first_evidence.content_identity, second_evidence.content_identity)
        self.assertNotEqual(first_evidence.provenance_identity, second_evidence.provenance_identity)
        self.assertNotEqual(first_manifest.identity, second_manifest.identity)
        self.assertEqual(first_state.identity, second_state.identity)

    def test_meaning_change_changes_evidence_and_state_identity(self):
        original_evidence, _, original_state = build_state()
        changed = reference_evidence()
        changed["observations"][0]["value"] = "10.5"
        changed_evidence = register_evidence(changed)
        changed_state = reconstruct_state(changed_evidence, declare_manifest(changed_evidence))
        self.assertNotEqual(original_evidence.content_identity, changed_evidence.content_identity)
        self.assertNotEqual(original_state.identity, changed_state.identity)

    def test_state_round_trip_is_verified_and_interface_is_immutable(self):
        _, _, state = build_state()
        loaded = load_state(state.to_dict())
        self.assertEqual(loaded, state)
        with self.assertRaises(FrozenInstanceError):
            loaded.identity = "changed"

    def test_invalid_reference_cases_fail_before_reconstruction(self):
        for case in invalid_evidence_cases().values():
            with self.subTest(case=case), self.assertRaises(SchemaError):
                register_evidence(case)


class NumericalOracleTests(SimpleTestCase):
    def setUp(self):
        _, _, self.state = build_state()

    def test_time_window_means_match_independent_decimal_calculation(self):
        result = time_window_mean(
            self.state,
            target_sensors=("sensor_alpha", "sensor_bravo"),
            variable_id="signal",
            unit="synthetic_unit",
            start="2026-01-01T00:00:00Z",
            end="2026-01-01T03:00:00Z",
            missing_policy="exclude",
        )
        values = {item["sensor_id"]: item["value"] for item in result["results"]}
        self.assertEqual(values["sensor_alpha"], GOLDEN["numerical"]["alpha_time_window_mean"])
        self.assertEqual(
            values["sensor_bravo"],
            GOLDEN["numerical"]["bravo_time_window_mean_excluding_missing"],
        )

    def test_graph_mean_matches_independent_weighted_reference(self):
        result = graph_neighborhood_mean(
            self.state,
            target_sensor="sensor_alpha",
            variable_id="signal",
            unit="synthetic_unit",
            start="2026-01-01T00:00:00Z",
            end="2026-01-01T03:00:00Z",
            missing_policy="exclude",
            max_hops=1,
        )
        self.assertEqual(
            result["value"],
            GOLDEN["numerical"]["alpha_one_hop_weighted_mean_excluding_missing"],
        )
        self.assertEqual(result["missing_count"], 1)


class InvestigationGovernanceTests(SimpleTestCase):
    def setUp(self):
        _, _, self.state = build_state()
        self.pipeline = VerificationPipeline(
            lambda identity: self.state
            if identity == self.state.identity
            else (_ for _ in ()).throw(KeyError(identity))
        )

    def test_complete_investigation_binds_state_method_and_authorization(self):
        admission, state = self.pipeline.admit(investigation(self.state.identity))
        self.assertEqual(state.identity, self.state.identity)
        self.assertEqual(admission.authorization_state, "admitted")
        self.assertEqual(admission.state_identity, self.state.identity)
        self.assertIn("computation:sha256:", admission.computation_identity)

    def test_each_verification_boundary_rejects_invalid_declarations(self):
        cases = [
            ({"schema_version": INVESTIGATION_SCHEMA}, "structural"),
            (investigation("state:sha256:" + "0" * 64), "state"),
            (investigation(self.state.identity, target_sensors=["unknown"]), "semantic"),
            (investigation(self.state.identity, method="unknown/1"), "method"),
            (
                investigation(
                    self.state.identity,
                    resource_budget={"max_records": 1, "max_targets": 1},
                ),
                "resource",
            ),
        ]
        for declaration, stage in cases:
            with self.subTest(stage=stage):
                with self.assertRaises(AdmissionError) as raised:
                    self.pipeline.admit(declaration)
                self.assertEqual(raised.exception.stage, stage)

    def test_malformed_budget_values_are_controlled_structural_rejections(self):
        raw = investigation(
            self.state.identity,
            resource_budget={"max_records": "many", "max_targets": 4},
        )
        with self.assertRaises(AdmissionError) as raised:
            self.pipeline.admit(raw)
        self.assertEqual(raised.exception.stage, "structural")

    def test_graph_method_requires_explicit_one_hop_policy(self):
        raw = investigation(
            self.state.identity,
            method=NEIGHBOR_METHOD,
            method_parameters={"max_hops": 2},
            target_sensors=["sensor_alpha"],
        )
        with self.assertRaises(AdmissionError) as raised:
            self.pipeline.admit(raw)
        self.assertEqual(raised.exception.code, "INVALID_PARAMETERS")

    def test_reordered_unordered_targets_have_one_investigation_identity(self):
        first, _ = self.pipeline.verify(investigation(self.state.identity))
        second_raw = deepcopy(investigation(self.state.identity))
        second_raw["target_sensors"] = list(reversed(second_raw["target_sensors"]))
        second, _ = self.pipeline.verify(second_raw)
        self.assertEqual(first.identity, second.identity)
