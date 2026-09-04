"""The FRED connector, against responses recorded from the live API.

Fixtures in ``tests/fixtures/fred/`` were recorded on 2026-09-03 with the project's own key
(stripped from the stored bodies, which never contain it). ``GDPC1_2024_vintages.json`` is the
interesting one: four quarters of real GDP, each revised four or five times, ending with the
currently-valid vintage.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import httpx
import pytest
import respx

from econbase import pipeline, schemas
from econbase.catalog import Catalog, SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, SourceError
from econbase.sources.fred import ENDPOINT, FredSource
from econbase.sources.http import Client
from econbase.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "fred"
KEY = "test-key-not-a-real-one"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def spec(native_id: str = "GDPC1", **params) -> SeriesSpec:
    return SeriesSpec(
        source="fred",
        native_id=native_id,
        entity_id="US",
        title=native_id,
        freq="Q" if native_id == "GDPC1" else "B",
        params=params,
    )


@pytest.fixture
def source() -> FredSource:
    settings = Settings(_env_file=None, fred_api_key=KEY)
    client = Client(settings, sleep=lambda _: None, monotonic=lambda: 0.0)
    src = FredSource(settings, client=client)
    yield src
    client.close()


# ---------------------------------------------------------------------------- parsing
def test_parses_every_vintage_of_every_period(source: FredSource) -> None:
    frame = source.parse(RawResponse(body=body("GDPC1_2024_vintages.json")), spec())
    assert list(frame.columns) == ["period", "value", "realtime_start", "realtime_end"]
    assert len(frame) == 17
    assert frame["period"].nunique() == 4, "four quarters of 2024"
    assert frame["realtime_end"].isna().sum() == 4, "one currently-valid vintage per quarter"
    assert all(isinstance(p, dt.date) for p in frame["period"])


def test_fred_inclusive_end_becomes_the_projects_exclusive_end(source: FredSource) -> None:
    """FRED reports the last valid day; the store records the first invalid one."""
    frame = source.parse(RawResponse(body=body("GDPC1_2024_vintages.json")), spec())
    q1 = frame[frame["period"] == dt.date(2024, 1, 1)].reset_index(drop=True)
    # recorded: first vintage valid 2024-04-25..2024-05-29, second starts 2024-05-30
    assert q1.loc[0, "realtime_start"] == dt.date(2024, 4, 25)
    assert q1.loc[0, "realtime_end"] == dt.date(2024, 5, 30), "2024-05-29 inclusive + 1 day"
    assert q1.loc[1, "realtime_start"] == dt.date(2024, 5, 30), "intervals meet exactly"
    ends = list(q1["realtime_end"])[:-1]
    starts = list(q1["realtime_start"])[1:]
    assert ends == starts, "no gap and no overlap between consecutive vintages"


def test_the_open_ended_sentinel_becomes_none(source: FredSource) -> None:
    frame = source.parse(RawResponse(body=body("GDPC1_2024_vintages.json")), spec())
    current = frame[frame["realtime_end"].isna()]
    assert len(current) == 4
    assert current["realtime_start"].max() == dt.date(2025, 9, 25)


def test_non_vintaged_series_return_only_period_and_value(source: FredSource) -> None:
    frame = source.parse(
        RawResponse(body=body("DGS10_novintage_2026_01.json")), spec("DGS10", vintages=False)
    )
    assert list(frame.columns) == ["period", "value"]
    assert len(frame) == 22
    holidays = frame[frame["value"].isna()]
    assert len(holidays) == 2, "New Year's Day and Martin Luther King Jr. Day carry '.'"
    assert dt.date(2026, 1, 1) in set(holidays["period"])
    assert math.isclose(
        float(frame.loc[frame["period"] == dt.date(2026, 1, 2), "value"].iloc[0]), 4.19
    )


def test_an_error_body_becomes_a_source_error(source: FredSource) -> None:
    with pytest.raises(SourceError, match="vintage dates"):
        source.parse(RawResponse(body=body("DGS10_vintage_limit_error.json")), spec("DGS10"))


def test_an_empty_body_is_rejected(source: FredSource) -> None:
    with pytest.raises(SourceError, match="empty body"):
        source.parse(RawResponse(body=b""), spec())


def test_a_non_json_body_is_rejected(source: FredSource) -> None:
    with pytest.raises(SourceError, match="not JSON"):
        source.parse(RawResponse(body=b"<html>maintenance</html>"), spec())


def test_no_observations_yields_an_empty_frame(source: FredSource) -> None:
    empty = json.dumps({"count": 0, "limit": 100000, "offset": 0, "observations": []}).encode()
    frame = source.parse(RawResponse(body=empty), spec())
    assert frame.empty and list(frame.columns) == [
        "period",
        "value",
        "realtime_start",
        "realtime_end",
    ]


# ---------------------------------------------------------------------------- fetching
@respx.mock
def test_fetch_requests_the_full_real_time_period(source: FredSource) -> None:
    route = respx.get(ENDPOINT).mock(
        return_value=httpx.Response(200, content=body("GDPC1_2024_vintages.json"))
    )
    raw = source.fetch_raw(spec())
    params = dict(route.calls[0].request.url.params)
    assert params["realtime_start"] == "1776-07-04" and params["realtime_end"] == "9999-12-31"
    assert params["series_id"] == "GDPC1" and params["file_type"] == "json"
    assert raw.covers_from is None, "the whole history is always returned"
    assert raw.ext == "json" and raw.body == body("GDPC1_2024_vintages.json")


@respx.mock
def test_a_non_vintaged_series_omits_the_real_time_period(source: FredSource) -> None:
    route = respx.get(ENDPOINT).mock(
        return_value=httpx.Response(200, content=body("DGS10_novintage_2026_01.json"))
    )
    source.fetch_raw(spec("DGS10", vintages=False))
    params = dict(route.calls[0].request.url.params)
    assert "realtime_start" not in params and "realtime_end" not in params


@respx.mock
def test_pagination_follows_the_count_and_keeps_every_page(source: FredSource) -> None:
    route = respx.get(ENDPOINT).mock(
        side_effect=[
            httpx.Response(200, content=body("GDPC1_page1.json")),
            httpx.Response(200, content=body("GDPC1_page2.json")),
        ]
    )
    raw = source.fetch_raw(spec())
    assert route.call_count == 2
    assert dict(route.calls[0].request.url.params)["offset"] == "0"
    assert dict(route.calls[1].request.url.params)["offset"] == "10"
    payload = json.loads(raw.body)
    assert isinstance(payload, list) and len(payload) == 2, "pages archived as a JSON array"
    frame = source.parse(raw, spec())
    assert len(frame) == 17, "the two pages parse back to the whole series"


@respx.mock
def test_observation_window_parameters_are_passed_through(source: FredSource) -> None:
    route = respx.get(ENDPOINT).mock(
        return_value=httpx.Response(200, content=body("GDPC1_2024_vintages.json"))
    )
    source.fetch_raw(spec(observation_start="2024-01-01", observation_end=dt.date(2024, 12, 31)))
    params = dict(route.calls[0].request.url.params)
    assert params["observation_start"] == "2024-01-01"
    assert params["observation_end"] == "2024-12-31"


@respx.mock
def test_extra_parameters_reach_the_api(source: FredSource) -> None:
    route = respx.get(ENDPOINT).mock(
        return_value=httpx.Response(200, content=body("GDPC1_2024_vintages.json"))
    )
    source.fetch_raw(spec(extra={"units": "pch"}))
    assert dict(route.calls[0].request.url.params)["units"] == "pch"


def test_a_missing_api_key_fails_before_any_request() -> None:
    src = FredSource(Settings(_env_file=None, fred_api_key=None))
    with respx.mock:
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(SourceError, match="FRED_API_KEY is not set"):
            src.fetch_raw(spec())
        assert route.call_count == 0


@respx.mock
def test_the_vintage_limit_refusal_names_the_fix(source: FredSource) -> None:
    respx.get(ENDPOINT).mock(
        return_value=httpx.Response(400, content=body("DGS10_vintage_limit_error.json"))
    )
    with pytest.raises(SourceError, match="vintages: false"):
        source.fetch_raw(spec("DGS10"))


@respx.mock
def test_the_api_key_never_appears_in_an_error(source: FredSource) -> None:
    respx.get(ENDPOINT).mock(return_value=httpx.Response(404, text="no such series"))
    with pytest.raises(SourceError) as exc:
        source.fetch_raw(spec("NOPE"))
    assert KEY not in str(exc.value)


# ---------------------------------------------------------------------------- end to end
@pytest.fixture
def fred_catalog(tmp_path: Path) -> Catalog:
    root = tmp_path / "catalog"
    (root / "us").mkdir(parents=True)
    (root / "concepts.yaml").write_text(
        "concepts:\n  gdp_real: {description: Real GDP, unit_kind: level, default_agg: sum}\n",
        encoding="utf-8",
    )
    (root / "entities.yaml").write_text(
        "entities:\n  - {entity_id: US, entity_type: country, name: United States}\n",
        encoding="utf-8",
    )
    (root / "us" / "fred.yaml").write_text(
        "source: fred\n"
        "defaults: {entity_id: US, license: FRED terms, redistributable: false}\n"
        "series:\n"
        "  - native_id: GDPC1\n"
        "    concept_id: gdp_real\n"
        "    title: Real Gross Domestic Product\n"
        "    unit: bn chained 2017 USD\n"
        "    freq: Q\n"
        "    seasonal_adj: true\n"
        "    expected_lag_days: 30\n",
        encoding="utf-8",
    )
    return Catalog.load(root)


@respx.mock
def test_update_stores_the_vintages_and_answers_as_of_questions(
    store: Store, fred_catalog: Catalog, source: FredSource
) -> None:
    respx.get(ENDPOINT).mock(
        return_value=httpx.Response(200, content=body("GDPC1_2024_vintages.json"))
    )
    summary = pipeline.update(
        store,
        fred_catalog,
        {"fred": source},
        now=dt.datetime(2026, 9, 3, 12, tzinfo=dt.UTC),
        tz="UTC",
    )
    assert summary.status == "ok", summary.outcomes[0].error
    assert summary.outcomes[0].rows_new == 17

    latest = schemas.to_pandas(store.observations(["fred:GDPC1"]))
    assert len(latest) == 4, "one current value per quarter"
    q1_now = float(latest.loc[latest["period"] == dt.date(2024, 1, 1), "value"].iloc[0])
    assert math.isclose(q1_now, 23082.119)

    # what was known on 2024-05-01: the first estimate, not today's number
    asof = schemas.to_pandas(store.observations(["fred:GDPC1"], asof=dt.date(2024, 5, 1)))
    assert len(asof) == 1, "only the first quarter had been published"
    assert math.isclose(float(asof.loc[0, "value"]), 22768.866)

    # the boundary day of a vintage still resolves (the inclusive/exclusive conversion)
    boundary = schemas.to_pandas(store.observations(["fred:GDPC1"], asof=dt.date(2024, 5, 29)))
    assert math.isclose(float(boundary.loc[0, "value"]), 22768.866)
    next_day = schemas.to_pandas(store.observations(["fred:GDPC1"], asof=dt.date(2024, 5, 30)))
    assert math.isclose(float(next_day.loc[0, "value"]), 22749.846)

    first = schemas.to_pandas(store.first_release(["fred:GDPC1"]))
    assert math.isclose(
        float(first.loc[first["period"] == dt.date(2024, 1, 1), "value"].iloc[0]), 22768.866
    )

    raw_index = schemas.to_pandas(store.read("raw_index"))
    assert len(raw_index) == 1 and raw_index.loc[0, "stored"]
    assert "api_key=REDACTED" in raw_index.loc[0, "url"]


@respx.mock
def test_a_second_identical_update_changes_nothing(
    store: Store, fred_catalog: Catalog, source: FredSource
) -> None:
    respx.get(ENDPOINT).mock(
        return_value=httpx.Response(200, content=body("GDPC1_2024_vintages.json"))
    )
    for day in (3, 4):
        summary = pipeline.update(
            store,
            fred_catalog,
            {"fred": source},
            now=dt.datetime(2026, 9, day, 12, tzinfo=dt.UTC),
            tz="UTC",
        )
    assert (summary.outcomes[0].rows_new, summary.outcomes[0].rows_revised) == (0, 0)
    assert store.observations(["fred:GDPC1"], include_history=True).num_rows == 17
    raw_index = schemas.to_pandas(store.read("raw_index"))
    assert len(raw_index) == 2 and not raw_index.loc[1, "stored"], "identical body deduped"
