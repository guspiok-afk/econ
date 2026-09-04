"""One HTTP client for every connector: pacing, retries and the small parsing helpers.

No connector opens its own ``httpx.Client``, writes its own retry loop or sleeps on its own.
Centralising it means one place decides how the project behaves towards a public API that is
doing us a favour by being open: a minimum interval between requests per source, bounded
retries with jitter on the errors that are worth retrying, and a clear failure otherwise.
"""

from __future__ import annotations

import datetime as dt
import logging
import ssl
import time
from collections.abc import Container, Mapping
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from econbase import __version__
from econbase.settings import Settings, get_settings
from econbase.sources.base import SourceError

log = logging.getLogger(__name__)

USER_AGENT = f"econbase/{__version__} (+https://github.com/guspiok-afk/econ)"

#: Minimum seconds between two requests to the same source. FRED documents 120 requests per
#: minute; the others publish no limit, so we stay deliberately gentle.
MIN_INTERVAL: dict[str, float] = {
    "fred": 0.6,
    "bcb_sgs": 2.0,
    "bcb_ptax": 2.0,
    "bcb_focus": 2.0,
    "sidra": 2.0,
    "ipeadata": 1.0,
    "dbnomics": 1.0,
    "nyfed": 5.0,
    "b3_taxas_ref": 5.0,
}
DEFAULT_MIN_INTERVAL = 1.0
MAX_ATTEMPTS = 5
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
#: Values a source uses to say "no number here".
MISSING_MARKERS = frozenset({"", ".", "..", "...", "-", "--", "n/a", "na", "nan", "x", "null"})


def default_ssl_context() -> ssl.SSLContext:
    """TLS context trusting the operating system's certificate store.

    ``httpx`` verifies against the bundled ``certifi`` roots, which fails on a machine whose
    traffic is inspected by corporate or antivirus middleware: the interception certificate
    lives in the OS store and nowhere else. Using the platform store keeps verification on
    (never disable it) while working on such machines. ``SSL_CERT_FILE`` still wins if set.
    """
    return ssl.create_default_context()


class RetryableStatus(Exception):
    """Internal signal: the response failed with a status worth retrying."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


def _log_retry(state: RetryCallState) -> None:
    log.warning(
        "retrying after %s (attempt %d/%d)",
        state.outcome.exception() if state.outcome else "?",
        state.attempt_number,
        MAX_ATTEMPTS,
    )


class Client:
    """Shared HTTP client. One instance per process is enough; it is not thread-safe."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        min_interval: Mapping[str, float] | None = None,
        sleep=time.sleep,
        monotonic=time.monotonic,
        verify: ssl.SSLContext | bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.min_interval = dict(MIN_INTERVAL)
        if min_interval:
            self.min_interval.update(min_interval)
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=self.settings.econbase_http_timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
            follow_redirects=True,
            verify=verify if verify is not None else default_ssl_context(),
        )

    # ------------------------------------------------------------------ pacing
    def _wait_turn(self, source: str) -> None:
        interval = self.min_interval.get(source, DEFAULT_MIN_INTERVAL)
        last = self._last_request.get(source)
        now = self._monotonic()
        if last is not None:
            remaining = interval - (now - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[source] = self._monotonic()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None

    # ------------------------------------------------------------------ requests
    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        source: str,
        headers: Mapping[str, str] | None = None,
        allow_status: Container[int] | None = None,
    ) -> httpx.Response:
        """GET with pacing and bounded retries. Raises :class:`SourceError` on failure.

        ``allow_status`` lists error statuses the caller wants to inspect itself instead of
        having them raised — the BCB answers a window with no observations with a 404, which is
        an ordinary outcome when sweeping a long history in windows, not a failure.
        """

        def _attempt() -> httpx.Response:
            self._wait_turn(source)
            # transport errors (timeout, connection reset) propagate for tenacity to retry
            response = self._client.get(url, params=dict(params or {}), headers=dict(headers or {}))
            if response.status_code in RETRY_STATUSES:
                pause = self._retry_after(response)
                if pause:
                    self._sleep(min(pause, 60.0))
                raise RetryableStatus(response)
            return response

        retrying = Retrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=wait_exponential_jitter(initial=1.0, max=60.0),
            retry=retry_if_exception_type((RetryableStatus, httpx.TransportError)),
            before_sleep=_log_retry,
            reraise=True,
            sleep=self._sleep,  # injectable so tests never wait for real
        )
        try:
            response = retrying(_attempt)
        except RetryableStatus as exc:
            raise SourceError(
                f"{source}: gave up after {MAX_ATTEMPTS} attempts, "
                f"last status {exc.response.status_code} for {_safe_url(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceError(
                f"{source}: request failed after {MAX_ATTEMPTS} attempts: {exc}"
            ) from exc

        if response.status_code >= 400 and not (
            allow_status and response.status_code in allow_status
        ):
            raise SourceError(
                f"{source}: HTTP {response.status_code} for {_safe_url(response)}: "
                f"{response.text[:200]}"
            )
        return response

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _safe_url(response: httpx.Response) -> str:
    from econbase.pipeline import redact  # local import: pipeline imports sources

    return redact(str(response.request.url)) or ""


# ---------------------------------------------------------------------------- parsing helpers
def to_float(value: object) -> float:
    """Parse a number the way statistical agencies write them; missing markers become NaN.

    Handles ``"0,21"`` (Brazilian decimal comma), ``"1.234,56"``, ``"1,234.56"``, percent signs
    and the assorted "no value here" markers (``"."`` at FRED, ``"..."`` and ``"-"`` at SIDRA).

    A single separator with exactly one group after it (``"1,234"``) is genuinely ambiguous;
    it is read as a decimal separator, which is the Brazilian convention this project meets
    most often. A connector whose source writes thousands that way must clean it first.
    """
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace("\xa0", "").replace(" ", "")
    if text.lower() in MISSING_MARKERS:
        return float("nan")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        # the rightmost separator is the decimal one; the other groups thousands
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        text = text.replace(",", "") if _is_thousands(text, ",") else text.replace(",", ".")
    elif has_dot and _is_thousands(text, "."):
        text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"cannot parse {value!r} as a number") from None
    return -number if negative else number


def _is_thousands(text: str, sep: str) -> bool:
    """True when ``sep`` groups thousands (``1.234.567``) rather than marking decimals."""
    body = text.lstrip("+-")
    parts = body.split(sep)
    if len(parts) < 2 or not parts[0] or len(parts[0]) > 3:
        return False
    return all(len(part) == 3 and part.isdigit() for part in parts[1:]) and len(parts) > 2


def odata_query(**params: object) -> str:
    """Build an OData query string the BCB's Olinda gateway accepts.

    ``httpx`` (like most clients) encodes a space as ``+``. Olinda rejects that with
    ``The types 'Edm.Boolean' and 'Edm.String' are not compatible``, an error message that
    points nowhere near the real cause. It wants ``%20``, and it accepts the single quotes of
    an OData literal unencoded. Build the query here and pass the finished URL to
    :meth:`Client.get`; never hand these parameters to ``params=``.

    >>> odata_query(**{"$format": "json", "$filter": "Indicador eq 'IPCA'"})
    "$format=json&$filter=Indicador%20eq%20'IPCA'"
    """
    parts = []
    for key, value in params.items():
        if value is None:
            continue
        parts.append(f"{key}={quote(str(value), safe="$,'()/:")}")
    return "&".join(parts)


def date_windows(start: dt.date, end: dt.date, *, years: int = 10) -> list[tuple[dt.date, dt.date]]:
    """Split ``[start, end]`` into consecutive inclusive windows of at most ``years``.

    Several APIs cap a request's span (BCB SGS refuses more than ten years of a daily series),
    so a connector fetches history in windows and concatenates.
    """
    if years < 1:
        raise ValueError("years must be >= 1")
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    windows: list[tuple[dt.date, dt.date]] = []
    cursor = start
    while cursor <= end:
        try:
            stop = cursor.replace(year=cursor.year + years) - dt.timedelta(days=1)
        except ValueError:  # 29 February
            stop = cursor.replace(year=cursor.year + years, day=28) - dt.timedelta(days=1)
        windows.append((cursor, min(stop, end)))
        cursor = stop + dt.timedelta(days=1)
    return windows
