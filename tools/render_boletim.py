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


def _grafico(
    valores: list[float],
    datas: list[str],
    largura: int = 320,
    altura: int = 150,
    escala: tuple[float, float] | None = None,
) -> str:
    """O caminho da série com escala legível, em SVG puro.

    A faísca que isto substitui mostrava a forma e escondia o nível: sem eixo, subir de 3 para 4
    e subir de 300 para 400 desenham o mesmo traço. Aqui os extremos vão escritos, e a linha do
    zero aparece quando a série cruza — porque num gráfico de variação o sinal é metade da
    informação.

    Margens reservadas na viewBox antes de desenhar: rótulo que vaza para fora dela some sem
    erro, e o gráfico fica cortado sem que nada avise.
    """
    if len(valores) < 2:
        return ""
    esquerda, baixo, topo = 38.0, 16.0, 6.0
    menor, maior = escala if escala else (min(valores), max(valores))
    if menor == maior:
        menor, maior = menor - 0.5, maior + 0.5
    espalho = maior - menor
    util_x = largura - esquerda - 4
    util_y = altura - baixo - topo

    def y(v: float) -> float:
        return topo + (maior - v) / espalho * util_y

    passo = util_x / (len(valores) - 1)
    pontos = " ".join(f"{esquerda + i * passo:.1f},{y(v):.1f}" for i, v in enumerate(valores))
    ultimo_x, ultimo_y = pontos.split()[-1].split(",")

    zero = ""
    if menor < 0 < maior:
        zero = (
            f'<line class="zero" x1="{esquerda}" y1="{y(0.0):.1f}" '
            f'x2="{largura - 4}" y2="{y(0.0):.1f}"/>'
        )

    # Cada número é formatado sozinho. Uma versão anterior aplicava `.replace(",", MILHAR)` ao
    # bloco inteiro de f-strings adjacentes, e o separador de milhar comeu as vírgulas das
    # COORDENADAS do polyline. O SVG continuou desenhando — a especificação aceita separação por
    # espaço — então nada quebrou à vista, e só o teste de limites da caixa notou.
    alto = f"{maior:,.1f}".replace(",", MILHAR)
    baixo_txt = f"{menor:,.1f}".replace(",", MILHAR)

    return (
        f'<svg class="grafico" viewBox="0 0 {largura} {altura}" role="img" aria-label="histórico">'
        f'<line class="eixo" x1="{esquerda}" y1="{topo}" x2="{esquerda}" y2="{altura - baixo}"/>'
        f"{zero}"
        f'<polyline class="traco" points="{pontos}"/>'
        f'<circle class="ponta" cx="{ultimo_x}" cy="{ultimo_y}" r="3"/>'
        f'<text class="marca" x="{esquerda - 5}" y="{topo + 4:.1f}" text-anchor="end">{alto}</text>'
        f'<text class="marca" x="{esquerda - 5}" y="{altura - baixo:.1f}" text-anchor="end">'
        f"{baixo_txt}</text>"
        f'<text class="marca" x="{esquerda}" y="{altura - 4}">{datas[0][:4]}</text>'
        f'<text class="marca" x="{largura - 4}" y="{altura - 4}" text-anchor="end">'
        f"{datas[-1][:7]}</text>"
        f"</svg>"
    )


def _cartao(api, ind: Indicador) -> str:
    dados = _serie(api, ind)
    if dados.empty:
        return ""
    recorte = dados.tail(140)
    valores = [float(v) for v in recorte["value"]]
    datas = [str(d) for d in recorte["period"]]
    atual = valores[-1]
    anterior = valores[-2] if len(valores) > 1 else atual
    variacao = atual - anterior
    seta = "▲" if variacao > 0 else ("▼" if variacao < 0 else "•")
    classe = "sobe" if variacao > 0 else ("desce" if variacao < 0 else "igual")
    quando = dados["period"].max()
    # Cada número formatado sozinho, de novo pelo mesmo motivo: aplicar o separador de milhar ao
    # cartão inteiro alcançava as vírgulas das coordenadas do gráfico embutido nele. O teste da
    # função não pegava, porque a função estava certa — quem estava errado era o chamador.
    valor_txt = f"{atual:,.{ind.casas}f}".replace(",", MILHAR)
    delta_txt = f"{abs(variacao):,.{ind.casas}f}".replace(",", MILHAR)

    return (
        f'<article class="cartao">'
        f'<div class="topo"><span class="rotulo">{ind.rotulo}</span>'
        f'<span class="quando">{quando}</span></div>'
        f'<div class="linha"><span class="valor">{valor_txt}</span>'
        f'<span class="unidade">{ind.unidade}</span>'
        f'<span class="delta {classe}">{seta} {delta_txt}</span></div>'
        f"{_grafico(valores, datas)}"
        f"</article>"
    )


# ---------------------------------------------------------------------------- os modelos
#
# Aqui a regra da licença muda de forma, e vale dizer por quê. Uma SÉRIE do FRED não pode ser
# republicada; um COEFICIENTE estimado, uma contribuição decomposta ou um hiato filtrado são
# trabalho derivado e nosso. Ainda assim, tudo que entra nesta seção é brasileiro e vem de série
# aberta, porque não há razão para chegar perto da fronteira sem precisar.
#
# A regra de Taylor fica de fora pelo mesmo motivo do PIB: o hiato dela é filtrado sobre a série
# trimestral que se declara dessazonalizada e não é. Publicá-la seria publicar o calendário
# vestido de prescrição de juros.


def _linhas(series: list[tuple[list[float], str]], datas: list[str]) -> str:
    """Várias séries numa escala só, porque escalas diferentes comparam forma e mentem sobre nível.

    A primeira entrega a escala e as demais são desenhadas dentro dela. Uma série que estourasse
    a caixa sairia cortada em silêncio, então a escala é a união de todas antes de qualquer traço.
    """
    juntos = [v for valores, _ in series for v in valores]
    if len(juntos) < 4:
        return ""
    menor, maior = min(juntos), max(juntos)
    if menor == maior:
        menor, maior = menor - 0.5, maior + 0.5

    base = _grafico(series[0][0], datas, escala=(menor, maior))
    esquerda, baixo, topo = 38.0, 16.0, 6.0
    largura, altura = 320, 150
    util_y = altura - baixo - topo

    extras = ""
    for valores, classe in series[1:]:
        if len(valores) < 2:
            continue
        passo = (largura - esquerda - 4) / (len(valores) - 1)
        pontos = " ".join(
            f"{esquerda + i * passo:.1f},{topo + (maior - v) / (maior - menor) * util_y:.1f}"
            for i, v in enumerate(valores)
        )
        extras += f'<polyline class="traco {classe}" points="{pontos}"/>'
    return base.replace("</svg>", extras + "</svg>")


def _duas_linhas(a: list[float], b: list[float], datas: list[str]) -> str:
    return _linhas([(a, "a"), (b, "b")], datas)


def _phillips_no_tempo(api, ctx_data: dt.date) -> str:
    """A curva ao longo do tempo, com a Selic na mesma escala.

    Uma curva de Phillips não é uma série: é uma relação. O que se pode desenhar historicamente é
    o que ela ACERTOU — a inflação que ela previa contra a que aconteceu — e é isso que está aqui,
    com a taxa de política no mesmo eixo, que é onde a pergunta "contra a Selic" faz sentido.

    As três grandezas são percentuais e cabem numa escala só: inflação anualizada trimestral entre
    -1,1 e 14,7 e Selic entre 2,0 e 15,0 no período estimado. Fossem incomparáveis, dois eixos
    seriam a resposta — e dois eixos num gráfico pequeno são um convite a ver correlação onde há
    escolha de escala.
    """
    import pandas as pd

    import econmodels.phillips  # noqa: F401  registra o modelo
    from econmodels.run import run_spec
    from econmodels.specs import load_specs

    spec = load_specs(Path(ROOT) / "specs", model_id="phillips")["br_bcb_small_scale"]
    ajuste = run_spec(api, spec, asof=ctx_data).tables()["fitted"]
    ajuste["period"] = pd.to_datetime(ajuste["period"])

    selic = api.get("policy_rate", entity="BR", freq="Q", agg="eop").set_index("period")["value"]
    selic.index = pd.to_datetime(selic.index)
    junto = ajuste.set_index("period").join(selic.rename("selic"), how="left").dropna()

    datas = [str(d.date()) for d in junto.index]
    realizado = [float(v) for v in junto["actual"]]
    previsto = [float(v) for v in junto["fitted"]]
    juros = [float(v) for v in junto["selic"]]
    erro_medio = float(junto["residual"].abs().mean())
    correlacao = float(junto["residual"].corr(junto["selic"]))

    return (
        '<article class="modelo">'
        "<h3>A curva contra a Selic</h3>"
        '<p class="sub">Inflação de preços livres, anualizada no trimestre: o que aconteceu, o '
        "que a equação do Banco Central previa, e a Selic no mesmo eixo. Todas em por cento.</p>"
        f"{_linhas([(realizado, 'a'), (previsto, 'b'), (juros, 'c')], datas)}"
        f'<div class="legenda"><span class="a">realizado</span>'
        f'<span class="b">previsto pela curva</span><span class="c">Selic</span></div>'
        f'<p class="sub">Erro absoluto médio de {erro_medio:.2f} ponto por trimestre em '
        f"{len(junto)} trimestres. A correlação entre o erro da curva e a Selic é "
        f"{correlacao:+.3f} — perto de zero, ou seja, o que a equação erra não é explicado pelo "
        "aperto ou pela folga monetária do momento.</p>"
        "</article>"
    )


def _duas_curvas(api, ctx_data: dt.date) -> str:
    """A inclinação brasileira ao lado da americana.

    Aqui a página encosta na fronteira da licença de propósito, e vale dizer onde ela está. A
    SÉRIE americana vem do FRED e não pode ser republicada — por isso não há gráfico dos Estados
    Unidos nesta página, e ele mora no aplicativo, que lê o store na máquina e não publica nada.
    O COEFICIENTE é outra coisa: é uma estatística que estimamos, não o dado da fonte, e é
    trabalho derivado nosso. É o mesmo raciocínio da ADR-0008 sobre o que um produto poderia
    vender.

    A especificação americana é nossa e o cartão diz isso. A brasileira segue o Banco Central.
    """
    import econmodels.phillips  # noqa: F401  registra o modelo
    from econmodels.run import run_spec
    from econmodels.specs import load_specs

    specs = load_specs(Path(ROOT) / "specs", model_id="phillips")
    linhas = []
    for spec_id, rotulo in (("br_bcb_small_scale", "Brasil"), ("us_desemprego", "Estados Unidos")):
        if spec_id not in specs:
            continue
        coeficientes = run_spec(api, specs[spec_id], asof=ctx_data).tables()["coefficients"]
        folga = coeficientes[coeficientes["name"] == "folga"]
        if folga.empty:
            continue
        estimativa, erro = float(folga["estimate"].iloc[0]), float(folga["std_error"].iloc[0])
        mudo = abs(estimativa) < 2 * erro
        linhas.append(
            f"<tr{' class="mudo"' if mudo else ''}><td>{rotulo}</td>"
            f"<td>{estimativa:+.3f}</td><td>±{erro:.3f}</td>"
            f"<td>{'—' if mudo else '•'}</td></tr>"
        )
    if not linhas:
        return ""
    return (
        '<article class="modelo">'
        "<h3>A inclinação, nos dois países</h3>"
        '<p class="sub">O coeficiente da folga: quanto a ociosidade da economia puxa a inflação. '
        "A teoria pede sinal negativo.</p>"
        '<table class="coef"><thead><tr><th>país</th><th>folga</th><th>erro</th><th>≠0</th></tr>'
        f"</thead><tbody>{''.join(linhas)}</tbody></table>"
        '<p class="sub">Em nenhum dos dois a inclinação se separa de zero a dois erros-padrão, e '
        "a americana ainda sai com o sinal trocado. Isso não é falha da estimação: é o que "
        "Mavroeidis, Plagborg-Møller e Stock mostraram em 2014 — a curva é fracamente "
        "identificada, e amostras deste tamanho não a distinguem de uma reta horizontal.</p>"
        '<p class="sub">Só os coeficientes aparecem aqui. A série americana vem do FRED, que '
        "permite uso e não republicação, então o gráfico dos Estados Unidos vive no aplicativo e "
        "não nesta página.</p>"
        "</article>"
    )


def _decomposicao(api, ctx_data: dt.date) -> str:
    """Quanto dos preços livres e dos administrados está dentro da inflação de doze meses."""
    from econmodels.base import RunContext
    from econmodels.decomposition import PriceDecomposition

    painel = api.get_panel(
        [(c, "BR") for c in ("cpi_headline", "cpi_free", "cpi_administered")],
        freq="M",
        start="1996-01-01",
    )
    tabela = PriceDecomposition().fit(painel, RunContext(asof=ctx_data)).tables()["contribution"]
    recorte = tabela[tabela["component"] != "composicao"]
    largo = recorte.pivot(index="period", columns="component", values="contribution").tail(120)
    datas = [str(d) for d in largo.index]
    livres = [float(v) for v in largo["cpi_free"]]
    administrados = [float(v) for v in largo["cpi_administered"]]
    ultimo = largo.iloc[-1]
    return (
        '<article class="modelo">'
        "<h3>De onde vem a inflação</h3>"
        '<p class="sub">Contribuição de cada metade para o IPCA de doze meses, em pontos '
        "percentuais. Os pesos são recuperados em janela móvel de cinco anos e somam um.</p>"
        f"{_duas_linhas(livres, administrados, datas)}"
        f'<div class="legenda"><span class="a">livres {ultimo["cpi_free"]:.2f} p.p.</span>'
        f'<span class="b">administrados {ultimo["cpi_administered"]:.2f} p.p.</span></div>'
        "</article>"
    )


def _phillips(api, ctx_data: dt.date) -> str:
    """A curva do Banco Central estimada sobre o que o catálogo tem."""
    from pathlib import Path as _P

    import econmodels.phillips  # noqa: F401  registra o modelo
    from econmodels.run import run_spec
    from econmodels.specs import load_specs

    spec = load_specs(_P(ROOT) / "specs", model_id="phillips")["br_bcb_small_scale"]
    tabelas = run_spec(api, spec, asof=ctx_data).tables()
    coeficientes = tabelas["coefficients"]
    diag = tabelas["diagnostics"].set_index("metric")["value"]

    linhas = []
    for _, linha in coeficientes.iterrows():
        estimativa, erro = float(linha["estimate"]), float(linha["std_error"])
        mudo = abs(estimativa) < 2 * erro
        marca = ' class="mudo"' if mudo else ""
        linhas.append(
            f"<tr{marca}><td>{linha['name']}</td><td>{estimativa:+.3f}</td>"
            f"<td>±{erro:.3f}</td><td>{'—' if mudo else '•'}</td></tr>"
        )
    return (
        '<article class="modelo">'
        "<h3>Curva de Phillips</h3>"
        f'<p class="sub">Equação agregada do modelo semiestrutural do Banco Central, adaptada ao '
        f"catálogo. Amostra de {diag.get('n_obs', '?')} trimestres, "
        f"especificação <code>{spec.spec_id}</code>.</p>"
        '<table class="coef"><thead><tr><th>termo</th><th>coef.</th><th>erro</th>'
        f"<th>≠0</th></tr></thead><tbody>{''.join(linhas)}</tbody></table>"
        '<p class="sub">Cinza é indistinguível de zero a dois erros-padrão. A folga do produto '
        "está entre eles: nesta amostra a inclinação da curva não se separa de zero, que é o que "
        "a literatura de identificação previa e não um defeito da estimação.</p>"
        "</article>"
    )


def _modelos(api, ctx_data: dt.date) -> str:
    partes = []
    for construir in (_decomposicao, _phillips, _phillips_no_tempo, _duas_curvas):
        try:
            partes.append(construir(api, ctx_data))
        except Exception as erro:  # um modelo que não roda não derruba o boletim inteiro
            # Ausência dita, não exceção exibida: quem lê isto no celular não tem o que fazer com
            # um nome de classe do Python, e o detalhe vai para quem gerou a página.
            print(f"  aviso: {construir.__name__} não gerou — {type(erro).__name__}: {erro}")
            partes.append(
                '<article class="modelo"><h3>Uma seção não pôde ser gerada</h3>'
                '<p class="sub">O modelo não rodou nesta execução. O detalhe ficou no log de '
                "quem gerou a página.</p></article>"
            )
    return (
        '<section><h2>Modelos</h2><div class="grade">' + "".join(partes) + "</div>"
        '<p class="sub" style="margin-top:6px">A regra de Taylor não aparece: o hiato dela vem '
        "da mesma série de PIB que se declara dessazonalizada e não é.</p></section>"
    )


def montar(api, agora: dt.datetime) -> str:
    conceitos = [ind.conceito for bloco in BLOCOS.values() for ind in bloco]
    _conferir_licenca(api, conceitos)

    secoes = []
    for titulo, indicadores in BLOCOS.items():
        cartoes = "".join(_cartao(api, ind) for ind in indicadores)
        if cartoes:
            secoes.append(f'<section><h2>{titulo}</h2><div class="grade">{cartoes}</div></section>')

    secoes.append(_modelos(api, agora.date()))
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
