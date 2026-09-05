"""Acceptance tests for WP-04e: impulse responses by local projection.

The package exists to answer a question the VAR cannot answer about itself: how much of its
impulse response is the data, and how much is the recursive structure it imposes on every
horizon at once? Jordà's estimator runs one regression per horizon and imposes nothing across
them, so where the two agree the finding is the data's and where they differ the difference is
the VAR's assumption.

The pinned results are therefore comparisons, not levels. Both estimators must find output
falling and both must show the price puzzle, because both are looking at the same sample through
a recursive ordering. Local projection is expected to give a deeper, earlier trough with wider
bands — that is its documented character, not a discrepancy to reconcile.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("econmodels.local_projections", reason="WP-04e not implemented yet")

from econmodels.base import PanelError, RunContext
from econmodels.local_projections import LocalProjections
from econmodels.var import VectorAutoregression

FIX = Path(__file__).parent / "fixtures" / "analysis" / "us_quarterly_var.csv"
SAMPLE_END = "2019-10-01"


def ctx(asof: str = "2026-09-05") -> RunContext:
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


def path_of(result, response: str) -> pd.Series:
    t = result.tables()["irf"]
    return t[t["response"] == response].set_index("horizon")["value"].sort_index()


def errors_of(result, response: str) -> pd.Series:
    t = result.tables()["irf"]
    return t[t["response"] == response].set_index("horizon")["std_error"].sort_index()


@pytest.fixture(scope="module")
def fitted():
    return LocalProjections(entity="US", horizon=20, lags=4).fit(us_panel(), ctx())


# ------------------------------------------------------------------ the estimator's own shape
def test_the_response_starts_at_zero_for_the_variables_that_cannot_jump() -> None:
    """A cumulative response is measured from the period of the shock, so horizon zero is zero."""
    r = LocalProjections(entity="US", horizon=8, lags=4).fit(us_panel(), ctx())
    assert path_of(r, "output").loc[0] == pytest.approx(0.0, abs=1e-9)
    assert path_of(r, "inflation").loc[0] == pytest.approx(0.0, abs=1e-9)


def test_one_regression_per_horizon_and_it_says_so(fitted) -> None:
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    assert int(diag["horizon"]) == 20
    assert "regressions" in diag.index
    assert int(diag["regressions"]) >= 20


def test_the_bands_widen_with_the_horizon(fitted) -> None:
    """The known character of the estimator: nothing ties the horizons together, so uncertainty
    accumulates instead of being smoothed by a companion matrix."""
    errors = errors_of(fitted, "output")
    assert errors.loc[16] > errors.loc[2] > 0


def test_the_sample_shrinks_by_one_observation_per_horizon(fitted) -> None:
    t = fitted.tables()["irf"]
    counts = t[t["response"] == "output"].set_index("horizon")["n_obs"]
    assert counts.loc[0] > counts.loc[20]
    assert counts.loc[0] - counts.loc[20] == pytest.approx(20, abs=1)


def test_the_errors_account_for_the_overlap_the_estimator_creates(fitted) -> None:
    """Successive horizons share observations by construction, so the errors must be corrected."""
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    assert str(diag["cov"]).lower() in {"hac", "newey_west", "newey-west"}


# ------------------------------------------------------------------ the pinned economics
def test_a_contractionary_shock_lowers_output(fitted) -> None:
    """1961Q1 to 2019Q4, four lags of controls: the trough is about one per cent."""
    output = path_of(fitted, "output")
    assert output.min() < -0.6, f"trough {output.min():.4f} is too shallow"
    assert 6 <= int(output.idxmin()) <= 16, "the trough should arrive between one and four years"


def test_the_price_puzzle_is_here_too(fitted) -> None:
    """It is not an artefact of the vector autoregression's cross-horizon structure: an
    estimator that imposes nothing across horizons finds it on the same sample."""
    first_year = path_of(fitted, "inflation").loc[1:4]
    assert first_year.max() > 0.35, (
        f"peak inflation response of {first_year.max():.4f} in the first year"
    )


def test_inflation_turns_negative_once_the_horizon_is_long_enough(fitted) -> None:
    assert path_of(fitted, "inflation").loc[12:20].min() < 0


# ------------------------------------------------------------------ against the other estimator
def test_the_two_estimators_agree_on_the_sign_of_the_output_response() -> None:
    """Where they agree, the finding belongs to the data rather than to either method."""
    lp = LocalProjections(entity="US", horizon=20, lags=4).fit(us_panel(), ctx())
    var = VectorAutoregression(entity="US", lags=4, horizon=20).fit(us_panel(), ctx())
    var_output = (
        var.tables()["irf"]
        .query("shock == 'policy' and response == 'output'")
        .set_index("horizon")["value"]
    )
    lp_output = path_of(lp, "output")
    for horizon in (4, 8, 12, 16):
        assert np.sign(lp_output.loc[horizon]) == np.sign(var_output.loc[horizon]), (
            f"the estimators disagree on the sign at horizon {horizon}"
        )


def test_both_find_the_price_puzzle() -> None:
    lp = LocalProjections(entity="US", horizon=8, lags=4).fit(us_panel(), ctx())
    var = VectorAutoregression(entity="US", lags=4, horizon=8).fit(us_panel(), ctx())
    var_infl = (
        var.tables()["irf"]
        .query("shock == 'policy' and response == 'inflation'")
        .set_index("horizon")["value"]
    )
    assert path_of(lp, "inflation").loc[1:4].max() > 0
    assert var_infl.loc[1:4].max() > 0


def test_local_projection_gives_the_deeper_trough() -> None:
    """Documented character rather than a discrepancy: the estimator is less restricted, so it
    tracks the sample more closely and pays for it in width."""
    lp = LocalProjections(entity="US", horizon=20, lags=4).fit(us_panel(), ctx())
    var = VectorAutoregression(entity="US", lags=4, horizon=20).fit(us_panel(), ctx())
    var_trough = (
        var.tables()["irf"].query("shock == 'policy' and response == 'output'")["value"].min()
    )
    assert path_of(lp, "output").min() < var_trough


# ------------------------------------------------------------------ refusals and portability
def test_a_monthly_panel_is_refused_before_any_arithmetic() -> None:
    panel = us_panel()
    panel.index = pd.date_range("1960-01-01", periods=len(panel), freq="MS")
    with pytest.raises(PanelError):
        LocalProjections(entity="US").fit(panel, ctx())


def test_a_missing_concept_is_named(fitted) -> None:
    with pytest.raises(PanelError, match="gdp_real@US"):
        LocalProjections(entity="US").fit(us_panel().drop(columns=["gdp_real@US"]), ctx())


def test_too_short_a_sample_for_the_horizon_is_refused() -> None:
    with pytest.raises(ValueError, match=r"(?i)observations|horizon|sample"):
        LocalProjections(entity="US", horizon=20, lags=4).fit(us_panel().head(20), ctx())


def test_the_model_asks_for_concepts_so_it_runs_on_any_country() -> None:
    needs = {r.concept for r in LocalProjections(entity="BR").requires}
    assert needs == {"cpi_headline_index", "gdp_real", "policy_rate"}


def test_two_runs_of_the_same_specification_agree() -> None:
    a = LocalProjections(entity="US", horizon=8, lags=4).fit(us_panel(), ctx())
    b = LocalProjections(entity="US", horizon=8, lags=4).fit(us_panel(), ctx())
    assert np.allclose(
        a.tables()["irf"]["value"].to_numpy(),
        b.tables()["irf"]["value"].to_numpy(),
        atol=1e-12,
    )
