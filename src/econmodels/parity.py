"""Uncovered interest parity analysis (the Fama regression)."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class FamaResult:
    alpha: float
    beta: float
    alpha_se: float
    beta_se: float
    r_squared: float
    n_obs: int
    horizon_months: int
    pvalue_beta_equals_one: float  # H0: β = 1, the parity restriction

    def holds(self, level: float = 0.05) -> bool:
        """True when parity cannot be rejected at this level."""
        return self.pvalue_beta_equals_one > level


@register
class UncoveredParity:
    model_id = "uip_fama"
    model_version = "1"
    requires = (
        ConceptRequest("fx_spot_usd", freq="M"),
        ConceptRequest("policy_rate", freq="M"),
        ConceptRequest("policy_rate", entity="US", freq="M"),
    )

    def __init__(self, base: str, quote: str = "US", horizon_months: int = 12) -> None:
        self.base = base
        self.quote = quote
        self.horizon_months = horizon_months

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        panel_for(self, panel, entity=self.base)
        s = np.log(series_for(panel, "fx_spot_usd", self.base))
        realised_dep = 100.0 * (s.shift(-self.horizon_months) - s)
        differential = series_for(panel, "policy_rate", self.base) - series_for(
            panel, "policy_rate", self.quote
        )

        df = pd.DataFrame(
            {"dep": realised_dep, "diff": differential},
            index=panel.index,
        ).dropna()

        if len(df) < 30:
            raise ValueError(f"Sample has fewer than 30 usable observations ({len(df)})")

        x = sm.add_constant(df["diff"])
        ols_model = sm.OLS(df["dep"], x)
        res = ols_model.fit(cov_type="HAC", cov_kwds={"maxlags": self.horizon_months})

        alpha = float(res.params["const"])
        beta = float(res.params["diff"])
        alpha_se = float(res.bse["const"])
        beta_se = float(res.bse["diff"])
        alpha_tstat = float(res.tvalues["const"])
        beta_tstat = float(res.tvalues["diff"])
        r_squared = float(res.rsquared)
        n_obs = int(res.nobs)

        ttest = res.t_test("diff = 1")
        pvalue_beta_equals_one = float(np.squeeze(ttest.pvalue))

        fama_result = FamaResult(
            alpha=alpha,
            beta=beta,
            alpha_se=alpha_se,
            beta_se=beta_se,
            r_squared=r_squared,
            n_obs=n_obs,
            horizon_months=self.horizon_months,
            pvalue_beta_equals_one=pvalue_beta_equals_one,
        )

        coefficients_df = pd.DataFrame(
            [
                {
                    "name": "alpha",
                    "estimate": alpha,
                    "std_error": alpha_se,
                    "t_stat": alpha_tstat,
                },
                {
                    "name": "beta",
                    "estimate": beta,
                    "std_error": beta_se,
                    "t_stat": beta_tstat,
                },
            ]
        )

        diagnostics_df = pd.DataFrame(
            [
                {"metric": "n_obs", "value": float(n_obs)},
                {"metric": "r_squared", "value": float(r_squared)},
                {"metric": "pvalue_beta_equals_one", "value": float(pvalue_beta_equals_one)},
                {"metric": "horizon_months", "value": float(self.horizon_months)},
            ]
        )

        fitted_df = pd.DataFrame(
            {
                "period": df.index,
                "differential": df["diff"].values,
                "realised_depreciation": df["dep"].values,
                "predicted": res.fittedvalues.values,
            }
        ).reset_index(drop=True)

        tables = {
            "coefficients": coefficients_df,
            "diagnostics": diagnostics_df,
            "fitted": fitted_df,
        }

        return TablesResult(_tables=tables, _artifacts=[fama_result])
