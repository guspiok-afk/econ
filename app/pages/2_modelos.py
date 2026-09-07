"""Duas especificações do mesmo modelo, lado a lado.

Era o pedido original: "faz sentido um modelo poder ter mais de uma especificação e testarmos
variações deles". A ADR-0007 respondeu onde a variação mora — num arquivo, com `spec_id` e
`spec_hash` — e esta tela é onde ela finalmente se lê.

A comparação só significa alguma coisa porque cada coluna carrega o seu `spec_hash`. Duas
estimativas de "a mesma" curva de Phillips não são comparáveis se uma delas mudou de forma no
caminho, e um número sem a impressão digital da especificação que o produziu é uma afirmação sem
endereço.

O que já se sabe e vale ter em vista ao olhar: `br_bcb_small_scale` segue a equação do Banco
Central e `br_exploratoria_hp` é um controle negativo deliberado — hiato por Hodrick-Prescott,
que usa o futuro para filtrar o passado. A segunda ajusta melhor dentro da amostra. Isso não é
uma vitória dela; é a demonstração de por que ajuste dentro da amostra não decide nada.

ADR-0008: nada é calculado aqui. `econmodels.run.run_spec` monta o painel e ajusta.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

# A pasta do aplicativo não entra no `sys.path` quando o Streamlit executa uma página —
# medido, não suposto — então a porta de entrada precisa ser alcançável assim, antes de
# qualquer outro import do próprio aplicativo.
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st
from acesso import aviso_de_modo_aberto, exigir_senha

import econmodels.decomposition
import econmodels.phillips  # noqa: F401  registra o modelo
from econbase.api import connect
from econmodels.run import RunError, run_spec
from econmodels.specs import load_specs

st.set_page_config(page_title="Modelos", page_icon="🧪", layout="wide")

exigir_senha()
RAIZ = Path(__file__).resolve().parents[2]


@st.cache_resource
def api():
    return connect()


@st.cache_data(ttl=600)
def especificacoes() -> dict[str, dict]:
    """Todas as especificações do repositório, agrupadas por modelo."""
    por_modelo: dict[str, dict] = {}
    for spec_id, spec in load_specs(RAIZ / "specs").items():
        por_modelo.setdefault(spec.model_id, {})[spec_id] = spec
    return por_modelo


def executar(spec, asof: dt.date):
    return run_spec(api(), spec, asof=asof)


def desenhavel(tabela: pd.DataFrame) -> pd.DataFrame:
    """Colunas de tipo misto viram texto antes de chegar à tela.

    Uma tabela de diagnósticas guarda `n_obs` e `spec_id` na mesma coluna, o que em pandas é
    `object`. O Arrow recusa converter e a tabela simplesmente não aparece, com o erro só no
    terminal — falha silenciosa na vista, que é a pior categoria. Três telas tropeçaram nisso
    antes de virar função.
    """
    saida = tabela.copy()
    for coluna in saida.columns:
        if saida[coluna].dtype == "object":
            saida[coluna] = saida[coluna].astype(str)
    return saida


st.sidebar.title("Modelos")
aviso_de_modo_aberto()
catalogo_specs = especificacoes()
if not catalogo_specs:
    st.error("Nenhuma especificação em `specs/`.")
    st.stop()

modelo = st.sidebar.selectbox("Modelo", sorted(catalogo_specs))
disponiveis = catalogo_specs[modelo]
escolhidas = st.sidebar.multiselect(
    "Especificações",
    sorted(disponiveis),
    default=sorted(disponiveis)[:2],
    help="Duas ou mais para comparar. Cada coluna mostra o seu spec_hash.",
)
quando = st.sidebar.date_input("Como se soubesse em", value=dt.date.today())

st.title(f"{modelo} — variações")

if not escolhidas:
    st.info("Escolha ao menos uma especificação na barra lateral.")
    st.stop()

resultados: dict[str, object] = {}
for spec_id in escolhidas:
    spec = disponiveis[spec_id]
    try:
        with st.spinner(f"estimando {spec_id}…"):
            resultados[spec_id] = executar(spec, quando)
    except (RunError, ValueError) as erro:
        st.error(f"**{spec_id}**: {erro}")

if not resultados:
    st.stop()

# ------------------------------------------------------------------ o que cada uma é
st.subheader("Procedência")
st.dataframe(
    pd.DataFrame(
        [
            {
                "especificação": spec_id,
                "spec_hash": disponiveis[spec_id].spec_hash[:12],
                "segue": " ".join((disponiveis[spec_id].provenance.follows or "—").split())[:150],
                "afasta-se": " ".join((disponiveis[spec_id].provenance.departs or "—").split())[
                    :150
                ],
            }
            for spec_id in resultados
        ]
    ),
    hide_index=True,
    width="stretch",
)

# ------------------------------------------------------------------ coeficientes lado a lado
st.subheader("Coeficientes")
colunas = {}
for spec_id, resultado in resultados.items():
    tabela = resultado.tables().get("coefficients")
    if tabela is None:
        continue
    colunas[spec_id] = tabela.set_index("name")["estimate"]
if colunas:
    st.dataframe(pd.DataFrame(colunas).round(4), width="stretch")
    st.caption(
        "Termo ausente numa coluna significa que aquela especificação não o inclui — não que o "
        "coeficiente seja zero."
    )

# ------------------------------------------------------------------ o que a curva acertou
ajustes = {}
for spec_id, resultado in resultados.items():
    tabela = resultado.tables().get("fitted")
    if tabela is None or tabela.empty:
        continue
    ajustes[spec_id] = tabela

if ajustes:
    st.subheader("Realizado contra previsto")
    st.caption(
        "Uma curva de Phillips é uma relação, não uma série: o que se desenha ao longo do tempo é "
        "o que ela acertou. A taxa de política entra no mesmo eixo — é onde a pergunta “contra a "
        "Selic”, ou contra a fed funds, faz sentido."
    )
    for spec_id, tabela in ajustes.items():
        entidade = disponiveis[spec_id].entity
        quadro = tabela.set_index("period")[["actual", "fitted"]]
        quadro.columns = ["realizado", "previsto pela curva"]
        try:
            juros = (
                api()
                .get("policy_rate", entity=entidade, freq="Q", agg="eop", as_pandas=True)
                .set_index("period")["value"]
            )
            quadro = quadro.join(juros.rename("taxa de política"), how="left")
        except Exception as erro:  # a série de juros pode não existir para a entidade
            st.caption(f"sem taxa de política para {entidade}: {erro}")
        st.markdown(f"**{spec_id}** · {entidade}")
        st.line_chart(quadro, height=300)
        erro_medio = float(tabela["residual"].abs().mean())
        st.caption(
            f"Erro absoluto médio de {erro_medio:.2f} ponto por trimestre em {len(tabela)} "
            "trimestres."
        )


# ------------------------------------------------------------------ diagnósticas
st.subheader("Diagnósticas")
diagnosticas = {}
for spec_id, resultado in resultados.items():
    tabela = resultado.tables().get("diagnostics")
    if tabela is not None:
        diagnosticas[spec_id] = tabela.set_index("metric")["value"].astype(str)
if diagnosticas:
    st.dataframe(desenhavel(pd.DataFrame(diagnosticas)), width="stretch")

st.warning(
    "Ajuste dentro da amostra não ordena especificações. Uma que usa o futuro para filtrar o "
    "passado — hiato por Hodrick-Prescott, por exemplo — ajusta melhor por construção e prevê "
    "pior. Compare procedência e restrições antes de comparar R².",
    icon="⚖️",
)

with st.expander("As tabelas inteiras, por especificação"):
    for spec_id, resultado in resultados.items():
        st.markdown(f"**{spec_id}** · `{disponiveis[spec_id].spec_hash[:12]}`")
        for nome, tabela in resultado.tables().items():
            st.caption(nome)
            st.dataframe(desenhavel(tabela), hide_index=True, width="stretch")

st.caption("Execução por `econmodels.run.run_spec`; esta tela não calcula. Ver ADR-0007 e 0008.")
