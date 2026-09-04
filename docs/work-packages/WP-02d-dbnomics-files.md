# WP-02d — DBnomics and published spreadsheets

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:antigravity` with a Gemini model (3.1 Pro) |
| Branch | `wp/02d-dbnomics` (already created; acceptance tests and fixtures are on it) |
| Issue | (opened when dispatched) |
| Depends on | WP-02a (merged, PR #3) |
| Estimated effort | ~5 h |

## Goal

Two connectors that between them open every remaining door:

* `dbnomics` — a generic client for 93 statistical providers. This is how a third country
  joins the catalog without a line of new code, which is the promise the project was designed
  around.
* `file_http` — reads a spreadsheet or CSV published at a URL. Its first use is the New York
  Fed's Global Supply Chain Pressure Index, which is only distributed as a file.

## What the live sources already taught us

Probed on 2026-09-04; fixtures reproduce each case.

1. **DBnomics period strings differ by frequency**, and the response says which one applies in
   `@frequency`. All four are in the fixtures:

   | `@frequency` | period looks like | becomes |
   |---|---|---|
   | `annual` | `1995` | 1995-01-01 |
   | `quarterly` | `1995-Q1` | 1995-01-01 |
   | `monthly` | `1995-01` | 1995-01-01 |
   | `daily` | `1995-01-02` | 1995-01-02 |

   Trust `@frequency` over the catalog's `freq`, and raise if they disagree: a mismatch means
   the catalog entry is wrong, and guessing would misdate the series.
2. **A series that does not exist answers HTTP 404** with a JSON body, so the shared client
   raises `SourceError` on its own. Do not add a second retry loop.
3. **Missing observations arrive as JSON `null`**, not as a string marker.
4. **DBnomics' BCB coverage is one dataset** (`bop`, balance of payments). It is not a
   substitute for the direct Banco Central connector; it is the route to *other* countries.
5. **The NY Fed's `gscpi_data.xlsx` is not an .xlsx.** Its first bytes are `D0 CF 11 E0`, the
   signature of the legacy OLE format, so `openpyxl` fails with "File contains no valid
   workbook part" and `xlrd` reads it. Choose the engine from the file's **signature**, never
   from the extension in the URL.
6. **The GSCPI sheet carries branding above the data.** Sheet `GSCPI Monthly Data`, the header
   sits on row 0, rows 1-4 are a logo and a link, and the observations start on row 5: 343 of
   them, from `31-Jan-1998` to `31-Jul-2026`.
7. **Its dates are the last day of each month** (`31-Jan-1998`), while the contract stores the
   period start. Convert, or the whole index lands one month late.

## Contract

### `src/econbase/sources/dbnomics.py`

```python
ENDPOINT = "https://api.db.nomics.world/v22/series/{native_id}"


@register
class DbnomicsSource(Source):
    name = "dbnomics"

    def fetch_raw(self, spec: SeriesSpec, since: date | None = None) -> RawResponse: ...
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame: ...
```

`native_id` is `"{provider}/{dataset}/{series}"`, e.g. `BCB/bop/S1-A`.

`fetch_raw` requests `?observations=1&format=json`, one call, `covers_from=None`, `ext="json"`.
`parse` reads `series.docs[0]`, zips `period` with `value`, maps `null` to NaN, converts each
period with `@frequency` as above, and returns `period`, `value`. Raise `SourceError` when
there are no docs, when `@frequency` is unknown, or when it contradicts `spec.freq`.

### `src/econbase/sources/file_http.py`

```python
@register
class FileHttpSource(Source):
    name = "file_http"
```

`native_id` names the dataset for the catalog (`nyfed_gscpi`); the URL lives in `params`.

| param | default | meaning |
|---|---|---|
| `url` | required | where the file is published |
| `format` | auto | `xls`, `xlsx` or `csv`; auto-detected from the file signature |
| `sheet` | first | worksheet name |
| `skiprows` | 0 | rows to drop before the data |
| `date_col` | 0 | column index or name holding the date |
| `value_col` | 1 | column index or name holding the value |
| `date_format` | auto | a `strptime` pattern when the dates are not ISO |
| `period_is_end` | `false` | dates mark the end of the period and must be moved to its start |

`parse` uses `pandas.read_excel` with the engine chosen from the signature (`PK` → openpyxl,
`D0 CF 11 E0` → xlrd) or `read_csv`, applies `to_float`, drops rows without a date, and returns
`period`, `value`. Both `openpyxl` and `xlrd` are already dependencies; do not add more.

### Catalog

`catalog/global/dbnomics.yaml` and `catalog/us/nyfed.yaml`, ids appended to `catalog/ids.txt`.

| series | id | freq | concept |
|---|---|---|---|
| Brazil current account, annual | `dbnomics:BCB/bop/S1-A` | A | — |
| Brazil current account, quarterly | `dbnomics:BCB/bop/S1-Q` | Q | — |
| Global Supply Chain Pressure Index | `file_http:nyfed_gscpi` | M | `supply_chain_pressure` |

The GSCPI entry needs `params: {url: ..., sheet: "GSCPI Monthly Data", skiprows: 5,
period_is_end: true}` and `redistributable: false` (the NY Fed's terms of use apply).

## Files you may change

- `src/econbase/sources/dbnomics.py`, `src/econbase/sources/file_http.py` (both new)
- `src/econbase/sources/__init__.py` — only to add the modules to `CONNECTOR_MODULES`
- `catalog/global/dbnomics.yaml`, `catalog/us/nyfed.yaml`, `catalog/ids.txt`
- `tests/fixtures/dbnomics/`, `tests/fixtures/file_http/` — only to add fixtures
- This file's Result section

Never the protected files in `AGENTS.md` section 3, and never
`src/econbase/sources/http.py` or `pyproject.toml`; both already carry what you need.

**Expect one merge conflict.** WP-02b and WP-02c are being implemented in parallel and also
append to `CONNECTOR_MODULES`. Whoever merges later keeps every entry.

## Acceptance tests (already in the repository, currently skipped)

`tests/test_source_dbnomics_files.py` — `uv run pytest tests/test_source_dbnomics_files.py -q`

## Definition of done

- [ ] Whole suite green, `ruff check` and `ruff format --check` clean
- [ ] Only the listed files changed; no new dependencies
- [ ] Catalog complete, ids appended to `catalog/ids.txt`
- [ ] `uv run econbase update --source dbnomics --source file_http` succeeds live
- [ ] Result section filled in

## Result

(filled in by the executor)
