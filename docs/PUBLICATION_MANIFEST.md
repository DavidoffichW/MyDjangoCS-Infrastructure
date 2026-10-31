# Reviewed source publication manifest

This allowlist is prepared for a future owner-authorized private GitHub inspection. It
does not authorize creating a remote, pushing, licensing, or redistributing the source.

## Include

- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`, `THIRD_PARTY_NOTICES.md`
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

The lab contains independently written application code and a vendored HTMX file
covered by `THIRD_PARTY_NOTICES.md`. The authored-code license and remote visibility
remain owner decisions; without a selected license, publication remains blocked.
