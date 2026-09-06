"""Turn `roadmap.yml` into the project panel, so nobody writes the panel by hand again.

The panel this replaces was written by hand three times in two days, and it was wrong twice: it
reported phase four as pending while its six models were on main, and it counted zero questions
waiting on the maintainer in the same hour a blocking one was filed. Both were drift between a
document and the repository, which is exactly what a generator removes — the page cannot claim a
milestone is validated when the roadmap says otherwise, because it has no other source.

What it will not do is invent. Everything here is read from `roadmap.yml`, `.pma/project.yaml`
and the repository itself; nothing is estimated and passed off as counted. Where a figure is a
guess it is labelled a guess, and where it comes from a command that ran, the page says so.

Usage:  uv run python tools/render_roadmap.py [--out painel/econ.html] [--open]
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

#: Milestone states, in the order a reader wants them, with the label the page shows.
STATES: dict[str, str] = {
    "bloqueado": "bloqueado",
    "em_revisao": "em revisão",
    "a_fazer": "a fazer",
    "validado": "validado",
    "abandonado": "abandonado",
}
SEVERITY_ORDER = {"alta": 0, "media": 1, "baixa": 2}


@dataclass(frozen=True, slots=True)
class Repo:
    """What the repository itself says, as opposed to what the roadmap claims about it."""

    branch: str
    head: str
    dirty: bool
    tests: int

    @classmethod
    def read(cls) -> Repo:
        return cls(
            branch=_git("rev-parse", "--abbrev-ref", "HEAD") or "?",
            head=_git("rev-parse", "--short", "HEAD") or "?",
            dirty=bool(_git("status", "--porcelain")),
            tests=len(list((ROOT / "tests").glob("test_*.py"))),
        )


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def load() -> tuple[dict, dict]:
    roadmap = yaml.safe_load((ROOT / "roadmap.yml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((ROOT / ".pma" / "project.yaml").read_text(encoding="utf-8"))
    return roadmap, manifest


# ------------------------------------------------------------------ small html helpers
def e(value: object) -> str:
    """Escape, and turn a folded YAML block into one clean line."""
    return html.escape(" ".join(str(value).split()))


def pill(state: str) -> str:
    return f'<span class="pill {e(state)}">{e(STATES.get(state, state))}</span>'


def section(title: str, eyebrow: str, body: str, lede: str = "") -> str:
    top = f'<p class="lede">{lede}</p>' if lede else ""
    return (
        f'<section><div class="shead"><p class="eyebrow">{e(eyebrow)}</p>'
        f"<h2>{e(title)}</h2>{top}</div>{body}</section>"
    )


# ------------------------------------------------------------------ the parts of the page
def render_counts(roadmap: dict, repo: Repo) -> str:
    tally: dict[str, int] = {}
    for milestone in roadmap["modulos"]:
        tally[milestone["estado"]] = tally.get(milestone["estado"], 0) + 1
    open_gaps = [g for g in roadmap["lacunas"] if g.get("estado") != "fechada"]
    waiting = [g for g in open_gaps if g.get("espera") == "mantenedor"]

    cells = [
        (len(roadmap["modulos"]), "marcos"),
        (tally.get("validado", 0), "validados"),
        (tally.get("bloqueado", 0), "bloqueados"),
        (len(open_gaps), "lacunas abertas"),
        (len(waiting), "esperam você"),
        (repo.tests, "arquivos de teste"),
    ]
    body = "".join(
        f'<div class="measure"><b>{n}</b><span>{e(label)}</span></div>' for n, label in cells
    )
    return f'<div class="measures">{body}</div>'


def render_phases(roadmap: dict) -> str:
    by_phase: dict[str, list[dict]] = {}
    for milestone in roadmap["modulos"]:
        by_phase.setdefault(milestone["fase"], []).append(milestone)

    blocks = []
    for phase in roadmap["fases"]:
        items = by_phase.get(phase["id"], [])
        done = sum(1 for m in items if m["estado"] == "validado")
        width = (100 * done / len(items)) if items else 0
        rows = "".join(render_milestone(m) for m in items)
        count = f"{done}/{len(items)}" if items else "sem marcos"
        blocks.append(
            f'<div class="phase"><div class="phead">'
            f'<div class="ptitle"><b>{e(phase["id"])}</b> {e(phase["nome"])}</div>'
            f'<div class="pmeta"><span class="num">{e(count)}</span>'
            f'<span class="track"><span class="fill" style="width:{width:.0f}%"></span></span>'
            f'<span class="pill fase-{e(phase["estado"])}">{e(phase["estado"].replace("_", " "))}'
            f"</span></div></div>"
            f'<div class="milestones">{rows}</div></div>'
        )
    return f'<div class="phases">{"".join(blocks)}</div>'


def render_milestone(m: dict) -> str:
    pins = m.get("preso_por") or []
    pinned = (
        '<div class="pins">' + "".join(f"<code>{e(Path(p).name)}</code>" for p in pins) + "</div>"
        if pins
        else '<div class="pins none">nada o prende</div>'
    )
    deps = m.get("depende_de") or []
    dep = f'<span class="dep">depois de {e(", ".join(deps))}</span>' if deps else ""
    blocked = m.get("bloqueado_por") or []
    blk = f'<span class="blk">travado por {e(", ".join(blocked))}</span>' if blocked else ""
    note = f'<p class="note">{e(m["nota"])}</p>' if m.get("nota") else ""
    return (
        f'<div class="ms {e(m["estado"])}">'
        f'<div class="msrow"><span class="msid num">{e(m["id"])}</span>'
        f'<span class="msname">{e(m["nome"])}</span>{pill(m["estado"])}</div>'
        f'<p class="crit">{e(m.get("criterio_aceite", ""))}</p>'
        f'<div class="msmeta">{pinned}{dep}{blk}</div>{note}</div>'
    )


def render_gaps(roadmap: dict) -> str:
    gaps = sorted(
        (g for g in roadmap["lacunas"] if g.get("estado") != "fechada"),
        key=lambda g: (SEVERITY_ORDER.get(g["gravidade"], 9), g["id"]),
    )
    if not gaps:
        return '<p class="note">Nenhuma lacuna aberta.</p>'
    cards = []
    for g in gaps:
        estado = e(g.get("estado", "aberta"))
        waits = (
            f'<span class="pill espera">espera {e(g["espera"])}</span>' if g.get("espera") else ""
        )
        cards.append(
            f'<div class="gap sev-{e(g["gravidade"])}">'
            f'<div class="grow"><span class="num gid">{e(g["id"])}</span>'
            f'<span class="gsev">{e(g["gravidade"])}</span>{waits}'
            f'<span class="pill {estado}">{estado}</span></div>'
            f"<h3>{e(g['titulo'])}</h3>"
            f'<p class="where"><code>{e(g.get("onde", ""))}</code></p>'
            f'<p class="note">{e(g.get("nota", ""))}</p></div>'
        )
    return f'<div class="gaps">{"".join(cards)}</div>'


def render_decisions(roadmap: dict) -> str:
    rows = []
    for d in roadmap["decisoes"]:
        doc = f"<code>{e(d['arquivo'])}</code>" if d.get("arquivo") else "—"
        rows.append(
            f'<tr><td class="n">{e(d["id"])}</td><td class="ph">{e(d["titulo"])}</td>'
            f'<td>{e(d["resposta"])}</td><td class="reopen">{e(d["reabrir_quando"])}</td>'
            f"<td>{doc}</td></tr>"
        )
    return (
        '<div class="tablewrap"><table><thead><tr><th>id</th><th>questão</th>'
        "<th>resposta</th><th>reabrir quando</th><th>documento</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_validation(roadmap: dict) -> str:
    rows = []
    for rule in roadmap["validacao"]:
        exists = (ROOT / rule["fonte"].split("::")[0]).exists()
        mark = "✓" if exists else "✗"
        rows.append(
            f'<tr><td class="ok">{mark}</td><td>{e(rule["regra"])}</td>'
            f'<td class="src"><code>{e(rule["fonte"])}</code></td></tr>'
        )
    return (
        '<div class="tablewrap"><table><thead><tr><th></th><th>a afirmação</th>'
        f"<th>o teste que a sustenta</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_backlog(roadmap: dict) -> str:
    items = []
    for b in roadmap["backlog"]:
        espera = b.get("espera")
        waits = f' <span class="pill espera">espera {e(espera)}</span>' if espera else ""
        items.append(
            f'<li><span class="num">{e(b["id"])}</span> <b>{e(b["titulo"])}</b> '
            f"{pill(b.get('estado', 'proposta'))}{waits}"
            + (f'<p class="note">{e(b["nota"])}</p>' if b.get("nota") else "")
            + "</li>"
        )
    return f'<ul class="backlog">{"".join(items)}</ul>'


# ------------------------------------------------------------------ the page
def render(roadmap: dict, manifest: dict, repo: Repo, now: dt.datetime) -> str:
    project = roadmap["projeto"]
    dirty = " · árvore suja" if repo.dirty else ""
    head = (
        f'<header><p class="eyebrow">Painel do projeto · {e(project["id"])}</p>'
        f"<h1>{e(project['nome'])}</h1>"
        f'<p class="lede">{e(manifest.get("goal", ""))}</p>'
        f'<div class="hmeta"><span class="eyebrow">{now:%d/%m/%Y %H:%M}</span>'
        f'<span class="eyebrow">{e(project["repo"])}</span>'
        f'<span class="eyebrow">{e(repo.branch)} @ {e(repo.head)}{dirty}</span></div></header>'
    )
    parts = [
        head,
        section("Onde está", "Contagem", render_counts(roadmap, repo)),
        section(
            "Fases e marcos",
            "O trabalho",
            render_phases(roadmap),
            "A barra mede marcos validados sobre marcos declarados, não esforço. Um marco só é "
            "validado quando nomeia os testes que o prendem — sem isso ele está afirmado, não "
            "mostrado.",
        ),
        section(
            "O que está aberto",
            "Lacunas",
            render_gaps(roadmap),
            "Ordenadas por gravidade. As que dizem “espera mantenedor” não avançam sem você.",
        ),
        section(
            "O que já se decidiu",
            "Decisões",
            render_decisions(roadmap),
            "Cada uma com o gatilho que a reabriria. Decisão sem gatilho é hábito.",
        ),
        section(
            "O que este projeto afirma sobre si",
            "Validação",
            render_validation(roadmap),
            "Cada afirmação nomeia o teste que a sustenta, e o visto confirma que o arquivo "
            "existe agora — não quando o texto foi escrito.",
        ),
        section("Adiado, com gatilho", "Backlog", render_backlog(roadmap)),
        "<footer>Gerado por <code>tools/render_roadmap.py</code> a partir de "
        "<code>roadmap.yml</code> e <code>.pma/project.yaml</code>. Não editar à mão: a próxima "
        "execução sobrescreve. Contagens de marco, lacuna e teste são aferidas; o estado de cada "
        "marco é declarado no roadmap e sustentado pelos testes que ele nomeia.</footer>",
    ]
    css = (Path(__file__).resolve().parent / "painel.css").read_text(encoding="utf-8")
    return TEMPLATE.format(body="".join(parts), title=e(project["nome"]), css=css)


#: The page shell. Styles live in `painel.css` next to this file: CSS in a Python string has to
#: be brace-doubled for `str.format` and cannot be linted or edited comfortably.
TEMPLATE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{css}</style></head><body><div class="wrap">{body}</div></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "painel" / "econ.html"))
    args = parser.parse_args()

    roadmap, manifest = load()
    page = render(roadmap, manifest, Repo.read(), dt.datetime.now())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"escrito: {out}  ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
