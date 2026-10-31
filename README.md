# Django/HTMX Reliability Lab

A small, inspectable experiment in accepting work exactly once at the application boundary, executing it deliberately, and leaving enough evidence to explain what happened.

The browser lets you assemble an ordered list of numerical operations with HTMX. Django validates and freezes that list into a versioned command, SQLite records its identity and state, and a single worker executes it. The arithmetic is intentionally simple; the interesting part is the failure behavior around it.

## What the lab demonstrates

- dynamic add, edit, remove, and reorder forms without a client-side framework;
- request correlation, middleware ordering, elapsed-time reporting, and short-circuiting;
- transactional command admission with an idempotency key;
- explicit `admitted → running → succeeded|failed|interrupted` transitions;
- controlled failure, operator-directed retry, and stale-running recovery;
- deterministic input and result identities;
- variant-aware caching of immutable results, never mutable job state;
- CSRF enforcement for both ordinary forms and HTMX requests.

It does **not** claim distributed exactly-once execution. SQLite plus a single worker is enough to expose the important contracts, not enough to make arbitrary external side effects safe.

## Run it on Windows

Python 3.12 is the tested local interpreter.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000>. Create a workflow, add a few operations, validate and admit it, then run the job from its detail page.

The browser action and the worker command use the same application service. To exercise the worker directly:

```powershell
.\.venv\Scripts\python.exe manage.py run_jobs --once
```

To mark a stale running attempt as interrupted:

```powershell
.\.venv\Scripts\python.exe manage.py recover_jobs --older-than-seconds 60
```

Recovery does not retry work automatically. An interrupted or failed job must be returned to the queue explicitly.

## Run the checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test workflows.tests -v 2
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pip check
```

The browser tests launch Chromium and exercise the complete Django/HTMX path, including failure and recovery.

## Design notes

- [Architecture and state model](docs/ARCHITECTURE.md)
- [Experiments and expected observations](docs/EXPERIMENTS.md)
- [Reference and licensing boundary](docs/REFERENCE_BOUNDARY.md)

Runtime requirements intentionally use compatible ranges instead of exact patch pins. The validated environment is recorded in the experiment notes.

## References

The design follows the documented behavior of [Django middleware](https://docs.djangoproject.com/en/5.2/topics/http/middleware/), [database transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/), [caching](https://docs.djangoproject.com/en/5.2/topics/cache/), and [security](https://docs.djangoproject.com/en/5.2/topics/security/), together with [HTMX](https://htmx.org/docs/) and [django-htmx](https://django-htmx.readthedocs.io/).

The GPL-3.0 tutorial [django_htmx_dynamic_forms](https://github.com/justdjango/django_htmx_dynamic_forms/tree/13f2bf04453d5230e42455f68213f2526ee1f6c9) was studied as a reference. No source was copied. This project independently implements the interaction using current dependencies.

## Publication status

This is a local research candidate. A license for the authored source has not been selected, so redistribution and public publication remain blocked pending an owner decision. The vendored HTMX asset retains its own license; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
