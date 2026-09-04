"""Frequency conversion and rates of change."""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import pytest

from econbase import transforms
from econbase.transforms import TransformError


def frame(pairs: list[tuple[str, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        {"period": [dt.date.fromisoformat(p) for p, _ in pairs], "value": [v for _, v in pairs]}
    )


def monthly(n: int, start: str = "2024-01-01", step: float = 1.0, first: float = 100.0):
    periods = [d.date() for d in pd.date_range(start, periods=n, freq="MS")]
    return pd.DataFrame({"period": periods, "value": [first + i * step for i in range(n)]})


# ---------------------------------------------------------------------------- resampling
def test_monthly_to_quarterly_with_each_aggregation() -> None:
    f = monthly(6, "2024-01-01", step=1.0, first=10.0)  # 10..15
    last = transforms.resample(f, from_freq="M", to_freq="Q", agg="last")
    assert list(last["period"]) == [dt.date(2024, 1, 1), dt.date(2024, 4, 1)]
    assert list(last["value"]) == [12.0, 15.0]

    mean = transforms.resample(f, from_freq="M", to_freq="Q", agg="mean")
    assert list(mean["value"]) == [11.0, 14.0]

    total = transforms.resample(f, from_freq="M", to_freq="Q", agg="sum")
    assert list(total["value"]) == [33.0, 42.0]

    eop = transforms.resample(f, from_freq="M", to_freq="Q", agg="eop")
    assert list(eop["value"]) == list(last["value"]), "eop and last are synonyms here"


def test_daily_to_monthly_skips_days_that_do_not_exist() -> None:
    f = frame([("2026-01-02", 4.1), ("2026-01-05", 4.3), ("2026-02-02", 4.5)])
    out = transforms.resample(f, from_freq="B", to_freq="M", agg="mean")
    assert list(out["period"]) == [dt.date(2026, 1, 1), dt.date(2026, 2, 1)]
    assert math.isclose(float(out["value"].iloc[0]), 4.2)


def test_a_period_with_no_observation_is_dropped_not_filled() -> None:
    f = frame([("2024-01-01", 1.0), ("2024-07-01", 2.0)])
    out = transforms.resample(f, from_freq="M", to_freq="Q", agg="mean")
    assert list(out["period"]) == [dt.date(2024, 1, 1), dt.date(2024, 7, 1)]


def test_upsampling_is_refused_with_a_reason() -> None:
    f = frame([("2024-01-01", 1.0), ("2024-04-01", 2.0)])
    with pytest.raises(TransformError, match="cannot upsample"):
        transforms.resample(f, from_freq="Q", to_freq="M", agg="last")


def test_same_frequency_is_a_no_op() -> None:
    f = monthly(3)
    out = transforms.resample(f, from_freq="M", to_freq="M", agg="last")
    assert out.equals(f.reset_index(drop=True))


def test_an_unknown_aggregation_or_frequency_is_refused() -> None:
    f = monthly(3)
    with pytest.raises(TransformError, match="unknown aggregation"):
        transforms.resample(f, from_freq="M", to_freq="Q", agg="median")
    with pytest.raises(TransformError, match="unknown frequency"):
        transforms.resample(f, from_freq="M", to_freq="Z", agg="last")


# ---------------------------------------------------------------------------- rates of change
def test_month_on_month_and_year_on_year() -> None:
    f = frame([(f"2024-{m:02d}-01", 100.0 * (1.01 ** (m - 1))) for m in range(1, 13)])
    f = pd.concat([f, frame([("2025-01-01", 100.0 * 1.01**12)])], ignore_index=True)
    mom = transforms.pct_change(f, freq="M", horizon="period")
    assert math.isclose(float(mom["value"].iloc[1]), 1.0, abs_tol=1e-9)
    yoy = transforms.pct_change(f, freq="M", horizon="year")
    assert math.isnan(float(yoy["value"].iloc[0]))
    assert math.isclose(float(yoy["value"].iloc[-1]), (1.01**12 - 1) * 100, abs_tol=1e-9)


def test_annualizing_a_monthly_rate_compounds_it() -> None:
    f = frame([("2024-01-01", 100.0), ("2024-02-01", 101.0)])
    plain = transforms.pct_change(f, freq="M", horizon="period")
    ann = transforms.pct_change(f, freq="M", horizon="period", annualize=True)
    assert math.isclose(float(plain["value"].iloc[1]), 1.0)
    assert math.isclose(float(ann["value"].iloc[1]), (1.01**12 - 1) * 100, rel_tol=1e-9)


def test_a_quarterly_rate_annualizes_to_the_fourth_power() -> None:
    f = frame([("2024-01-01", 100.0), ("2024-04-01", 101.0)])
    ann = transforms.pct_change(f, freq="Q", horizon="period", annualize=True)
    assert math.isclose(float(ann["value"].iloc[1]), (1.01**4 - 1) * 100, rel_tol=1e-9)


def test_year_over_year_on_daily_data_is_refused() -> None:
    f = frame([("2026-01-02", 1.0), ("2026-01-03", 2.0)])
    with pytest.raises(TransformError, match="ambiguous"):
        transforms.pct_change(f, freq="B", horizon="year")


def test_log_difference_approximates_the_percentage_change_for_small_moves() -> None:
    f = frame([("2024-01-01", 100.0), ("2024-02-01", 100.5)])
    pct = float(transforms.pct_change(f, freq="M")["value"].iloc[1])
    log = float(transforms.log_diff(f, freq="M")["value"].iloc[1])
    assert math.isclose(pct, 0.5)
    assert math.isclose(log, 0.4987541511, abs_tol=1e-8)


def test_log_difference_of_a_non_positive_value_is_missing_not_an_error() -> None:
    f = frame([("2024-01-01", 100.0), ("2024-02-01", 0.0), ("2024-03-01", 100.0)])
    out = transforms.log_diff(f, freq="M")
    assert math.isnan(float(out["value"].iloc[1]))
    assert math.isnan(float(out["value"].iloc[2]))


def test_difference_and_lag() -> None:
    f = frame([("2024-01-01", 10.0), ("2024-02-01", 12.5)])
    assert math.isclose(float(transforms.diff(f)["value"].iloc[1]), 2.5)
    assert math.isclose(float(transforms.lag(f)["value"].iloc[1]), 10.0)


# ---------------------------------------------------------------------------- levels
def test_rebasing_moves_the_reference_period_to_one_hundred() -> None:
    f = frame([("2024-01-01", 200.0), ("2024-02-01", 220.0)])
    out = transforms.rebase(f, base="2024-01-01")
    assert list(out["value"]) == pytest.approx([100.0, 110.0])


def test_rebasing_on_a_period_that_is_not_there_is_refused() -> None:
    f = frame([("2024-01-01", 200.0)])
    with pytest.raises(TransformError, match="not in the series"):
        transforms.rebase(f, base="2023-01-01")


def test_deflating_keeps_only_the_periods_both_series_have() -> None:
    nominal = frame([("2024-01-01", 200.0), ("2024-02-01", 220.0), ("2024-03-01", 240.0)])
    prices = frame([("2024-01-01", 100.0), ("2024-02-01", 110.0)])
    real = transforms.deflate(nominal, prices)
    assert list(real["period"]) == [dt.date(2024, 1, 1), dt.date(2024, 2, 1)]
    assert list(real["value"]) == pytest.approx([200.0, 200.0]), "the rise was entirely prices"


# ---------------------------------------------------------------------------- registry
def test_the_named_transforms_match_their_functions() -> None:
    f = frame([("2024-01-01", 100.0), ("2024-02-01", 101.0)])
    assert math.isclose(
        float(transforms.apply(f, "mom", freq="M")["value"].iloc[1]),
        float(transforms.pct_change(f, freq="M")["value"].iloc[1]),
    )
    assert set(transforms.TRANSFORMS) == {
        "yoy",
        "mom",
        "mom_ann",
        "log_diff",
        "log_diff_ann",
        "diff",
    }


def test_an_unknown_transform_lists_the_ones_that_exist() -> None:
    with pytest.raises(TransformError, match="available:"):
        transforms.apply(monthly(2), "detrend", freq="M")


def test_an_empty_series_survives_every_transform() -> None:
    empty = pd.DataFrame({"period": [], "value": []})
    for name in transforms.TRANSFORMS:
        assert transforms.apply(empty, name, freq="M").empty
    assert transforms.resample(empty, from_freq="M", to_freq="Q", agg="last").empty


def test_compounding_is_the_right_way_to_aggregate_a_rate_of_change() -> None:
    """Three months of 0.67, 0.58 and 0.16 make a quarter of 1.4159%.

    Their average, 0.47, is a number with no economic meaning, and their sum, 1.41, misses the
    cross terms. Prices compound.
    """
    f = frame([("2026-04-01", 0.67), ("2026-05-01", 0.58), ("2026-06-01", 0.16)])
    out = transforms.resample(f, from_freq="M", to_freq="Q", agg="compound")
    assert list(out["period"]) == [dt.date(2026, 4, 1)]
    assert float(out["value"].iloc[0]) == pytest.approx(1.4159, abs=1e-4)

    plain_mean = float(
        transforms.resample(f, from_freq="M", to_freq="Q", agg="mean")["value"].iloc[0]
    )
    plain_sum = float(
        transforms.resample(f, from_freq="M", to_freq="Q", agg="sum")["value"].iloc[0]
    )
    assert plain_mean == pytest.approx(0.47)
    assert plain_sum == pytest.approx(1.41)


def test_compounding_handles_negative_rates_and_gaps() -> None:
    f = frame([("2026-01-01", 1.0), ("2026-02-01", -0.5), ("2026-03-01", None)])
    out = transforms.resample(f, from_freq="M", to_freq="Q", agg="compound")
    expected = ((1.01 * 0.995) - 1) * 100
    assert float(out["value"].iloc[0]) == pytest.approx(expected)


def test_compounding_a_quarter_with_no_data_yields_nothing() -> None:
    f = frame([("2026-01-01", 1.0), ("2026-07-01", 2.0)])
    out = transforms.resample(f, from_freq="M", to_freq="Q", agg="compound")
    assert list(out["period"]) == [dt.date(2026, 1, 1), dt.date(2026, 7, 1)]
