"""Acceptance tests for WP-05a: the mixed-frequency dynamic factor nowcast.

Two of these tests exist because of how the earlier packages went wrong.

The first is the benchmark test. My acceptance test for the Phillips curve demanded that the
Bank's specification beat a margin I had measured on a cruder one, and the Bank's specification
lost. The fix was to measure rather than to assume, and it applies here with more force: over
2018-2025 this model cuts the error against the unconditional mean by more than half, and in the
calm years since 2022 it loses to that same mean. So the gate is the full sample, where the
advantage is large and real, and the calm-years figure is asserted to be *worse* — because that
is what it is, and a test that quietly passed either way would be measuring nothing.

The second is the out-of-sample test. Everything in phase five rests on a backtest not seeing
the future, and the way that fails is silent: a number that looks good because it was told the
answer. The cutoff itself is applied by `get_panel(asof=...)` and guarded in `test_vintages.py`;
what belongs here is the half the model owns, which is that a quarter it reports as unobserved
really was estimated without its own target value.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("econmodels.dfm", reason="WP-05a not implemented yet")

from econmodels.base import PanelError, RunContext
from econmodels.dfm import DfmError, DynamicFactorNowcast, seasonal_share

FIX = Path(__file__).parent / "fixtures" / "analysis" / "us_monthly_dfm.csv"


def ctx(asof: str = "2026-09-05", seed: int = 0, kind: str = "mixed") -> RunContext:
    return RunContext(asof=dt.date.fromisoformat(asof), seed=seed, vintage_kind=kind)


def full_panel() -> pd.DataFrame:
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    return raw.add_suffix("@US")


#: Days after a quarter ends before the first estimate of GDP exists. The advance estimate lands
#: about a month later, and the number only has to be roughly right: what it must not be is zero.
GDP_LAG_DAYS = 30


def visible_through(month: str) -> pd.DataFrame:
    """The panel as it would have looked at the end of ``month``.

    Cutting the rows is not enough, and getting that wrong invalidated every backtest number in
    the first version of this package. A quarterly series sits on the grid at the month the
    quarter **starts** -- 2018-01-01 carries 2018Q1 -- so truncating at March 2018 keeps a figure
    the Bureau does not publish until late April. The backtest then reported an in-sample fitted
    value for the quarter it claimed to be nowcasting, and compared it against an out-of-sample
    mean. Found by an adversarial review, not by me.

    So the target is also blanked wherever the quarter had not yet been published: it counts as
    known only once the quarter has ended and the lag has passed. The monthly indicators are
    still treated as equally timely, which is a simplification; the real per-series lag is
    exercised against the store in `test_vintages.py`.
    """
    panel = full_panel().loc[:month].copy()
    asof = pd.Timestamp(month) + pd.offsets.MonthEnd(0)
    quarter_end = pd.PeriodIndex(panel.index, freq="Q").to_timestamp(how="end").normalize()
    published = quarter_end + pd.Timedelta(days=GDP_LAG_DAYS)
    panel.loc[published > asof, "gdp_real@US"] = np.nan
    return panel


def fit(panel: pd.DataFrame, **kwargs):
    return DynamicFactorNowcast(entity="US", sample_start="1992-02-01", **kwargs).fit(panel, ctx())


@pytest.fixture(scope="module")
def fitted():
    return fit(full_panel())


def nowcast_for(result, quarter: str) -> float:
    table = result.tables()["nowcast"].set_index("quarter")
    return float(table.loc[quarter, "value"])


# ------------------------------------------------------------------ the ragged edge
def test_a_quarter_with_no_published_target_still_gets_a_number(fitted) -> None:
    """The whole point. A model needing a rectangle would have nothing to say here."""
    table = fitted.tables()["nowcast"]
    pending = table[~table["is_observed"]]
    assert not pending.empty, "the fixture should end inside an unpublished quarter"
    assert pending["value"].notna().all()
    assert pending["n_visible"].iloc[-1] > 0, "and it should be reading something"


def test_only_the_current_quarter_is_a_pending_nowcast(fitted) -> None:
    """Found by a live run, not by a test, which is why it is now a test.

    The filter also produces values for the quarters *before* the target's history starts, and
    those arrived flagged only as "not observed" — the same flag the current quarter carries. A
    reader taking every unobserved row got three estimates where there is one, and one of them
    had no monthly observation behind it at all.
    """
    table = fitted.tables()["nowcast"]
    assert set(table["status"]) <= {"observed", "backfill", "gap", "pending"}
    pending = table[table["status"] == "pending"]
    assert len(pending) == 1, "exactly one quarter is genuinely being nowcast"
    assert pending.iloc[0]["quarter"] == table["quarter"].max()
    assert not pending.iloc[0]["is_observed"]


def test_a_quarter_before_the_target_history_is_not_called_a_nowcast() -> None:
    panel = full_panel()
    late = panel.copy()
    late.loc[late.index < pd.Timestamp("2000-01-01"), "gdp_real@US"] = np.nan
    table = fit(late).tables()["nowcast"]
    early = table[table["quarter"] < "2000Q1"]
    assert not early.empty
    assert set(early["status"]) == {"backfill"}


def test_the_incomplete_bottom_of_the_panel_is_reported(fitted) -> None:
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    assert int(diag["ragged_edge"]) >= 1
    assert diag["vintage_kind"] == "mixed"
    assert diag["asof"] == "2026-09-05"


def test_the_factor_is_monthly_and_the_target_is_quarterly(fitted) -> None:
    tables = fitted.tables()
    assert len(tables["factor"]) > 3 * len(tables["nowcast"]) - 5
    quarters = pd.PeriodIndex(tables["nowcast"]["quarter"], freq="Q")
    assert quarters.is_monotonic_increasing and quarters.is_unique


def test_every_input_declares_how_it_was_made_stationary(fitted) -> None:
    loadings = fitted.tables()["loadings"]
    assert set(loadings["transform"]) <= {"logdiff", "diff"}
    assert "gdp_real" in set(loadings["variable"])


# ------------------------------------------------------------------ genuinely out of sample
def test_an_unobserved_quarter_was_estimated_without_its_own_target() -> None:
    """The half of the guarantee this model owns.

    Erasing a quarter's target value must change that quarter's estimate, **and** the estimate
    that comes back must not be the erased value. The weaker half alone -- that deleting the
    answer changes the output -- is what an adversarial review called tautological, and it was
    right: a model that simply echoed the target would satisfy it.
    """
    panel = visible_through("2024-09")  # 2024Q2 ended in June and is published by September
    blinded = panel.copy()
    blinded.loc[blinded.index >= pd.Timestamp("2024-04-01"), "gdp_real@US"] = np.nan

    seeing = fit(panel)
    blind = fit(blinded)
    assert bool(seeing.tables()["nowcast"].set_index("quarter").loc["2024Q2", "is_observed"])
    assert not bool(blind.tables()["nowcast"].set_index("quarter").loc["2024Q2", "is_observed"])

    truth = 100.0 * np.log(full_panel()["gdp_real@US"].dropna()).diff()
    truth.index = pd.PeriodIndex(truth.index, freq="Q")
    realised = float(truth[pd.Period("2024Q2")])
    estimate = nowcast_for(blind, "2024Q2")
    assert estimate != nowcast_for(seeing, "2024Q2")
    assert abs(estimate - realised) > 1e-6, "a blinded quarter must not come back as its own value"


def test_the_indicators_still_carry_the_blinded_quarter() -> None:
    """And the estimate must not collapse to the sample mean when the target is hidden: the
    monthly block is what a nowcast is for."""
    panel = visible_through("2024-09")
    blinded = panel.copy()
    blinded.loc[blinded.index >= pd.Timestamp("2024-04-01"), "gdp_real@US"] = np.nan
    stripped = blinded.copy()
    stripped.loc[stripped.index >= pd.Timestamp("2024-04-01"), "employment@US"] = np.nan

    assert nowcast_for(fit(blinded), "2024Q2") != nowcast_for(fit(stripped), "2024Q2")


def test_a_later_cutoff_changes_the_answer() -> None:
    """The mirror of the test above: if truncation changed nothing, nothing would be read."""
    early = nowcast_for(fit(visible_through("2024-02")), "2024Q1")
    late = nowcast_for(fit(visible_through("2024-03")), "2024Q1")
    assert early != late


# ------------------------------------------------------------------ does it forecast
def _backtest(quarters: pd.PeriodIndex, month_offset: int) -> pd.DataFrame:
    truth = full_panel()["gdp_real@US"].dropna()
    truth = 100.0 * np.log(truth).diff()
    truth.index = pd.PeriodIndex(truth.index, freq="Q")

    rows = []
    for quarter in quarters:
        cutoff = str(quarter.asfreq("M", "start") + month_offset)
        panel = visible_through(cutoff)
        result = fit(panel)
        history = panel["gdp_real@US"].dropna()
        history = (100.0 * np.log(history).diff()).dropna()
        rows.append(
            {
                "quarter": str(quarter),
                "nowcast": nowcast_for(result, str(quarter)),
                "mean": float(history.mean()),
                "truth": float(truth[quarter]),
            }
        )
    return pd.DataFrame(rows)


def _rmse(frame: pd.DataFrame, column: str) -> float:
    return float(np.sqrt(np.mean((frame[column] - frame["truth"]) ** 2)))


@pytest.fixture(scope="module")
def backtest() -> pd.DataFrame:
    return _backtest(pd.period_range("2018Q1", "2025Q4", freq="Q"), month_offset=2)


def test_over_the_full_sample_the_factor_beats_the_unconditional_mean(backtest) -> None:
    """Where a common shock moves everything at once, a common factor is the right object."""
    assert _rmse(backtest, "nowcast") < 0.6 * _rmse(backtest, "mean")


def test_and_in_the_calm_years_it_loses(backtest) -> None:
    """Asserted rather than hidden. The advantage above is a statement about a crisis, and a
    write-up quoting the first number without this one is quoting 2020 as a capability.

    The subsample matters, and choosing it took two readings. Excluding 2020 alone is not a calm
    sample -- 2021 is the recovery, driven by the same shock, and the model still wins there. It
    is also not stable: on this fixture, where every indicator is truncated on the same day, the
    excluding-2020 aggregate has the model narrowly ahead (0.457 against 0.473), while against
    the store with real per-series publication lags it is narrowly behind (0.510 against 0.482).
    A claim that flips sign with the truncation rule is not a claim. 2022-2025 is behind on both.
    """
    calm = backtest[backtest["quarter"] >= "2022"]
    assert _rmse(calm, "nowcast") > _rmse(calm, "mean")


def test_the_error_falls_as_the_quarter_fills() -> None:
    """Information accumulation: the property that justifies a state space over a regression."""
    quarters = pd.period_range("2018Q1", "2020Q4", freq="Q")
    early = _rmse(_backtest(quarters, month_offset=0), "nowcast")
    late = _rmse(_backtest(quarters, month_offset=2), "nowcast")
    assert late < early, f"month 3 ({late:.3f}) should beat month 1 ({early:.3f})"


# ------------------------------------------------------------------ reproducibility and refusals
def test_the_same_panel_gives_the_same_answer(fitted) -> None:
    again = fit(full_panel())
    pd.testing.assert_frame_equal(fitted.tables()["nowcast"], again.tables()["nowcast"])


def test_a_quarterly_panel_is_refused_before_any_arithmetic() -> None:
    panel = full_panel()
    panel.index = pd.date_range("1992-01-01", periods=len(panel), freq="QS")
    with pytest.raises(PanelError):
        fit(panel)


def test_a_concept_with_no_declared_transform_is_refused_by_name() -> None:
    panel = full_panel().rename(columns={"wages@US": "mystery_index@US"})
    with pytest.raises(DfmError, match="mystery_index"):
        DynamicFactorNowcast(
            entity="US",
            indicators=("employment", "mystery_index"),
            sample_start="1992-02-01",
        ).fit(panel, ctx())


def test_a_panel_without_the_target_says_so() -> None:
    panel = full_panel()
    panel["gdp_real@US"] = np.nan
    with pytest.raises(DfmError, match="nothing to nowcast"):
        fit(panel)


def test_too_little_quarterly_history_is_refused() -> None:
    with pytest.raises(DfmError, match="quarterly history"):
        DynamicFactorNowcast(entity="US", sample_start="2023-01-01").fit(full_panel(), ctx())


def test_the_model_asks_for_concepts_so_it_runs_on_any_country() -> None:
    needs = {r.concept for r in DynamicFactorNowcast(entity="BR").requires}
    assert "gdp_real" in needs and "industrial_production" in needs


# ------------------------------------------------------------------ the seasonal trap
def test_an_unadjusted_target_is_refused_by_name() -> None:
    """Found by running Brazil, where the catalog says adjusted and the data says otherwise.

    Its GDP growth is 55% explained by which quarter of the year it is, and the nowcast the
    model produced for a third quarter was, underneath, the observation that third quarters are
    up. That is a confident number with nothing behind it, which is worse than no number.
    """
    panel = full_panel()
    seasonal = panel.copy()
    quarter = panel.index.quarter
    bump = pd.Series(np.where(quarter == 3, 1.06, 0.98), index=panel.index)
    seasonal["gdp_real@US"] = panel["gdp_real@US"] * bump

    with pytest.raises(DfmError, match=r"not seasonally adjusted"):
        fit(seasonal)


def test_the_seasonal_refusal_can_be_overridden_deliberately() -> None:
    panel = full_panel()
    quarter = panel.index.quarter
    panel["gdp_real@US"] = panel["gdp_real@US"] * pd.Series(
        np.where(quarter == 3, 1.06, 0.98), index=panel.index
    )
    result = fit(panel, allow_seasonal=True)
    diag = result.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["seasonal_share"]) > 0.25


def test_an_adjusted_target_passes_and_the_share_is_reported(fitted) -> None:
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["seasonal_share"]) < 0.25


def test_the_seasonal_share_separates_the_two_countries_by_a_mile() -> None:
    """The numbers the threshold was chosen from, so a later tweak has to face them."""
    adjusted = pd.Series(
        [0.5, 0.6, 0.4, 0.55] * 20,
        index=pd.period_range("1990Q1", periods=80, freq="Q"),
    )
    unadjusted = pd.Series(
        [2.3, -2.9, 0.8, 2.2] * 20,
        index=pd.period_range("1990Q1", periods=80, freq="Q"),
    )
    assert seasonal_share(adjusted) > 0.9  # a pure repeating pattern is all calendar
    assert seasonal_share(unadjusted) > 0.9
    noisy = pd.Series(
        np.random.default_rng(0).normal(size=80),
        index=pd.period_range("1990Q1", periods=80, freq="Q"),
    )
    assert seasonal_share(noisy) < 0.25


# ------------------------------------------------------------------ found by adversarial review
def test_a_hole_in_the_target_does_not_become_one_quarters_growth() -> None:
    """Dropping the empty quarters and differencing what is left computes growth straight across
    the hole and books all of it to the quarter after it."""
    panel = full_panel()
    holed = panel.copy()
    holed.loc[holed.index == pd.Timestamp("2024-04-01"), "gdp_real@US"] = np.nan

    intact = nowcast_for(fit(panel), "2024Q3")
    with_hole = nowcast_for(fit(holed), "2024Q3")
    # the 2024Q3 figure must still be about one quarter, not about two
    assert abs(with_hole - intact) < 1.0, (
        f"a single missing quarter moved the next one from {intact:+.3f} to {with_hole:+.3f}"
    )


def test_a_panel_ending_on_a_published_quarter_still_nowcasts_the_next_one() -> None:
    """A caller always asks about the quarter after the last one known. A panel that stops on the
    closing month of a published quarter used to answer with that quarter, marked observed."""
    panel = full_panel().loc[:"2024-09"]
    panel.loc[panel.index > pd.Timestamp("2024-07-01"), "gdp_real@US"] = np.nan
    table = fit(panel).tables()["nowcast"]
    pending = table[table["status"] == "pending"]
    assert len(pending) == 1
    assert pending.iloc[0]["quarter"] == "2024Q4"
