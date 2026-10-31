# Conformance vectors and reproduction

The checked-in vectors live in
`workflows/tests/golden/conformance_vectors.json`. They are ordinary public synthetic data
and are intentionally small enough to verify with an independent implementation.

## Canonical vector

Input:

```json
{
  "schema_version": "mydjangocs.golden/1",
  "label": "alpha",
  "values": ["1", "0", "-2.5"]
}
```

Canonical UTF-8 text:

```json
{"label":"alpha","schema_version":"mydjangocs.golden/1","values":["1","0","-2.5"]}
```

Expected identity:

```text
golden:sha256:17eaa71dfe284d45bfa13bffd977fa6f19daf4b576cada3cea026b5e66ea4083
```

The test suite checks the bytes and domain-separated identity. The SHA-256 value was also
recomputed with the Windows .NET cryptography implementation rather than importing the
project's identity function.

## Numerical vectors

| Computation | Expected value |
|---|---:|
| Sensor Alpha time-window mean | `11.5` |
| Sensor Bravo mean, explicit missing excluded | `21.333333` |
| Sensor Alpha one-hop weighted mean, explicit missing excluded | `20.511628` |

The expected values are fixed independent Decimal calculations. Tests compare them against
the public method functions and verify counts and missingness.

## Binary vector properties

Binary tests assert the 52-byte header and 40-byte record sizes, fixed magic/version/flags,
little-endian record interpretation, record-count/length agreement, and payload SHA-256.
Bit corruption, truncation, unknown flags, inconsistent missingness, and unsupported
timestamp precision are rejected.

## Execute the conformance checks

```powershell
.\.venv\Scripts\python.exe manage.py test `
  workflows.tests.test_foundation_contracts `
  workflows.tests.test_memory_binary_store `
  workflows.tests.test_architecture_boundaries -v 2
```

For the full persisted experiment:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py run_reference_experiment
.\.venv\Scripts\python.exe manage.py reconcile_artifacts
```

Expected properties, not hard-coded database IDs, are:

- two independent jobs succeed;
- both report the same result identity;
- all registered evidence, manifest, state, and result artifacts verify;
- reconciliation reports no missing, corrupt, or orphaned blocks.

The exact UUIDs and elapsed times are intentionally not conformance values.
