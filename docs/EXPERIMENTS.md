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
the portfolio evidence. Remote CI remains unexecuted until a remote repository is
authorized.
