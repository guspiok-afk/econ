"""FRED (Federal Reserve Bank of St. Louis) — the one source with real vintages.

FRED's ``series/observations`` endpoint returns, for a real-time period spanning all of
history, one row per ``(date, realtime_start, realtime_end)``: exactly the bitemporal shape
this project stores. That is why the connector talks to the endpoint directly instead of
wrapping ``fredapi``, whose ``get_series_all_releases`` drops ``realtime_end`` and so cannot
say when a value stopped being current.

Series parameters (``params`` in the catalog entry):

``vintages`` (bool, default ``True``)
    Ask for the whole real-time period, so the store receives FRED's own intervals. FRED
    refuses this for series with more than 2000 vintage dates (daily rates such as ``DGS10``
    are revised every business day); set ``vintages: false`` for those. The connector then
    returns only ``period``/``value`` and the pipeline assigns pseudo real-time intervals from
    the collection date, exactly as it does for the Brazilian sources.
``observation_start``/``observation_end``
    ISO dates limiting the periods requested (default: everything).
``extra``
    Mapping passed through to the API (``units``, ``frequency``, ``aggregation_method``).
    Use sparingly: a transformation applied by the source is invisible to the store.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, Source, SourceError, register
from econbase.sources.http import Client, to_float

ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"
#: The full real-time period FRED accepts: everything ever published, still current included.
FIRST_REALTIME = "1776-07-04"
LAST_REALTIME = "9999-12-31"
PAGE_LIMIT = 100_000
MAX_PAGES = 100
#: FRED rejects a real-time period covering more vintage dates than this (JSON file type).
MAX_VINTAGE_DATES = 2000


def _iso(value: object, field: str) -> dt.date:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise SourceError(f"fred: {field} {value!r} is not an ISO date") from exc


def _exclusive_end(value: object) -> dt.date | None:
    """Convert FRED's inclusive ``realtime_end`` to this project's exclusive one.

    FRED reports the **last** day a value was current; ``docs/CONTRACT.md`` stores the
    **first** day it was not. Copying the field verbatim would make an as-of query on the last
    day of a vintage return nothing at all, because the next vintage only starts the day after.
    The open-ended sentinel becomes ``None`` (the pipeline would map it anyway, and adding a
    day to 9999-12-31 would overflow).
    """
    end = _iso(value, "realtime_end")
    if end >= dt.date(9999, 12, 31):
        return None
    return end + dt.timedelta(days=1)


def _explain(exc: SourceError, spec: SeriesSpec) -> SourceError:
    """Turn FRED's vintage-limit refusal into the instruction that fixes it."""
    text = str(exc)
    if "vintage dates" in text and "exceeds the maximum" in text:
        return SourceError(
            f"fred: {spec.native_id} has more than {MAX_VINTAGE_DATES} vintage dates, which "
            "FRED refuses to return at once. Set `params: {vintages: false}` on this catalog "
            "entry: the store then records pseudo real-time intervals from the collection "
            f"date. Original error: {text}"
        )
    return exc


@register
class FredSource(Source):
    """Bitemporal connector for FRED series (``fred:CPIAUCSL``)."""

    name = "fred"

    def __init__(self, settings: Settings | None = None, client: Client | None = None) -> None:
        super().__init__(settings)
        self._client = client

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = Client(self.settings)
        return self._client

    # ------------------------------------------------------------------ fetch
    @staticmethod
    def wants_vintages(spec: SeriesSpec) -> bool:
        """Whether to ask FRED for its own real-time intervals for this series."""
        return bool(spec.params.get("vintages", True))

    def _params(self, spec: SeriesSpec, offset: int) -> dict[str, Any]:
        key = (self.settings or Settings()).fred_api_key
        params: dict[str, Any] = {
            "series_id": spec.native_id,
            "api_key": key,
            "file_type": "json",
            "limit": PAGE_LIMIT,
            "offset": offset,
            "sort_order": "asc",
        }
        if self.wants_vintages(spec):
            params["realtime_start"] = FIRST_REALTIME
            params["realtime_end"] = LAST_REALTIME
        extra = spec.params.get("extra") or {}
        if not isinstance(extra, dict):
            raise SourceError(f"fred: params.extra must be a mapping, got {type(extra).__name__}")
        params.update(extra)
        for field in ("observation_start", "observation_end"):
            if spec.params.get(field):
                params[field] = _iso(spec.params[field], field).isoformat()
        return params

    def fetch_raw(self, spec: SeriesSpec, since: dt.date | None = None) -> RawResponse:
        """Fetch every vintage of the series, following the API's pagination.

        ``since`` is ignored: FRED is cheap to read in full and the whole vintage history is
        what makes it worth having, so the response always covers everything.
        """
        settings = self.settings or Settings()
        if not settings.fred_api_key:
            raise SourceError(
                "fred: FRED_API_KEY is not set; put it in .env (free key at "
                "https://fred.stlouisfed.org/docs/api/api_key.html)"
            )
        pages: list[bytes] = []
        offset = 0
        url = ENDPOINT
        while True:
            try:
                response = self.client.get(ENDPOINT, self._params(spec, offset), source=self.name)
            except SourceError as exc:
                raise _explain(exc, spec) from exc
            url = str(response.request.url)
            pages.append(response.content)
            try:
                meta = response.json()
            except json.JSONDecodeError as exc:
                raise SourceError(f"fred: {spec.native_id}: response is not JSON: {exc}") from exc
            count = int(meta.get("count", 0))
            limit = int(meta.get("limit", PAGE_LIMIT))
            offset += limit
            if offset >= count or not meta.get("observations"):
                break
            if len(pages) >= MAX_PAGES:
                raise SourceError(
                    f"fred: {spec.native_id}: more than {MAX_PAGES} pages ({count} rows); "
                    "narrow the request with params.observation_start"
                )
        body = pages[0] if len(pages) == 1 else b"[" + b",".join(pages) + b"]"
        return RawResponse(body=body, ext="json", url=url, covers_from=None)

    # ------------------------------------------------------------------ parse
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        """Turn the archived body into the frame the pipeline expects.

        With ``vintages`` on that is the bitemporal shape; with it off, ``period``/``value``
        only, because FRED then reports every row as valid for today alone, which would be a
        zero-length interval rather than a vintage.
        """
        if not raw.body:
            raise SourceError(f"fred: {spec.native_id}: empty body")
        try:
            payload = json.loads(raw.body)
        except json.JSONDecodeError as exc:
            raise SourceError(f"fred: {spec.native_id}: archived body is not JSON: {exc}") from exc
        pages = payload if isinstance(payload, list) else [payload]

        vintaged = self.wants_vintages(spec)
        columns = ["period", "value"] + (["realtime_start", "realtime_end"] if vintaged else [])
        rows: list[dict[str, Any]] = []
        for page in pages:
            if not isinstance(page, dict):
                raise SourceError(
                    f"fred: {spec.native_id}: unexpected page type {type(page).__name__}"
                )
            if "error_message" in page:
                raise SourceError(f"fred: {spec.native_id}: {page['error_message']}")
            for obs in page.get("observations", []):
                row = {"period": _iso(obs["date"], "date"), "value": to_float(obs.get("value"))}
                if vintaged:
                    row["realtime_start"] = _iso(obs["realtime_start"], "realtime_start")
                    row["realtime_end"] = _exclusive_end(obs["realtime_end"])
                rows.append(row)
        if not rows:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame(rows)
        sort_by = ["period", "realtime_start"] if vintaged else ["period"]
        # the pipeline maps the far-future sentinel to NULL and validates the intervals
        return frame.sort_values(sort_by).reset_index(drop=True)
