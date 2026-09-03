from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from econbase import schemas
from econbase.store import Store, StoreError


def _obs(series_id: str, *periods: str, run_id: str = "r1") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": series_id,
            "period": [dt.date.fromisoformat(p) for p in periods],
            "value": [float(i) for i in range(len(periods))],
            "realtime_start": dt.date(2026, 9, 1),
            "realtime_end": None,
            "observed_at": dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC),
            "run_id": run_id,
        }
    )


def test_empty_store_reads_typed_empty_tables(store: Store) -> None:
    for name, schema in schemas.TABLES.items():
        t = store.read(name)
        assert t.num_rows == 0
        assert t.schema.equals(schema), name
    assert store.observations().num_rows == 0
    assert store.manifest().run_id is None
    assert store.query("SELECT count(*) AS n FROM obs_latest").to_pylist() == [{"n": 0}]


def test_transaction_replace_partition_and_manifest_swap(store: Store) -> None:
    with store.transaction(run_id="r1", catalog_hash="h1") as tx:
        tx.replace_partition(
            "observations",
            "a",
            schemas.from_pandas(_obs("a:1", "2026-01-01", "2026-02-01"), schemas.OBSERVATIONS),
        )
        tx.replace_partition(
            "observations",
            "b",
            schemas.from_pandas(_obs("b:1", "2026-01-01"), schemas.OBSERVATIONS),
        )
    m = store.manifest()
    assert (
        m.run_id == "r1" and m.catalog_hash == "h1" and m.schema_version == schemas.SCHEMA_VERSION
    )
    assert sorted(m.files["observations"]) == [
        "observations/source=a/part-r1.parquet",
        "observations/source=b/part-r1.parquet",
    ]
    assert store.read("observations").num_rows == 3
    assert store.read("observations", partition="source=a").num_rows == 2
    assert not store.staging_dir.joinpath("r1").exists()

    # replacing one partition leaves the other untouched and orphans the old file
    with store.transaction(run_id="r2") as tx:
        tx.replace_partition(
            "observations",
            "a",
            schemas.from_pandas(_obs("a:1", "2026-01-01", run_id="r2"), schemas.OBSERVATIONS),
        )
    m2 = store.manifest()
    assert m2.catalog_hash == "h1"  # carried forward when not given
    assert sorted(m2.files["observations"]) == [
        "observations/source=a/part-r2.parquet",
        "observations/source=b/part-r1.parquet",
    ]
    old = store.lake_dir / "observations/source=a/part-r1.parquet"
    assert old.exists()  # still on disk until gc
    assert store.read("observations").num_rows == 2


def test_gc_removes_only_old_orphans(store: Store) -> None:
    with store.transaction(run_id="r1") as tx:
        tx.replace_table(
            "entities",
            schemas.from_pandas(
                pd.DataFrame(
                    [
                        {
                            "entity_id": "BR",
                            "entity_type": "country",
                            "name": "Brazil",
                            "attributes": "{}",
                        }
                    ]
                ),
                schemas.ENTITIES,
            ),
        )
    with store.transaction(run_id="r2") as tx:
        tx.replace_table(
            "entities",
            schemas.from_pandas(
                pd.DataFrame(
                    [
                        {
                            "entity_id": "US",
                            "entity_type": "country",
                            "name": "US",
                            "attributes": "{}",
                        }
                    ]
                ),
                schemas.ENTITIES,
            ),
        )
    orphan = store.lake_dir / "entities/part-r1.parquet"
    live = store.lake_dir / "entities/part-r2.parquet"
    assert orphan.exists() and live.exists()
    # fresh orphan is kept
    assert store.gc(older_than_days=7) == []
    # age the orphan and the live file; only the orphan goes
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(days=30)).timestamp()
    os.utime(orphan, (old, old))
    os.utime(live, (old, old))
    deleted = store.gc(older_than_days=7)
    assert deleted == [orphan]
    assert live.exists() and not orphan.exists()
    assert store.read("entities").column("entity_id").to_pylist() == ["US"]


def test_rollback_on_exception_leaves_manifest_untouched(store: Store) -> None:
    with pytest.raises(RuntimeError, match="boom"), store.transaction(run_id="r1") as tx:
        tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
        raise RuntimeError("boom")
    assert store.manifest().run_id is None
    assert not (store.staging_dir / "r1").exists()
    assert list(store.lake_dir.rglob("*.parquet")) == []


def test_append_table_accumulates(store: Store) -> None:
    def runs(run_id: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "started_at": dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
                    "finished_at": None,
                    "status": "ok",
                    "trigger": "manual",
                    "package_version": None,
                    "git_sha": None,
                    "catalog_hash": None,
                    "n_series": 0,
                    "n_errors": 0,
                }
            ]
        )

    with store.transaction(run_id="r1") as tx:
        tx.append_table("runs", schemas.from_pandas(runs("r1"), schemas.RUNS))
    with store.transaction(run_id="r2") as tx:
        tx.append_table("runs", schemas.from_pandas(runs("r2"), schemas.RUNS))
    assert store.read("runs").column("run_id").to_pylist() == ["r1", "r2"]
    assert len(store.manifest().files["runs"]) == 1


def test_rebuild_db_creates_read_only_queryable_views(store: Store) -> None:
    with store.transaction(run_id="r1") as tx:
        tx.replace_partition(
            "observations",
            "a",
            schemas.from_pandas(_obs("a:1", "2026-01-01"), schemas.OBSERVATIONS),
        )
    path = store.rebuild_db()
    assert path.exists()
    con = duckdb.connect(str(path), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM obs_latest").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM obs_asof(DATE '2026-09-01')").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM obs_asof(DATE '2026-08-31')").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    finally:
        con.close()
    # rebuilding again replaces the file
    assert store.rebuild_db() == path


def test_unknown_table_and_partition_misuse_raise(store: Store) -> None:
    with pytest.raises(StoreError):
        store.read("nope")
    with store.transaction(run_id="r1") as tx:
        with pytest.raises(StoreError):
            tx.replace_partition("entities", "x", schemas.empty_table(schemas.ENTITIES))
        with pytest.raises(StoreError):
            tx.replace_table("observations", schemas.empty_table(schemas.OBSERVATIONS))
        tx.rollback()
        tx.committed = True  # prevent auto-commit of an empty tx in __exit__


def test_manifest_is_atomic_json(store: Store, tmp_path: Path) -> None:
    with store.transaction(run_id="r1") as tx:
        tx.replace_table("entities", schemas.empty_table(schemas.ENTITIES))
    assert not list(store.lake_dir.glob("manifest.json.tmp-*"))
    (store.lake_dir / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(StoreError, match="corrupt manifest"):
        store.manifest()
