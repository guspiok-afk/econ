"""When a period would have been known, for the series whose history does not record it.

The store keeps true vintages wherever the source publishes them — FRED does, so asking the
United States GDP as of June 2018 returns the 285 observations that existed then, ending at
2018Q1. For everything else `realtime_start` is the date this project collected the row, and
collection began on 3 September 2026. Asking any Brazilian series as of 2024 therefore returns
**nothing**, silently, which is the worst possible answer: an empty panel looks like a modelling
choice rather than a missing capability.

A pseudo-real-time backtest is exactly what phase five needs and exactly what that prevents, so
this module reconstructs the missing half from the one fact the catalog already records: how many
days after the end of a period the source usually publishes it. A period counts as known at a
date when ``period_end + expected_lag_days <= asof``.

The result is a simulation and must never be called anything else. `RunContext.vintage_kind`
already carries the vocabulary — ``true``, ``pseudo``, ``mixed``, ``latest`` — and this is what
finally makes it mean something. A backtest built on pseudo vintages is worth running and is not
worth confusing with one built on recorded ones; ``mixed`` reports the split per series so nobody
has to remember which was which.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.pipeline import _period_end

VINTAGE_KINDS = ("latest", "true", "pseudo", "mixed")


class VintageError(ValueError):
    """A vintage was asked for in a way the data cannot answer."""


@dataclass(frozen=True, slots=True)
class Availability:
    """Which kind of history one series actually has."""

    series_id: str
    has_true_vintages: bool
    earliest_known: dt.date | None
    expected_lag_days: int | None

    @property
    def usable_kind(self) -> str:
        return "true" if self.has_true_vintages else "pseudo"


def published_at(period: dt.date, spec: SeriesSpec) -> dt.date | None:
    """The date the source would have published ``period``, or ``None`` when unknowable."""
    if spec.expected_lag_days is None:
        return None
    return _period_end(period, spec.freq) + dt.timedelta(days=int(spec.expected_lag_days))


def availability(frame: pd.DataFrame, spec: SeriesSpec) -> Availability:
    """Read from the stored rows whether this series carries real vintages.

    The catalog already declares it: a source that publishes real-time periods carries
    ``params: {vintages: true}``, which is how the connector was told to fetch them. That
    declaration is the answer, and inferring one from the rows instead would be guessing — a
    vintaged series whose recorded rows happen to share a collection date looks un-vintaged, and
    a fixture is exactly where that happens.

    The row count is kept only as a fallback for a series the catalog says nothing about: many
    distinct ``realtime_start`` values cannot arise from a single collection.
    """
    if frame.empty:
        return Availability(
            spec.series_id, _declares_vintages(spec) or False, None, spec.expected_lag_days
        )
    starts = pd.to_datetime(frame["realtime_start"]).dt.date
    declared = _declares_vintages(spec)
    return Availability(
        series_id=spec.series_id,
        has_true_vintages=declared if declared is not None else starts.nunique() > 1,
        earliest_known=starts.min(),
        expected_lag_days=spec.expected_lag_days,
    )


def _declares_vintages(spec: SeriesSpec) -> bool | None:
    """What the catalog says, or ``None`` when it says nothing."""
    params = getattr(spec, "params", None) or {}
    value = params.get("vintages")
    return bool(value) if value is not None else None


def pseudo_asof(frame: pd.DataFrame, spec: SeriesSpec, asof: dt.date) -> pd.DataFrame:
    """The rows a reader would have had at ``asof``, simulated from the publication lag.

    Only the current value of each period is used, because a series without true vintages has no
    other value to offer: the simulation can say *when* something became known and cannot invent
    *what* was first said. That limit is the honest boundary of a pseudo backtest and belongs in
    any write-up of one.
    """
    if spec.expected_lag_days is None:
        raise VintageError(
            f"{spec.series_id} has no expected_lag_days, so there is nothing to simulate from. "
            "Give it one in the catalog, or ask for vintage_kind='latest' and say so."
        )
    if frame.empty:
        return frame
    current = frame[frame["realtime_end"].isna()] if "realtime_end" in frame else frame
    periods = pd.to_datetime(current["period"]).dt.date
    known = periods.map(lambda p: published_at(p, spec)) <= asof
    return current[known].reset_index(drop=True)


def describe_split(kinds: dict[str, str]) -> str:
    """A one-line summary of which series used which kind, for a result's diagnostics."""
    if not kinds:
        return "none"
    counts: dict[str, int] = {}
    for kind in kinds.values():
        counts[kind] = counts.get(kind, 0) + 1
    return ", ".join(f"{kind}:{count}" for kind, count in sorted(counts.items()))
