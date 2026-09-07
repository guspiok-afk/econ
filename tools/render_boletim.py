"""O quadro brasileiro numa página que o celular abre de qualquer lugar.

O aplicativo Streamlit resolve o uso na mesma rede e não resolve o resto: ele exige a máquina
ligada e alcançável. Esta página resolve o resto por outro caminho — ela é **gerada**, não
servida. Uma vez publicada, funciona no ônibus, com o notebook desligado, sem túnel, sem VPN e
sem porta aberta.

O que ela paga por isso é ser só leitura e ser um retrato: mostra o que era verdade quando foi
gerada, e envelhece até a próxima execução. Por isso o carimbo de data é grande e não discreto.

**O que pode entrar aqui é decidido pela licença, não pelo gosto.** Das 73 séries do catálogo, 40
são redistribuíveis e todas elas são brasileiras; as 33 restantes vêm do FRED e do NY Fed, que
permitem uso e não republicação. Publicar uma página é republicar. Então o boletim é brasileiro
por obrigação e não por escolha, e `_conferir_licenca` recusa a geração se alguma série restrita
escapar para dentro dela — uma checagem que existe porque a alternativa é descobrir depois.

Uso:
    uv run --extra models python tools/render_boletim.py [--out painel/boletim.html] [--artifact]
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from econbase.api import connect

ROOT = Path(__file__).resolve().parents[1]

#: Separador de milhar. Escapado em vez de literal: o caractere fino é invisível no editor e o
#: linter, com razão, recusa caractere ambíguo dentro de string.
MILHAR = chr(0x202F)  # espaço fino: invisível no editor, e o linter recusa o literal


class LicencaViolada(RuntimeError):
    """Uma série que não pode ser republicada chegou a uma página que vai ser publicada."""


@dataclass(frozen=True, slots=True)
class Indicador:
    """Uma linha do boletim, declarada e não montada no meio do desenho."""

    conceito: str
    rotulo: str
    unidade: str
    transform: str | None = None
    casas: int = 2
    nota: str = ""


BLOCOS: dict[str, tuple[Indicador, ...]] = {
    "Preços": (
        Indicador("cpi_headline_index", "IPCA", "% em 12 meses", "yoy", 2),
        Indicador("cpi_core", "Núcleo", "% no mês", None, 2),
    ),
    "Juros e câmbio": (
        Indicador("policy_rate", "Selic meta", "% ao ano", None, 2),
        Indicador("interbank_rate", "Selic efetiva", "% ao dia útil", None, 4),
        Indicador("fx_spot_usd", "Dólar (PTAX)", "R$", None, 4),
        Indicador("credit_rate", "Juro médio do crédito", "% ao ano", None, 1),
    ),
    "Atividade": (
        Indicador("activity_index", "IBC-Br", "% em 12 meses", "yoy", 2),
        Indicador("retail_sales", "Varejo", "% em 12 meses", "yoy", 2),
        Indicador("industrial_production", "Produção industrial", "% em 12 meses", "yoy", 2),
        Indicador("unemployment_rate", "Desocupação", "%", None, 1),
    ),
    "Expectativas (Focus)": (
        Indicador("inflation_expectations_12m", "IPCA em 12 meses", "%", None, 2),
        Indicador("policy_rate_expectations_eoy", "Selic no fim do ano", "%", None, 2),
    ),
    "Crédito e fiscal": (
        Indicador("credit_delinquency", "Inadimplência", "%", None, 2),
        Indicador("gross_debt", "Dívida bruta", "% do PIB", None, 1),
        Indicador("primary_balance", "Resultado primário", "% do PIB, 12 meses", None, 2),
    ),
}

#: O PIB fica de fora enquanto a lacuna C1 estiver aberta: a série do catálogo declara ajuste
#: sazonal e não tem, e um número trimestral sazonal num boletim é um número errado com aparência
#: de certo. Ausência explicada é melhor que presença enganosa.
AUSENTE = (
    "O PIB não aparece aqui. A série do catálogo se declara dessazonalizada e não é — dummies de "
    "trimestre explicam 55% da variação do crescimento —, então publicá-la seria publicar o "
    "calendário. Volta quando a lacuna C1 for decidida."
)


def _conferir_licenca(api, conceitos: list[str], entidade: str = "BR") -> None:
    """Recusa gerar se alguma série do boletim não puder ser republicada.

    A entidade é argumento e não "BR" fixo: uma guarda que só sabe olhar para um país não guarda
    nada no dia em que o boletim ganhar um segundo — e é justamente o segundo país que traria as
    séries restritas, porque as trinta e três são todas de fora.
    """
    restritas = []
    for conceito in conceitos:
        ficha = api.describe(conceito, entidade)
        if not ficha["redistributable"]:
            restritas.append(f"{ficha['series_id']} ({ficha['license']})")
    if restritas:
        raise LicencaViolada(
            "esta página é publicada e estas séries não podem ser republicadas: "
            + ", ".join(restritas)
        )


def _serie(api, ind: Indicador) -> pd.DataFrame:
    return api.get(ind.conceito, entity="BR", transform=ind.transform, start="2015-01-01")


def _faisca(valores: list[float], largura: int = 240, altura: int = 44) -> str:
    """Um traço do caminho recente. SVG puro: nada a carregar, nada a bloquear."""
    if len(valores) < 2:
        return ""
    menor, maior = min(valores), max(valores)
    espalho = (maior - menor) or 1.0
    passo = largura / (len(valores) - 1)
    pontos = " ".join(
        f"{i * passo:.1f},{altura - 4 - (v - menor) / espalho * (altura - 8):.1f}"
        for i, v in enumerate(valores)
    )
    ultimo_x, ultimo_y = pontos.split()[-1].split(",")
    return (
        f'<svg class="faisca" viewBox="0 0 {largura} {altura}" preserveAspectRatio="none" '
        f'role="img" aria-hidden="true">'
        f'<polyline points="{pontos}" fill="none" stroke="currentColor" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{ultimo_x}" cy="{ultimo_y}" r="2.6" fill="currentColor"/></svg>'
    )


def _cartao(api, ind: Indicador) -> str:
    dados = _serie(api, ind)
    if dados.empty:
        return ""
    valores = [float(v) for v in dados["value"].tail(60)]
    atual = valores[-1]
    anterior = valores[-2] if len(valores) > 1 else atual
    variacao = atual - anterior
    seta = "▲" if variacao > 0 else ("▼" if variacao < 0 else "•")
    classe = "sobe" if variacao > 0 else ("desce" if variacao < 0 else "igual")
    quando = dados["period"].max()
    return (
        f'<article class="cartao">'
        f'<div class="topo"><span class="rotulo">{ind.rotulo}</span>'
        f'<span class="quando">{quando}</span></div>'
        f'<div class="linha"><span class="valor">{atual:,.{ind.casas}f}</span>'
        f'<span class="unidade">{ind.unidade}</span>'
        f'<span class="delta {classe}">{seta} {abs(variacao):,.{ind.casas}f}</span></div>'
        f"{_faisca(valores)}"
        f"</article>"
        # separador de milhar em espaço fino, que é a convenção brasileira sem o ponto que confunde
        # com a vírgula decimal num número já formatado
    ).replace(",", MILHAR)


def montar(api, agora: dt.datetime) -> str:
    conceitos = [ind.conceito for bloco in BLOCOS.values() for ind in bloco]
    _conferir_licenca(api, conceitos)

    secoes = []
    for titulo, indicadores in BLOCOS.items():
        cartoes = "".join(_cartao(api, ind) for ind in indicadores)
        if cartoes:
            secoes.append(f'<section><h2>{titulo}</h2><div class="grade">{cartoes}</div></section>')

    corpo = "".join(secoes)
    return (
        f'<header><p class="olho">Boletim · Brasil</p><h1>Como está a economia</h1>'
        f'<p class="carimbo">gerado em {agora:%d/%m/%Y às %H:%M}</p></header>'
        f"{corpo}"
        f"<footer><p>{AUSENTE}</p>"
        f"<p>Um retrato: os números são os que estavam na base quando esta página foi gerada, e "
        f"envelhecem até a próxima. A variação ao lado de cada número é contra a observação "
        f"anterior da mesma série, não contra o mês anterior.</p>"
        f"<p>Só séries de licença aberta — Banco Central e IBGE. As 33 séries do FRED e do NY Fed "
        f"que o projeto coleta permitem uso e não republicação, e por isso não estão aqui.</p>"
        f"</footer>"
    )


PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Boletim Brasil</title>
<style>{css}</style></head><body><div class="folha">{corpo}</div></body></html>
"""

FRAGMENTO = """<title>Boletim Brasil</title>
<style>{css}</style>
<div class="folha">{corpo}</div>
"""


def render(api, agora: dt.datetime, *, artifact: bool = False) -> str:
    css = (Path(__file__).resolve().parent / "boletim.css").read_text(encoding="utf-8")
    return (FRAGMENTO if artifact else PAGINA).format(css=css, corpo=montar(api, agora))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "painel" / "boletim.html"))
    parser.add_argument("--artifact", action="store_true")
    args = parser.parse_args()

    pagina = render(connect(), dt.datetime.now(), artifact=args.artifact)
    destino = Path(args.out)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina, encoding="utf-8")
    print(f"escrito: {destino}  ({len(pagina):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
