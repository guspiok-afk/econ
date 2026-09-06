"""Identification by sign restrictions, and the honesty it forces.

A recursive ordering picks one identification out of infinitely many and reports it as the
answer. Sign restrictions do the opposite: they keep every identification consistent with a
minimal statement about how monetary policy behaves — the rate rises, output falls, inflation
falls — and report the whole surviving set.

That set is the result. Publishing its median without its band would put back exactly the false
precision the method exists to remove, so the impulse response table carries three columns and
the acceptance rate goes into the diagnostics: two per cent of candidate rotations surviving is
information about how demanding the restrictions are, and a reader who cannot see it cannot
judge the answer.

One thing this module cannot tell you, and neither can its tests: for the horizons where a sign
was imposed, finding that sign proves nothing. What is worth reading is whether the responses
keep their sign after the restriction stops binding.
"""

from __future__ import annotations

from collections.abc import Sequence

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

#: The minimal statement about monetary policy that every accepted identification must satisfy.
DEFAULT_SIGNS = {"policy": 1, "output": -1, "inflation": -1}
VARIABLES = ("inflation", "output", "policy")


@register
class SignRestrictedVAR:
    """A vector autoregression identified by refusing what does not look like policy."""

    model_id = "var_sign"
    model_version = "1"
    requires: Sequence[ConceptRequest] = (
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
        self.signs = dict(signs) if signs else dict(DEFAULT_SIGNS)
        self.bands = bands

    def _system(self, panel: pd.DataFrame) -> pd.DataFrame:
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

    def _satisfies(self, response: np.ndarray) -> bool:
        """Does this candidate shock behave like monetary policy over the restricted window?"""
        for h in range(self.restrict_through + 1):
            for name, wanted in self.signs.items():
                if wanted * response[h, VARIABLES.index(name)] <= 0:
                    return False
        return True

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        system = self._system(panel)
        # what each equation estimates: a constant plus one coefficient per variable per lag
        n_params = self.lags * len(VARIABLES) + 1
        effective = len(system) - self.lags
        if effective < n_params:
            raise ValueError(
                f"not enough observations for a VAR of {self.lags} lags: {len(system)} rows leave "
                f"an effective sample of {effective} against {n_params} parameters per equation. "
                "Reduce the lags or lengthen the sample."
            )

        fitted = VAR(system).fit(self.lags)
        chol = np.linalg.cholesky(fitted.sigma_u)
        moving_average = fitted.ma_rep(maxn=self.horizon)

        accepted: list[np.ndarray] = []
        candidates = 0
        for _ in range(self.draws):
            rotation, upper = np.linalg.qr(ctx.rng.normal(size=(len(VARIABLES),) * 2))
            # sign convention on the diagonal, so a rotation and its mirror are not counted twice
            rotation = rotation * np.sign(np.diag(upper))
            impact = chol @ rotation
            for column in range(len(VARIABLES)):
                for direction in (1.0, -1.0):
                    candidates += 1
                    shock = direction * impact[:, column]
                    response = np.array(
                        [moving_average[h] @ shock for h in range(self.horizon + 1)]
                    )
                    if self._satisfies(response):
                        accepted.append(response)

        if not accepted:
            raise ValueError(
                f"no rotation satisfies the restrictions after {candidates} candidates. "
                f"The signs asked for were {self.signs}; a set that nothing satisfies is a "
                "statement about the restrictions, not about the data."
            )

        draws_array = np.array(accepted)
        low, high = self.bands
        rows: list[dict[str, object]] = []
        for h in range(self.horizon + 1):
            for index, name in enumerate(VARIABLES):
                values = draws_array[:, h, index]
                rows.append(
                    {
                        "horizon": h,
                        "response": name,
                        "median": float(np.median(values)),
                        "low": float(np.percentile(values, low)),
                        "high": float(np.percentile(values, high)),
                    }
                )

        diagnostics = pd.DataFrame(
            [
                {"metric": "identification", "value": "sign"},
                {"metric": "restrict_through", "value": str(self.restrict_through)},
                {"metric": "signs", "value": ",".join(f"{k}{v:+d}" for k, v in self.signs.items())},
                {"metric": "draws", "value": str(self.draws)},
                {"metric": "candidates", "value": str(candidates)},
                {"metric": "accepted", "value": str(len(accepted))},
                {"metric": "acceptance_rate", "value": str(len(accepted) / candidates)},
                {"metric": "bands", "value": f"{low}-{high}"},
                {"metric": "lags", "value": str(self.lags)},
                {"metric": "n_obs", "value": str(int(fitted.nobs))},
                {"metric": "n_params", "value": str(n_params)},
                {"metric": "seed", "value": str(ctx.seed)},
                {"metric": "asof", "value": str(ctx.asof)},
            ]
        )
        return TablesResult(_tables={"irf": pd.DataFrame(rows), "diagnostics": diagnostics})
