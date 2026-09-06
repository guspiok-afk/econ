"""Reconstructing what was known, for the series whose history does not record it.

Phase five is a nowcasting backtest, and until this module existed it could not run on Brazil at
all. Every Brazilian series carries one `realtime_start` — the day this project collected it — so
asking as of any past date returned **zero rows**, silently. An empty panel reads as a modelling
choice rather than as a missing capability, which is the worst way for a limitation to present
itself.

The simulation reconstructs the missing half from `expected_lag_days`, and the tests below draw
the line it must not cross: it can say *when* a figure became known and can never invent *what*
was first said. Where a source publishes real vintages the recorded ones win, and `mixed` says
which series used which so a write-up cannot blur them.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from econbase.api import Api, ApiError
from econbase.pipeline import _period_end
from econbase.vintages import (
    Availability,
    VintageError,
    availability,
    describe_split,
    pseudo_asof,
    published_at,
)


class Spec:
    """The handful of catalog fields the simulator reads."""

    def __init__(self, freq: str = "M", lag: int | None = 12, vintages: bool | None = None) -> None:
        self.series_id = "toy:1"
        self.freq = freq
        self.expected_lag_days = lag
        self.params = {} if vintages is None else {"vintages": vintages}


def rows(periods: list[str], starts: list[str] | None = None) -> pd.DataFrame:
    starts = starts or ["2026-09-03"] * len(periods)
    return pd.DataFrame(
        {
            "period": [dt.date.fromisoformat(p) for p in periods],
            "value": [1.0] * len(periods),
            "realtime_start": [dt.date.fromisoformat(s) for s in starts],
            "realtime_end": [None] * len(periods),
        }
    )


# ------------------------------------------------------------------ when a period became known
def test_a_monthly_figure_is_known_after_the_month_ends_plus_the_lag() -> None:
    """May's IPCA, twelve days after the end of May."""
    assert published_at(dt.date(2024, 5, 1), Spec(freq="M", lag=12)) == dt.date(2024, 6, 12)


def test_a_quarterly_figure_waits_for_the_quarter_to_end() -> None:
    assert published_at(dt.date(2024, 4, 1), Spec(freq="Q", lag=30)) == dt.date(2024, 7, 30)


def test_a_series_without_a_declared_lag_cannot_be_simulated() -> None:
    assert published_at(dt.date(2024, 1, 1), Spec(lag=None)) is None
    with pytest.raises(VintageError, match="expected_lag_days"):
        pseudo_asof(rows(["2024-01-01"]), Spec(lag=None), dt.date(2024, 6, 1))


# ------------------------------------------------------------------ the simulation itself
def test_only_what_had_been_published_comes_back() -> None:
    frame = rows(["2024-03-01", "2024-04-01", "2024-05-01", "2024-06-01"])
    out = pseudo_asof(frame, Spec(freq="M", lag=12), dt.date(2024, 6, 30))
    assert [str(p) for p in out["period"]] == ["2024-03-01", "2024-04-01", "2024-05-01"]


def test_the_boundary_day_counts_as_published() -> None:
    """Published on the twelfth, known on the twelfth: an exclusive bound loses a month."""
    frame = rows(["2024-05-01"])
    assert len(pseudo_asof(frame, Spec(freq="M", lag=12), dt.date(2024, 6, 12))) == 1
    assert len(pseudo_asof(frame, Spec(freq="M", lag=12), dt.date(2024, 6, 11))) == 0


def test_nothing_published_yet_is_an_empty_frame_and_not_an_error() -> None:
    frame = rows(["2024-05-01"])
    assert pseudo_asof(frame, Spec(), dt.date(2020, 1, 1)).empty


def test_an_empty_history_stays_empty() -> None:
    assert pseudo_asof(rows([]), Spec(), dt.date(2024, 1, 1)).empty


# ------------------------------------------------------------------ which kind a series has
def test_the_catalog_declaration_decides() -> None:
    """Not the row count. A vintaged series whose rows share a collection date is still vintaged,
    and inferring from the rows made exactly that mistake on a fixture."""
    frame = rows(["2024-01-01", "2024-02-01"])
    assert availability(frame, Spec(vintages=True)).has_true_vintages
    assert not availability(frame, Spec(vintages=False)).has_true_vintages


def test_without_a_declaration_there_are_no_true_vintages_whatever_the_rows_look_like() -> None:
    """The heuristic that used to live here was live-wrong, and wrong in the silent direction.

    It read "more than one distinct realtime_start" as revision history. But every daily run
    stamps the periods it newly finds with today's date, so an ordinary daily series grows a new
    realtime_start every day it collects: `bcb_sgs:432` had three after three days. That made
    `mixed` resolve to `true`, ask the store for a 2024 vintage that never existed, and return an
    empty frame with no error — the exact failure this module exists to end.

    Guessing toward `pseudo` costs a simulation where a real history existed. Guessing toward
    `true` costs an empty panel that reads as a modelling result. Only the catalog decides now.
    """
    one_collection = rows(["2024-01-01", "2024-02-01"])
    assert not availability(one_collection, Spec()).has_true_vintages

    looks_revised = rows(["2024-01-01", "2024-01-01"], ["2024-02-15", "2024-03-15"])
    assert not availability(looks_revised, Spec()).has_true_vintages
    assert availability(looks_revised, Spec(vintages=True)).has_true_vintages


def test_the_usable_kind_follows_from_what_exists() -> None:
    assert Availability("x", True, None, 12).usable_kind == "true"
    assert Availability("x", False, None, 12).usable_kind == "pseudo"


def test_the_split_is_summarised_for_a_diagnostics_table() -> None:
    assert describe_split({"a": "true", "b": "pseudo", "c": "pseudo"}) == "pseudo:2, true:1"
    assert describe_split({}) == "none"


# ------------------------------------------------------------------ through the read API
def test_an_unknown_kind_is_refused(loaded: Api) -> None:
    with pytest.raises(ApiError, match="vintage_kind"):
        loaded.get("gdp_real", entity="US", asof="2024-06-30", vintage_kind="invented")


def test_true_vintages_are_used_where_the_source_publishes_them(loaded: Api) -> None:
    early = loaded.get("gdp_real", entity="US", asof="2024-06-30", vintage_kind="true")
    late = loaded.get("gdp_real", entity="US", vintage_kind="latest")
    assert 0 < len(early) < len(late)


def test_asking_before_a_series_was_ever_collected_says_why(loaded: Api) -> None:
    """The failure this module exists to end: zero rows, no reason, looks like a modelling choice.

    A series with no recorded vintages has one date on record — the day collection ran — and an
    as-of before it is answering a question the data cannot answer. Saying so, and naming the two
    kinds that can answer it, is the whole difference.
    """
    with pytest.raises(VintageError, match="pseudo"):
        loaded.get("govt_yield_10y", entity="US", asof="2020-01-01", vintage_kind="true")


def test_pseudo_answers_where_true_cannot(loaded: Api) -> None:
    everything = loaded.get("govt_yield_10y", entity="US")
    midpoint = list(everything["period"])[len(everything) // 2]

    out = loaded.get("govt_yield_10y", entity="US", asof=midpoint, vintage_kind="pseudo")
    assert 0 < len(out) < len(everything)
    assert out["period"].max() <= midpoint


def test_mixed_takes_the_recorded_history_where_it_exists(loaded: Api) -> None:
    true_only = loaded.get("gdp_real", entity="US", asof="2024-06-30", vintage_kind="true")
    mixed = loaded.get("gdp_real", entity="US", asof="2024-06-30", vintage_kind="mixed")
    pd.testing.assert_frame_equal(true_only, mixed)


def test_latest_ignores_the_asof_entirely(loaded: Api) -> None:
    asked = loaded.get("gdp_real", entity="US", asof="2020-01-01", vintage_kind="latest")
    plain = loaded.get("gdp_real", entity="US")
    pd.testing.assert_frame_equal(asked, plain)


def test_a_panel_can_mix_the_two_kinds(loaded: Api) -> None:
    panel = loaded.get_panel(
        [("gdp_real", "US"), ("govt_yield_10y", "US")],
        asof="2024-06-30",
        vintage_kind="mixed",
        freq="Q",
        agg="mean",
    )
    assert not panel.empty
    assert panel.index.max() <= pd.Timestamp("2024-06-30")


def test_no_simulated_row_could_have_been_unknown(loaded: Api) -> None:
    """Rewritten after a review called the first version circular, correctly.

    It used to take the rows `pseudo_asof` returned and assert `published_at(period) <= asof` —
    the very condition the function had just filtered on. Break `published_at` (flip the sign of
    the lag, or have it always answer 1900-01-01) and the function returns corrupted rows while
    the test cheerfully re-derives the same broken arithmetic and passes.

    The claim is now checked against something the function does not compute: the calendar. A
    monthly period cannot be known before the month it covers has even ended.
    """
    everything = loaded.get("govt_yield_10y", entity="US")
    asof = list(everything["period"])[len(everything) // 2]
    out = loaded.get("govt_yield_10y", entity="US", asof=asof, vintage_kind="pseudo")

    assert not out.empty
    spec = loaded.resolve("govt_yield_10y", "US").spec
    for period in out["period"]:
        assert period <= asof, "a period cannot begin after the date it is claimed to be known"
        assert _period_end(period, spec.freq) <= asof, "nor can it still be running"


def test_a_daily_series_collected_for_three_days_is_not_mistaken_for_a_vintaged_one() -> None:
    """The live bug, in the shape it actually took.

    `bcb_sgs:432` is collected every day and every run stamps the newly found periods with that
    day's date. Three days of ordinary operation gave it three distinct `realtime_start` values,
    the old heuristic read that as revision history, and asking the Brazilian policy rate as of
    June 2024 came back as zero rows with no error.
    """
    three_days = rows(
        ["2026-09-04", "2026-09-05", "2026-09-06"],
        ["2026-09-04", "2026-09-05", "2026-09-06"],
    )
    have = availability(three_days, Spec(freq="D", lag=1))
    assert not have.has_true_vintages
    assert have.usable_kind == "pseudo", "pseudo answers; true would have returned nothing"
