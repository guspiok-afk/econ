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


def test_the_manifest_declares_no_phase_the_roadmap_has_forgotten(roadmap) -> None:
    """Two files describing the same project drifted apart once already, and the panel reported a
    finished phase as pending while its six models were on main.

    The roadmap is allowed to run ahead -- a phase can be planned here before the manifest the
    PMA reads catches up -- but it may never have fewer phases than the manifest declares.
    """
    manifest = yaml.safe_load((ROOT / ".pma" / "project.yaml").read_text(encoding="utf-8"))
    known = {f["nome"] for f in roadmap["fases"]}
    forgotten = [p["title"] for p in manifest["phases"] if p["title"] not in known]
    assert not forgotten, f"phases the manifest declares and the roadmap does not: {forgotten}"
