"""Series transformations: frequency conversion and the usual rates of change.

Everything here is pure pandas and numpy so it stays in the core package. Filters that need
`scipy` or `statsmodels` (Hodrick-Prescott, Hamilton, X-13) belong to `econmodels`, where the
optional dependencies live, and they are estimated on the as-of panel of a run rather than
precomputed — see AGENTS.md rule 8.

Two rules run through the module:

* **A downsample always states its aggregation.** Averaging a policy rate over a quarter and
  taking its end-of-quarter value are different series, so the caller says which one it means.
* **Upsampling is refused.** Turning quarterly GDP into a monthly series requires a model of
  what happened in between; that is an analysis, not a data-layer convenience, and the mixed
  frequency dynamic factor model handles it properly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import numpy as np
import pandas as pd

#: Periods per year, used to annualize a rate and to order frequencies.
PERIODS_PER_YEAR: dict[str, float] = {
    "D": 365.25,
    "B": 252.0,
    "W": 52.0,
    "M": 12.0,
    "Q": 4.0,
    "A": 1.0,
}

#: Coarser frequencies have a higher rank; a downsample moves up.
_RANK: dict[str, int] = {"D": 0, "B": 1, "W": 2, "M": 3, "Q": 4, "A": 5}

_PANDAS_RULE: dict[str, str] = {"D": "D", "B": "B", "W": "W", "M": "MS", "Q": "QS", "A": "YS"}


class TransformError(ValueError):
    """A transformation was asked for that would misrepresent the data."""


def periods_per_year(freq: str) -> float:
    try:
        return PERIODS_PER_YEAR[freq]
    except KeyError:
        raise TransformError(f"unknown frequency {freq!r}") from None


def _check_freq(freq: str) -> str:
    if freq not in _RANK:
        raise TransformError(f"unknown frequency {freq!r}")
    return freq


def _as_series(frame: pd.DataFrame) -> pd.Series:
    """A ``period``/``value`` frame as a Series indexed by a DatetimeIndex."""
    if "period" not in frame.columns or "value" not in frame.columns:
        raise TransformError("expected columns 'period' and 'value'")
    s = pd.Series(
        pd.to_numeric(frame["value"], errors="coerce").to_numpy(dtype="float64"),
        index=pd.DatetimeIndex(pd.to_datetime(frame["period"])),
        name="value",
    )
    return s.sort_index()


def _as_frame(series: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": [d.date() if isinstance(d, dt.datetime) else d for d in series.index],
            "value": series.to_numpy(dtype="float64"),
        }
    )


# ---------------------------------------------------------------------------- frequency
def _compound(values: pd.Series) -> float:
    """Chain period rates of change, in percent, into the rate for the whole period."""
    present = values.dropna()
    if present.empty:
        return float("nan")
    return float(((1.0 + present / 100.0).prod() - 1.0) * 100.0)


def resample(frame: pd.DataFrame, *, from_freq: str, to_freq: str, agg: str) -> pd.DataFrame:
    """Convert a ``period``/``value`` frame to a coarser frequency.

    ``agg`` is one of ``last``, ``eop``, ``mean``, ``sum``, ``compound``. ``last`` and ``eop``
    both take the final observation of the period; they differ only for strictly regular data,
    which economic series rarely are, so they are kept as synonyms rather than as a false
    distinction.

    ``compound`` is the one that is not interchangeable with its neighbours. A series of period
    rates of change does not add: twelve months at 0.5 per cent make 6.17 per cent, not 6.00,
    and the gap widens with the rate — at Brazil's 2002 inflation it passes half a point. Rates
    of change take ``compound``; flows take ``sum``; levels and rates per annum take ``mean``,
    ``last`` or ``eop``.
    """
    _check_freq(from_freq)
    _check_freq(to_freq)
    if from_freq == to_freq:
        return frame.reset_index(drop=True)
    if _RANK[to_freq] < _RANK[from_freq]:
        raise TransformError(
            f"cannot upsample {from_freq} to {to_freq}: inventing observations between periods "
            "is a modelling choice, not a conversion. Use a mixed-frequency model instead."
        )
    series = _as_series(frame)
    if series.empty:
        return frame.reset_index(drop=True)
    grouper = series.resample(_PANDAS_RULE[to_freq])
    if agg in ("last", "eop"):
        out = grouper.last()
    elif agg == "mean":
        out = grouper.mean()
    elif agg == "sum":
        out = grouper.sum(min_count=1)
    elif agg == "compound":
        out = grouper.apply(_compound)
    else:
        raise TransformError(f"unknown aggregation {agg!r}; use last, eop, mean, sum or compound")
    return _as_frame(out.dropna(how="all"))


# ---------------------------------------------------------------------------- rates of change
def _shift_for(freq: str, horizon: str) -> int:
    if horizon == "period":
        return 1
    if horizon == "year":
        per_year = periods_per_year(freq)
        if freq in ("D", "B", "W"):
            raise TransformError(
                f"a year-over-year change on {freq} data is ambiguous; resample to M, Q or A first"
            )
        return round(per_year)
    raise TransformError(f"unknown horizon {horizon!r}")


def pct_change(
    frame: pd.DataFrame, *, freq: str, horizon: str = "period", annualize: bool = False
) -> pd.DataFrame:
    """Percentage change over one period (``horizon='period'``) or one year (``'year'``)."""
    series = _as_series(frame)
    shift = _shift_for(_check_freq(freq), horizon)
    out = series.pct_change(periods=shift) * 100.0
    if annualize:
        out = annualize_rate(out, freq=freq, periods=shift)
    return _as_frame(out)


def log_diff(
    frame: pd.DataFrame, *, freq: str, horizon: str = "period", annualize: bool = False
) -> pd.DataFrame:
    """100 times the change in logs: the continuously-compounded counterpart of ``pct_change``."""
    series = _as_series(frame)
    shift = _shift_for(_check_freq(freq), horizon)
    with np.errstate(divide="ignore", invalid="ignore"):
        logged = np.log(series.where(series > 0))
    out = (logged - logged.shift(shift)) * 100.0
    if annualize:
        out = out * (periods_per_year(freq) / shift)
    return _as_frame(out)


def annualize_rate(series: pd.Series, *, freq: str, periods: int = 1) -> pd.Series:
    """Compound a percentage change measured over ``periods`` into an annual rate."""
    exponent = periods_per_year(freq) / periods
    return ((1.0 + series / 100.0) ** exponent - 1.0) * 100.0


def diff(frame: pd.DataFrame, *, periods: int = 1) -> pd.DataFrame:
    """Simple difference, for series already expressed in rates or percentage points."""
    return _as_frame(_as_series(frame).diff(periods=periods))


def lag(frame: pd.DataFrame, *, periods: int = 1) -> pd.DataFrame:
    """Shift the values forward in time, leaving the period index untouched."""
    return _as_frame(_as_series(frame).shift(periods=periods))


# ---------------------------------------------------------------------------- levels
def rebase(frame: pd.DataFrame, *, base: dt.date | str, value: float = 100.0) -> pd.DataFrame:
    """Rescale an index so that ``base`` equals ``value``."""
    series = _as_series(frame)
    stamp = pd.Timestamp(base)
    if stamp not in series.index:
        raise TransformError(f"base period {base} is not in the series")
    anchor = series.loc[stamp]
    if not np.isfinite(anchor) or anchor == 0:
        raise TransformError(f"base period {base} has no usable value ({anchor})")
    return _as_frame(series / anchor * value)


def deflate(
    nominal: pd.DataFrame, deflator: pd.DataFrame, *, base: dt.date | str | None = None
) -> pd.DataFrame:
    """Divide a nominal series by a price index, optionally rebased first.

    Periods present in one frame and not the other are dropped: a real series is only defined
    where both parts of it exist.
    """
    num = _as_series(nominal)
    den = _as_series(deflator)
    if base is not None:
        den = _as_series(rebase(_as_frame(den), base=base))
    joined = pd.concat([num.rename("n"), den.rename("d")], axis=1, join="inner")
    joined = joined[joined["d"].notna() & (joined["d"] != 0)]
    return _as_frame(joined["n"] / joined["d"] * 100.0)


# ---------------------------------------------------------------------------- registry
def _yoy(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    return pct_change(frame, freq=freq, horizon="year")


def _mom(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    return pct_change(frame, freq=freq, horizon="period")


def _mom_ann(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    return pct_change(frame, freq=freq, horizon="period", annualize=True)


def _log_diff(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    return log_diff(frame, freq=freq, horizon="period")


def _log_diff_ann(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    return log_diff(frame, freq=freq, horizon="period", annualize=True)


def _diff(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    return diff(frame)


#: Transformations `api.get(transform=...)` accepts, by name.
TRANSFORMS: dict[str, Callable[[pd.DataFrame, str], pd.DataFrame]] = {
    "yoy": _yoy,
    "mom": _mom,
    "mom_ann": _mom_ann,
    "log_diff": _log_diff,
    "log_diff_ann": _log_diff_ann,
    "diff": _diff,
}


def apply(frame: pd.DataFrame, name: str, *, freq: str) -> pd.DataFrame:
    """Apply a named transformation from :data:`TRANSFORMS`."""
    try:
        fn = TRANSFORMS[name]
    except KeyError:
        raise TransformError(
            f"unknown transform {name!r}; available: {', '.join(sorted(TRANSFORMS))}"
        ) from None
    return fn(frame, freq)
