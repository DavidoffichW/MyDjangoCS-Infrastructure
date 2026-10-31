# Architecture

## Boundary

The lab is one Django process, one SQLite database, server-rendered templates, and a vendored HTMX browser asset. There is no task broker, distributed scheduler, or separate API service.

```text
browser
  │ ordinary or HX request
  ▼
security → trace middleware → common → CSRF → HTMX → demonstration guard
  │
  ▼
view → application service → transaction → SQLite
                              │
single worker command ────────┘
```

Middleware observes and constrains requests. It does not perform domain transitions or schedule work.

## Responsibility and authority

| Component | Owns | Does not own |
|---|---|---|
| `Workflow` / `WorkflowStep` | Editable draft and ordered operation positions | Admitted execution input |
| `Job` | Frozen command, content identity, authoritative state and result | Browser presentation or cache state |
| `ExecutionAttempt` | One numbered execution attempt and terminal evidence | Job admission or retry policy |
| `JobEvent` | Ordered record of committed state changes | Middleware observations |
| `services.py` | Validation, admission, guarded transitions, calculation and recovery | HTTP rendering |
| `views.py` | HTTP adaptation and controlled status responses | Domain transition rules |
| middleware | Correlation, timing and a demonstrable short-circuit | Jobs, transactions or scheduling |
| result cache | Disposable HTML for an immutable result and response variant | Authority or recovery |
| worker command | Serial execution admission | Distributed scheduling |

## Command admission and identity

An editable `Workflow` contains ordered `WorkflowStep` records. Admission performs four operations inside the application boundary:

1. validate that the ordered sequence is complete and supported;
2. serialize the command with `reliability-lab.command/1`;
3. canonicalize decimal inputs and hash the snapshot plus values;
4. atomically create a `Job` and its first event.

`Job.idempotency_key` is unique. Reusing a key with the same content identity returns the existing job. Reusing it with different input raises an explicit conflict.

The editable workflow is not authoritative execution input after admission. A job
executes its immutable JSON snapshot. Model validation and an SQLite trigger reject
updates to the five admitted command fields, including updates that bypass `save()`.

Canonicalization is versioned and deliberately narrow. JSON keys are sorted, UTF-8
is used directly, and decimals are rendered without redundant zeroes. Unicode strings
remain code-point exact: NFC and NFD text are not treated as identical. Inputs are
finite decimals within the documented magnitude, count, and decimal-place bounds.

## State machine

```text
                         controlled retry
                      ┌────────────────────┐
                      ▼                    │
admitted ──claim──> running ──failure──> failed
                       │                   │
                       ├──interruption──> interrupted
                       │                   │
                       └──commit result─> succeeded
```

Only declared transitions are legal. Claiming and completing an attempt use separate
transactions so an interrupted process leaves a detectable `running` record. Each
authoritative SQLite write uses a short process lock and `BEGIN IMMEDIATE`; the process
lock handles shared-connection test/runtime contention and SQLite's database write lock
serializes separate processes. Conditional updates still verify the expected state,
revision, and attempt number. `select_for_update()` is not treated as a row lock on
SQLite.

Recovery changes an old `running` record to `interrupted`; it does not assume that
blindly replaying side effects is safe. Requeue remains an explicit operator action.

## Formal invariants and assumptions

| Kind | Invariant | Enforcement and assumption |
|---|---|---|
| Safety | One authoritative job per global idempotency key | Unique database constraint; matching content returns it, conflicting content fails |
| Safety | Admitted command bytes do not change | Versioned snapshot, model guard, SQLite update trigger |
| Safety | Attempt numbers are unique and states match finish evidence | Database constraints plus transactional claim/finalize |
| Safety | No success without a committed result and digest | Database check constraint and one finalization transaction |
| Safety | No second successful transition | Conditional update requires the current running attempt; success cannot be requeued |
| Safety | Cache is never authority | Only successful result digests form cache keys; database is read before cache lookup |
| Safety | A crash before finalization cannot imply success | Claim and result commit are separate; stale running work is interrupted |
| Progress | A valid admitted job can be claimed | Assumes the SQLite write window becomes available within bounded retry or a later request retries |
| Progress | Interrupted work can continue | Requires explicit recovery and requeue; no automatic replay |

These properties assume one SQLite database on a local filesystem, supported Django
access paths, and no hostile direct modification of the database file. They are not a
distributed consensus or external-effect guarantee.

## Deterministic execution

Operations consume decimal strings under precision 28 and `ROUND_HALF_EVEN`.
Canonical JSON uses UTF-8, sorted keys, compact separators, and rejects non-finite JSON
numbers. SHA-256 identifies admitted content and successful results; a digest proves
byte identity under this schema, not numerical correctness by itself.

This proves repeatability for the lab operations under the recorded command version. It is not evidence of scientific validity, platform-independent floating-point behavior outside this decimal path, or safe replay of arbitrary external effects.

## Cache contract

Only a successful, immutable result is cached. The key contains the result digest and response variant (`page` or `fragment`), and responses vary on `HX-Request`. Draft workflows, admitted jobs, and other mutable states bypass this cache.

The cache is disposable. SQLite remains authoritative.

## Transaction boundaries

- Admission commits the job and its first event together.
- Claim commits the running state, attempt number, attempt row, and transition event.
- Calculation runs outside a transaction and performs no authoritative write.
- Finalization commits the terminal job, result/digest, terminal attempt, and event.
- Recovery commits the interrupted job, attempt evidence, and event together.

That separation is intentional: after termination, the database can distinguish work
that was never claimed, work of unknown completion left running, and a result that was
fully committed.
