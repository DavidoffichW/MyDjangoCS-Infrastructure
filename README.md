# MyDjangoCS-Infrastructure

MyDjangoCS-Infrastructure is a compact systems laboratory for studying how a scientific command becomes an identifiable, authorized, durable, and reproducible result. It uses Django and HTMX for the human-facing workflow, but its central subject is not CRUD. The repository is concerned with boundaries: which bytes count as evidence, which rules turn those bytes into semantic state, which declaration authorizes a computation, which process owns an execution attempt, and which persisted object can be trusted after interruption.

The included study uses a fictional four-sensor network. Its observations, relationships, missing values, and anomalous values are synthetic. Two transparent reference methods—a time-window mean and a one-hop graph-neighborhood mean—make the lifecycle concrete without pretending to be a validated physical model. Reproducibility here means that the declared inputs and policy produce the same canonical identities and numerical outputs. It does not mean that the fictional graph describes reservoir communication, that the methods are appropriate for operational decisions, or that deterministic software proves a scientific hypothesis.

## Architecture

The implementation separates scientific meaning from runtime mechanisms and HTTP delivery. That separation matters because a web view, database row, cache entry, or filesystem path must not quietly become a second definition of the experiment.

```text
browser / JSON client
        │
        ▼
frontend ──► web_infra (middleware, views, API, response cache)
                         │
                         ▼
                    services
             scientific │ workflows
                  ┌──────┴──────┐
                  ▼             ▼
             foundation    infrastructure
        contracts and meaning  memory, preservation,
                               transactions, orchestration
                  │             │
                  └──────┬──────┘
                         ▼
               workflows.models / SQLite
```

`foundation/` is Django-independent. It owns canonicalization, schemas, reconstruction, admission policy, numerical methods, and the supported public Python API. `infrastructure/` owns mechanisms whose correctness is important but whose meaning is not scientific: bounded memory, content-addressed storage, authoritative SQLite write windows, claims, finalization, and recovery. `services/` composes those two layers with persistent Django records. `web_infra/` adapts services to middleware, HTML, HTMX fragments, caching, and the versioned JSON surface. `workflows/models/` remains the authoritative Django app and schema; `frontend/` contains presentation only.

A scientific request follows a deliberate path. The HTTP adapter parses a declaration and passes it to the scientific service. The service asks the foundation to close and verify the declaration against a reloaded, reverified semantic state. Only then does it persist an admission and job. A foreground worker claims that job with a fenced ownership generation, executes the pure foundation method, publishes immutable result bytes, and atomically marks the database attempt successful. A later read verifies the artifact again before creating an HTML or JSON representation. Each boundary is explicit in source rather than hidden in a model `save()` method or middleware side effect.

## Repository organization

```text
foundation/       scientific contracts, schemas, reconstruction, governance, methods
infrastructure/   memory, preservation, persistence, orchestration
services/         scientific and workflow application services
web_infra/        middleware, caching, API adapters, HTML views
workflows/        Django models, forms, migrations, commands, and tests
frontend/         templates, CSS, and the vendored HTMX browser asset
reliability_lab/  Django settings and process entry points
docs/             deeper contracts, conformance evidence, and experiment descriptions
```

The directories are dependency boundaries, not categories chosen for visual neatness. Foundation modules may use standard-library and declared scientific contracts, but cannot import Django or application layers. Infrastructure may depend on public foundation contracts, while it must not define scientific interpretation. Services own use-case coordination. Web code may call services but cannot reconstruct state or write artifact bytes directly. Automated AST-based tests in [`test_architecture_boundaries.py`](workflows/tests/test_architecture_boundaries.py) enforce these rules and detect static import cycles.

Within those layers, files are organized by one responsibility. For example, [`infrastructure/memory/`](infrastructure/memory/) separates allocation from scoped borrowing and handle identity; [`services/scientific/`](services/scientific/) separates artifact registration, investigation admission, fenced jobs, and result finalization; and [`web_infra/caching/`](web_infra/caching/) separates cache identity from response rendering. The historical `workflows` application label and migration history remain unchanged, so the structural refactor does not create a fictitious database migration.

## Evidence and provenance

Evidence is accepted through an exact versioned schema in [`foundation/schema/evidence.py`](foundation/schema/evidence.py). An observation names its source, sensor, timestamp, variable, unit, value, quality, and missingness. Missingness is not inferred from an empty string or a failed conversion: `value=null` and `missing=true` must agree. Relationships are explicit, bounded, non-self-referential edges between known sensors. Quality labels and provenance remain attached to source observations rather than being replaced by a derived numerical summary.

Registration in [`foundation/evidence/registration.py`](foundation/evidence/registration.py) creates two related identities. The content identity covers scientific values and explicit relationships; the provenance identity covers the source declaration and generator context while binding back to content. This allows equivalent content from different declared origins to share semantic meaning without erasing provenance. Neither identity authorizes a calculation by itself. Evidence remains an immutable input, while manifests, reconstructed state, admissions, attempts, and results are separate derived records.

## Canonicalization and identity

Stable hashing requires more than calling SHA-256 on an ordinary Python dictionary. JSON key order, duplicate keys, floating-point spellings, Unicode validity, timestamps, and negative zero can otherwise make logically confusing byte representations. The restricted profile in [`foundation/contracts/canonical.py`](foundation/contracts/canonical.py) accepts only its documented JSON types, sorts keys by UTF-16 code units, rejects duplicate keys and floating-point tokens, normalizes explicit-offset timestamps to UTC, and represents schema-defined decimals as bounded canonical strings.

Identities use the visible form `<domain>:sha256:<digest>`. The hashed envelope includes a domain, schema version, and canonical payload with unambiguous framing. Domain separation prevents identical bytes from accidentally giving an evidence object and a result object the same meaning. Schema versions make contract evolution an explicit identity change. Database UUIDs, filenames, and URLs are still useful locators, but they are not semantic identity: they can change without changing content, or remain unchanged while mutable content changes. See [`foundation/contracts/identities.py`](foundation/contracts/identities.py) and [the detailed contract](docs/CONTRACTS.md).

## Reconstruction and manifests

A manifest binds one admitted evidence-content identity, its provenance identity, and the versioned reconstruction rules. It answers “which declared rules produced this state?” rather than treating a Python function name as sufficient provenance. Manifest construction lives in [`foundation/reconstruction/manifests.py`](foundation/reconstruction/manifests.py).

Reconstruction in [`foundation/reconstruction/state.py`](foundation/reconstruction/state.py) creates stable sensor entities, maps explicit relationships to entity edges, and attaches each observation to the corresponding entity. It does not infer edges from spatial proximity. The resulting immutable record is verified by recomputing its complete semantic identity and checking for duplicate entities, dangling edges, and unknown observation references. A provenance-only change can leave semantic state unchanged; changing an observation, relationship, or reconstruction rule changes the relevant identity. Strict loading never trusts serialized state merely because it was previously written.

## Scientific computation and numerical policy

The time-window method selects a declared variable and unit over an inclusive temporal window, groups observations by requested sensor, and computes a mean. The graph method starts from one target sensor, uses only explicit one-hop edges and their declared weights, and computes a weighted mean over the selected window. Each method has a versioned name and an isolated implementation under [`foundation/computation/`](foundation/computation/).

Both methods use `Decimal` with precision 28, `ROUND_HALF_EVEN`, and six-place output quantization before canonical rendering. The declaration must choose whether explicit missing values are excluded or propagated. Admission rejects incompatible method parameters, unknown variables or units, unavailable targets, invalid windows, and resource budgets that would admit too many targets or records. Tests compare representative results to independent decimal calculations. These controls establish numerical repeatability within the stated policy; they do not establish calibrated uncertainty or scientific fitness for a real field.

## Memory ownership and borrowing

[`infrastructure/memory/arena.py`](infrastructure/memory/arena.py) owns allocation and byte accounting. A [`Handle`](infrastructure/memory/handles.py) contains a slot and generation, so releasing and reusing a slot invalidates old references instead of creating an accidental alias. Scoped [`Borrow`](infrastructure/memory/borrowing.py) tokens mediate access: multiple shared readers may coexist, while an exclusive writer requires a mutable allocation with no active reader or writer. Sealing returns owned immutable bytes and forbids later writes; release requires no active borrow and decrements the arena quota.

The arena is a runtime experiment in explicit ownership. It does not turn Python into Rust, does not provide compile-time lifetime checking, and does not defend against a hostile process. Its guarantee is narrower and testable: application callers receive no raw address or writable `memoryview`, expired tokens and stale generations fail, and quota or borrow conflicts raise controlled errors. Binary serialization can optionally stage through the narrow arena protocol, while its scientific format remains independent of the concrete arena implementation.

## Binary interoperability

The observation format in [`foundation/binary/observations.py`](foundation/binary/observations.py) is a portable file contract, not a native ABI. Its 52-byte little-endian header contains an eight-byte magic, format version, flags, record count, payload length, and SHA-256 payload checksum. Each 40-byte record contains a bounded ASCII sensor identifier, UTC epoch milliseconds, a signed fixed-point value scaled by one million, an explicit missing flag, a quality code, and reserved zero bytes.

Encoding sorts observations by sensor and timestamp. Decoding checks magic, version, flags, counts, exact lengths, checksum, codes, missing sentinel agreement, identifier encoding, and timestamp precision before returning typed records. The standard sizes and explicit endianness are intended for reproducible interchange across platforms; they do not expose a C struct layout, pointer, compiler alignment, or in-process calling convention. Golden vectors protect the byte layout from accidental change during refactoring.

## Immutable preservation

The content-addressed store in [`infrastructure/preservation/store.py`](infrastructure/preservation/store.py) accepts bounded non-empty bytes and derives a reference binding type, schema, size, payload digest, and domain-separated identity. Publication writes a staged file, flushes it, and exposes it with a same-filesystem hard link. If another writer wins, the existing bytes must be identical. Reads are incremental and bounded, then verify size, checksum, and complete artifact identity. Corruption is rejected rather than falling back to mutable database JSON.

Filesystem publication and SQLite registration are intentionally separate persistence domains; no transaction can atomically commit both on ordinary local filesystems. A crash can therefore leave a valid but unregistered block, or metadata whose bytes later disappear. [`infrastructure/persistence/reconciliation.py`](infrastructure/persistence/reconciliation.py) reports orphans, marks registered objects missing or corrupt, and re-verifies healthy objects. It never silently promotes or deletes an artifact. Optional quarantine is explicit. The original evidence, reconstructed state, and results remain distinct immutable objects.

## Execution governance

An investigation is not executable merely because its JSON parses. The pipeline in [`foundation/governance/`](foundation/governance/) performs five stages. Structural closure requires exact fields and supported versions. State verification reloads and rechecks the declared semantic state. Semantic verification checks targets, variable/unit compatibility, and the time interval. Method verification checks the versioned algorithm, parameters, and missing-data policy. Resource verification enforces the declaration’s bounded target and record envelope.

Every rejection has a stage and stable code, and no `Admission` exists until all stages succeed. The admission binds the investigation, state, and computation identities. Django services in [`services/scientific/investigations.py`](services/scientific/investigations.py) persist that immutable declaration and enforce idempotency. Reusing a key for the same computation returns the existing authoritative job; reusing it for a different computation fails explicitly.

## Orchestration and recovery

Jobs move through `admitted → running → succeeded|failed|interrupted`. SQLite does not offer functional `SELECT FOR UPDATE` row locking, so claims use short authoritative write windows and atomic conditional updates. The shared transaction mechanism in [`infrastructure/persistence/transactions.py`](infrastructure/persistence/transactions.py) uses `BEGIN IMMEDIATE` only around bounded SQLite state changes and retries lock contention within a fixed policy.

A scientific claim increments a generation, creates a random owner token, and records both on an execution attempt. Finalization succeeds only if job state, attempt number, claim generation, and owner token still match. That fencing prevents an obsolete worker from committing after an acknowledged recovery and later claim. Recovery is deliberately operator-controlled: elapsed time alone cannot prove a process died, so a running attempt is marked interrupted only after external confirmation. Retry is a separate transition. Subprocess tests terminate real workers before and after important commit boundaries and inspect the reopened database and store.

This is a single-host laboratory, not a distributed queue. It does not provide consensus, leases across machines, automatic retry of arbitrary side effects, or distributed exactly-once execution. The demonstrated result is narrower: under the local SQLite and single-worker assumptions, authoritative transitions are durable, fenced, and inspectable.

## Caching

Caching is permitted only after a job has succeeded and, for scientific jobs, after its result artifact passes read-time verification. The cache identity includes job identity, result artifact identity, and representation variant. Full HTML and HTMX fragments cannot cross because the response varies on `HX-Request`; mutable, failed, and interrupted jobs bypass result caching. The policy is in [`web_infra/caching/identities.py`](web_infra/caching/identities.py), while response rendering is isolated in [`responses.py`](web_infra/caching/responses.py).

A cache hit is an optimization, not authority. Clearing the cache changes latency, not the scientific result or durable state. A stale representation cannot be reused after a result identity change because the key changes. The laboratory uses Django’s local-memory backend, so it makes no claim about shared-cache isolation across processes or deployments.

## Django middleware and HTMX

Django’s security middleware runs first, followed by request tracing, common request handling, CSRF, django-htmx request classification, and the demonstration guard. Correlation identifiers are accepted only under a bounded header-safe grammar; invalid values are replaced. Tracing records entry, guard, and view observations and returns correlation, elapsed-time, and `Server-Timing` headers. The guard demonstrates a middleware short circuit without owning any domain transition. These responsibilities are separate under [`web_infra/middleware/`](web_infra/middleware/).

HTMX requests reuse ordinary Django forms, URLs, CSRF tokens, and service functions; they only select fragment responses. Full-page HTML remains a fallback, including keyboard and non-JavaScript form semantics. The `/api/v1/` endpoints expose versioned JSON envelopes for state, admission, and result retrieval. API adapters translate controlled service failures but do not implement reconstruction or persistence themselves.

## Complete experimental walkthrough

Start at `/lab/` and seed the fictional reference run. Registration publishes evidence, manifest, and state artifacts, then creates a `ResearchRun` linking their verified identities. The reconstructed state contains four entities, explicit graph edges, and a short time series with declared missingness and quality. Its accepted identity is:

```text
semantic-state:sha256:6edea8182bab6fe1d6b9b46fbeab87332e60b6a21596ffb0a5093b71ac188a83
```

Admit the default time-window investigation for `sensor_alpha` and `sensor_bravo`, execute the job, and inspect the immutable result. Alpha has four available values and mean `11.5`. Bravo has three available values, one explicit missing observation, and mean `21.333333` under the `exclude` policy. The verified result identity is:

```text
result:sha256:7d32c02fdb42164d1d1f681906afbe27c380240ec61dc57ba62923ced7adf291
```

`python manage.py run_reference_experiment` performs the same admitted computation under two independent job identities. It reports identical result identities while preserving both attempt histories. `reconcile_artifacts` then verifies the registered bytes. A reviewer can inspect the SQLite lifecycle through the browser, compare the result artifact with the job, and rerun the golden conformance tests without relying on a pre-existing runtime database.

## Validation and conformance

The suite combines schema and golden-vector tests, independent decimal checks, property tests, memory lifecycle tests, binary corruption cases, storage races, transaction rollback, concurrent HTTP submissions, claim fencing, recovery, cache variation, API contracts, and browser workflows. Process tests use actual subprocess termination at preservation, admission, calculation, finalization, result-commit, and recovery boundaries. Chromium tests exercise ordinary page and HTMX paths. Architecture tests enforce layer imports and reject static cycles.

CI runs on Windows and Ubuntu with Python 3.12 and 3.13. Cross-platform golden identities matter because accidental platform-dependent ordering, timestamps, or binary packing would invalidate the experiment. The tests demonstrate the named fixtures and failure boundaries; their count is not evidence for arbitrary workloads, hostile multi-user deployment, or all possible filesystem failures. Detailed procedures and vectors are in [`docs/CONFORMANCE.md`](docs/CONFORMANCE.md) and [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md).

## Installation and use

Python 3.12 or 3.13 is supported. On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

On Linux or macOS:

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/lab/> for the scientific path or <http://127.0.0.1:8000/> for the dynamic workflow reliability experiment. Useful commands:

```powershell
.\.venv\Scripts\python.exe manage.py run_reference_experiment
.\.venv\Scripts\python.exe manage.py reconcile_artifacts
.\.venv\Scripts\python.exe manage.py run_jobs --once
.\.venv\Scripts\python.exe manage.py recover_jobs --older-than-seconds 60 --confirm-worker-stopped
.\.venv\Scripts\python.exe manage.py benchmark_lab --iterations 25
```

For development checks:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test workflows.tests -v 2
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pip check
```

The benchmark uses a fixed small workload and reports descriptive local timings. It is not a capacity or scalability result.

## Limitations and security

The server is intended for trusted local, single-user use and should remain bound to loopback. Django’s CSRF and security middleware are enabled, request bodies and scientific records are bounded, and errors avoid exposing arbitrary internal exceptions. There is no authentication, authorization model, TLS termination, tenant isolation, or hardened shared deployment contract. SQLite and the local-memory cache are selected to make transaction and failure behavior observable, not to stand in for a production distributed system.

Scientific data are synthetic, methods are illustrative, and graph adjacency is not a claim of physical connectivity. Python’s arena demonstrates runtime ownership checks but cannot provide native memory isolation or Rust-style compile-time lifetimes. No Rust or other native extension is included; a native boundary would need an independently justified ABI, toolchain, packaging, and conformance program. The detailed WellNet research material that informed broader study is excluded and is not required to understand or run this repository.

## References and license

Repository documentation:

- [Architecture and authority boundaries](docs/ARCHITECTURE.md)
- [Canonical, memory, binary, persistence, and API contracts](docs/CONTRACTS.md)
- [Golden vectors and conformance procedure](docs/CONFORMANCE.md)
- [Adversarial experiments and measured results](docs/EXPERIMENTS.md)
- [Reviewed publication manifest](docs/PUBLICATION_MANIFEST.md)
- [Reference and licensing boundary](docs/REFERENCE_BOUNDARY.md)

The implementation follows Django’s documentation for [middleware](https://docs.djangoproject.com/en/5.2/topics/http/middleware/), [transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/), [caching](https://docs.djangoproject.com/en/5.2/topics/cache/), and [security](https://docs.djangoproject.com/en/5.2/topics/security/), plus the [HTMX documentation](https://htmx.org/docs/). The canonical profile is informed by [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) but deliberately excludes binary floating-point serialization and does not claim complete JCS compatibility.

Independently authored code is licensed under [MIT](LICENSE). The vendored HTMX asset keeps its Zero-Clause BSD terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Restricted reference source and the detailed local research report are not part of this repository, license, or publication manifest.
