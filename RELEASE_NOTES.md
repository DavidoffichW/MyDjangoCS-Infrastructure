# MyDjangoCS-Infrastructure v0.1.0

This first release packages a deliberately small systems laboratory for deterministic
scientific computation and local reliability experiments.

## Highlights

- A framework-independent scientific foundation with strict evidence schemas, canonical
  JSON, domain-separated identities, verified reconstruction, bounded admission, and fixed
  Decimal policies.
- A fictional four-sensor investigation with independent conformance values and stable
  semantic-state and result identities.
- An explicit binary observation format and a bounded Python memory arena that demonstrates
  generation-safe handles and scoped borrow conflicts.
- Immutable content-addressed artifacts joined to SQLite authority records through explicit
  registration and reconciliation.
- Conditional worker claims, attempt generations, owner-token fencing, controlled recovery,
  and real subprocess crash tests.
- Django, HTMX, and versioned JSON interfaces over the same application services, with CSRF,
  request tracing, idempotent admission, and representation-safe result caching.
- 108 Django tests and six Chromium workflows in a Windows/Ubuntu Python 3.12/3.13 CI matrix.

## Reference result

The default investigation calculates a mean of `11.5` for Sensor Alpha and `21.333333` for
Sensor Bravo while explicitly excluding Bravo's one missing observation. Independent jobs
replay to:

```text
result:sha256:7d32c02fdb42164d1d1f681906afbe27c380240ec61dc57ba62923ced7adf291
```

## Run locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/lab/>. Linux users can use `python3.12` and
`./.venv/bin/python` in the same sequence. The README includes the reference experiment,
reconciliation, worker, recovery, benchmark, and validation commands.

## Deliberate limits

This is a trusted, single-user, loopback laboratory. It does not provide distributed
consensus, arbitrary external-effect exactly-once execution, Rust compiler guarantees,
production multi-user security, or scientific validation of a physical process. Its corpus
is entirely fictional. Restricted research material and external source archives are not
part of the release.

Project code is MIT licensed. The vendored HTMX 2.0.11 asset retains Zero-Clause BSD terms
documented in `THIRD_PARTY_NOTICES.md`.
