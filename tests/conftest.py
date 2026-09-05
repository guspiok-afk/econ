"""Shared fixtures: temp data dir, temp catalog, static connector, leakage guard."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

import httpx
import pandas as pd
import pyarrow as pa
import pytest
import respx

from econbase import pipeline
from econbase.api import Api
from econbase.catalog import Catalog
from econbase.settings import Settings, get_settings
from econbase.sources.base import StaticSource
from econbase.sources.fred import ENDPOINT, FredSource
from econbase.sources.http import Client
from econbase.store import Store

UTC = dt.UTC

CONCEPTS_YAML = """\
concepts:
  cpi_headline: {description: CPI monthly change, unit_kind: pct, default_agg: sum}
  policy_rate: {description: Policy rate, unit_kind: pct_pa, default_agg: eop}
  gdp_real: {description: Real GDP, unit_kind: level, default_agg: sum}
"""

ENTITIES_YAML = """\
entities:
  - {entity_id: BR, entity_type: country, name: Brazil, attributes: {currency: BRL}}
  - {entity_id: US, entity_type: country, name: United States}
"""

STATIC_YAML = """\
source: static
defaults: {entity_id: BR, license: CC0, redistributable: true, freq: M, expected_lag_days: 12}
series:
  - native_id: ipca
    concept_id: cpi_headline
    title: IPCA monthly change
    unit: pct
  - native_id: selic
    concept_id: policy_rate
    title: Selic target
    unit: pct_pa
    freq: D
    expected_lag_days: 1
    aliases: [static:selic_old]
  - native_id: gdp_us
    entity_id: US
    concept_id: gdp_real
    title: US real GDP
    freq: Q
    expected_lag_days: 30
"""


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("ECONBASE_DATA_DIR", str(d))
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    # tests must not read the maintainer's real .env from the repository root
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield d
    get_settings.cache_clear()


@pytest.fixture
def store(data_dir: Path) -> Store:
    return Store(data_dir)


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    (root / "br").mkdir(parents=True)
    (root / "concepts.yaml").write_text(CONCEPTS_YAML, encoding="utf-8")
    (root / "entities.yaml").write_text(ENTITIES_YAML, encoding="utf-8")
    (root / "br" / "static.yaml").write_text(STATIC_YAML, encoding="utf-8")
    return root


@pytest.fixture
def catalog(catalog_root: Path) -> Catalog:
    return Catalog.load(catalog_root)


def frame(*pairs: tuple[str, float | None]) -> pd.DataFrame:
    """Build a ``period, value`` frame from ISO date strings."""
    return pd.DataFrame(
        {
            "period": [dt.date.fromisoformat(p) for p, _ in pairs],
            "value": [v for _, v in pairs],
        }
    )


def vframe(*rows: tuple[str, float, str, str | None]) -> pd.DataFrame:
    """Build a vintaged frame: (period, value, realtime_start, realtime_end)."""
    return pd.DataFrame(
        {
            "period": [dt.date.fromisoformat(r[0]) for r in rows],
            "value": [r[1] for r in rows],
            "realtime_start": [dt.date.fromisoformat(r[2]) for r in rows],
            "realtime_end": [dt.date.fromisoformat(r[3]) if r[3] else None for r in rows],
        }
    )


@pytest.fixture
def static_source() -> StaticSource:
    return StaticSource(
        {
            "static:ipca": frame(("2026-05-01", 0.5), ("2026-06-01", 0.3), ("2026-07-01", 0.4)),
            "static:selic": frame(("2026-08-28", 15.0), ("2026-08-29", 15.0)),
            "static:gdp_us": frame(("2026-01-01", 23000.0)),
        }
    )


@pytest.fixture
def leakage_guard() -> Callable[[pa.Table, dt.date], None]:
    """Assert that an as-of query never returns a row published after ``asof``."""

    def _check(table: pa.Table, asof: dt.date) -> None:
        df = table.to_pandas(date_as_object=True)
        if df.empty:
            return
        late = df[df["realtime_start"].map(lambda d: d > asof)]
        assert late.empty, f"leakage: {len(late)} rows with realtime_start > {asof}"

    return _check


# ---------------------------------------------------------------- the recorded FRED fixture
# Moved here from test_api.py once a second file needed it: the vintage tests ask exactly the
# question this fixture was built to answer, and a fixture two files share belongs in conftest.
FRED_FIX = Path(__file__).parent / "fixtures" / "fred"

FRED_CONCEPTS_YAML = """\
concepts:
  gdp_real: {description: Real GDP, unit_kind: level, default_agg: sum}
  govt_yield_10y: {description: Ten-year yield, unit_kind: pct_pa, default_agg: eop}
  cpi_headline: {description: CPI, unit_kind: pct, default_agg: sum}
"""

FRED_ENTITIES_YAML = """\
entities:
  - {entity_id: US, entity_type: country, name: United States}
  - {entity_id: BR, entity_type: country, name: Brazil}
"""

FRED_YAML = """\
source: fred
defaults: {entity_id: US, license: FRED terms, redistributable: false}
series:
  - native_id: GDPC1
    concept_id: gdp_real
    title: Real Gross Domestic Product
    unit: bn chained 2017 USD
    freq: Q
    seasonal_adj: true
    expected_lag_days: 30
  - native_id: DGS10
    concept_id: govt_yield_10y
    title: Ten-year Treasury constant maturity
    unit: percent per year
    freq: B
    expected_lag_days: 1
    params: {vintages: false}
"""


@pytest.fixture
def catalog_us(tmp_path: Path) -> Catalog:
    root = tmp_path / "catalog"
    (root / "us").mkdir(parents=True)
    (root / "concepts.yaml").write_text(FRED_CONCEPTS_YAML, encoding="utf-8")
    (root / "entities.yaml").write_text(FRED_ENTITIES_YAML, encoding="utf-8")
    (root / "us" / "fred.yaml").write_text(FRED_YAML, encoding="utf-8")
    return Catalog.load(root)


@pytest.fixture
def loaded(store: Store, catalog_us: Catalog) -> Api:
    """A store holding the recorded FRED vintages of GDP and the daily ten-year yield."""
    settings = Settings(_env_file=None, fred_api_key="test-key")
    client = Client(settings, sleep=lambda _: None, monotonic=lambda: 0.0)
    source = FredSource(settings, client=client)
    with respx.mock:
        respx.get(ENDPOINT).mock(
            side_effect=lambda request: httpx.Response(
                200,
                content=(FRED_FIX / "GDPC1_2024_vintages.json").read_bytes()
                if "GDPC1" in str(request.url)
                else (FRED_FIX / "DGS10_novintage_2026_01.json").read_bytes(),
            )
        )
        pipeline.update(
            store,
            catalog_us,
            {"fred": source},
            now=dt.datetime(2026, 9, 4, 12, tzinfo=dt.UTC),
            tz="UTC",
        )
    client.close()
    return Api(store, catalog_us)


# ---------------------------------------------------------------------------- resolution
