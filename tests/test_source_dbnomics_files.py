"""Acceptance tests for WP-02d: the DBnomics client and the published-file reader.

Recorded from the live sources on 2026-09-04. Two things they proved are worth stating up
front, because both silently misdate a whole series if handled by assumption:

* DBnomics writes a period differently for every frequency, and only ``@frequency`` says which
  convention applies;
* the New York Fed publishes the supply chain index as a legacy ``.xls`` under an ``.xlsx``
  name, with dates on the last day of each month rather than the first.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import httpx
import pytest
import respx

from econbase import pipeline, schemas
from econbase.catalog import Catalog, SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, SourceError
from econbase.sources.http import Client
from econbase.store import Store

pytest.importorskip("econbase.sources.dbnomics", reason="WP-02d not implemented yet")
pytest.importorskip("econbase.sources.file_http", reason="WP-02d not implemented yet")

from econbase.sources.dbnomics import DbnomicsSource
from econbase.sources.file_http import FileHttpSource

DB_FIX = Path(__file__).parent / "fixtures" / "dbnomics"
FILE_FIX = Path(__file__).parent / "fixtures" / "file_http"
DB_BASE = "https://api.db.nomics.world/v22/series"
GSCPI_URL = (
    "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"
)


def db_body(name: str) -> bytes:
    return (DB_FIX / name).read_bytes()


def gscpi_bytes() -> bytes:
    return (FILE_FIX / "gscpi_data.xlsx").read_bytes()


def db_spec(native_id: str, freq: str) -> SeriesSpec:
    return SeriesSpec(
        source="dbnomics", native_id=native_id, entity_id="BR", title=native_id, freq=freq
    )


def gscpi_spec(**params) -> SeriesSpec:
    base = {
        "url": GSCPI_URL,
        "sheet": "GSCPI Monthly Data",
        "skiprows": 5,
        "period_is_end": True,
    }
    return SeriesSpec(
        source="file_http",
        native_id="nyfed_gscpi",
        entity_id="WW",
        title="Global Supply Chain Pressure Index",
        freq="M",
        params={**base, **params},
    )


@pytest.fixture
def client() -> Client:
    c = Client(Settings(_env_file=None), sleep=lambda _: None, monotonic=lambda: 0.0)
    yield c
    c.close()


@pytest.fixture
def dbn(client: Client) -> DbnomicsSource:
    return DbnomicsSource(Settings(_env_file=None), client=client)


@pytest.fixture
def files(client: Client) -> FileHttpSource:
    return FileHttpSource(Settings(_env_file=None), client=client)


# --------------------------------------------------- DBnomics: one period style per frequency
def test_an_annual_period_is_the_first_of_january(dbn: DbnomicsSource) -> None:
    frame = dbn.parse(RawResponse(body=db_body("bcb_bop_anual.json")), db_spec("BCB/bop/S1-A", "A"))
    assert list(frame.columns) == ["period", "value"]
    assert frame["period"].min() == dt.date(1995, 1, 1)
    assert all(p.month == 1 and p.day == 1 for p in frame["period"])


def test_a_quarterly_period_starts_its_quarter(dbn: DbnomicsSource) -> None:
    """1995-Q1 becomes 1995-01-01, not the first of March or the end of the quarter."""
    frame = dbn.parse(
        RawResponse(body=db_body("bcb_bop_trimestral.json")), db_spec("BCB/bop/S1-Q", "Q")
    )
    periods = sorted(frame["period"])
    assert periods[0] == dt.date(1995, 1, 1)
    assert periods[1] == dt.date(1995, 4, 1)
    assert all(p.month in (1, 4, 7, 10) and p.day == 1 for p in periods)


def test_a_monthly_period_starts_its_month(dbn: DbnomicsSource) -> None:
    frame = dbn.parse(
        RawResponse(body=db_body("bcb_bop_mensal.json")), db_spec("BCB/bop/S1-M", "M")
    )
    periods = sorted(frame["period"])
    assert periods[0] == dt.date(1995, 1, 1)
    assert periods[1] == dt.date(1995, 2, 1)
    assert all(p.day == 1 for p in periods)


def test_the_catalog_frequency_must_agree_with_the_source(dbn: DbnomicsSource) -> None:
    """A quarterly series declared monthly would be misdated silently; refuse instead."""
    with pytest.raises(SourceError):
        dbn.parse(
            RawResponse(body=db_body("bcb_bop_trimestral.json")), db_spec("BCB/bop/S1-Q", "M")
        )


def test_a_response_without_series_is_rejected(dbn: DbnomicsSource) -> None:
    with pytest.raises(SourceError):
        dbn.parse(
            RawResponse(body=db_body("serie_inexistente_404.json")), db_spec("NAO/EXISTE/XYZ", "A")
        )


def test_a_null_observation_becomes_nan(dbn: DbnomicsSource) -> None:
    body = (
        b'{"series": {"docs": [{"@frequency": "annual", "period": ["2020", "2021"], '
        b'"value": [1.5, null]}]}}'
    )
    frame = dbn.parse(RawResponse(body=body), db_spec("X/Y/Z", "A"))
    assert math.isclose(float(frame["value"].iloc[0]), 1.5)
    assert math.isnan(float(frame["value"].iloc[1]))


@respx.mock
def test_fetch_asks_for_observations(dbn: DbnomicsSource) -> None:
    route = respx.get(url__startswith=DB_BASE).mock(
        return_value=httpx.Response(200, content=db_body("bcb_bop_anual.json"))
    )
    raw = dbn.fetch_raw(db_spec("BCB/bop/S1-A", "A"))
    url = str(route.calls[0].request.url)
    assert "BCB/bop/S1-A" in url and "observations=1" in url
    assert raw.covers_from is None and raw.ext == "json"


# --------------------------------------------------- published files
def test_the_engine_comes_from_the_signature_not_the_extension(files: FileHttpSource) -> None:
    """gscpi_data.xlsx is a legacy OLE .xls; openpyxl cannot open it and xlrd can."""
    assert gscpi_bytes()[:4] == b"\xd0\xcf\x11\xe0", "the fixture really is the old format"
    frame = files.parse(RawResponse(body=gscpi_bytes(), ext="xlsx"), gscpi_spec())
    assert len(frame) == 343


def test_month_end_dates_are_moved_to_the_period_start(files: FileHttpSource) -> None:
    """The sheet says 31-Jan-1998; the store keeps 1998-01-01."""
    frame = files.parse(RawResponse(body=gscpi_bytes()), gscpi_spec())
    assert frame["period"].min() == dt.date(1998, 1, 1)
    assert frame["period"].max() == dt.date(2026, 7, 1)
    assert all(p.day == 1 for p in frame["period"])
    first = frame.loc[frame["period"] == dt.date(1998, 1, 1), "value"].iloc[0]
    assert math.isclose(float(first), -1.147548, abs_tol=1e-6)
    last = frame.loc[frame["period"] == dt.date(2026, 7, 1), "value"].iloc[0]
    assert math.isclose(float(last), 0.804737, abs_tol=1e-6)


def test_the_branding_rows_above_the_data_are_skipped(files: FileHttpSource) -> None:
    """Rows 1 to 4 of the sheet carry a logo and a link, not observations."""
    frame = files.parse(RawResponse(body=gscpi_bytes()), gscpi_spec())
    assert frame["value"].notna().all()
    assert frame["period"].is_monotonic_increasing


def test_a_missing_url_parameter_is_refused(files: FileHttpSource) -> None:
    spec = SeriesSpec(
        source="file_http", native_id="x", entity_id="WW", title="x", freq="M", params={}
    )
    with pytest.raises(SourceError):
        files.fetch_raw(spec)


def test_a_csv_is_read_with_the_same_parameters(files: FileHttpSource) -> None:
    csv = b"when,how_much\n2026-01-01,1.5\n2026-02-01,2.5\n"
    spec = SeriesSpec(
        source="file_http",
        native_id="demo",
        entity_id="WW",
        title="demo",
        freq="M",
        params={
            "url": "https://x/y.csv",
            "format": "csv",
            "date_col": "when",
            "value_col": "how_much",
        },
    )
    frame = files.parse(RawResponse(body=csv, ext="csv"), spec)
    assert list(frame["period"]) == [dt.date(2026, 1, 1), dt.date(2026, 2, 1)]
    assert list(frame["value"]) == pytest.approx([1.5, 2.5])


@respx.mock
def test_fetch_downloads_the_url_from_the_catalog_entry(files: FileHttpSource) -> None:
    route = respx.get(GSCPI_URL).mock(return_value=httpx.Response(200, content=gscpi_bytes()))
    raw = files.fetch_raw(gscpi_spec())
    assert route.call_count == 1
    assert raw.body == gscpi_bytes() and raw.covers_from is None


# --------------------------------------------------- end to end
CONCEPTS_YAML = """\
concepts:
  supply_chain_pressure: {description: GSCPI, unit_kind: index, default_agg: mean}
"""

ENTITIES_YAML = """\
entities:
  - {entity_id: WW, entity_type: region, name: World}
  - {entity_id: BR, entity_type: country, name: Brazil}
"""

NYFED_YAML = """\
source: file_http
defaults: {entity_id: WW, license: NY Fed terms of use, redistributable: false}
series:
  - native_id: nyfed_gscpi
    concept_id: supply_chain_pressure
    title: Global Supply Chain Pressure Index
    unit: standard deviations from the mean
    freq: M
    expected_lag_days: 10
    params:
      url: https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx
      sheet: GSCPI Monthly Data
      skiprows: 5
      period_is_end: true
"""


@pytest.fixture
def gscpi_catalog(tmp_path: Path) -> Catalog:
    root = tmp_path / "catalog"
    (root / "us").mkdir(parents=True)
    (root / "concepts.yaml").write_text(CONCEPTS_YAML, encoding="utf-8")
    (root / "entities.yaml").write_text(ENTITIES_YAML, encoding="utf-8")
    (root / "us" / "nyfed.yaml").write_text(NYFED_YAML, encoding="utf-8")
    return Catalog.load(root)


@respx.mock
def test_update_stores_the_index_and_archives_the_spreadsheet(
    store: Store, gscpi_catalog: Catalog, files: FileHttpSource
) -> None:
    respx.get(GSCPI_URL).mock(return_value=httpx.Response(200, content=gscpi_bytes()))
    summary = pipeline.update(
        store,
        gscpi_catalog,
        {"file_http": files},
        now=dt.datetime(2026, 9, 4, 12, tzinfo=dt.UTC),
        tz="UTC",
    )
    assert summary.status == "ok", [o.error for o in summary.outcomes]
    stored = schemas.to_pandas(store.observations(["file_http:nyfed_gscpi"]))
    assert len(stored) == 343
    assert stored["period"].min() == dt.date(1998, 1, 1)

    raw_index = schemas.to_pandas(store.read("raw_index"))
    assert len(raw_index) == 1 and raw_index.loc[0, "stored"]
    archived = store.raw_dir / raw_index.loc[0, "path"]
    assert archived.exists(), "the spreadsheet itself is kept, not only what we parsed from it"
