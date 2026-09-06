"""Impulse responses by local projection (Jordà, 2005).

One regression per horizon, and nothing imposed across them. That is the whole difference from a
vector autoregression, which extrapolates a single estimated system to every horizon at once: if
the lag structure is wrong, the error compounds along the response path. Here a mistake at
horizon twelve stays at horizon twelve.

The cost is efficiency and the benefit is honesty about it — the bands widen with the horizon
because nothing is tying them together, which is the estimator telling the truth about how little
the sample says that far out.

Successive horizons overlap by construction: the regression for h and the one for h+1 share all
but one observation. The standard errors must be corrected for that, exactly as in the Fama
regression, and getting it wrong manufactures significance rather than losing it.
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

#: Residual degrees of freedom a horizon's regression must keep after its parameters.
#:
#: This replaced a fixed floor of twenty rows, which was wrong in a way only measurement showed.
#: The parameter count grows with the lag order -- a constant, the shock, and ``lags`` times three
#: variables -- so at eight lags a projection estimates twenty-six coefficients, and a fixed floor
#: of twenty let it run on twenty-two observations. It did not fail: it returned -0.3986 for the
#: output response with a rank-deficient design, which is a number where there is no estimate.
#: Jules' implementation of this same package scaled its guard with the parameters and refused.
MIN_RESIDUAL_DF = 10


@register
class LocalProjections:
    """Impulse responses estimated horizon by horizon."""

    model_id = "local_projections"
    model_version = "1"
    requires: Sequence[ConceptRequest] = (
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

    def _system(self, panel: pd.DataFrame) -> pd.DataFrame:
        """The three variables, built the same way the vector autoregression builds them."""
        panel_for(self, panel, entity=self.entity)
        cpi = series_for(panel, "cpi_headline_index", self.entity)
        gdp = series_for(panel, "gdp_real", self.entity)
        policy = series_for(panel, "policy_rate", self.entity)
        return pd.DataFrame(
            {
                "inflation": 100.0 * np.log(cpi).diff(4),
                "output": 100.0 * np.log(gdp),
                "policy": policy,
            }
        ).dropna()

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        system = self._system(panel)
        if self.shock not in system.columns:
            raise ValueError(f"unknown shock {self.shock!r}; the system carries {list(system)}")
        unknown = [r for r in self.responses if r not in system.columns]
        if unknown:
            raise ValueError(
                f"unknown response(s) {unknown}; the system carries {list(system)}. "
                "Left unchecked this surfaced as a bare KeyError from inside the loop."
            )

        controls = pd.concat(
            [system.shift(lag).add_suffix(f"_l{lag}") for lag in range(1, self.lags + 1)], axis=1
        )
        design = pd.concat([system[self.shock].rename("shock"), controls], axis=1)

        # constant, the shock itself, and one coefficient per variable per lag
        n_params = 2 + self.lags * len(system.columns)
        needed = n_params + MIN_RESIDUAL_DF

        rows: list[dict[str, object]] = []
        regressions = 0
        for response in self.responses:
            for h in range(self.horizon + 1):
                # cumulative from the period of the shock, so horizon zero is zero by construction
                left = (system[response].shift(-h) - system[response]).rename("y")
                frame = pd.concat([left, design], axis=1).dropna()
                if h == 0:
                    # y is identically zero here, so there is nothing to estimate. Running the
                    # regression anyway returned the right number for the wrong reason and
                    # inflated the regression count by one per response.
                    rows.append(
                        {
                            "horizon": 0,
                            "response": response,
                            "value": 0.0,
                            "std_error": 0.0,
                            "ci_low": 0.0,
                            "ci_high": 0.0,
                            "n_obs": len(frame),
                        }
                    )
                    continue
                if len(frame) < needed:
                    raise ValueError(
                        f"not enough observations for horizon {h}: {len(frame)} usable against "
                        f"{n_params} parameters, and this projection keeps at least "
                        f"{MIN_RESIDUAL_DF} residual degrees of freedom. Shorten the lags or the "
                        "horizon, or lengthen the sample."
                    )
                fitted = sm.OLS(frame["y"], sm.add_constant(frame.drop(columns="y"))).fit(
                    cov_type="HAC", cov_kwds={"maxlags": h}
                )
                regressions += 1
                beta = float(fitted.params["shock"])
                error = float(fitted.bse["shock"])
                low, high = fitted.conf_int(alpha=0.05).loc["shock"]
                rows.append(
                    {
                        "horizon": h,
                        "response": response,
                        "value": beta,
                        "std_error": error,
                        "ci_low": float(low),
                        "ci_high": float(high),
                        "n_obs": int(fitted.nobs),
                    }
                )

        irf = pd.DataFrame(rows)
        diagnostics = pd.DataFrame(
            [
                {"metric": "horizon", "value": str(self.horizon)},
                {"metric": "lags", "value": str(self.lags)},
                {"metric": "shock", "value": self.shock},
                {"metric": "cov", "value": "newey_west"},
                {"metric": "regressions", "value": str(regressions)},
                {"metric": "n_params", "value": str(n_params)},
                {"metric": "n_obs_max", "value": str(int(irf["n_obs"].max()))},
                {"metric": "n_obs_min", "value": str(int(irf["n_obs"].min()))},
                {"metric": "entity", "value": self.entity},
                {"metric": "asof", "value": str(ctx.asof)},
            ]
        )
        return TablesResult(_tables={"irf": irf, "diagnostics": diagnostics})
