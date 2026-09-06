"""Testes de aceitação da decomposição livres contra administrados.

O pacote não estima nada de novo sobre a economia — ele reparte o que já está publicado — então
quase todo teste aqui é sobre aritmética que precisa fechar, e sobre uma escolha que precisa ser
defendida com número em vez de gosto: por que o peso é móvel.

A resposta está medida no primeiro teste. O peso de amostra cheia dos administrados é 16%, e o
dos últimos dez anos é 26%. Usar o primeiro para repartir a inflação de hoje erraria a
contribuição dos administrados em cerca de dois quintos.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("econmodels.decomposition", reason="WP-05e não implementado")

from econmodels.base import PanelError, RunContext
from econmodels.decomposition import (
    MIN_WINDOW,
    DecompositionError,
    PriceDecomposition,
    _weights,
)

FIX = Path(__file__).parent / "fixtures" / "analysis" / "br_ipca_decomposicao.csv"
PARTS = ("cpi_free", "cpi_administered")


def ctx(asof: str = "2026-09-06") -> RunContext:
    return RunContext(asof=dt.date.fromisoformat(asof))


#: A fixture guarda os nomes em português com que as séries foram gravadas; o modelo fala em
#: conceitos. O mapa é explícito porque a primeira versão deste arquivo tentou adivinhar e um
#: `skip` defensivo engoliu os catorze testes sem que nada ficasse vermelho.
COLUNAS = {
    "ipca": "cpi_headline",
    "livres": "cpi_free",
    "administrados": "cpi_administered",
}


def panel() -> pd.DataFrame:
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    faltando = set(COLUNAS) - set(raw.columns)
    assert not faltando, f"a fixture mudou de forma e não traz {sorted(faltando)}"
    return raw[list(COLUNAS)].rename(columns=COLUNAS).add_suffix("@BR")


@pytest.fixture(scope="module")
def fitted():
    return PriceDecomposition().fit(panel(), ctx())


def at_latest(result) -> pd.DataFrame:
    table = result.tables()["contribution"]
    return table[table["period"] == table["period"].max()].set_index("component")


# ------------------------------------------------------------------ por que o peso é móvel
def test_o_peso_de_amostra_cheia_erraria_o_de_hoje_por_muito() -> None:
    """A medição que justifica a janela móvel, e não o contrário.

    A participação dos administrados subiu de cerca de 18% nos anos noventa para cerca de 26%
    hoje. Um peso único de amostra cheia é puxado para baixo pela hiperinflação até 1994, quando
    a variância dos preços livres dominava tudo, e passa a não servir a nenhuma ponta.
    """
    frame = panel()
    headline = frame["cpi_headline@BR"]
    parts = frame[[f"{p}@BR" for p in PARTS]]
    parts.columns = list(PARTS)

    inteira = _weights(headline, parts, window=len(frame))
    recente = _weights(headline, parts, window=60)
    cheia = float(inteira.iloc[-1]["cpi_administered"])
    hoje = float(recente.iloc[-1]["cpi_administered"])

    assert hoje > cheia, "os administrados pesam mais hoje do que na média da amostra"
    assert hoje - cheia > 0.05, (
        f"a diferença é de {hoje - cheia:.3f}, pequena demais para justificar janela móvel"
    )


def test_o_peso_se_move_ao_longo_do_tempo(fitted) -> None:
    caminho = fitted.tables()["weights"]
    administrados = caminho[caminho["component"] == "cpi_administered"]["weight"]
    assert administrados.max() - administrados.min() > 0.03, (
        "um peso que não se move não precisava de janela"
    )


# ------------------------------------------------------------------ a aritmética tem de fechar
def test_os_pesos_somam_um_em_toda_janela(fitted) -> None:
    """É o que uma média ponderada significa, e é imposto por construção, não esperado."""
    caminho = fitted.tables()["weights"]
    soma = caminho.groupby("period")["weight"].sum()
    assert np.allclose(soma.to_numpy(dtype="float64"), 1.0, atol=1e-9)


def test_as_participacoes_somam_um_em_todo_periodo(fitted) -> None:
    """Incluída a linha de composição. Sem ela somariam 0,976 e a tabela pareceria errada."""
    tabela = fitted.tables()["contribution"]
    soma = tabela.groupby("period")["share"].sum()
    assert np.allclose(soma.to_numpy(dtype="float64"), 1.0, atol=1e-9)


def test_a_composicao_e_uma_linha_e_nao_um_erro_escondido(fitted) -> None:
    """Somar doze contribuições mensais não dá a inflação de doze meses, porque um índice compõe
    e uma soma não. A diferença é nomeada em vez de espalhada nas outras linhas."""
    tabela = fitted.tables()["contribution"]
    assert "composicao" in set(tabela["component"])
    linha = at_latest(fitted).loc["composicao"]
    assert pd.isna(linha["weight"]), "composição não tem peso: não é uma parte da cesta"
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    assert float(diag["residual_mean_pp"]) < float(diag["residual_max_pp"])


def test_a_contribuicao_e_o_peso_vezes_a_taxa(fitted) -> None:
    """A checagem que impede a tabela de virar três colunas que não conversam."""
    ultimo = at_latest(fitted)
    for parte in PARTS:
        linha = ultimo.loc[parte]
        aproximado = float(linha["weight"]) * float(linha["rate_12m"])
        # acumular contribuições mensais não é multiplicar a taxa acumulada, mas fica perto
        assert abs(float(linha["contribution"]) - aproximado) < 0.6


def test_cada_parte_carrega_peso_taxa_e_contribuicao(fitted) -> None:
    ultimo = at_latest(fitted)
    for parte in PARTS:
        assert parte in ultimo.index
        for coluna in ("weight", "rate_12m", "contribution", "share"):
            assert not pd.isna(ultimo.loc[parte, coluna])


# ------------------------------------------------------------------ diagnósticas e recusas
def test_as_diagnosticas_dizem_a_janela_e_o_peso_de_hoje(fitted) -> None:
    diag = fitted.tables()["diagnostics"].set_index("metric")["value"]
    assert int(diag["window_months"]) == 60
    assert diag["weights_sum_to"].startswith("1")
    assert 0.0 < float(diag["weight_cpi_administered"]) < 1.0


def test_uma_janela_curta_demais_e_recusada() -> None:
    with pytest.raises(DecompositionError, match="curta demais"):
        PriceDecomposition(window=MIN_WINDOW - 1).fit(panel(), ctx())


def test_uma_amostra_curta_demais_para_a_janela_e_recusada() -> None:
    with pytest.raises(DecompositionError, match="não bastam"):
        PriceDecomposition(window=120).fit(panel().head(100), ctx())


def test_um_painel_trimestral_e_recusado_antes_de_qualquer_conta() -> None:
    curto = panel()
    curto.index = pd.date_range("1996-01-01", periods=len(curto), freq="QS")
    with pytest.raises(PanelError):
        PriceDecomposition().fit(curto, ctx())


def test_uma_parte_ausente_do_painel_e_nomeada() -> None:
    sem = panel().drop(columns=["cpi_administered@BR"])
    with pytest.raises(PanelError, match="cpi_administered"):
        PriceDecomposition().fit(sem, ctx())


def test_a_restricao_de_soma_um_so_vale_para_duas_partes() -> None:
    """Escrita para duas. Três partes precisam de outra álgebra, e a mensagem diz isso."""
    frame = panel()
    tres = frame[[f"{p}@BR" for p in PARTS] + ["cpi_headline@BR"]]
    tres.columns = ["a", "b", "c"]
    with pytest.raises(DecompositionError, match="duas partes"):
        _weights(frame["cpi_headline@BR"], tres, window=60)


def test_o_modelo_pede_conceitos_e_nao_series(fitted) -> None:
    precisa = {r.concept for r in PriceDecomposition().requires}
    assert precisa == {"cpi_headline", "cpi_free", "cpi_administered"}


# ------------------------------------------------------------------ o segundo nível
SEGUNDO = ("cpi_services", "cpi_tradables")


def painel_livres() -> pd.DataFrame:
    raw = pd.read_csv(FIX, parse_dates=["period"]).set_index("period")
    mapa = {"livres": "cpi_free", "servicos": "cpi_services", "comercializaveis": "cpi_tradables"}
    faltando = set(mapa) - set(raw.columns)
    assert not faltando, f"a fixture não traz {sorted(faltando)}"
    return raw[list(mapa)].rename(columns=mapa).add_suffix("@BR")


@pytest.fixture(scope="module")
def nivel_dois():
    return PriceDecomposition(headline="cpi_free", parts=SEGUNDO).fit(painel_livres(), ctx())


def test_a_mesma_algebra_reparte_os_livres_em_servicos_e_comercializaveis(nivel_dois) -> None:
    """Os livres são eles próprios a soma ponderada de duas partes, e nada no modelo precisou
    mudar para descer um nível: é a mesma restrição de soma um sobre outro par."""
    ultimo = nivel_dois.tables()["contribution"]
    ultimo = ultimo[ultimo["period"] == ultimo["period"].max()].set_index("component")
    for parte in SEGUNDO:
        assert parte in ultimo.index
    assert abs(float(ultimo["share"].sum()) - 1.0) < 1e-9


def test_os_pesos_do_segundo_nivel_tambem_somam_um(nivel_dois) -> None:
    caminho = nivel_dois.tables()["weights"]
    soma = caminho.groupby("period")["weight"].sum()
    assert np.allclose(soma.to_numpy(dtype="float64"), 1.0, atol=1e-9)


def test_requires_descreve_a_instancia_e_nao_a_classe() -> None:
    """Um `requires` fixo declararia os conceitos do primeiro nível mesmo trabalhando no segundo.

    Decorativo hoje, porque `fit` resolve as colunas por conta própria — e mentira no dia em que
    algo passar a ler a declaração para montar o painel, que é exatamente o que `panel_for` faz
    nos outros modelos.
    """
    primeiro = {r.concept for r in PriceDecomposition().requires}
    segundo = {r.concept for r in PriceDecomposition(headline="cpi_free", parts=SEGUNDO).requires}
    assert primeiro == {"cpi_headline", "cpi_free", "cpi_administered"}
    assert segundo == {"cpi_free", *SEGUNDO}
    assert all(r.freq == "M" for r in PriceDecomposition().requires)
