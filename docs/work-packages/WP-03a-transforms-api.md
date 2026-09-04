# WP-03a — Transformations and the read API

| Field | Value |
|---|---|
| Status | done |
| Executor | `agent:claude` (architect; `api.py` is the contract every analysis depends on) |
| Branch | `wp/03a-transforms-api` |
| Depends on | WP-02a (merged) |

## Goal

The layer between the store and the analyses: frequency conversion, rates of change, and a read
API that speaks concepts instead of series ids and can rebuild any panel as it stood on a past
date.

## Result

Delivered. 46 new tests (177 total), ruff clean.

`src/econbase/transforms.py` — pure pandas and numpy, so it stays in the core package. Filters
needing scipy or statsmodels (Hodrick-Prescott, Hamilton, X-13) belong to `econmodels`, where
the optional dependencies live, and are estimated on a run's as-of panel rather than stored.

Two rules are enforced rather than documented:
- a downsample always states its aggregation, because the average policy rate over a quarter
  and its end-of-quarter value are different series;
- upsampling is refused with a reason. Turning quarterly GDP into a monthly series requires a
  model of what happened in between; the mixed-frequency dynamic factor model does that
  properly in phase 5.

`src/econbase/api.py` — `Api.get`, `get_panel`, `resolve`, `describe`, `vintages`, and
`connect()`. Design decisions worth keeping:
- **Order of operations:** read as of the date, convert frequency, transform, *then* trim to
  the window. Trimming last means a year-over-year change at the start of a window is computed
  from the observation a year earlier instead of coming back empty.
- **`asof` is the whole point.** The panel is built from the vintage intervals, and every
  transformation is computed on that panel, so nothing published later can reach a backtest.
- A pointless `agg` on a single series is an error, but `get_panel` passes the aggregation only
  to the series it actually converts, because one panel mixes frequencies.

Verified against the recorded FRED vintages: 2024Q1 real GDP reads 22,768.866 as of 2024-05-01
and 23,082.119 today; the boundary day of each vintage resolves correctly; and a growth rate
computed as of a past date differs from today's, which is exactly the leakage the store exists
to prevent.

## Follow-ups

WP-03b: `scripts/daily.ps1`, the Task Scheduler entries and the operational documentation.
It waits for the Brazilian connectors so the scheduled run has something to fetch.
