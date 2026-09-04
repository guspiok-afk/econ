"""Acceptance tests for WP-02c: the IBGE (SIDRA) and IPEA connectors.

Written before the implementation, against responses recorded from the live APIs on
2026-09-04. The centrepiece is the period-code ambiguity: SIDRA returns ``202403`` for the
third quarter of 2024 in the GDP table and for March 2024 in the IPCA table, and only the
series frequency tells them apart. Both fixtures are real.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import httpx
import pytest
import respx

from econbase import pipeline, schemas
from econbase.catalog import Catalog, SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, SourceError
from econbase.sources.http import Client
from econbase.store import Store

pytest.importorskip("econbase.sources.sidra", reason="WP-02c not implemented yet")
pytest.importorskip("econbase.sources.ipeadata", reason="WP-02c not implemented yet")

from econbase.sources.ipeadata import IpeadataSource
from econbase.sources.sidra import SidraSource

SIDRA_FIX = Path(__file__).parent / "fixtures" / "sidra"
IPEA_FIX = Path(__file__).parent / "fixtures" / "ipeadata"
SIDRA_BASE = "https://apisidra.ibge.gov.br/values"
IPEA_BASE = "http://www.ipeadata.gov.br/api/odata4"


def sidra_body(name: str) -> bytes:
    return (SIDRA_FIX / name).read_bytes()


def ipea_body(name: str) -> bytes:
    return (IPEA_FIX / name).read_bytes()


def sidra_spec(native_id: str, freq: str = "M", **params) -> SeriesSpec:
    return SeriesSpec(
        source="sidra",
        native_id=native_id,
        entity_id="BR",
        title=f"SIDRA {native_id}",
        freq=freq,
        params=params,
    )


def ipea_spec(native_id: str = "BM12_TJOVER12", freq: str = "M") -> SeriesSpec:
    return SeriesSpec(
        source="ipeadata", native_id=native_id, entity_id="BR", title=native_id, freq=freq
    )


@pytest.fixture
def client() -> Client:
    c = Client(Settings(_env_file=None), sleep=lambda _: None, monotonic=lambda: 0.0)
    yield c
    c.close()


@pytest.fixture
def sidra(client: Client) -> SidraSource:
    return SidraSource(Settings(_env_file=None), client=client)


@pytest.fixture
def ipea(client: Client) -> IpeadataSource:
    return IpeadataSource(Settings(_env_file=None), client=client)


# ------------------------------------------------------- the period-code ambiguity
def test_a_monthly_code_is_a_month(sidra: SidraSource) -> None:
    frame = sidra.parse(
        RawResponse(body=sidra_body("ipca_1737_v63_mensal.json")), sidra_spec("1737/63", "M")
    )
    assert list(frame.columns) == ["period", "value"]
    assert len(frame) == 12
    assert all(p.day == 1 for p in frame["period"]), "the period is the start of the month"
    assert frame["period"].max() == dt.date(2026, 7, 1)
    assert frame["period"].is_monotonic_increasing


def test_the_same_six_digits_are_a_quarter_in_a_quarterly_table(sidra: SidraSource) -> None:
    """202403 is the third quarter of 2024 here and March 2024 in a monthly table."""
    frame = sidra.parse(
        RawResponse(body=sidra_body("pib_1620_v583_trimestral.json")), sidra_spec("1620/583", "Q")
    )
    assert len(frame) == 8
    periods = sorted(frame["period"])
    assert periods[0] == dt.date(2024, 7, 1), "202403 is Q3 2024, so it starts in July"
    assert all(p.month in (1, 4, 7, 10) and p.day == 1 for p in periods)
    assert periods[1] == dt.date(2024, 10, 1), "202404 is Q4 2024"
    assert periods[2] == dt.date(2025, 1, 1), "202501 is Q1 2025"


def test_reading_a_quarterly_table_as_monthly_is_refused(sidra: SidraSource) -> None:
    """A quarter code of 03 would silently become March if the frequency were ignored."""
    with pytest.raises(SourceError):
        sidra.parse(
            RawResponse(body=sidra_body("pib_1620_v583_trimestral.json")),
            sidra_spec("1620/583", "A"),
        )


def test_the_moving_quarter_of_the_labour_survey_is_monthly(sidra: SidraSource) -> None:
    """Code 202508 is labelled jun-jul-ago 2025: monthly data over a three-month window."""
    frame = sidra.parse(
        RawResponse(body=sidra_body("pnad_6381_v4099_desemprego.json")),
        sidra_spec("6381/4099", "M"),
    )
    assert len(frame) == 12
    assert dt.date(2025, 8, 1) in set(frame["period"]), "the period is the window's last month"
    assert math.isclose(
        float(frame.loc[frame["period"] == dt.date(2025, 8, 1), "value"].iloc[0]), 5.6
    )


# ------------------------------------------------------- SIDRA shape and errors
def test_the_header_element_is_not_an_observation(sidra: SidraSource) -> None:
    raw = json.loads(sidra_body("ipca_1737_v63_mensal.json").decode("utf-8"))
    assert raw[0]["V"] == "Valor", "the first element maps keys to labels"
    frame = sidra.parse(
        RawResponse(body=sidra_body("ipca_1737_v63_mensal.json")), sidra_spec("1737/63")
    )
    assert len(frame) == len(raw) - 1


def test_the_period_column_is_found_even_with_an_extra_dimension(sidra: SidraSource) -> None:
    """Table 1620 carries a sector dimension, so the period is not always the third."""
    frame = sidra.parse(
        RawResponse(body=sidra_body("pib_1620_v583_trimestral.json")), sidra_spec("1620/583", "Q")
    )
    assert not frame.empty and frame["period"].notna().all()


def test_the_missing_value_marker_becomes_nan(sidra: SidraSource) -> None:
    """The IPCA's first published period, December 1979, carries '...'."""
    frame = sidra.parse(
        RawResponse(body=sidra_body("ipca_com_valor_ausente.json")), sidra_spec("1737/63")
    )
    dec79 = frame.loc[frame["period"] == dt.date(1979, 12, 1), "value"]
    assert len(dec79) == 1 and math.isnan(float(dec79.iloc[0]))
    jan80 = frame.loc[frame["period"] == dt.date(1980, 1, 1), "value"].iloc[0]
    assert math.isclose(float(jan80), 6.62)


def test_an_index_series_keeps_its_precision(sidra: SidraSource) -> None:
    frame = sidra.parse(
        RawResponse(body=sidra_body("ipca_1737_v2266_indice.json")), sidra_spec("1737/2266")
    )
    assert float(frame["value"].max()) > 7000, "the IPCA index is in the thousands"


def test_accented_labels_decode_as_utf8(sidra: SidraSource) -> None:
    """The response is UTF-8 despite what a Windows console shows; do not switch to latin-1."""
    text = sidra_body("ipca_1737_v63_mensal.json").decode("utf-8")
    assert "Variação mensal" in text


def test_a_plain_text_error_body_is_rejected(sidra: SidraSource) -> None:
    with pytest.raises(SourceError):
        sidra.parse(
            RawResponse(body=sidra_body("tabela_invalida_400.txt")), sidra_spec("999999/63")
        )


@respx.mock
def test_fetch_builds_the_path_from_the_catalog_entry(sidra: SidraSource) -> None:
    route = respx.get(url__startswith=SIDRA_BASE).mock(
        return_value=httpx.Response(200, content=sidra_body("pib_1620_v583_trimestral.json"))
    )
    raw = sidra.fetch_raw(sidra_spec("1620/583", "Q", classifications="c11255/90707"))
    url = str(route.calls[0].request.url)
    assert "/t/1620/" in url and "/v/583/" in url and "c11255/90707" in url
    assert "/p/all" in url, "the whole history is one cheap request"
    assert raw.covers_from is None


# ------------------------------------------------------- IPEA
def test_ipea_takes_the_date_and_ignores_the_utc_offset(ipea: IpeadataSource) -> None:
    """1974-01-01T00:00:00-02:00 must stay 1974-01-01, whatever the offset of the day."""
    frame = ipea.parse(RawResponse(body=ipea_body("selic_mensal.json")), ipea_spec())
    assert list(frame.columns) == ["period", "value"]
    assert frame["period"].min() == dt.date(1974, 1, 1)
    assert all(p.day == 1 for p in frame["period"])
    first = frame.loc[frame["period"] == dt.date(1974, 1, 1), "value"].iloc[0]
    assert math.isclose(float(first), 1.46)


def test_ipea_rejects_a_series_that_came_back_empty(ipea: IpeadataSource) -> None:
    """IPEA answers 200 with an empty list for a code that does not exist."""
    with pytest.raises(SourceError):
        ipea.parse(RawResponse(body=ipea_body("serie_vazia.json")), ipea_spec("PAN12_IBCBRG12"))


@respx.mock
def test_ipea_requests_the_series_by_its_code(ipea: IpeadataSource) -> None:
    route = respx.get(url__startswith=IPEA_BASE).mock(
        return_value=httpx.Response(200, content=ipea_body("selic_mensal.json"))
    )
    ipea.fetch_raw(ipea_spec("BM12_TJOVER12"))
    assert "BM12_TJOVER12" in str(route.calls[0].request.url)


# ------------------------------------------------------- end to end
CONCEPTS_YAML = """\
concepts:
  gdp_real: {description: Real GDP, unit_kind: index, default_agg: mean}
  unemployment_rate: {description: Unemployment, unit_kind: pct, default_agg: mean}
"""

ENTITIES_YAML = """\
entities:
  - {entity_id: BR, entity_type: country, name: Brazil}
"""

SIDRA_YAML = """\
source: sidra
defaults: {entity_id: BR, license: IBGE open data, redistributable: true}
series:
  - native_id: 1620/583
    concept_id: gdp_real
    title: GDP volume index, chained
    unit: index
    freq: Q
    seasonal_adj: true
    expected_lag_days: 60
    params: {classifications: c11255/90707}
  - native_id: 6381/4099
    concept_id: unemployment_rate
    title: Unemployment rate, moving quarter ending in the reference month
    unit: pct
    freq: M
    expected_lag_days: 45
"""


@pytest.fixture
def br_catalog(tmp_path: Path) -> Catalog:
    root = tmp_path / "catalog"
    (root / "br").mkdir(parents=True)
    (root / "concepts.yaml").write_text(CONCEPTS_YAML, encoding="utf-8")
    (root / "entities.yaml").write_text(ENTITIES_YAML, encoding="utf-8")
    (root / "br" / "sidra.yaml").write_text(SIDRA_YAML, encoding="utf-8")
    return Catalog.load(root)


@respx.mock
def test_update_stores_quarterly_and_monthly_series_side_by_side(
    store: Store, br_catalog: Catalog, sidra: SidraSource
) -> None:
    respx.get(url__startswith=f"{SIDRA_BASE}/t/1620").mock(
        return_value=httpx.Response(200, content=sidra_body("pib_1620_v583_trimestral.json"))
    )
    respx.get(url__startswith=f"{SIDRA_BASE}/t/6381").mock(
        return_value=httpx.Response(200, content=sidra_body("pnad_6381_v4099_desemprego.json"))
    )
    summary = pipeline.update(
        store,
        br_catalog,
        {"sidra": sidra},
        now=dt.datetime(2026, 9, 4, 12, tzinfo=dt.UTC),
        tz="America/Sao_Paulo",
    )
    assert summary.status == "ok", [o.error for o in summary.outcomes]

    gdp = schemas.to_pandas(store.observations(["sidra:1620/583"]))
    assert len(gdp) == 8
    assert set(p.month for p in gdp["period"]) <= {1, 4, 7, 10}

    unemployment = schemas.to_pandas(store.observations(["sidra:6381/4099"]))
    assert len(unemployment) == 12

    series = schemas.to_pandas(store.read("series")).set_index("series_id")
    assert series.loc["sidra:1620/583", "freq"] == "Q"
    assert series.loc["sidra:6381/4099", "freq"] == "M"
