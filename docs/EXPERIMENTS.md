# Experiments

## Request lifecycle

Send a request with `X-Correlation-ID: experiment-42`. The response exposes a sanitized correlation identifier, a `Server-Timing` observation, and this trace:

```text
trace.enter > guard.pass > view.home > trace.exit
```

Sending `X-Lab-Short-Circuit: 1` produces HTTP 429 and:

```text
trace.enter > guard.block > trace.exit
```

This demonstrates request order and short-circuiting. It is instrumentation for the lab, not a production tracing system.

## Duplicate admission

1. Build a workflow and admit values with an idempotency key.
2. Repeat the request with numerically equivalent values such as `1.0` instead of `1`.
3. Observe that the existing job is returned.
4. Reuse the key with different values and observe HTTP 409.

The invariant is key-plus-content consistency. The implementation does not claim exactly-once external effects.

## Failure and recovery

Add **Inject one controlled failure** to a workflow. The first attempt records `INJECTED_FAILURE`. Return the job to the queue and run it again; the second attempt succeeds. The two attempts and all state changes remain visible.

For interruption recovery, claim a job, leave it running beyond a threshold, and run `recover_jobs`. The job becomes `interrupted`; a human-directed requeue is still required.

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

These are executed versions, not exact runtime pins. Remote CI remains unexecuted until a remote repository is authorized.
