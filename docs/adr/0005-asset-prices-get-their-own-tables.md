# ADR-0005 — Asset prices will not be forced into the long observations table

Date: 2026-09-03 · Status: accepted (implementation deferred)

## Context
The sibling project (local and global asset prices) will share this repository and store.
Daily OHLCV as five long rows per instrument-day plus a vintage column that never varies is
~5× the rows of a wide table and a join per field; at 5k instruments × 25 years that is
~156M long rows vs ~31M wide.

## Decision
One logical API (`api.get`) over separate physical families: `observations` (bitemporal macro
series), `prices_daily` (wide, append-only, partitioned by year, weekly compaction) and
`corporate_actions` (event table). The `table` field on every catalog entry is the dispatch
seam; `Store.read` dispatches on it. Schemas for the price tables are defined when the first
instrument (B3 COTAHIST) is ingested, not before.

## Consequences
No change to macro code when the markets domain opens. Adjusted prices are computed from
`corporate_actions`, never stored as the only copy.
