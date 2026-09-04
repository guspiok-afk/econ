"""Acceptance test for WP-02e-br: fourteen more Banco Central series.

Every title below is the name the Banco Central itself publishes, taken from its open data
portal rather than written from memory. That check mattered: seven of the names first assumed
were wrong — 11427 is the exclusion core without administered prices and food at home, not the
double-weighted one; 20717 is free-market lending overall, not corporate; 22707 is the trade
balance, not exports. A wrong title is worse than a missing series, because a future reader
trusts it.

The file is also read as raw text before being parsed, so a stray markdown fence fails here
with a clear message instead of as a YAML scanner error two frames deep.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from econbase.catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / "catalog" / "br" / "bcb_sgs.yaml"

#: native_id -> (concept_id or None, unit, expected_lag_days, official title)
EXPECTED: dict[str, tuple[str | None, str, int, str]] = {
    "4466": (
        "cpi_core",
        "pct",
        12,
        "Índice nacional de preços ao consumidor-Amplo (IPCA) - "
        "Núcleo médias aparadas com suavização",
    ),
    "11427": (
        None,
        "pct",
        12,
        "Índice nacional de preços ao consumidor - Amplo (IPCA) - "
        "Núcleo por exclusão - Sem monitorados e alimentos no domicílio",
    ),
    "16121": (
        None,
        "pct",
        12,
        "Índice nacional de preços ao consumidor - Amplo (IPCA) - Núcleo por exclusão - ex2",
    ),
    "24364": (
        None,
        "index",
        45,
        "Índice de Atividade Econômica do Banco Central (IBC-Br) - com ajuste sazonal",
    ),
    "4513": (
        None,
        "pct of GDP",
        30,
        "Dívida Líquida do Setor Público (% PIB) - Total - Setor público consolidado",
    ),
    "20541": (None, "BRL million", 30, "Saldo da carteira de crédito - Pessoas físicas - Total"),
    "20542": (None, "BRL million", 30, "Saldo da carteira de crédito com recursos livres - Total"),
    "20716": (
        None,
        "pct per year",
        30,
        "Taxa média de juros das operações de crédito - Pessoas físicas - Total",
    ),
    "20717": (
        None,
        "pct per year",
        30,
        "Taxa média de juros das operações de crédito com recursos livres - Total",
    ),
    "21084": (
        None,
        "pct",
        30,
        "Inadimplência da carteira de crédito - Pessoas físicas - Total",
    ),
    "21085": (
        None,
        "pct",
        30,
        "Inadimplência da carteira de crédito com recursos livres - Total",
    ),
    "22707": (
        "trade_balance",
        "USD million",
        25,
        "Balança comercial - Balanço de Pagamentos - mensal - saldo",
    ),
    "22708": (None, "USD million", 25, "Exportação de bens - Balanço de Pagamentos - mensal"),
    "22701": (None, "USD million", 25, "Transações correntes - mensal - saldo"),
}


def test_the_file_holds_yaml_and_nothing_else() -> None:
    """A markdown fence written into the file breaks the parser three frames deep."""
    text = YAML.read_text(encoding="utf-8")
    assert "```" not in text, (
        "there is a markdown code fence in the YAML: paste the entries, not the block around them"
    )
    assert not text.lstrip().startswith("#!"), "unexpected header line"


@pytest.fixture(scope="module")
def sgs() -> dict[str, object]:
    catalog = Catalog.load(ROOT / "catalog")
    return {s.native_id: s for s in catalog.series.values() if s.source == "bcb_sgs"}


def test_every_series_of_the_table_is_present(sgs: dict[str, object]) -> None:
    missing = sorted(set(EXPECTED) - set(sgs))
    assert not missing, f"absent from catalog/br/bcb_sgs.yaml: {missing}"


@pytest.mark.parametrize("native_id", sorted(EXPECTED))
def test_each_entry_matches_the_table(native_id: str, sgs: dict[str, object]) -> None:
    spec = sgs.get(native_id)
    assert spec is not None, f"{native_id} is missing"
    concept, unit, lag, title = EXPECTED[native_id]
    assert spec.title == title, (
        f"{native_id}: the title must be the name the Banco Central publishes, verbatim"
    )
    assert spec.concept_id == concept, f"{native_id}: concept_id"
    assert spec.unit == unit, f"{native_id}: unit"
    assert spec.expected_lag_days == lag, f"{native_id}: expected_lag_days"
    assert spec.freq == "M", f"{native_id}: every series here is monthly"
    assert spec.entity_id == "BR"
    assert spec.seasonal_adj is (native_id == "24364"), (
        f"{native_id}: only the IBC-Br entry is seasonally adjusted"
    )


def test_every_id_reached_the_baseline_list() -> None:
    """The second file of the task; it has been forgotten before."""
    listed = {
        line.strip()
        for line in (ROOT / "catalog" / "ids.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = sorted(f"bcb_sgs:{n}" for n in EXPECTED if f"bcb_sgs:{n}" not in listed)
    assert not missing, f"append these to catalog/ids.txt: {missing}"


def test_the_existing_entries_were_not_disturbed(sgs: dict[str, object]) -> None:
    """The package adds; it does not touch what was already there."""
    for native_id, concept in (
        ("433", "cpi_headline"),
        ("432", "policy_rate"),
        ("1", "fx_spot_usd"),
    ):
        assert sgs[native_id].concept_id == concept, f"{native_id} was changed"


def test_a_concept_is_claimed_once(sgs: dict[str, object]) -> None:
    claimed = [s.concept_id for s in sgs.values() if s.concept_id]
    assert len(claimed) == len(set(claimed)), "two Brazilian series carry the same concept"
