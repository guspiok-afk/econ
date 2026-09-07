"""What must exist, so a merge cannot quietly delete it.

On 5 September 2026 a pull request whose branch had been rebuilt from an older base was merged,
and it removed 4,290 lines across forty-three files: the parity model, the results store, the
specification loader, the panel guard that had just fixed two blockers, eleven test files. The
suite could not catch it, because the suite went with it — a deleted test does not fail.

The review could not catch it either, and that is the part worth naming. A pull request diff is
computed against the merge base, so when the base is old, everything merged since shows up as
"unchanged" rather than as a deletion. I read the diff, approved, and the tree came in behind it.

Two kinds of guard live here, and neither needs updating when work is added. Load-bearing single
files are listed by name: deleting one is a decision, and a decision should have to edit this
list. Collections get floors: there are at least this many models, specifications, decision
records and catalogued series, so a merge that drops a batch trips a wire even though nobody
enumerated the batch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Files without which something load-bearing is gone. Removing one should mean editing this
#: list in the same commit, and having to explain why in the pull request.
LOAD_BEARING = [
    # the data contract and its enforcement
    "docs/CONTRACT.md",
    "docs/IDENTIFIERS.md",
    "src/econbase/schemas.py",
    "src/econbase/catalog.py",
    "src/econbase/store.py",
    "src/econbase/pipeline.py",
    "src/econbase/settings.py",
    "src/econbase/transforms.py",
    "src/econbase/api.py",
    "src/econbase/report.py",
    # the model contract and everything built on it
    "src/econmodels/base.py",
    "src/econmodels/specs.py",
    "src/econmodels/results.py",
    "src/econmodels/parity.py",
    "src/econmodels/taylor.py",
    "src/econmodels/var.py",
    # operations
    "scripts/daily.ps1",
    "scripts/backup.ps1",
    "docs/OPERATION.md",
    "docs/MANUAL.md",
    "AGENTS.md",
    # the project's own memory
    "roadmap.yml",
    "app/painel.py",
    "app/pages/1_vintages.py",
    "app/pages/2_modelos.py",
    "src/econmodels/run.py",
    "docs/adr/0008-the-app-is-a-thin-view-over-the-read-api.md",
    "tools/render_roadmap.py",
    "tools/painel.css",
    "catalog/us/nyfed.yaml",
    "docs/QUESTIONS.md",
    "docs/referencias/phillips.md",
    ".pma/project.yaml",
    ".pma/projects/fin.yaml",
    "catalog/concepts.yaml",
    "catalog/entities.yaml",
    "catalog/ids.txt",
]

#: Floors, not counts: they never need raising when work is added, and they trip when a batch
#: disappears. Each is set a little below what exists at the time of writing.
FLOORS = {
    "src/econmodels/*.py": 6,
    "specs/**/*.yaml": 2,
    "docs/adr/*.md": 7,
    "docs/work-packages/*.md": 10,
    "tests/test_*.py": 25,
    "tests/fixtures/analysis/*.csv": 5,
}


@pytest.mark.parametrize("relative", LOAD_BEARING)
def test_a_load_bearing_file_is_still_there(relative: str) -> None:
    path = ROOT / relative
    assert path.is_file(), (
        f"{relative} is gone. If that was deliberate, remove it from LOAD_BEARING in the same "
        "commit and say why in the pull request; if it was not, a merge deleted it."
    )


@pytest.mark.parametrize("pattern,floor", sorted(FLOORS.items()))
def test_a_collection_did_not_lose_a_batch(pattern: str, floor: int) -> None:
    found = sorted(ROOT.glob(pattern))
    assert len(found) >= floor, (
        f"only {len(found)} files match {pattern!r}, and there should be at least {floor}. "
        "A floor trips when a merge drops a batch nobody enumerated."
    )


def test_the_catalog_still_lists_the_series_it_used_to() -> None:
    """The catalog is the one collection whose loss would be silent in the data, not the code."""
    ids = (ROOT / "catalog" / "ids.txt").read_text(encoding="utf-8").splitlines()
    listed = [line for line in ids if line.strip() and not line.lstrip().startswith("#")]
    assert len(listed) >= 70, f"catalog/ids.txt lists {len(listed)} series; it had 73"


def test_every_specification_still_parses() -> None:
    """A specification that stops loading is as lost as one that was deleted."""
    from econmodels.specs import load_specs

    specs = load_specs(ROOT / "specs")
    assert len(specs) >= 2
