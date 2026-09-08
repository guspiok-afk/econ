"""O fator dinâmico contra um modelo de fundação que não sabe nada de economia.

O WP-05a mediu o fator dinâmico contra a **média incondicional** do crescimento, e o resultado foi
desconfortável: ele ganha na amostra cheia — 0,818 contra 2,065 — e **perde nos anos calmos**,
0,501 contra 0,423. Média incondicional é um adversário fraco, e o pacote nunca respondeu a
pergunta que importa: o painel de frequência mista paga a própria complexidade?

Este arranjo responde. O Chronos é univariado: ele vê a história do crescimento trimestral do PIB
e mais nada — nem emprego, nem produção industrial, nem varejo. O fator dinâmico vê tudo isso e
ainda trata a ponta irregular. Se os dois empatarem, o painel não está comprando nada, e isso é
resultado.

**A comparação é justa por construção.** Os três competidores recebem exatamente a mesma janela:
o painel cortado na mesma data de conhecimento, com o PIB do trimestre corrente escondido pela
defasagem de publicação. É o mesmo `visible_through` que o backtest do WP-05a usa, e foi ele que
consertou o vazamento em que a versão anterior entregava ao modelo o trimestre que ele dizia
estimar.

Os pesos ficam fora do repositório, em `%LOCALAPPDATA%\\econbase\\models`, pela mesma razão que os
dados ficam: peso de modelo não é código e não entra no git.

Uso, em ambiente EFÊMERO — torch e as dezoito dependências dele não entram no ambiente que o
agendador usa duas vezes por dia:

    uv run --with torch --with chronos-forecasting python tools/bench_nowcast.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
PESOS_PADRAO = Path(os.environ.get("LOCALAPPDATA", ".")) / "econbase" / "models"

#: Mês do trimestre em que se pergunta. Dois é meio de trimestre, o mesmo corte do WP-05a.
DESLOCAMENTO = 2
FIXTURE = ROOT / "tests" / "fixtures" / "analysis" / "us_monthly_dfm.csv"
#: Dias após o fim do trimestre até a primeira estimativa do PIB existir.
ATRASO_PIB = 30


def painel_completo() -> pd.DataFrame:
    bruto = pd.read_csv(FIXTURE, parse_dates=["period"]).set_index("period")
    return bruto.add_suffix("@US")


def visivel_ate(mes: str) -> pd.DataFrame:
    """O painel como estava no fim de ``mes``, com o alvo ainda não publicado escondido.

    Cortar linhas não basta e é a armadilha que este projeto já pisou: uma série trimestral fica
    na grade no mês em que o trimestre COMEÇA, então truncar em março de 2018 mantém um número
    que o Bureau só publica no fim de abril.
    """
    painel = painel_completo().loc[:mes].copy()
    asof = pd.Timestamp(mes) + pd.offsets.MonthEnd(0)
    fim_do_trimestre = pd.PeriodIndex(painel.index, freq="Q").to_timestamp(how="end").normalize()
    publicado = fim_do_trimestre + pd.Timedelta(days=ATRASO_PIB)
    painel.loc[publicado > asof, "gdp_real@US"] = np.nan
    return painel


def crescimento(painel: pd.DataFrame) -> pd.Series:
    """Crescimento trimestral do PIB, em por cento, indexado por trimestre."""
    nivel = painel["gdp_real@US"].dropna()
    taxa = (100.0 * np.log(nivel).diff()).dropna()
    taxa.index = pd.PeriodIndex(taxa.index, freq="Q")
    return taxa


#: sha256 de `model.safetensors` de amazon/chronos-bolt-tiny, conferido contra o que o Hub
#: publica em 07/09/2026. Conferir uma vez à mão não vale nada: o arquivo mora fora do
#: repositório, num diretório gravável, e ninguém repete a conferência antes de cada execução.
#: Aqui ela é repetida por construção.
SHA_CHRONOS_BOLT_TINY = "75068728d376d2bec670379eeef4bfb4d24c0cfe24d957451f8d19b447030a32"


def conferir_pesos(arquivo: Path, esperado: str) -> str:
    """O sha256 do arquivo, recusando se não for o esperado.

    Isto NÃO protege contra tudo. O hash de referência foi obtido pelo mesmo canal TLS que o
    antivírus desta máquina intercepta, então ele guarda contra corrupção e contra um CDN
    adulterado, e não contra o próprio interceptador. É a garantia que se pode dar, dita pelo
    tamanho que tem.
    """
    import hashlib

    digestor = hashlib.sha256()
    with arquivo.open("rb") as fluxo:
        for bloco in iter(lambda: fluxo.read(1 << 20), b""):
            digestor.update(bloco)
    obtido = digestor.hexdigest()
    if obtido != esperado:
        raise RuntimeError(
            f"{arquivo.name} nao e o arquivo esperado. "
            f"esperado {esperado}, obtido {obtido}. "
            "Apague o diretorio e baixe de novo antes de rodar qualquer coisa."
        )
    return obtido


def carregar_chronos(caminho: Path, esperado: str = SHA_CHRONOS_BOLT_TINY):
    """Carrega os pesos depois de conferi-los.

    `safetensors` é o formato que existe para NÃO executar código ao ser lido, ao contrário do
    pickle dos modelos antigos, e `trust_remote_code` fica no padrão desligado — nenhum código do
    repositório do modelo roda aqui. O risco real deste arranjo nunca foram os pesos: são as
    bibliotecas, e é por isso que elas rodam em ambiente efêmero.
    """
    import torch
    from chronos import BaseChronosPipeline

    conferir_pesos(caminho / "model.safetensors", esperado)
    return BaseChronosPipeline.from_pretrained(
        str(caminho), device_map="cpu", torch_dtype=torch.float32, trust_remote_code=False
    )


def prever_chronos(tubo, historia: pd.Series) -> float:
    import torch

    contexto = torch.tensor(historia.to_numpy(dtype="float32"))
    _, media = tubo.predict_quantiles(contexto, prediction_length=1, quantile_levels=[0.5])
    return float(media[0, 0])


def prever_dfm(painel: pd.DataFrame, trimestre: pd.Period, quando: dt.date) -> float:
    from econmodels.base import RunContext
    from econmodels.dfm import DynamicFactorNowcast

    resultado = DynamicFactorNowcast(entity="US", sample_start="1992-02-01").fit(
        painel, RunContext(asof=quando, vintage_kind="mixed")
    )
    tabela = resultado.tables()["nowcast"].set_index("quarter")
    return float(tabela.loc[str(trimestre), "value"])


def rodar(tubo, inicio: str = "2018Q1", fim: str = "2025Q4") -> pd.DataFrame:
    verdade = crescimento(painel_completo())
    linhas: list[dict[str, object]] = []
    for trimestre in pd.period_range(inicio, fim, freq="Q"):
        if trimestre not in verdade.index:
            continue
        corte = str(trimestre.asfreq("M", "start") + DESLOCAMENTO)
        painel = visivel_ate(corte)
        historia = crescimento(painel)
        if len(historia) < 24:
            continue
        linhas.append(
            {
                "trimestre": str(trimestre),
                "realizado": float(verdade[trimestre]),
                "dfm": prever_dfm(painel, trimestre, pd.Timestamp(corte).date()),
                "chronos": prever_chronos(tubo, historia),
                "media": float(historia.mean()),
                "passeio": float(historia.iloc[-1]),
                "n_historia": len(historia),
            }
        )
        print(f"  {linhas[-1]['trimestre']}  realizado {linhas[-1]['realizado']:+.3f}")
    return pd.DataFrame(linhas)


def erro(quadro: pd.DataFrame, coluna: str) -> float:
    return float(np.sqrt(np.mean((quadro[coluna] - quadro["realizado"]) ** 2)))


def relatar(quadro: pd.DataFrame) -> str:
    competidores = ["dfm", "chronos", "media", "passeio"]
    cortes = {
        "2018-2025 completo": quadro,
        "sem 2020": quadro[~quadro["trimestre"].str.startswith("2020")],
        "2022-2025 (calmo)": quadro[quadro["trimestre"] >= "2022"],
    }
    largura = max(len(k) for k in cortes) + 2
    linhas = [
        f"{'recorte':<{largura}}{'n':>4}" + "".join(f"{c:>10}" for c in competidores),
        "-" * (largura + 4 + 10 * len(competidores)),
    ]
    for nome, corte in cortes.items():
        if corte.empty:
            continue
        valores = {c: erro(corte, c) for c in competidores}
        melhor = min(valores, key=valores.get)
        linhas.append(
            f"{nome:<{largura}}{len(corte):>4}"
            + "".join(f"{valores[c]:>9.3f}" + ("*" if c == melhor else " ") for c in competidores)
        )
    linhas.append("")
    linhas.append("* menor erro quadrático médio do recorte. Chronos é univariado: vê só a")
    linhas.append("  história do próprio PIB, sem nenhum dos indicadores mensais.")
    return "\n".join(linhas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", default=str(PESOS_PADRAO / "chronos-bolt-tiny"))
    parser.add_argument("--saida", default=str(ROOT / "reports" / "bench_nowcast.csv"))
    args = parser.parse_args()

    caminho = Path(args.modelo)
    if not (caminho / "config.json").exists():
        print(f"pesos não encontrados em {caminho}")
        print("baixe config.json e model.safetensors de huggingface.co/amazon/chronos-bolt-tiny")
        return 1

    print(f"carregando {caminho.name}…")
    tubo = carregar_chronos(caminho)
    print("rodando o backtest:")
    quadro = rodar(tubo)
    if quadro.empty:
        print("nenhum trimestre utilizável")
        return 1

    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    quadro.to_csv(saida, index=False)
    print()
    print(relatar(quadro))
    print()
    print(f"detalhe por trimestre: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
