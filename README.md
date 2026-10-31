# MyDjangoCS-Infrastructure

A small systems laboratory for one question: what does it take to turn fictional
observations into a result that can be identified, reproduced, interrupted, recovered,
and explained?

The project deliberately joins two experiments. The original Django/HTMX workflow lab
shows transactional admission, idempotency, middleware, caching, and controlled job
execution. The deterministic foundation adds versioned evidence, semantic reconstruction,
scientific computations, managed memory, a portable binary format, and immutable artifact
preservation. The browser lets you inspect the entire authority chain rather than hiding it
behind a dashboard.

Everything in the scientific corpus is fictional.

## What you can inspect

- canonical, domain-separated identities for evidence, provenance, manifests, state,
  investigations, computations, attempts, and results;
- a deterministic four-sensor reconstruction with explicit missing and anomalous values;
- time-window and one-hop graph summaries with declared decimal and missing-data policies;
- five-stage investigation verification before execution is authorized;
- content-addressed artifacts reconciled against SQLite metadata after restart or failure;
- fenced job ownership, process-termination probes, explicit recovery, and replay evidence;
- a bounded memory arena and an explicit little-endian binary observation format;
- Django, HTMX, versioned JSON endpoints, middleware traces, and representation-safe caches.

This is not a distributed scheduler, a production scientific model, or an exactly-once
system for arbitrary side effects. SQLite serializes the authoritative write windows, one
local worker executes pure computations, and recovery requires positive confirmation that
the prior worker has stopped.

## Run the lab

Python 3.12 and 3.13 are exercised in CI. On Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/lab/> for the deterministic experiment or
<http://127.0.0.1:8000/> for the original workflow experiment.

The deterministic page guides you through:

```text
fictional evidence → manifest → semantic state → verified investigation
                   → admitted computation → execution attempt → immutable result
```

You can run the same path without the browser:

```powershell
.\.venv\Scripts\python.exe manage.py run_reference_experiment
.\.venv\Scripts\python.exe manage.py reconcile_artifacts
```

`run_reference_experiment` executes the same admitted computation twice under independent
job identities and reports whether the result identities match. `reconcile_artifacts`
verifies every registered block and reports missing, corrupt, or unregistered files without
deleting them.

The generic foreground worker remains available:

```powershell
.\.venv\Scripts\python.exe manage.py run_jobs --once
```

Recovery is intentionally explicit:

```powershell
.\.venv\Scripts\python.exe manage.py recover_jobs `
  --older-than-seconds 60 `
  --confirm-worker-stopped
```

Age is not proof of worker death, so the confirmation flag is mandatory. Recovery marks
unknown work as interrupted; it does not automatically replay it.

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

Chromium tests exercise both browser workflows. Separate subprocess tests terminate real
Python processes at preservation, admission, execution, result-commit, and recovery
boundaries, then reopen the database and artifact store to inspect what survived.

For a small fixed-workload timing probe:

```powershell
.\.venv\Scripts\python.exe manage.py benchmark_lab --iterations 25
```

The output is descriptive local evidence, not a scalability claim.

## Contracts and evidence

- [Architecture and authority boundaries](docs/ARCHITECTURE.md)
- [Canonical, memory, binary, persistence, and API contracts](docs/CONTRACTS.md)
- [Golden vectors and conformance procedure](docs/CONFORMANCE.md)
- [Adversarial experiments and measured results](docs/EXPERIMENTS.md)
- [Reviewed publication manifest](docs/PUBLICATION_MANIFEST.md)
- [Reference and licensing boundary](docs/REFERENCE_BOUNDARY.md)

The implementation uses compatible dependency ranges rather than exact patch pins. The
executed versions belong in validation evidence, not in the runtime contract.

## References and licensing

The design follows the documented behavior of
[Django middleware](https://docs.djangoproject.com/en/5.2/topics/http/middleware/),
[transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/),
[SQLite support](https://docs.djangoproject.com/en/5.2/ref/databases/),
[caching](https://docs.djangoproject.com/en/5.2/topics/cache/), and
[security](https://docs.djangoproject.com/en/5.2/topics/security/). The canonical profile
is a deliberately restricted scientific subset informed by
[RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html); it is not advertised as a complete
implementation of that RFC.

The independently authored code is licensed under [MIT](LICENSE). The vendored HTMX asset
retains its Zero-Clause BSD terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
The excluded WellNet archive and detailed local research report are not part of this
repository or its license.

The repository remains private. Public visibility, tags, and releases require a separate
owner decision.
