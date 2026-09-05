"""Phillips curve estimation for Brazil (and expandable to other countries)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.filters.hp_filter import hpfilter

from econmodels.base import (
    ConceptRequest,
    Result,
    RunContext,
    TablesResult,
    panel_for,
    register,
    series_for,
)
from econmodels.specs import Spec


def _annualised_quarterly(s: pd.Series) -> pd.Series:
    """Compound a quarterly percentage rate into an annual percentage rate."""
    return ((1.0 + s / 100.0) ** 4 - 1.0) * 100.0


def _log_diff(s: pd.Series) -> pd.Series:
    """100 times log difference."""
    return 100.0 * (np.log(s) - np.log(s.shift(1)))


def _hamilton_gap(s: pd.Series, h: int = 8, p: int = 4) -> pd.Series:
    """Hamilton (2018) filter gap: regression of y_t on constant and y_{t-h}...y_{t-h-p+1}."""
    clean = s.dropna()
    if clean.empty:
        return s
    y = 100.0 * np.log(clean) if ((clean > 0).all() and clean.mean() > 20) else clean
    lags = pd.concat([y.shift(i) for i in range(h, h + p)], axis=1).dropna()
    if len(lags) < p + 5:
        return pd.Series(index=s.index, dtype=float)
    X = sm.add_constant(lags)
    y_sub = y.reindex(X.index)
    res = sm.OLS(y_sub, X).fit()
    cycle = pd.Series(res.resid, index=X.index)
    return cycle.reindex(s.index)


def _hp_gap(s: pd.Series, lamb: float = 1600.0) -> pd.Series:
    """Hodrick-Prescott filter cycle."""
    clean = s.dropna()
    if len(clean) < 8:
        return pd.Series(index=s.index, dtype=float)
    y = 100.0 * np.log(clean) if ((clean > 0).all() and clean.mean() > 20) else clean
    cycle, _ = hpfilter(y, lamb=lamb)
    return pd.Series(cycle, index=clean.index).reindex(s.index)


def _apply_transform(s: pd.Series, transform_name: str | None) -> pd.Series:
    if transform_name == "annualised_quarterly":
        return _annualised_quarterly(s)
    if transform_name == "log_diff":
        return _log_diff(s)
    if transform_name == "hamilton_gap":
        return _hamilton_gap(s)
    if transform_name == "hp_gap":
        return _hp_gap(s)
    if transform_name is None or transform_name == "":
        return s
    raise ValueError(f"unknown transform {transform_name!r}")


@register
class PhillipsCurve:
    model_id = "phillips"
    model_version = "1"

    def __init__(self, spec: Spec) -> None:
        self.spec = spec

    @property
    def requires(self) -> Sequence[ConceptRequest]:
        return [
            ConceptRequest(concept=concept, entity=entity, freq="Q")
            for concept, entity in self.spec.concepts()
        ]

    def _build_transformed_series(
        self, panel: pd.DataFrame
    ) -> tuple[pd.Series, dict[str, pd.Series]]:
        default_entity = self.spec.entity
        dep_s = series_for(
            panel,
            self.spec.dependent.concept,
            self.spec.dependent.entity or default_entity,
        )
        dep_transformed = _apply_transform(dep_s, self.spec.dependent.transform)

        terms_dict: dict[str, pd.Series] = {}
        for term in self.spec.terms:
            s = series_for(panel, term.concept, term.entity or default_entity)
            s_trans = _apply_transform(s, term.transform)
            if len(term.lags) == 1:
                t_series = s_trans.shift(term.lags[0])
            else:
                t_series = pd.concat([s_trans.shift(lag) for lag in term.lags], axis=1).mean(axis=1)
            terms_dict[term.name] = t_series

        return dep_transformed, terms_dict

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        panel_for(self, panel, entity=self.spec.entity)

        if len(panel) < 12:
            raise ValueError(f"Sample has fewer than 12 usable observations ({len(panel)})")

        dep_s, terms_dict = self._build_transformed_series(panel)

        reg_data = pd.DataFrame({"Y": dep_s, **terms_dict})

        if self.spec.sample.start:
            reg_data = reg_data[reg_data.index >= pd.Timestamp(self.spec.sample.start)]
        if self.spec.sample.end:
            reg_data = reg_data[reg_data.index <= pd.Timestamp(self.spec.sample.end)]

        reg_data = reg_data.dropna()

        if len(reg_data) < 12:
            raise ValueError(
                f"Sample has fewer than 12 usable observations after trimming ({len(reg_data)})"
            )

        # Identify sum_to_one restriction if present
        sum_restriction = None
        for r in self.spec.restrictions:
            if r.kind == "sum_to_one":
                sum_restriction = r
                break

        weights = None
        if self.spec.estimation.method == "wls":
            w = pd.Series(1.0, index=reg_data.index)
            w.loc["2020-04-01":"2022-12-31"] = 1.0 / 9.0
            weights = w

        cov_type = "HAC" if self.spec.estimation.cov == "newey_west" else "nonrobust"
        cov_kwds = {"maxlags": self.spec.estimation.maxlags or 4} if cov_type == "HAC" else None

        term_names = [t.name for t in self.spec.terms]

        if sum_restriction is not None:
            over_terms = list(sum_restriction.over)
            exp_term_name = None
            for t_name in over_terms:
                t_concept = self.spec.term(t_name).concept
                if t_name == "expectativa" or "inflation_expectations" in t_concept:
                    exp_term_name = t_name
                    break
            if exp_term_name is None:
                exp_term_name = over_terms[0]

            E = reg_data[exp_term_name]
            lhs = reg_data["Y"] - E

            other_over_terms = [t for t in over_terms if t != exp_term_name]
            other_terms = [t for t in term_names if t not in over_terms]

            X_dict: dict[str, Any] = {"const": 1.0}
            for t in other_over_terms:
                X_dict[t] = reg_data[t] - E
            for t in other_terms:
                X_dict[t] = reg_data[t]

            X = pd.DataFrame(X_dict, index=reg_data.index)

            if weights is not None:
                res_restricted = sm.WLS(lhs, X, weights=weights).fit(
                    cov_type=cov_type, cov_kwds=cov_kwds
                )
            else:
                res_restricted = sm.OLS(lhs, X).fit(cov_type=cov_type, cov_kwds=cov_kwds)

            estimates = {}
            std_errors = {}
            t_stats = {}

            for col in X.columns:
                if col == "const":
                    continue
                estimates[col] = float(res_restricted.params[col])
                std_errors[col] = float(res_restricted.bse[col])
                t_stats[col] = float(res_restricted.tvalues[col])

            sum_other = sum(estimates[t] for t in other_over_terms)
            exp_estimate = 1.0 - sum_other

            if other_over_terms:
                cov_sub = res_restricted.cov_params().loc[other_over_terms, other_over_terms]
                var_exp = float(cov_sub.values.sum())
                exp_se = float(np.sqrt(max(0.0, var_exp)))
            else:
                exp_se = 0.0

            exp_tstat = exp_estimate / exp_se if exp_se > 0 else float("nan")

            estimates[exp_term_name] = exp_estimate
            std_errors[exp_term_name] = exp_se
            t_stats[exp_term_name] = exp_tstat

            inflation_weights_sum = 1.0

            fitted_vals = res_restricted.fittedvalues + E
            residuals = reg_data["Y"] - fitted_vals

            # Unrestricted model for Wald test diagnostic
            X_unrest_dict: dict[str, Any] = {"const": 1.0}
            for t in term_names:
                X_unrest_dict[t] = reg_data[t]
            X_unrest = pd.DataFrame(X_unrest_dict, index=reg_data.index)

            if weights is not None:
                res_unrest = sm.WLS(reg_data["Y"], X_unrest, weights=weights).fit(
                    cov_type=cov_type, cov_kwds=cov_kwds
                )
            else:
                res_unrest = sm.OLS(reg_data["Y"], X_unrest).fit(
                    cov_type=cov_type, cov_kwds=cov_kwds
                )

            r_hypothesis = " + ".join(over_terms) + " = 1"
            wald_test = res_unrest.t_test(r_hypothesis)
            wald_pvalue = float(np.squeeze(wald_test.pvalue))

        else:
            X_dict = {"const": 1.0}
            for t in term_names:
                X_dict[t] = reg_data[t]
            X = pd.DataFrame(X_dict, index=reg_data.index)

            if weights is not None:
                res = sm.WLS(reg_data["Y"], X, weights=weights).fit(
                    cov_type=cov_type, cov_kwds=cov_kwds
                )
            else:
                res = sm.OLS(reg_data["Y"], X).fit(cov_type=cov_type, cov_kwds=cov_kwds)

            estimates = {t: float(res.params[t]) for t in term_names}
            std_errors = {t: float(res.bse[t]) for t in term_names}
            t_stats = {t: float(res.tvalues[t]) for t in term_names}

            fitted_vals = res.fittedvalues
            residuals = reg_data["Y"] - fitted_vals

            inflation_terms = [
                t.name
                for t in self.spec.terms
                if t.concept.startswith("cpi_") or "inflation_expectations" in t.concept
            ]
            inflation_weights_sum = sum(estimates[t] for t in inflation_terms)

            if inflation_terms:
                r_hypothesis = " + ".join(inflation_terms) + " = 1"
                wald_test = res.t_test(r_hypothesis)
                wald_pvalue = float(np.squeeze(wald_test.pvalue))
            else:
                wald_pvalue = float("nan")

        ss_res = np.sum((reg_data["Y"] - fitted_vals) ** 2)
        ss_tot = np.sum((reg_data["Y"] - reg_data["Y"].mean()) ** 2)
        r_squared = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        n_oos, rmse_oos, rmse_oos_exp, rmse_oos_rw = self._compute_oos_metrics(panel, reg_data)

        coef_rows = []
        for t in term_names:
            coef_rows.append(
                {
                    "name": t,
                    "estimate": estimates[t],
                    "std_error": std_errors[t],
                    "t_stat": t_stats[t],
                }
            )
        coef_df = pd.DataFrame(coef_rows)

        fitted_df = pd.DataFrame(
            {
                "period": reg_data.index,
                "actual": reg_data["Y"].values,
                "fitted": fitted_vals.values,
                "residual": residuals.values,
            }
        ).reset_index(drop=True)

        diag_rows = [
            {"metric": "n_obs", "value": float(len(reg_data))},
            {"metric": "r_squared", "value": r_squared},
            {"metric": "inflation_weights_sum", "value": float(inflation_weights_sum)},
            {"metric": "wald_verticality_pvalue", "value": float(wald_pvalue)},
            {"metric": "n_oos", "value": float(n_oos)},
            {"metric": "rmse_oos", "value": float(rmse_oos)},
            {"metric": "rmse_oos_expectations", "value": float(rmse_oos_exp)},
            {"metric": "rmse_oos_random_walk", "value": float(rmse_oos_rw)},
            {"metric": "spec_id", "value": str(self.spec.spec_id)},
            {"metric": "spec_hash", "value": str(self.spec.spec_hash)},
        ]
        diag_df = pd.DataFrame(diag_rows)

        tables = {
            "coefficients": coef_df,
            "fitted": fitted_df,
            "diagnostics": diag_df,
        }

        return TablesResult(_tables=tables)

    def _compute_oos_metrics(
        self, panel: pd.DataFrame, reg_data_full: pd.DataFrame
    ) -> tuple[int, float, float, float]:
        """Expanding window pseudo-out-of-sample forecast evaluation from 2015-01-01."""
        default_entity = self.spec.entity
        dep_s = series_for(
            panel,
            self.spec.dependent.concept,
            self.spec.dependent.entity or default_entity,
        )
        dep_transformed = _apply_transform(dep_s, self.spec.dependent.transform)

        terms_dict: dict[str, pd.Series] = {}
        for term in self.spec.terms:
            s = series_for(panel, term.concept, term.entity or default_entity)
            if term.concept == "activity_index":
                s_trans = _hp_gap(s)
            else:
                s_trans = _apply_transform(s, term.transform)
            if len(term.lags) == 1:
                t_series = s_trans.shift(term.lags[0])
            else:
                t_series = pd.concat([s_trans.shift(lag) for lag in term.lags], axis=1).mean(axis=1)
            terms_dict[term.name] = t_series

        reg_data = pd.DataFrame({"Y": dep_transformed, **terms_dict})
        if self.spec.sample.start:
            reg_data = reg_data[reg_data.index >= pd.Timestamp(self.spec.sample.start)]

        eval_dates = reg_data[reg_data.index >= pd.Timestamp("2015-01-01")].index

        errs_model: list[float] = []
        errs_exp: list[float] = []
        errs_rw: list[float] = []

        exp_term = None
        first_lag_term = None
        for t in self.spec.terms:
            if "inflation_expectations" in t.concept or t.name == "expectativa":
                exp_term = t.name
            if t.lags and 1 in t.lags and t.concept == self.spec.dependent.concept:
                first_lag_term = t.name

        if exp_term is None:
            exp_term = self.spec.terms[0].name
        if first_lag_term is None:
            first_lag_term = exp_term

        for t in eval_dates:
            train = reg_data[reg_data.index < t].dropna()
            if len(train) < 12 or t not in reg_data.index:
                continue

            row_t = reg_data.loc[t]
            if row_t.isna().any():
                continue

            sum_restriction = None
            for r in self.spec.restrictions:
                if r.kind == "sum_to_one":
                    sum_restriction = r
                    break

            weights = None
            if self.spec.estimation.method == "wls":
                w = pd.Series(1.0, index=train.index)
                w.loc["2020-04-01":"2022-12-31"] = 1.0 / 9.0
                weights = w

            term_names = [tm.name for tm in self.spec.terms]

            if sum_restriction is not None:
                over_terms = list(sum_restriction.over)
                exp_term_name = None
                for t_name in over_terms:
                    t_concept = self.spec.term(t_name).concept
                    if t_name == "expectativa" or "inflation_expectations" in t_concept:
                        exp_term_name = t_name
                        break
                if exp_term_name is None:
                    exp_term_name = over_terms[0]

                E_train = train[exp_term_name]
                lhs_train = train["Y"] - E_train
                other_over_terms = [tm for tm in over_terms if tm != exp_term_name]
                other_terms = [tm for tm in term_names if tm not in over_terms]

                X_train_dict: dict[str, Any] = {"const": 1.0}
                for tm in other_over_terms:
                    X_train_dict[tm] = train[tm] - E_train
                for tm in other_terms:
                    X_train_dict[tm] = train[tm]

                X_train = pd.DataFrame(X_train_dict, index=train.index)

                if weights is not None:
                    res_m = sm.WLS(lhs_train, X_train, weights=weights).fit()
                else:
                    res_m = sm.OLS(lhs_train, X_train).fit()

                E_t = row_t[exp_term_name]
                X_t_dict: dict[str, Any] = {"const": 1.0}
                for tm in other_over_terms:
                    X_t_dict[tm] = row_t[tm] - E_t
                for tm in other_terms:
                    X_t_dict[tm] = row_t[tm]

                X_t = pd.Series(X_t_dict)
                pred_model = float(res_m.predict(X_t.to_frame().T).iloc[0]) + E_t

            else:
                X_train_dict = {"const": 1.0}
                for tm in term_names:
                    X_train_dict[tm] = train[tm]
                X_train = pd.DataFrame(X_train_dict, index=train.index)

                if weights is not None:
                    res_m = sm.WLS(train["Y"], X_train, weights=weights).fit()
                else:
                    res_m = sm.OLS(train["Y"], X_train).fit()

                X_t_dict = {"const": 1.0}
                for tm in term_names:
                    X_t_dict[tm] = row_t[tm]
                X_t = pd.Series(X_t_dict)
                pred_model = float(res_m.predict(X_t.to_frame().T).iloc[0])

            actual_t = float(row_t["Y"])
            pred_exp = float(row_t[exp_term])
            pred_rw = float(row_t[first_lag_term])

            errs_model.append(actual_t - pred_model)
            errs_exp.append(actual_t - pred_exp)
            errs_rw.append(actual_t - pred_rw)

        n_oos = len(errs_model)
        if n_oos == 0:
            return 0, float("nan"), float("nan"), float("nan")

        rmse_model = float(np.sqrt(np.mean(np.square(errs_model))))
        rmse_exp = float(np.sqrt(np.mean(np.square(errs_exp))))
        rmse_rw = float(np.sqrt(np.mean(np.square(errs_rw))))

        return n_oos, rmse_model, rmse_exp, rmse_rw
