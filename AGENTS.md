# AGENTS.md — shared instructions for every coding agent in this repository

This file is read by Claude Code, Google Antigravity, Jules and local Ollama-based agents.
`CLAUDE.md` and `GEMINI.md` only point here. Keep this file under 12,000 characters.

## 1. What this project is

`econ` is an open-data economic database plus an analytics layer, built to feed complex
models (Phillips curve, Taylor rule, UIP/CIP, VAR/SVAR/BVAR, mixed-frequency dynamic factor
nowcasting with real-time vintages, LMCI/GSCPI/sticky-CPI style indices, DSGE) and, later,
an application and sibling projects (first: local and global asset prices). Countries: Brazil
and the US first; adding a country must be a catalog change, not a code change.

Two Python packages in one repository, one `pyproject.toml`:
- `src/econbase/` — data layer: catalog, sources (connectors), store, pipeline, transforms, `api`, CLI.
- `src/econmodels/` — analyses. It may import only `econbase.api` and `econbase.schemas`.

The full design lives in `docs/` (CONTRACT.md, IDENTIFIERS.md, adr/). Read the relevant doc
before touching the area it covers.

**Portability note.** Sections 4, 5 and 7, and the general half of 6 and 8, are the operating
process and are project-independent: they will be lifted verbatim into a separate
agent-operations kit once each executor has completed at least one work package here (the
status board in section 10 tracks that). Keep project facts out of them — data rules,
protected files, dependency pins and source specifics belong in sections 1-3, 9 and 10. When
you edit this file, put your change on the correct side of that line.

## 2. Non-negotiable data rules

1. **Parquet is the system of record.** The DuckDB file is a disposable cache of views,
   rebuilt by `econbase rebuild-db`. Never write to the `.duckdb` file; never make readers
   depend on it.
2. **Data lives outside the repository and outside any synced folder** (OneDrive, Google
   Drive): `ECONBASE_DATA_DIR`, default `%LOCALAPPDATA%\econbase\data`, sub-dirs `raw/`
   (gzipped HTTP bodies), `lake/` (Parquet tables incl. `raw_index` + `manifest.json`), `db/`.
   Nothing under `data/`, no `.parquet`, no `.duckdb`, no `.env` is ever committed.
3. **Vintages are bitemporal, ALFRED style.** `observations(series_id, period, value,
   realtime_start, realtime_end, observed_at, run_id)`; logical key
   `(series_id, period, realtime_start)`; `realtime_end IS NULL` means "currently valid".
   A changed value closes the open row and inserts a new one. Never store one snapshot per
   run, never overwrite history. Vintaged sources copy the interval the API returns, except
   that an open-ended sentinel (`9999-12-31`) is stored as NULL. The pipeline validates every
   result: unique key, one open row per period, no empty or overlapping intervals.
4. **Identifiers are immutable.** `series_id = "{source}:{native_id}"` (`bcb_sgs:433`,
   `fred:CPIAUCSL`, `sidra:1737/2266`, `derived:sticky_cpi_br`). Renaming is forbidden;
   add an alias instead. `entity_id` is ISO 3166-1 alpha-2 for countries. `concept_id` is
   snake_case; `(entity_id, concept_id)` is unique in `catalog/concepts.yaml`.
5. **Period and frequency conventions.** `period` is a DATE and is the START of the period
   (M/Q/A) or the observation date (D/B). `freq` in `{D,B,W,M,Q,A}` lives on the series
   row. Resampling takes an explicit aggregation (`last|mean|sum|eop`) and never guesses.
   `realtime_*` are DATE; `observed_at` is a UTC timestamp.
6. **Writers never modify a Parquet file in place.** Write to `lake/_staging/<run_id>/`,
   then promote by atomically writing `manifest.json`. Partition by `source` only; ZSTD;
   never one file per series.
7. **Every HTTP response is archived** to `raw/` before parsing (hash-deduplicated).
8. **Analyses reference concepts, not series ids** (`api.get("cpi_headline", entity="BR")`).
   Inside a backtest, filters, seasonal adjustment and any derived input are computed on the
   as-of panel, never read pre-computed. A test fixture asserts no row has
   `realtime_start > asof`.
9. **One writer.** Windows Task Scheduler on the maintainer machine runs `econbase update`.
   GitHub Actions runs tests only. No workflow writes data, no data is committed to git.

## 3. Protected files (change only in a PR labelled `agent:claude`, reviewed by the architect)

`src/econbase/schemas.py`, `src/econbase/store.py`, `src/econbase/pipeline.py`,
`src/econbase/catalog.py`, `src/econbase/settings.py`, `src/econmodels/base.py`,
`docs/CONTRACT.md`, `docs/IDENTIFIERS.md`, `pyproject.toml` dependency pins, this file.
If your task seems to require changing one of them, stop and write the needed change as a
comment on the issue instead of editing it.

## 4. How work is organized: work packages (WP)

1. Every task is a work package: `docs/work-packages/WP-NN-<slug>.md`, written from
   `docs/work-packages/TEMPLATE.md`. A WP states the goal, the exact contract (signatures,
   schemas), the files you may touch, the acceptance tests (already in the repo, failing),
   fixtures, definition of done and the suggested executor.
2. Each WP is a GitHub Issue carrying one executor label: `agent:claude`, `agent:jules`,
   `agent:antigravity`, `agent:ollama` (Jules is additionally triggered by its own `jules`
   label). The issue body links the WP file.
3. One branch per WP: `wp/NN-<slug>`. Never commit to `main`.
   **`C:\dev\econ` belongs to whichever agent is running there.** Never switch its branch
   while someone else is working: the checkout deletes their files from disk mid-task and they
   see the work package's own tests vanish. Anyone needing a second branch at the same time
   takes a worktree of their own (`git worktree add C:\dev\econ-<name> <branch>`); the
   architect works from `C:\dev\econ-claude`.
4. Open a PR to `main`. CI (ruff + pytest) must be green. The architect (Claude Code)
   reviews and merges. Address review comments in the same branch.
5. Do not start a WP whose acceptance tests do not exist yet; ask for them.
6. Do not widen the scope: no extra files, no drive-by refactors, no new dependencies
   unless the WP lists them.

## 5. Routing rules (who does what)

- **Claude Code (architect/integrator):** contracts, protected files, acceptance tests for
  every WP, PR review and merge, ADRs, CI.
- **Jules (asynchronous, via GitHub Issues):** self-contained WPs whose tests exist:
  connectors, transforms, catalog population, small fixes. Prefers tasks finishable in one
  session without design decisions.
- **Antigravity (interactive, Manager view):** iterative work: analyses with a golden test,
  notebooks, reports, debugging, anything needing back-and-forth with the maintainer.
- **Ollama (local model, mechanical):** docstrings, unit tests from a spec, YAML catalog
  entries from a list, recording fixtures, formatting, secondary PR review. Never core,
  schema or vintage logic.
- **Heavy compute** (Bayesian DSGE, DFM backtest loops, BVAR): Google Colab reading Parquet
  from the Google Drive backup of the maintainer, not the laptop.

## 6. Engineering conventions

- Python `>=3.13`, developed on 3.14. Environment and locking with `uv` only
  (`uv sync --frozen`, `uv run ...`). Never `pip install` into the project.
- Pins are deliberate: `duckdb>=1.5,<2`, `pandas>=2.3,<4`, `pyarrow>=21`. Do not bump.
- Lint/format: `ruff` (config in `pyproject.toml`). Types: annotate public functions.
- Tests: `pytest`. No network in tests: connectors are tested against recorded HTTP
  responses (`respx`) stored under `tests/fixtures/`. Store tests use a temp
  `ECONBASE_DATA_DIR`.
- `Store` and `api` return `pyarrow.Table` by default; convert to pandas at the edge.
- Connectors implement `Source.fetch_raw(spec, since) -> RawResponse` (the bytes, unparsed)
  and `Source.parse(raw, spec) -> long DataFrame`. The pipeline archives the raw response
  before parsing, so never parse inside `fetch_raw`. Requests go through the shared HTTP
  helper (`sources/http.py`: httpx, tenacity retries, per-source minimum interval, window
  chunking); no connector owns its own retry loop.
- CLI subcommands (`update`, `check`, `rebuild-db`, `gc`, `list`, `search`) are idempotent
  and return non-zero exit codes on failure.
- Commits: Conventional Commits (`feat(sources): add SIDRA connector`), scoped by package or
  area. Small, reviewable PRs.
- Code, comments, docstrings and commit messages in English. User-facing docs may be in
  Portuguese (pt-BR).
- Secrets only via `.env` (see `.env.example`) loaded by `pydantic-settings`. Never print,
  log or commit a key.

## 7. Definition of done (every WP)

- Acceptance tests pass; no existing test broken; `ruff check` and `ruff format --check` clean.
- Only files listed in the WP were changed; no new dependencies outside the WP.
- Public functions have docstrings; the WP file "Result" section is filled in.
- For connectors: fixtures recorded, license and redistribution flag set on the catalog
  entries, `expected_lag_days` filled.
- For analyses: a golden test against a published reference value, with tolerance stated.

## 8. Never do this

- Run `yfinance` or any terms-of-service-restricted scraper inside `econbase update`.
- Commit Parquet, DuckDB files, `.env`, notebook outputs, or anything under `data/`.
- Let GitHub Actions write or publish data.
- Put the data directory or the repository inside OneDrive or Google Drive sync folders.
- "Fix" a vintage by editing history. Revisions are new rows.
- Add an orchestrator (Dagster/Prefect/dlt), a web framework, or Julia. Those have explicit
  adoption triggers recorded in `docs/adr/`.

## 9. Useful context

- Sources: BCB SGS/PTAX/Focus (python-bcb), IBGE SIDRA (sidrapy), IPEA (ipeadatapy), FRED
  (direct httpx client with full real-time period; `fredapi` lacks `realtime_end`),
  DBnomics (generic connector for IMF/OECD/ECB/BIS), NY Fed GSCPI (xlsx), B3 reference rates
  (scraper, secondary priority).
- Modelling stack: statsmodels 0.15 (DynamicFactorMQ, VAR/SVAR, X-13), `bvar`, `localproj`,
  Impulso (Bayesian VAR), gEconpy (DSGE, optional extra `econmodels[dsge]`).
- Methodology PDFs (KC Fed LMCI, NY Fed GSCPI SR1017, Atlanta Fed sticky CPI, GDPNow
  explainer) are summarized in `docs/methodology/` when a WP needs them.

## 10. Project status board

A living board tracks phases, work packages and what is waiting on the maintainer:
https://claude.ai/code/artifact/93f5a13e-3e87-4f86-a439-e3dddbdd9398

Claude Code updates it whenever a work package is delivered, a PR is merged, or a decision
changes. It is a view, not a source of truth: the work-package files under
`docs/work-packages/` and the pull requests remain authoritative.
