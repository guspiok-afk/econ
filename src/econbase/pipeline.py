"""The update pipeline: fetch -> archive raw -> bitemporal diff -> commit; plus the freshness check.

Vintage semantics (ADR-0002): for sources without native vintages, :func:`apply_snapshot`
compares the incoming picture with the currently open rows and closes/opens intervals with
``realtime_start = run date``. For vintaged sources, :func:`apply_vintages` upserts the
intervals the source publishes.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import logging
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from time import perf_counter
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa

from econbase import schemas
from econbase.catalog import Catalog, SeriesSpec, path_safe
from econbase.settings import DEFAULT_TZ
from econbase.sources.base import FetchResult, Source
from econbase.store import Store

log = logging.getLogger(__name__)

OBS_COLS: list[str] = list(schemas.OBSERVATIONS.names)
VALUE_ATOL = 1e-12
#: A full-history fetch may close at most this many open periods (absolute and as a fraction
#: of the open periods) before the pipeline refuses, to survive truncated API responses.
MAX_VANISH_ABS = 10
MAX_VANISH_FRACTION = 0.5


# ---------------------------------------------------------------------------- run identity
def new_run_id(now: dt.datetime) -> str:
    """Sortable run id: ``YYYYmmddTHHMMSSZ-<6 hex>`` in UTC."""
    return f"{now.astimezone(dt.UTC):%Y%m%dT%H%M%S}Z-{secrets.token_hex(3)}"


def run_date_for(now: dt.datetime, tz: str = DEFAULT_TZ) -> dt.date:
    """Calendar date a fetch instant maps to for ``realtime_start`` (see CONTRACT.md)."""
    return now.astimezone(ZoneInfo(tz)).date()


# ---------------------------------------------------------------------------- helpers
def values_equal(a: pd.Series, b: pd.Series) -> np.ndarray:
    """Element-wise equality with NaN == NaN and a tiny absolute tolerance."""
    x = pd.to_numeric(a, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    y = pd.to_numeric(b, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    both_nan = np.isnan(x) & np.isnan(y)
    return both_nan | np.isclose(x, y, rtol=0.0, atol=VALUE_ATOL, equal_nan=False)


def _to_dates(s: pd.Series) -> pd.Series:
    """Any date-like column to python ``date`` objects (object dtype), NaT -> None."""
    if pd.api.types.is_datetime64_any_dtype(s):
        out = s.dt.date
    else:
        out = s.map(lambda v: v.date() if isinstance(v, dt.datetime) else v)
    out = out.astype(object)
    return out.where(out.notna(), None)


def _normalize_incoming(frame: pd.DataFrame, *, vintaged: bool) -> pd.DataFrame:
    cols = ["period", "value"] + (["realtime_start", "realtime_end"] if vintaged else [])
    missing = [c for c in ("period", "value") if c not in frame.columns]
    if missing:
        raise ValueError(f"incoming frame lacks columns {missing}")
    if vintaged and "realtime_end" not in frame.columns:
        frame = frame.assign(realtime_end=None)
    inc = frame[cols].copy()
    inc["period"] = _to_dates(inc["period"])
    inc = inc[inc["period"].notna()]
    # fail loudly on non-numeric values: connectors own the parsing, the store never guesses
    inc["value"] = pd.to_numeric(inc["value"], errors="raise").astype("float64")
    if vintaged:
        inc["realtime_start"] = _to_dates(inc["realtime_start"])
        inc = inc[inc["realtime_start"].notna()]
        inc["realtime_end"] = _to_dates(inc["realtime_end"])
        inc = inc.drop_duplicates(["period", "realtime_start"], keep="last")
        inc = inc.sort_values(["period", "realtime_start"])
    else:
        inc = inc.drop_duplicates("period", keep="last").sort_values("period")
    return inc.reset_index(drop=True)


def _empty_obs() -> pd.DataFrame:
    return schemas.to_pandas(schemas.empty_table(schemas.OBSERVATIONS))


def _coerce_obs_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Make a partition frame safe for the diff logic (date objects, float values)."""
    if df is None or len(df) == 0:
        return _empty_obs()
    out = df.copy()
    for c in ("period", "realtime_start", "realtime_end"):
        out[c] = _to_dates(out[c])
    out["value"] = pd.to_numeric(out["value"], errors="coerce").astype("float64")
    return out[OBS_COLS].reset_index(drop=True)


# ---------------------------------------------------------------------------- diff logic
@dataclass(slots=True)
class DiffCounts:
    rows_fetched: int = 0
    rows_new: int = 0
    rows_revised: int = 0
    rows_closed: int = 0


def apply_snapshot(
    current: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    series_id: str,
    run_date: dt.date,
    observed_at: dt.datetime,
    run_id: str,
    covers_from: dt.date | None = None,
) -> tuple[pd.DataFrame, DiffCounts]:
    """Apply a non-vintaged snapshot of ``series_id`` to the partition frame ``current``.

    Rows of other series pass through untouched. Within the covered window, a period whose
    value changed is closed and re-opened with today's date; a period the source no longer
    publishes is closed; a period opened today and changed again today is replaced in place
    so ``(series_id, period, realtime_start)`` stays unique.
    """
    current = _coerce_obs_frame(current)
    inc = _normalize_incoming(incoming, vintaged=False)
    mine = current["series_id"] == series_id
    others = current[~mine]
    cur = current[mine]
    is_open = cur["realtime_end"].isna()
    closed_rows = cur[~is_open]
    open_rows = cur[is_open]

    if covers_from is not None:
        in_window = open_rows["period"].map(lambda p: p >= covers_from)
        untouched = open_rows[~in_window]
        consider = open_rows[in_window]
    else:
        untouched = open_rows.iloc[0:0]
        consider = open_rows

    merged = consider[["period", "value"]].merge(
        inc, on="period", how="outer", suffixes=("_cur", "_new"), indicator=True
    )
    both = merged["_merge"] == "both"
    same = pd.Series(values_equal(merged["value_cur"], merged["value_new"]), index=merged.index)
    unchanged = set(merged.loc[both & same, "period"])
    changed = set(merged.loc[both & ~same, "period"])
    vanished = set(merged.loc[merged["_merge"] == "left_only", "period"])
    new = set(merged.loc[merged["_merge"] == "right_only", "period"])

    if len(consider) and consider["realtime_start"].map(lambda d: d > run_date).any():
        raise ValueError(
            f"{series_id}: run date {run_date} is earlier than an existing vintage; "
            "refusing to write inverted intervals (clock or run-order problem)"
        )
    if len(vanished) > max(MAX_VANISH_ABS, MAX_VANISH_FRACTION * len(consider)):
        raise ValueError(
            f"{series_id}: source dropped {len(vanished)} of {len(consider)} open periods; "
            "refusing to close them (truncated response? set FetchResult.covers_from)"
        )

    keep_open = consider[consider["period"].isin(unchanged)]
    to_close = consider[consider["period"].isin(changed | vanished)].copy()
    opened_today = to_close["realtime_start"].map(lambda d: d == run_date)
    to_close = to_close[~opened_today]  # same-day revisions collapse: drop instead of closing
    to_close["realtime_end"] = run_date

    insert_periods = sorted(changed | new)
    if insert_periods:
        values = inc.set_index("period").loc[insert_periods, "value"].to_numpy()
        inserts = pd.DataFrame(
            {
                "series_id": series_id,
                "period": insert_periods,
                "value": values,
                "realtime_start": run_date,
                "realtime_end": None,
                "observed_at": observed_at,
                "run_id": run_id,
            }
        )
    else:
        inserts = _empty_obs()

    parts = [p for p in (others, closed_rows, untouched, keep_open, to_close, inserts) if len(p)]
    result = pd.concat(parts, ignore_index=True)[OBS_COLS] if parts else _empty_obs()
    counts = DiffCounts(
        rows_fetched=len(inc),
        rows_new=len(new),
        rows_revised=len(changed),
        rows_closed=len(changed) + len(vanished),
    )
    return result, counts


def apply_vintages(
    current: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    series_id: str,
    observed_at: dt.datetime,
    run_id: str,
) -> tuple[pd.DataFrame, DiffCounts]:
    """Upsert vintaged rows (``period, value, realtime_start[, realtime_end]``) for ``series_id``.

    Keys present in both keep their identity; ``realtime_end`` and ``value`` take the incoming
    value when it differs (the source is the authority on its own vintages). Keys only in the
    store are kept as they are. Rows that change carry the current ``observed_at``/``run_id``.
    """
    current = _coerce_obs_frame(current)
    inc = _normalize_incoming(incoming, vintaged=True)
    mine = current["series_id"] == series_id
    others = current[~mine]
    cur = current[mine]

    key = ["period", "realtime_start"]
    merged = cur.merge(inc, on=key, how="outer", suffixes=("_cur", "_new"), indicator=True)
    both = merged["_merge"] == "both"
    new = merged["_merge"] == "right_only"
    take_new = both | new

    end_cur = merged["realtime_end_cur"]
    end_new = merged["realtime_end_new"]
    same_end = (end_cur.isna() & end_new.isna()) | (
        end_cur.notna() & end_new.notna() & (end_cur == end_new)
    )
    value_changed = ~pd.Series(
        values_equal(merged["value_cur"], merged["value_new"]), index=merged.index
    )
    revised = both & (value_changed | ~same_end)
    touched = revised | new
    closed_now = both & end_cur.isna() & end_new.notna()

    rows = pd.DataFrame(
        {
            "series_id": series_id,
            "period": merged["period"].to_numpy(dtype=object),
            "value": np.where(take_new, merged["value_new"], merged["value_cur"]),
            "realtime_start": merged["realtime_start"].to_numpy(dtype=object),
            "realtime_end": [
                n if t else c for t, n, c in zip(take_new, end_new, end_cur, strict=True)
            ],
            "observed_at": [
                observed_at if t else c for t, c in zip(touched, merged["observed_at"], strict=True)
            ],
            "run_id": [run_id if t else c for t, c in zip(touched, merged["run_id"], strict=True)],
        }
    )
    rows["realtime_end"] = _to_dates(rows["realtime_end"])
    rows["observed_at"] = pd.to_datetime(rows["observed_at"], utc=True)
    parts = [p for p in (others, rows) if len(p)]
    result = pd.concat(parts, ignore_index=True)[OBS_COLS] if parts else _empty_obs()
    counts = DiffCounts(
        rows_fetched=len(inc),
        rows_new=int(new.sum()),
        rows_revised=int(revised.sum()),
        rows_closed=int(closed_now.sum()),
    )
    return result, counts


# ---------------------------------------------------------------------------- run outcome
@dataclass(slots=True)
class SeriesOutcome:
    series_id: str
    source: str
    rows_fetched: int = 0
    rows_new: int = 0
    rows_revised: int = 0
    rows_closed: int = 0
    raw_sha256: str | None = None
    error: str | None = None
    duration_ms: int = 0

    def apply(self, counts: DiffCounts) -> None:
        self.rows_fetched = counts.rows_fetched
        self.rows_new = counts.rows_new
        self.rows_revised = counts.rows_revised
        self.rows_closed = counts.rows_closed


@dataclass(slots=True)
class RunSummary:
    run_id: str
    run_date: dt.date
    started_at: dt.datetime
    finished_at: dt.datetime
    status: str
    outcomes: list[SeriesOutcome] = field(default_factory=list)

    @property
    def n_errors(self) -> int:
        return sum(1 for o in self.outcomes if o.error)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(o) for o in self.outcomes])


# ---------------------------------------------------------------------------- update
def _select_specs(
    catalog: Catalog,
    series_ids: Iterable[str] | None,
    source_names: Iterable[str] | None,
) -> list[SeriesSpec]:
    specs = list(catalog.series.values())
    if source_names is not None:
        wanted = set(source_names)
        specs = [s for s in specs if s.source in wanted]
    if series_ids is not None:
        ids = {catalog.resolve_alias(s) for s in series_ids}
        specs = [s for s in specs if s.series_id in ids]
    return specs


def _last_raw_sha(store: Store) -> dict[str, str]:
    idx = schemas.to_pandas(store.read("raw_index"))
    if idx.empty:
        return {}
    idx = idx.sort_values("fetched_at")
    return idx.groupby("series_id")["sha256"].last().to_dict()


def _archive_raw(
    store: Store,
    spec: SeriesSpec,
    result: FetchResult,
    *,
    run_id: str,
    fetched_at: dt.datetime,
    previous_sha: str | None,
) -> tuple[dict[str, object], str]:
    body = result.raw_body or b""
    sha = hashlib.sha256(body).hexdigest()
    rel = f"{spec.source}/{path_safe(spec.series_id)}/{run_id}.{result.raw_ext}.gz"
    stored = sha != previous_sha
    if stored:
        target = store.raw_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wb", compresslevel=6) as fh:
            fh.write(body)
    row = {
        "source": spec.source,
        "series_id": spec.series_id,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "url": result.url,
        "sha256": sha,
        "bytes": len(body),
        "path": rel,
        "stored": stored,
    }
    return row, sha


def _series_stats(part: pd.DataFrame) -> dict[str, tuple[dt.date, dt.date]]:
    if part.empty:
        return {}
    open_rows = part[part["realtime_end"].isna()]
    if open_rows.empty:
        return {}
    g = open_rows.groupby("series_id")["period"]
    return {sid: (mn, mx) for sid, mn, mx in zip(g.min().index, g.min(), g.max(), strict=True)}


def _build_series_table(
    catalog: Catalog,
    existing: pd.DataFrame,
    stats: Mapping[str, tuple[dt.date, dt.date]],
    touched: set[str],
    now: dt.datetime,
) -> pa.Table:
    base = schemas.to_pandas(catalog.series_table())
    prev = existing.set_index("series_id") if not existing.empty else None
    first, last, updated = [], [], []
    for sid in base["series_id"]:
        if sid in touched:
            mn, mx = stats.get(sid, (None, None))
            first.append(mn)
            last.append(mx)
            updated.append(
                now
                if mn is not None
                else (
                    prev.loc[sid, "last_updated"]
                    if prev is not None and sid in prev.index
                    else None
                )
            )
        elif prev is not None and sid in prev.index:
            first.append(prev.loc[sid, "first_period"])
            last.append(prev.loc[sid, "last_period"])
            updated.append(prev.loc[sid, "last_updated"])
        else:
            first.append(None)
            last.append(None)
            updated.append(None)
    base["first_period"] = first
    base["last_period"] = last
    base["last_updated"] = updated
    return schemas.from_pandas(base, schemas.SERIES, "series")


def update(
    store: Store,
    catalog: Catalog,
    sources: Mapping[str, Source],
    *,
    series_ids: Iterable[str] | None = None,
    source_names: Iterable[str] | None = None,
    now: dt.datetime | None = None,
    tz: str = DEFAULT_TZ,
    trigger: str = "manual",
    package_version: str | None = None,
    git_sha: str | None = None,
) -> RunSummary:
    """Run one update over the selected series and commit it as a single run.

    ``now`` is injectable for deterministic tests; it must be timezone-aware.
    """
    started = now or dt.datetime.now(dt.UTC)
    if started.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    run_id = new_run_id(started)
    run_date = run_date_for(started, tz)
    observed_at = started.astimezone(dt.UTC).replace(microsecond=0)
    specs = _select_specs(catalog, series_ids, source_names)
    by_source: dict[str, list[SeriesSpec]] = {}
    for s in specs:
        by_source.setdefault(s.source, []).append(s)

    outcomes: list[SeriesOutcome] = []
    raw_rows: list[dict[str, object]] = []
    stats: dict[str, tuple[dt.date, dt.date]] = {}
    touched: set[str] = set()
    previous_sha = _last_raw_sha(store)

    with store.transaction(run_id=run_id, catalog_hash=catalog.catalog_hash) as tx:
        for source_name, source_specs in sorted(by_source.items()):
            source = sources.get(source_name)
            if source is None:
                for spec in source_specs:
                    outcomes.append(
                        SeriesOutcome(
                            spec.series_id,
                            source_name,
                            error="no connector registered for this source",
                        )
                    )
                continue
            part = _coerce_obs_frame(
                schemas.to_pandas(store.read("observations", partition=f"source={source_name}"))
            )
            partition_touched = False
            for spec in source_specs:
                t0 = perf_counter()
                outcome = SeriesOutcome(spec.series_id, source_name)
                try:
                    result = source.fetch(spec, since=None)
                    if result.raw_body is not None:
                        row, sha = _archive_raw(
                            store,
                            spec,
                            result,
                            run_id=run_id,
                            fetched_at=observed_at,
                            previous_sha=previous_sha.get(spec.series_id),
                        )
                        raw_rows.append(row)
                        outcome.raw_sha256 = sha
                    frame = result.frame
                    if frame is None or len(frame) == 0:
                        outcome.error = "empty response; no changes applied"
                    else:
                        if result.has_vintages:
                            part, counts = apply_vintages(
                                part,
                                frame,
                                series_id=spec.series_id,
                                observed_at=observed_at,
                                run_id=run_id,
                            )
                        else:
                            part, counts = apply_snapshot(
                                part,
                                frame,
                                series_id=spec.series_id,
                                run_date=run_date,
                                observed_at=observed_at,
                                run_id=run_id,
                                covers_from=result.covers_from,
                            )
                        outcome.apply(counts)
                        touched.add(spec.series_id)
                        partition_touched = True
                except Exception as exc:  # one series must never abort the run
                    log.exception("fetch failed for %s", spec.series_id)
                    outcome.error = f"{type(exc).__name__}: {exc}"
                outcome.duration_ms = int((perf_counter() - t0) * 1000)
                outcomes.append(outcome)
            if partition_touched:
                tx.replace_partition(
                    "observations", source_name, schemas.from_pandas(part, schemas.OBSERVATIONS)
                )
                stats.update(_series_stats(part))

        existing_series = schemas.to_pandas(store.read("series"))
        tx.replace_table(
            "series", _build_series_table(catalog, existing_series, stats, touched, observed_at)
        )
        tx.replace_table("entities", catalog.entities_table())
        if raw_rows:
            tx.append_table(
                "raw_index", schemas.from_pandas(pd.DataFrame(raw_rows), schemas.RAW_INDEX)
            )
        finished = now if now is not None else dt.datetime.now(dt.UTC)
        n_err = sum(1 for o in outcomes if o.error)
        status = (
            "ok" if n_err == 0 else ("failed" if n_err == len(outcomes) and outcomes else "partial")
        )
        if outcomes:
            rs = pd.DataFrame([{**asdict(o), "run_id": run_id} for o in outcomes])
            tx.append_table("run_series", schemas.from_pandas(rs, schemas.RUN_SERIES))
        runs = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "started_at": observed_at,
                    "finished_at": finished.astimezone(dt.UTC).replace(microsecond=0),
                    "status": status,
                    "trigger": trigger,
                    "package_version": package_version,
                    "git_sha": git_sha,
                    "catalog_hash": catalog.catalog_hash,
                    "n_series": len(outcomes),
                    "n_errors": n_err,
                }
            ]
        )
        tx.append_table("runs", schemas.from_pandas(runs, schemas.RUNS))

    return RunSummary(run_id, run_date, observed_at, finished, status, outcomes)


# ---------------------------------------------------------------------------- freshness
def _period_end(period: dt.date, freq: str) -> dt.date:
    ts = pd.Timestamp(period)
    if freq in ("D", "B"):
        return period
    if freq == "W":
        return period + dt.timedelta(days=6)
    if freq == "M":
        return (ts + pd.offsets.MonthEnd(0)).date()
    if freq == "Q":
        return (ts + pd.offsets.QuarterEnd(startingMonth=((ts.month - 1) // 3 + 1) * 3)).date()
    if freq == "A":
        return dt.date(period.year, 12, 31)
    raise ValueError(f"unknown freq {freq!r}")


def _next_period_start(period: dt.date, freq: str) -> dt.date:
    ts = pd.Timestamp(period)
    if freq == "D":
        return period + dt.timedelta(days=1)
    if freq == "B":
        return (ts + pd.offsets.BDay(1)).date()
    if freq == "W":
        return period + dt.timedelta(days=7)
    if freq == "M":
        return (ts + pd.offsets.MonthBegin(1)).date()
    if freq == "Q":
        return (ts + pd.offsets.DateOffset(months=3)).date()
    if freq == "A":
        return dt.date(period.year + 1, 1, 1)
    raise ValueError(f"unknown freq {freq!r}")


def check(store: Store, catalog: Catalog, *, today: dt.date | None = None) -> pd.DataFrame:
    """Freshness per catalog series: ``ok``, ``stale``, ``no_data`` or ``unknown_lag``.

    A series is stale when the *next* period after its last one should already have been
    published: ``period_end(next) + expected_lag_days < today``.
    """
    today = today or dt.date.today()
    last = schemas.to_pandas(
        store.query(
            "SELECT series_id, max(period) AS last_period FROM obs_latest GROUP BY series_id"
        )
    )
    last_map = (
        dict(zip(last["series_id"], last["last_period"], strict=True)) if not last.empty else {}
    )
    rows = []
    for spec in catalog.series.values():
        lp = last_map.get(spec.series_id)
        row = {
            "series_id": spec.series_id,
            "source": spec.source,
            "freq": spec.freq,
            "last_period": lp,
            "expected_lag_days": spec.expected_lag_days,
            "expected_by": None,
            "days_stale": None,
            "status": "no_data",
        }
        if lp is not None:
            if spec.expected_lag_days is None:
                row["status"] = "unknown_lag"
            else:
                expected_by = _period_end(
                    _next_period_start(lp, spec.freq), spec.freq
                ) + dt.timedelta(days=spec.expected_lag_days)
                days = (today - expected_by).days
                row["expected_by"] = expected_by
                row["days_stale"] = max(days, 0)
                row["status"] = "stale" if days > 0 else "ok"
        rows.append(row)
    return pd.DataFrame(rows)
