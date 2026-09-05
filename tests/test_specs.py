"""Specifications as files, and the hash that keeps a stored run honest.

One model estimated many ways is the analysis, not a detour — and for the Phillips curve it is
the only defensible deliverable, because the primary literature says an aggregate time-series
regression does not identify the slope. A single number is not informative; a distribution over
specifications is. That only works if a specification is an object the store can group by.

The hash carries as much weight as the identifier. A run has to stay reproducible when the file
is edited later; without it, an edit silently re-labels every earlier run as belonging to the new
specification, and two different things get compared as one.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

from econmodels.specs import Spec, SpecError, hash_bytes, load_spec, load_specs

ROOT = Path(__file__).resolve().parents[1]

MINIMAL = {
    "spec_id": "toy",
    "model_id": "phillips",
    "entity": "BR",
    "provenance": {"follows": "nowhere in particular"},
    "dependent": {"concept": "cpi_free"},
    "terms": [
        {"name": "expectativa", "concept": "inflation_expectations_12m"},
        {"name": "folga", "concept": "activity_index", "lags": [1]},
    ],
}


def write(tmp_path: Path, body: dict, name: str | None = None) -> Path:
    path = tmp_path / f"{name or body['spec_id']}.yaml"
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


# ------------------------------------------------------------------ validation
def test_a_minimal_specification_loads(tmp_path: Path) -> None:
    spec = load_spec(write(tmp_path, MINIMAL))
    assert spec.spec_id == "toy"
    assert spec.estimation.method == "ols"
    assert spec.term("folga").lags == [1]


def test_a_field_nobody_recognises_is_refused(tmp_path: Path) -> None:
    """A typo in a specification is silent otherwise, and changes the analysis."""
    body = MINIMAL | {"estimaton": {"method": "ols"}}
    with pytest.raises(SpecError, match=r"estimaton|Extra"):
        load_spec(write(tmp_path, body))


def test_a_restriction_over_a_term_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    body = MINIMAL | {"restrictions": [{"kind": "sum_to_one", "over": ["expectativa", "inercia"]}]}
    with pytest.raises(SpecError, match="inercia"):
        load_spec(write(tmp_path, body))


def test_two_terms_may_not_share_a_name(tmp_path: Path) -> None:
    body = MINIMAL | {
        "terms": [
            {"name": "folga", "concept": "activity_index"},
            {"name": "folga", "concept": "unemployment_rate"},
        ]
    }
    with pytest.raises(SpecError, match="share a name"):
        load_spec(write(tmp_path, body))


def test_a_negative_lag_is_refused(tmp_path: Path) -> None:
    """A lead is not a lag with a minus sign; it changes what the equation claims."""
    body = MINIMAL | {"terms": [{"name": "folga", "concept": "activity_index", "lags": [-1]}]}
    with pytest.raises(SpecError, match="negative lag"):
        load_spec(write(tmp_path, body))


def test_an_empty_lag_list_is_refused(tmp_path: Path) -> None:
    body = MINIMAL | {"terms": [{"name": "folga", "concept": "activity_index", "lags": []}]}
    with pytest.raises(SpecError, match="empty lag"):
        load_spec(write(tmp_path, body))


def test_the_file_name_must_match_the_identifier(tmp_path: Path) -> None:
    """So a run can be traced to a file without opening every one."""
    with pytest.raises(SpecError, match="file name"):
        load_spec(write(tmp_path, MINIMAL, name="outro_nome"))


def test_a_file_that_is_not_yaml_says_so(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("spec_id: [unclosed\n", encoding="utf-8")
    with pytest.raises(SpecError, match="not valid YAML"):
        load_spec(path)


# ------------------------------------------------------------------ the hash
def test_editing_the_file_changes_the_hash(tmp_path: Path) -> None:
    """The whole point: an edited file must not re-label the runs that came before it."""
    first = load_spec(write(tmp_path, MINIMAL))
    edited = MINIMAL | {"estimation": {"method": "ols", "cov": "nonrobust"}}
    second = load_spec(write(tmp_path, edited))
    assert first.spec_id == second.spec_id
    assert first.spec_hash != second.spec_hash


def test_the_same_bytes_give_the_same_hash() -> None:
    assert hash_bytes(b"x") == hash_bytes(b"x") != hash_bytes(b"y")


def test_the_hash_is_short_enough_to_read_in_a_table() -> None:
    assert len(hash_bytes(b"x")) == 16


# ------------------------------------------------------------------ collections
def test_two_files_may_not_declare_the_same_identifier(tmp_path: Path) -> None:
    write(tmp_path, MINIMAL)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "toy.yaml").write_text(
        yaml.safe_dump(MINIMAL, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(SpecError, match="two files declare"):
        load_specs(tmp_path)


def test_a_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    assert load_specs(tmp_path / "nao-existe") == {}


def test_loading_can_be_narrowed_to_one_model(tmp_path: Path) -> None:
    write(tmp_path, MINIMAL)
    write(tmp_path, MINIMAL | {"spec_id": "other", "model_id": "taylor"})
    assert set(load_specs(tmp_path, model_id="phillips")) == {"toy"}


def test_the_concepts_come_back_with_the_dependent_first_and_no_repeats(tmp_path: Path) -> None:
    body = MINIMAL | {
        "terms": [
            {"name": "inercia", "concept": "cpi_free", "lags": [1]},
            {"name": "folga", "concept": "activity_index"},
        ]
    }
    spec = load_spec(write(tmp_path, body))
    assert spec.concepts() == [("cpi_free", "BR"), ("activity_index", "BR")]


def test_a_term_may_name_another_country(tmp_path: Path) -> None:
    body = MINIMAL | {
        "terms": [{"name": "externo", "concept": "policy_rate", "entity": "US"}],
        "restrictions": [],
    }
    spec = load_spec(write(tmp_path, body))
    assert ("policy_rate", "US") in spec.concepts()


# ------------------------------------------------------------------ the real ones
@pytest.fixture(scope="module")
def shipped() -> dict[str, Spec]:
    return load_specs(ROOT / "specs")


def test_the_specifications_in_the_repository_all_load(shipped: dict[str, Spec]) -> None:
    assert shipped, "there should be at least the two Phillips specifications"


def test_every_specification_says_where_it_comes_from(shipped: dict[str, Spec]) -> None:
    """Including the one whose provenance is 'nowhere' — that is the honest answer, not a blank."""
    for spec in shipped.values():
        assert spec.provenance.follows.strip(), f"{spec.spec_id} has no provenance"


def test_the_bank_specification_imposes_verticality(shipped: dict[str, Spec]) -> None:
    spec = shipped["br_bcb_small_scale"]
    kinds = [r.kind for r in spec.restrictions]
    assert "sum_to_one" in kinds, "the Bank writes the expectations weight as one minus the rest"
    assert spec.dependent.concept == "cpi_free", "the Bank explains free prices, not headline"


def test_the_exploratory_specification_is_kept_as_a_negative_control(
    shipped: dict[str, Spec],
) -> None:
    """It is wrong on purpose, and the file has to say so or it looks like an oversight."""
    spec = shipped["br_exploratoria_hp"]
    assert not spec.restrictions, "it is the one without the verticality restriction"
    assert spec.dependent.concept == "cpi_headline"
    assert "controle negativo" in (spec.provenance.follows + (spec.provenance.departs or ""))


# ------------------------------------------------------------------ what a run records
def test_a_saved_run_records_which_specification_produced_it(tmp_path: Path, store) -> None:
    import pandas as pd

    from econmodels.base import TablesResult
    from econmodels.results import list_runs, save_result

    spec = load_spec(write(tmp_path, MINIMAL))
    result = TablesResult(
        _tables={"coefficients": pd.DataFrame({"name": ["a"], "estimate": [1.0]})}
    )
    run_id = save_result(
        store,
        result,
        model_id="phillips",
        model_version="1",
        asof=dt.date(2026, 9, 5),
        entity_id="BR",
        spec=spec,
    )
    row = list_runs(store).set_index("model_run_id").loc[run_id]
    assert row["spec_id"] == "toy"
    assert row["spec_hash"] == spec.spec_hash


def test_two_specifications_of_one_model_are_two_comparable_rows(tmp_path: Path, store) -> None:
    """The shape the comparison needs: group by spec_id, not unpack JSON."""
    import pandas as pd

    from econmodels.base import TablesResult
    from econmodels.results import list_runs, save_result

    frame = pd.DataFrame({"name": ["beta"], "estimate": [0.1]})
    for spec_id in ("toy", "toy_b"):
        spec = load_spec(write(tmp_path, MINIMAL | {"spec_id": spec_id}))
        save_result(
            store,
            TablesResult(_tables={"coefficients": frame}),
            model_id="phillips",
            model_version="1",
            asof=dt.date(2026, 9, 5),
            spec=spec,
        )
    assert set(list_runs(store, model_id="phillips")["spec_id"]) == {"toy", "toy_b"}
