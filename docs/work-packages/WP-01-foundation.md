# WP-01 — Foundation: contract, schemas, store, bitemporal pipeline, catalog, CLI

| Field | Value |
|---|---|
| Status | in review (awaiting maintainer merge decision) |
| Suggested executor | `agent:claude` (touches only protected files) |
| Branch | `wp/01-foundation` |
| Issue | (repository not published yet) |
| Depends on | none |
| Estimated effort | ~35 h |

## Goal

After this WP the repository has a working, tested data layer with no connectors yet: a
declarative catalog, a Parquet-as-truth store with atomic manifest promotion, a bitemporal
(ALFRED-style) update pipeline with a raw HTTP archive, run logging, a freshness check, a
CLI, and the model protocol for `econmodels`. Every later WP (connectors, transforms,
analyses) plugs into these contracts without changing them.

## Contract

Defined in `docs/CONTRACT.md` and `docs/IDENTIFIERS.md`, implemented in
`src/econbase/schemas.py` (pyarrow schemas, `SCHEMA_VERSION`), `src/econbase/catalog.py`
(pydantic models), `src/econbase/store.py` (`Store`, `Transaction`, `Manifest`),
`src/econbase/pipeline.py` (`update`, `check`, `apply_snapshot`, `apply_vintages`),
`src/econbase/sources/base.py` (`Source`, `FetchResult`, registry), `src/econbase/cli.py`
(`econbase update|check|rebuild-db|gc|list|search|init`), `src/econmodels/base.py`
(`ConceptRequest`, `RunContext`, `Result`, `Model`, registry).

## Files changed

`pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/ci.yml`,
`docs/CONTRACT.md`, `docs/IDENTIFIERS.md`, `docs/adr/*.md`, `catalog/concepts.yaml`,
`catalog/entities.yaml`, `src/econbase/**`, `src/econmodels/**`, `tests/**`,
`scripts/backup.ps1`.

## Acceptance tests

- `tests/test_schemas.py` — schema casting, rejection of missing/extra columns.
- `tests/test_settings.py` — default data dir per platform, env override, empty string → default.
- `tests/test_catalog.py` — id grammar, `(entity, concept)` uniqueness, alias resolution with
  `DeprecationWarning`, undefined concept rejected, stable `catalog_hash`.
- `tests/test_store.py` — transaction round trip, atomic manifest, partition replacement,
  `gc` removes only orphans, `rebuild_db` produces a read-only queryable file.
- `tests/test_pipeline.py` — two updates with a changed value produce two intervals; as-of at
  the boundary returns the right value; first release; vanished period closed on full-history
  fetch and left open on windowed fetch; empty fetch is a no-op; same-day revision collapses;
  vintaged source (FRED-like) upsert; raw archive hash dedupe; leakage guard.
- `tests/test_check.py` — freshness classification by frequency and `expected_lag_days`.
- `tests/test_cli.py` — `init`, `list`, `rebuild-db`, `check` via Typer runner.

Run: `uv run pytest -q`

## Definition of done

- [ ] All tests pass; `ruff check` and `ruff format --check` clean
- [ ] `uv.lock` committed; `uv sync --frozen` works from a clean checkout
- [ ] CI workflow present (tests only; never writes data)
- [ ] `docs/CONTRACT.md`, `docs/IDENTIFIERS.md`, ADRs 0001–0006 written
- [ ] `scripts/backup.ps1` present and documented
- [ ] Independent review (adversarial, multi-lens) run and findings addressed

## Notes for the executor

- `realtime_start` for sources without native vintages is the fetch date in
  `ECONBASE_TZ` (default America/Sao_Paulo). Two revisions on the same day collapse to the last
  value (DATE granularity), which keeps `(series_id, period, realtime_start)` unique.
- An empty fetch never closes rows: it is recorded as a warning in `run_series`.
- Windowed fetches (`FetchResult.covers_from`) only allow "vanished" detection inside the
  window.
- Partitions are rewritten whole per run (a few MB each); old part files stay until `gc`.

## Result

Delivered on branch `wp/01-foundation` (2026-09-03), 4 commits, 56 tests, ruff clean.

- Contract: `docs/CONTRACT.md`, `docs/IDENTIFIERS.md`, ADR-0001..0006, `schemas.py`
  (`SCHEMA_VERSION = 1.0.0`, six tables, `ensure_schema`/`from_pandas`).
- `catalog.py`: pydantic specs, id grammar, `(entity, concept)` uniqueness, aliases with
  `DeprecationWarning`, `catalog_hash`, `catalog/ids.txt` baseline guard.
- `store.py`: Parquet as truth, staged writes, atomic manifest, views `obs_latest`,
  `obs_first_release`, macro `obs_asof(d)`, `rebuild_db`, `gc` (min 1 day in the CLI).
- `pipeline.py`: raw HTTP archive with hash dedupe, `apply_snapshot` (ALFRED intervals,
  same-day collapse, `covers_from` window), `apply_vintages` (upsert of native vintages),
  guards (inverted interval, mass close > max(10, 50%), non-numeric values), credential
  redaction in persisted URLs/errors, `runs`/`run_series`, `check()` freshness.
- `cli.py`: `init | list | search | check | update | rebuild-db | gc`, non-zero exit codes.
- `econmodels/base.py`: `ConceptRequest`, `RunContext`, `Result`, `Model`, registry.
- `.github/workflows/ci.yml` (tests only), `scripts/backup.ps1`, `docs/MANUAL.md`.

Deviations from the contract: none. Deferred by design (see plan): `api.py`, `transforms.py`,
connectors, `daily.ps1` (WP-02/03).

Review status: the multi-lens adversarial review workflow could not run (API overloaded,
three attempts). An architect self-review was performed instead and produced the fixes in
commits 3 and 4 (guards, redaction, id baseline, gc minimum, tzdata). The independent review
remains a to-do before or right after merge; re-run it with the saved workflow script.

Open questions for the maintainer: none blocking. Follow-ups: WP-02 (connectors + shared
HTTP helper + FRED thin client), WP-03 (transforms, `api.get`, `daily.ps1`, Task Scheduler).
Note for WP-03: `daily.ps1` must `Set-Location` to the repository root before calling
`econbase`, otherwise `.env` is not found.
