"""Persisting what a model produced, with the provenance that makes it arguable.

A number without its vintage and its code is not a result, it is a rumour. Every saved run
carries the ``asof`` the panel was built at, the seed, the parameters, the git commit and the
catalog hash, so the question "where did this come from" has an answer that does not depend on
anyone's memory.

Outputs are stored melted — one row per (table, row, column) — because the analyses do not agree
on a shape. A coefficient table is indexed by name, an impulse response by horizon and a fitted
table by period, and a wide store would need a migration for every analysis added. Reading a
table back pivots it, and the round trip is covered by a test.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from econbase import schemas
from econbase.pipeline import new_run_id
from econbase.store import Store

__all__ = ["ResultsError", "list_runs", "load_result", "save_result"]

_NUMERIC = "value_num"
_TEXT = "value_txt"


class ResultsError(RuntimeError):
    """A result could not be stored or read back."""


def git_sha(repo: Path | None = None) -> str | None:
    """The commit the code came from, or ``None`` outside a checkout."""
    root = repo or Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=root,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _spec_params(spec: Any | None) -> dict[str, Any]:
    """The resolved specification, so a run reconstructs even if its file later changes."""
    if spec is None:
        return {}
    as_params = getattr(spec, "as_params", None)
    return as_params() if callable(as_params) else {}


def _melt(table_name: str, frame: pd.DataFrame, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_ix, (_, row) in enumerate(frame.iterrows()):
        for column in frame.columns:
            value = row[column]
            num: float | None = None
            txt: str | None = None
            if value is None or (isinstance(value, float) and pd.isna(value)):
                pass
            elif isinstance(value, (bool,)):
                txt = "true" if value else "false"
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                num = float(value)
            elif isinstance(value, (dt.date, dt.datetime, pd.Timestamp)):
                txt = pd.Timestamp(value).date().isoformat()
            elif pd.isna(value):
                pass
            else:
                txt = str(value)
            rows.append(
                {
                    "model_run_id": run_id,
                    "table_name": table_name,
                    "row_ix": row_ix,
                    "column_name": str(column),
                    _NUMERIC: num,
                    _TEXT: txt,
                }
            )
    return rows


def save_result(
    store: Store,
    result: Any,
    *,
    model_id: str,
    model_version: str,
    asof: dt.date,
    seed: int = 0,
    entity_id: str | None = None,
    vintage_kind: str = "latest",
    spec: Any | None = None,
    params: dict[str, Any] | None = None,
    catalog_hash: str | None = None,
    package_version: str | None = None,
    now: dt.datetime | None = None,
) -> str:
    """Write one model run and its tables; returns the run id."""
    tables = result.tables()
    if not tables:
        raise ResultsError(f"{model_id} returned no tables; there is nothing to store")
    stamp = now or dt.datetime.now(dt.UTC)
    run_id = new_run_id(stamp)

    rows: list[dict[str, Any]] = []
    for name, frame in tables.items():
        if not isinstance(frame, pd.DataFrame):
            raise ResultsError(f"table {name!r} of {model_id} is not a DataFrame")
        rows.extend(_melt(name, frame.reset_index(drop=True), run_id))

    run_row = pd.DataFrame(
        [
            {
                "model_run_id": run_id,
                "model_id": model_id,
                "model_version": model_version,
                "entity_id": entity_id,
                "asof": asof,
                "seed": int(seed),
                "vintage_kind": vintage_kind,
                "spec_id": getattr(spec, "spec_id", None),
                "spec_hash": getattr(spec, "spec_hash", None),
                "params": json.dumps(
                    params if params is not None else _spec_params(spec),
                    sort_keys=True,
                    default=str,
                ),
                "git_sha": git_sha(),
                "package_version": package_version,
                "catalog_hash": catalog_hash,
                "created_at": stamp,
            }
        ]
    )

    with store.transaction(run_id=run_id, catalog_hash=catalog_hash) as tx:
        tx.append_table("model_runs", schemas.from_pandas(run_row, schemas.MODEL_RUNS))
        tx.append_table(
            "model_outputs", schemas.from_pandas(pd.DataFrame(rows), schemas.MODEL_OUTPUTS)
        )
    return run_id


def _unmelt(frame: pd.DataFrame) -> pd.DataFrame:
    """Rebuild one table from its melted rows, numbers as numbers."""
    out: dict[str, list[Any]] = {}
    width = frame["row_ix"].max() + 1 if len(frame) else 0
    for column in frame["column_name"].drop_duplicates():
        sel = frame[frame["column_name"] == column].set_index("row_ix")
        values: list[Any] = []
        for ix in range(int(width)):
            if ix not in sel.index:
                values.append(None)
                continue
            row = sel.loc[ix]
            num, txt = row[_NUMERIC], row[_TEXT]
            values.append(txt if (num is None or pd.isna(num)) else float(num))
        out[str(column)] = values
    return pd.DataFrame(out)


def load_result(store: Store, model_run_id: str) -> dict[str, pd.DataFrame]:
    """Every table of one stored run, in the shape the model returned."""
    outputs = schemas.to_pandas(store.read("model_outputs"))
    mine = outputs[outputs["model_run_id"] == model_run_id]
    if mine.empty:
        raise ResultsError(f"no stored run {model_run_id!r}")
    return {
        str(name): _unmelt(group.sort_values("row_ix"))
        for name, group in mine.groupby("table_name", sort=True)
    }


def list_runs(store: Store, *, model_id: str | None = None) -> pd.DataFrame:
    """The stored runs, newest first, with the provenance of each."""
    runs = schemas.to_pandas(store.read("model_runs"))
    if model_id is not None:
        runs = runs[runs["model_id"] == model_id]
    if runs.empty:
        return runs
    return runs.sort_values("created_at", ascending=False).reset_index(drop=True)


def _arrow(frame: pd.DataFrame, schema: pa.Schema) -> pa.Table:  # pragma: no cover - thin alias
    return schemas.from_pandas(frame, schema)
