# Public source manifest

MyDjangoCS-Infrastructure v0.1.0 is public. This manifest describes the
independently authored source and separately licensed frontend asset included
in the repository.

## Included

- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`, `RELEASE_NOTES.md`, `LICENSE`, and `THIRD_PARTY_NOTICES.md`
- `manage.py`, `pyproject.toml`, `MANIFEST.in`, and `requirements*.txt`
- `foundation/`, containing the Django-independent scientific contracts and API
- `infrastructure/`, containing memory, artifact, persistence, and worker mechanisms
- `services/`, containing application services
- `web_infra/`, containing middleware, cache, API, and HTML adapters
- `reliability_lab/` and `workflows/`
- `frontend/templates/`, `frontend/static/css/app.css`, and package metadata
- `frontend/static/vendor/htmx/htmx.min.js` with its retained license
- the public technical documents under `docs/`

## Excluded

- Git metadata, virtual environments, caches, coverage, and test output
- SQLite databases, runtime artifact stores, and generated benchmark output
- local research output, reference archives, portfolio coordination records,
  context exports, credentials, local configuration, and private datasets

Project code is licensed under MIT. The vendored HTMX asset retains its
Zero-Clause BSD terms and is identified in `THIRD_PARTY_NOTICES.md`.
