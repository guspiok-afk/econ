"""A vista. Ela desenha e não calcula.

ADR-0008: o aplicativo é fino de propósito. Toda leitura passa por `econbase.api` e toda
estimação por um modelo registrado em `econmodels`. Se um cálculo aparecer aqui, está no lugar
errado — vira função com teste do outro lado, e esta tela volta a só chamar.

A regra tem uma razão prática: o Streamlit é o caminho mais curto até uso próprio e uma base ruim
para produto, porque reexecuta o script inteiro a cada interação e não foi feito para multiusuário.
Mantendo a vista fina, trocá-la é reescrever a vista e não o sistema.

**A restrição que atravessa todas as telas:** trinta e três das setenta e três séries são
`redistributable: false` — o FRED e o NY Fed permitem uso e não republicação. Para uso próprio
isso é indiferente, porque quem olha é quem coletou. No dia em que houver um segundo par de olhos
não é, e descobrir isso depois de construídas as telas é caro. Por isso o interruptor de
redistribuição existe desde a primeira, e por isso ele mostra o que está escondendo em vez de
esconder em silêncio.

Rodar:  uv run --extra app --extra models streamlit run app/painel.py --server.port 8502
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

# A pasta do aplicativo não entra no `sys.path` quando o Streamlit executa uma página —
# medido, não suposto — então a porta de entrada precisa ser alcançável assim, antes de
# qualquer outro import do próprio aplicativo.
sys.path.insert(0, str(_Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st
from acesso import aviso_de_modo_aberto, exigir_senha

from econbase.api import connect

st.set_page_config(page_title="Base econômica", page_icon="📊", layout="wide")

exigir_senha()


@st.cache_resource
def api():
    """Uma conexão por processo. O store é imutável entre execuções do agendador."""
    return connect()


@st.cache_data(ttl=600)
def catalogo() -> pd.DataFrame:
    frame = api().series().to_pandas()
    return frame.sort_values(["entity_id", "concept_id"]).reset_index(drop=True)


@st.cache_data(ttl=600)
def serie(concept: str, entity: str, freq: str | None, transform: str | None) -> pd.DataFrame:
    return api().get(concept, entity=entity, freq=freq or None, transform=transform or None)


def ficha(concept: str, entity: str) -> dict:
    return api().describe(concept, entity)


# ------------------------------------------------------------------ barra lateral
st.sidebar.title("Base econômica")
aviso_de_modo_aberto()

todas = catalogo()
restritas = int((~todas["redistributable"]).sum())

apenas_livres = st.sidebar.toggle(
    "Só o que pode sair daqui",
    value=False,
    help=(
        "Esconde as séries cuja licença proíbe republicação. Para uso próprio não muda nada; "
        "é o modo a usar antes de mostrar uma tela a outra pessoa."
    ),
)
visiveis = todas[todas["redistributable"]] if apenas_livres else todas

if apenas_livres:
    st.sidebar.caption(f"Escondendo {restritas} de {len(todas)} séries por licença.")
else:
    st.sidebar.caption(
        f"{restritas} das {len(todas)} séries não podem ser republicadas. "
        "Ligue o interruptor antes de mostrar isto a alguém."
    )

paises = sorted(visiveis["entity_id"].unique())
if not paises:
    st.error("Nenhuma série visível com o filtro atual.")
    st.stop()

entidade = st.sidebar.selectbox(
    "Entidade", paises, index=paises.index("BR") if "BR" in paises else 0
)
do_pais = visiveis[visiveis["entity_id"] == entidade]
conceitos = sorted(do_pais["concept_id"].dropna().unique())
if not conceitos:
    st.error(f"Nenhuma série de {entidade} visível com o filtro atual.")
    st.stop()

conceito = st.sidebar.selectbox("Conceito", conceitos)

st.sidebar.divider()
frequencia = st.sidebar.selectbox(
    "Frequência", ["nativa", "M", "Q", "A"], help="Converter exige agregação declarada no conceito."
)
transformacao = st.sidebar.selectbox(
    "Transformação", ["nenhuma", "yoy", "mom", "log_diff"], help="Aplicada depois da conversão."
)

# ------------------------------------------------------------------ o corpo
info = ficha(conceito, entidade)
st.title(info["title"] or f"{conceito}@{entidade}")

# Uma linha que quebra sozinha, em vez de três colunas que se espremem. No Streamlit as colunas
# NÃO empilham em tela estreita: num celular viram três tiras ilegíveis lado a lado.
st.caption(
    f"`{info['series_id']}` · {info['source']} · {info['unit'] or '—'} · "
    f"frequência {info['freq']} · "
    + ("dessazonalizada" if info["seasonal_adj"] else "sem ajuste sazonal")
    + f" · defasagem de {info['expected_lag_days']} dias"
)

if not info["redistributable"]:
    st.warning(
        f"**{info['license']}**: esta série pode ser usada e não republicada. "
        "Não a mostre fora desta máquina.",
        icon="⚠️",
    )

try:
    dados = serie(
        conceito,
        entidade,
        None if frequencia == "nativa" else frequencia,
        None if transformacao == "nenhuma" else transformacao,
    )
except Exception as erro:  # a API recusa o que não sabe fazer, e a recusa é informação
    st.error(str(erro))
    st.stop()

if dados.empty:
    st.info("A série não devolveu observações com estes parâmetros.")
    st.stop()

grafico = dados.set_index("period")["value"]
st.line_chart(grafico, height=380)

# Abas em vez de colunas: elas ocupam a largura toda em qualquer tela, e no celular a segunda
# fica a um toque em vez de espremida ao lado da primeira.
recentes, cobertura = st.tabs(["Últimas observações", "Cobertura"])
with recentes:
    st.dataframe(dados.tail(12).iloc[::-1], hide_index=True, width="stretch")
with cobertura:
    st.dataframe(
        pd.DataFrame(
            [
                {"campo": "observações", "valor": f"{len(dados):,}".replace(",", ".")},
                {"campo": "primeira", "valor": str(dados["period"].min())},
                {"campo": "última", "valor": str(dados["period"].max())},
                {"campo": "atualizada em", "valor": str(info["last_updated"])[:19]},
                {"campo": "licença", "valor": info["license"] or "—"},
                {"campo": "fonte", "valor": info["source_url"] or "—"},
            ]
        ),
        hide_index=True,
        width="stretch",
    )

st.caption(
    "Os números vêm de `econbase.api`; esta tela não calcula nada. "
    "Ver ADR-0008 para por que ela é fina."
)
