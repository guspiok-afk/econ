"""O boletim é publicado, e por isso a licença deixa de ser rótulo e vira portão.

Servir o painel na rede é usar o dado; publicar uma página é republicá-lo. Trinta e três das
setenta e três séries do catálogo — todas do FRED e do NY Fed — permitem a primeira coisa e não a
segunda. Então esta página é brasileira por obrigação, e a obrigação é verificada em vez de
lembrada: `_conferir_licenca` recusa a geração se qualquer série restrita entrar na lista.

O teste que importa aqui é o que tenta furar essa regra de propósito.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "render_boletim.py"


def _carregar():
    spec = importlib.util.spec_from_file_location("render_boletim", SCRIPT)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["render_boletim"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def boletim():
    return _carregar()


@pytest.fixture(scope="module")
def api():
    econbase_api = pytest.importorskip("econbase.api")
    try:
        conexao = econbase_api.connect()
        conexao.series()
    except Exception as erro:  # pragma: no cover - máquina sem base coletada
        pytest.skip(f"sem store local: {erro}")
    return conexao


@pytest.fixture(scope="module")
def pagina(boletim, api) -> str:
    return boletim.render(api, dt.datetime(2026, 9, 6, 23, 0))


# ------------------------------------------------------------------ a licença é um portão
def test_toda_serie_do_boletim_pode_ser_republicada(boletim, api) -> None:
    for bloco in boletim.BLOCOS.values():
        for ind in bloco:
            ficha = api.describe(ind.conceito, "BR")
            assert ficha["redistributable"], (
                f"{ind.rotulo} usa {ficha['series_id']}, que não pode ser republicada "
                f"({ficha['license']})"
            )


def test_uma_serie_restrita_faz_a_geracao_recusar(boletim, api) -> None:
    """A tentativa deliberada de furar a regra.

    Sem isto a checagem seria decorativa: passaria sempre, porque a lista atual é brasileira, e
    ninguém saberia se ela de fato morde no dia em que alguém acrescentar uma série do FRED.
    """
    # a lista de hoje passa, e passar é o estado normal
    boletim._conferir_licenca(api, ["gdp_real", "policy_rate"])

    # a mesma guarda apontada para os Estados Unidos, onde toda série é restrita, tem de morder
    with pytest.raises(boletim.LicencaViolada, match="republicadas"):
        boletim._conferir_licenca(api, ["gdp_real"], entidade="US")


def test_a_pagina_diz_por_que_e_so_brasileira(pagina: str) -> None:
    assert "não republicação" in pagina or "republicação" in pagina
    assert "FRED" in pagina


# ------------------------------------------------------------------ o que a página mostra
def test_a_pagina_tem_um_cartao_por_indicador(pagina: str, boletim) -> None:
    esperados = sum(len(bloco) for bloco in boletim.BLOCOS.values())
    assert len(re.findall(r'class="cartao"', pagina)) == esperados


def test_cada_cartao_traz_valor_unidade_e_data(pagina: str) -> None:
    for classe in ("valor", "unidade", "quando", "faisca"):
        assert f'class="{classe}"' in pagina


def test_o_carimbo_de_data_esta_visivel(pagina: str) -> None:
    """A página é um retrato e envelhece. Quem a abre precisa ver quando ela foi tirada."""
    assert "06/09/2026" in pagina
    assert 'class="carimbo"' in pagina


def test_a_ausencia_do_pib_e_explicada(pagina: str) -> None:
    """Ausência explicada é melhor que presença enganosa: a série do PIB do catálogo se declara
    dessazonalizada e não é, então publicá-la seria publicar o calendário."""
    assert "PIB não aparece" in pagina
    assert "C1" in pagina


# ------------------------------------------------------------------ a faísca
def test_a_faisca_e_svg_sem_nada_a_carregar(boletim) -> None:
    """Uma página que depende de biblioteca externa não abre no celular sem rede boa — e a
    política de conteúdo do hospedeiro bloqueia quase tudo de qualquer forma."""
    svg = boletim._faisca([1.0, 2.0, 1.5, 3.0])
    assert svg.startswith("<svg") and "polyline" in svg
    assert "http" not in svg and "<script" not in svg


def test_uma_serie_de_um_ponto_nao_desenha_faisca(boletim) -> None:
    assert boletim._faisca([1.0]) == ""


def test_a_faisca_cabe_na_propria_caixa(boletim) -> None:
    """Coordenada fora da viewBox some sem erro: o traço aparece cortado e ninguém percebe."""
    svg = boletim._faisca([0.0, 100.0, 50.0], largura=240, altura=44)
    pontos = re.search(r'points="([^"]+)"', svg).group(1)
    for par in pontos.split():
        x, y = (float(v) for v in par.split(","))
        assert 0 <= x <= 240
        assert 0 <= y <= 44


# ------------------------------------------------------------------ a cópia publicada
def test_a_versao_de_artifact_nao_traz_esqueleto_de_documento(boletim, api) -> None:
    fragmento = boletim.render(api, dt.datetime(2026, 9, 6, 23, 0), artifact=True)
    for etiqueta in ("<!doctype", "<html", "<head>", "<body"):
        assert etiqueta not in fragmento.lower()
    assert fragmento.startswith("<title>")


def test_as_duas_versoes_mostram_os_mesmos_numeros(boletim, api, pagina: str) -> None:
    fragmento = boletim.render(api, dt.datetime(2026, 9, 6, 23, 0), artifact=True)
    valores = lambda html: re.findall(r'class="valor">([^<]+)<', html)  # noqa: E731
    assert valores(pagina) == valores(fragmento)
