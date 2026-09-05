"""The Taylor rule -- a monetary policy rule for any country.

Taylor (1993) proposed a formula for the short-term interest rate that a central bank would
set if it weighted two things equally: how far inflation is from target, and how far the
economy is from its potential output.

::

    i_t = r* + pi_t + a_pi * (pi_t - pi*) + a_y * gap_t

**Design positions** (each is a parameter, so the next person can disagree without editing
the code):

Which inflation
    Year-over-year percentage change in the CPI headline index, computed as a
    four-quarter trailing change: ``(CPI[t] / CPI[t-4] - 1) * 100``.  Taylor used the
    GDP deflator; this base has the CPI index instead, which is close in level and is the
    series most analyses will already have.  The choice is recorded in every result's
    ``diagnostics`` table.

Which output gap
    Hodrick-Prescott filter on the log of real GDP, ``hp_lambda = 1600`` (the standard
    for quarterly data).  The gap is ``(GDP / potential - 1) * 100``, in percent of
    potential.  **The filter is two-sided**: it uses the full panel it receives, so the
    gap at a past date may revise when later data arrives.  This is stated in
    ``diagnostics`` (``gap_two_sided = True``) rather than hidden, because in a backtest
    the caller must re-run the filter on the as-of panel to avoid leakage.

Which neutral rate
    A parameter (``neutral_real_rate``, default 2.0) -- not a constant.  Two per cent is
    the paper's assumption and is defensible for the 1987-1992 sample; it is not
    defensible for 2010-2020, so the value is explicit and travels with every result.

References
    Taylor, John B. "Discretion versus policy rules in practice."
    Carnegie-Rochester conference series on public policy, vol. 39, 1993, pp. 195-214.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm

from econmodels.base import (
    ConceptRequest,
    Result,
    RunContext,
    TablesResult,
    panel_for,
    register,
    series_for,
)


def _hp_filter(y: np.ndarray, lamb: float) -> np.ndarray:
    """Hodrick-Prescott filter returning the trend component.

    Uses statsmodels' implementation, which is the standard two-sided filter.
    """
    _, trend = sm.tsa.filters.hpfilter(y, lamb=lamb)
    return np.asarray(trend)


def _yoy_inflation(cpi: pd.Series) -> pd.Series:
    """Four-quarter trailing year-over-year CPI inflation (percent).

    Returns NaN for the first four quarters (no year-ago level available).
    """
    return (cpi / cpi.shift(4) - 1.0) * 100.0


def _hamilton_gap(log_gdp: np.ndarray, horizon: int = 8, lags: int = 4) -> np.ndarray:
    """Hamilton's (2018) alternative to the Hodrick-Prescott filter.

    Regress the level on its own values ``horizon`` periods earlier and call the residual the
    cycle. It has no endpoint problem and no smoothing parameter to choose, which are the two
    complaints against Hodrick-Prescott — and it is genuinely a different filter, which is the
    point: ``gap_method`` was accepted, never consulted, and still written into the diagnostics
    as the method that had been used.
    """
    y = pd.Series(log_gdp)
    design = pd.concat([y.shift(horizon + i) for i in range(lags)], axis=1)
    design.columns = [f"lag{i}" for i in range(lags)]
    frame = pd.concat([y.rename("y"), design], axis=1).dropna()
    if len(frame) <= lags + 1:
        raise ValueError(
            f"the Hamilton filter needs more than {lags + 1} usable observations after "
            f"{horizon + lags} are consumed by its own lags; the sample has {len(frame)}"
        )
    fitted = sm.OLS(frame["y"], sm.add_constant(frame.drop(columns="y"))).fit()
    gap = pd.Series(np.nan, index=y.index, dtype=float)
    gap.loc[frame.index] = fitted.resid
    return np.asarray(gap) * 100.0


def _output_gap(gdp: pd.Series, hp_lambda: float, method: str = "hp") -> pd.Series:
    """Output gap in percent of potential."""
    log_gdp = np.log(gdp.values.astype(float))
    if method == "hp":
        trend = _hp_filter(log_gdp, hp_lambda)
        gap_pct = (np.exp(log_gdp - trend) - 1.0) * 100.0
    elif method == "hamilton":
        gap_pct = _hamilton_gap(log_gdp)
    else:
        raise ValueError(
            f"unknown gap_method {method!r}; use 'hp' or 'hamilton'. A method that is accepted "
            "and then ignored is worse than one that is refused, because the result carries an "
            "assumption that was never applied."
        )
    return pd.Series(gap_pct, index=gdp.index, name="gap")


#: Residual degrees of freedom below which a standard error means nothing.
_MIN_RESIDUAL_DF = 10


@register
class TaylorRule:
    """Taylor (1993) monetary policy rule.

    ``fit`` applies the rule with given coefficients; ``estimate`` regresses the actual
    policy rate on inflation and the gap to recover them from the data.
    """

    model_id = "taylor_rule"
    model_version = "1"

    def __init__(
        self,
        entity: str,
        neutral_real_rate: float = 2.0,
        inflation_target: float = 2.0,
        weight_inflation: float = 0.5,
        weight_gap: float = 0.5,
        gap_method: str = "hp",
        hp_lambda: float = 1600.0,
    ) -> None:
        self.entity = entity
        self.neutral_real_rate = neutral_real_rate
        self.inflation_target = inflation_target
        self.weight_inflation = weight_inflation
        self.weight_gap = weight_gap
        self.gap_method = gap_method
        self.hp_lambda = hp_lambda

    requires: Sequence[ConceptRequest] = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    # ------------------------------------------------------------------ column helpers
    def _col(self, concept: str) -> str:
        return f"{concept}@{self.entity}"

    def _extract(self, panel: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """The three series, after the panel has been checked against what the model declared.

        `panel_for` is what makes the row shifts below mean what they say. Every lag here is
        positional — `cpi.shift(4)` for a four-quarter change — and that is a four-quarter change
        only on a quarterly index with no holes. On the monthly panel `api.get_panel` returns by
        default it was a four-month change reported as annual, and the prescribed rate came out
        six points low with no exception and no warning.
        """
        panel_for(self, panel, entity=self.entity)
        cpi = series_for(panel, "cpi_headline_index", self.entity).dropna()
        gdp = series_for(panel, "gdp_real", self.entity).dropna()
        rate = series_for(panel, "policy_rate", self.entity)

        if len(cpi) < 5 or len(gdp) < 5:
            raise ValueError(
                f"not enough observations to compute the Taylor rule "
                f"(CPI has {len(cpi)}, GDP has {len(gdp)}; need at least 5)"
            )
        return cpi, gdp, rate

    def _diagnostics(self, actual: pd.Series, prescribed: pd.Series) -> pd.DataFrame:
        """Build the diagnostics table with settings and fit statistics."""
        mask = actual.notna() & prescribed.notna()
        a = actual[mask].astype(float)
        p = prescribed[mask].astype(float)

        rows = [
            ("neutral_real_rate", self.neutral_real_rate),
            ("inflation_target", self.inflation_target),
            ("weight_inflation", self.weight_inflation),
            ("weight_gap", self.weight_gap),
            ("gap_method", self.gap_method),
            ("gap_two_sided", True),
            ("hp_lambda", self.hp_lambda),
            ("inflation_measure", "cpi_headline_index_yoy_4q"),
            ("n_obs", int(mask.sum())),
            ("correlation", float(a.corr(p)) if len(a) > 1 else float("nan")),
            (
                "mean_absolute_deviation",
                float((a - p).abs().mean()) if len(a) > 0 else float("nan"),
            ),
        ]
        return pd.DataFrame(rows, columns=["metric", "value"])

    # ------------------------------------------------------------------ fit
    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        """Apply the Taylor rule with the given coefficients.

        The output gap is computed here, on the panel as received — never precomputed.
        The HP filter is two-sided; this is declared in diagnostics.
        """
        cpi, gdp, rate = self._extract(panel)

        # Four-quarter trailing CPI inflation
        inflation = _yoy_inflation(cpi)

        # Output gap via HP filter on log GDP — computed on *this* panel only
        gap = _output_gap(gdp, self.hp_lambda, self.gap_method)

        # Build a common index (intersection of all series)
        common = inflation.dropna().index.intersection(gap.dropna().index).intersection(rate.index)
        if len(common) == 0:
            raise ValueError("no observations remain after aligning inflation, gap, and rate")

        inflation = inflation.reindex(common)
        gap = gap.reindex(common)
        rate = rate.reindex(common)

        # The rule
        prescribed = (
            self.neutral_real_rate
            + inflation
            + self.weight_inflation * (inflation - self.inflation_target)
            + self.weight_gap * gap
        )

        prescription = pd.DataFrame(
            {
                "period": common,
                "actual": rate.values,
                "prescribed": prescribed.values,
                "gap": gap.values,
                "inflation": inflation.values,
                "deviation": (rate - prescribed).values,
            }
        )

        diag = self._diagnostics(rate, prescribed)

        return TablesResult({"prescription": prescription, "diagnostics": diag})

    # ------------------------------------------------------------------ estimate
    def estimate(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        """Regress the actual policy rate on inflation and the gap to recover weights.

        The regression is:
            rate_t = const + b_inflation * inflation_t + b_gap * gap_t + e_t

        From which the Taylor rule parameters can be inferred:
            a_π = b_inflation - 1  (since the rule has π as both level and gap term)
            a_y = b_gap
        """
        cpi, gdp, rate = self._extract(panel)

        inflation = _yoy_inflation(cpi)
        gap = _output_gap(gdp, self.hp_lambda, self.gap_method)

        common = (
            inflation.dropna()
            .index.intersection(gap.dropna().index)
            .intersection(rate.dropna().index)
        )
        # Three regressors are fitted here (constant, inflation, gap), so three observations
        # interpolate them exactly: zero residual degrees of freedom, undefined standard errors,
        # and a coefficients table that looks like any other. Demand degrees of freedom, not rows.
        needed = 3 + _MIN_RESIDUAL_DF
        if len(common) < needed:
            raise ValueError(
                f"not enough observations for estimation: {len(common)} usable, and fitting "
                f"three parameters with residual degrees of freedom needs at least {needed}"
            )

        y = rate.reindex(common).astype(float)
        X = pd.DataFrame({"inflation": inflation.reindex(common), "gap": gap.reindex(common)})
        X = sm.add_constant(X)

        model = sm.OLS(y, X).fit()

        coef_rows = []
        for name in ["const", "inflation", "gap"]:
            coef_rows.append(
                {
                    "name": name,
                    "estimate": float(model.params[name]),
                    "std_error": float(model.bse[name]),
                }
            )
        coefficients = pd.DataFrame(coef_rows)

        # Also produce the prescription with the *given* (not estimated) coefficients
        fit_result = self.fit(panel, ctx)

        diag = self._diagnostics(
            rate.reindex(common),
            fit_result.tables()["prescription"].set_index("period")["prescribed"].reindex(common),
        )

        return TablesResult(
            {
                "prescription": fit_result.tables()["prescription"],
                "coefficients": coefficients,
                "diagnostics": diag,
            }
        )
