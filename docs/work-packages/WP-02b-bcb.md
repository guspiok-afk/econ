# WP-02b — Banco Central: SGS time series and Focus expectations

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:jules` |
| Branch | `wp/02b-bcb` (already created; the acceptance tests are on it) |
| Issue | (opened when dispatched) |
| Depends on | WP-02a (merged, PR #3) |
| Estimated effort | ~6 h |

## Goal

Two connectors that bring Brazil's central bank data into the store: `bcb_sgs` for the time
series system (inflation, policy rate, exchange rate, credit, fiscal) and `bcb_focus` for the
weekly market expectations survey. After this WP, `econbase update` fills roughly twenty
Brazilian series and the acceptance tests below pass offline.

## What was already learned from the live APIs

These were found by probing the real endpoints on 2026-09-04. Do not rediscover them; the
fixtures reproduce each one.

1. **Daily series must be requested in windows.** Asking for a daily series without
   `dataInicial`/`dataFinal` returns **HTTP 406**, not the full history. The documented cap is
   ten years per request. Monthly series answer fine without a window.
2. **A window with no observations returns HTTP 404** with a JSON body, not an empty array.
   When sweeping a long history in windows this is an ordinary outcome for the early windows —
   treat it as "no rows here" and carry on. Use `client.get(..., allow_status={404})`.
3. **An unknown series id returns HTTP 200 with an HTML page.** Parsing must detect that the
   body is not JSON and raise `SourceError`, otherwise a typo becomes a silent empty series.
4. **Olinda (Focus) rejects `+` as an encoded space** and answers
   `The types 'Edm.Boolean' and 'Edm.String' are not compatible`, which points nowhere near the
   cause. Build the query with `econbase.sources.http.odata_query(...)` and pass the finished
   URL to `client.get`. Never use `params=` for Olinda.
5. **SGS dates are `dd/mm/yyyy`** and values are strings with a decimal **dot** (`"0.33"`).
   Monthly series carry day `01`; that is already the period start the contract wants.
6. Successful SGS responses are UTF-8 JSON with exactly the keys `data` and `valor`.

## Contract

### `src/econbase/sources/bcb_sgs.py`

```python
ENDPOINT = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{native_id}/dados"

@register
class BcbSgsSource(Source):
    name = "bcb_sgs"
    def fetch_raw(self, spec: SeriesSpec, since: date | None = None) -> RawResponse: ...
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame: ...
```

Parameters on the catalog entry (`params`):

| key | default | meaning |
|---|---|---|
| `start` | `"1980-01-01"` | first date to sweep from when no `since` is given |
| `windowed` | derived from `freq` | force windowing on or off; default: on for `D`/`B`, off for the rest |
| `window_years` | `10` | window size for windowed series |

`fetch_raw`:
- Not windowed: one request without dates. `covers_from = None`.
- Windowed: `date_windows(start_date, today, years=window_years)` where `start_date` is
  `since` when given, else `params["start"]`. One request per window, `dataInicial`/`dataFinal`
  formatted `dd/mm/yyyy`, `allow_status={404}`; a 404 window contributes no rows.
  `covers_from = start_date` when `since` was given, `None` otherwise (a sweep from `params.start`
  to today is the complete history, so the pipeline may close periods that vanished).
- `RawResponse.body` is a JSON array: the single body when unwindowed, otherwise the window
  bodies concatenated as `[body1,body2,...]` (skip 404 bodies). `ext="json"`.

`parse`:
- Accept both shapes: a list of observations, or a list of lists (windowed).
- Reject a body that is not JSON, or whose rows lack `data`/`valor`, with `SourceError`
  naming the series (this is what catches the HTML page of quirk 3).
- `period = datetime.strptime(row["data"], "%d/%m/%Y").date()`; `value = to_float(row["valor"])`.
- Return columns `period`, `value` only (SGS publishes no vintages; the pipeline assigns
  pseudo real-time intervals).

### `src/econbase/sources/bcb_focus.py`

```python
BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"

@register
class BcbFocusSource(Source):
    name = "bcb_focus"
```

`native_id` is `"{resource}/{indicador}"`, e.g. `ExpectativasMercadoInflacao12Meses/IPCA`
(the `/` is legal in a native id, see `docs/IDENTIFIERS.md`).

Parameters:

| key | default | meaning |
|---|---|---|
| `suavizada` | `"N"` | `"S"`/`"N"`; only for the 12- and 24-month resources |
| `data_referencia` | none | e.g. `"2026"` for `ExpectativasMercadoAnuais` |
| `statistic` | `"Mediana"` | which column becomes `value` (`Media`, `Mediana`, ...) |
| `base_calculo` | `0` | Focus publishes two calculation bases |
| `start` | `"2000-01-01"` | first survey date to request |

`fetch_raw`: build the filter from the parameters that apply to the resource, always including
`Indicador eq '<indicador>'` and `Data ge '<start>'`; `$orderby=Data`; page with `$top`/`$skip`
until a page returns fewer rows than `$top` (use `$top=10000`). Concatenate pages into a JSON
array exactly as the SGS connector does. `covers_from = None`.

`parse`: `period` = `Data` (ISO, the survey date, so `freq` is `D`); `value` = the column named
by `statistic`; rows whose statistic is null are dropped. Columns `period`, `value` only.
Raise `SourceError` when the body carries `codigo`/`mensagem` (Olinda's error shape).

### Catalog

`catalog/br/bcb_sgs.yaml` and `catalog/br/bcb_focus.yaml`, plus every new id appended to
`catalog/ids.txt` (a test enforces this). Series to add, with `expected_lag_days` filled from
the observed publication rhythm:

| series | id | freq | concept |
|---|---|---|---|
| IPCA monthly change | `bcb_sgs:433` | M | `cpi_headline` |
| IPCA 12-month | `bcb_sgs:13522` | M | — |
| Selic target | `bcb_sgs:432` | D | `policy_rate` |
| Selic effective (CDI-like) | `bcb_sgs:11` | D | `interbank_rate` |
| IBC-Br | `bcb_sgs:24363` | M | `activity_index` |
| PTAX sell (USD/BRL) | `bcb_sgs:1` | D | `fx_spot_usd` |
| Swap DI-Pré 360 | `bcb_sgs:7806` | D | `swap_1y` |
| Credit outstanding, total | `bcb_sgs:20539` | M | `credit_outstanding` |
| Average lending rate | `bcb_sgs:20714` | M | `credit_rate` |
| Non-performing loans | `bcb_sgs:21082` | M | `credit_delinquency` |
| Primary balance, 12m % GDP | `bcb_sgs:4649` | M | `primary_balance` |
| Gross general government debt | `bcb_sgs:13762` | M | `gross_debt` |
| Focus: IPCA 12 months ahead | `bcb_focus:ExpectativasMercadoInflacao12Meses/IPCA` | D | `inflation_expectations_12m` |
| Focus: Selic, year end | `bcb_focus:ExpectativasMercadoAnuais/Selic` | D | `policy_rate_expectations_eoy` |

Verify each id with one request before committing it; if an id turns out to be wrong or
retired, say so in the Result section rather than substituting one silently.

Licence: BCB open data, `redistributable: true`, `source_url` pointing at the series page.

## Files you may change

- `src/econbase/sources/bcb_sgs.py` (new), `src/econbase/sources/bcb_focus.py` (new)
- `src/econbase/sources/__init__.py` — only to add the two modules to `CONNECTOR_MODULES`
- `catalog/br/bcb_sgs.yaml`, `catalog/br/bcb_focus.yaml` (new), `catalog/ids.txt`
- `tests/fixtures/bcb_sgs/`, `tests/fixtures/bcb_focus/` — only to add fixtures
- This file's Result section

Everything else is out of scope, and the protected files in `AGENTS.md` section 3 are never
in it. `src/econbase/sources/http.py` already has everything you need (`odata_query`,
`allow_status`, `to_float`, `date_windows`); if you believe it needs a change, say so on the
issue instead of editing it.

## Acceptance tests (already in the repository, currently failing)

`tests/test_source_bcb.py` — run with `uv run pytest tests/test_source_bcb.py -q`

Fixtures are already recorded from the live APIs under `tests/fixtures/bcb_sgs/` and
`tests/fixtures/bcb_focus/`; you should not need to record more, and the suite must not touch
the network.

## Definition of done

- [ ] `uv run pytest tests/test_source_bcb.py -q` passes, and the whole suite stays green
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] Only the files listed above changed; no new dependencies
- [ ] Catalog entries complete, every id appended to `catalog/ids.txt`
- [ ] `uv run econbase update --source bcb_sgs --source bcb_focus` succeeds against the live
      APIs and `econbase check` reports no series as `no_data`
- [ ] Result section below filled in, naming any catalog id that turned out to be wrong

## Result

(filled in by the executor)
