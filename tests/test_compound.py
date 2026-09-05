"""Rates of change do not add, and the Banco Central publishes the proof.

`bcb_sgs:433` is the monthly IPCA and `bcb_sgs:13522` is the twelve-month accumulated rate the
Banco Central computes from it. Chaining the monthlies reproduces the published series to within
its own rounding; adding them is wrong by up to two thirds of a point, which is the size of an
inflation surprise. The recorded fixture is 319 months, from 2000.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from econbase.transforms import TransformError, resample

FIX = Path(__file__).parent / "fixtures" / "analysis" / "br_ipca_monthly_vs_12m.csv"


def frame(values: list[float], start: str = "2020-01-01", freq: str = "MS") -> pd.DataFrame:
    return pd.DataFrame(
        {"period": pd.date_range(start, periods=len(values), freq=freq), "value": values}
    )


def test_three_months_of_one_percent_compound_and_do_not_add() -> None:
    out = resample(frame([1.0, 1.0, 1.0]), from_freq="M", to_freq="Q", agg="compound")
    assert float(out["value"].iloc[0]) == pytest.approx(3.030100, abs=1e-9)


def test_a_fall_and_a_rise_do_not_cancel() -> None:
    """Down ten per cent and up ten per cent is a loss, not a wash."""
    out = resample(frame([-10.0, 10.0, 0.0]), from_freq="M", to_freq="Q", agg="compound")
    assert float(out["value"].iloc[0]) == pytest.approx(-1.0, abs=1e-9)


def test_a_missing_month_is_skipped_not_treated_as_zero() -> None:
    out = resample(frame([1.0, np.nan, 1.0]), from_freq="M", to_freq="Q", agg="compound")
    assert float(out["value"].iloc[0]) == pytest.approx(2.01, abs=1e-9)


def test_a_quarter_with_nothing_in_it_stays_missing() -> None:
    out = resample(frame([np.nan, np.nan, np.nan]), from_freq="M", to_freq="Q", agg="compound")
    assert out.empty or bool(pd.isna(out["value"].iloc[0]))


def test_an_unknown_aggregation_still_names_the_ones_that_exist() -> None:
    with pytest.raises(TransformError, match="compound"):
        resample(frame([1.0, 2.0]), from_freq="M", to_freq="Q", agg="geometric")


# ------------------------------------------------------------------ the published proof
@pytest.fixture(scope="module")
def ipca() -> pd.DataFrame:
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    chained = ((1.0 + raw["ipca_mensal"] / 100.0).rolling(12).apply(np.prod) - 1.0) * 100.0
    return pd.DataFrame({"chained": chained, "published": raw["ipca_12m_bcb"]}).dropna()


def test_chaining_the_monthlies_reproduces_the_published_twelve_month_rate(
    ipca: pd.DataFrame,
) -> None:
    error = (ipca["chained"] - ipca["published"]).abs()
    assert len(ipca) > 300, "the fixture should cover more than three hundred months"
    assert error.max() < 0.02, (
        f"worst month is off by {error.max():.4f} points; the published series carries two "
        "decimals, so anything beyond rounding means the chaining is wrong"
    )


def test_adding_the_monthlies_would_have_been_wrong_by_far_more(ipca: pd.DataFrame) -> None:
    """The test that gives the other one its meaning: the wrong method is wrong visibly."""
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    added = raw["ipca_mensal"].rolling(12).sum()
    error = (added - raw["ipca_12m_bcb"]).abs().dropna()
    assert error.max() > 0.5, (
        "if summing were this close to the published series, compounding would not be worth "
        "the aggregation"
    )
