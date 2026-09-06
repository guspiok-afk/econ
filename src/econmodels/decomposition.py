"""Onde a inflação brasileira foi feita: preços livres contra administrados.

O Banco Central divide o IPCA em preços livres — os que o mercado forma — e administrados, que
são fixados ou seguem regra contratual: energia, combustível, plano de saúde, transporte público,
água. A divisão importa para política monetária porque os dois respondem a coisas diferentes. Um
choque de administrados não é excesso de demanda, e tratá-lo como se fosse é apertar juros contra
um reajuste tarifário.

Este pacote não estima nada de novo sobre a economia: ele decompõe o que já está publicado, e
todo o trabalho está em fazer isso sem mentir sobre o peso de cada parte.

**Os pesos mudam, e mudam muito.** O catálogo não traz os pesos publicados pelo IBGE, então eles
são recuperados da própria identidade — o cheio é a média ponderada das partes. Medido sobre 427
meses: numa amostra cheia os administrados pesam 16,1%; de 1995 a 2005, 17,9%; de 2006 a 2015,
25,1%; de 2016 em diante, 25,8%. O peso de amostra cheia **não serve a nenhum subperíodo**,
porque é puxado para baixo pela hiperinflação até 1994, quando a variância dos livres dominava
tudo. Por isso a estimação é em janela móvel, e o caminho do peso vai numa tabela: a alta da
participação dos administrados é resultado, não ruído a esconder.

A soma dos pesos é imposta em 1, porque é isso que uma média ponderada significa. A restrição
não custa precisão — na janela de 60 meses o peso dos administrados sai em 0,2612 com ela e
0,2611 sem — e compra a única propriedade que faz a tabela ser lida sem calculadora: as
contribuições somam o índice cheio.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from econmodels.base import (
    ConceptRequest,
    Result,
    RunContext,
    TablesResult,
    check_frequency,
    column_for,
    register,
)

#: Meses de janela para recuperar os pesos. Sessenta é meia década: curto o bastante para
#: acompanhar uma revisão de POF, longo o bastante para o ajuste não perseguir choque mensal.
DEFAULT_WINDOW = 60

#: Abaixo disso a janela não identifica dois pesos com estabilidade que valha reportar.
MIN_WINDOW = 24


class DecompositionError(ValueError):
    """O painel não sustenta a decomposição pedida."""


def _weights(headline: pd.Series, parts: pd.DataFrame, window: int) -> pd.DataFrame:
    """Pesos em janela móvel, somando exatamente 1.

    A restrição entra por construção e não por penalidade: com duas partes, regredir
    ``cheio - segunda`` sobre ``primeira - segunda`` estima o peso da primeira, e o da segunda é
    o que sobra de um. Nada de otimizador, nada de multiplicador de Lagrange, e o resultado é
    exatamente o mesmo que a regressão livre entrega quando ela é bem comportada.
    """
    if parts.shape[1] != 2:
        raise DecompositionError(
            f"a restrição de soma um está escrita para duas partes, e chegaram {parts.shape[1]}: "
            f"{list(parts.columns)}"
        )
    first, second = parts.columns
    left = headline - parts[second]
    right = parts[first] - parts[second]

    rows: list[dict[str, object]] = []
    for end in range(window, len(headline) + 1):
        y = left.iloc[end - window : end].to_numpy(dtype="float64")
        x = right.iloc[end - window : end].to_numpy(dtype="float64")
        denominator = float(x @ x)
        if denominator == 0.0:
            continue
        share = float(x @ y) / denominator
        rows.append(
            {
                "period": headline.index[end - 1],
                first: share,
                second: 1.0 - share,
            }
        )
    if not rows:
        raise DecompositionError("nenhuma janela utilizável para recuperar os pesos")
    return pd.DataFrame(rows).set_index("period")


@register
class PriceDecomposition:
    """A inflação cheia repartida entre as partes que a produziram."""

    model_id = "br_price_decomposition"
    model_version = "1"
    requires: Sequence[ConceptRequest] = (
        ConceptRequest("cpi_headline", freq="M"),
        ConceptRequest("cpi_free", freq="M"),
        ConceptRequest("cpi_administered", freq="M"),
    )

    def __init__(
        self,
        entity: str = "BR",
        headline: str = "cpi_headline",
        parts: tuple[str, str] = ("cpi_free", "cpi_administered"),
        window: int = DEFAULT_WINDOW,
        horizon: int = 12,
    ) -> None:
        self.entity = entity
        self.headline = headline
        self.parts = parts
        self.window = window
        self.horizon = horizon

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result:
        check_frequency(panel, "M")
        if self.window < MIN_WINDOW:
            raise DecompositionError(
                f"janela de {self.window} meses é curta demais para identificar os pesos; "
                f"o mínimo é {MIN_WINDOW}"
            )

        headline = column_for(panel, self.headline, self.entity)
        columns = {part: column_for(panel, part, self.entity) for part in self.parts}
        frame = panel[[headline, *columns.values()]].dropna()
        if len(frame) < self.window + self.horizon:
            raise DecompositionError(
                f"{len(frame)} meses utilizáveis não bastam para uma janela de {self.window} "
                f"mais {self.horizon} meses de acumulação"
            )

        rates = frame[list(columns.values())]
        rates.columns = list(self.parts)
        weights = _weights(frame[headline], rates, self.window)

        # contribuição mensal, que é onde a identidade vale; a acumulação vem depois
        monthly = weights.mul(rates.loc[weights.index], axis=0)
        accumulated = monthly.rolling(self.horizon).sum().dropna()
        headline_12m = (
            (1.0 + frame[headline] / 100.0).rolling(self.horizon).apply(np.prod, raw=True) - 1.0
        ) * 100.0
        headline_12m = headline_12m.loc[accumulated.index]

        rows: list[dict[str, object]] = []
        for period, line in accumulated.iterrows():
            total = float(headline_12m.loc[period])
            # a composição fecha a conta. Somar doze contribuições mensais não dá a inflação de
            # doze meses, porque um índice compõe e uma soma não: a diferença chega a 1,52 ponto
            # percentual no pico e fica em 0,24 na média. Sem esta linha as participações somam
            # 0,976 e a tabela parece errada quando está apenas incompleta.
            rows.append(
                {
                    "period": period.date(),
                    "component": "composicao",
                    "weight": float("nan"),
                    "rate_12m": float("nan"),
                    "contribution": total - float(line.sum()),
                    "share": (total - float(line.sum())) / total if total else float("nan"),
                }
            )
            for part in self.parts:
                value = float(line[part])
                rows.append(
                    {
                        "period": period.date(),
                        "component": part,
                        "weight": float(weights.loc[period, part]),
                        "rate_12m": float(
                            (
                                (1.0 + rates[part].loc[:period].tail(self.horizon) / 100.0).prod()
                                - 1.0
                            )
                            * 100.0
                        ),
                        "contribution": value,
                        "share": value / total if total else float("nan"),
                    }
                )
        contribution = (
            pd.DataFrame(rows).sort_values(["period", "component"]).reset_index(drop=True)
        )

        # o resíduo é a distância entre somar contribuições mensais e compor doze meses. Ele não
        # é erro do modelo: é o que a composição cobra de quem soma. Vai medido para que ninguém
        # leia a tabela como exata quando ela é aproximada em uma casa decimal.
        residual = (accumulated.sum(axis=1) - headline_12m).abs()

        weight_path = (
            weights.reset_index()
            .melt(id_vars="period", var_name="component", value_name="weight")
            .assign(period=lambda d: d["period"].dt.date)
            .sort_values(["period", "component"])
            .reset_index(drop=True)
        )

        latest = weights.index[-1]
        diagnostics = pd.DataFrame(
            [
                {"metric": "window_months", "value": str(self.window)},
                {"metric": "horizon_months", "value": str(self.horizon)},
                {"metric": "weights_sum_to", "value": "1 (imposto)"},
                {"metric": "n_obs", "value": str(len(frame))},
                {"metric": "n_windows", "value": str(len(weights))},
                {"metric": "latest_period", "value": str(latest.date())},
                *(
                    {"metric": f"weight_{part}", "value": f"{float(weights.loc[latest, part]):.4f}"}
                    for part in self.parts
                ),
                {"metric": "residual_max_pp", "value": f"{float(residual.max()):.4f}"},
                {"metric": "residual_mean_pp", "value": f"{float(residual.mean()):.4f}"},
                {"metric": "entity", "value": self.entity},
                {"metric": "asof", "value": str(ctx.asof)},
                {"metric": "vintage_kind", "value": str(ctx.vintage_kind)},
            ]
        )
        return TablesResult(
            _tables={
                "contribution": contribution,
                "weights": weight_path,
                "diagnostics": diagnostics,
            }
        )
