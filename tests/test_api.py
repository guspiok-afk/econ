"""The read API: concept resolution, panels, and the as-of guarantee.

The last group is the important one. A backtest is only worth running if a panel built as of a
past date cannot contain anything published after it, so those tests use the recorded FRED
vintages of US GDP: 2020Q2 read 17,205.8 when it was first published and reads 19,078.0 today,
after the 2023 comprehensive revision.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from econbase import pipeline
from econbase.api import Api, ApiError, connect
from econbase.catalog import Catalog
from econbase.settings import Settings
from econbase.sources.fred import ENDPOINT, FredSource
from econbase.sources.http import Client
from econbase.store import Store

FRED_FIX = Path(__file__).parent / "fixtures" / "fred"

CONCEPTS_YAML = """\
concepts:
  gdp_real: {description: Real GDP, unit_kind: level, default_agg: sum}
  govt_yield_10y: {description: Ten-year yield, unit_kind: pct_pa, default_agg: eop}
  cpi_headline: {description: CPI, unit_kind: pct, default_agg: sum}
"""

ENTITIES_YAML = """\
entities:
  - {entity_id: US, entity_type: country, name: United States}
  - {entity_id: BR, entity_type: country, name: Brazil}
"""

FRED_YAML = """\
source: fred
defaults: {entity_id: US, license: FRED terms, redistributable: false}
series:
  - native_id: GDPC1
    concept_id: gdp_real
    title: Real Gross Domestic Product
    unit: bn chained 2017 USD
    freq: Q
    seasonal_adj: true
    expected_lag_days: 30
  - native_id: DGS10
    concept_id: govt_yield_10y
    title: Ten-year Treasury constant maturity
    unit: percent per year
    freq: B
    expected_lag_days: 1
    params: {vintages: false}
"""


@pytest.fixture
def catalog_us(tmp_path: Path) -> Catalog:
    root = tmp_path / "catalog"
    (root / "us").mkdir(parents=True)
    (root / "concepts.yaml").write_text(CONCEPTS_YAML, encoding="utf-8")
    (root / "entities.yaml").write_text(ENTITIES_YAML, encoding="utf-8")
    (root / "us" / "fred.yaml").write_text(FRED_YAML, encoding="utf-8")
    return Catalog.load(root)


@pytest.fixture
def loaded(store: Store, catalog_us: Catalog) -> Api:
    """A store holding the recorded FRED vintages of GDP and the daily ten-year yield."""
    settings = Settings(_env_file=None, fred_api_key="test-key")
    client = Client(settings, sleep=lambda _: None, monotonic=lambda: 0.0)
    source = FredSource(settings, client=client)
    with respx.mock:
        respx.get(ENDPOINT).mock(
            side_effect=lambda request: httpx.Response(
                200,
                content=(FRED_FIX / "GDPC1_2024_vintages.json").read_bytes()
                if "GDPC1" in str(request.url)
                else (FRED_FIX / "DGS10_novintage_2026_01.json").read_bytes(),
            )
        )
        pipeline.update(
            store,
            catalog_us,
            {"fred": source},
            now=dt.datetime(2026, 9, 4, 12, tzinfo=dt.UTC),
            tz="UTC",
        )
    client.close()
    return Api(store, catalog_us)


# ---------------------------------------------------------------------------- resolution
def test_a_concept_resolves_to_the_series_of_that_country(loaded: Api) -> None:
    key = loaded.resolve("gdp_real", "US")
    assert key.series_id == "fred:GDPC1" and key.label == "gdp_real"


def test_a_series_id_resolves_without_an_entity(loaded: Api) -> None:
    key = loaded.resolve("fred:GDPC1")
    assert key.concept == "gdp_real" and key.entity == "US"


def test_a_concept_without_an_entity_says_so(loaded: Api) -> None:
    with pytest.raises(ApiError, match="needs an entity"):
        loaded.resolve("gdp_real")


def test_a_concept_no_country_carries_names_the_ones_that_do(loaded: Api) -> None:
    with pytest.raises(ApiError, match=r"no series carries 'gdp_real' for BR.*it exists for US"):
        loaded.resolve("gdp_real", "BR")


def test_an_unknown_concept_suggests_what_exists(loaded: Api) -> None:
    with pytest.raises(ApiError, match="unknown concept"):
        loaded.resolve("gdp_nominal", "US")


def test_the_entity_of_a_series_id_must_agree(loaded: Api) -> None:
    with pytest.raises(ApiError, match="belongs to US"):
        loaded.resolve("fred:GDPC1", "BR")


def test_listing_concepts_and_entities(loaded: Api) -> None:
    assert loaded.concepts("US") == ["gdp_real", "govt_yield_10y"]
    assert loaded.concepts("BR") == []
    assert loaded.entities("gdp_real") == ["US"]
    assert "cpi_headline" in loaded.concepts()


# ---------------------------------------------------------------------------- reading
def test_get_returns_the_current_values(loaded: Api) -> None:
    gdp = loaded.get("gdp_real", entity="US")
    assert list(gdp.columns) == ["period", "value"]
    assert len(gdp) == 4, "four quarters of 2024 in the fixture"
    assert math.isclose(
        float(gdp.loc[gdp["period"] == dt.date(2024, 1, 1), "value"].iloc[0]), 23082.119
    )


def test_start_and_end_trim_the_window(loaded: Api) -> None:
    gdp = loaded.get("gdp_real", entity="US", start="2024-04-01", end="2024-07-01")
    assert list(gdp["period"]) == [dt.date(2024, 4, 1), dt.date(2024, 7, 1)]


def test_a_transform_is_computed_before_the_window_is_trimmed(loaded: Api) -> None:
    """Trimming first would make the first quarter of the window come back empty."""
    growth = loaded.get("gdp_real", entity="US", transform="mom", start="2024-04-01")
    assert not math.isnan(float(growth["value"].iloc[0])), (
        "the change for 2024Q2 needs 2024Q1, which is outside the window"
    )


def test_daily_data_converts_to_monthly_with_an_explicit_aggregation(loaded: Api) -> None:
    monthly = loaded.get("govt_yield_10y", entity="US", freq="M", agg="mean")
    assert len(monthly) == 1, "the fixture covers January 2026 only"
    assert math.isclose(float(monthly["value"].iloc[0]), 4.2135, abs_tol=1e-3)


def test_the_concept_supplies_a_default_aggregation(loaded: Api) -> None:
    """govt_yield_10y declares eop, so a monthly reading takes the month's last value."""
    monthly = loaded.get("govt_yield_10y", entity="US", freq="M")
    last_day = loaded.get("govt_yield_10y", entity="US").iloc[-1]
    assert math.isclose(float(monthly["value"].iloc[0]), float(last_day["value"]))


def test_an_aggregation_without_a_frequency_change_is_refused(loaded: Api) -> None:
    """On a single series a pointless agg is a mistake worth naming."""
    with pytest.raises(ApiError, match="only applies when freq"):
        loaded.get("gdp_real", entity="US", agg="mean")


def test_a_panel_applies_the_aggregation_only_where_it_converts(loaded: Api) -> None:
    """A panel mixes frequencies: quarterly GDP needs no aggregation, the daily yield does."""
    panel = loaded.get_panel(["gdp_real", "govt_yield_10y"], entity="US", freq="Q", agg="mean")
    assert list(panel.columns) == ["gdp_real", "govt_yield_10y"]


def test_arrow_is_available_for_callers_that_want_it(loaded: Api) -> None:
    table = loaded.get("gdp_real", entity="US", as_pandas=False)
    assert table.num_rows == 4 and table.column_names == ["period", "value"]


def test_a_bad_date_argument_names_itself(loaded: Api) -> None:
    with pytest.raises(ApiError, match="start must be an ISO date"):
        loaded.get("gdp_real", entity="US", start="last january")


# ---------------------------------------------------------------------------- as of
def test_asof_returns_what_was_known_on_that_date(loaded: Api) -> None:
    """The first estimate of 2024Q1, published 2024-04-25 and revised a month later."""
    first = loaded.get("gdp_real", entity="US", asof="2024-05-01")
    assert len(first) == 1, "only the first quarter had been published by then"
    assert math.isclose(float(first["value"].iloc[0]), 22768.866)

    today = loaded.get("gdp_real", entity="US", end="2024-01-01")
    assert math.isclose(float(today["value"].iloc[0]), 23082.119)


def test_asof_on_the_last_day_of_a_vintage_still_resolves(loaded: Api) -> None:
    boundary = loaded.get("gdp_real", entity="US", asof="2024-05-29")
    assert math.isclose(float(boundary["value"].iloc[0]), 22768.866)
    next_day = loaded.get("gdp_real", entity="US", asof="2024-05-30")
    assert math.isclose(float(next_day["value"].iloc[0]), 22749.846)


def test_asof_before_any_publication_is_empty_not_wrong(loaded: Api) -> None:
    assert loaded.get("gdp_real", entity="US", asof="2024-01-01").empty


def test_a_transform_on_an_asof_panel_uses_only_what_was_known(loaded: Api) -> None:
    """The growth rate of a backtest must be computed from the vintage, not from today."""
    asof_growth = loaded.get("gdp_real", entity="US", asof="2024-08-01", transform="mom")
    today_growth = loaded.get("gdp_real", entity="US", transform="mom")
    q2 = dt.date(2024, 4, 1)
    a = float(asof_growth.loc[asof_growth["period"] == q2, "value"].iloc[0])
    b = float(today_growth.loc[today_growth["period"] == q2, "value"].iloc[0])
    assert not math.isclose(a, b), (
        "the revisions moved the growth rate; the panel must not mix them"
    )


def test_vintages_expose_the_whole_audit_trail(loaded: Api) -> None:
    history = loaded.vintages("gdp_real", "US")
    q1 = history[history["period"] == dt.date(2024, 1, 1)]
    assert len(q1) == 5, "four revisions and the current reading"
    assert q1["realtime_end"].isna().sum() == 1


# ---------------------------------------------------------------------------- panels
def test_a_panel_aligns_series_on_one_index(loaded: Api) -> None:
    panel = loaded.get_panel(["gdp_real", "govt_yield_10y"], entity="US", freq="Q", agg="mean")
    assert list(panel.columns) == ["gdp_real", "govt_yield_10y"]
    assert panel.index.name == "period"
    assert all(isinstance(d, dt.date) for d in panel.index)


def test_a_panel_across_countries_labels_the_columns(loaded: Api) -> None:
    panel = loaded.get_panel(["gdp_real"], entities=["US"])
    assert list(panel.columns) == ["gdp_real@US"]


def test_a_pair_names_its_own_country(loaded: Api) -> None:
    """The form a two-country model needs, and the one the cross product cannot express.

    Uncovered parity wants the exchange rate and the policy rate for Brazil and the policy rate
    for the United States. `entities=['BR','US']` asks for all four and fails on the one no
    series carries; `entity='BR'` drops the suffix the models resolve on.
    """
    panel = loaded.get_panel([("gdp_real", "US"), ("govt_yield_10y", "US")], freq="Q", agg="mean")
    assert list(panel.columns) == ["gdp_real@US", "govt_yield_10y@US"]


def test_pairs_and_entities_together_are_refused(loaded: Api) -> None:
    with pytest.raises(ApiError, match="not both"):
        loaded.get_panel([("gdp_real", "US")], entities=["US"])


def test_a_panel_can_be_trimmed_by_date(loaded: Api) -> None:
    """Bounds arrive as dates and the index holds Timestamps; pandas refuses to compare the two.

    The previous version walked the index element by element, which worked only while the index
    carried date objects. It broke silently the moment the panel started returning a proper time
    index, and no test noticed until a live run raised a TypeError.
    """
    whole = loaded.get_panel(["gdp_real"], entity="US")
    assert len(whole) > 2, "the fixture must span enough periods to cut"
    middle = whole.index[len(whole) // 2]

    cut = loaded.get_panel(["gdp_real"], entity="US", start=middle.date())
    assert 0 < len(cut) < len(whole)
    assert cut.index.min() >= middle

    both = loaded.get_panel(
        ["gdp_real"], entity="US", start=whole.index[0].date(), end=middle.date()
    )
    assert both.index.max() <= middle


def test_a_panel_carries_a_datetime_index(loaded: Api) -> None:
    """Models resample, filter and shift on this index, and every fixture parses its dates.

    Returning plain date objects meant a model was validated against one kind of index and run
    against another, which is silent until a Hodrick-Prescott filter or a calendar-aware
    operation quietly behaves differently.
    """
    panel = loaded.get_panel(["gdp_real"], entity="US")
    assert isinstance(panel.index, pd.DatetimeIndex)
    assert panel.index.name == "period"


def test_an_inner_join_keeps_only_shared_periods(loaded: Api) -> None:
    outer = loaded.get_panel(["gdp_real", "govt_yield_10y"], entity="US", freq="Q", agg="mean")
    inner = loaded.get_panel(
        ["gdp_real", "govt_yield_10y"], entity="US", freq="Q", agg="mean", how="inner"
    )
    assert len(inner) <= len(outer)
    assert inner.notna().all().all()


def test_an_empty_panel_request_is_refused(loaded: Api) -> None:
    with pytest.raises(ApiError, match="at least one key"):
        loaded.get_panel([])


# ---------------------------------------------------------------------------- metadata
def test_describe_carries_what_a_modeller_needs_to_know(loaded: Api) -> None:
    info = loaded.describe("gdp_real", "US")
    assert info["series_id"] == "fred:GDPC1"
    assert info["freq"] == "Q" and info["seasonal_adj"] is True
    assert info["redistributable"] is False, "licence travels with the series"
    assert info["first_period"] == dt.date(2024, 1, 1)
    assert info["last_period"] == dt.date(2024, 10, 1)


def test_connect_opens_the_real_catalog(data_dir: Path) -> None:
    api = connect("catalog")
    assert "fred:GDPC1" in api.catalog.series
    assert api.store.data_dir == data_dir.resolve()
