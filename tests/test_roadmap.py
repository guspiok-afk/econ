"""The roadmap has to stay true, or it is worse than not having one.

`roadmap.yml` says which milestones are validated and which tests hold them up. A document that
claims a milestone is validated while the test naming it has been renamed, moved or deleted is a
document that lies with authority — and this repository has already been burned twice by exactly
that shape of problem: a merge that silently deleted 4,290 lines, and a panel that reported a
phase as pending while its six models were on main.

So the rule is mechanical. **A milestone marked `validado` must name at least one test file, and
every file it names must exist.** A milestone that is not yet validated may point at a test that
does not exist yet: that is a promise, and the promise becomes binding the moment the state
changes. Everything else here is ordinary schema checking.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "roadmap.yml"

VALID_STATES = {"validado", "em_revisao", "a_fazer", "bloqueado", "abandonado"}
SEVERITIES = {"alta", "media", "baixa"}
#: `mitigada` diz que o sintoma foi contido e a causa não: honesto, e diferente de fechada.
GAP_STATES = {"aberta", "mitigada", "despachada", "fechada"}


@pytest.fixture(scope="module")
def roadmap() -> dict:
    return yaml.safe_load(ROADMAP.read_text(encoding="utf-8"))


def test_the_roadmap_exists_and_parses(roadmap) -> None:
    assert roadmap["schema"] == "econ/roadmap/1"
    for section in ("projeto", "fases", "modulos", "lacunas", "decisoes", "validacao", "backlog"):
        assert section in roadmap, f"the roadmap has no {section!r} section"


# ------------------------------------------------------------------ the rule that matters
def test_every_validated_milestone_names_the_tests_that_hold_it(roadmap) -> None:
    """No `preso_por`, no `validado`. A milestone with nothing pinning it is asserted, not shown.

    Both defects found on 6 September 2026 -- the backtest reading the quarter it claimed to
    nowcast, and routine daily collection read as revision history -- sat behind a green suite
    because nothing tested the thing that was wrong.
    """
    bare = [
        m["id"] for m in roadmap["modulos"] if m["estado"] == "validado" and not m.get("preso_por")
    ]
    assert not bare, f"validated with nothing pinning them: {bare}"


def test_every_test_a_validated_milestone_names_exists(roadmap) -> None:
    missing = [
        (m["id"], path)
        for m in roadmap["modulos"]
        if m["estado"] == "validado"
        for path in m.get("preso_por", [])
        if not (ROOT / path).exists()
    ]
    assert not missing, f"validated milestones pointing at tests that are not there: {missing}"


def test_a_milestone_still_to_do_does_not_already_have_its_tests(roadmap) -> None:
    """The rule looking the other way, added after this file was wrong three times in a day.

    `preso_por` catches a validated milestone whose tests are gone. Nothing caught the opposite:
    a milestone described as pending whose work is already done and merged. On 6 September 2026
    that happened to M044, to M046, and to the interface phase — every time because the roadmap
    was written from memory of the plan rather than from the repository.

    A milestone still `a_fazer` whose named tests all exist is not proof that it is finished, but
    it is a strong enough smell to stop and look. Milestones with nothing named are untouched.
    """
    suspicious = [
        m["id"]
        for m in roadmap["modulos"]
        if m["estado"] == "a_fazer"
        and m.get("preso_por")
        and all((ROOT / path).exists() for path in m["preso_por"])
    ]
    assert not suspicious, (
        f"marked as still to do, but every test they name already exists: {suspicious}. "
        "Either the work is done and the state is stale, or the tests belong to another milestone."
    )


def test_a_validation_rule_names_a_file_that_exists(roadmap) -> None:
    """The `validacao` section is the short list of claims this project makes about itself. Each
    one names the test that earns it."""
    missing = [
        rule["fonte"]
        for rule in roadmap["validacao"]
        if not (ROOT / rule["fonte"].split("::")[0]).exists()
    ]
    assert not missing, f"validation rules with no such file: {missing}"


# ------------------------------------------------------------------ ordinary consistency
def test_milestone_ids_are_unique_and_states_are_known(roadmap) -> None:
    ids = [m["id"] for m in roadmap["modulos"]]
    assert len(ids) == len(set(ids)), "duplicate milestone id"
    unknown = {m["estado"] for m in roadmap["modulos"]} - VALID_STATES
    assert not unknown, f"unknown milestone states: {unknown}"


def test_every_milestone_belongs_to_a_declared_phase(roadmap) -> None:
    phases = {f["id"] for f in roadmap["fases"]}
    stray = {m["fase"] for m in roadmap["modulos"]} - phases
    assert not stray, f"milestones in phases that do not exist: {stray}"


def test_dependencies_point_at_milestones_that_exist(roadmap) -> None:
    ids = {m["id"] for m in roadmap["modulos"]}
    dangling = [
        (m["id"], dep)
        for m in roadmap["modulos"]
        for dep in m.get("depende_de", [])
        if dep not in ids
    ]
    assert not dangling, f"dependencies on milestones that do not exist: {dangling}"


def test_a_blocked_milestone_names_what_blocks_it(roadmap) -> None:
    gaps = {g["id"] for g in roadmap["lacunas"]}
    for milestone in roadmap["modulos"]:
        if milestone["estado"] != "bloqueado":
            continue
        blockers = milestone.get("bloqueado_por")
        assert blockers, f"{milestone['id']} is blocked by nothing in particular"
        unknown = set(blockers) - gaps
        assert not unknown, f"{milestone['id']} blocked by gaps that do not exist: {unknown}"


def test_every_gap_carries_a_severity(roadmap) -> None:
    unknown = {g["gravidade"] for g in roadmap["lacunas"]} - SEVERITIES
    assert not unknown, f"unknown severities: {unknown}"


def test_gap_states_are_known_and_mitigated_is_not_closed(roadmap) -> None:
    """`mitigada` is a state of its own on purpose.

    L02 is the case that forced it: a panel mixing recorded and simulated vintages now warns and
    labels every column, so the incoherence is visible -- and it is still there. Filing that as
    `fechada` would be the comfortable lie; leaving it `aberta` would hide that the symptom was
    contained. Neither is what happened.
    """
    unknown = {g.get("estado", "aberta") for g in roadmap["lacunas"]} - GAP_STATES
    assert not unknown, f"unknown gap states: {unknown}"
    mitigated = [g for g in roadmap["lacunas"] if g.get("estado") == "mitigada"]
    for gap in mitigated:
        assert "MITIGADA" in gap.get("nota", ""), (
            f"{gap['id']} is filed as mitigated without saying what remains"
        )


def test_every_decision_says_when_it_would_be_reopened(roadmap) -> None:
    """A decision without a trigger is a habit. The trigger is what makes it revisitable."""
    silent = [d["id"] for d in roadmap["decisoes"] if not d.get("reabrir_quando")]
    assert not silent, f"decisions with no reopening trigger: {silent}"


def test_a_document_a_decision_cites_exists(roadmap) -> None:
    missing = [
        (d["id"], d["arquivo"])
        for d in roadmap["decisoes"]
        if d.get("arquivo") and not (ROOT / d["arquivo"]).exists()
    ]
    assert not missing, f"decisions citing documents that are not there: {missing}"


def test_the_two_files_number_the_phases_the_same_way(roadmap) -> None:
    """One project, one numbering. This file used to have its own.

    It counted from zero (F0) while `.pma/project.yaml` counts from one (01), so every phase
    appeared one higher over there — and the offset was not even constant, because the interface
    sat before the assets project here and after it in the manifest. Asking which phase the
    interface is had two answers, which is one too many.

    The manifest wins because it is what the PMA reads. The roadmap may run ahead of it — a phase
    can be planned here before the manifest catches up — but every phase the manifest declares
    must exist here under the same id, with the same title, in the same order.
    """
    manifest = yaml.safe_load((ROOT / ".pma" / "project.yaml").read_text(encoding="utf-8"))
    here = {f["id"]: f["nome"] for f in roadmap["fases"]}

    mismatched = [
        (p["id"], p["title"], here.get(p["id"]))
        for p in manifest["phases"]
        if here.get(p["id"]) != p["title"]
    ]
    assert not mismatched, f"phases the two files disagree about: {mismatched}"

    declared = [p["id"] for p in manifest["phases"]]
    kept = [f["id"] for f in roadmap["fases"] if f["id"] in set(declared)]
    assert kept == declared, f"the manifest orders phases {declared}, the roadmap {kept}"


def test_phase_ids_are_unique_and_sorted(roadmap) -> None:
    ids = [f["id"] for f in roadmap["fases"]]
    assert len(ids) == len(set(ids)), "duplicate phase id"
    assert ids == sorted(ids), f"phases out of order: {ids}"
