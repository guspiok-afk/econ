# WP-02e-us — The United States catalog

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:ollama` (local model; mechanical and fully specified) |
| Branch | `wp/02e-us-catalog` (already created; the acceptance test is on it) |
| Worktree | `C:\dev\econ-ollama` (already prepared, dependencies installed) |
| Depends on | WP-02a (merged) |
| Estimated effort | ~2 h |

## Goal

The United States side of the catalog currently holds two series against Brazil's twenty-two.
This package brings it to twenty-nine: inflation, the labour market, interest rates, activity,
credit, sentiment and the two Fed indices this project exists to replicate.

No code. One YAML file and one list of identifiers.

## Why this is a transcription job

Every field below was verified against the live FRED API on 2026-09-04: each identifier exists,
and each `vintages` flag was tested by actually requesting the full real-time period. Nothing
here needs to be researched or decided — it needs to be typed accurately, which is the whole
task, and the acceptance test checks every field of every entry.

## What to write

### 1. `catalog/us/fred.yaml`

Keep the two entries already there (`GDPC1`, `DGS10`) exactly as they are and add the
twenty-seven below. Use the same shape as the existing entries and the same `defaults:` block.

`source_url` is `https://fred.stlouisfed.org/series/<native_id>` for every one.

| native_id | concept_id | freq | unit | seasonal_adj | lag | vintages |
|---|---|---|---|---|---|---|
| CPIAUCSL | cpi_headline_index | M | index 1982-1984=100 | true | 12 | true |
| CPILFESL | — | M | index 1982-1984=100 | true | 12 | true |
| PCEPI | — | M | index 2017=100 | true | 28 | true |
| PCEPILFE | — | M | index 2017=100 | true | 28 | true |
| CORESTICKM159SFRBATL | cpi_sticky | M | percent change from year ago | true | 12 | true |
| COREFLEXCPIM159SFRBATL | cpi_flexible | M | percent change from year ago | true | 12 | true |
| UNRATE | unemployment_rate | M | percent | true | 5 | true |
| PAYEMS | employment | M | thousands of persons | true | 5 | true |
| CIVPART | — | M | percent | true | 5 | true |
| ICSA | initial_claims | W | number | true | 5 | true |
| JTSJOL | — | M | thousands | true | 38 | true |
| AHETPI | wages | M | dollars per hour | true | 5 | true |
| FRBKCLMCILA | labor_conditions_index | M | index | true | 12 | true |
| FRBKCLMCIM | — | M | index | true | 12 | true |
| FEDFUNDS | policy_rate | M | percent per year | false | 3 | true |
| SOFR | interbank_rate | D | percent per year | false | 1 | true |
| DGS2 | govt_yield_2y | B | percent per year | false | 1 | **false** |
| T10Y2Y | — | B | percent per year | false | 1 | **false** |
| T5YIE | — | B | percent per year | false | 1 | **false** |
| INDPRO | industrial_production | M | index 2017=100 | true | 16 | true |
| TCU | capacity_utilization | M | percent | true | 16 | true |
| RSXFS | retail_sales | M | millions of dollars | true | 16 | true |
| HOUST | — | M | thousands of units, annual rate | true | 18 | true |
| UMCSENT | consumer_confidence | M | index 1966Q1=100 | false | 1 | true |
| GDPNOW | gdp_nowcast | Q | percent change at annual rate | true | 0 | true |
| TOTCI | credit_outstanding | W | billions of dollars | true | 8 | true |
| DRCCLACBS | credit_delinquency | Q | percent | true | 60 | true |
| DTWEXBGS | fx_effective_index | D | index Jan 2006=100 | false | 1 | true |

Notes that matter:

- **`vintages: false` on exactly four series.** FRED refuses a real-time period covering more
  than 2000 vintage dates, and those four are revised every business day: DGS2 has 5103 vintage
  dates, DGS10 5102, T10Y2Y 3114, T5YIE 3118. Every other series here was tested and accepted.
  Write `params: {vintages: false}` on those four and leave `params` off the rest.
- A dash in the concept column means **no `concept_id` line at all**. Only one series per
  country may carry a concept, and these have no counterpart in `catalog/concepts.yaml`.
- `DGS10` already exists and already carries `govt_yield_10y`; do not add it twice.

### 2. `catalog/ids.txt`

Append `fred:<native_id>` for each of the twenty-seven, one per line. A test fails if any is
missing.

## Files you may change

`catalog/us/fred.yaml`, `catalog/ids.txt`, and the Result section of this file. Nothing else,
and no code at all.

## Acceptance test

`tests/test_catalog_us.py` — already in the repository and currently failing.

```
uv run pytest tests/test_catalog_us.py -q
```

It checks every field of every entry against the table above, so a typo fails the build rather
than reaching the store.

## Definition of done

- [ ] `uv run pytest -q` fully green (not just the new file)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] Only `catalog/us/fred.yaml`, `catalog/ids.txt` and this file changed
- [ ] `uv run python -m econbase.cli update --source fred` run against the live API, with its
      **output pasted into the Result section below**. It takes a few minutes and it is the
      step that catches a wrong identifier; do not tick this box without it.

## Result

Executed by the local model (`qwen3-coder:30b` through Aider) on 2026-09-04, then corrected by
the architect. **36 acceptance tests pass, 253 in the whole suite, ruff clean.**

### What the model got right

All thirty entries, every field: concept, frequency, unit, seasonal adjustment, publication
lag, source URL and the `vintages` flag on the four series that need it. Once the two format
problems below were fixed, 35 of 36 tests passed with no substantive correction at all. For a
bulk transcription this is a good result.

### What it got wrong, and what that teaches

1. **Six titles contain a colon** (`Consumer Price Index for All Urban Consumers: All Items`)
   and were written unquoted, which is invalid YAML. The work package said "use the same shape
   as the existing entries", and none of those had a colon, so there was no example to copy —
   partly a gap in the specification rather than in the model.
2. **A markdown code fence was written into the file.** The model emitted the file inside a
   fenced block and the closing fence landed in the YAML.
3. **`catalog/ids.txt` was never touched.** The second half of the task was skipped silently.

The lesson for the next mechanical package: give the local model one file at a time, show an
example of every awkward case it will meet, and have the acceptance test read the file as text
before parsing it, so a stray fence fails with a clear message.

### Live verification

`uv run python -m econbase.cli update --source fred` — **30 series, 0 errors, 470,669
observations.** Some vintage histories are large, which is the point: TOTCI carries 167,649
rows, the two Kansas City Fed labour indices about 46,500 each, and industrial production
39,356.

Economic checks: sticky CPI at 2.72% against flexible at 1.09% year on year (July 2026); the
Atlanta Fed nowcast reading 4.75% for the third quarter; and the vintage test that only this
kind of base can answer — April 2020 unemployment was published at 14.7% and now reads 14.8%.
