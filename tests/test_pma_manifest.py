r"""The project manifest exists to be read by a machine, so it must parse.

`.pma/project.yaml` is what makes this repository legible to an external manager without
reading its code. It spent a day unparseable: a Windows path written in double quotes turned
`\e`, `\d` and `\l` into YAML escape sequences, two of which do not exist. Nothing read the
file, so nothing complained.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
PMA = ROOT / ".pma"
MANIFEST = PMA / "project.yaml"

#: The repository's own project, plus any other project hosted here. A repository can carry more
#: than one: the asset-price work is a second project sharing this core, and the manager reads
#: each one the same way.
MANIFESTS = [MANIFEST, *sorted((PMA / "projects").glob("*.yaml"))]
IDS = [p.stem for p in MANIFESTS]

STATES = {"done", "active", "todo", "blocked"}
STATUSES = {"active", "paused", "done", "archived"}


def manifest(path: Path = MANIFEST) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", MANIFESTS, ids=IDS)
def test_the_manifest_parses(path: Path) -> None:
    assert isinstance(manifest(path), dict), "the manifest must be a YAML mapping"


REQUIRED = ("schema", "project", "goal", "phases", "executors", "interfaces", "commands")


@pytest.mark.parametrize("path", MANIFESTS, ids=IDS)
@pytest.mark.parametrize("key", REQUIRED)
def test_the_manifest_carries_what_a_manager_needs(key: str, path: Path) -> None:
    assert key in manifest(path), f"{path.name} has no {key!r}"


@pytest.mark.parametrize("path", MANIFESTS, ids=IDS)
def test_the_vocabulary_is_the_one_the_manager_compares_on(path: Path) -> None:
    """One vocabulary across projects, or the manager cannot rank them against each other."""
    doc = manifest(path)
    assert doc["project"]["status"] in STATUSES, f"{path.name}: unknown project status"
    for phase in doc["phases"]:
        assert phase["state"] in STATES, (
            f"{path.name}: phase {phase['id']} state {phase['state']!r}"
        )


@pytest.mark.parametrize("path", MANIFESTS, ids=IDS)
def test_every_decision_says_what_would_reopen_it(path: Path) -> None:
    """A decision without a trigger is an opinion, and gets relitigated."""
    for entry in manifest(path)["decisions"]:
        assert entry.get("question") and entry.get("answer"), f"{path.name}: incomplete decision"
        assert entry.get("reopen_when"), (
            f"{path.name}: {entry['question']!r} has no reopen_when; write 'nunca' if it is closed"
        )


@pytest.mark.parametrize("path", MANIFESTS, ids=IDS)
def test_every_project_id_is_distinct(path: Path) -> None:
    ids = [manifest(p)["project"]["id"] for p in MANIFESTS]
    assert len(ids) == len(set(ids)), f"two projects share an id: {ids}"


def test_every_interface_declares_its_stability() -> None:
    for entry in manifest()["interfaces"]:
        assert entry.get("kind"), "an interface without a kind cannot be depended on"
        assert entry.get("stability") in {"stable", "provisional", "internal"}, (
            f"interface {entry.get('kind')!r} declares stability {entry.get('stability')!r}"
        )
