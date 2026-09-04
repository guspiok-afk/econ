"""Acceptance tests for WP-02b: the BCB time-series and Focus expectations connectors.

Written before the implementation. Every fixture was recorded from the live APIs on
2026-09-04, including the four error shapes the BCB uses, so the traps are exercised rather
than imagined:

* a daily series refused without a date window (HTTP 406)
* a window with no observations (HTTP 404 with a JSON body, not an empty list)
* an unknown series id (HTTP 200 with an HTML page)
* Olinda's OData error shape (HTTP 400 with ``codigo``/``mensagem``)
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from econbase import pipeline, schemas
from econbase.catalog import Catalog, SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, SourceError
from econbase.sources.http import Client
from econbase.store import Store

pytest.importorskip("econbase.sources.bcb_sgs", reason="WP-02b not implemented yet")
pytest.importorskip("econbase.sources.bcb_focus", reason="WP-02b not implemented yet")

from econbase.sources.bcb_focus import BcbFocusSource
from econbase.sources.bcb_sgs import BcbSgsSource

SGS_FIX = Path(__file__).parent / "fixtures" / "bcb_sgs"
FOCUS_FIX = Path(__file__).parent / "fixtures" / "bcb_focus"
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados"
FOCUS_BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"


def sgs_body(name: str) -> bytes:
    return (SGS_FIX / name).read_bytes()


def focus_body(name: str) -> bytes:
    return (FOCUS_FIX / name).read_bytes()


def sgs_spec(native_id: str, freq: str = "M", **params) -> SeriesSpec:
    return SeriesSpec(
        source="bcb_sgs",
        native_id=native_id,
        entity_id="BR",
        title=f"SGS {native_id}",
        freq=freq,
        params=params,
    )


def focus_spec(native_id: str, **params) -> SeriesSpec:
    return SeriesSpec(
        source="bcb_focus",
        native_id=native_id,
        entity_id="BR",
        title=f"Focus {native_id}",
        freq="D",
        params=params,
    )


@pytest.fixture
def client() -> Client:
    c = Client(Settings(_env_file=None), sleep=lambda _: None, monotonic=lambda: 0.0)
    yield c
    c.close()


@pytest.fixture
def sgs(client: Client) -> BcbSgsSource:
    return BcbSgsSource(Settings(_env_file=None), client=client)


@pytest.fixture
def focus(client: Client) -> BcbFocusSource:
    return BcbFocusSource(Settings(_env_file=None), client=client)


# ---------------------------------------------------------------- SGS parsing
def test_sgs_parses_brazilian_dates_and_dotted_decimals(sgs: BcbSgsSource) -> None:
    frame = sgs.parse(RawResponse(body=sgs_body("433_ipca_2026.json")), sgs_spec("433"))
    assert list(frame.columns) == ["period", "value"], "SGS publishes no vintages"
    assert len(frame) == 7
    assert frame.loc[0, "period"] == dt.date(2026, 1, 1), "01/01/2026 is day/month/year"
    assert math.isclose(float(frame.loc[0, "value"]), 0.33)
    assert all(isinstance(p, dt.date) for p in frame["period"])
    assert frame["period"].is_monotonic_increasing


def test_sgs_parses_a_daily_series(sgs: BcbSgsSource) -> None:
    frame = sgs.parse(RawResponse(body=sgs_body("432_selic_ago2026.json")), sgs_spec("432", "D"))
    assert len(frame) == 31, "the Selic target is published for every calendar day"
    assert frame["period"].min() == dt.date(2026, 8, 1)
    assert frame["period"].max() == dt.date(2026, 8, 31)
    assert math.isclose(float(frame["value"].iloc[-1]), 14.00)


def test_sgs_parses_a_business_day_series(sgs: BcbSgsSource) -> None:
    frame = sgs.parse(RawResponse(body=sgs_body("1_ptax_ago2026.json")), sgs_spec("1", "B"))
    assert len(frame) == 21, "PTAX only exists on business days"
    assert math.isclose(float(frame.loc[0, "value"]), 5.0723)


def test_sgs_parses_a_windowed_body_made_of_several_pages(sgs: BcbSgsSource) -> None:
    """A windowed fetch archives a JSON array of window bodies; parse must merge them."""
    merged = (
        b"[" + sgs_body("433_ipca_2026.json") + b"," + sgs_body("432_selic_ago2026.json") + b"]"
    )
    frame = sgs.parse(RawResponse(body=merged), sgs_spec("433"))
    assert len(frame) == 7 + 31


def test_sgs_rejects_the_html_page_of_an_unknown_series(sgs: BcbSgsSource) -> None:
    """An unknown id answers 200 with HTML; a typo must not become a silent empty series."""
    with pytest.raises(SourceError):
        sgs.parse(RawResponse(body=sgs_body("unknown_series.html")), sgs_spec("99999999"))


def test_sgs_rejects_a_body_without_the_expected_keys(sgs: BcbSgsSource) -> None:
    with pytest.raises(SourceError):
        sgs.parse(RawResponse(body=b'[{"date": "2026-01-01", "value": 1}]'), sgs_spec("433"))


# ---------------------------------------------------------------- SGS fetching
@respx.mock
def test_sgs_fetches_a_monthly_series_without_a_window(sgs: BcbSgsSource) -> None:
    route = respx.get(SGS_URL.format("433")).mock(
        return_value=httpx.Response(200, content=sgs_body("433_ipca_2026.json"))
    )
    raw = sgs.fetch_raw(sgs_spec("433"))
    assert route.call_count == 1
    params = dict(route.calls[0].request.url.params)
    assert params["formato"] == "json"
    assert "dataInicial" not in params, "monthly series answer fine without a window"
    assert raw.covers_from is None and raw.ext == "json"


@respx.mock
def test_sgs_windows_a_daily_series_because_the_api_refuses_the_full_history(
    sgs: BcbSgsSource,
) -> None:
    """Without a window the BCB answers 406, so daily series must be swept in windows."""
    route = respx.get(SGS_URL.format("432")).mock(
        return_value=httpx.Response(200, content=sgs_body("432_selic_ago2026.json"))
    )
    sgs.fetch_raw(sgs_spec("432", "D", start="2000-01-01", window_years=10))
    assert route.call_count >= 3, "2000 to today is at least three ten-year windows"
    for call in route.calls:
        params = dict(call.request.url.params)
        assert "dataInicial" in params and "dataFinal" in params
        start = dt.datetime.strptime(params["dataInicial"], "%d/%m/%Y").date()
        end = dt.datetime.strptime(params["dataFinal"], "%d/%m/%Y").date()
        assert (end - start).days <= 3653, "windows must stay inside the ten-year limit"
    first = dict(route.calls[0].request.url.params)
    assert first["dataInicial"] == "01/01/2000"


@respx.mock
def test_sgs_treats_an_empty_window_as_no_rows_not_as_a_failure(sgs: BcbSgsSource) -> None:
    """The BCB answers a window with no observations with 404; early windows are often empty."""
    route = respx.get(SGS_URL.format("432")).mock(
        side_effect=[
            httpx.Response(404, content=sgs_body("433_empty_window.json")),
            httpx.Response(200, content=sgs_body("432_selic_ago2026.json")),
            httpx.Response(404, content=sgs_body("433_empty_window.json")),
        ]
    )
    raw = sgs.fetch_raw(sgs_spec("432", "D", start="2006-01-01", window_years=10))
    assert route.call_count == 3
    frame = sgs.parse(raw, sgs_spec("432", "D"))
    assert len(frame) == 31, "only the window that had data contributes rows"


@respx.mock
def test_sgs_reports_the_window_limit_clearly(sgs: BcbSgsSource) -> None:
    """A 406 means the window was too long; the message must say so."""
    respx.get(SGS_URL.format("432")).mock(
        return_value=httpx.Response(406, content=sgs_body("432_window_too_long_406.json"))
    )
    with pytest.raises(SourceError) as exc:
        sgs.fetch_raw(sgs_spec("432", "D", start="2000-01-01", window_years=30))
    assert "janela" in str(exc.value) or "window" in str(exc.value).lower()


@respx.mock
def test_sgs_since_narrows_the_sweep_and_sets_covers_from(sgs: BcbSgsSource) -> None:
    respx.get(SGS_URL.format("432")).mock(
        return_value=httpx.Response(200, content=sgs_body("432_selic_ago2026.json"))
    )
    since = dt.date(2026, 1, 1)
    raw = sgs.fetch_raw(sgs_spec("432", "D"), since=since)
    assert raw.covers_from == since, "an incremental fetch must not close older periods"


# ---------------------------------------------------------------- Focus
def test_focus_takes_the_median_of_the_survey(focus: BcbFocusSource) -> None:
    frame = focus.parse(
        RawResponse(body=focus_body("ipca_12m.json")),
        focus_spec("ExpectativasMercadoInflacao12Meses/IPCA"),
    )
    assert list(frame.columns) == ["period", "value"]
    assert len(frame) == 5
    assert frame["period"].max() == dt.date(2026, 8, 28), "period is the survey date"
    latest = frame.loc[frame["period"].idxmax(), "value"]
    assert math.isclose(float(latest), 4.3455), "median IPCA expected 12 months ahead"


def test_focus_can_take_a_different_statistic(focus: BcbFocusSource) -> None:
    frame = focus.parse(
        RawResponse(body=focus_body("ipca_12m.json")),
        focus_spec("ExpectativasMercadoInflacao12Meses/IPCA", statistic="Media"),
    )
    latest = frame.loc[frame["period"].idxmax(), "value"]
    assert math.isclose(float(latest), 4.2964)


def test_focus_parses_the_annual_resource(focus: BcbFocusSource) -> None:
    frame = focus.parse(
        RawResponse(body=focus_body("selic_anuais.json")),
        focus_spec("ExpectativasMercadoAnuais/Selic", data_referencia="2026"),
    )
    assert len(frame) == 5
    latest = frame.loc[frame["period"].idxmax(), "value"]
    assert math.isclose(float(latest), 13.75)


def test_focus_rejects_an_olinda_error_body(focus: BcbFocusSource) -> None:
    with pytest.raises(SourceError):
        focus.parse(
            RawResponse(body=focus_body("bad_filter_400.json")),
            focus_spec("ExpectativasMercadoInflacao12Meses/IPCA"),
        )


@respx.mock
def test_focus_encodes_spaces_as_percent_twenty_not_plus(focus: BcbFocusSource) -> None:
    """Olinda rejects '+' with an error that names Edm.Boolean; it needs %20."""
    route = respx.get(url__startswith=FOCUS_BASE).mock(
        return_value=httpx.Response(200, content=focus_body("ipca_12m.json"))
    )
    focus.fetch_raw(focus_spec("ExpectativasMercadoInflacao12Meses/IPCA"))
    query = str(route.calls[0].request.url).split("?", 1)[1]
    assert "+" not in query, "a '+' in the query makes Olinda answer 400"
    assert "%20" in query
    assert "Indicador%20eq%20'IPCA'" in query or "Indicador%20eq%20%27IPCA%27" in query


@respx.mock
def test_focus_filters_by_the_parameters_of_the_catalog_entry(focus: BcbFocusSource) -> None:
    route = respx.get(url__startswith=FOCUS_BASE).mock(
        return_value=httpx.Response(200, content=focus_body("selic_anuais.json"))
    )
    focus.fetch_raw(focus_spec("ExpectativasMercadoAnuais/Selic", data_referencia="2026"))
    url = str(route.calls[0].request.url)
    assert "ExpectativasMercadoAnuais" in url
    assert "Selic" in url and "2026" in url


@respx.mock
def test_focus_pages_until_a_short_page(focus: BcbFocusSource) -> None:
    full = json.loads(focus_body("ipca_12m.json"))
    big = {"value": full["value"] * 2000}  # 10000 rows: a full page
    route = respx.get(url__startswith=FOCUS_BASE).mock(
        side_effect=[
            httpx.Response(200, json=big),
            httpx.Response(200, content=focus_body("ipca_12m.json")),
        ]
    )
    focus.fetch_raw(focus_spec("ExpectativasMercadoInflacao12Meses/IPCA"))
    assert route.call_count == 2, "stop when a page comes back shorter than $top"
    assert "skip" in str(route.calls[1].request.url).lower()


# ---------------------------------------------------------------- end to end
CONCEPTS_YAML = """concepts:
  cpi_headline: {description: IPCA, unit_kind: pct, default_agg: sum}
  policy_rate: {description: Selic, unit_kind: pct_pa, default_agg: eop}
  inflation_expectations_12m:
    description: Focus IPCA 12 months ahead
    unit_kind: pct
    default_agg: last
"""

ENTITIES_YAML = """entities:
  - {entity_id: BR, entity_type: country, name: Brazil}
"""

SGS_YAML = """source: bcb_sgs
defaults: {entity_id: BR, license: BCB open data, redistributable: true}
series:
  - native_id: '433'
    concept_id: cpi_headline
    title: IPCA
    unit: pct
    freq: M
    expected_lag_days: 12
"""

FOCUS_YAML = """source: bcb_focus
defaults: {entity_id: BR, license: BCB open data, redistributable: true}
series:
  - native_id: ExpectativasMercadoInflacao12Meses/IPCA
    concept_id: inflation_expectations_12m
    title: Focus IPCA 12 months ahead
    unit: pct
    freq: D
    expected_lag_days: 7
"""


@pytest.fixture
def br_catalog(tmp_path: Path) -> Catalog:
    root = tmp_path / "catalog"
    (root / "br").mkdir(parents=True)
    (root / "concepts.yaml").write_text(CONCEPTS_YAML, encoding="utf-8")
    (root / "entities.yaml").write_text(ENTITIES_YAML, encoding="utf-8")
    (root / "br" / "sgs.yaml").write_text(SGS_YAML, encoding="utf-8")
    (root / "br" / "focus.yaml").write_text(FOCUS_YAML, encoding="utf-8")
    return Catalog.load(root)


@respx.mock
def test_update_stores_both_sources(
    store: Store, br_catalog: Catalog, sgs: BcbSgsSource, focus: BcbFocusSource
) -> None:
    respx.get(SGS_URL.format("433")).mock(
        return_value=httpx.Response(200, content=sgs_body("433_ipca_2026.json"))
    )
    respx.get(url__startswith=FOCUS_BASE).mock(
        return_value=httpx.Response(200, content=focus_body("ipca_12m.json"))
    )
    summary = pipeline.update(
        store,
        br_catalog,
        {"bcb_sgs": sgs, "bcb_focus": focus},
        now=dt.datetime(2026, 9, 4, 12, tzinfo=dt.UTC),
        tz="America/Sao_Paulo",
    )
    assert summary.status == "ok", [o.error for o in summary.outcomes]

    ipca = schemas.to_pandas(store.observations(["bcb_sgs:433"]))
    assert len(ipca) == 7
    assert ipca["realtime_start"].unique().tolist() == [dt.date(2026, 9, 4)], (
        "SGS has no vintages, so the store records pseudo real-time intervals"
    )

    expectations = schemas.to_pandas(
        store.observations(["bcb_focus:ExpectativasMercadoInflacao12Meses/IPCA"])
    )
    assert len(expectations) == 5

    raw_index = schemas.to_pandas(store.read("raw_index"))
    assert set(raw_index["source"]) == {"bcb_sgs", "bcb_focus"}
    assert raw_index["stored"].all()


@respx.mock
def test_a_revision_of_a_brazilian_series_opens_a_second_interval(
    store: Store, br_catalog: Catalog, sgs: BcbSgsSource, focus: BcbFocusSource
) -> None:
    """The IBGE revises the IPCA; the store must keep both readings."""
    original = json.loads(sgs_body("433_ipca_2026.json"))
    revised = [dict(row) for row in original]
    revised[-1] = {**revised[-1], "valor": "0.11"}
    respx.get(SGS_URL.format("433")).mock(
        side_effect=[
            httpx.Response(200, json=original),
            httpx.Response(200, json=revised),
        ]
    )
    respx.get(url__startswith=FOCUS_BASE).mock(
        return_value=httpx.Response(200, content=focus_body("ipca_12m.json"))
    )
    sources = {"bcb_sgs": sgs, "bcb_focus": focus}
    for day in (4, 5):
        pipeline.update(
            store,
            br_catalog,
            sources,
            now=dt.datetime(2026, 9, day, 12, tzinfo=dt.UTC),
            tz="America/Sao_Paulo",
        )
    history = schemas.to_pandas(store.observations(["bcb_sgs:433"], include_history=True))
    july = history[history["period"] == dt.date(2026, 7, 1)].sort_values("realtime_start")
    assert len(july) == 2
    assert math.isclose(float(july["value"].iloc[0]), 0.07)
    assert july["realtime_end"].iloc[0] == dt.date(2026, 9, 5)
    assert math.isclose(float(july["value"].iloc[1]), 0.11)
    assert july["realtime_end"].iloc[1] is None

    asof = schemas.to_pandas(store.observations(["bcb_sgs:433"], asof=dt.date(2026, 9, 4)))
    assert math.isclose(float(asof[asof["period"] == dt.date(2026, 7, 1)]["value"].iloc[0]), 0.07)


def test_pandas_import_is_used() -> None:
    """Keep the pandas import honest for linting; the connectors return DataFrames."""
    assert isinstance(pd.DataFrame(), pd.DataFrame)
