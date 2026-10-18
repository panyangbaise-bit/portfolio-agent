# Development

Use Python 3.11 or newer. CI is configured for Python 3.11 and 3.13.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check
```

`make check` runs Ruff lint, the repository-wide formatter check and pytest.
`make format` applies safe lint fixes and formatting. `make coverage` writes a
terminal report and `coverage.xml`; CI uploads the report for each Python version.
Use `make check PYTHON=python` if working in an already activated environment.

The default test suite ignores `.env`, uses a temporary SQLite database and
replaces configured API/notification credentials with inert test values before
application imports. Individual tests inject provider fixtures and in-memory
sessions. The real Qdrant transport test is opt-in:

```bash
MEMORY_TEST_QDRANT_URL=http://127.0.0.1:16333 .venv/bin/python -m pytest tests/test_memory_qdrant.py
```

Use a disposable local Qdrant instance. The standalone manual scheduler script
under `tests/` is a live integration utility when executed directly; it is not a
substitute for the isolated pytest suite.

## Conventions

- Keep calculations in `domain/`; HTTP/provider logic in `adapters/`; session state
  and rendering in `app/`. Backend code must not import the UI.
- Views expose `render()`. Importing a view must not query data or render a page.
- Start services through `runtime.py`; do not add startup code at module import.
- Preserve tool names, argument schemas, session IDs and ledger semantics during
  refactors. Cover changes at observable boundaries, especially trade accounting,
  authorization, degraded providers and lifecycle failure recovery.
- Use explicit public exports, typed interfaces at boundaries, contextual logging
  and deterministic fixtures. Keep UTC in storage; use `common.time` for display.
- Dependencies are declared in `requirements.txt`, with development tools in
  `requirements-dev.txt`. They use version ranges, not a fully locked dependency
  graph; run the suite after upgrades and record the deployed environment.
- Keep secrets, personal ledgers and generated coverage output out of Git. Schema
  changes need a migration and tests against both existing and empty databases.

## Screenshots

Capture the deployed app in the owner's authenticated browser, using its native
screenshot export. Prefer a fixed desktop viewport and actual visible page
states. Keep browser tabs, developer tools and unrelated windows out of the
export. Do not manufacture charts, reports or recommendations for a screenshot.
Keep account identities, private URLs and personal contact details out of the
export and documentation. Inspect every image and update both language versions
of the README.
