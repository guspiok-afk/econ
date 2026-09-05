"""The audit behind the page, which is the only part of it that can be wrong quietly.

A chart that renders badly is obvious. An audit that cries wolf is worse than none, because the
reader stops looking — the first version of this one flagged forty of sixty-nine series and put
Brazilian hyperinflation and the April 2020 collapse in the same bucket as a corrupted tick.
These tests pin the distinctions that made it useful: a spike that reverts is worth a look, a
level shift that persists is history, and a flat stretch is only news when it is unusual for
that particular series.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from econbase.report import (
    FLAT_RUN,
    JUMP_FACTOR,
    Report,
    _audit,
    _chart_points,
    payload_for,
)


class Spec:
    """The handful of catalog fields the audit reads."""

    def __init__(self, freq: str = "M", unit: str = "pct") -> None:
        self.freq = freq
        self.unit = unit


def frame(values: list[float], start: str = "2000-01-01", freq: str = "MS") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq=freq)
    return pd.DataFrame({"period": [d.date() for d in idx], "value": values})


def kinds(findings) -> set[str]:
    return {f.kind for f in findings}


# ------------------------------------------------------------------ nothing to say
def test_a_healthy_series_produces_nothing() -> None:
    rng = np.random.default_rng(0)
    values = list(100 + np.cumsum(rng.normal(0, 0.5, 120)))
    assert _audit("s", Spec(), frame(values), "ok") == []


# ------------------------------------------------------------------ the spike distinction
def test_a_spike_that_reverts_is_flagged() -> None:
    values = [1.0] * 60
    values[30] = 1.0 + 40 * JUMP_FACTOR  # out and straight back
    found = _audit("s", Spec(), frame(values), "ok")
    assert "pico_isolado" in kinds(found)
    assert "2002-07" in next(f.message for f in found if f.kind == "pico_isolado")


def test_a_level_shift_that_persists_is_not_a_spike() -> None:
    """Hyperinflation, a currency reform and a rebased index all look like this, and are real."""
    values = [1.0] * 40 + [500.0] * 40
    assert "pico_isolado" not in kinds(_audit("s", Spec(), frame(values), "ok"))


def test_a_spike_is_reported_as_low_severity_because_it_may_be_history() -> None:
    """April 2020 is indistinguishable from a corrupted tick, so this can never be an alarm."""
    values = [1.0] * 60
    values[30] = 1.0 + 40 * JUMP_FACTOR
    spike = next(f for f in _audit("s", Spec(), frame(values), "ok") if f.kind == "pico_isolado")
    assert spike.severity == "baixo"


# ------------------------------------------------------------------ the flat distinction
def test_a_policy_rate_held_as_long_as_it_has_been_held_before_is_not_flagged() -> None:
    """A rate kept for a year is policy. The test is whether this stretch is unusual for it."""
    values = [10.0] * 20 + [11.0] * 20 + [12.0] * 20
    assert "estagnada" not in kinds(_audit("s", Spec(freq="M"), frame(values), "ok"))


def test_a_flat_stretch_longer_than_any_before_it_is_flagged() -> None:
    values = [10.0, 11.0] * 20 + [12.0] * (FLAT_RUN + 6)
    found = _audit("s", Spec(), frame(values), "ok")
    assert "estagnada" in kinds(found)


# ------------------------------------------------------------------ the plain failures
def test_a_series_with_no_rows_says_so() -> None:
    empty = pd.DataFrame({"period": [], "value": []})
    assert kinds(_audit("s", Spec(), empty, None)) == {"sem_dados"}


def test_a_series_of_only_nulls_says_so() -> None:
    found = _audit("s", Spec(), frame([float("nan")] * 30), "ok")
    assert kinds(found) == {"tudo_nulo"}


def test_a_stale_series_is_high_severity() -> None:
    found = _audit("s", Spec(), frame([1.0, 2.0, 3.0]), "stale")
    assert [f.severity for f in found if f.kind == "parada"] == ["alto"]


def test_a_hole_in_the_monthly_grid_is_flagged() -> None:
    values = frame([1.0] * 30)
    holed = values.drop(index=[10, 11, 12]).reset_index(drop=True)
    found = _audit("s", Spec(freq="M"), holed, "ok")
    assert "lacuna" in kinds(found)
    assert next(f for f in found if f.kind == "lacuna").severity == "alto"


def test_a_daily_series_is_not_measured_against_a_calendar_grid() -> None:
    """Weekends and holidays are not holes, and pretending otherwise flags every daily series."""
    values = frame([1.0] * 40, freq="B")
    assert "lacuna" not in kinds(_audit("s", Spec(freq="D"), values, "ok"))


# ------------------------------------------------------------------ the page itself
def test_the_chart_thins_a_long_series_without_inventing_points() -> None:
    values = frame([float(i) for i in range(5000)], freq="D")
    points = _chart_points(values, "D")
    assert 0 < len(points) <= 600
    assert points[0][0] < points[-1][0]
    assert all(isinstance(p[1], float) for p in points)


def test_a_restricted_series_keeps_its_metadata_and_loses_its_values() -> None:
    report = Report(generated_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC))
    report.series = [
        {"series_id": "a", "redistributable": True, "points": [["2020-01-01", 1.0]], "title": "A"},
        {"series_id": "b", "redistributable": False, "points": [["2020-01-01", 2.0]], "title": "B"},
    ]
    trimmed = payload_for(report, redistributable_only=True)
    by_id = {s["series_id"]: s for s in trimmed["series"]}
    assert by_id["a"]["points"] and not by_id["b"]["points"]
    assert by_id["b"]["title"] == "B", "metadata is not the restricted part"
    assert trimmed["trimmed"] is True


def test_the_page_reaches_no_network(tmp_path: Path) -> None:
    """It has to open from a pen drive, on a plane, in five years."""
    template = (Path("src/econbase/report_template.html")).read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "//cdn", "integrity="):
        assert forbidden not in template.replace('rel="noopener"', ""), (
            f"the template reaches out for {forbidden!r}; the page must be self-contained"
        )


def test_the_template_has_exactly_one_placeholder() -> None:
    template = (Path("src/econbase/report_template.html")).read_text(encoding="utf-8")
    assert template.count("__DATA__") == 1


@pytest.mark.parametrize("trimmed", [False, True])
def test_the_payload_is_json_serialisable(trimmed: bool) -> None:
    report = Report(generated_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC))
    report.series = [{"series_id": "a", "redistributable": True, "points": [], "title": "A"}]
    report.totals = {"series": 1}
    json.dumps(payload_for(report, redistributable_only=trimmed), default=str)
