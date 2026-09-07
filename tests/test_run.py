"""De um arquivo de especificação a um resultado, numa chamada.

Sem isto, cada consumidor montaria o painel à mão: descobrir o modelo pelo `model_id`, ler a
frequência em `requires`, pedir as séries certas, ajustar. Quatro passos e uma ordem, replicados
em cada lugar que quisesse rodar uma variação — e a primeira réplica ia parar dentro de uma tela,
onde a ADR-0008 diz que lógica não mora.

O que estes testes protegem é sobretudo a escolha da frequência. Ela sai do modelo e não de quem
chama, porque quem sabe em que frequência a curva de Phillips estima é a curva de Phillips. Um
painel montado na grade errada não falha: ele desloca por linha o que deveria deslocar por
período, e devolve um número plausível. É o defeito que a guarda de painel existe para impedir, e
ele voltaria por esta porta se a frequência virasse argumento.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

pytest.importorskip("statsmodels", reason="a camada de modelos é um extra")

import econmodels.phillips  # noqa: F401  registra o modelo
from econmodels.base import ConceptRequest
from econmodels.run import RunError, frequency_of, model_for, panel_for_spec, run_spec
from econmodels.specs import load_specs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def specs():
    return load_specs(ROOT / "specs", model_id="phillips")


@pytest.fixture(scope="module")
def api():
    econbase_api = pytest.importorskip("econbase.api")
    try:
        conexao = econbase_api.connect()
        conexao.series()
    except Exception as erro:  # pragma: no cover - máquina sem base coletada
        pytest.skip(f"sem store local: {erro}")
    return conexao


# ------------------------------------------------------------------ resolver o modelo
def test_a_especificacao_encontra_o_seu_modelo(specs) -> None:
    modelo = model_for(specs["br_bcb_small_scale"])
    assert modelo.model_id == "phillips"
    assert modelo.spec.spec_id == "br_bcb_small_scale"


def test_um_model_id_desconhecido_e_recusado_com_a_lista(specs) -> None:
    spec = specs["br_bcb_small_scale"].model_copy(update={"model_id": "inventado"})
    with pytest.raises(RunError, match="inventado"):
        model_for(spec)


# ------------------------------------------------------------------ a frequência é do modelo
def test_a_frequencia_vem_da_declaracao_do_modelo(specs) -> None:
    assert frequency_of(model_for(specs["br_bcb_small_scale"])) == "Q"


class SemFrequencia:
    requires = (ConceptRequest("cpi_headline"),)


class DuasFrequencias:
    requires = (ConceptRequest("cpi_headline", freq="M"), ConceptRequest("gdp_real", freq="Q"))


def test_um_modelo_sem_frequencia_declarada_e_recusado() -> None:
    with pytest.raises(RunError, match="não declara frequência"):
        frequency_of(SemFrequencia())


def test_um_modelo_que_pede_duas_frequencias_e_recusado() -> None:
    """Um painel tem uma grade. Escolher uma por ele seria decidir no lugar de quem sabe."""
    with pytest.raises(RunError, match="mais de uma frequência"):
        frequency_of(DuasFrequencias())


# ------------------------------------------------------------------ contra o store de verdade
def test_o_painel_traz_todas_as_series_que_a_especificacao_le(api, specs) -> None:
    spec = specs["br_bcb_small_scale"]
    painel = panel_for_spec(api, spec)
    esperadas = {f"{c}@{e}" for c, e in spec.concepts()}
    assert esperadas <= set(painel.columns), esperadas - set(painel.columns)


def test_o_painel_sai_na_grade_que_o_modelo_pediu(api, specs) -> None:
    import pandas as pd

    painel = panel_for_spec(api, specs["br_bcb_small_scale"])
    esperado = pd.date_range(painel.index.min(), painel.index.max(), freq="QS")
    assert list(painel.index) == list(esperado)


def test_as_duas_especificacoes_rodam_de_ponta_a_ponta(api, specs) -> None:
    for spec_id, spec in specs.items():
        resultado = run_spec(api, spec, asof=dt.date(2026, 9, 6))
        tabelas = resultado.tables()
        assert "coefficients" in tabelas, spec_id
        assert not tabelas["coefficients"].empty, spec_id


def test_o_resultado_sabe_de_que_especificacao_veio(api, specs) -> None:
    """Um número sem a impressão digital da especificação que o produziu não é comparável."""
    spec = specs["br_bcb_small_scale"]
    resultado = run_spec(api, spec, asof=dt.date(2026, 9, 6))
    diag = resultado.tables()["diagnostics"].set_index("metric")["value"]
    assert str(diag.get("spec_id", "")) == spec.spec_id
    assert spec.spec_hash, "a especificação carregada tem de trazer o seu hash"


def test_as_duas_especificacoes_nao_dao_a_mesma_coisa(api, specs) -> None:
    """Se dessem, a comparação não teria o que comparar e o controle negativo não controlaria.

    `br_exploratoria_hp` usa hiato por Hodrick-Prescott, que filtra o passado com o futuro. Ele
    ajusta melhor dentro da amostra por construção, e isso é o argumento contra ordenar
    especificações por ajuste — não a favor dele.
    """
    banco = run_spec(api, specs["br_bcb_small_scale"], asof=dt.date(2026, 9, 6))
    controle = run_spec(api, specs["br_exploratoria_hp"], asof=dt.date(2026, 9, 6))

    def coeficientes(resultado):
        return resultado.tables()["coefficients"].set_index("name")["estimate"]

    assert set(coeficientes(banco).index) != set(coeficientes(controle).index)
