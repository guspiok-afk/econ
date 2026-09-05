"""Estimating the quarter that has not been published yet.

Every indicator arrives on its own schedule, so the bottom of the panel is not a line but a
staircase: payrolls for August, industrial production only through July, and the quarter's GDP
nowhere at all. A model that requires a rectangle has to throw away the most recent and most
valuable rows to get one. A dynamic factor model does not: it treats the missing cells as
states to be filtered rather than as rows to be dropped, so the newest figure contributes the
day it lands.

What the factor buys is measured in ``docs/work-packages/WP-05a-dfm.md`` and is narrower than
the headline suggests. Over 2018-2025 it cuts the root mean squared error of United States
quarterly growth from 2.07 to 0.79 against the unconditional mean. Over the calm years since
2022 it scores 0.49 against 0.42 -- a loss. The gain is concentrated where a common shock moves
everything at once, which is where a common factor is the right object and where a mean is
worst; outside of that, quarterly growth at this horizon is close to unforecastable. Both
figures travel together in the acceptance tests, so the first cannot circulate on its own.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from econmodels.base import (
    ConceptRequest,
    Result,
    RunContext,
    TablesResult,
    check_frequency,
    column_for,
    register,
)

#: How each concept is made stationary. Guessing for an unlisted one is how a factor ends up
#: estimated over a trending level, so an unknown concept is refused by name instead.
TRANSFORMS: dict[str, str] = {
    "employment": "logdiff",
    "industrial_production": "logdiff",
    "retail_sales": "logdiff",
    "wages": "logdiff",
    "gdp_real": "logdiff",
    "activity_index": "logdiff",
    "unemployment_rate": "diff",
    "capacity_utilization": "diff",
    "consumer_confidence": "diff",
    "labor_conditions_index": "diff",
}

DEFAULT_INDICATORS: tuple[str, ...] = (
    "employment",
    "industrial_production",
    "retail_sales",
    "wages",
    "unemployment_rate",
    "capacity_utilization",
    "consumer_confidence",
    "labor_conditions_index",
)

#: Below this many quarterly observations the state space has nothing to anchor the target on.
MIN_QUARTERS = 20

#: Above this share of the target's variance explained by the quarter of the year, the model is
#: fitting a calendar rather than a cycle. Chosen from measurement, not taste: the United States
#: series scores 0.007 and Brazil's scores 0.553, so anything in between is a wide no-man's land
#: and the threshold does not need to be delicate.
MAX_SEASONAL_R2 = 0.25


class DfmError(ValueError):
    """The panel or the specification cannot support a mixed-frequency factor."""


def _stationary(series: pd.Series, concept: str) -> pd.Series:
    kind = TRANSFORMS.get(concept)
    if kind is None:
        raise DfmError(
            f"no stationarity transform declared for {concept!r}. Add it to "
            "econmodels.dfm.TRANSFORMS; estimating a factor over an untransformed level is "
            "the failure that produces a plausible-looking result from a spurious one."
        )
    if kind == "logdiff":
        if (series.dropna() <= 0).any():
            raise DfmError(f"{concept!r} is declared logdiff but is not strictly positive")
        return 100.0 * np.log(series).diff()
    return series.diff()


def seasonal_share(growth: pd.Series) -> float:
    """How much of a quarterly growth series is explained by which quarter of the year it is.

    The coefficient of determination of a regression on quarter-of-year dummies, computed as
    group means because that is all such a regression is. A seasonally adjusted series scores
    near zero; an unadjusted one scores high, and a model fitted to it will report the calendar
    back as a forecast — confidently, because the calendar is genuinely predictable.

    This exists because a live run did exactly that. Brazil's ``gdp_real`` is catalogued as
    seasonally adjusted and is not: it scores 0.553 against 0.007 for the United States, and the
    nowcast it produced for a third quarter was really the statement that third quarters are up.
    """
    clean = growth.dropna()
    if len(clean) < 8:
        return 0.0
    quarter = pd.PeriodIndex(clean.index, freq="Q").quarter
    fitted = clean.groupby(quarter).transform("mean")
    total = float(((clean - clean.mean()) ** 2).sum())
    if total == 0.0:
        return 0.0
    return 1.0 - float(((clean - fitted) ** 2).sum()) / total


@register
class DynamicFactorNowcast:
    """A common factor read off monthly indicators, carrying a quarterly target."""

    model_id = "dfm_nowcast"
    model_version = "1"
    requires: Sequence[ConceptRequest] = (
        *(ConceptRequest(concept, freq="M") for concept in DEFAULT_INDICATORS),
        # no freq: the panel grid is monthly and this column is not, which is the whole point
        ConceptRequest("gdp_real"),
    )

    def __init__(
        self,
        entity: str,
        target: str = "gdp_real",
        indicators: Sequence[str] | None = None,
        factors: int = 1,
        factor_orders: int = 1,
        sample_start: str | None = None,
        maxiter: int = 100,
        allow_seasonal: bool = False,
    ) -> None:
        self.entity = entity
        self.target = target
        self.indicators = tuple(indicators) if indicators else DEFAULT_INDICATORS
        self.factors = factors
        self.factor_orders = factor_orders
        self.sample_start = sample_start
        self.maxiter = maxiter
        self.allow_seasonal = allow_seasonal

    # ------------------------------------------------------------------ inputs
    def _blocks(self, panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Split the ragged panel into the monthly block and the quarterly target."""
        check_frequency(panel, "M")
        if self.sample_start:
            panel = panel.loc[self.sample_start :]

        monthly = pd.DataFrame(index=panel.index)
        for concept in self.indicators:
            column = column_for(panel, concept, self.entity)
            monthly[concept] = _stationary(panel[column], concept)

        target_column = column_for(panel, self.target, self.entity)
        observed = panel[target_column].dropna()
        if observed.empty:
            raise DfmError(
                f"{self.target}@{self.entity} has no observations in this panel, so there is "
                "nothing to nowcast. Ask get_panel for it with mixed_freq=True."
            )
        quarterly = _stationary(observed, self.target).to_frame(self.target)
        quarterly.index = pd.PeriodIndex(quarterly.index, freq="Q")
        monthly.index = pd.PeriodIndex(monthly.index, freq="M")
        # the first row of every differenced column is empty by construction
        return monthly.iloc[1:], quarterly.iloc[1:]

    @staticmethod
    def _ragged_edge(monthly: pd.DataFrame) -> int:
        """How many months at the bottom are still incomplete -- the reason this model exists."""
        complete = monthly.notna().all(axis=1)
        trailing = 0
        for value in reversed(complete.tolist()):
            if value:
                break
            trailing += 1
        return trailing

    # ------------------------------------------------------------------ fit
    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

        monthly, quarterly = self._blocks(panel)
        usable = len(quarterly.dropna())
        if usable < MIN_QUARTERS:
            raise DfmError(
                "a mixed-frequency factor needs a usable quarterly history: "
                f"{usable} observations of {self.target} is not one"
            )

        seasonal = seasonal_share(quarterly[self.target])
        if seasonal > MAX_SEASONAL_R2 and not self.allow_seasonal:
            raise DfmError(
                f"{self.target}@{self.entity} is not seasonally adjusted: the quarter of the "
                f"year explains {seasonal:.1%} of its growth. A factor fitted to it would "
                "report the calendar as a forecast. Point the concept at an adjusted series, "
                "or pass allow_seasonal=True having said so in the write-up."
            )

        model = DynamicFactorMQ(
            monthly,
            endog_quarterly=quarterly,
            factors=self.factors,
            factor_orders=self.factor_orders,
            idiosyncratic_ar1=True,
            standardize=True,
        )
        fitted = model.fit(disp=False, maxiter=self.maxiter)

        last_month = monthly.index[-1]
        quarter_end = last_month.asfreq("Q").asfreq("M", "end")
        horizon = max(last_month, quarter_end)
        predicted = fitted.get_prediction(start=monthly.index[0], end=horizon).predicted_mean[
            self.target
        ]

        observed_quarters = set(quarterly.dropna().index)
        # A quarter without a published target is not automatically a nowcast. The state space
        # also fills the quarters *before* the target's history begins, and a live run put two
        # of those — one with zero visible monthly observations — in the same column as the
        # current quarter. Anything reading "not observed" as "this is the estimate" would have
        # taken three answers where there is one, so the distinction is a column and not a note.
        first_observed = min(observed_quarters)
        last_observed = max(observed_quarters)

        def status(quarter: pd.Period) -> str:
            if quarter in observed_quarters:
                return "observed"
            if quarter < first_observed:
                return "backfill"
            return "gap" if quarter < last_observed else "pending"

        rows: list[dict[str, object]] = []
        for period, value in predicted.items():
            if period.month % 3 != 0:  # only the month closing a quarter carries its level
                continue
            quarter = period.asfreq("Q")
            window = monthly.loc[str(quarter.asfreq("M", "start")) : str(period)]
            rows.append(
                {
                    "period": period.to_timestamp("M").date(),
                    "quarter": str(quarter),
                    "value": float(value),
                    "n_visible": int(window.notna().sum().sum()),
                    "is_observed": quarter in observed_quarters,
                    "status": status(quarter),
                }
            )
        nowcast = pd.DataFrame(rows)

        factor = fitted.factors.smoothed.iloc[:, 0]
        factor_table = pd.DataFrame(
            {
                "period": [p.to_timestamp("M").date() for p in factor.index],
                "value": factor.to_numpy(dtype="float64"),
            }
        )
        loadings = pd.DataFrame(
            [
                {"variable": name, "transform": TRANSFORMS[name]}
                for name in [*list(monthly.columns), self.target]
            ]
        )
        diagnostics = pd.DataFrame(
            [
                {"metric": "llf", "value": f"{float(fitted.llf):.4f}"},
                {"metric": "factors", "value": str(self.factors)},
                {"metric": "factor_orders", "value": str(self.factor_orders)},
                {"metric": "n_indicators", "value": str(len(monthly.columns))},
                {"metric": "n_obs_monthly", "value": str(len(monthly))},
                {"metric": "n_obs_quarterly", "value": str(usable)},
                {"metric": "ragged_edge", "value": str(self._ragged_edge(monthly))},
                {"metric": "seasonal_share", "value": f"{seasonal:.4f}"},
                {"metric": "last_month", "value": str(last_month)},
                {"metric": "target", "value": f"{self.target}@{self.entity}"},
                {"metric": "entity", "value": self.entity},
                {"metric": "asof", "value": str(ctx.asof)},
                {"metric": "vintage_kind", "value": str(ctx.vintage_kind)},
                {"metric": "seed", "value": str(ctx.seed)},
            ]
        )
        return TablesResult(
            _tables={
                "nowcast": nowcast,
                "factor": factor_table,
                "loadings": loadings,
                "diagnostics": diagnostics,
            }
        )
