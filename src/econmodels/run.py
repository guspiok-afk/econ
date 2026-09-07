"""De uma especificação a um resultado, sem que quem chama precise montar o painel.

Rodar uma especificação exigia três passos e o conhecimento de como encadeá-los: descobrir qual
modelo o `model_id` nomeia, ler em `requires` a frequência que ele espera, pedir o painel dessas
séries à API, e só então ajustar. Cada consumidor que fizesse isso à mão faria a sua versão, e a
primeira delas ia parar dentro de uma tela — que é exatamente onde a ADR-0008 diz que lógica não
mora.

Então mora aqui, uma vez, com teste. A vista chama uma função.

A frequência sai de `model.requires` e não de um argumento, porque quem sabe em que frequência um
modelo estima é o modelo. Passá-la de fora seria deixar a tela decidir se a curva de Phillips é
trimestral, o que ela não tem como saber e não deve adivinhar.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from econmodels.base import Model, Result, RunContext, available
from econmodels.specs import Spec


class RunError(ValueError):
    """A especificação não pode ser executada como pedida."""


def model_for(spec: Spec) -> Model:
    """A instância que a especificação nomeia."""
    registro = available()
    if spec.model_id not in registro:
        conhecidos = ", ".join(sorted(registro)) or "nenhum"
        raise RunError(
            f"{spec.spec_id} nomeia o modelo {spec.model_id!r}, que não está registrado. "
            f"Registrados: {conhecidos}."
        )
    return registro[spec.model_id](spec)


def frequency_of(model: Model) -> str:
    """A frequência em que o modelo estima, lida da própria declaração dele.

    Um modelo que peça frequências diferentes entre os termos não tem uma grade, e montar um
    painel para ele seria escolher uma por conta própria. Recusar é a resposta certa: a escolha
    pertence ao modelo, e o silêncio aqui viraria um deslocamento por linha que não é o que
    parece — o defeito que a guarda de painel existe para impedir.
    """
    declaradas = {r.freq for r in model.requires if r.freq}
    if not declaradas:
        raise RunError(
            f"{type(model).__name__} não declara frequência em `requires`, então não há grade "
            "para montar o painel. Declare `freq` nos ConceptRequest."
        )
    if len(declaradas) > 1:
        raise RunError(
            f"{type(model).__name__} pede mais de uma frequência ({sorted(declaradas)}); "
            "um painel tem uma grade só."
        )
    return declaradas.pop()


def panel_for_spec(
    api,
    spec: Spec,
    *,
    model: Model | None = None,
    asof: dt.date | str | None = None,
    vintage_kind: str = "latest",
    start: str | None = None,
) -> pd.DataFrame:
    """O painel que esta especificação lê, na frequência que o modelo dela estima."""
    model = model or model_for(spec)
    keys = list(spec.concepts())
    if not keys:
        raise RunError(f"{spec.spec_id} não lê nenhuma série")
    return api.get_panel(
        keys,
        freq=frequency_of(model),
        asof=asof,
        vintage_kind=vintage_kind,
        start=start or spec.sample.start,
    )


def run_spec(
    api,
    spec: Spec,
    *,
    asof: dt.date | None = None,
    seed: int = 0,
    vintage_kind: str = "latest",
) -> Result:
    """Monta o painel e ajusta. O caminho inteiro de um arquivo de especificação a um resultado.

    `asof` viaja para os dois lados de propósito: ele corta o painel na data de conhecimento e
    entra no `RunContext`, para que o resultado registre a data com que foi produzido. Um
    resultado que não sabe a sua própria data não pode ser comparado com outro.
    """
    model = model_for(spec)
    panel = panel_for_spec(api, spec, model=model, asof=asof, vintage_kind=vintage_kind)
    ctx = RunContext(
        asof=asof or dt.date.today(),
        seed=seed,
        vintage_kind=vintage_kind,
        params={"spec_id": spec.spec_id, "spec_hash": spec.spec_hash},
    )
    return model.fit(panel, ctx)
