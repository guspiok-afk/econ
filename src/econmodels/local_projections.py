"""Local projections estimator (Jordà 2005) for impulse response analysis.

Local projections estimate impulse responses directly by running a separate regression for
each horizon h, imposing no cross-horizon restrictions. Standard errors are corrected for
overlapping observations using Newey-West / HAC covariance with maxlags = h.
"""

from __future__ import annotations

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


@register
class LocalProjections:
    """Jordà (2005) local projections estimator for impulse responses."""

    model_id = "local_projections"
    model_version = "1"
    requires = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    def __init__(
        self,
        entity: str,
        horizon: int = 20,
        lags: int = 4,
        shock: str = "policy",
        responses: tuple[str, ...] = ("inflation", "output", "policy"),
    ) -> None:
        self.entity = entity
        self.horizon = horizon
        self.lags = lags
        self.shock = shock
        self.responses = responses

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:

        panel_for(self, panel, entity=self.entity)

        cpi = series_for(panel, "cpi_headline_index", self.entity).sort_index()
        gdp = series_for(panel, "gdp_real", self.entity).sort_index()
        policy_rate = series_for(panel, "policy_rate", self.entity).sort_index()

        inflation = 100 * np.log(cpi / cpi.shift(4))
        output = 100 * np.log(gdp)
        policy = policy_rate

        vars_map = {
            "inflation": inflation,
            "output": output,
            "policy": policy,
        }

        if self.shock not in vars_map:
            allowed = list(vars_map.keys())
            raise ValueError(f"Unknown shock variable {self.shock!r}. Must be one of {allowed}")

        for resp in self.responses:
            if resp not in vars_map:
                allowed = list(vars_map.keys())
                raise ValueError(f"Unknown response variable {resp!r}. Must be one of {allowed}")

        df_base = pd.DataFrame(vars_map).dropna()

        num_params = 1 + 1 + self.lags * len(vars_map)
        if len(df_base) <= self.lags + self.horizon:
            raise ValueError(
                f"Insufficient observations ({len(df_base)}) for requested "
                f"horizon ({self.horizon}) and lags ({self.lags})."
            )

        X_lags = pd.DataFrame(index=df_base.index)
        for lag_idx in range(1, self.lags + 1):
            for col in df_base.columns:
                X_lags[f"{col}_lag{lag_idx}"] = df_base[col].shift(lag_idx)

        shock_series = df_base[self.shock]

        irf_rows = []
        regressions_count = 0
        n_obs_max = 0

        for h in range(self.horizon + 1):
            for resp in self.responses:
                resp_series = df_base[resp]
                if h == 0:
                    valid_mask = shock_series.notna() & X_lags.notna().all(axis=1)
                    n_obs_h0 = int(valid_mask.sum())
                    if n_obs_h0 > n_obs_max:
                        n_obs_max = n_obs_h0

                    irf_rows.append(
                        {
                            "horizon": h,
                            "response": resp,
                            "value": 0.0,
                            "std_error": 0.0,
                            "ci_low": 0.0,
                            "ci_high": 0.0,
                            "n_obs": n_obs_h0,
                        }
                    )
                else:
                    lhs = resp_series.shift(-h) - resp_series
                    reg_df = pd.concat(
                        [lhs.rename("y"), shock_series.rename("shock"), X_lags], axis=1
                    ).dropna()

                    if len(reg_df) < num_params:
                        raise ValueError(
                            f"Insufficient observations ({len(reg_df)}) "
                            f"at horizon {h} for estimation."
                        )

                    X = sm.add_constant(reg_df.drop(columns=["y"]))
                    mod = sm.OLS(reg_df["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": h})

                    val = float(mod.params["shock"])
                    se = float(mod.bse["shock"])
                    ci = mod.conf_int(alpha=0.05).loc["shock"]
                    ci_low = float(ci[0])
                    ci_high = float(ci[1])
                    n_obs = int(mod.nobs)

                    if n_obs > n_obs_max:
                        n_obs_max = n_obs

                    regressions_count += 1

                    irf_rows.append(
                        {
                            "horizon": h,
                            "response": resp,
                            "value": val,
                            "std_error": se,
                            "ci_low": ci_low,
                            "ci_high": ci_high,
                            "n_obs": n_obs,
                        }
                    )

        df_irf = pd.DataFrame(irf_rows)

        df_diag = pd.DataFrame(
            [
                {"metric": "horizon", "value": str(self.horizon)},
                {"metric": "lags", "value": str(self.lags)},
                {"metric": "cov", "value": "newey-west"},
                {"metric": "regressions", "value": str(regressions_count)},
                {"metric": "n_obs_max", "value": str(n_obs_max)},
            ]
        )

        return TablesResult({"irf": df_irf, "diagnostics": df_diag})
