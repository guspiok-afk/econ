"""Banco Central do Brasil — SGS (Sistema Gerenciador de Séries Temporais)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, Source, SourceError, register
from econbase.sources.http import Client, date_windows, to_float

ENDPOINT = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{native_id}/dados"


def _parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%d/%m/%Y").date()
    except (ValueError, TypeError) as exc:
        raise SourceError(f"bcb_sgs: invalid date {value!r}") from exc


@register
class BcbSgsSource(Source):
    """Connector for Banco Central do Brasil SGS time series."""

    name = "bcb_sgs"

    def __init__(self, settings: Settings | None = None, client: Client | None = None) -> None:
        super().__init__(settings)
        self._client = client

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = Client(self.settings)
        return self._client

    def is_windowed(self, spec: SeriesSpec) -> bool:
        if "windowed" in spec.params:
            return bool(spec.params["windowed"])
        return spec.freq in ("D", "B")

    def fetch_raw(self, spec: SeriesSpec, since: dt.date | None = None) -> RawResponse:
        windowed = self.is_windowed(spec)
        url = ENDPOINT.format(native_id=spec.native_id)

        if not windowed:
            response = self.client.get(url, params={"formato": "json"}, source=self.name)
            return RawResponse(
                body=response.content, ext="json", url=str(response.request.url), covers_from=None
            )

        # Windowed fetch for daily / business-day series
        window_years = int(spec.params.get("window_years", 10))
        if since is not None:
            start_date = since
            covers_from = since
        else:
            start_raw = spec.params.get("start", "1980-01-01")
            if isinstance(start_raw, dt.date):
                start_date = start_raw
            else:
                start_date = dt.date.fromisoformat(str(start_raw))
            covers_from = None

        today = dt.date.today()
        windows = [] if start_date > today else date_windows(start_date, today, years=window_years)

        bodies: list[bytes] = []
        last_url = url
        for w_start, w_end in windows:
            params = {
                "formato": "json",
                "dataInicial": w_start.strftime("%d/%m/%Y"),
                "dataFinal": w_end.strftime("%d/%m/%Y"),
            }
            response = self.client.get(url, params=params, source=self.name, allow_status={404})
            last_url = str(response.request.url)
            if response.status_code == 200:
                bodies.append(response.content)

        if len(bodies) == 1:
            body = bodies[0]
        elif bodies:
            body = b"[" + b",".join(bodies) + b"]"
        else:
            body = b"[]"

        return RawResponse(body=body, ext="json", url=last_url, covers_from=covers_from)

    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        if not raw.body:
            raise SourceError(f"bcb_sgs: {spec.native_id}: empty body")
        try:
            payload = json.loads(raw.body)
        except json.JSONDecodeError as exc:
            raise SourceError(f"bcb_sgs: {spec.native_id}: response is not JSON: {exc}") from exc

        # Accept both shapes: a list of observations, or a list of lists (windowed)
        if not isinstance(payload, list):
            raise SourceError(f"bcb_sgs: {spec.native_id}: expected JSON array in response")

        items: list[dict[str, Any]] = []
        for elem in payload:
            if isinstance(elem, list):
                for sub_elem in elem:
                    if not isinstance(sub_elem, dict):
                        raise SourceError(
                            f"bcb_sgs: {spec.native_id}: observation row is not a dict"
                        )
                    items.append(sub_elem)
            elif isinstance(elem, dict):
                items.append(elem)
            else:
                raise SourceError(
                    f"bcb_sgs: {spec.native_id}: element in JSON array is not dict or list"
                )

        rows: list[dict[str, Any]] = []
        for row in items:
            if "data" not in row or "valor" not in row:
                raise SourceError(
                    f"bcb_sgs: {spec.native_id}: missing 'data' or 'valor' key in row {row}"
                )
            period = _parse_date(row["data"])
            val = to_float(row["valor"])
            rows.append({"period": period, "value": val})

        if not rows:
            return pd.DataFrame(columns=["period", "value"])

        frame = pd.DataFrame(rows)
        return frame.sort_values("period").reset_index(drop=True)
