"""The monetary VAR model with recursive identification.

Fits a vector autoregression on inflation, real GDP, and the policy rate, identified
recursively (Cholesky decomposition) under a specified variable ordering.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.api import VAR

from econmodels.base import ConceptRequest, Result, RunContext, TablesResult, register


@register
class VectorAutoregression:
    """A 3-variable monetary VAR identified recursively."""

    model_id = "var_monetary"
    model_version = "1"
    requires = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    def __init__(
        self,
        entity: str,
        lags: int | str = 4,
        max_lags: int = 8,
        horizon: int = 24,
        order: tuple[str, str, str] = ("inflation", "output", "policy"),
        identification: str = "cholesky",
    ) -> None:
        if identification.lower() != "cholesky":
            raise ValueError(
                f"Only 'cholesky' identification is currently supported, got '{identification}'."
            )
        self.entity = entity
        self.lags = lags
        self.max_lags = max_lags
        self.horizon = horizon
        self.order = order
        self.identification = identification

    def _get_series(self, panel: pd.DataFrame, concept: str) -> pd.Series:
        """Locate the column for a concept and entity in the given panel."""
        col_name = f"{concept}@{self.entity}"
        if col_name in panel.columns:
            return panel[col_name]
        if concept in panel.columns and not any("@" in str(c) for c in panel.columns):
            return panel[concept]
        cols_str = ", ".join(str(c) for c in panel.columns)
        raise ValueError(
            f"Concept '{concept}' for entity '{self.entity}' (expected '{col_name}') "
            f"not found in panel columns: [{cols_str}]"
        )

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        cpi = self._get_series(panel, "cpi_headline_index")
        gdp = self._get_series(panel, "gdp_real")
        policy_rate = self._get_series(panel, "policy_rate")

        # Transformations:
        # Sort index to ensure chronological ordering before shift
        cpi = cpi.sort_index()
        gdp = gdp.sort_index()
        policy_rate = policy_rate.sort_index()

        # inflation: 4-quarter log change of price index, times 100
        inflation = 100 * np.log(cpi / cpi.shift(4))
        # output: 100 * log of real GDP
        output = 100 * np.log(gdp)
        # policy: rate as it comes
        policy = policy_rate

        vars_map = {
            "inflation": inflation,
            "output": output,
            "policy": policy,
        }

        # Validate order keys
        for var_name in self.order:
            if var_name not in vars_map:
                allowed = list(vars_map.keys())
                msg = f"Unknown variable '{var_name}' in order. Must be one of {allowed}"
                raise ValueError(msg)

        df_var = pd.DataFrame({v: vars_map[v] for v in self.order}).dropna()

        # Check sample size discounting the lags consumed during estimation
        check_lags = self.lags if isinstance(self.lags, int) else self.max_lags
        n_effective = len(df_var) - check_lags
        min_required = check_lags * len(self.order) + 1
        if len(df_var) <= check_lags or n_effective < min_required:
            msg = (
                f"Insufficient observations ({len(df_var)}) for requested lags ({check_lags}). "
                f"Effective sample size after lags ({n_effective}) is below min ({min_required})."
            )
            raise ValueError(msg)

        model = VAR(df_var)
        if isinstance(self.lags, int):
            results = model.fit(maxlags=self.lags)
        elif isinstance(self.lags, str):
            results = model.fit(maxlags=self.max_lags, ic=self.lags.lower())
        else:
            raise ValueError(f"Invalid lags configuration: {self.lags}")

        # Table 1: irf (horizon, shock, response, value)
        irf_obj = results.irf(self.horizon)
        orth_irfs = irf_obj.orth_irfs  # shape (horizon + 1, k_vars, k_vars)
        irf_rows = []
        for h in range(self.horizon + 1):
            for s_idx, shock in enumerate(results.names):
                for r_idx, response in enumerate(results.names):
                    irf_rows.append(
                        {
                            "horizon": h,
                            "shock": shock,
                            "response": response,
                            "value": float(orth_irfs[h, r_idx, s_idx]),
                        }
                    )
        df_irf = pd.DataFrame(irf_rows)

        # Table 2: fevd (horizon, response, shock, value)
        # Fetch horizon + 1 steps to include step 0 through step self.horizon
        fevd_obj = results.fevd(self.horizon + 1)
        decomp = fevd_obj.decomp  # shape (k_vars, horizon + 1, k_vars)
        fevd_rows = []
        for r_idx, response in enumerate(results.names):
            for h in range(decomp.shape[1]):
                for s_idx, shock in enumerate(results.names):
                    fevd_rows.append(
                        {
                            "horizon": h,
                            "response": response,
                            "shock": shock,
                            "value": float(decomp[r_idx, h, s_idx]),
                        }
                    )
        df_fevd = pd.DataFrame(fevd_rows)

        # Table 3: coefficients (equation, regressor, estimate, std_error)
        coeff_rows = []
        for eq in results.params.columns:
            for reg in results.params.index:
                coeff_rows.append(
                    {
                        "equation": eq,
                        "regressor": reg,
                        "estimate": float(results.params.loc[reg, eq]),
                        "std_error": float(results.bse.loc[reg, eq]),
                    }
                )
        df_coeff = pd.DataFrame(coeff_rows)

        # Table 4: diagnostics (metric, value)
        max_eig = float(np.max(1.0 / np.abs(results.roots)))
        diag_rows = [
            {"metric": "n_obs", "value": str(results.nobs)},
            {"metric": "lags", "value": str(results.k_ar)},
            {"metric": "identification", "value": str(self.identification)},
            {"metric": "order", "value": ",".join(self.order)},
            {"metric": "max_eigenvalue", "value": str(max_eig)},
            {"metric": "loglikelihood", "value": str(float(results.llf))},
        ]
        df_diag = pd.DataFrame(diag_rows)

        return TablesResult(
            _tables={
                "irf": df_irf,
                "fevd": df_fevd,
                "coefficients": df_coeff,
                "diagnostics": df_diag,
            }
        )
