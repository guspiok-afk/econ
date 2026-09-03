# ADR-0002 — Vintages are stored as ALFRED-style real-time intervals

Date: 2026-09-03 · Status: accepted

## Context
Nowcasting backtests and honest model evaluation need "what was known when". FRED exposes
per-observation `realtime_start/realtime_end`; BCB, IBGE and IPEA expose nothing, so their
history of revisions can only be captured by observing them repeatedly from day one. A
snapshot-per-run design grows O(runs × observations) and makes deduplication the hardest code.

## Decision
`observations(series_id, period, value, realtime_start, realtime_end, observed_at, run_id)`
with key `(series_id, period, realtime_start)`. A revision closes the open row and inserts a
new one. FRED intervals are copied verbatim. Sources without vintages get
`realtime_start = fetch date in ECONBASE_TZ`; same-day revisions collapse to the last value.
Every HTTP body is archived in `raw/` so the intervals can be rebuilt if the diff logic ever
has a bug. An empty fetch never closes rows.

## Consequences
Storage grows with revisions, not runs. `latest`, `as_of(d)` and `first_release` are
one-line SQL. Brazilian backtests before the collection start date are pseudo real-time
(by publication lag) and must be labelled as such.
