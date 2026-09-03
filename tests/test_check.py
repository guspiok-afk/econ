from __future__ import annotations

import datetime as dt

from econbase import pipeline
from econbase.catalog import Catalog
from econbase.sources.base import StaticSource
from econbase.store import Store

T1 = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)


def test_freshness_classification(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    # fetch everything except the quarterly US series so it shows up as no_data
    pipeline.update(
        store,
        catalog,
        {"static": static_source},
        now=T1,
        tz="UTC",
        series_ids=["static:ipca", "static:selic"],
    )
    report = pipeline.check(store, catalog, today=dt.date(2026, 9, 3)).set_index("series_id")

    # monthly, last period July, lag 12: August should be out by Sept 12 -> still ok on Sept 3
    ipca = report.loc["static:ipca"]
    assert ipca["status"] == "ok"
    assert ipca["expected_by"] == dt.date(2026, 9, 12)
    assert ipca["days_stale"] == 0

    # daily, last Aug 29, lag 1: Aug 30 should be out by Aug 31 -> stale by 3 days on Sept 3
    selic = report.loc["static:selic"]
    assert selic["status"] == "stale"
    assert selic["expected_by"] == dt.date(2026, 8, 31)
    assert selic["days_stale"] == 3

    assert report.loc["static:gdp_us", "status"] == "no_data"


def test_quarterly_and_unknown_lag(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    pipeline.update(store, catalog, {"static": static_source}, now=T1, tz="UTC")
    # quarterly, last period 2026Q1, lag 30: Q2 should be out by July 30 -> stale on Sept 3
    report = pipeline.check(store, catalog, today=dt.date(2026, 9, 3)).set_index("series_id")
    gdp = report.loc["static:gdp_us"]
    assert gdp["status"] == "stale" and gdp["expected_by"] == dt.date(2026, 7, 30)

    assert pipeline._period_end(dt.date(2026, 2, 1), "M") == dt.date(2026, 2, 28)
    assert pipeline._period_end(dt.date(2026, 10, 1), "Q") == dt.date(2026, 12, 31)
    assert pipeline._period_end(dt.date(2026, 1, 1), "A") == dt.date(2026, 12, 31)
    assert pipeline._next_period_start(dt.date(2026, 12, 1), "M") == dt.date(2027, 1, 1)
    assert pipeline._next_period_start(dt.date(2026, 9, 4), "B") == dt.date(
        2026, 9, 7
    )  # Friday -> Monday
    assert pipeline._next_period_start(dt.date(2026, 10, 1), "Q") == dt.date(2027, 1, 1)
