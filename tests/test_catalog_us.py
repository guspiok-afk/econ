"""Acceptance test for WP-02e-us: every field of the United States catalog.

The table below was verified against the live FRED API on 2026-09-04 — each identifier exists,
and each ``vintages`` flag was settled by actually requesting the full real-time period rather
than by reasoning about frequencies. A mismatch here is a typo that would otherwise reach the
store, so the test is deliberately exhaustive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from econbase.catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]

#: native_id -> (concept_id or None, freq, seasonal_adj, expected_lag_days, vintages)
EXPECTED: dict[str, tuple[str | None, str, bool, int, bool]] = {
    "GDPC1": ("gdp_real", "Q", True, 30, True),
    "DGS10": ("govt_yield_10y", "B", False, 1, False),
    "CPIAUCSL": ("cpi_headline_index", "M", True, 12, True),
    "CPILFESL": (None, "M", True, 12, True),
    "PCEPI": (None, "M", True, 28, True),
    "PCEPILFE": (None, "M", True, 28, True),
    "CORESTICKM159SFRBATL": ("cpi_sticky", "M", True, 12, True),
    "COREFLEXCPIM159SFRBATL": ("cpi_flexible", "M", True, 12, True),
    "UNRATE": ("unemployment_rate", "M", True, 5, True),
    "PAYEMS": ("employment", "M", True, 5, True),
    "CIVPART": (None, "M", True, 5, True),
    "ICSA": ("initial_claims", "W", True, 5, True),
    "JTSJOL": (None, "M", True, 38, True),
    "AHETPI": ("wages", "M", True, 5, True),
    "FRBKCLMCILA": ("labor_conditions_index", "M", True, 12, True),
    "FRBKCLMCIM": (None, "M", True, 12, True),
    "FEDFUNDS": ("policy_rate", "M", False, 3, True),
    "SOFR": ("interbank_rate", "D", False, 1, True),
    "DGS2": ("govt_yield_2y", "B", False, 1, False),
    "T10Y2Y": (None, "B", False, 1, False),
    "T5YIE": (None, "B", False, 1, False),
    "INDPRO": ("industrial_production", "M", True, 16, True),
    "TCU": ("capacity_utilization", "M", True, 16, True),
    "RSXFS": ("retail_sales", "M", True, 16, True),
    "HOUST": (None, "M", True, 18, True),
    "UMCSENT": ("consumer_confidence", "M", False, 1, True),
    "GDPNOW": ("gdp_nowcast", "Q", True, 0, True),
    "TOTCI": ("credit_outstanding", "W", True, 8, True),
    "DRCCLACBS": ("credit_delinquency", "Q", True, 60, True),
    "DTWEXBGS": ("fx_effective_index", "D", False, 1, True),
}

#: The four FRED refuses a full real-time period for, with the vintage dates it counted.
TOO_MANY_VINTAGES = {"DGS2": 5103, "DGS10": 5102, "T10Y2Y": 3114, "T5YIE": 3118}


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(ROOT / "catalog")


@pytest.fixture(scope="module")
def us_series(catalog: Catalog) -> dict[str, object]:
    return {s.native_id: s for s in catalog.series.values() if s.source == "fred"}


def test_every_series_of_the_table_is_in_the_catalog(us_series: dict[str, object]) -> None:
    missing = sorted(set(EXPECTED) - set(us_series))
    assert not missing, f"absent from catalog/us/fred.yaml: {missing}"


def test_no_series_was_invented(us_series: dict[str, object]) -> None:
    extra = sorted(set(us_series) - set(EXPECTED))
    assert not extra, f"not in the work package's table: {extra}"


@pytest.mark.parametrize("native_id", sorted(EXPECTED))
def test_each_entry_matches_the_table(native_id: str, us_series: dict[str, object]) -> None:
    spec = us_series.get(native_id)
    assert spec is not None, f"{native_id} is missing"
    concept, freq, sa, lag, vintages = EXPECTED[native_id]
    assert spec.concept_id == concept, f"{native_id}: concept_id"
    assert spec.freq == freq, f"{native_id}: freq"
    assert spec.seasonal_adj is sa, f"{native_id}: seasonal_adj"
    assert spec.expected_lag_days == lag, f"{native_id}: expected_lag_days"
    assert spec.params.get("vintages", True) is vintages, f"{native_id}: params.vintages"
    assert spec.entity_id == "US"
    assert spec.unit, f"{native_id}: unit must not be empty"
    assert spec.source_url == f"https://fred.stlouisfed.org/series/{native_id}"


def test_the_four_daily_series_ask_for_no_vintages(us_series: dict[str, object]) -> None:
    """FRED refuses a real-time period covering more than 2000 vintage dates.

    These four are revised every business day and were counted on 2026-09-04; every other
    series in the table was tested and accepted the full history.
    """
    for native_id, counted in TOO_MANY_VINTAGES.items():
        spec = us_series[native_id]
        assert spec.params.get("vintages") is False, (
            f"{native_id} has {counted} vintage dates, past FRED's limit of 2000, "
            "so it needs params: {vintages: false}"
        )


def test_every_id_was_added_to_the_baseline_list() -> None:
    listed = {
        line.strip()
        for line in (ROOT / "catalog" / "ids.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = sorted(f"fred:{n}" for n in EXPECTED if f"fred:{n}" not in listed)
    assert not missing, f"append these to catalog/ids.txt: {missing}"


def test_a_concept_is_claimed_once_per_country(catalog: Catalog) -> None:
    """Two US series carrying the same concept would make api.get ambiguous."""
    claimed = [c for (e, c) in catalog.concept_map if e == "US"]
    assert len(claimed) == len(set(claimed))
    expected_concepts = {c for c, *_ in EXPECTED.values() if c}
    assert set(claimed) == expected_concepts


def test_the_licence_travels_with_every_series(us_series: dict[str, object]) -> None:
    for native_id, spec in us_series.items():
        assert spec.license, f"{native_id}: licence must be stated"
        assert spec.redistributable is False, (
            f"{native_id}: FRED redistributes other agencies' data under their terms, "
            "so nothing here is marked redistributable"
        )
