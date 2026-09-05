"""A result that cannot say where it came from is a rumour.

These tests are the reason the store exists: a saved run must carry the as-of date, the seed,
the parameters and the commit, and the tables must come back in the shape the model returned
them. The melted storage is an implementation detail that the round trip has to hide.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from econbase.store import Store
from econmodels.base import TablesResult
from econmodels.results import ResultsError, list_runs, load_result, save_result


@pytest.fixture
def result() -> TablesResult:
    return TablesResult(
        _tables={
            "coefficients": pd.DataFrame(
                {
                    "name": ["alpha", "beta"],
                    "estimate": [11.5822, -0.7251],
                    "std_error": [5.1999, 0.4784],
                }
            ),
            "diagnostics": pd.DataFrame(
                {"metric": ["n_obs", "r_squared"], "value": [308.0, 0.0368]}
            ),
            "fitted": pd.DataFrame(
                {
                    "period": [dt.date(2020, 1, 1), dt.date(2020, 2, 1)],
                    "predicted": [1.5, 2.5],
                }
            ),
        }
    )


def save(store: Store, result: TablesResult, **kw) -> str:
    defaults = dict(
        model_id="uip_fama",
        model_version="1",
        asof=dt.date(2026, 9, 4),
        seed=0,
        entity_id="BR",
        params={"horizon_months": 12},
    )
    return save_result(store, result, **(defaults | kw))


def test_a_saved_result_comes_back_in_the_shape_it_went_in(
    store: Store, result: TablesResult
) -> None:
    run_id = save(store, result)
    back = load_result(store, run_id)
    assert set(back) == {"coefficients", "diagnostics", "fitted"}
    assert list(back["coefficients"]["name"]) == ["alpha", "beta"]
    assert back["coefficients"]["estimate"].tolist() == pytest.approx([11.5822, -0.7251])
    assert back["diagnostics"]["value"].tolist() == pytest.approx([308.0, 0.0368])


def test_numbers_come_back_as_numbers_and_text_as_text(store: Store, result: TablesResult) -> None:
    """Melted storage puts both in one table; reading must not return the numbers as strings."""
    back = load_result(store, save(store, result))
    assert all(isinstance(v, float) for v in back["coefficients"]["estimate"])
    assert all(isinstance(v, str) for v in back["coefficients"]["name"])


def test_a_date_column_survives_the_round_trip(store: Store, result: TablesResult) -> None:
    back = load_result(store, save(store, result))
    assert list(back["fitted"]["period"]) == ["2020-01-01", "2020-02-01"]


def test_the_run_carries_the_provenance_that_makes_it_arguable(
    store: Store, result: TablesResult
) -> None:
    run_id = save(store, result)
    runs = list_runs(store)
    row = runs[runs["model_run_id"] == run_id].iloc[0]
    assert row["model_id"] == "uip_fama"
    assert row["asof"] == dt.date(2026, 9, 4)
    assert int(row["seed"]) == 0
    assert row["entity_id"] == "BR"
    assert json.loads(row["params"]) == {"horizon_months": 12}
    assert row["vintage_kind"] == "latest"


def test_two_runs_of_the_same_model_are_two_rows(store: Store, result: TablesResult) -> None:
    first = save(store, result)
    second = save(store, result, asof=dt.date(2026, 9, 3))
    assert first != second
    runs = list_runs(store, model_id="uip_fama")
    assert len(runs) == 2
    assert set(runs["asof"]) == {dt.date(2026, 9, 4), dt.date(2026, 9, 3)}


def test_a_second_model_does_not_disturb_the_first(store: Store, result: TablesResult) -> None:
    """Appending must carry forward what is already stored, or a run erases its predecessor."""
    first = save(store, result)
    save(store, result, model_id="taylor_rule", model_version="1", entity_id="US")
    assert set(list_runs(store)["model_id"]) == {"uip_fama", "taylor_rule"}
    assert load_result(store, first)["coefficients"].shape == (2, 3)


def test_asking_for_a_run_that_was_never_stored_says_so(store: Store) -> None:
    with pytest.raises(ResultsError, match="no stored run"):
        load_result(store, "20260904T000000Z-aaaaaa")


def test_a_model_that_returned_nothing_is_refused(store: Store) -> None:
    with pytest.raises(ResultsError, match="nothing to store"):
        save(store, TablesResult(_tables={}))


def test_listing_runs_of_one_model_leaves_the_others_out(
    store: Store, result: TablesResult
) -> None:
    save(store, result)
    save(store, result, model_id="taylor_rule")
    assert list(list_runs(store, model_id="taylor_rule")["model_id"]) == ["taylor_rule"]


def test_the_stored_run_is_readable_from_duckdb(store: Store, result: TablesResult) -> None:
    """The point of putting results in the lake rather than in a pickle beside it."""
    run_id = save(store, result)
    con = store.connect()
    try:
        n = con.sql(
            f"select count(*) from model_outputs where model_run_id = '{run_id}'"
        ).fetchone()[0]
    finally:
        con.close()
    assert n == 2 * 3 + 2 * 2 + 2 * 2
