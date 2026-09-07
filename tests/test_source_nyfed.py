"""O índice de pressão nas cadeias globais, e o que dá para afirmar sem redistribuí-lo.

A série é `redistributable: false` — os termos do NY Fed não nos deixam republicar os valores — e
esse é o motivo de não haver aqui uma fixture com o dado, como há para o IPCA. Um teste que
gravasse o índice num CSV do repositório violaria a mesma regra que mantém a página de conferência
local, e a regra não vale menos por ser inconveniente.

Então o que este arquivo tranca é o que pode ser trancado sem copiar o dado: a entrada de
catálogo, e o formato exato da planilha publicada — folha nomeada, cinco linhas de cabeçalho,
data no fim do período — reconstruído sinteticamente. Se o NY Fed mudar a forma do arquivo, o
`parse` quebra aqui antes de quebrar numa execução às seis da manhã.

O que **não** pode virar teste, porque exige o dado, fica medido e datado em vez de afirmado:
em 06/09/2026, sobre 344 observações de jan/1998 a ago/2026, o índice tem média **0,0077** e
desvio **1,0013**. Ele é padronizado na origem, e essa é a impressão digital que confirma que a
coluna lida é a certa: nenhuma outra coluna da planilha tem média zero e desvio um. O máximo
histórico é **dezembro de 2021, em 4,431** — o pico da crise de cadeias — e o mínimo é maio de
2023, em -1,591.
"""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import pandas as pd
import pytest

from econbase.catalog import Catalog
from econbase.sources.base import RawResponse
from econbase.sources.file_http import FileHttpSource

ROOT = Path(__file__).resolve().parents[1]
SERIES_ID = "file_http:nyfed_gscpi"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(ROOT / "catalog")


@pytest.fixture(scope="module")
def spec(catalog: Catalog):
    found = catalog.get(SERIES_ID)
    assert found is not None, f"{SERIES_ID} saiu do catálogo"
    return found


# ------------------------------------------------------------------ a entrada de catálogo
def test_o_indice_e_global_e_nao_americano(spec) -> None:
    """Mede pressão em cadeias globais. Catalogá-lo como US seria dizer outra coisa."""
    assert spec.entity_id == "WW"
    assert spec.concept_id == "supply_chain_pressure"
    assert spec.freq == "M"


def test_os_termos_do_ny_fed_estao_declarados(spec) -> None:
    """A flag é o que mantém esta série fora de qualquer página publicada."""
    assert spec.redistributable is False
    assert "NY Fed" in (spec.license or "")


def test_a_planilha_e_lida_no_lugar_certo(spec) -> None:
    """Folha, salto de cabeçalho e convenção de período viajam no catálogo, não no código."""
    params = spec.params or {}
    assert params["sheet"] == "GSCPI Monthly Data"
    assert params["skiprows"] == 5
    assert params["period_is_end"] is True, (
        "a planilha data o fim do mês; sem isto todo período entra deslocado"
    )
    assert params["url"].startswith("https://www.newyorkfed.org/")


def test_o_atraso_de_publicacao_esta_declarado(spec) -> None:
    """Sem ele a série não pode entrar em backtest pseudo-tempo-real."""
    assert spec.expected_lag_days is not None
    assert 0 < spec.expected_lag_days <= 45


# ------------------------------------------------------------------ o formato do arquivo
def workbook(rows: list[tuple[dt.date, float]]) -> bytes:
    """Uma planilha com a forma da publicada: cinco linhas de miolo antes do cabeçalho.

    Valores inventados de propósito. O que se testa é a forma do arquivo, e a forma é pública
    mesmo quando o conteúdo não é.
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        preamble = pd.DataFrame({0: ["Global Supply Chain Pressure Index"] + [""] * 4})
        preamble.to_excel(writer, sheet_name="GSCPI Monthly Data", index=False, header=False)
        frame = pd.DataFrame(rows, columns=["Date", "GSCPI"])
        frame.to_excel(
            writer, sheet_name="GSCPI Monthly Data", index=False, header=False, startrow=5
        )
    return buffer.getvalue()


def test_a_planilha_publicada_e_lida_como_esperado(spec) -> None:
    linhas = [
        (dt.date(2024, 1, 31), -0.25),
        (dt.date(2024, 2, 29), 0.10),
        (dt.date(2024, 3, 31), 0.42),
    ]
    parsed = FileHttpSource().parse(RawResponse(body=workbook(linhas), ext="xlsx"), spec)
    assert len(parsed) == 3
    assert list(parsed["value"]) == [-0.25, 0.10, 0.42]


def test_o_periodo_volta_no_inicio_do_mes_e_nao_no_fim(spec) -> None:
    """O contrato diz que `period` é o início do período; a planilha data o fim.

    É `period_is_end` que faz a tradução, e uma série mensal datada em 31 de janeiro entrando
    como 31 de janeiro cairia fora da grade mensal e seria recusada por `check_frequency`.
    """
    parsed = FileHttpSource().parse(
        RawResponse(body=workbook([(dt.date(2024, 1, 31), 1.0)]), ext="xlsx"), spec
    )
    period = pd.to_datetime(parsed["period"].iloc[0]).date()
    assert period == dt.date(2024, 1, 1), f"o período voltou como {period}"
