# Architecture and authority boundaries

The laboratory keeps deterministic authority independent from web delivery. Django adapts
HTTP requests and persists lifecycle records; it does not define evidence meaning, numeric
methods, canonical identities, memory rules, or artifact bytes.

```text
┌──────────────── deterministic_lab (no Django imports) ────────────────┐
│ schema → evidence registration → manifest → reconstructed state       │
│                           │                                           │
│ investigation → five-stage verification → computation → result       │
│                           │                                           │
│ memory arena · binary format · content-addressed artifact store       │
└───────────────────────────┬───────────────────────────────────────────┘
                            │ explicit adapter calls
┌──────────────── Django application ───────────────────────────────────┐
│ models + migrations │ scientific_services │ legacy workflow services │
│ worker commands     │ views/API           │ middleware/cache          │
└───────────────────────────┬───────────────────────────────────────────┘
                            │
                 HTML/HTMX browser or JSON client
```

`workflows/tests/test_architecture_boundaries.py` parses every foundation module and fails
if it imports Django, the web project, or the workflows application.

## Authority chain

| Record | Meaning | Identity inputs | Preserved as |
|---|---|---|---|
| Evidence content | Scientific values and explicit relationships | Canonical semantic evidence | Immutable artifact |
| Evidence provenance | Source and generator declarations | Canonical provenance evidence | Immutable artifact metadata |
| Manifest | The evidence admitted for reconstruction | Content and provenance identities | Immutable artifact |
| Semantic state | Verified entities, edges, and observations | Reconstructed meaning, not source location | Immutable artifact + `ResearchRun` |
| Investigation | Complete declared question and policy | State, targets, time, method, missing/numeric/resource/output policy | `InvestigationRecord` |
| Admission | Authorization to run one exact computation | Investigation and computation identities | Immutable `AdmissionRecord` |
| Attempt | One fenced ownership generation | Job, generation, random owner token | `ExecutionAttempt` |
| Result | Deterministic method output | Admission, state, method output | Immutable artifact + terminal job |

Equivalent source provenance may produce the same semantic state identity. A changed
observation changes both evidence content and semantic state. The contracts never treat
filenames, database primary keys, or HTTP paths as scientific identity.

## Persistence and reconciliation

The filesystem stores immutable bytes by content digest. SQLite stores their declared type,
schema, size, payload checksum, lifecycle state, and links to runs and results.

Publication is staged, flushed, and exposed with a same-filesystem hard link. Database
registration occurs separately. That boundary intentionally allows one safe failure mode:
an artifact may exist without a database row. `reconcile_artifacts` reports such an object
as an orphan; it does not silently promote or delete it. Conversely, missing or corrupt
registered bytes change the artifact record to a failed state and block result delivery.

The source evidence remains immutable. Reconstruction creates a new semantic artifact, and
execution creates a result artifact. No stage overwrites its predecessor.

## Transaction and execution model

Authoritative SQLite writes use a short in-process lock plus an explicit `BEGIN IMMEDIATE`
window. A repository-wide eager `IMMEDIATE` transaction mode was tested and rejected: two
concurrent HTTP executions could both enter as writers and produce lock failures. Keeping
the write intent inside the application service preserves short, deliberate critical
sections.

```text
admitted ── fenced claim ──> running ── committed result ──> succeeded
                                │
                                ├── controlled failure ────> failed
                                └── confirmed interruption → interrupted
                                                           │
                                             explicit retry ┘
```

A claim increments `claim_generation`, creates a random `owner_token`, binds both values to
the attempt, and records a deterministic attempt identity. Finalization succeeds only when
job state, generation, owner token, and attempt number still match. A stale worker therefore
cannot commit after an owner-confirmed recovery and new claim.

Age alone never proves that a worker stopped. Recovery requires explicit out-of-band
confirmation, marks the work interrupted, and leaves retry to an operator. These are
single-host guarantees, not leases, distributed consensus, or exactly-once external effects.

## HTTP and cache boundary

HTML, HTMX fragments, and JSON are delivery representations of the same application
services. The JSON surface is versioned under `/api/v1/` and uses structured success/error
envelopes. Django CSRF protection remains active. Upload parsing is bounded by Django's
configured request limit, and the scientific schemas enforce their own record and resource
budgets.

Only a successfully committed and reverified result artifact may enter the cache. Cache keys
include the job, representation, and result artifact identity. Mutable job state, failures,
and interrupted work bypass the cache. `Vary: HX-Request` prevents page and fragment
representations from crossing.

## Deliberate exclusions

- no distributed queue, Redis, Celery, or external database;
- no native extension or Rust boundary in this increment (the local Rust toolchain was not
  available, and the Python boundary already has conformance tests);
- no operational, private, or real scientific data;
- no claim of physical validity from deterministic execution;
- no hidden fallback from corrupt preservation bytes to database JSON.
