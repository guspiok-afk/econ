"""Safety guards of the update pipeline: they must refuse, loudly, rather than corrupt vintages."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from econbase import pipeline, schemas
from econbase.catalog import Catalog
from econbase.sources.base import StaticSource
from econbase.store import Store

T1 = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
T2 = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)


def monthly(n: int, start: str = "2024-01-01", value: float = 1.0) -> pd.DataFrame:
    periods = [d.date() for d in pd.date_range(start, periods=n, freq="MS")]
    return pd.DataFrame({"period": periods, "value": [value] * n})


def _run(
    store: Store, catalog: Catalog, src: StaticSource, when: dt.datetime
) -> pipeline.RunSummary:
    return pipeline.update(
        store, catalog, {"static": src}, now=when, tz="UTC", series_ids=["static:ipca"]
    )


def test_mass_vanish_is_refused_and_leaves_data_untouched(store: Store, catalog: Catalog) -> None:
    src = StaticSource({"static:ipca": monthly(30)})
    assert _run(store, catalog, src, T1).status == "ok"
    src.frames["static:ipca"] = monthly(5)  # truncated response: 25 of 30 periods gone
    s2 = _run(store, catalog, src, T2)
    err = s2.outcomes[0].error
    assert err and "refusing to close" in err
    obs = schemas.to_pandas(store.observations(["static:ipca"]))
    assert len(obs) == 30 and obs["realtime_end"].isna().all()


def test_small_vanish_is_still_applied(store: Store, catalog: Catalog) -> None:
    src = StaticSource({"static:ipca": monthly(30)})
    _run(store, catalog, src, T1)
    src.frames["static:ipca"] = monthly(27)  # 3 of 30 gone: below both thresholds
    s2 = _run(store, catalog, src, T2)
    assert s2.outcomes[0].error is None and s2.outcomes[0].rows_closed == 3
    assert store.observations(["static:ipca"]).num_rows == 27


def test_run_dated_before_an_existing_vintage_is_refused(store: Store, catalog: Catalog) -> None:
    src = StaticSource({"static:ipca": monthly(3)})
    _run(store, catalog, src, T2)  # first run "tomorrow"
    src.frames["static:ipca"] = monthly(3, value=2.0)
    s = _run(store, catalog, src, T1)  # then a run dated "yesterday" with a revision
    err = s.outcomes[0].error
    assert err and "earlier than an existing vintage" in err
    obs = schemas.to_pandas(store.observations(["static:ipca"], include_history=True))
    assert len(obs) == 3 and set(obs["value"]) == {1.0}


def test_non_numeric_values_are_an_error_not_nan(store: Store, catalog: Catalog) -> None:
    bad = pd.DataFrame({"period": [dt.date(2026, 1, 1)], "value": ["1,23"]})
    src = StaticSource({"static:ipca": bad})
    s = _run(store, catalog, src, T1)
    assert s.outcomes[0].error and "ValueError" in s.outcomes[0].error
    assert store.observations(["static:ipca"]).num_rows == 0


def test_missing_values_are_stored_as_nan_and_compared_as_equal(
    store: Store, catalog: Catalog
) -> None:
    f = pd.DataFrame({"period": [dt.date(2026, 1, 1), dt.date(2026, 2, 1)], "value": [1.0, None]})
    src = StaticSource({"static:ipca": f})
    _run(store, catalog, src, T1)
    s2 = _run(store, catalog, src, T2)
    o = s2.outcomes[0]
    assert (o.rows_new, o.rows_revised, o.rows_closed) == (0, 0, 0)
    obs = schemas.to_pandas(store.observations(["static:ipca"]))
    assert len(obs) == 2 and obs["value"].isna().sum() == 1
