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

## Command admission

An editable `Workflow` contains ordered `WorkflowStep` records. Admission performs four operations inside the application boundary:

1. validate that the ordered sequence is complete and supported;
2. serialize the command with `reliability-lab.command/1`;
3. canonicalize decimal inputs and hash the snapshot plus values;
4. atomically create a `Job` and its first event.

`Job.idempotency_key` is unique. Reusing a key with the same content identity returns the existing job. Reusing it with different input raises an explicit conflict.

The editable workflow is not authoritative execution input after admission. A job executes its immutable JSON snapshot.

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

Only declared transitions are legal. Claiming and completing an attempt use separate transactions so an interrupted process leaves a detectable `running` record. Recovery changes an old `running` record to `interrupted`; it does not assume that blindly replaying side effects is safe.

## Deterministic execution

Operations consume decimal strings under a fixed precision context. Canonical JSON uses UTF-8, sorted keys, compact separators, and rejects non-finite JSON numbers. SHA-256 identifies admitted content and successful results.

This proves repeatability for the lab operations under the recorded command version. It is not evidence of scientific validity, platform-independent floating-point behavior outside this decimal path, or safe replay of arbitrary external effects.

## Cache contract

Only a successful, immutable result is cached. The key contains the result digest and response variant (`page` or `fragment`), and responses vary on `HX-Request`. Draft workflows, admitted jobs, and other mutable states bypass this cache.

The cache is disposable. SQLite remains authoritative.
