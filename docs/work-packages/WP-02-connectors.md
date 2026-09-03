# WP-02 — Connectors, shared HTTP helper, initial catalog

| Field | Value |
|---|---|
| Status | ready (spec written; implementation not started) |
| Suggested executor | split into sub-packages below (`agent:claude` for 02a; others dispatchable) |
| Branch | `wp/02-connectors` (sub-packages may use `wp/02b-...`, `wp/02c-...` from it) |
| Issue | (open one per sub-package when dispatched) |
| Depends on | WP-01 (merged, PR #1) |
| Estimated effort | ~25 h total |

## Goal

After this WP, `econbase update` fills the store with the initial ~120 Brazilian and US series
from open sources, with recorded HTTP fixtures so the test suite never touches the network.
Every connector goes through one shared HTTP helper (retries, per-source pacing, chunking) and
returns the `FetchResult` contract from `src/econbase/sources/base.py`.

## Contract (applies to every connector)

```python
class XSource(Source):
    name = "x"                                   # == source segment of series_id
    def fetch(self, spec: SeriesSpec, since: date | None = None) -> FetchResult: ...
```

- `FetchResult.frame` columns: `period` (datetime.date, period START), `value` (float or NaN);
  vintaged sources add `realtime_start`, `realtime_end` (date or None).
- `FetchResult.raw_body`: the exact bytes received (the pipeline archives them);
  `raw_ext` = `json | xml | csv | xlsx`; `url` = the request URL (the pipeline redacts keys).
- `FetchResult.covers_from`: `None` when the frame is the complete history; the first period of
  the window otherwise (windowed fetches never close periods outside the window).
- Values must be numeric already: parse decimals in the connector (`"0,21"` → `0.21`); missing
  markers (`"."`, `""`, `"-"`) → `NaN`. Never let strings reach the pipeline.
- `spec.params` carries source-specific arguments (documented per source below).
- Use `econbase.sources.http.Client` for every request. No connector owns a retry loop, a
  sleep, or its own `httpx.Client`.
- Register with `@register`; add the module path to `CONNECTOR_MODULES` in `sources/__init__.py`.
- Tests: `tests/test_source_<name>.py` with `respx` fixtures under `tests/fixtures/<name>/`
  (JSON/CSV/XLSX bodies recorded from the real API, credentials stripped). One test per
  behaviour: parse, chunking/paging, missing values, empty response, HTTP 5xx retry then success.

## Sub-packages

### WP-02a — shared HTTP helper + FRED (executor `agent:claude`)

`src/econbase/sources/http.py`:
- `Client(settings)` wrapping one `httpx.Client(timeout=settings.econbase_http_timeout,
  headers={"User-Agent": "econbase/<version> (+https://github.com/guspiok-afk/econ)"})`.
- `get(url, params=None, *, source: str) -> httpx.Response`: per-source minimum interval
  between requests (defaults: `fred` 0.6 s ≈ 100/min, `bcb_sgs`/`bcb_focus` 2 s, `sidra` 2 s,
  `ipeadata` 1 s, `dbnomics` 1 s, `nyfed` 5 s); `tenacity` retry with exponential backoff + jitter
  on 429, 5xx, timeouts and connection errors (5 attempts, max 60 s); raise `SourceError` with
  status and redacted URL otherwise.
- Helpers: `date_windows(start, end, years=10) -> list[(start, end)]`; `to_float(s) -> float`
  (accepts `"0,21"`, `"1.234,5"`, `"."`, `""`, None).

`src/econbase/sources/fred.py` (vintaged):
- `GET https://api.stlouisfed.org/fred/series/observations` with
  `series_id, api_key, file_type=json, realtime_start=1776-07-04, realtime_end=9999-12-31,
  output_type=1, observation_start=1776-07-04` → `observations[]` of
  `{realtime_start, realtime_end, date, value}`; `value == "."` → NaN;
  `realtime_end == "9999-12-31"` → `None` (still current). Pagination: `limit=100000`, `offset`
  loop while `count > offset + limit`.
- `period` = `date` (FRED dates are period starts). `covers_from=None`.
- Missing API key → `SourceError("FRED_API_KEY not set")` before any request.
- Fixture: `tests/fixtures/fred/GDPC1_observations_p1.json` (recorded, key removed).

### WP-02b — BCB SGS + Focus expectations (executor `agent:jules` or `agent:antigravity`)

`bcb_sgs.py`: `GET https://api.bcb.gov.br/dados/serie/bcdata.sgs.{native_id}/dados?formato=json
&dataInicial=dd/mm/yyyy&dataFinal=dd/mm/yyyy` → `[{"data": "01/01/2020", "valor": "0.21"}]`.
Rules: the API caps a request at 10 years for daily series, so iterate `date_windows` from
`spec.params.get("start", "1980-01-01")` to today and concatenate; `period` = `data` parsed
`%d/%m/%Y` (monthly series come as day 01); `valor` via `to_float`. Full history each run
(`covers_from=None`). `raw_body` = concatenation of window bodies as a JSON array.
Series in the initial catalog: 433, 4466, 11427, 16121, 432, 4189, 24363, 1, 10813, 7806,
20539, 20714, 21082, 4380, 13521, 22701, 13762 (verify each id exists with one request).

`bcb_focus.py` (OData, not vintaged but `period` = survey date):
`GET https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/{resource}?$format=json
&$filter=Indicador eq '{indicador}'{extra}&$orderby=Data&$top=100000` where `resource` ∈
`ExpectativasMercadoInflacao12Meses` (params: `indicador`, `suavizada` = "S"/"N"),
`ExpectativasMercadoAnuais` (params: `indicador`, `reference`: year, possibly relative like
`+0`), `ExpectativaMercadoMensais`. Use column `Mediana`; `period` = `Data` (survey date, daily).
`params` documented in the catalog entry.

### WP-02c — IBGE SIDRA + IPEA (executor `agent:antigravity` or `agent:jules`)

`sidra.py`: `native_id` = `"{table}/{variable}"` plus params `{"n": "n1/all", "classifications":
"c315/7169", "decimals": 2}`. `GET https://apisidra.ibge.gov.br/values/t/{table}/{n}/v/{variable}/p/all[/{classifications}]/d/v{variable}%20{decimals}`
→ list whose first element is the header map; rows carry `D?C` period code (`202601`,
`202601` for months, `202601` quarters as `202601`? verify: quarters come as `202601`? no —
SIDRA quarterly codes are `YYYYQQ`, e.g. `202601`; check `D?N` text) and `V` value (`"..."`,
`"-"`, `"X"` → NaN). Map the period code to a period start by the series `freq`.
Tables: 1737 (IPCA, v63 monthly change; v2266 index), 7060 (IPCA groups), 1620/5932 (GDP),
6381 (unemployment), 8888 (PIM-PF), 8880 (PMC), 5906 (PMS).

`ipeadata.py`: `GET http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{native_id}')`
→ `{"value": [{"VALDATA": "2020-01-01T00:00:00-03:00", "VALVALOR": 0.21}]}`; `period` = date part
of `VALDATA`. Use for CAGED, FGV confidence (only series marked open), fiscal series.

### WP-02d — DBnomics + generic HTTP file + GSCPI (executor `agent:jules`)

`dbnomics.py`: `native_id` = `"{provider}/{dataset}/{series}"`;
`GET https://api.db.nomics.world/v22/series/{provider}/{dataset}/{series}?observations=1&format=json`
→ `series.docs[0].period` (ISO period strings: `2020-01`, `2020-Q1`, `2020`) and `.value`
(`"NA"` → NaN). Convert period strings to period starts.

`file_http.py`: a connector for published files: params `{"url": ..., "format": "xlsx|csv",
"sheet": ..., "date_col": ..., "value_col": ..., "skiprows": ...}`; `raw_ext` from format;
requires `openpyxl` (add to dependencies). First use: NY Fed GSCPI
`https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx`
(sheet `GSCPI Monthly Data`, verify sheet name and columns when recording the fixture).

### WP-02e — initial catalog (executor `agent:ollama` or `agent:antigravity`, reviewed by `agent:claude`)

Fill `catalog/br/bcb_sgs.yaml`, `catalog/br/bcb_focus.yaml`, `catalog/br/ibge_sidra.yaml`,
`catalog/br/ipeadata.yaml`, `catalog/us/fred.yaml`, `catalog/us/nyfed.yaml`,
`catalog/global/dbnomics.yaml` following the plan's list (~120 series). Every entry needs
`title`, `unit`, `freq`, `seasonal_adj`, `license`, `redistributable`, `expected_lag_days`,
`source_url`, and `concept_id` where the series is the canonical one for its country.
Append every new id to `catalog/ids.txt` (test enforces it). Verify each native id with one
request before committing (Ollama/Antigravity can run a tiny script for that).
Licenses: BCB, IBGE, IPEA, FRED, NY Fed data are open/attribution; set `redistributable: true`
only where the source terms allow redistribution, otherwise `false` (series stays local-only).

### Deferred: B3 reference rates scraper (`b3_taxas_ref`)
Secondary source for cupom cambial / DI; prefer BCB SGS swap series first. Own WP later.

## Acceptance tests (to be written by `agent:claude` before dispatch)

- `tests/test_http_helper.py`: pacing, retry on 503 then 200, `SourceError` on 404, `to_float`,
  `date_windows`.
- `tests/test_source_fred.py`, `tests/test_source_bcb_sgs.py`, `tests/test_source_bcb_focus.py`,
  `tests/test_source_sidra.py`, `tests/test_source_ipeadata.py`, `tests/test_source_dbnomics.py`,
  `tests/test_source_file_http.py`: fixture-driven parse tests + an end-to-end
  `pipeline.update` with the connector mocked via `respx`.
- `tests/test_catalog_real.py`: the real catalog loads; every `concept_id` used exists; every
  BR/US series has `expected_lag_days`; `ids.txt` complete.

## Definition of done

- [ ] All connectors registered; `uv run econbase update` succeeds on the real catalog
- [ ] Fixtures recorded and credentials stripped; suite passes offline
- [ ] `openpyxl` added to dependencies (`uv lock` updated)
- [ ] Catalog complete with `ids.txt`; `econbase check` shows all series `ok` or `unknown_lag`
- [ ] Manual updated (which sources, how to add a series)

## Result

(filled in at the end of the WP)
