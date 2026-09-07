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


# ------------------------------------------------------------------ a tela de vintages
VINTAGES = str(ROOT / "app" / "pages" / "1_vintages.py")


@pytest.fixture(scope="module")
def vintages() -> AppTest:
    api = pytest.importorskip("econbase.api")
    try:
        api.connect().series()
    except Exception as erro:  # pragma: no cover
        pytest.skip(f"sem store local: {erro}")
    return AppTest.from_file(VINTAGES, default_timeout=180).run()


def test_a_tela_de_vintages_abre(vintages: AppTest) -> None:
    assert not vintages.exception, [str(e.value) for e in vintages.exception]
    assert not vintages.error, [e.value for e in vintages.error]


def test_ela_diz_de_que_tipo_e_a_vintage_que_desenhou(vintages: AppTest) -> None:
    """Sem isso a tela desenharia história gravada e simulação com o mesmo traço.

    `true` é o que a fonte publicou na ocasião; `pseudo` é o valor de hoje recuado pela
    defasagem, que responde quando algo passou a ser conhecido e não o que foi dito. Mostrar as
    duas iguais é mentir por omissão, e é a razão de o aviso ser um bloco e não uma legenda.
    """
    dito = " ".join([s.value for s in vintages.success] + [i.value for i in vintages.info])
    assert "gravada" in dito or "simulada" in dito

    tabela = vintages.dataframe[0].value.set_index("campo")["valor"]
    assert tabela["tipo de vintage"] in {"true", "pseudo", "mixed", "latest"}


def test_a_tabela_de_numeros_e_toda_texto(vintages: AppTest) -> None:
    """Uma coluna que mistura número e travessão vira `object`, e o pyarrow recusa convertê-la:
    a tabela some da tela e o erro fica só no terminal. Aconteceu ao escrever esta página."""
    coluna = vintages.dataframe[0].value["valor"]
    assert all(isinstance(v, str) for v in coluna), coluna.tolist()


def test_ela_compara_duas_leituras_da_mesma_serie(vintages: AppTest) -> None:
    tabela = vintages.dataframe[0].value.set_index("campo")["valor"]
    assert {"observações então", "observações hoje", "períodos em comum"} <= set(tabela.index)
    assert int(tabela["observações hoje"].replace(".", "")) >= int(
        tabela["observações então"].replace(".", "")
    ), "a leitura de hoje não pode ter menos períodos que a de uma data passada"


def test_a_tela_de_vintages_tambem_nao_calcula() -> None:
    fonte = (ROOT / "app" / "pages" / "1_vintages.py").read_text(encoding="utf-8")
    assert "from econmodels" not in fonte and "import econmodels" not in fonte


# ------------------------------------------------------------------ a tela de modelos
MODELOS = str(ROOT / "app" / "pages" / "2_modelos.py")


@pytest.fixture(scope="module")
def modelos() -> AppTest:
    pytest.importorskip("statsmodels", reason="a camada de modelos é um extra")
    api = pytest.importorskip("econbase.api")
    try:
        api.connect().series()
    except Exception as erro:  # pragma: no cover
        pytest.skip(f"sem store local: {erro}")
    return AppTest.from_file(MODELOS, default_timeout=300).run()


def test_a_tela_de_modelos_abre_e_estima(modelos: AppTest) -> None:
    assert not modelos.exception, [str(e.value) for e in modelos.exception]
    assert not modelos.error, [e.value for e in modelos.error]
    assert {"Procedência", "Coeficientes", "Diagnósticas"} <= {s.value for s in modelos.subheader}


def test_cada_coluna_carrega_o_seu_spec_hash(modelos: AppTest) -> None:
    """A comparação só significa algo com a impressão digital de cada especificação ao lado.

    Duas estimativas da "mesma" curva não são comparáveis se uma mudou de forma no caminho, e um
    número sem endereço não é comparável com nada.
    """
    procedencia = modelos.dataframe[0].value
    assert {"especificação", "spec_hash", "segue", "afasta-se"} <= set(procedencia.columns)
    assert procedencia["spec_hash"].str.len().gt(0).all()
    assert procedencia["spec_hash"].nunique() == len(procedencia), "hashes repetidos"


def test_os_coeficientes_ficam_lado_a_lado(modelos: AppTest) -> None:
    coeficientes = modelos.dataframe[1].value
    assert len(coeficientes.columns) >= 2, "menos de duas especificações para comparar"
    assert coeficientes.notna().any().all(), "alguma coluna veio inteira vazia"


def test_a_tela_avisa_que_ajuste_dentro_da_amostra_nao_ordena(modelos: AppTest) -> None:
    """O aviso existe porque o controle negativo AJUSTA MELHOR: o hiato por Hodrick-Prescott usa
    o futuro para filtrar o passado. Sem esse aviso a tela convidaria a escolher pelo R²."""
    assert modelos.warning
    dito = " ".join(w.value for w in modelos.warning)
    assert "Hodrick-Prescott" in dito or "dentro da amostra" in dito


def test_a_tela_de_modelos_nao_estima_por_conta_propria() -> None:
    """Ela importa `econmodels` para registrar os modelos e chama `run_spec`. Não faz conta."""
    fonte = (ROOT / "app" / "pages" / "2_modelos.py").read_text(encoding="utf-8")
    assert "run_spec" in fonte
    for proibido in ("OLS(", "statsmodels", ".fit(", "np."):
        assert proibido not in fonte, f"a tela contém {proibido!r}: a conta está no lugar errado"
