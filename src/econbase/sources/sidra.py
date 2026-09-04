"""IBGE SIDRA — tables from Brazil's census bureau (IPCA, GDP, unemployment, …).

The centrepiece of this connector is the period-code ambiguity: SIDRA returns the same six
digits (e.g. ``202403``) for both a month (March 2024) and a quarter (Q3 2024). Only the
series ``freq`` from the catalog resolves this, and the connector refuses to guess: parsing
a quarterly table with a monthly frequency raises :class:`SourceError` instead of silently
misdating an entire series.

``native_id`` is ``"{table}/{variable}"``, e.g. ``1737/63`` for the IPCA monthly change.
The ``params`` dict may carry ``territory``, ``classifications`` and ``periods``.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, Source, SourceError, register
from econbase.sources.http import Client, to_float

ENDPOINT = "https://apisidra.ibge.gov.br/values"

#: Header labels that mark the period column across SIDRA's various surveys.
_PERIOD_LABELS = ("Mês", "Trimestre", "Trimestre Móvel", "Ano")


def _find_period_column(header: dict[str, str]) -> str:
    """Identify the code column whose label names a time dimension.

    The period column ends in ``C`` (the code column, not the ``N`` label column) and its
    header value starts with one of the known temporal labels.  This is necessary because
    tables with extra dimensions (sector, CNAE activity, …) shift the position.
    """
    for key, label in header.items():
        if not key.endswith("C"):
            continue
        for prefix in _PERIOD_LABELS:
            if label.startswith(prefix):
                return key
    raise SourceError(
        f"sidra: cannot find a period column in header keys {list(header.keys())}; "
        f"expected one ending in 'C' whose label starts with {_PERIOD_LABELS}"
    )


def _parse_period_code(code: str, freq: str) -> dt.date:
    """Convert a SIDRA period code to the contract's period-start date.

    Rules, derived from live responses recorded on 2026-09-04:

    * ``M`` (monthly, including "trimestre móvel"): ``YYYYMM`` → first day of that month.
    * ``Q`` (quarterly): ``YYYYQ`` where Q ∈ {01,02,03,04} → first day of that quarter.
    * ``A`` (annual): ``YYYY`` → 1 January.

    Raises :class:`SourceError` when the code does not match the shape its frequency
    requires, so that a quarterly table can never be silently read as monthly.
    """
    try:
        if freq == "M":
            if len(code) != 6:
                raise ValueError(f"expected 6 digits for monthly, got {code!r}")
            year, month = int(code[:4]), int(code[4:6])
            return dt.date(year, month, 1)

        if freq == "Q":
            if len(code) != 6:
                raise ValueError(f"expected 6 digits for quarterly, got {code!r}")
            year, quarter = int(code[:4]), int(code[4:6])
            if quarter < 1 or quarter > 4:
                raise ValueError(f"quarter {quarter} out of range 1-4 in {code!r}")
            month = (quarter - 1) * 3 + 1
            return dt.date(year, month, 1)

        if freq == "A":
            if len(code) != 4:
                raise ValueError(f"expected 4 digits for annual, got {code!r}")
            return dt.date(int(code), 1, 1)

    except (ValueError, OverflowError) as exc:
        raise SourceError(f"sidra: period code {code!r} with freq={freq}: {exc}") from exc

    raise SourceError(f"sidra: unsupported frequency {freq!r} for period parsing")


@register
class SidraSource(Source):
    """Connector for IBGE's SIDRA API (``sidra:1737/63``, ``sidra:1620/583``, …)."""

    name = "sidra"

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
        """Fetch the full history of a SIDRA table/variable in one request.

        ``since`` is ignored: the whole history is a single cheap request (the IPCA is
        137 KB), and ``covers_from`` is ``None`` so the pipeline treats it as complete.
        """
        table, variable = spec.native_id.split("/", 1)
        territory = spec.params.get("territory", "n1/all")
        periods = spec.params.get("periods", "all")
        classifications = spec.params.get("classifications")

        url = f"{ENDPOINT}/t/{table}/{territory}/v/{variable}/p/{periods}"
        if classifications:
            url = f"{url}/{classifications}"

        response = self.client.get(url, source=self.name)
        return RawResponse(
            body=response.content,
            ext="json",
            url=str(response.request.url),
            covers_from=None,
        )

    # ------------------------------------------------------------------ parse
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        """Decode the SIDRA JSON response into a ``(period, value)`` frame.

        The first element of the response is a header map (keys → human labels); the
        observations start at index 1. The period column is identified dynamically from
        the header, and the period code is interpreted using the series ``freq``.
        """
        if not raw.body:
            raise SourceError(f"sidra: {spec.native_id}: empty body")

        text = raw.body.decode("utf-8")

        # A 400 response from SIDRA is plain text, not JSON
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceError(
                f"sidra: {spec.native_id}: response is not JSON: {text[:200]}"
            ) from exc

        if not isinstance(payload, list) or len(payload) < 1:
            raise SourceError(
                f"sidra: {spec.native_id}: expected a JSON list, got {type(payload).__name__}"
            )

        header = payload[0]
        if not isinstance(header, dict) or "V" not in header:
            raise SourceError(
                f"sidra: {spec.native_id}: first element is not the expected header map"
            )

        period_col = _find_period_column(header)

        rows: list[dict[str, object]] = []
        for obs in payload[1:]:
            code = obs.get(period_col, "")
            period = _parse_period_code(str(code), spec.freq)
            value = to_float(obs.get("V"))
            rows.append({"period": period, "value": value})

        if not rows:
            return pd.DataFrame(columns=["period", "value"])

        frame = pd.DataFrame(rows)
        return frame.sort_values("period").reset_index(drop=True)
