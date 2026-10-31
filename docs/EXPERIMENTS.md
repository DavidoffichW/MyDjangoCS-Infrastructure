# MyDjangoCS-Infrastructure adversarial reliability experiments

The tests use independent database connections for races and disposable on-disk SQLite
databases for process termination. A deliberately raised Python exception is tested as
rollback behavior, but is not reported as a process crash.

## Experiment matrix

| Hypothesis | Setup / fault | Expected invariant | Observed result | Test | Limitation |
|---|---|---|---|---|---|
| Equal concurrent submissions share authority | Two committed requests, same key and canonical input | One job; both callers receive its identity | Passed | `test_identical_concurrent_admission_returns_one_authoritative_job` | Global key scope only |
| A reused key cannot change meaning | Concurrent submissions, same key, different values | One job and one explicit conflict | Passed | `test_conflicting_concurrent_admission_has_one_winner_and_one_conflict` | No distributed database claim |
| One running attempt wins | Two independent claim/execute requests | One attempt; loser is controlled | Passed | `test_competing_claims_have_one_controlled_winner`, browser double-submit | A contender can receive 503 if the bounded SQLite window is busy |
| Pre-claim death leaves no claim evidence | Terminate the subprocess inside an uncommitted outer transaction | Admitted, zero attempts | Passed | `test_process_exit_before_claim_commit_rolls_back_every_claim_record` | OS/filesystem durability beyond SQLite is not simulated |
| Post-claim death fails closed | Exit after claim commit | Running with no result; explicit recovery interrupts | Passed | `test_process_exit_after_claim_fails_closed_until_recovery` | Completion outside the database cannot be inferred |
| Calculation death cannot become success | Kill during deterministic calculation | Running, no result/digest | Passed | `test_process_termination_during_calculation_leaves_no_result` | Calculation has no external effects |
| Pre-finalization death cannot become success | Kill immediately before result finalization | Running, no result/digest | Passed | `test_process_termination_before_finalization_leaves_no_result` | Same local machine/database |
| A committed result survives worker death | Exit immediately after success commit | One terminal attempt/result/event sequence after restart | Passed | `test_process_exit_after_success_commit_preserves_one_result` | No power-loss/fsync laboratory |
| Recovery itself is atomic | Kill while recovery is uncommitted | Original running state remains; later recovery succeeds | Passed | `test_process_termination_during_recovery_rolls_back_reconciliation` | Manual recovery policy |
| Cache variants cannot cross | Page/fragment, two digests, clear, failed/interrupted jobs | Correct representation or no cache entry | Passed | cache tests in `test_http.py` | Local-memory cache only |
| Ordinary HTML remains usable | Chromium with JavaScript disabled | Add/remove forms still work | Passed | `test_ordinary_html_forms_work_without_javascript` | HTMX enhancements are intentionally absent |

## Deterministic foundation experiments

| Hypothesis | Setup / fault | Expected invariant | Observed result | Test | Limitation |
|---|---|---|---|---|---|
| Provenance and meaning have different identities | Re-register equal observations under a different fictional source | Provenance/manifest change; semantic state remains equal | Passed | `test_provenance_changes_without_changing_semantic_state` | Tests the declared v1 schemas only |
| A meaning change reaches semantic authority | Change one observation value | Evidence content and state identities both change | Passed | `test_meaning_change_changes_evidence_and_state_identity` | SHA-256 identity is not scientific validation |
| Invalid evidence never becomes state | Missingness conflict, dangling edge, unsupported schema | Typed rejection before reconstruction | Passed | `test_invalid_reference_cases_fail_before_reconstruction` | Deliberately small schema surface |
| Borrow rules survive thread contention | Four simultaneous shared readers, then an exclusive request | Readers succeed; writer is rejected until release | Passed | `test_cross_thread_readers_are_allowed_and_writer_is_rejected` | In-process arena, not shared memory |
| Portable bytes detect damage | Flip one payload bit and truncate a record | Checksum and length failures | Passed | binary tests in `test_memory_binary_store.py` | One version and record type |
| Filesystem publication can precede metadata safely | Terminate after three state artifacts publish but before database registration | No authority rows; three reportable orphans | Passed | `test_state_publication_without_database_registration_is_reconciled_as_orphan` | No power-loss/fsync hardware lab |
| Admission is atomic | Terminate after job/event creation but before transaction commit | No investigation, admission, or job survives | Passed | `test_admission_process_death_rolls_back_all_authority_rows` | Local SQLite only |
| Result publication cannot imply success | Terminate after result artifact publication but before database finalization | Running job, no result authority, one reportable orphan | Passed | `test_published_result_without_database_commit_is_recoverable_orphan` | Orphan cleanup is operator-directed |
| Stale owners cannot finalize | Interrupt a claimed job, requeue, claim again, then finalize with old token | Old finalizer rejected; current generation succeeds | Passed | `test_stale_attempt_cannot_finalize_after_owner_confirmed_recovery` | Confirmation is outside the process |
| Corrupt result bytes cannot be cached or served | Modify a registered result block after success | Controlled 409 before cache insertion | Passed | `test_corrupt_result_artifact_fails_closed_before_cache` | Local attacker with filesystem access is out of scope |
| Browser and command paths use the same authority | Open, reconstruct, admit, execute, inspect result in Chromium | Full persisted workflow succeeds | Passed | `test_scientific_workbench_preserves_and_executes_verified_state` | One local browser/session |

The scientific process tests use a fresh SQLite file and artifact directory for every case.
Exit codes 87–94 are deliberate hard exits from distinct failure boundaries; they are not
raised Python exceptions. Each test starts a new process to inspect the resulting state.

## Request lifecycle

Send a request with `X-Correlation-ID: experiment-42`. The response exposes a sanitized correlation identifier, a `Server-Timing` observation, and this trace:

```text
trace.enter > guard.pass > view.home > trace.exit
```

Sending `X-Lab-Short-Circuit: 1` produces HTTP 429 and:

```text
trace.enter > guard.block > trace.exit
```

View and inner-middleware exceptions are converted by Django at middleware boundaries;
the outer trace middleware observes the resulting 500 response. CSRF rejection reaches
the guard's request phase but not the view. This is instrumentation for the lab, not a
production tracing system.

## Duplicate admission

1. Build a workflow and admit values with an idempotency key.
2. Repeat the request with numerically equivalent values such as `1.0` instead of `1`.
3. Observe that the existing job is returned.
4. Reuse the key with different values and observe HTTP 409.

The invariant is key-plus-content consistency. The implementation does not claim exactly-once external effects.

## Failure and recovery

Add **Inject one controlled failure** to a workflow. The first attempt records `INJECTED_FAILURE`. Return the job to the queue and run it again; the second attempt succeeds. The two attempts and all state changes remain visible.

The subprocess probes terminate actual Python processes at the transaction boundaries
listed above. They inspect the reopened database before recovery and again afterward.
Recovery never infers success and never retries automatically.

## Cache correctness

Request a successful result twice as a full page and twice with `HX-Request: true`. Each response variant first reports `X-Lab-Cache: MISS`, then `HIT`. The full page and fragment never share cached HTML. Asking for the result of a mutable job returns HTTP 409 and does not enter the cache.

## Validated local environment

- Windows 11
- CPython 3.12.13 (64-bit)
- Django 5.2.18
- django-htmx 1.29.0
- HTMX 2.0.11
- Playwright 1.64.1 with Chromium
- Ruff 0.17.3

These are the R0 executed versions. R1 requalification records its exact environment in
the portfolio evidence. The private GitHub repository now executes the complete test,
browser, migration, Ruff, and dependency checks on Windows and Ubuntu. Run
`41241400675` passed on both operating systems at
`9002db9283a230bd7b6e7a1a3a1d6fc26130bf24`; later changes must qualify again on
their own exact commit.

## Deterministic foundation qualification

On 2026-11-01, CPython 3.12.13 on Windows executed 103 tests in 66.002 seconds, and a fresh
CPython 3.13.14 environment executed the same 103 tests in 65.486 seconds. The suite included
six Chromium workflows, six new scientific hard-exit scenarios, the original seven
process-termination scenarios, concurrent SQLite requests, property-based memory checks,
golden vectors, migrations, API/CSRF behavior, and artifact corruption. Django system
checks, migration drift, Ruff, dependency checks, and the source diff check passed in both
environments.

The fixed 25-iteration microbenchmark used four entities, 16 observations, four explicit
relationships, a 6,415-byte state artifact, and a 946-byte result artifact:

| Operation | Median | p95 |
|---|---:|---:|
| Canonical investigation declaration | 0.0503 ms | 0.0592 ms |
| Existing-store state build and verification | 5.1945 ms | 5.5024 ms |
| Foundation method execution and result publication | 1.4851 ms | 1.8485 ms |
| 4 KiB arena allocate/write/seal/release | 0.0323 ms | 0.0418 ms |
| Verified result artifact read | 0.5434 ms | 0.5791 ms |

The cold state build was 150.3398 ms. These measurements describe one local synthetic
workload and include timer noise, filesystem caching, and host-specific behavior. They do
not establish throughput, large-data behavior, or production scalability. Windows and
Linux remote CI on both Python versions remain gates for the final branch commit.
