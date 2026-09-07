"""A porta da vista.

O problema que isto resolve não é a porta de rede: é que o Streamlit não tem autenticação, e sem
ela servir o painel fora da máquina significa abrir o painel inteiro a quem estiver na rede —
incluindo as trinta e três séries cuja licença proíbe republicação. Abrir buraco no firewall sem
resolver isso seria trocar um problema por um pior.

Com senha, a decisão volta a ser do dono: ele escolhe quem entra, e o endereço deixar de ser
segredo deixa de importar.

**O padrão é aberto, de propósito.** Sem `ECONBASE_APP_PASSWORD` no `.env` a vista roda como
sempre rodou, porque uma senha obrigatória para uso local nesta máquina seria cerimônia sem
ganho — e cerimônia sem ganho é o que ensina alguém a contornar a segurança. O que a vista faz é
**dizer em que modo está**, para que servir na rede sem senha seja uma escolha e não um descuido.

Comparação em tempo constante porque é barata e porque comparar segredo com `==` é o tipo de
detalhe que ninguém revisa depois.
"""

from __future__ import annotations

import hmac

import streamlit as st

from econbase.settings import get_settings

CHAVE = "econ_acesso_liberado"


def senha_configurada() -> str | None:
    """A senha do `.env`, ou ``None`` quando a vista está aberta."""
    valor = get_settings().econbase_app_password
    return valor or None


def confere(tentativa: str, esperada: str) -> bool:
    """Comparação em tempo constante, para o tempo de resposta não vazar o prefixo certo."""
    return hmac.compare_digest(tentativa.encode("utf-8"), esperada.encode("utf-8"))


def exigir_senha() -> None:
    """Bloqueia a página até a senha certa, ou passa direto se não houver senha configurada.

    Chamada no topo de cada página. O estado vive em `st.session_state`, que é por sessão do
    navegador e compartilhado entre as páginas: entrar uma vez basta, e fechar a aba encerra.
    """
    esperada = senha_configurada()
    if esperada is None:
        st.session_state[CHAVE] = True
        return
    if st.session_state.get(CHAVE):
        return

    st.title("Base econômica")
    st.caption("Esta vista está protegida por senha.")
    with st.form("acesso"):
        tentativa = st.text_input("Senha", type="password")
        enviou = st.form_submit_button("Entrar")
    if enviou:
        if confere(tentativa, esperada):
            st.session_state[CHAVE] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()


def aviso_de_modo_aberto() -> None:
    """Diz na barra lateral que a vista está sem senha.

    Não é decoração. Quem serve o painel na rede precisa ver, na própria tela, que ele está
    aberto — a alternativa é descobrir pelo visitante.
    """
    if senha_configurada() is None:
        st.sidebar.caption(
            "🔓 Sem senha. Serve para uso local. Antes de servir na rede, preencha "
            "`ECONBASE_APP_PASSWORD` no `.env`."
        )
