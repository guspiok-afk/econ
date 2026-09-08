"""O arranjo da comparação, testado sem baixar modelo nenhum.

Os pesos do Chronos não estão no repositório e não vão estar: peso de modelo não é código. Então
o teste que precisa deles pula, e o resto — que é a parte onde um erro estraga a comparação — roda
sempre.

A parte que importa é a **justiça**. Uma comparação em que um dos lados enxerga um trimestre a
mais não mede nada, e a forma de errar isso é silenciosa: o número sai plausível. Por isso o
recorte da janela é testado com mais cuidado que o resultado.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("statsmodels", reason="a camada de modelos é um extra")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "bench_nowcast.py"


def _carregar():
    spec = importlib.util.spec_from_file_location("bench_nowcast", SCRIPT)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["bench_nowcast"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def bench():
    return _carregar()


# ------------------------------------------------------------------ a janela é a mesma para todos
def test_o_alvo_do_trimestre_corrente_fica_escondido(bench) -> None:
    """A armadilha que este projeto já pisou uma vez.

    Uma série trimestral fica na grade no mês em que o trimestre COMEÇA, então cortar em março de
    2018 mantém o PIB do primeiro trimestre — um número que o Bureau só publica no fim de abril.
    Sem esconder, o competidor que lê o painel recebe a resposta que deveria estimar.
    """
    painel = bench.visivel_ate("2018-03")
    ultimo = painel["gdp_real@US"].dropna().index.max()
    assert ultimo < pd.Timestamp("2018-01-01"), (
        f"o PIB de 2018Q1 continua visível em março de 2018 (último: {ultimo.date()})"
    )


def test_um_corte_mais_tarde_enxerga_mais(bench) -> None:
    cedo = bench.crescimento(bench.visivel_ate("2018-03"))
    tarde = bench.crescimento(bench.visivel_ate("2018-09"))
    assert len(tarde) > len(cedo)


def test_todos_recebem_a_mesma_historia(bench) -> None:
    """O Chronos e a média leem a mesma série; o fator dinâmico lê o mesmo painel. Se a janela
    divergisse entre eles a comparação seria entre janelas, não entre modelos."""
    painel = bench.visivel_ate("2024-05")
    historia = bench.crescimento(painel)
    assert historia.index.max() < pd.Period("2024Q2", freq="Q")
    assert float(historia.mean()) == float(historia.mean())  # sem NaN
    assert not historia.isna().any()


def test_o_crescimento_e_uma_taxa_e_nao_um_nivel(bench) -> None:
    historia = bench.crescimento(bench.painel_completo())
    assert historia.abs().max() < 30, "isto não parece taxa de crescimento trimestral"
    assert isinstance(historia.index, pd.PeriodIndex)


# ------------------------------------------------------------------ a conta do erro
def test_o_erro_e_zero_quando_a_previsao_acerta(bench) -> None:
    quadro = pd.DataFrame({"realizado": [1.0, 2.0, 3.0], "x": [1.0, 2.0, 3.0]})
    assert bench.erro(quadro, "x") == 0.0


def test_o_erro_quadratico_medio_e_o_que_diz_ser(bench) -> None:
    quadro = pd.DataFrame({"realizado": [0.0, 0.0], "x": [3.0, 4.0]})
    assert bench.erro(quadro, "x") == pytest.approx(np.sqrt(12.5))


def test_o_relatorio_marca_o_vencedor_de_cada_recorte(bench) -> None:
    quadro = pd.DataFrame(
        {
            "trimestre": ["2020Q1", "2022Q1", "2023Q1"],
            "realizado": [1.0, 1.0, 1.0],
            "dfm": [1.0, 5.0, 5.0],
            "chronos": [5.0, 1.0, 1.0],
            "media": [5.0, 5.0, 5.0],
            "passeio": [9.0, 9.0, 9.0],
        }
    )
    texto = bench.relatar(quadro)
    assert "2018-2025 completo" in texto and "2022-2025 (calmo)" in texto
    calmo = next(linha for linha in texto.splitlines() if linha.startswith("2022-2025"))
    # nos anos calmos o chronos acerta e o dfm erra: a estrela tem de estar na coluna dele
    assert calmo.index("*") > calmo.index("0.000") or "0.000*" in calmo


def test_o_relatorio_diz_que_o_chronos_e_univariado(bench) -> None:
    """Sem essa linha o leitor compara dois números sem saber que um dos lados via mais."""
    quadro = pd.DataFrame(
        {
            "trimestre": ["2023Q1"],
            "realizado": [1.0],
            "dfm": [1.0],
            "chronos": [1.0],
            "media": [1.0],
            "passeio": [1.0],
        }
    )
    assert "univariado" in bench.relatar(quadro)


# ------------------------------------------------------------------ com os pesos, se existirem
def test_o_chronos_preve_um_numero_plausivel(bench) -> None:
    pytest.importorskip("chronos", reason="a comparação é um extra: uv sync --extra bench")
    pesos = Path(bench.PESOS_PADRAO) / "chronos-bolt-tiny"
    if not (pesos / "config.json").exists():
        pytest.skip(f"pesos ausentes em {pesos}")

    tubo = bench.carregar_chronos(pesos)
    historia = bench.crescimento(bench.visivel_ate("2024-05"))
    previsao = bench.prever_chronos(tubo, historia)
    assert abs(previsao) < 10, f"previsão de crescimento trimestral implausível: {previsao}"
