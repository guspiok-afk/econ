"""O que se sabia naquele dia, ao lado do que se sabe hoje.

É a razão de a base guardar histórico de revisão desde o primeiro dia (ADR-0002), e até esta tela
existir ela era invisível: o dado estava lá e não havia como olhar para ele. O desemprego
americano de abril de 2020 foi publicado em 14,7% e hoje lê 14,8% — pequeno, e é essa a diferença
entre avaliar uma decisão com o número que o decisor tinha e com o número que sobrou depois.

A tela mostra as duas séries sobrepostas e a diferença entre elas, e diz **de que tipo** é a
vintage que produziu a linha antiga. Isso não é detalhe: `true` é história gravada como foi
publicada; `pseudo` é o valor de hoje recuado pela defasagem de publicação, o que responde
*quando* algo se tornou conhecido e não *o que* foi dito na época. Uma tela que desenhasse as duas
com o mesmo traço estaria mentindo por omissão.

ADR-0008: aqui não se calcula. A diferença entre as duas séries é subtração de coluna, que é
desenho; qualquer coisa além disso vira função com teste do outro lado.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

# A pasta do aplicativo não entra no `sys.path` quando o Streamlit executa uma página —
# medido, não suposto — então a porta de entrada precisa ser alcançável assim, antes de
# qualquer outro import do próprio aplicativo.
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import datetime as dt

import pandas as pd
import streamlit as st
from acesso import aviso_de_modo_aberto, exigir_senha

from econbase.api import connect
from econbase.vintages import VINTAGE_KINDS, VintageError

st.set_page_config(page_title="Vintages", page_icon="🕰️", layout="wide")

exigir_senha()


@st.cache_resource
def api():
    return connect()


@st.cache_data(ttl=600)
def catalogo() -> pd.DataFrame:
    return api().series().to_pandas()


@st.cache_data(ttl=600)
def leitura(concept: str, entity: str, asof: dt.date | None, kind: str) -> tuple[pd.DataFrame, str]:
    """A série e o tipo de vintage que a produziu, sempre juntos."""
    frame = api().get(concept, entity=entity, asof=asof, vintage_kind=kind)
    return frame, api().vintage_used(concept, entity) or kind


st.sidebar.title("Vintages")
aviso_de_modo_aberto()

todas = catalogo()
apenas_livres = st.sidebar.toggle("Só o que pode sair daqui", value=False)
visiveis = todas[todas["redistributable"]] if apenas_livres else todas

paises = sorted(visiveis["entity_id"].unique())
if not paises:
    st.error("Nenhuma série visível com o filtro atual.")
    st.stop()
entidade = st.sidebar.selectbox(
    "Entidade", paises, index=paises.index("US") if "US" in paises else 0
)
conceitos = sorted(visiveis[visiveis["entity_id"] == entidade]["concept_id"].dropna().unique())
if not conceitos:
    st.error(f"Nenhuma série de {entidade} visível com o filtro atual.")
    st.stop()
conceito = st.sidebar.selectbox("Conceito", conceitos)

st.sidebar.divider()
quando = st.sidebar.date_input(
    "O que se sabia em",
    value=dt.date(2018, 6, 30),
    min_value=dt.date(1960, 1, 1),
    max_value=dt.date.today(),
    help="A data de conhecimento, não o período da observação.",
)
tipo = st.sidebar.selectbox(
    "Tipo de vintage",
    [k for k in VINTAGE_KINDS if k != "latest"],
    help=(
        "true: história gravada. pseudo: valor de hoje recuado pela defasagem. mixed: o que houver."
    ),
)

ficha = api().describe(conceito, entidade)
st.title(f"{ficha['title'] or conceito} — antes e agora")
st.caption(f"`{ficha['series_id']}` · defasagem declarada de {ficha['expected_lag_days']} dias")

if not ficha["redistributable"]:
    st.warning(f"**{ficha['license']}**: use, não republique.", icon="⚠️")

hoje, _ = leitura(conceito, entidade, None, "latest")
try:
    antes, usada = leitura(conceito, entidade, quando, tipo)
except VintageError as erro:
    st.error(str(erro))
    st.info(
        "Séries coletadas por este projeto não têm história anterior ao início da coleta. "
        "`pseudo` simula a partir da defasagem de publicação; `true` só responde onde a fonte "
        "publica períodos em tempo real, o que hoje é o FRED."
    )
    st.stop()

if antes.empty:
    st.info("Nada era conhecido nessa data.")
    st.stop()

if usada == "pseudo":
    st.info(
        "Esta linha é **simulada**: é o valor de hoje recuado pela defasagem de publicação. "
        "Ela diz quando um período passou a ser conhecido, e não o que foi dito na época.",
        icon="🔁",
    )
else:
    st.success("Esta linha é **história gravada**, como a fonte publicou na ocasião.", icon="🗄️")

lado_a_lado = pd.DataFrame(
    {
        f"como era em {quando}": antes.set_index("period")["value"],
        "como é hoje": hoje.set_index("period")["value"],
    }
)
st.line_chart(lado_a_lado, height=360)

comum = lado_a_lado.dropna()
temos = not comum.empty
revisoes = (comum.iloc[:, 1] - comum.iloc[:, 0]) if temos else pd.Series(dtype="float64")

# abas, não colunas: ver `app/painel.py` sobre o que colunas fazem numa tela de celular
mudanca, numeros = st.tabs(["Onde mudou", "Em números"])
with mudanca:
    if not temos:
        st.caption("Nenhum período em comum entre as duas leituras.")
    else:
        st.line_chart(revisoes.rename("revisão"), height=240)
with numeros:
    st.dataframe(
        pd.DataFrame(
            # tudo como texto: uma coluna que mistura número e travessão é objeto para o pandas,
            # e o pyarrow recusa convertê-la — a tabela some e o erro fica no terminal
            [
                {"campo": "tipo de vintage", "valor": usada},
                {"campo": "observações então", "valor": f"{len(antes):,}".replace(",", ".")},
                {"campo": "observações hoje", "valor": f"{len(hoje):,}".replace(",", ".")},
                {"campo": "períodos em comum", "valor": f"{len(comum):,}".replace(",", ".")},
                {
                    "campo": "maior revisão",
                    "valor": f"{revisoes.abs().max():.4f}" if temos else "—",
                },
                {
                    "campo": "períodos revisados",
                    "valor": str(int((revisoes.abs() > 1e-9).sum())) if temos else "—",
                },
            ]
        ),
        hide_index=True,
        width="stretch",
    )

st.caption("Leitura por `econbase.api`; esta tela não calcula. Ver ADR-0002 e ADR-0008.")
