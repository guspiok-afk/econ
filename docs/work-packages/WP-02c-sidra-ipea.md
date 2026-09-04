# WP-02c — IBGE (SIDRA) and IPEA connectors

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:antigravity` |
| Branch | `wp/02c-sidra` (already created; the acceptance tests are on it) |
| Issue | (opened when dispatched) |
| Depends on | WP-02a (merged, PR #3) |
| Estimated effort | ~7 h |

## Goal

The two connectors that bring Brazil's statistical institute and IPEA into the store: `sidra`
for the IBGE tables (IPCA and its groups, GDP, unemployment, industrial production, retail and
services) and `ipeadata` for the series IPEA republishes with a stable code. After this WP the
Brazilian side of the catalog is essentially complete.

This package carries a real judgement call — mapping SIDRA's period codes onto the contract's
period-start convention — which is why it is not a mechanical task.

## What the live APIs already taught us

Probed on 2026-09-04. Fixtures reproduce every case; do not rediscover them.

1. **The first element of a SIDRA response is a header map**, not an observation. Its values
   are the human labels of each key. Rows start at index 1.
2. **The period code is ambiguous across frequencies and you must use the series `freq` to
   read it.** Recorded proof: table 1620 (GDP) returns `202403` for *the third quarter of
   2024*, while table 1737 (IPCA) returns `202403` for *March 2024*. Same six characters, two
   meanings.
   - `M` → `YYYYMM`, period = first day of that month
   - `Q` → `YYYYQ` with the quarter in 1–4, period = first day of that quarter
   - `A` → `YYYY`, period = 1 January
3. **Do not hardcode `D3C` as the period column.** Table 1620 carries a fourth dimension
   (sector) and other tables carry classifications, so the position shifts. Find the key whose
   header label starts with `Mês`, `Trimestre`, `Trimestre Móvel` or `Ano`, and whose name
   ends in `C` (the code column, not the `N` label column).
4. **PNAD's "trimestre móvel" is monthly data over a three-month window.** Code `202508` is
   labelled `jun-jul-ago 2025`. Treat it as `freq: M` with the period being the month in the
   code (the window's last month), and say so in the series `title`, because that is how the
   number is cited and it keeps the freshness check honest.
5. **SIDRA responses are UTF-8**, despite what a Windows console shows. Decode as UTF-8. Do
   not "fix" this to latin-1.
6. **A bad table or variable answers HTTP 400 with a plain-text body**, not JSON
   (`Tabela 999999: Tabela inválida`). The shared client already turns that into a
   `SourceError` carrying the text.
7. **Missing values are `"..."`**; `to_float` already maps them to NaN. The IPCA's first
   period (197912) is missing, so this is not hypothetical.
8. **IPEA timestamps carry a shifting UTC offset** (`1974-01-01T00:00:00-02:00` in summer
   time, `-03:00` today). Take the date from the string before the `T` and ignore the offset;
   never convert the timestamp to another zone first.
9. **IPEA answers HTTP 200 with an empty `value` list for a code that does not exist**, so a
   typo becomes a silently empty series unless you reject it. `PAN12_IBCBRG12` behaves this
   way today, and `CAGED12_SALDO12` stops in 2019 because the survey was replaced.

## Contract

### `src/econbase/sources/sidra.py`

```python
ENDPOINT = "https://apisidra.ibge.gov.br/values"


@register
class SidraSource(Source):
    name = "sidra"

    def fetch_raw(self, spec: SeriesSpec, since: date | None = None) -> RawResponse: ...
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame: ...
```

`native_id` is `"{table}/{variable}"`, e.g. `1737/63`.

| param | default | meaning |
|---|---|---|
| `territory` | `"n1/all"` | territorial level path segment |
| `classifications` | none | e.g. `"c11255/90707"`, appended as its own path segment |
| `periods` | `"all"` | the `p/` segment |

`fetch_raw` builds `"{ENDPOINT}/t/{table}/{territory}/v/{variable}/p/{periods}[/{classifications}]"`
and issues one request. `covers_from = None` (`p/all` is the whole history). `ext = "json"`.
`since` is ignored: the full history is a single cheap request (the IPCA is 137 KB).

`parse` decodes UTF-8, drops the header element, resolves the period column as described
above, converts each code with the series `freq`, and returns `period`, `value` only. Raise
`SourceError` when the body is not a JSON list, when the header is missing, when no period
column can be identified, or when a code does not match the shape its frequency requires.

### `src/econbase/sources/ipeadata.py`

```python
ENDPOINT = "http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{code}')"


@register
class IpeadataSource(Source):
    name = "ipeadata"
```

`native_id` is the IPEA code (`BM12_TJOVER12`). `parse` takes `VALDATA` (date part only) and
`VALVALOR` (may be null → NaN), returns `period`, `value`. An empty `value` list raises
`SourceError` naming the code, because IPEA does not distinguish "no such series" from "no
observations".

### Catalog

`catalog/br/ibge_sidra.yaml` and `catalog/br/ipeadata.yaml`, every new id appended to
`catalog/ids.txt`. Verify each id with one request before committing it, and report in the
Result section any that turned out to be retired.

| series | id | freq | concept |
|---|---|---|---|
| IPCA monthly change | `sidra:1737/63` | M | — (BCB 433 already holds `cpi_headline`) |
| IPCA index | `sidra:1737/2266` | M | `cpi_headline_index` |
| GDP volume index, chained | `sidra:1620/583` | Q | `gdp_real` |
| Unemployment rate (moving quarter) | `sidra:6381/4099` | M | `unemployment_rate` |
| Industrial production | `sidra:8888/12606` | M | `industrial_production` |
| Retail sales volume | `sidra:8880/7169` | M | `retail_sales` |
| Services volume | `sidra:5906/8677` | M | — |
| Selic accumulated in the month | `ipeadata:BM12_TJOVER12` | M | — |

Licence: IBGE and IPEA open data, `redistributable: true`.

## Files you may change

- `src/econbase/sources/sidra.py`, `src/econbase/sources/ipeadata.py` (both new)
- `src/econbase/sources/__init__.py` — only to add the modules to `CONNECTOR_MODULES`
- `catalog/br/ibge_sidra.yaml`, `catalog/br/ipeadata.yaml`, `catalog/ids.txt`
- `tests/fixtures/sidra/`, `tests/fixtures/ipeadata/` — only to add fixtures
- This file's Result section

Nothing else, and never the protected files in `AGENTS.md` section 3. If you think
`src/econbase/sources/http.py` needs a change, say so on the issue instead of editing it.

## Acceptance tests (already in the repository, currently skipped)

`tests/test_source_sidra_ipea.py` — `uv run pytest tests/test_source_sidra_ipea.py -q`

The fixtures are recorded; the suite must not touch the network.

## Definition of done

- [ ] `uv run pytest` fully green, `ruff check` and `ruff format --check` clean
- [ ] Only the listed files changed; no new dependencies
- [ ] Catalog complete, ids appended to `catalog/ids.txt`
- [ ] `uv run econbase update --source sidra --source ipeadata` succeeds against the live APIs
- [ ] Result section filled in, naming any retired id

## Result

(filled in by the executor)
