# MyDjangoCS-Infrastructure public release candidate manifest

This allowlist defines the independently authored source proposed for a future public
v0.1.0 release. It supports review; it does not itself authorize a visibility change, merge,
tag, or GitHub Release.

## Include

- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`, `RELEASE_NOTES.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`
- `manage.py`, `pyproject.toml`, `MANIFEST.in`, `requirements*.txt`
- `foundation/`, the Django-independent scientific contracts and public API
- `infrastructure/`, runtime memory, preservation, persistence, and orchestration
- `services/`, explicit scientific and workflow application services
- `web_infra/`, middleware, cache, API, and HTML delivery adapters
- `reliability_lab/`
- `workflows/`, including migrations, management commands, and synthetic tests
- `frontend/templates/`
- `frontend/__init__.py`, which makes the reviewed frontend assets package data
- `frontend/static/css/app.css`
- `frontend/static/vendor/htmx/htmx.min.js` and `frontend/static/vendor/htmx/LICENSE`
- `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `docs/CONFORMANCE.md`,
  `docs/EDITORIAL_RESEARCH.md`, `docs/EXPERIMENTS.md`,
  `docs/REFERENCE_BOUNDARY.md`, and this file

## Exclude

- `.git/`, virtual environments, caches, coverage and test output
- `db.sqlite3`, `runtime/`, content-addressed runtime artifacts, and every test SQLite file
- `research-output/` and the detailed WellNet report
- `references/` and the WellNet archive
- `GHP_Docs/`, context exports, agent instructions, and internal validation material
- credentials, local environment files, private datasets, and generated artifacts

## Publication gates

- Independently authored project code is licensed under the root MIT license.
- `frontend/static/vendor/htmx/htmx.min.js` and its retained license remain governed by
  Zero-Clause BSD and are identified in `THIRD_PARTY_NOTICES.md`.
- The complete reachable Git history, not only the current tree, must pass the same
  confidentiality and provenance review before public visibility changes.
- The exact delivered commit must pass the Windows/Ubuntu Python 3.12/3.13 workflow.
- The owner must explicitly approve merge, public visibility, tag, and release operations.

The reviewed source remains in the private
`DavidoffichW/MyDjangoCS-Infrastructure` repository. The restricted WellNet archive,
detailed local research report, GHP coordination records, and context exports are not part
of this candidate. Their disclosure boundary is unchanged.
