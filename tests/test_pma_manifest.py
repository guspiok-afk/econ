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
MANIFEST = ROOT / ".pma" / "project.yaml"


def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_the_manifest_parses() -> None:
    assert isinstance(manifest(), dict), "the manifest must be a YAML mapping"


REQUIRED = ("schema", "project", "goal", "phases", "executors", "interfaces", "commands")


@pytest.mark.parametrize("key", REQUIRED)
def test_the_manifest_carries_what_a_manager_needs(key: str) -> None:
    assert key in manifest(), f"the manifest has no {key!r}"


def test_every_interface_declares_its_stability() -> None:
    for entry in manifest()["interfaces"]:
        assert entry.get("kind"), "an interface without a kind cannot be depended on"
        assert entry.get("stability") in {"stable", "provisional", "internal"}, (
            f"interface {entry.get('kind')!r} declares stability {entry.get('stability')!r}"
        )
