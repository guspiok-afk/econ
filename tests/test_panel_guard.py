"""The seam between a model and the panel it was handed.

Two of the three models written so far shipped a resolver that guessed rather than refused, and
both would have answered a malformed panel with a plausible number. One fell back to "the only
column there is"; the other matched by prefix and ignored the entity, so a two-country panel
answers with whichever column came first.

The frequency half is worse, because it fails on the panel `api.get_panel` returns by *default*.
Every model here shifts by row — `shift(4)` for a four-quarter change — and that is only a
four-quarter change when the index really is quarterly. The price index is monthly in both
countries, so the default panel is monthly, and a four-row shift becomes a four-month change
reported as annual: six percentage points of error in a prescribed policy rate, silently.

`ConceptRequest(freq="Q")` declared the need all along. Nothing read it. These tests are what
make the declaration mean something.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from econmodels.base import (
    ConceptRequest,
    PanelError,
    RunContext,
    check_frequency,
    column_for,
    panel_for,
    series_for,
)


def quarterly(n: int = 40, start: str = "2000-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="QS")


def panel(index: pd.DatetimeIndex, **columns: float) -> pd.DataFrame:
    return pd.DataFrame({k: np.arange(len(index), dtype=float) for k in columns}, index=index)


class Model:
    """The smallest thing that satisfies the protocol's shape."""

    model_id = "toy"
    model_version = "1"

    def __init__(self, entity: str = "US", requires=()) -> None:
        self.entity = entity
        self.requires = requires

    def fit(self, panel, ctx):  # pragma: no cover - never called
        raise NotImplementedError


# ------------------------------------------------------------------ resolving a column
def test_the_documented_name_resolves() -> None:
    p = panel(quarterly(), **{"gdp_real@US": 1.0})
    assert column_for(p, "gdp_real", "US") == "gdp_real@US"


def test_a_single_column_panel_is_not_an_excuse_to_guess() -> None:
    """The fallback that shipped in the parity model: one column, so it must be the right one."""
    p = panel(quarterly(), **{"fx_spot_usd@BR": 1.0})
    with pytest.raises(PanelError, match="policy_rate@BR"):
        column_for(p, "policy_rate", "BR")


def test_the_entity_is_never_ignored() -> None:
    """The fallback that shipped in the VAR: match by prefix, answer with the wrong country."""
    p = panel(quarterly(), **{"policy_rate@BR": 1.0, "policy_rate@US": 1.0})
    assert column_for(p, "policy_rate", "US") == "policy_rate@US"
    with pytest.raises(PanelError):
        column_for(p, "policy_rate", "AR")


def test_the_refusal_names_what_it_did_find() -> None:
    p = panel(quarterly(), **{"gdp_real@US": 1.0, "policy_rate@US": 1.0})
    with pytest.raises(PanelError, match=r"gdp_real@US.*policy_rate@US"):
        column_for(p, "cpi_headline_index", "US")


def test_a_series_comes_back_as_floats() -> None:
    p = pd.DataFrame({"gdp_real@US": ["1", "2", "3"]}, index=quarterly(3))
    assert series_for(p, "gdp_real", "US").tolist() == [1.0, 2.0, 3.0]


# ------------------------------------------------------------------ the frequency
def test_a_quarterly_panel_passes_a_quarterly_check() -> None:
    check_frequency(panel(quarterly(), **{"x@US": 1.0}), "Q")


def test_a_monthly_panel_is_refused_where_quarterly_was_declared() -> None:
    """The defect that reached a merged pull request, and cost six points in a policy rate."""
    monthly = pd.date_range("2000-01-01", periods=60, freq="MS")
    with pytest.raises(PanelError, match=r"not Q"):
        check_frequency(panel(monthly, **{"x@US": 1.0}), "Q")


def test_a_hole_in_the_grid_is_refused() -> None:
    """A shift by row is not a shift by period across a hole."""
    index = quarterly(40).delete(10)
    with pytest.raises(PanelError, match="hole"):
        check_frequency(panel(index, **{"x@US": 1.0}), "Q")


def test_the_refusal_says_how_to_get_the_right_panel() -> None:
    monthly = pd.date_range("2000-01-01", periods=24, freq="MS")
    with pytest.raises(PanelError, match=r"freq='Q'"):
        check_frequency(panel(monthly, **{"x@US": 1.0}), "Q")


def test_a_plain_index_is_refused_before_anything_else() -> None:
    p = pd.DataFrame({"x@US": [1.0, 2.0]}, index=[dt.date(2000, 1, 1), dt.date(2000, 4, 1)])
    with pytest.raises(PanelError, match="DatetimeIndex"):
        check_frequency(p, "Q")


def test_daily_series_are_not_measured_against_a_calendar_grid() -> None:
    """Weekends and holidays are not holes, and pretending otherwise refuses every daily panel."""
    business = pd.date_range("2020-01-01", periods=60, freq="B")
    check_frequency(panel(business, **{"x@US": 1.0}), "D")
    check_frequency(panel(business, **{"x@US": 1.0}), "B")


def test_an_empty_panel_is_left_to_the_model_to_complain_about() -> None:
    check_frequency(pd.DataFrame(index=pd.DatetimeIndex([])), "Q")


# ------------------------------------------------------------------ requires, finally read
def test_the_declaration_is_enforced() -> None:
    model = Model(requires=(ConceptRequest("gdp_real", freq="Q"),))
    monthly = pd.date_range("2000-01-01", periods=36, freq="MS")
    with pytest.raises(PanelError, match=r"not Q"):
        panel_for(model, panel(monthly, **{"gdp_real@US": 1.0}))


def test_every_declared_concept_must_be_present() -> None:
    model = Model(requires=(ConceptRequest("gdp_real"), ConceptRequest("policy_rate")))
    with pytest.raises(PanelError, match="policy_rate@US"):
        panel_for(model, panel(quarterly(), **{"gdp_real@US": 1.0}))


def test_an_optional_concept_may_be_absent() -> None:
    """The seam the Phillips curve needs: no expectations series exists for the United States."""
    model = Model(
        requires=(
            ConceptRequest("cpi_headline_index"),
            ConceptRequest("inflation_expectations_12m", optional=True),
        )
    )
    out = panel_for(model, panel(quarterly(), **{"cpi_headline_index@US": 1.0}))
    assert list(out.columns) == ["cpi_headline_index@US"]


def test_a_request_may_name_its_own_entity() -> None:
    """Uncovered parity wants two concepts for Brazil and one for the United States."""
    model = Model(
        entity="BR",
        requires=(
            ConceptRequest("fx_spot_usd"),
            ConceptRequest("policy_rate"),
            ConceptRequest("policy_rate", entity="US"),
        ),
    )
    p = panel(
        quarterly(),
        **{"fx_spot_usd@BR": 1.0, "policy_rate@BR": 1.0, "policy_rate@US": 1.0},
    )
    panel_for(model, p)


def test_a_model_without_an_entity_is_told_to_pass_one() -> None:
    class Anonymous:
        model_id = "anon"
        model_version = "1"
        requires = (ConceptRequest("gdp_real"),)

        def fit(self, panel, ctx):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(PanelError, match="which entity"):
        panel_for(Anonymous(), panel(quarterly(), **{"gdp_real@US": 1.0}))


def test_the_panel_comes_back_untouched() -> None:
    model = Model(requires=(ConceptRequest("gdp_real", freq="Q"),))
    p = panel(quarterly(), **{"gdp_real@US": 1.0})
    assert panel_for(model, p) is p


def test_the_context_is_not_needed_to_check_a_panel() -> None:
    """Deliberate: checking the shape must not require constructing a run."""
    ctx = RunContext(asof=dt.date(2026, 9, 5))
    assert ctx.seed == 0
