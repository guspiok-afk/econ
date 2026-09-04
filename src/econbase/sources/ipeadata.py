"""IPEA (Instituto de Pesquisa Econômica Aplicada) OData API connector.

IPEA exposes historical series through an OData v4 endpoint.  The timestamps in the response
carry a shifting UTC offset (``-02:00`` during Brazilian summer time, ``-03:00`` otherwise),
so only the date part before the ``T`` is used — never converting the timestamp to another
timezone first.

IPEA silently returns HTTP 200 with an empty ``value`` list for a code that does not exist,
so the connector raises :class:`SourceError` when no observations come back, because
distinguishing "no such series" from "legitimately empty" is impossible.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, Source, SourceError, register
from econbase.sources.http import Client

ENDPOINT = "http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{code}')"


def _parse_ipea_date(raw: str) -> dt.date:
    """Extract the date from an IPEA timestamp, ignoring the UTC offset.

    Examples:
        ``"1974-01-01T00:00:00-02:00"`` → ``date(1974, 1, 1)``
        ``"2026-07-01T00:00:00-03:00"`` → ``date(2026, 7, 1)``

    The offset shifts with daylight saving time, so converting the timestamp as a whole
    would move some dates to the previous day.  Taking the date part before the ``T``
    gives the value IPEA intended.
    """
    date_str = raw.split("T", 1)[0]
    return dt.date.fromisoformat(date_str)


@register
class IpeadataSource(Source):
    """Connector for IPEA's OData series (``ipeadata:BM12_TJOVER12``)."""

    name = "ipeadata"

    def __init__(self, settings: Settings | None = None, client: Client | None = None) -> None:
        super().__init__(settings)
        self._client = client

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = Client(self.settings)
        return self._client

    # ------------------------------------------------------------------ fetch
    def fetch_raw(self, spec: SeriesSpec, since: dt.date | None = None) -> RawResponse:
        """Fetch the full history of an IPEA series.

        ``since`` is ignored: the entire series is returned in one request.
        """
        url = ENDPOINT.format(code=spec.native_id)
        response = self.client.get(url, source=self.name)
        return RawResponse(
            body=response.content,
            ext="json",
            url=str(response.request.url),
            covers_from=None,
        )

    # ------------------------------------------------------------------ parse
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        """Decode the IPEA OData response into a ``(period, value)`` frame.

        ``VALDATA`` provides the period (date part only); ``VALVALOR`` may be ``null``,
        which becomes NaN.  An empty ``value`` list raises :class:`SourceError`.
        """
        if not raw.body:
            raise SourceError(f"ipeadata: {spec.native_id}: empty body")

        try:
            payload = json.loads(raw.body)
        except json.JSONDecodeError as exc:
            raise SourceError(f"ipeadata: {spec.native_id}: response is not JSON") from exc

        observations = payload.get("value", [])
        if not observations:
            raise SourceError(
                f"ipeadata: {spec.native_id}: IPEA returned an empty series; "
                "the code may not exist or the survey may have been discontinued"
            )

        rows: list[dict[str, object]] = []
        for obs in observations:
            period = _parse_ipea_date(obs["VALDATA"])
            val = obs.get("VALVALOR")
            value = float("nan") if val is None else float(val)
            rows.append({"period": period, "value": value})

        frame = pd.DataFrame(rows)
        return frame.sort_values("period").reset_index(drop=True)
