# Data contract (schema version 1.0.0)

This page is the public interface of the store. Parquet files written under this contract
are what every consumer (analyses, sibling projects, a future API) reads. Changing it is a
schema version bump: additive columns = minor, rename/type change = major plus a migration.

## Storage layout

```
%ECONBASE_DATA_DIR%/
  raw/<source>/<series_key>/<run_id>.<ext>.gz   # archived HTTP bodies (hash-deduplicated)
  lake/
    manifest.json                                # {schema_version, catalog_hash, run_id, created_at, files}
    observations/source=<source>/part-<run_id>.parquet
    series/part-<run_id>.parquet
    entities/part-<run_id>.parquet
    runs/part-<run_id>.parquet
    run_series/part-<run_id>.parquet
    raw_index/part-<run_id>.parquet
    _staging/<run_id>/...                        # in-flight writes, never read
  db/econbase.duckdb                             # disposable cache of views (econbase rebuild-db)
```

Parquet is the system of record. Readers resolve the file list from `manifest.json`, never by
globbing, so a writer can add files and swap the manifest atomically while readers hold old
files open. Files are never modified in place; `econbase gc` deletes files no manifest
references. Partitioning: `observations` by `source` only, rewritten whole per run; all other
tables are single-file and rewritten per run. Compression ZSTD.

## Tables

### observations
| column | type | meaning |
|---|---|---|
| series_id | string | `{source}:{native_id}`, immutable (see IDENTIFIERS.md) |
| period | date | START of the period (M/Q/A/W) or the observation date (D/B) |
| value | float64 | numeric value in the series unit; NaN allowed (missing published as such) |
| realtime_start | date | first date on which this value was the current one |
| realtime_end | date, nullable | first date on which it stopped being current; NULL = still current |
| observed_at | timestamp (UTC) | instant of the fetch that produced this row (audit) |
| run_id | string | run that wrote the row |

Logical key: `(series_id, period, realtime_start)`. A revision closes the open row
(`realtime_end = run date`) and inserts a new row (`realtime_start = run date`). Two
revisions on the same day collapse to the last value (DATE granularity). Sources with native
vintages (FRED/ALFRED) copy their intervals verbatim. Sources without them get
`realtime_start = fetch date in ECONBASE_TZ` (pseudo real-time, labelled as such in any
backtest).

Standard queries (views/macros in every connection): `obs_latest` (`realtime_end IS NULL`),
`obs_asof(d)` (`realtime_start <= d AND (realtime_end IS NULL OR realtime_end > d)`),
`obs_first_release` (row with the minimum `realtime_start` per `(series_id, period)`).

### series
`series_id, entity_id, concept_id (nullable), source, native_id, title, unit, scale (float64),
freq (D|B|W|M|Q|A), seasonal_adj (bool), calendar (nullable: B3|NYSE|SIFMA|...),
source_url, license, redistributable (bool), aliases (list<string>), method_version (nullable,
derived series only), expected_lag_days (int32, nullable), table, domain, first_period (date),
last_period (date), last_updated (timestamp UTC)`. Rewritten from the catalog on every run.

### entities
`entity_id, entity_type (country|instrument|issuer|index|region), name, attributes (JSON string)`.

### runs
`run_id, started_at, finished_at, status (ok|partial|failed), trigger (manual|scheduler|ci),
package_version, git_sha, catalog_hash, n_series (int32), n_errors (int32)`.

### run_series
`run_id, series_id, source, rows_fetched, rows_new, rows_revised, rows_closed (int64),
raw_sha256 (nullable), error (nullable), duration_ms (int64)`.

### raw_index
`source, series_id, run_id, fetched_at (timestamp UTC), url, sha256, bytes (int64),
path (relative to raw/), stored (bool; false when the body equalled the previous one and only
the index row was kept)`.

## Conventions

- Dates are tz-naive DATE; timestamps are UTC. `ECONBASE_TZ` (default `America/Sao_Paulo`)
  only decides which calendar date a fetch instant maps to for `realtime_start`.
- `freq` lives on the series row. Resampling takes an explicit aggregation
  (`last | mean | sum | eop`) and never guesses.
- `Store` and `api` return `pyarrow.Table`; pandas conversion happens at the edge.
- Asset prices (OHLCV) will NOT be forced into `observations`; they get their own physical
  tables when the first instrument is ingested (ADR-0005). The `table` field on the catalog
  entry is the dispatch seam.
- `run_id` is a sortable string: `YYYYmmddTHHMMSSZ-<6 hex>`.
