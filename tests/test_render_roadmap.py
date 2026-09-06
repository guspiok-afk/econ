"""The panel is generated, and the generator has to stay honest about what it read.

The page it replaces was written by hand three times in two days and was wrong twice — a phase
reported as pending while its six models were on main, and zero questions waiting on the
maintainer in the same hour a blocking one was filed. A generator removes that failure by
construction: the page has no source but `roadmap.yml`, so it cannot claim more than the roadmap
says. What it can still do is drop things silently, and that is what these tests watch.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "render_roadmap.py"


def _load():
    """Import the script by path.

    It has to be registered in `sys.modules` *before* it executes: `Repo` is a slotted dataclass,
    and building one looks its own module up by name to rebind the recreated class. Without the
    registration the import fails at definition time, not at first use.
    """
    spec = importlib.util.spec_from_file_location("render_roadmap", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_roadmap"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def render_roadmap():
    return _load()


@pytest.fixture(scope="module")
def page(render_roadmap) -> str:
    roadmap, manifest = render_roadmap.load()
    repo = render_roadmap.Repo(branch="test", head="0000000", dirty=False, tests=1)
    return render_roadmap.render(roadmap, manifest, repo, dt.datetime(2026, 9, 6, 12, 0))


def test_the_generator_runs_on_the_real_roadmap(page) -> None:
    assert page.startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")


def test_every_milestone_reaches_the_page(page, render_roadmap) -> None:
    """A milestone dropped by the renderer is a milestone that stops existing for the reader."""
    roadmap, _ = render_roadmap.load()
    missing = [m["id"] for m in roadmap["modulos"] if m["id"] not in page]
    assert not missing, f"milestones the page never shows: {missing}"


def test_every_gap_and_decision_reaches_the_page(page, render_roadmap) -> None:
    roadmap, _ = render_roadmap.load()
    absent = [
        g["id"] for g in roadmap["lacunas"] if g.get("estado") != "fechada" and g["id"] not in page
    ]
    absent += [d["id"] for d in roadmap["decisoes"] if d["id"] not in page]
    assert not absent, f"gaps or decisions the page never shows: {absent}"


def test_the_blocking_gap_is_not_buried(page, render_roadmap) -> None:
    """Severity orders the list, so what waits on the maintainer cannot sit under what does not.

    This is the failure the hand-written panel actually had: a blocking question filed and the
    page reporting nothing waiting.
    """
    roadmap, _ = render_roadmap.load()
    high = [
        g for g in roadmap["lacunas"] if g["gravidade"] == "alta" and g.get("estado") != "fechada"
    ]
    low = [
        g for g in roadmap["lacunas"] if g["gravidade"] == "baixa" and g.get("estado") != "fechada"
    ]
    if high and low:
        assert page.index(high[0]["id"]) < page.index(low[0]["id"])


def test_a_milestone_with_nothing_pinning_it_says_so(render_roadmap) -> None:
    """Silence would read as "no tests needed". It has to read as an absence."""
    loose = {
        "id": "M999",
        "fase": "F0",
        "nome": "Sem teste",
        "estado": "a_fazer",
        "criterio_aceite": "nada",
    }
    assert "nada o prende" in render_roadmap.render_milestone(loose)


def test_the_template_leaves_nothing_unsubstituted(page) -> None:
    """`str.format` fails loudly on a missing key, but a stray brace in the CSS would survive."""
    for placeholder in ("{body}", "{title}", "{css}"):
        assert placeholder not in page


def test_content_is_escaped(render_roadmap) -> None:
    """Roadmap text is written by hand and will eventually contain a `<` or an `&`."""
    nasty = {
        "id": "M998",
        "fase": "F0",
        "nome": "<script>alert(1)</script>",
        "estado": "a_fazer",
        "criterio_aceite": "a & b < c",
    }
    out = render_roadmap.render_milestone(nasty)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "a &amp; b &lt; c" in out


def test_folded_yaml_becomes_one_line(render_roadmap) -> None:
    """Acceptance criteria are folded YAML blocks; their newlines are formatting, not content."""
    assert render_roadmap.e("uma\n  frase\n  quebrada") == "uma frase quebrada"


def test_the_footer_says_the_page_is_generated(page) -> None:
    """Anyone editing the HTML by hand loses the edit on the next run, and should be told."""
    assert "render_roadmap.py" in page
    assert "Não editar à mão" in page


def test_the_repository_reader_survives_a_missing_git(render_roadmap, monkeypatch) -> None:
    """The panel must render on a machine without git rather than fail on decoration."""
    monkeypatch.setattr(render_roadmap, "_git", lambda *a: "")
    repo = render_roadmap.Repo.read()
    assert repo.branch == "?" and repo.head == "?"
    assert repo.tests > 0, "test files are counted from disk, not from git"


def test_the_stylesheet_is_a_file_and_is_inlined(page) -> None:
    """Shipped as one self-contained page: it is opened from disk and from a phone."""
    assert (ROOT / "tools" / "painel.css").exists()
    assert "<style>" in page and "--accent" in page
    assert re.search(r"link rel=\"stylesheet\" href=\"https://fonts\.googleapis", page)
