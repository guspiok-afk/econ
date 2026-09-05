"""Acceptance tests for WP-04f: the sign-restricted VAR.

The recursive VAR and the local projections both put inflation *up* after a tightening on this
sample. That is the price puzzle, and this package is the answer to it: instead of ordering the
variables and accepting whatever falls out, refuse any identification that does not behave like
monetary policy.

The tests are written around one trap. For the horizons where a sign is imposed, finding that
sign proves nothing — it was assumed. The informative claim is that inflation *stays* negative
well past the restricted window, which nothing forced. A test that only checked the restricted
horizons would be checking the code's arithmetic, not the data.

The second thing they enforce is that the answer is a set. Sign restrictions identify a region,
not a point, and reporting the median without the band turns an admission of ignorance into a
false estimate.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("econmodels.sign_restrictions", reason="WP-04f not implemented yet")

from econmodels.base import PanelError, RunContext
from econmodels.sign_restrictions import SignRestrictedVAR
from econmodels.var import VectorAutoregression

FIX = Path(__file__).parent / "fixtures" / "analysis" / "us_quarterly_var.csv"
RESTRICTED_THROUGH = 3


def ctx(asof: str = "2026-09-05", seed: int = 0) -> RunContext:
    return RunContext(asof=dt.date.fromisoformat(asof), seed=seed)


def us_panel(end: str | None = "2019-10-01") -> pd.DataFrame:
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


def band(result, response: str) -> pd.DataFrame:
    t = result.tables()["irf"]
    return t[t["response"] == response].set_index("horizon").sort_index()


@pytest.fixture(scope="module")
def fitted():
    return SignRestrictedVAR(
        entity="US", lags=4, horizon=20, restrict_through=RESTRICTED_THROUGH, draws=2000
    ).fit(us_panel(), ctx())


# ------------------------------------------------------------------ the answer is a set
def test_the_result_is_a_band_and_not_a_point(fitted) -> None:
    """Sign restrictions identify a region. A median without a band is a false estimate."""
    frame = band(fitted, "output")
    for column in ("median", "low", "high"):
        assert column in frame.columns, f"the impulse response table has no {column!r}"
    assert (frame["low"] <= frame["median"]).all()
    assert (frame["median"] <= frame["high"]).all()


def test_the_band_is_not_degenerate(fitted) -> None:
    frame = band(fitted, "output")
    assert (frame["high"] - frame["low"]).max() > 0.05, (
        "an identified set with no width is a point estimate wearing a band's clothes"
    )


def test_how_many_draws_survived_is_reported(fitted) -> None:
    """Two per cent on this sample. A reader who cannot see it cannot judge the answer."""
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    accepted = float(diag["accepted"])
    assert accepted > 0, "no rotation satisfied the restrictions"
    assert 0.0 < float(diag["acceptance_rate"]) < 1.0


def test_the_restrictions_travel_with_the_result(fitted) -> None:
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    assert int(diag["restrict_through"]) == RESTRICTED_THROUGH
    assert str(diag["identification"]) == "sign"


# ------------------------------------------------------------------ what was imposed
@pytest.mark.parametrize("response,direction", [("policy", 1), ("output", -1), ("inflation", -1)])
def test_the_imposed_signs_hold_where_they_were_imposed(fitted, response, direction) -> None:
    """This checks the arithmetic, not the data: these signs were assumed, not discovered."""
    frame = band(fitted, response).loc[:RESTRICTED_THROUGH]
    assert all(direction * value > 0 for value in frame["median"])


# ------------------------------------------------------------------ what was not imposed
def test_inflation_stays_negative_well_past_the_restricted_window(fitted) -> None:
    """The informative claim. Nothing forces the sign after horizon three, and the puzzle does
    not come back — which is what makes the identification worth the trouble."""
    beyond = band(fitted, "inflation").loc[RESTRICTED_THROUGH + 1 :]["median"]
    assert beyond.max() < 0.0, (
        f"inflation returns to {beyond.max():+.4f} once the restriction stops binding"
    )


def test_output_stays_below_trend_past_the_restricted_window(fitted) -> None:
    beyond = band(fitted, "output").loc[RESTRICTED_THROUGH + 1 :]["median"]
    assert beyond.max() < 0.0


def test_the_rate_response_dies_out(fitted) -> None:
    """A monetary shock that never fades is not a shock, it is a regime."""
    policy = band(fitted, "policy")["median"]
    assert abs(policy.loc[20]) < abs(policy.loc[0])


# ------------------------------------------------------------------ against the recursive answer
def test_the_recursive_identification_shows_the_puzzle_and_this_one_does_not() -> None:
    """The package in one assertion: same data, same reduced form, different identification."""
    panel = us_panel()
    recursive = VectorAutoregression(entity="US", lags=4, horizon=20).fit(panel, ctx())
    restricted = SignRestrictedVAR(
        entity="US", lags=4, horizon=20, restrict_through=RESTRICTED_THROUGH, draws=2000
    ).fit(panel, ctx())

    puzzle = (
        recursive.tables()["irf"]
        .query("shock == 'policy' and response == 'inflation'")
        .set_index("horizon")["value"]
        .loc[1:4]
        .max()
    )
    assert puzzle > 0.25, "the recursive run should still show the puzzle"
    assert band(restricted, "inflation").loc[1:4]["median"].max() < 0


def test_both_agree_that_output_falls() -> None:
    """Where identification does not matter, the two must not disagree."""
    panel = us_panel()
    recursive = VectorAutoregression(entity="US", lags=4, horizon=20).fit(panel, ctx())
    restricted = SignRestrictedVAR(entity="US", lags=4, horizon=20, draws=2000).fit(panel, ctx())
    recursive_trough = (
        recursive.tables()["irf"].query("shock == 'policy' and response == 'output'")["value"].min()
    )
    assert recursive_trough < 0
    assert band(restricted, "output")["median"].min() < 0


# ------------------------------------------------------------------ reproducibility and refusals
def test_the_same_seed_gives_the_same_set(fitted) -> None:
    """Random rotations, so the seed in RunContext has to be the only source of variation."""
    again = SignRestrictedVAR(
        entity="US", lags=4, horizon=20, restrict_through=RESTRICTED_THROUGH, draws=2000
    ).fit(us_panel(), ctx())
    pd.testing.assert_frame_equal(
        fitted.tables()["irf"].reset_index(drop=True),
        again.tables()["irf"].reset_index(drop=True),
    )


def test_a_different_seed_gives_a_different_set() -> None:
    a = SignRestrictedVAR(entity="US", lags=4, horizon=8, draws=500).fit(us_panel(), ctx(seed=1))
    b = SignRestrictedVAR(entity="US", lags=4, horizon=8, draws=500).fit(us_panel(), ctx(seed=2))
    assert not a.tables()["irf"]["median"].equals(b.tables()["irf"]["median"])


def test_restrictions_nothing_can_satisfy_are_refused_rather_than_returned_empty() -> None:
    """Asking for a shock that raises the rate and raises output is a question, not a bug — but
    it must come back as a refusal and not as an empty table nobody notices."""
    with pytest.raises(ValueError, match=r"(?i)no rotation|accepted|satisfies"):
        SignRestrictedVAR(
            entity="US",
            lags=4,
            horizon=8,
            draws=200,
            signs={"policy": 1, "output": 1, "inflation": 1},
        ).fit(us_panel(), ctx())


def test_a_monthly_panel_is_refused_before_any_arithmetic() -> None:
    panel = us_panel()
    panel.index = pd.date_range("1960-01-01", periods=len(panel), freq="MS")
    with pytest.raises(PanelError):
        SignRestrictedVAR(entity="US").fit(panel, ctx())


def test_the_model_asks_for_concepts_so_it_runs_on_any_country() -> None:
    needs = {r.concept for r in SignRestrictedVAR(entity="BR").requires}
    assert needs == {"cpi_headline_index", "gdp_real", "policy_rate"}
