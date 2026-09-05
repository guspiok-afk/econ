"""Arrow schemas for every table in the store.

This module is the machine-readable form of ``docs/CONTRACT.md``. Every write into the lake
passes through :func:`ensure_schema`, so a Parquet file can only ever carry exactly these
columns and types. ``SCHEMA_VERSION`` is written into the manifest.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import pandas as pd
import pyarrow as pa

SCHEMA_VERSION = "1.0.0"

FREQUENCIES: tuple[str, ...] = ("D", "B", "W", "M", "Q", "A")
ENTITY_TYPES: tuple[str, ...] = ("country", "instrument", "issuer", "index", "region")
RUN_STATUSES: tuple[str, ...] = ("ok", "partial", "failed")
TRIGGERS: tuple[str, ...] = ("manual", "scheduler", "ci")
AGGREGATIONS: tuple[str, ...] = ("last", "mean", "sum", "eop", "compound")

_TS_UTC = pa.timestamp("us", tz="UTC")

OBSERVATIONS = pa.schema(
    [
        pa.field("series_id", pa.string(), nullable=False),
        pa.field("period", pa.date32(), nullable=False),
        pa.field("value", pa.float64(), nullable=True),
        pa.field("realtime_start", pa.date32(), nullable=False),
        pa.field("realtime_end", pa.date32(), nullable=True),
        pa.field("observed_at", _TS_UTC, nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
    ]
)

SERIES = pa.schema(
    [
        pa.field("series_id", pa.string(), nullable=False),
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("concept_id", pa.string(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
        pa.field("native_id", pa.string(), nullable=False),
        pa.field("title", pa.string(), nullable=False),
        pa.field("unit", pa.string(), nullable=True),
        pa.field("scale", pa.float64(), nullable=True),
        pa.field("freq", pa.string(), nullable=False),
        pa.field("seasonal_adj", pa.bool_(), nullable=True),
        pa.field("calendar", pa.string(), nullable=True),
        pa.field("source_url", pa.string(), nullable=True),
        pa.field("license", pa.string(), nullable=True),
        pa.field("redistributable", pa.bool_(), nullable=True),
        pa.field("aliases", pa.list_(pa.string()), nullable=True),
        pa.field("method_version", pa.string(), nullable=True),
        pa.field("expected_lag_days", pa.int32(), nullable=True),
        pa.field("table", pa.string(), nullable=False),
        pa.field("domain", pa.string(), nullable=False),
        pa.field("first_period", pa.date32(), nullable=True),
        pa.field("last_period", pa.date32(), nullable=True),
        pa.field("last_updated", _TS_UTC, nullable=True),
    ]
)

ENTITIES = pa.schema(
    [
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("entity_type", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("attributes", pa.string(), nullable=True),
    ]
)

RUNS = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("started_at", _TS_UTC, nullable=False),
        pa.field("finished_at", _TS_UTC, nullable=True),
        pa.field("status", pa.string(), nullable=False),
        pa.field("trigger", pa.string(), nullable=False),
        pa.field("package_version", pa.string(), nullable=True),
        pa.field("git_sha", pa.string(), nullable=True),
        pa.field("catalog_hash", pa.string(), nullable=True),
        pa.field("n_series", pa.int32(), nullable=False),
        pa.field("n_errors", pa.int32(), nullable=False),
    ]
)

RUN_SERIES = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("series_id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("rows_fetched", pa.int64(), nullable=False),
        pa.field("rows_new", pa.int64(), nullable=False),
        pa.field("rows_revised", pa.int64(), nullable=False),
        pa.field("rows_closed", pa.int64(), nullable=False),
        pa.field("raw_sha256", pa.string(), nullable=True),
        pa.field("error", pa.string(), nullable=True),
        pa.field("duration_ms", pa.int64(), nullable=False),
    ]
)

RAW_INDEX = pa.schema(
    [
        pa.field("source", pa.string(), nullable=False),
        pa.field("series_id", pa.string(), nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("fetched_at", _TS_UTC, nullable=False),
        pa.field("url", pa.string(), nullable=True),
        pa.field("sha256", pa.string(), nullable=False),
        pa.field("bytes", pa.int64(), nullable=False),
        pa.field("path", pa.string(), nullable=False),
        pa.field("stored", pa.bool_(), nullable=False),
    ]
)

MODEL_RUNS = pa.schema(
    [
        pa.field("model_run_id", pa.string(), nullable=False),
        pa.field("model_id", pa.string(), nullable=False),
        pa.field("model_version", pa.string(), nullable=False),
        pa.field("entity_id", pa.string(), nullable=True),
        pa.field("asof", pa.date32(), nullable=False),
        pa.field("seed", pa.int64(), nullable=False),
        pa.field("vintage_kind", pa.string(), nullable=False),
        pa.field("spec_id", pa.string(), nullable=True),
        # The content of the specification file, so a run stays reproducible when the file
        # is later edited. Without it an edit silently re-labels every earlier run.
        pa.field("spec_hash", pa.string(), nullable=True),
        pa.field("params", pa.string(), nullable=True),  # JSON, so a rerun is reconstructible
        pa.field("git_sha", pa.string(), nullable=True),
        pa.field("package_version", pa.string(), nullable=True),
        pa.field("catalog_hash", pa.string(), nullable=True),
        pa.field("created_at", _TS_UTC, nullable=False),
    ]
)

#: Every table a model returns, melted. Wide storage would need a migration per analysis, and
#: the analyses do not agree on a shape: a coefficient table has names, an impulse response has
#: horizons, a fitted table has periods.
MODEL_OUTPUTS = pa.schema(
    [
        pa.field("model_run_id", pa.string(), nullable=False),
        pa.field("table_name", pa.string(), nullable=False),
        pa.field("row_ix", pa.int32(), nullable=False),
        pa.field("column_name", pa.string(), nullable=False),
        pa.field("value_num", pa.float64(), nullable=True),
        pa.field("value_txt", pa.string(), nullable=True),
    ]
)

TABLES: dict[str, pa.Schema] = {
    "observations": OBSERVATIONS,
    "series": SERIES,
    "entities": ENTITIES,
    "runs": RUNS,
    "run_series": RUN_SERIES,
    "raw_index": RAW_INDEX,
    "model_runs": MODEL_RUNS,
    "model_outputs": MODEL_OUTPUTS,
}

#: Tables whose files are partitioned by a column value in the path (``table/col=value/``).
PARTITIONED: dict[str, str] = {"observations": "source"}


class SchemaError(ValueError):
    """A table does not conform to the contract."""


def empty_table(schema: pa.Schema) -> pa.Table:
    """A zero-row table with exactly ``schema``."""
    return schema.empty_table()


def ensure_schema(table: pa.Table, schema: pa.Schema, name: str = "table") -> pa.Table:
    """Return ``table`` with exactly ``schema`` (column order and types), or raise.

    Missing or extra columns are errors; type differences are resolved by a safe cast.
    """
    have = set(table.column_names)
    want = set(schema.names)
    missing = sorted(want - have)
    extra = sorted(have - want)
    if missing or extra:
        raise SchemaError(f"{name}: missing columns {missing}, unexpected columns {extra}")
    table = table.select(schema.names)
    try:
        return table.cast(schema)
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError) as exc:
        raise SchemaError(f"{name}: cannot cast to contract schema: {exc}") from exc


def _coerce_frame(df: pd.DataFrame, schema: pa.Schema) -> pd.DataFrame:
    """Normalize pandas dtypes so that Arrow inference plus a safe cast succeed."""
    out = pd.DataFrame(index=df.index)
    for field in schema:
        col = (
            df[field.name]
            if field.name in df.columns
            else pd.Series([None] * len(df), index=df.index)
        )
        t = field.type
        if pa.types.is_date(t):
            if pd.api.types.is_datetime64_any_dtype(col):
                col = col.dt.date
            else:
                col = col.map(lambda v: v.date() if isinstance(v, dt.datetime) else v)
            col = col.astype(object).where(col.notna(), None)
        elif pa.types.is_timestamp(t):
            col = pd.to_datetime(col, utc=True)
        elif pa.types.is_integer(t):
            col = pd.array(pd.to_numeric(col, errors="raise"), dtype="Int64")
        elif pa.types.is_floating(t):
            col = pd.to_numeric(col, errors="raise").astype("float64")
        elif pa.types.is_boolean(t):
            col = col.astype(object).where(col.notna(), None)
        elif pa.types.is_list(t):
            col = col.map(
                lambda v: list(v) if isinstance(v, Iterable) and not isinstance(v, str) else v
            )
            col = col.astype(object).where(col.notna(), None)
        elif pa.types.is_string(t):
            col = col.astype(object).where(col.notna(), None)
            col = col.map(lambda v: v if v is None else str(v))
        out[field.name] = col
    return out


def from_pandas(df: pd.DataFrame, schema: pa.Schema, name: str = "table") -> pa.Table:
    """Convert a DataFrame to an Arrow table conforming exactly to ``schema``.

    Missing nullable columns are added as nulls; dtypes are normalized first so that dates,
    UTC timestamps, nullable integers and string lists round-trip without surprises.
    """
    if df is None or len(df) == 0:
        return empty_table(schema)
    coerced = _coerce_frame(df, schema)
    table = pa.Table.from_pandas(coerced, preserve_index=False)
    return ensure_schema(table, schema, name)


def to_pandas(table: pa.Table) -> pd.DataFrame:
    """Arrow to pandas with dates as ``datetime.date`` objects (stable for joins on periods)."""
    return table.to_pandas(date_as_object=True)
