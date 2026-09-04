"""The shared HTTP client: pacing, retries, failures and the parsing helpers."""

from __future__ import annotations

import datetime as dt
import itertools
import math

import httpx
import pytest
import respx

from econbase.settings import Settings
from econbase.sources.base import SourceError
from econbase.sources.http import Client, date_windows, to_float

URL = "https://example.test/data"


class FakeClock:
    """Deterministic stand-in for time.monotonic/time.sleep."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(clock: FakeClock) -> Client:
    c = Client(
        Settings(_env_file=None),
        min_interval={"demo": 2.0},
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    yield c
    c.close()


@respx.mock
def test_pacing_waits_between_requests_to_the_same_source(client: Client, clock: FakeClock) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    client.get(URL, source="demo")
    assert clock.slept == [], "the first request never waits"
    client.get(URL, source="demo")
    assert clock.slept == [2.0], "the second waits the source's minimum interval"


@respx.mock
def test_pacing_is_per_source(client: Client, clock: FakeClock) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    client.get(URL, source="demo")
    client.get(URL, source="other")
    assert clock.slept == [], "a different source has its own budget"


@respx.mock
def test_retries_a_server_error_then_succeeds(client: Client) -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"value": 1}),
        ]
    )
    response = client.get(URL, source="demo")
    assert response.status_code == 200 and route.call_count == 2


@respx.mock
def test_retries_a_transport_error_then_succeeds(client: Client) -> None:
    route = respx.get(URL).mock(
        side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(200, json={})]
    )
    assert client.get(URL, source="demo").status_code == 200
    assert route.call_count == 2


@respx.mock
def test_gives_up_after_the_attempt_budget(client: Client) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(500, text="down"))
    with pytest.raises(SourceError, match="gave up after 5 attempts"):
        client.get(URL, source="demo")
    assert route.call_count == 5


@respx.mock
def test_a_client_error_fails_immediately_with_the_body(client: Client) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(404, text="no such series"))
    with pytest.raises(SourceError, match="HTTP 404"):
        client.get(URL, source="demo")
    assert route.call_count == 1, "a 404 is not worth retrying"


@respx.mock
def test_retry_after_header_is_honoured(client: Client, clock: FakeClock) -> None:
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={}),
        ]
    )
    client.get(URL, source="demo")
    assert 7.0 in clock.slept


@respx.mock
def test_credentials_are_redacted_in_error_messages(client: Client) -> None:
    respx.get(URL).mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(SourceError) as exc:
        client.get(URL, {"api_key": "s3cr3t", "series_id": "X"}, source="demo")
    assert "s3cr3t" not in str(exc.value) and "api_key=REDACTED" in str(exc.value)


@respx.mock
def test_the_user_agent_identifies_the_project(client: Client) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    client.get(URL, source="demo")
    assert route.calls[0].request.headers["User-Agent"].startswith("econbase/")


# ---------------------------------------------------------------------------- helpers
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0,21", 0.21),  # Brazilian decimal comma
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("1234.5", 1234.5),
        ("12%", 12.0),
        ("(1.5)", -1.5),
        ("-0,5", -0.5),
        (3, 3.0),
        (2.5, 2.5),
    ],
)
def test_to_float_parses_agency_number_formats(raw: object, expected: float) -> None:
    assert to_float(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [".", "...", "-", "", None, "X", "n/a", "NaN"])
def test_to_float_maps_missing_markers_to_nan(raw: object) -> None:
    assert math.isnan(to_float(raw))


def test_to_float_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="cannot parse"):
        to_float("twelve")


def test_date_windows_cover_the_range_without_gaps_or_overlaps() -> None:
    start, end = dt.date(2000, 1, 1), dt.date(2026, 9, 3)
    windows = date_windows(start, end, years=10)
    assert windows[0][0] == start and windows[-1][1] == end
    for (_, a_end), (b_start, _) in itertools.pairwise(windows):
        assert b_start == a_end + dt.timedelta(days=1)
    assert all(a <= b for a, b in windows)


def test_date_windows_handles_a_leap_day_start() -> None:
    windows = date_windows(dt.date(2024, 2, 29), dt.date(2026, 1, 1), years=1)
    assert windows[0][0] == dt.date(2024, 2, 29)
    for (_, a_end), (b_start, _) in itertools.pairwise(windows):
        assert b_start == a_end + dt.timedelta(days=1)


def test_date_windows_validates_its_arguments() -> None:
    with pytest.raises(ValueError, match="before start"):
        date_windows(dt.date(2026, 1, 2), dt.date(2026, 1, 1))
    with pytest.raises(ValueError, match="years must be"):
        date_windows(dt.date(2026, 1, 1), dt.date(2026, 1, 2), years=0)


def test_a_single_day_range_is_one_window() -> None:
    day = dt.date(2026, 1, 1)
    assert date_windows(day, day) == [(day, day)]


@respx.mock
def test_a_prebuilt_query_survives_the_request(client: Client, clock: FakeClock) -> None:
    """A URL that already carries a query must reach the server exactly as written.

    httpx replaces a URL's query with whatever `params` holds, so passing an empty dict used to
    strip it silently. An OData request that must encode its spaces as %20 then arrived with no
    filter at all and the server answered with the entire series instead of the two rows asked
    for — a wrong answer, not an error.
    """
    route = respx.get(url__startswith="https://example.test/odata").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    client.get("https://example.test/odata?%24top=2&%24filter=A%20eq%20'B'", source="demo")
    sent = str(route.calls[0].request.url)
    assert "%24top=2" in sent or "$top=2" in sent
    assert "A%20eq%20'B'" in sent or "A eq 'B'" in sent
    assert "+" not in sent.split("?", 1)[1]


@respx.mock
def test_params_still_work_when_they_are_given(client: Client) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    client.get(URL, {"series_id": "X", "limit": 5}, source="demo")
    params = dict(route.calls[0].request.url.params)
    assert params["series_id"] == "X" and params["limit"] == "5"
