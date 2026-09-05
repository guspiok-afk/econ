"""Acceptance tests for WP-04c: the Brazilian Phillips curve.

These pin no slope, and that is the whole design. Three independent primary results establish
that an aggregate time-series regression does not identify the Phillips slope — six hundred
thousand specifications dispersed symmetrically around zero, ordinary least squares converging on
the targeting rule with the opposite sign, and the wrong sign reproduced inside a state panel
without time fixed effects. Fixing a number here would enshrine noise.

What can be demanded instead is everything that is deterministic: the arithmetic of the data, the
verticality restriction holding by construction, orderings the Banco Central publishes, and
performance against benchmarks that need no model at all.

A slack coefficient with the wrong sign in one cell of the specification grid is the modal
expected result and is not a defect. In every cell it is an inverted sign convention, which is.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Each of these arrives in a pull request of its own, so the file has to survive a base that has
# none of them: a bare import would break collection instead of skipping.
pytest.importorskip("econmodels.specs", reason="WP-04c depends on the specification loader")
pytest.importorskip("econmodels.phillips", reason="WP-04c not implemented yet")

from econmodels.phillips import PhillipsCurve

from econmodels.base import PanelError, RunContext
from econmodels.specs import load_specs

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "analysis" / "br_phillips_trimestral.csv"


def ctx(asof: str = "2026-09-05") -> RunContext:
    return RunContext(asof=dt.date.fromisoformat(asof), seed=0)


@pytest.fixture(scope="module")
def specs():
    return load_specs(ROOT / "specs", model_id="phillips")


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    return raw.rename(columns={c: f"{c}@BR" for c in raw.columns})


def table(result, name: str) -> pd.DataFrame:
    return result.tables()[name]


def coef(result) -> pd.Series:
    return table(result, "coefficients").set_index("name")["estimate"]


def diag(result) -> pd.Series:
    return table(result, "diagnostics").set_index("metric")["value"]


@pytest.fixture(scope="module")
def bank(specs, panel):
    return PhillipsCurve(specs["br_bcb_small_scale"]).fit(panel, ctx())


# ------------------------------------------------------------------ the data, exactly
def test_the_dependent_is_the_one_the_specification_names(specs, panel) -> None:
    """The Bank explains free prices. Headline mixes in a quarter of the index that is set by
    institutional rule and does not respond to slack, and the attenuation is mechanical."""
    assert specs["br_bcb_small_scale"].dependent.concept == "cpi_free"
    fitted = table(PhillipsCurve(specs["br_bcb_small_scale"]).fit(panel, ctx()), "fitted")
    expected = ((1 + panel["cpi_free@BR"] / 100) ** 4 - 1) * 100
    joined = fitted.set_index("period")["actual"].dropna()
    assert np.allclose(joined, expected.reindex(joined.index), atol=1e-9), (
        "the actual column must be the annualised quarterly rate of the declared concept"
    )


def test_the_sample_starts_where_the_specification_says(bank, specs) -> None:
    start = pd.Timestamp(specs["br_bcb_small_scale"].sample.start)
    assert table(bank, "fitted")["period"].min() >= start


def test_residuals_are_actual_minus_fitted(bank) -> None:
    f = table(bank, "fitted").dropna()
    assert (f["residual"] - (f["actual"] - f["fitted"])).abs().max() < 1e-9


# ------------------------------------------------------------------ the restriction
def test_verticality_holds_by_construction_not_by_luck(bank) -> None:
    """The Bank writes the expectations weight as one minus the rest. It is imposed, not tested."""
    total = float(diag(bank)["inflation_weights_sum"])
    assert abs(total - 1.0) < 1e-8, f"the inflation coefficients sum to {total}, not one"


def test_the_exchange_rate_stays_outside_the_unit_sum(bank, specs) -> None:
    over = [
        tuple(r.over) for r in specs["br_bcb_small_scale"].restrictions if r.kind == "sum_to_one"
    ]
    assert over, "the specification must carry the restriction"
    assert all("repasse" not in names for names in over)


def test_the_unrestricted_version_is_reported_as_a_diagnostic(bank) -> None:
    """Reported, never demanded: the Bank imposes it, so the Wald statistic is information."""
    assert "wald_verticality_pvalue" in diag(bank).index


def test_the_specification_travels_with_the_result(bank, specs) -> None:
    d = diag(bank)
    assert str(d["spec_id"]) == "br_bcb_small_scale"
    assert str(d["spec_hash"]) == specs["br_bcb_small_scale"].spec_hash


# ------------------------------------------------------------------ published orderings
def test_pass_through_is_smaller_for_free_prices_than_for_headline(specs, panel) -> None:
    """Administered prices pass more of the exchange rate through, not less: the Bank measures
    +1.65 against +0.72 points for a permanent ten per cent depreciation. Running the same code
    on the two dependents has to reproduce the ordering, and this is executable today."""
    free = PhillipsCurve(specs["br_bcb_small_scale"]).fit(panel, ctx())
    headline_spec = specs["br_bcb_small_scale"].model_copy(deep=True)
    headline_spec.dependent.concept = "cpi_headline"
    headline = PhillipsCurve(headline_spec).fit(panel, ctx())
    assert coef(free)["repasse"] < coef(headline)["repasse"], (
        "free prices must show less pass-through than headline"
    )


def test_pass_through_is_positive_and_of_a_plausible_size(bank) -> None:
    """A depreciation raises inflation. The magnitude is checked loosely on purpose: the Bank's
    published 0.011 is the residual after commodities in reais, and this one is the full
    pass-through, so the comparable figure is the ~0.06 of the local-projections box."""
    passthrough = float(coef(bank)["repasse"])
    assert 0.0 < passthrough < 0.3, f"pass-through of {passthrough:.4f} is not credible"


def test_expectations_carry_more_weight_than_a_single_lag(bank) -> None:
    c = coef(bank)
    assert c["expectativa"] > c["inercia_livres"], (
        "under an inflation-targeting regime the survey should dominate one quarter of inertia"
    )


# ------------------------------------------------------------------ does it beat doing nothing
def test_the_model_is_not_materially_worse_than_reading_the_survey(bank) -> None:
    """The honest bar. Measured margin is four per cent, which is itself the finding: the
    equation adds little to simply reading the Focus survey."""
    d = diag(bank)
    assert float(d["rmse_oos"]) <= 1.02 * float(d["rmse_oos_expectations"])


def test_the_model_beats_a_random_walk_with_room_to_spare(bank) -> None:
    d = diag(bank)
    assert float(d["rmse_oos"]) < 0.90 * float(d["rmse_oos_random_walk"])


def test_the_out_of_sample_exercise_is_long_enough_to_mean_something(bank) -> None:
    assert int(diag(bank)["n_oos"]) >= 40


# ------------------------------------------------------------------ the negative control
def test_the_exploratory_specification_reproduces_the_error_it_documents(specs, panel) -> None:
    """It is kept because it is wrong in a knowable way. If it stops being wrong, either the data
    changed or the implementation is not doing what the file says."""
    spec = specs["br_exploratoria_hp"]
    result = PhillipsCurve(spec).fit(panel, ctx())
    d = diag(result)
    assert not spec.restrictions
    assert float(d["inflation_weights_sum"]) > 1.2, (
        "without the restriction the inflation coefficients overshoot one; that is the point"
    )


def test_both_specifications_run_on_the_same_panel(specs, panel) -> None:
    """The use case the whole design exists for: two ways of estimating one model, compared."""
    results = {sid: PhillipsCurve(spec).fit(panel, ctx()) for sid, spec in specs.items()}
    assert len(results) >= 2
    assert len({str(diag(r)["spec_hash"]) for r in results.values()}) == len(results)


# ------------------------------------------------------------------ refusals
def test_a_monthly_panel_is_refused_before_any_arithmetic(specs, panel) -> None:
    """The defect that cost six points in a prescribed policy rate, in the package before this."""
    monthly = panel.copy()
    monthly.index = pd.date_range("2004-01-01", periods=len(panel), freq="MS")
    with pytest.raises(PanelError):
        PhillipsCurve(specs["br_bcb_small_scale"]).fit(monthly, ctx())


def test_a_panel_missing_a_declared_concept_is_refused(specs, panel) -> None:
    with pytest.raises(PanelError, match="fx_spot_usd@BR"):
        PhillipsCurve(specs["br_bcb_small_scale"]).fit(
            panel.drop(columns=["fx_spot_usd@BR"]), ctx()
        )


def test_too_short_a_sample_is_refused_rather_than_fitted(specs, panel) -> None:
    with pytest.raises(ValueError, match=r"(?i)observations|sample"):
        PhillipsCurve(specs["br_bcb_small_scale"]).fit(panel.head(8), ctx())


def test_the_model_declares_what_the_specification_reads(specs) -> None:
    model = PhillipsCurve(specs["br_bcb_small_scale"])
    declared = {(r.concept, r.entity or "BR") for r in model.requires}
    assert declared == set(specs["br_bcb_small_scale"].concepts())
    assert all(r.freq == "Q" for r in model.requires)
