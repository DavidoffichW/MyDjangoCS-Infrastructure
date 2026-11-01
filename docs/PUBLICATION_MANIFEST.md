# MyDjangoCS-Infrastructure reviewed source publication manifest

This allowlist governs the owner-authorized private GitHub inspection. It does not
authorize public visibility, release, licensing, or redistribution of the source.

## Include

- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`
- `manage.py`, `pyproject.toml`, `requirements*.txt`
- `foundation/`, the Django-independent scientific contracts and public API
- `infrastructure/`, runtime memory, preservation, persistence, and orchestration
- `services/`, explicit scientific and workflow application services
- `web_infra/`, middleware, cache, API, and HTML delivery adapters
- `reliability_lab/`
- `workflows/`, including migrations, management commands, and synthetic tests
- `frontend/templates/`
- `frontend/static/css/app.css`
- `frontend/static/vendor/htmx/htmx.min.js` with its retained notice
- `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `docs/CONFORMANCE.md`,
  `docs/EXPERIMENTS.md`, `docs/REFERENCE_BOUNDARY.md`, and this file

## Exclude

- `.git/`, virtual environments, caches, coverage and test output
- `db.sqlite3`, `runtime/`, content-addressed runtime artifacts, and every test SQLite file
- `research-output/` and the detailed WellNet report
- `references/` and the WellNet archive
- `GHP_Docs/`, context exports, agent instructions, and internal validation material
- credentials, local environment files, private datasets, and generated artifacts

The lab contains independently written application code licensed under MIT and a
vendored HTMX file covered separately by `THIRD_PARTY_NOTICES.md`. The reviewed
source is staged in the private `DavidoffichW/MyDjangoCS-Infrastructure`
repository. Public visibility, tag, release, and any change to the WellNet
disclosure boundary remain separate owner decisions.
