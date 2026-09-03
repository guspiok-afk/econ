from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from tests.conftest import frame, vframe

from econbase import pipeline, schemas
from econbase.catalog import Catalog
from econbase.sources.base import FetchResult, Source, StaticSource
from econbase.store import Store

T1 = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
T2 = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)
T2b = dt.datetime(2026, 9, 2, 18, 0, tzinfo=dt.UTC)
T3 = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.UTC)
D1, D2, D3 = T1.date(), T2.date(), T3.date()


def run(
    store: Store, catalog: Catalog, source: Source, when: dt.datetime, **kw
) -> pipeline.RunSummary:
    return pipeline.update(store, catalog, {"static": source}, now=when, tz="UTC", **kw)


def history(store: Store, series_id: str, period: str) -> pd.DataFrame:
    df = schemas.to_pandas(store.observations([series_id], include_history=True))
    p = dt.date.fromisoformat(period)
    return df[df["period"] == p].sort_values("realtime_start").reset_index(drop=True)


def latest_value(
    store: Store, series_id: str, period: str, asof: dt.date | None = None
) -> float | None:
    df = schemas.to_pandas(store.observations([series_id], asof=asof))
    hit = df[df["period"] == dt.date.fromisoformat(period)]
    return None if hit.empty else float(hit["value"].iloc[0])


def test_first_run_inserts_open_rows(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    summary = run(store, catalog, static_source, T1)
    assert summary.status == "ok" and summary.n_errors == 0
    obs = schemas.to_pandas(store.observations())
    assert len(obs) == 6
    assert obs["realtime_end"].isna().all()
    assert set(obs["realtime_start"]) == {D1}
    assert set(obs["run_id"]) == {summary.run_id}
    rs = schemas.to_pandas(store.read("run_series"))
    assert rs.set_index("series_id").loc["static:ipca", "rows_new"] == 3
    runs = schemas.to_pandas(store.read("runs"))
    assert len(runs) == 1 and runs.loc[0, "n_series"] == 3 and runs.loc[0, "status"] == "ok"
    series = schemas.to_pandas(store.read("series")).set_index("series_id")
    assert series.loc["static:ipca", "first_period"] == dt.date(2026, 5, 1)
    assert series.loc["static:ipca", "last_period"] == dt.date(2026, 7, 1)
    assert store.manifest().catalog_hash == catalog.catalog_hash


def test_revision_creates_two_intervals(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = frame(
        ("2026-05-01", 0.5), ("2026-06-01", 0.35), ("2026-07-01", 0.4)
    )
    s2 = run(store, catalog, static_source, T2)
    o = {x.series_id: x for x in s2.outcomes}["static:ipca"]
    assert (o.rows_fetched, o.rows_new, o.rows_revised, o.rows_closed) == (3, 0, 1, 1)

    h = history(store, "static:ipca", "2026-06-01")
    assert len(h) == 2
    assert (
        h.loc[0, "value"] == 0.3
        and h.loc[0, "realtime_start"] == D1
        and h.loc[0, "realtime_end"] == D2
    )
    assert (
        h.loc[1, "value"] == 0.35
        and h.loc[1, "realtime_start"] == D2
        and h.loc[1, "realtime_end"] is None
    )
    assert latest_value(store, "static:ipca", "2026-06-01") == 0.35
    assert latest_value(store, "static:ipca", "2026-06-01", asof=D1) == 0.3
    assert latest_value(store, "static:ipca", "2026-06-01", asof=D2) == 0.35
    fr = schemas.to_pandas(store.first_release(["static:ipca"]))
    assert float(fr[fr["period"] == dt.date(2026, 6, 1)]["value"].iloc[0]) == 0.3
    # untouched periods keep a single open row
    assert len(history(store, "static:ipca", "2026-05-01")) == 1
    # observations of other series in the same partition are untouched
    assert len(history(store, "static:selic", "2026-08-28")) == 1


def test_vanished_period_is_closed_on_full_history_fetch(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = frame(("2026-05-01", 0.5), ("2026-06-01", 0.3))
    s2 = run(store, catalog, static_source, T2)
    o = {x.series_id: x for x in s2.outcomes}["static:ipca"]
    assert (o.rows_new, o.rows_revised, o.rows_closed) == (0, 0, 1)
    h = history(store, "static:ipca", "2026-07-01")
    assert len(h) == 1 and h.loc[0, "realtime_end"] == D2
    assert latest_value(store, "static:ipca", "2026-07-01") is None
    assert latest_value(store, "static:ipca", "2026-07-01", asof=D1) == 0.4


def test_windowed_fetch_never_touches_periods_outside_the_window(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = frame(("2026-06-01", 0.3), ("2026-07-01", 0.4))
    static_source.covers_from["static:ipca"] = dt.date(2026, 6, 1)
    s2 = run(store, catalog, static_source, T2)
    o = {x.series_id: x for x in s2.outcomes}["static:ipca"]
    assert (o.rows_fetched, o.rows_new, o.rows_revised, o.rows_closed) == (2, 0, 0, 0)
    obs = schemas.to_pandas(store.observations(["static:ipca"]))
    assert len(obs) == 3 and obs["realtime_end"].isna().all()


def test_empty_fetch_is_a_noop_with_warning(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = pd.DataFrame({"period": [], "value": []})
    s2 = run(store, catalog, static_source, T2)
    o = {x.series_id: x for x in s2.outcomes}["static:ipca"]
    assert o.error and "empty" in o.error
    assert s2.status == "partial"
    obs = schemas.to_pandas(store.observations(["static:ipca"]))
    assert len(obs) == 3 and obs["realtime_end"].isna().all()


def test_same_day_revisions_collapse_to_last_value(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = frame(
        ("2026-05-01", 0.5), ("2026-06-01", 0.35), ("2026-07-01", 0.4)
    )
    run(store, catalog, static_source, T2)
    static_source.frames["static:ipca"] = frame(
        ("2026-05-01", 0.5), ("2026-06-01", 0.36), ("2026-07-01", 0.4)
    )
    run(store, catalog, static_source, T2b)
    h = history(store, "static:ipca", "2026-06-01")
    assert len(h) == 2
    assert h.loc[0, "realtime_end"] == D2
    assert (
        h.loc[1, "realtime_start"] == D2
        and h.loc[1, "realtime_end"] is None
        and h.loc[1, "value"] == 0.36
    )
    # logical key is unique across the whole store
    all_rows = schemas.to_pandas(store.observations(include_history=True))
    assert not all_rows.duplicated(["series_id", "period", "realtime_start"]).any()
    # no zero-length intervals
    closed = all_rows[all_rows["realtime_end"].notna()]
    assert (closed["realtime_end"] > closed["realtime_start"]).all()


class VintagedSource(Source):
    name = "static"

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        super().__init__()
        self.frames = frames

    def fetch(self, spec, since=None) -> FetchResult:
        return FetchResult(frame=self.frames[spec.series_id].copy(), raw_body=b"{}", url="v://x")


def test_vintaged_source_upserts_intervals(store: Store, catalog: Catalog) -> None:
    src = VintagedSource({"static:gdp_us": vframe(("2026-01-01", 100.0, "2026-04-30", None))})
    run(store, catalog, src, T1, series_ids=["static:gdp_us"])
    src.frames["static:gdp_us"] = vframe(
        ("2026-01-01", 100.0, "2026-04-30", "2026-05-29"),
        ("2026-01-01", 101.0, "2026-05-29", None),
    )
    s2 = run(store, catalog, src, T2, series_ids=["static:gdp_us"])
    o = s2.outcomes[0]
    assert (o.rows_fetched, o.rows_new, o.rows_revised, o.rows_closed) == (2, 1, 1, 1)
    h = history(store, "static:gdp_us", "2026-01-01")
    assert len(h) == 2
    assert h.loc[0, "realtime_end"] == dt.date(2026, 5, 29) and h.loc[1, "realtime_end"] is None
    assert latest_value(store, "static:gdp_us", "2026-01-01") == 101.0
    assert latest_value(store, "static:gdp_us", "2026-01-01", asof=dt.date(2026, 5, 15)) == 100.0
    # a third identical fetch changes nothing
    s3 = run(store, catalog, src, T3, series_ids=["static:gdp_us"])
    o3 = s3.outcomes[0]
    assert (o3.rows_new, o3.rows_revised) == (0, 0)


def test_raw_archive_dedupes_identical_bodies(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    run(store, catalog, static_source, T1)
    idx1 = schemas.to_pandas(store.read("raw_index"))
    assert len(idx1) == 3 and idx1["stored"].all()
    files_after_1 = sorted(store.raw_dir.rglob("*.gz"))
    assert len(files_after_1) == 3
    assert all((store.raw_dir / p).exists() for p in idx1["path"])
    static_source.frames["static:ipca"] = frame(
        ("2026-05-01", 0.5), ("2026-06-01", 0.35), ("2026-07-01", 0.4)
    )
    run(store, catalog, static_source, T2)
    idx2 = schemas.to_pandas(store.read("raw_index"))
    second = idx2[idx2["fetched_at"] == pd.Timestamp(T2)].set_index("series_id")
    assert bool(second.loc["static:ipca", "stored"]) is True
    assert bool(second.loc["static:selic", "stored"]) is False
    assert not (store.raw_dir / second.loc["static:selic", "path"]).exists()
    assert len(sorted(store.raw_dir.rglob("*.gz"))) == 4


def test_asof_queries_never_leak(
    store: Store, catalog: Catalog, static_source: StaticSource, leakage_guard
) -> None:
    run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = frame(
        ("2026-05-01", 0.5), ("2026-06-01", 0.35), ("2026-07-01", 0.4)
    )
    run(store, catalog, static_source, T2)
    for asof in (dt.date(2026, 8, 31), D1, D2):
        leakage_guard(store.observations(asof=asof), asof)
    assert store.observations(asof=dt.date(2026, 8, 31)).num_rows == 0


def test_unknown_source_records_errors_without_writing_observations(
    store: Store, catalog: Catalog
) -> None:
    summary = pipeline.update(store, catalog, {}, now=T1, tz="UTC")
    assert summary.status == "failed" and summary.n_errors == 3
    assert store.observations().num_rows == 0
    assert schemas.to_pandas(store.read("runs")).loc[0, "status"] == "failed"


def test_fetch_exception_is_isolated_to_the_series(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    del static_source.frames["static:selic"]  # StaticSource raises KeyError
    s = run(store, catalog, static_source, T1)
    errs = {o.series_id: o.error for o in s.outcomes if o.error}
    assert set(errs) == {"static:selic"} and "KeyError" in errs["static:selic"]
    assert s.status == "partial"
    assert store.observations().num_rows == 4


def test_alias_selection_and_source_filter(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    with pytest.warns(DeprecationWarning):
        s = run(store, catalog, static_source, T1, series_ids=["static:selic_old"])
    assert [o.series_id for o in s.outcomes] == ["static:selic"]
    s2 = pipeline.update(
        store, catalog, {"static": static_source}, now=T2, tz="UTC", source_names=["nope"]
    )
    assert s2.outcomes == [] and s2.status == "ok"


def test_run_date_follows_configured_timezone() -> None:
    late_utc = dt.datetime(2026, 9, 2, 1, 30, tzinfo=dt.UTC)  # still Sept 1 in São Paulo
    assert pipeline.run_date_for(late_utc, "America/Sao_Paulo") == dt.date(2026, 9, 1)
    assert pipeline.run_date_for(late_utc, "UTC") == dt.date(2026, 9, 2)
    rid = pipeline.new_run_id(late_utc)
    assert rid.startswith("20260902T013000Z-") and len(rid) == len("20260902T013000Z-") + 6


def test_values_equal_treats_nan_as_equal_and_uses_tiny_tolerance() -> None:
    a = pd.Series([1.0, float("nan"), 2.0, 3.0])
    b = pd.Series([1.0 + 1e-13, float("nan"), 2.5, None])
    assert list(pipeline.values_equal(a, b)) == [True, True, False, False]
