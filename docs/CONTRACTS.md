# Deterministic foundation contracts

## Canonical JSON profile

Version: `mydjangocs.canonical-json/1`.

The profile accepts JSON nulls, booleans, signed 64-bit integers, strings, arrays, and
objects with string keys. It emits compact UTF-8 JSON and orders keys by UTF-16 code units.
Parsing rejects duplicate object keys, floating-point tokens, invalid UTF-8, unpaired
surrogates, and unsupported values.

Scientific decimals are schema-defined strings. They must be finite, bounded, and within
the declared fractional precision. Redundant fractional zeroes are removed and all signed
zero forms become `"0"`. The profile does not normalize Unicode: NFC and NFD strings remain
different source values. Timestamps require an explicit offset and normalize to UTC with a
`Z` suffix while preserving significant microseconds.

This is a restricted profile informed by RFC 8785. It deliberately excludes the RFC's
binary floating-point number serialization and does not claim general JCS compatibility.

## Identity construction

Every identity is displayed as:

```text
<domain>:sha256:<hex digest of canonical versioned envelope>
```

The digest input is the unambiguous byte framing
`mydjangocs\0<domain>\0<schema>\0<canonical payload>`. Domains prevent identical payload
bytes in unrelated contracts from sharing meaning. Schema versions are identity inputs;
compatibility is explicit rather than inferred.

## Evidence and reconstruction

Evidence v1 accepts at most 5,000 observations and 10,000 relationships. Identifiers are
portable bounded names. Each observation declares source, sensor, timestamp, variable,
value, unit, missing flag, quality, provenance, and schema version. Missingness is explicit:
null and `missing=true` must agree. Relationships cannot be self-referential, duplicated, or
point to an unknown sensor.

Reconstruction sorts inputs, derives stable entity and edge identities, separates semantic
content from provenance, and returns frozen Python records. It does not infer a relationship
from proximity. Verification recomputes the complete state identity before use.

## Numerical methods

The implemented methods are `time-window-mean/1` and `graph-neighborhood-mean/1`.
Both use decimal precision 28, `ROUND_HALF_EVEN`, and six output decimal places. Missing
values are either excluded or propagated as declared. The graph method accepts exactly one
target and one explicit hop; weights come only from declared edges.

These methods are transparent reference computations, not validated scientific models.

## Managed-memory arena

The arena owns byte storage and exposes generation-safe handles, not raw addresses.

- Allocation types are `u8`, `i64`, and `f64`; total bytes cannot exceed the arena quota.
- Multiple scoped shared readers may coexist.
- One scoped exclusive writer requires no readers or writer and only a mutable allocation.
- Sealing forbids later mutation and returns owned immutable bytes.
- Release requires no borrows, invalidates the generation, and returns the slot for reuse.
- Expired borrow tokens and stale handles fail deterministically.

No writable `memoryview`, pointer, or buffer escapes the arena. The implementation is an
ownership experiment inside Python; it is not a substitute for process isolation.

## Portable observation format

The binary format is a file/interchange contract, not a native ABI. All fields are
little-endian with standard sizes and no native alignment.

Header (`<8sHHII32s`, 52 bytes):

| Offset | Size | Field |
|---:|---:|---|
| 0 | 8 | magic `MDSOBS\0\0` |
| 8 | 2 | format version (`1`) |
| 10 | 2 | flags (`0`) |
| 12 | 4 | record count |
| 16 | 4 | payload length |
| 20 | 32 | SHA-256 of the record payload |

Record (`<16sqqBB6x`, 40 bytes): sensor identifier, UTC epoch milliseconds, signed
fixed-point value at scale 1,000,000, missing flag, quality code, and six reserved zero
bytes. Sensor identifiers are at most 15 ASCII bytes. Missing values use an explicit
signed-64 sentinel which must agree with the missing flag. Sub-millisecond timestamps are
rejected rather than truncated. Decoders validate magic, version, flags, counts, length,
checksum, codes, and missingness before returning records.

## Artifact preservation

Artifacts are immutable non-empty byte strings no larger than 8 MiB by default. A reference
binds type, schema version, size, SHA-256 payload digest, and a domain-separated artifact
identity. Reads are incremental and bounded; size, digest, and identity are all reverified.
The store never treats a cache entry or database row as a substitute for missing bytes.

## Investigation verification

Admission runs five named stages in order:

1. **structural** — exact fields, versions, value shapes, timestamp and numeric policy;
2. **state** — load and reverify the declared semantic state;
3. **semantic** — targets, variable/unit, and time window exist and agree;
4. **method** — versioned method, parameters, and missing policy are supported;
5. **resource** — selected records and targets fit the declared bounded envelope.

Each rejection has a stable stage and code. Authorization exists only after all five stages
complete.

## Stable Python and HTTP surfaces

`deterministic_lab.FoundationAPI` is the Django-independent composition root. Its API version
is `mydjangocs.foundation-api/1`.

The HTTP adapter exposes:

- `GET /api/v1/runs/<run>/state/`
- `POST /api/v1/runs/<run>/admit/`
- `GET /api/v1/jobs/<job>/result/`

All are bounded by the same schemas and services as the HTML path. State and result reads
reverify preservation bytes before returning success.
