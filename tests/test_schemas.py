from __future__ import annotations

import datetime as dt

import pandas as pd
import pyarrow as pa
import pytest

from econbase import schemas


def test_every_table_has_a_schema_and_empty_table_matches() -> None:
    for name, schema in schemas.TABLES.items():
        empty = schemas.empty_table(schema)
        assert empty.num_rows == 0
        assert empty.schema.equals(schema), name


def test_ensure_schema_rejects_missing_and_extra_columns() -> None:
    t = pa.table({"series_id": ["a"], "period": [dt.date(2026, 1, 1)]})
    with pytest.raises(schemas.SchemaError, match="missing columns"):
        schemas.ensure_schema(t, schemas.OBSERVATIONS)
    full = schemas.empty_table(schemas.OBSERVATIONS).append_column("extra", pa.array([], pa.int8()))
    with pytest.raises(schemas.SchemaError, match="unexpected columns"):
        schemas.ensure_schema(full, schemas.OBSERVATIONS)


def test_from_pandas_normalizes_dates_timestamps_ints_and_lists() -> None:
    df = pd.DataFrame(
        {
            "series_id": ["x:1"],
            "entity_id": ["BR"],
            "concept_id": [None],
            "source": ["x"],
            "native_id": ["1"],
            "title": ["t"],
            "unit": ["pct"],
            "scale": [1.0],
            "freq": ["M"],
            "seasonal_adj": [False],
            "calendar": [None],
            "source_url": [None],
            "license": ["CC0"],
            "redistributable": [True],
            "aliases": [("x:old",)],
            "method_version": [None],
            "expected_lag_days": [float("nan")],
            "table": ["observations"],
            "domain": ["macro"],
            "first_period": [pd.Timestamp("2020-01-01")],
            "last_period": [None],
            "last_updated": [dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC)],
        }
    )
    t = schemas.from_pandas(df, schemas.SERIES)
    assert t.schema.equals(schemas.SERIES)
    row = t.to_pylist()[0]
    assert row["first_period"] == dt.date(2020, 1, 1)
    assert row["expected_lag_days"] is None
    assert row["aliases"] == ["x:old"]
    assert row["last_updated"] == dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC)


def test_to_pandas_returns_date_objects() -> None:
    t = pa.table(
        {
            "series_id": ["a"],
            "period": [dt.date(2026, 1, 1)],
            "value": [1.0],
            "realtime_start": [dt.date(2026, 2, 1)],
            "realtime_end": [None],
            "observed_at": [dt.datetime(2026, 2, 1, tzinfo=dt.UTC)],
            "run_id": ["r"],
        },
        schema=schemas.OBSERVATIONS,
    )
    df = schemas.to_pandas(t)
    assert isinstance(df.loc[0, "period"], dt.date)
    assert df.loc[0, "realtime_end"] is None or pd.isna(df.loc[0, "realtime_end"])
