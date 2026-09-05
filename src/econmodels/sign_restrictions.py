"""The monetary VAR model with sign restrictions identification.

Fits a vector autoregression on inflation, real GDP, and the policy rate, identified
by sign restrictions across drawn random orthogonal matrices (rotations).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.api import VAR

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
class SignRestrictedVAR:
    """A 3-variable monetary VAR identified by sign restrictions."""

    model_id = "var_sign"
    model_version = "1"
    requires = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    def __init__(
        self,
        entity: str,
        lags: int = 4,
        horizon: int = 20,
        restrict_through: int = 3,
        draws: int = 2000,
        signs: dict[str, int] | None = None,
        bands: tuple[float, float] = (16.0, 84.0),
    ) -> None:
        self.entity = entity
        self.lags = lags
        self.horizon = horizon
        self.restrict_through = restrict_through
        self.draws = draws
        self.signs = signs if signs is not None else {"policy": 1, "output": -1, "inflation": -1}
        self.bands = bands

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

        df_var = pd.DataFrame(vars_map).dropna()

        n_effective = len(df_var) - self.lags
        min_required = self.lags * len(df_var.columns) + 1
        if len(df_var) <= self.lags or n_effective < min_required:
            msg = (
                f"Insufficient observations ({len(df_var)}) for requested lags ({self.lags}). "
                f"Effective sample size after lags ({n_effective}) is below min ({min_required})."
            )
            raise ValueError(msg)

        model = VAR(df_var)
        results = model.fit(maxlags=self.lags)

        sigma = results.sigma_u
        P = np.linalg.cholesky(sigma)
        psi = results.ma_rep(self.horizon)  # shape (horizon + 1, k, k)

        k = len(df_var.columns)
        var_names = list(df_var.columns)
        accepted_irfs: list[np.ndarray] = []
        total_combos = 0
        rng = ctx.rng

        for _ in range(self.draws):
            Z = rng.standard_normal((k, k))
            Q, _ = np.linalg.qr(Z)
            A = P @ Q
            for col in range(k):
                for sign_factor in (1.0, -1.0):
                    total_combos += 1
                    cand = A[:, col] * sign_factor
                    ok = True
                    for h in range(self.restrict_through + 1):
                        irf_h = psi[h] @ cand
                        for var_idx, var_name in enumerate(var_names):
                            if var_name in self.signs:
                                req_sign = self.signs[var_name]
                                if req_sign * irf_h[var_idx] <= 0:
                                    ok = False
                                    break
                        if not ok:
                            break
                    if ok:
                        irf_full = np.array([psi[h] @ cand for h in range(self.horizon + 1)])
                        accepted_irfs.append(irf_full)

        if not accepted_irfs:
            raise ValueError(
                "No rotation satisfied the specified sign restrictions. Zero accepted draws."
            )

        accepted = np.array(accepted_irfs)  # shape (N_accepted, horizon + 1, k)
        medians = np.median(accepted, axis=0)
        lows = np.percentile(accepted, self.bands[0], axis=0)
        highs = np.percentile(accepted, self.bands[1], axis=0)

        irf_rows = []
        for h in range(self.horizon + 1):
            for v_idx, v_name in enumerate(var_names):
                irf_rows.append(
                    {
                        "horizon": h,
                        "response": v_name,
                        "median": float(medians[h, v_idx]),
                        "low": float(lows[h, v_idx]),
                        "high": float(highs[h, v_idx]),
                    }
                )
        df_irf = pd.DataFrame(irf_rows)

        acc_cnt = len(accepted_irfs)
        acc_rate = acc_cnt / total_combos if total_combos > 0 else 0.0

        diag_rows = [
            {"metric": "identification", "value": "sign"},
            {"metric": "restrict_through", "value": str(self.restrict_through)},
            {"metric": "draws", "value": str(self.draws)},
            {"metric": "accepted", "value": str(acc_cnt)},
            {"metric": "acceptance_rate", "value": str(acc_rate)},
            {"metric": "n_obs", "value": str(results.nobs)},
            {"metric": "lags", "value": str(results.k_ar)},
            {"metric": "bands", "value": str(self.bands)},
        ]
        df_diag = pd.DataFrame(diag_rows)

        return TablesResult({"irf": df_irf, "diagnostics": df_diag})
