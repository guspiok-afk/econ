"""A vista, exercida sem navegador.

O `AppTest` do Streamlit roda o script de ponta a ponta num processo só e devolve os elementos
que ele desenhou. Vale mais que uma captura de tela: um teste continua rodando amanhã.

O que se tranca aqui é o que a ADR-0008 promete. Que a tela abre. Que o interruptor de
redistribuição realmente esconde as trinta e três séries de licença restrita, em vez de só mudar
uma legenda. E que uma série restrita avisa quando aparece — porque um aplicativo que mostra tudo
serve para uso próprio e não pode ser mostrado a mais ninguém, e descobrir isso depois de
construídas as telas é caro.

Estes testes leem o store real. Numa máquina sem base coletada eles pulam em vez de falhar: a
ausência de dado não é defeito da vista.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="a vista é um extra: uv sync --extra app")

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / "app" / "painel.py")


def rodar() -> AppTest:
    api = pytest.importorskip("econbase.api")
    try:
        catalogo = api.connect().series().to_pandas()
    except Exception as erro:  # pragma: no cover - máquina sem base coletada
        pytest.skip(f"sem store local: {erro}")
    if catalogo.empty:  # pragma: no cover
        pytest.skip("store vazio")
    return AppTest.from_file(SCRIPT, default_timeout=180).run()


@pytest.fixture(scope="module")
def app() -> AppTest:
    return rodar()


def test_a_tela_abre_sem_excecao(app: AppTest) -> None:
    assert not app.exception, [str(e.value) for e in app.exception]
    assert not app.error, [e.value for e in app.error]


def test_os_controles_estao_todos_la(app: AppTest) -> None:
    rotulos = {s.label for s in app.sidebar.selectbox}
    assert rotulos == {"Entidade", "Conceito", "Frequência", "Transformação"}
    assert [t.label for t in app.sidebar.toggle] == ["Só o que pode sair daqui"]


def test_a_tela_desenha_uma_serie(app: AppTest) -> None:
    assert app.title, "nenhum título — a série não chegou a ser resolvida"
    assert len(app.dataframe) >= 2, "faltam as tabelas de observações e cobertura"


# ------------------------------------------------------------------ a restrição de licença
def test_o_interruptor_esconde_de_verdade_e_nao_so_avisa() -> None:
    """A parte que importa: ele filtra o catálogo, não muda uma legenda.

    Um interruptor que anuncia esconder e não esconde é pior que nenhum, porque cria confiança
    onde não há.
    """
    api = pytest.importorskip("econbase.api")
    try:
        catalogo = api.connect().series().to_pandas()
    except Exception as erro:  # pragma: no cover
        pytest.skip(f"sem store local: {erro}")

    restritas = catalogo[~catalogo["redistributable"]]
    if restritas.empty:  # pragma: no cover - nada a esconder nesta máquina
        pytest.skip("nenhuma série restrita no catálogo local")

    aberto = AppTest.from_file(SCRIPT, default_timeout=180).run()
    todos_conceitos = set(aberto.sidebar.selectbox[1].options)

    fechado = AppTest.from_file(SCRIPT, default_timeout=180)
    fechado.run()
    fechado.sidebar.toggle[0].set_value(True).run()
    livres = set(fechado.sidebar.selectbox[1].options)

    assert not fechado.exception, [str(e.value) for e in fechado.exception]
    assert livres <= todos_conceitos
    entidade = fechado.sidebar.selectbox[0].value
    restritas_da_entidade = set(
        restritas[restritas["entity_id"] == entidade]["concept_id"].dropna()
    )
    livres_da_entidade = set(
        catalogo[(catalogo["entity_id"] == entidade) & catalogo["redistributable"]][
            "concept_id"
        ].dropna()
    )
    so_restritas = restritas_da_entidade - livres_da_entidade
    assert not (livres & so_restritas), (
        f"o interruptor deixou passar conceitos que só existem em série restrita: "
        f"{sorted(livres & so_restritas)}"
    )


def test_a_legenda_conta_quantas_serie_estao_em_jogo(app: AppTest) -> None:
    """Contagem aferida do catálogo, não número escrito à mão."""
    legendas = " ".join(c.value for c in app.sidebar.caption)
    assert "republicadas" in legendas or "Escondendo" in legendas
    assert any(char.isdigit() for char in legendas)


def test_uma_serie_restrita_avisa_ao_aparecer() -> None:
    """Sem isto a licença é uma coluna do catálogo que ninguém lê no momento que importa."""
    api = pytest.importorskip("econbase.api")
    try:
        catalogo = api.connect().series().to_pandas()
    except Exception as erro:  # pragma: no cover
        pytest.skip(f"sem store local: {erro}")

    restritas = catalogo[~catalogo["redistributable"] & catalogo["concept_id"].notna()]
    if restritas.empty:  # pragma: no cover
        pytest.skip("nenhuma série restrita no catálogo local")
    alvo = restritas.iloc[0]

    app = AppTest.from_file(SCRIPT, default_timeout=180)
    app.run()
    app.sidebar.selectbox[0].set_value(alvo["entity_id"]).run()
    app.sidebar.selectbox[1].set_value(alvo["concept_id"]).run()

    assert not app.exception, [str(e.value) for e in app.exception]
    assert app.warning, f"{alvo['series_id']} é restrita e a tela não avisou"
    assert "republicada" in " ".join(w.value for w in app.warning)


# ------------------------------------------------------------------ a vista é fina
def test_a_vista_nao_importa_modelo_nenhum() -> None:
    """ADR-0008. A tela chama a API de leitura; ela não estima.

    O dia em que precisar de um número que a API não dá, o número vira função de modelo com
    teste — e não uma conta no meio do desenho, onde ninguém a revisa.
    """
    fonte = (ROOT / "app" / "painel.py").read_text(encoding="utf-8")
    assert "import econmodels" not in fonte
    assert "from econmodels" not in fonte
    assert "statsmodels" not in fonte
