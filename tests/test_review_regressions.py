"""Regression tests for the defects found by the WP-01 independent review.

Each test names the finding it locks down. They exist so a future refactor cannot quietly
reintroduce a corruption path that was already paid for once.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pandas as pd
import pytest
from tests.conftest import frame, vframe

from econbase import pipeline, schemas
from econbase.catalog import Catalog
from econbase.sources.base import RawResponse, Source, SourceError, StaticSource
from econbase.store import Store, StoreError, WriterLock

T1 = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
T2 = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)
T3 = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.UTC)
D1, D2, D3 = T1.date(), T2.date(), T3.date()


def _run(store, catalog, src, when, **kw) -> pipeline.RunSummary:
    return pipeline.update(store, catalog, {"static": src}, now=when, tz="UTC", **kw)


def _history(store: Store, series_id: str) -> pd.DataFrame:
    return schemas.to_pandas(store.observations([series_id], include_history=True))


# --------------------------------------------------------------- C1: covers_from both ways
def test_covers_from_ignores_incoming_periods_before_the_window(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    """A windowed fetch that still returns an older period must not open a second row."""
    _run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = frame(("2026-06-01", 0.35), ("2026-07-01", 0.4))
    static_source.covers_from["static:ipca"] = dt.date(2026, 6, 15)  # after the 06-01 period
    s2 = _run(store, catalog, static_source, T2, series_ids=["static:ipca"])

    assert s2.outcomes[0].error is None
    obs = schemas.to_pandas(store.observations(["static:ipca"]))
    assert len(obs) == 3, "one open row per period"
    june = obs[obs["period"] == dt.date(2026, 6, 1)]
    assert len(june) == 1 and float(june["value"].iloc[0]) == 0.3, "old value untouched"
    hist = _history(store, "static:ipca")
    assert not hist.duplicated(["series_id", "period", "realtime_start"]).any()


def test_covers_from_after_every_returned_period_is_refused(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    _run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = frame(("2026-05-01", 0.9))
    static_source.covers_from["static:ipca"] = dt.date(2026, 7, 1)
    s2 = _run(store, catalog, static_source, T2, series_ids=["static:ipca"])
    assert s2.outcomes[0].error and "before covers_from" in s2.outcomes[0].error
    assert store.observations(["static:ipca"]).num_rows == 3


# ------------------------------------------------- C2: bad period types stay per-series
def test_non_date_periods_fail_one_series_not_the_run(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    _run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = pd.DataFrame(
        {"period": ["2026-08-01"], "value": [0.5]}  # ISO strings, not dates
    )
    s2 = _run(store, catalog, static_source, T2)

    errs = {o.series_id: o.error for o in s2.outcomes if o.error}
    assert set(errs) == {"static:ipca"}
    assert "expected datetime.date" in errs["static:ipca"]
    assert s2.status == "partial"
    runs = schemas.to_pandas(store.read("runs"))
    assert len(runs) == 2 and runs.iloc[-1]["status"] == "partial"
    assert store.observations(["static:ipca"]).num_rows == 3  # untouched
    assert store.observations(["static:selic"]).num_rows == 2  # sibling still updated


# ---------------------------------------------------- C3: vintage interval validation
class _Vintaged(Source):
    name = "static"

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        super().__init__()
        self.frames = frames

    def fetch_raw(self, spec, since=None) -> RawResponse:
        return RawResponse(body=b"{}", url="v://x")

    def parse(self, raw: RawResponse, spec) -> pd.DataFrame:
        return self.frames[spec.series_id].copy()


def test_vintaged_frame_without_realtime_end_is_refused(store: Store, catalog: Catalog) -> None:
    src = _Vintaged(
        {
            "static:gdp_us": pd.DataFrame(
                {
                    "period": [dt.date(2026, 1, 1)],
                    "value": [100.0],
                    "realtime_start": [dt.date(2026, 4, 30)],
                }
            )
        }
    )
    s = _run(store, catalog, src, T1, series_ids=["static:gdp_us"])
    assert s.outcomes[0].error and "realtime_end" in s.outcomes[0].error
    assert store.observations(["static:gdp_us"]).num_rows == 0


def test_zero_length_vintage_interval_is_refused(store: Store, catalog: Catalog) -> None:
    src = _Vintaged({"static:gdp_us": vframe(("2026-01-01", 100.0, "2026-04-30", "2026-04-30"))})
    s = _run(store, catalog, src, T1, series_ids=["static:gdp_us"])
    assert s.outcomes[0].error and "end at or before they start" in s.outcomes[0].error


def test_overlapping_vintages_are_refused(store: Store, catalog: Catalog) -> None:
    src = _Vintaged({"static:gdp_us": vframe(("2026-01-01", 100.0, "2026-04-30", None))})
    _run(store, catalog, src, T1, series_ids=["static:gdp_us"])
    # a second open interval for the same period would leave two current values
    src.frames["static:gdp_us"] = vframe(("2026-01-01", 101.0, "2026-05-29", None))
    s2 = _run(store, catalog, src, T2, series_ids=["static:gdp_us"])
    assert s2.outcomes[0].error and (
        "more than one open row" in s2.outcomes[0].error
        or "open interval from" in s2.outcomes[0].error
    )
    assert store.observations(["static:gdp_us"]).num_rows == 1


# ------------------------------------------------------------- C4: unusable frame
def test_frame_whose_periods_are_all_missing_does_not_close_anything(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    _run(store, catalog, static_source, T1)
    static_source.frames["static:ipca"] = pd.DataFrame(
        {"period": [None, pd.NaT], "value": [1.0, 2.0]}
    )
    s2 = _run(store, catalog, static_source, T2, series_ids=["static:ipca"])
    assert s2.outcomes[0].error and "no usable rows" in s2.outcomes[0].error
    obs = schemas.to_pandas(store.observations(["static:ipca"]))
    assert len(obs) == 3 and obs["realtime_end"].isna().all()


def test_a_fetch_that_would_close_every_period_is_refused(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    """Even below the absolute threshold: losing the whole series is never a revision."""
    static_source.frames["static:ipca"] = frame(("2026-05-01", 0.5), ("2026-06-01", 0.3))
    _run(store, catalog, static_source, T1, series_ids=["static:ipca"])
    static_source.frames["static:ipca"] = frame(("2030-01-01", 9.9))  # disjoint periods
    s2 = _run(store, catalog, static_source, T2, series_ids=["static:ipca"])
    assert s2.outcomes[0].error and "refusing to close" in s2.outcomes[0].error
    assert store.observations(["static:ipca"]).num_rows == 2


# ------------------------------------------- C5: backdated run vs already-closed rows
def test_backdated_run_after_a_close_is_refused(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    static_source.frames["static:ipca"] = frame(("2026-05-01", 0.5), ("2026-06-01", 0.3))
    _run(store, catalog, static_source, T1, series_ids=["static:ipca"])
    static_source.frames["static:ipca"] = frame(("2026-05-01", 0.5), ("2026-06-01", 0.31))
    _run(store, catalog, static_source, T3, series_ids=["static:ipca"])  # closes at D3
    static_source.frames["static:ipca"] = frame(("2026-05-01", 0.5), ("2026-06-01", 0.32))
    s = _run(store, catalog, static_source, T2, series_ids=["static:ipca"])  # clock went back
    assert s.outcomes[0].error and "earlier than an existing vintage" in s.outcomes[0].error
    hist = _history(store, "static:ipca")
    assert len(hist) == 3  # 05-01 open, 06-01 closed + reopened


# ------------------------------------------------- C6/C10: first release with a NULL value
def test_first_release_keeps_a_missing_first_value(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    static_source.frames["static:ipca"] = pd.DataFrame(
        {"period": [dt.date(2026, 5, 1)], "value": [float("nan")]}
    )
    _run(store, catalog, static_source, T1, series_ids=["static:ipca"])
    static_source.frames["static:ipca"] = frame(("2026-05-01", 0.42))
    _run(store, catalog, static_source, T2, series_ids=["static:ipca"])

    fr = schemas.to_pandas(store.first_release(["static:ipca"]))
    assert len(fr) == 1
    row = fr.iloc[0]
    assert row["realtime_start"] == D1
    assert pd.isna(row["value"]), "the first release was missing; it must not borrow a revision"
    assert row["realtime_end"] == D2, "first_release returns the whole row"
    assert store.first_release(["static:ipca"]).schema.equals(schemas.OBSERVATIONS)


# ------------------------------------------------------------ C7/C14: writer lock
def test_second_writer_is_refused_while_a_transaction_is_open(store: Store) -> None:
    with store.transaction(run_id="r1") as tx:
        tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
        assert store.lock_path.exists()
        with pytest.raises(StoreError, match="another writer holds"):
            store.transaction(run_id="r2")
    assert not store.lock_path.exists(), "the lock is released on commit"


def test_lock_is_released_on_rollback(store: Store) -> None:
    with pytest.raises(RuntimeError), store.transaction(run_id="r1"):
        raise RuntimeError("boom")
    assert not store.lock_path.exists()
    with store.transaction(run_id="r2") as tx:  # a new writer can proceed
        tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))


def test_stale_lock_is_taken_over(store: Store) -> None:
    store.lock_path.write_text(json.dumps({"pid": 1, "run_id": "crashed"}), encoding="utf-8")
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=12)).timestamp()
    os.utime(store.lock_path, (old, old))
    with store.transaction(run_id="r1") as tx:  # must not deadlock forever
        tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
    assert store.manifest().run_id == "r1"


def test_commit_is_refused_when_the_manifest_moved(store: Store) -> None:
    tx = store.transaction(run_id="r1")
    tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
    # simulate another writer that bypassed the lock and committed meanwhile
    m = store.manifest()
    m.run_id = "other"
    m.dump(store.manifest_path)
    with pytest.raises(StoreError, match="manifest changed"):
        tx.commit()
    tx.rollback()


# ------------------------------------------------------- C8/C16: durable manifest
def test_manifest_keeps_a_previous_copy_and_reports_recovery(store: Store) -> None:
    for run in ("r1", "r2"):
        with store.transaction(run_id=run) as tx:
            tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
    prev = store.manifest_path.with_name("manifest.json.prev")
    assert prev.exists() and json.loads(prev.read_text(encoding="utf-8"))["run_id"] == "r1"
    store.manifest_path.write_text("{truncated", encoding="utf-8")
    with pytest.raises(StoreError, match="Recover the previous run"):
        store.manifest()


# --------------------------------------------------- C9: archive before parsing
class _ParseFails(Source):
    name = "static"

    def fetch_raw(self, spec, since=None) -> RawResponse:
        return RawResponse(body=b'{"payload": "recorded"}', url="https://x/y")

    def parse(self, raw: RawResponse, spec) -> pd.DataFrame:
        raise ValueError("column layout changed")


def test_raw_body_is_archived_even_when_parsing_fails(store: Store, catalog: Catalog) -> None:
    s = _run(store, catalog, _ParseFails(), T1, series_ids=["static:ipca"])
    assert s.outcomes[0].error and "column layout changed" in s.outcomes[0].error
    idx = schemas.to_pandas(store.read("raw_index"))
    assert len(idx) == 1 and idx.loc[0, "stored"]
    archived = store.raw_dir / idx.loc[0, "path"]
    assert archived.exists()
    import gzip

    assert gzip.decompress(archived.read_bytes()) == b'{"payload": "recorded"}'


# ------------------------------------------- C11: open-ended sentinel becomes NULL
def test_far_future_realtime_end_is_stored_as_open(store: Store, catalog: Catalog) -> None:
    src = _Vintaged({"static:gdp_us": vframe(("2026-01-01", 100.0, "2026-04-30", "9999-12-31"))})
    _run(store, catalog, src, T1, series_ids=["static:gdp_us"])
    latest = schemas.to_pandas(store.observations(["static:gdp_us"]))
    assert len(latest) == 1, "the sentinel must not hide the row from obs_latest"
    assert latest.loc[0, "realtime_end"] is None
    report = pipeline.check(store, catalog, today=dt.date(2026, 5, 1)).set_index("series_id")
    assert report.loc["static:gdp_us", "last_period"] == dt.date(2026, 1, 1)


# ------------------------------------------------------- C12/C15: trigger validation
def test_invalid_trigger_is_rejected(store: Store, catalog: Catalog) -> None:
    with pytest.raises(ValueError, match="trigger must be one of"):
        pipeline.update(store, catalog, {}, now=T1, tz="UTC", trigger="cron")


def test_cli_rejects_an_invalid_trigger(catalog_root, data_dir) -> None:
    from typer.testing import CliRunner

    from econbase.cli import app

    result = CliRunner().invoke(
        app, ["update", "--catalog", str(catalog_root), "--trigger", "cron"]
    )
    assert result.exit_code == 2


# ------------------------------------------------------------------ misc contract
def test_static_source_raises_a_source_error_for_an_unknown_series(
    store: Store, catalog: Catalog, static_source: StaticSource
) -> None:
    del static_source.frames["static:selic"]
    with pytest.raises(SourceError):
        static_source.fetch_raw(catalog.get("static:selic"))


def test_writer_lock_context_manager_round_trip(store: Store) -> None:
    lock = WriterLock(store.lock_path, run_id="x")
    with lock:
        assert store.lock_path.exists()
    assert not store.lock_path.exists()


# ------------------------------------------- unjudged edge cases found during the fix pass
def test_first_windowed_fetch_of_a_new_series_works(store: Store, catalog: Catalog) -> None:
    """A connector that windows from day one must not crash on the empty history."""
    src = StaticSource(
        {"static:ipca": frame(("2026-06-01", 0.3))},
        covers_from={"static:ipca": dt.date(2026, 1, 1)},
    )
    s = _run(store, catalog, src, T1, series_ids=["static:ipca"])
    assert s.outcomes[0].error is None and s.outcomes[0].rows_new == 1
    assert store.observations(["static:ipca"]).num_rows == 1


def test_covers_from_accepts_a_pandas_timestamp(store: Store, catalog: Catalog) -> None:
    src = StaticSource(
        {"static:ipca": frame(("2026-06-01", 0.3))},
        covers_from={"static:ipca": pd.Timestamp("2026-01-01")},
    )
    s = _run(store, catalog, src, T1, series_ids=["static:ipca"])
    assert s.outcomes[0].error is None, s.outcomes[0].error


def test_a_bare_string_series_id_is_an_error_not_an_empty_result(store: Store) -> None:
    with pytest.raises(StoreError, match="must be a collection"):
        store.observations("static:ipca")
    with pytest.raises(StoreError, match="must be a collection"):
        store.first_release("static:ipca")


def test_gc_ages_orphans_from_the_moment_they_became_orphans(store: Store) -> None:
    with store.transaction(run_id="r1") as tx:
        tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
    old_file = store.lake_dir / "entities/part-r1.parquet"
    stale = (dt.datetime.now(dt.UTC) - dt.timedelta(days=30)).timestamp()
    os.utime(old_file, (stale, stale))  # written long ago but still live
    with store.transaction(run_id="r2") as tx:  # only now does it become garbage
        tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
    assert store.gc(older_than_days=7) == [], "a fresh orphan must survive its grace period"
    assert old_file.exists()


def test_env_file_is_found_from_any_working_directory() -> None:
    from econbase.settings import REPO_ENV

    assert REPO_ENV.name == ".env"
    assert (REPO_ENV.parent / "pyproject.toml").exists(), "REPO_ENV must point at the repo root"
