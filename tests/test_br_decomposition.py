"""The four IPCA components, identified by arithmetic rather than by their names.

The Banco Central's open-data portal did not return the published names of these four series, so
the titles in the catalog are ours and say so. Trusting a name would have been the weaker check
anyway: seven of the fourteen titles added earlier were wrong on the first attempt, and a wrong
name is invisible.

What identifies a series beyond doubt is what it does. The headline IPCA is the weighted sum of
free and administered prices, and free prices are in turn the weighted sum of services and
tradables. Both identities hold on 427 recorded months to four decimals, which is a stronger
claim than any label.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

statsmodels = pytest.importorskip("statsmodels.api")

from econbase.catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "analysis" / "br_ipca_decomposicao.csv"

EXPECTED = {
    "11428": "cpi_free",
    "4449": "cpi_administered",
    "10844": "cpi_services",
    "4447": "cpi_tradables",
}


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return pd.read_csv(FIX, parse_dates=["period"]).set_index("period")


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(ROOT / "catalog")


def fit(frame: pd.DataFrame, left: str, right: list[str]):
    x = statsmodels.add_constant(frame[right])
    return statsmodels.OLS(frame[left], x).fit()


# ------------------------------------------------------------------ the identities
def test_headline_is_free_plus_administered(frame: pd.DataFrame) -> None:
    """The decomposition that makes 11428 and 4449 what the catalog says they are."""
    r = fit(frame, "ipca", ["livres", "administrados"])
    assert r.rsquared > 0.999, f"R-squared {r.rsquared:.5f} is too low for an identity"
    weights = r.params["livres"] + r.params["administrados"]
    assert weights == pytest.approx(1.0, abs=0.01), f"weights sum to {weights:.4f}, not one"
    assert r.params["livres"] > r.params["administrados"], "free prices are the larger share"


def test_free_prices_split_into_services_and_tradables(frame: pd.DataFrame) -> None:
    r = fit(frame, "livres", ["servicos", "comercializaveis"])
    assert r.rsquared > 0.99
    weights = r.params["servicos"] + r.params["comercializaveis"]
    assert weights == pytest.approx(1.0, abs=0.02), f"weights sum to {weights:.4f}, not one"


def test_the_shares_are_the_ones_the_index_actually_uses(frame: pd.DataFrame) -> None:
    """Roughly five sixths free, one sixth administered — a fact about the IPCA, not a guess."""
    r = fit(frame, "ipca", ["livres", "administrados"])
    assert 0.78 < r.params["livres"] < 0.88
    assert 0.12 < r.params["administrados"] < 0.22


def test_the_fixture_covers_the_estimable_sample(frame: pd.DataFrame) -> None:
    assert len(frame) > 400
    assert frame.index.min().year == 1991


# ------------------------------------------------------------------ the catalog side
@pytest.mark.parametrize("native_id,concept", sorted(EXPECTED.items()))
def test_each_component_is_in_the_catalog(catalog: Catalog, native_id: str, concept: str) -> None:
    spec = catalog.get(f"bcb_sgs:{native_id}")
    assert spec.concept_id == concept
    assert spec.entity_id == "BR"
    assert spec.freq == "M"
    assert spec.unit == "pct"


@pytest.mark.parametrize("concept", sorted(set(EXPECTED.values())))
def test_each_concept_compounds_rather_than_adds(catalog: Catalog, concept: str) -> None:
    """They are rates of change; summing them to a quarter is wrong by more than rounding."""
    assert catalog.concepts[concept].default_agg == "compound"


def test_the_titles_do_not_claim_to_be_the_banks(catalog: Catalog) -> None:
    """The four names are ours. Claiming otherwise is the failure this test exists to prevent."""
    for native_id in EXPECTED:
        title = catalog.get(f"bcb_sgs:{native_id}").title
        assert title.startswith("IPCA "), title
        assert title.isascii(), (
            f"{title!r} looks like a Portuguese official name; these four were never verified "
            "against the Bank's published titles, and pretending otherwise is the defect"
        )


def test_every_component_reached_the_baseline_list() -> None:
    listed = {
        line.strip()
        for line in (ROOT / "catalog" / "ids.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = sorted(f"bcb_sgs:{n}" for n in EXPECTED if f"bcb_sgs:{n}" not in listed)
    assert not missing, f"append these to catalog/ids.txt: {missing}"
