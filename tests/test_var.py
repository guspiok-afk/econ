"""Acceptance tests for WP-04d: the monetary VAR with recursive identification.

The pinned result is a fact about the United States that every textbook reproduces and that
this base must reproduce too: a contractionary monetary shock lowers output after about two
years, and — with recursive identification on this ordering — inflation *rises* first. That
second half is the price puzzle. It is not a bug to be fixed here; it is the finding that
motivates sign restrictions, and a VAR that does not show it on this sample is not fitting the
same data.

The other tests guard identification itself. A recursive scheme means the ordering is an
economic assumption, and an implementation that ignores it would still produce plausible
pictures.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("econmodels.var", reason="WP-04d not implemented yet")

from econmodels.var import VectorAutoregression

from econmodels.base import RunContext

FIX = Path(__file__).parent / "fixtures" / "analysis" / "us_quarterly_var.csv"
SAMPLE_END = "2019-10-01"  # 2020 dominates any linear VAR; the package documents the cut


def ctx(asof: str = "2026-09-04") -> RunContext:
    return RunContext(asof=dt.date.fromisoformat(asof), seed=0)


def us_panel(end: str | None = SAMPLE_END) -> pd.DataFrame:
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


def irf_path(result, shock: str, response: str) -> pd.Series:
    t = result.tables()["irf"]
    sel = t[(t["shock"] == shock) & (t["response"] == response)]
    return sel.set_index("horizon")["value"].sort_index()


# ------------------------------------------------------------------ identification
def test_a_recursive_scheme_puts_zeros_where_it_promised() -> None:
    """On this ordering nothing but the policy rate may move in the quarter of the shock."""
    r = VectorAutoregression(entity="US", lags=4, horizon=24).fit(us_panel(), ctx())
    assert irf_path(r, "policy", "inflation").loc[0] == pytest.approx(0.0, abs=1e-12)
    assert irf_path(r, "policy", "output").loc[0] == pytest.approx(0.0, abs=1e-12)
    assert irf_path(r, "policy", "policy").loc[0] > 0.5


def test_the_ordering_is_an_assumption_and_changing_it_changes_the_answer() -> None:
    """If reversing the order leaves the impact responses untouched, nothing is identified."""
    base = VectorAutoregression(entity="US", lags=4, horizon=8).fit(us_panel(), ctx())
    flipped = VectorAutoregression(
        entity="US", lags=4, horizon=8, order=("policy", "output", "inflation")
    ).fit(us_panel(), ctx())
    a = irf_path(base, "policy", "inflation").loc[0]
    b = irf_path(flipped, "policy", "inflation").loc[0]
    assert abs(a - b) > 1e-6, "the identification is not doing anything"


def test_the_ordering_travels_with_the_result() -> None:
    r = VectorAutoregression(entity="US", lags=4).fit(us_panel(), ctx())
    diag = r.tables()["diagnostics"].set_index("metric")["value"]
    assert "identification" in diag.index and "order" in diag.index
    assert "lags" in diag.index and float(diag["lags"]) == 4


# ------------------------------------------------------------------ the pinned economics
def test_a_contractionary_shock_lowers_output() -> None:
    """1961Q1 to 2019Q4, four lags: the trough is about half a per cent, two to five years out."""
    r = VectorAutoregression(entity="US", lags=4, horizon=24).fit(us_panel(), ctx())
    output = irf_path(r, "policy", "output")
    assert output.min() < -0.35, f"trough {output.min():.4f} is too shallow to be the textbook one"
    assert 8 <= int(output.idxmin()) <= 20, "the trough should arrive between two and five years"
    assert output.loc[24] < 0, "output has not returned above trend by the sixth year"


def test_the_impact_response_of_the_rate_is_the_recorded_one() -> None:
    r = VectorAutoregression(entity="US", lags=4, horizon=24).fit(us_panel(), ctx())
    assert irf_path(r, "policy", "policy").loc[0] == pytest.approx(0.7545, abs=0.02)


def test_the_price_puzzle_is_there_because_it_is_in_the_data() -> None:
    """Inflation rises for the first year after a tightening. It is the reason sign
    restrictions exist, and a run that hides it is not fitting this sample."""
    r = VectorAutoregression(entity="US", lags=4, horizon=24).fit(us_panel(), ctx())
    first_year = irf_path(r, "policy", "inflation").loc[1:4]
    assert first_year.max() > 0.25, (
        f"peak inflation response of {first_year.max():.4f} in the first year: the price puzzle "
        "should be plainly visible on this sample and ordering"
    )


def test_the_sample_is_the_one_the_package_declares() -> None:
    r = VectorAutoregression(entity="US", lags=4).fit(us_panel(), ctx())
    diag = r.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["n_obs"]) == pytest.approx(232, abs=1)


# ------------------------------------------------------------------ the model itself
def test_the_system_is_stable_and_says_so() -> None:
    """An explosive VAR produces impulse responses that grow without bound and look decisive."""
    r = VectorAutoregression(entity="US", lags=4).fit(us_panel(), ctx())
    diag = r.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["max_eigenvalue"]) < 1.0


def test_choosing_the_lag_length_records_what_was_chosen() -> None:
    r = VectorAutoregression(entity="US", lags="aic", max_lags=8).fit(us_panel(), ctx())
    chosen = float(r.tables()["diagnostics"].set_index("metric")["value"]["lags"])
    assert 1 <= chosen <= 8


def test_the_variance_decomposition_sums_to_one() -> None:
    r = VectorAutoregression(entity="US", lags=4, horizon=12).fit(us_panel(), ctx())
    fevd = r.tables()["fevd"]
    totals = fevd.groupby(["horizon", "response"])["value"].sum()
    assert np.allclose(totals.to_numpy(), 1.0, atol=1e-8), (
        "a decomposition must exhaust the variance"
    )


def test_two_runs_of_the_same_specification_agree() -> None:
    a = VectorAutoregression(entity="US", lags=4, horizon=8).fit(us_panel(), ctx())
    b = VectorAutoregression(entity="US", lags=4, horizon=8).fit(us_panel(), ctx())
    assert np.allclose(
        a.tables()["irf"]["value"].to_numpy(), b.tables()["irf"]["value"].to_numpy(), atol=1e-12
    )


# ------------------------------------------------------------------ portability and refusal
def test_the_model_asks_for_concepts_so_it_runs_on_any_country() -> None:
    needs = {r.concept for r in VectorAutoregression(entity="BR").requires}
    assert needs == {"cpi_headline_index", "gdp_real", "policy_rate"}


def test_too_few_observations_for_the_lag_length_is_refused() -> None:
    short = us_panel().head(12)
    with pytest.raises(ValueError, match=r"(?i)observations|lags|sample"):
        VectorAutoregression(entity="US", lags=4).fit(short, ctx())
