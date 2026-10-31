# MyDjangoCS-Infrastructure reviewed source publication manifest

This allowlist governs the owner-authorized private GitHub inspection. It does not
authorize public visibility, release, licensing, or redistribution of the source.

## Include

- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`
- `manage.py`, `pyproject.toml`, `requirements*.txt`
- `reliability_lab/`
- `workflows/`, including migrations, management commands, and synthetic tests
- `templates/`
- `static/css/app.css`
- `static/vendor/htmx/htmx.min.js` with its retained notice
- `docs/ARCHITECTURE.md`, `docs/EXPERIMENTS.md`, `docs/REFERENCE_BOUNDARY.md`, and this file

## Exclude

- `.git/`, virtual environments, caches, coverage and test output
- `db.sqlite3` and every runtime/test SQLite file
- `research-output/` and the detailed WellNet report
- `references/` and the WellNet archive
- `GHP_Docs/`, context exports, agent instructions, and internal validation material
- credentials, local environment files, private datasets, and generated artifacts

The lab contains independently written application code licensed under MIT and a
vendored HTMX file covered separately by `THIRD_PARTY_NOTICES.md`. The reviewed
source is staged in the private `DavidoffichW/MyDjangoCS-Infrastructure`
repository. Public visibility, tag, release, and any change to the WellNet
disclosure boundary remain separate owner decisions.
