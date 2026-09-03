# ADR-0001 — Parquet is the system of record; DuckDB is a disposable cache

Date: 2026-09-03 · Status: accepted

## Context
DuckDB allows one read-write process OR many read-only processes on a database file. A live
`.duckdb` file shared by the updater, notebooks, a sibling project and a future app would
fight over locks, and a `.duckdb` file inside a cloud-synced folder corrupts.

## Decision
Parquet files under `ECONBASE_DATA_DIR/lake` are the truth. A `manifest.json` names the live
files; writers stage new files and swap the manifest atomically; readers resolve files from the
manifest. `db/econbase.duckdb` contains only views and is rebuilt by `econbase rebuild-db`.
Partition `observations` by `source`, rewritten whole per run; ZSTD; never one file per series.

## Consequences
Zero lock contention between writer and readers. Old files remain until `econbase gc`.
DuckLake (or any multi-writer catalog) becomes a `Store` swap if a second writer ever appears.
