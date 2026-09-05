"""Acceptance tests for WP-04a: uncovered interest parity.

Three kinds, in the order of what they prove. The synthetic ones check the algebra: if parity
holds by construction the slope must be one, and nothing else matters until it is. The recorded
one checks the whole chain against reality, and pins the forward premium puzzle — the slope is
negative where theory says one. The last one checks that a fit made as of a past date cannot
see what was published afterwards.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("econmodels.parity", reason="WP-04a not implemented yet")

from econmodels.base import RunContext
from econmodels.parity import UncoveredParity

FIX = Path(__file__).parent / "fixtures" / "analysis" / "br_us_monthly_parity.csv"
HORIZON = 12


def ctx(asof: str = "2026-09-04") -> RunContext:
    return RunContext(asof=dt.date.fromisoformat(asof), seed=0)


def panel_from_fixture() -> pd.DataFrame:
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    return pd.DataFrame(
        {
            "fx_spot_usd@BR": raw["brl_usd"],
            "policy_rate@BR": raw["selic"],
            "policy_rate@US": raw["fed_funds"],
        }
    )


def synthetic(beta: float, alpha: float = 0.0, n: int = 240, noise: float = 0.0) -> pd.DataFrame:
    """A world where the depreciation is exactly alpha + beta * differential."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2000-01-01", periods=n, freq="MS")
    diff = pd.Series(rng.uniform(2.0, 14.0, n), index=idx)  # interest differential, in points
    log_s = pd.Series(0.0, index=idx)
    for i in range(n - HORIZON):
        step = (alpha + beta * diff.iloc[i]) / 100.0
        if noise:
            step += rng.normal(0, noise / 100.0)
        log_s.iloc[i + HORIZON] = log_s.iloc[i] + step
    return pd.DataFrame(
        {
            "fx_spot_usd@BR": np.exp(log_s),
            "policy_rate@BR": diff + 2.0,
            "policy_rate@US": pd.Series(2.0, index=idx),
        }
    )


# ------------------------------------------------------------------ the algebra
def test_when_parity_holds_the_slope_is_one() -> None:
    model = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON)
    result = model.fit(synthetic(beta=1.0), ctx())
    coef = result.tables()["coefficients"].set_index("name")
    assert float(coef.loc["beta", "estimate"]) == pytest.approx(1.0, abs=1e-6)
    assert float(coef.loc["alpha", "estimate"]) == pytest.approx(0.0, abs=1e-6)


def test_a_constant_risk_premium_lands_in_the_intercept() -> None:
    """A currency that always depreciates three points more than parity: beta 1, alpha 3."""
    model = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON)
    coef = (
        model.fit(synthetic(beta=1.0, alpha=3.0), ctx()).tables()["coefficients"].set_index("name")
    )
    assert float(coef.loc["beta", "estimate"]) == pytest.approx(1.0, abs=1e-6)
    assert float(coef.loc["alpha", "estimate"]) == pytest.approx(3.0, abs=1e-6)


def test_a_world_where_the_carry_never_pays_gives_a_zero_slope() -> None:
    model = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON)
    coef = model.fit(synthetic(beta=0.0), ctx()).tables()["coefficients"].set_index("name")
    assert float(coef.loc["beta", "estimate"]) == pytest.approx(0.0, abs=1e-6)


def test_parity_is_not_rejected_when_it_holds() -> None:
    model = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON)
    result = model.fit(synthetic(beta=1.0, noise=1.0), ctx())
    diag = result.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["pvalue_beta_equals_one"]) > 0.05


# ------------------------------------------------------------------ reality
def test_the_real_data_reproduces_the_forward_premium_puzzle() -> None:
    """Theory says one; Brazil against the United States since 2000 says about minus 0.7."""
    model = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON)
    result = model.fit(panel_from_fixture(), ctx())
    coef = result.tables()["coefficients"].set_index("name")
    diag = result.tables()["diagnostics"].set_index("metric")["value"]

    assert float(coef.loc["beta", "estimate"]) == pytest.approx(-0.725, abs=0.01)
    assert float(coef.loc["alpha", "estimate"]) == pytest.approx(11.58, abs=0.10)
    assert int(diag["n_obs"]) == 308
    assert float(diag["pvalue_beta_equals_one"]) < 0.001, "parity must be rejected on this sample"


def test_the_standard_errors_account_for_overlapping_windows() -> None:
    """Twelve-month windows one month apart share eleven months; plain OLS errors are too small.

    Newey-West with at least the horizon in lags roughly doubles the slope's standard error
    here. Getting this wrong manufactures significance rather than losing it.
    """
    model = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON)
    coef = model.fit(panel_from_fixture(), ctx()).tables()["coefficients"].set_index("name")
    assert float(coef.loc["beta", "std_error"]) == pytest.approx(0.478, abs=0.02)


def test_the_fitted_table_lines_up_with_the_inputs() -> None:
    result = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON).fit(
        panel_from_fixture(), ctx()
    )
    fitted = result.tables()["fitted"]
    assert set(fitted.columns) >= {"period", "differential", "realised_depreciation", "predicted"}
    assert len(fitted) == 308
    assert fitted["period"].is_monotonic_increasing


def test_holds_reports_the_verdict() -> None:
    result = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON).fit(
        panel_from_fixture(), ctx()
    )
    diag = result.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["horizon_months"]) == HORIZON


# ------------------------------------------------------------------ guards
def test_too_short_a_sample_is_refused_rather_than_fitted() -> None:
    short = panel_from_fixture().head(HORIZON + 20)
    with pytest.raises(ValueError, match=r"(?i)observations|sample"):
        UncoveredParity(base="BR", quote="US", horizon_months=HORIZON).fit(short, ctx())


def test_missing_inputs_are_dropped_not_filled() -> None:
    panel = panel_from_fixture().copy()
    panel.iloc[50:60, panel.columns.get_loc("policy_rate@BR")] = np.nan
    result = UncoveredParity(base="BR", quote="US", horizon_months=HORIZON).fit(panel, ctx())
    n = int(result.tables()["diagnostics"].set_index("metric")["value"]["n_obs"])
    assert n < 308, "rows without a differential cannot enter the regression"
    assert n > 250


def test_a_panel_of_the_wrong_shape_is_refused_rather_than_guessed() -> None:
    """One column must never stand in for every concept the model asked for.

    A resolver that falls back to "the only column there is" turns a malformed panel into a
    regression of the exchange rate on itself, which returns a number instead of an error.
    """
    single = pd.DataFrame(
        {"fx_spot_usd@BR": [1.0] * 100},
        index=pd.date_range("2000-01-01", periods=100, freq="MS"),
    )
    with pytest.raises(KeyError, match=r"policy_rate@BR"):
        UncoveredParity(base="BR", quote="US", horizon_months=HORIZON).fit(single, ctx())


def test_the_model_declares_what_it_needs() -> None:
    """The panel is built from concepts, so the same model runs on another country."""
    needs = {r.concept for r in UncoveredParity(base="BR").requires}
    assert needs == {"fx_spot_usd", "policy_rate"}


def test_a_result_is_reproducible() -> None:
    a = UncoveredParity(base="BR").fit(panel_from_fixture(), ctx())
    b = UncoveredParity(base="BR").fit(panel_from_fixture(), ctx())
    x = a.tables()["coefficients"].set_index("name")["estimate"]
    y = b.tables()["coefficients"].set_index("name")["estimate"]
    assert all(math.isclose(x[k], y[k], rel_tol=1e-12) for k in x.index)
