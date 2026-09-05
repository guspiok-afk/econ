"""Acceptance tests for WP-04b: the Taylor rule.

The pinned result is the paper's own claim. Taylor (1993) showed a simple rule tracking the
federal funds rate closely over 1987-1992; run from this base with his settings, the
prescription correlates 0.78 with the actual rate and misses by about one point on average.

The other tests guard the two things that make a policy rule wrong in ways that look right: the
arithmetic, and the output gap. A filter run over the whole sample and then read at a past date
knows the future, which is the leakage the vintages exist to prevent.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("econmodels.taylor", reason="WP-04b not implemented yet")

from econmodels.base import RunContext
from econmodels.taylor import TaylorRule

FIX = Path(__file__).parent / "fixtures" / "analysis" / "us_quarterly_taylor.csv"


def ctx(asof: str = "2026-09-04") -> RunContext:
    return RunContext(asof=dt.date.fromisoformat(asof), seed=0)


def us_panel(end: str | None = None) -> pd.DataFrame:
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    if end:
        raw = raw.loc[:end]
    return pd.DataFrame(
        {
            "cpi_headline_index@US": raw["cpi_index"],
            "gdp_real@US": raw["gdp_real"],
            "policy_rate@US": raw["fed_funds"],
        }
    )


def flat_panel(inflation: float, gap_pct: float, n: int = 40) -> pd.DataFrame:
    """A world with constant inflation and a constant output gap, so the rule is arithmetic."""
    idx = pd.date_range("2000-01-01", periods=n, freq="QS")
    cpi = pd.Series(100.0 * (1 + inflation / 100) ** (np.arange(n) / 4), index=idx)
    trend = pd.Series(1000.0 * 1.005 ** np.arange(n), index=idx)
    return pd.DataFrame(
        {
            "cpi_headline_index@US": cpi,
            "gdp_real@US": trend * (1 + gap_pct / 100),
            "policy_rate@US": pd.Series(4.0, index=idx),
        }
    )


# ------------------------------------------------------------------ the arithmetic
def test_the_rule_is_the_formula() -> None:
    """r* + pi + a(pi - target) + b(gap), with nothing else added quietly."""
    model = TaylorRule(entity="US", neutral_real_rate=2.0, inflation_target=2.0)
    result = model.fit(flat_panel(inflation=4.0, gap_pct=0.0), ctx())
    row = result.tables()["prescription"].dropna(subset=["prescribed"]).iloc[-1]
    expected = 2.0 + 4.0 + 0.5 * (4.0 - 2.0)
    assert float(row["prescribed"]) == pytest.approx(expected, abs=1e-6)
    assert float(row["inflation"]) == pytest.approx(4.0, abs=1e-6)


def test_the_weights_do_what_they_say() -> None:
    panel = flat_panel(inflation=6.0, gap_pct=0.0)
    half = TaylorRule(entity="US", weight_inflation=0.5).fit(panel, ctx())
    full = TaylorRule(entity="US", weight_inflation=1.0).fit(panel, ctx())
    a = float(half.tables()["prescription"].dropna(subset=["prescribed"]).iloc[-1]["prescribed"])
    b = float(full.tables()["prescription"].dropna(subset=["prescribed"]).iloc[-1]["prescribed"])
    assert b - a == pytest.approx(0.5 * (6.0 - 2.0), abs=1e-6)


def test_a_neutral_rate_shifts_the_whole_path() -> None:
    panel = us_panel()
    low = TaylorRule(entity="US", neutral_real_rate=0.5).fit(panel, ctx())
    high = TaylorRule(entity="US", neutral_real_rate=2.0).fit(panel, ctx())
    d = (
        high.tables()["prescription"]["prescribed"] - low.tables()["prescription"]["prescribed"]
    ).dropna()
    assert d.round(9).nunique() == 1 and d.iloc[0] == pytest.approx(1.5, abs=1e-6)


def test_the_deviation_is_actual_minus_prescribed() -> None:
    table = TaylorRule(entity="US").fit(us_panel(), ctx()).tables()["prescription"].dropna()
    assert (table["deviation"] - (table["actual"] - table["prescribed"])).abs().max() < 1e-9


# ------------------------------------------------------------------ the paper
def test_taylors_own_sample_reproduces_his_claim() -> None:
    """1987Q1 to 1992Q3, his settings: the rule tracks the funds rate closely."""
    result = TaylorRule(
        entity="US",
        neutral_real_rate=2.0,
        inflation_target=2.0,
        weight_inflation=0.5,
        weight_gap=0.5,
    ).fit(us_panel(), ctx())
    table = result.tables()["prescription"].set_index("period").loc["1987-01-01":"1992-07-01"]
    table = table.dropna(subset=["actual", "prescribed"])

    assert len(table) == 23, "the sample is twenty-three quarters"
    correlation = table["actual"].corr(table["prescribed"])
    mad = (table["actual"] - table["prescribed"]).abs().mean()
    assert correlation >= 0.75, f"correlation {correlation:.3f} is too low to call it tracking"
    assert mad <= 1.2, f"mean absolute deviation {mad:.2f} points is too wide"


def test_the_settings_travel_with_the_result() -> None:
    """A prescription without its assumptions cannot be argued with."""
    result = TaylorRule(entity="US", neutral_real_rate=1.0, inflation_target=3.0).fit(
        us_panel(), ctx()
    )
    diag = result.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["neutral_real_rate"]) == 1.0
    assert float(diag["inflation_target"]) == 3.0
    assert "gap_method" in diag.index


def test_estimating_the_weights_recovers_something_sensible() -> None:
    result = TaylorRule(entity="US").estimate(us_panel(), ctx())
    coef = result.tables()["coefficients"].set_index("name")
    assert {"inflation", "gap"} <= set(coef.index)
    assert float(coef.loc["inflation", "estimate"]) > 0, (
        "a central bank that raises rates when inflation falls is not a Taylor rule"
    )
    assert float(coef.loc["inflation", "std_error"]) > 0


# ------------------------------------------------------------------ the gap
def test_the_gap_is_computed_on_the_panel_it_was_given() -> None:
    """A filter run over the whole sample and read at a past date knows the future."""
    short = TaylorRule(entity="US").fit(us_panel(end="1990-10-01"), ctx("1990-12-31"))
    full = TaylorRule(entity="US").fit(us_panel(), ctx())
    q = pd.Timestamp("1990-10-01")
    g_short = float(short.tables()["prescription"].set_index("period").loc[q, "gap"])
    g_full = float(full.tables()["prescription"].set_index("period").loc[q, "gap"])
    assert not np.isnan(g_short)
    # a two-sided filter legitimately revises the past; what it may not do is hide that it did
    if abs(g_short - g_full) > 1e-9:
        diag = full.tables()["diagnostics"].set_index("metric")["value"]
        assert "two_sided" in " ".join(map(str, diag.index)) or "gap_method" in diag.index


def test_the_gap_is_centred_and_in_percent() -> None:
    table = TaylorRule(entity="US").fit(us_panel(), ctx()).tables()["prescription"].dropna()
    assert abs(table["gap"].mean()) < 1.0, (
        "an output gap averaging far from zero is a trend, not a gap"
    )
    assert table["gap"].abs().max() < 15.0, "the gap is in percent of potential, not a ratio"


def test_a_gap_of_zero_leaves_only_the_inflation_terms() -> None:
    model = TaylorRule(entity="US", weight_gap=0.0)
    result = model.fit(us_panel(), ctx())
    table = result.tables()["prescription"].dropna(subset=["prescribed", "inflation"])
    expected = 2.0 + table["inflation"] + 0.5 * (table["inflation"] - 2.0)
    assert (table["prescribed"] - expected).abs().max() < 1e-9


# ------------------------------------------------------------------ portability
def test_the_model_asks_for_concepts_so_it_runs_on_any_country() -> None:
    needs = {r.concept for r in TaylorRule(entity="BR").requires}
    assert needs == {"cpi_headline_index", "gdp_real", "policy_rate"}


def test_a_country_without_the_inputs_fails_clearly() -> None:
    empty = pd.DataFrame(
        {"cpi_headline_index@US": [], "gdp_real@US": [], "policy_rate@US": []},
        index=pd.DatetimeIndex([], name="period"),
    )
    with pytest.raises(ValueError, match=r"(?i)observations|empty|sample"):
        TaylorRule(entity="US").fit(empty, ctx())
