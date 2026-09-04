"""Banco Central do Brasil — Focus market expectations survey (Olinda OData API)."""

from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.settings import Settings
from econbase.sources.base import RawResponse, Source, SourceError, register
from econbase.sources.http import Client, odata_query, to_float

BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"


@register
class BcbFocusSource(Source):
    """Connector for Banco Central do Brasil Focus market expectations survey."""

    name = "bcb_focus"

    def __init__(self, settings: Settings | None = None, client: Client | None = None) -> None:
        super().__init__(settings)
        self._client = client

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = Client(self.settings)
        return self._client

    def fetch_raw(self, spec: SeriesSpec, since: dt.date | None = None) -> RawResponse:
        if "/" not in spec.native_id:
            raise SourceError(
                "bcb_focus: native_id must be in format 'Resource/Indicador', "
                f"got {spec.native_id!r}"
            )

        resource, indicador = spec.native_id.split("/", 1)
        url_path = f"{BASE}/{resource}"

        filter_parts = [f"Indicador eq '{indicador}'"]

        if since is not None:
            start_date = since
        else:
            start_raw = spec.params.get("start", "2000-01-01")
            if isinstance(start_raw, dt.date):
                start_date = start_raw
            else:
                start_date = dt.date.fromisoformat(str(start_raw))

        filter_parts.append(f"Data ge '{start_date.isoformat()}'")

        if "suavizada" in spec.params:
            filter_parts.append(f"Suavizada eq '{spec.params['suavizada']}'")
        elif "12Meses" in resource or "24Meses" in resource:
            filter_parts.append("Suavizada eq 'N'")

        if "data_referencia" in spec.params:
            filter_parts.append(f"DataReferencia eq '{spec.params['data_referencia']}'")

        if "base_calculo" in spec.params:
            filter_parts.append(f"baseCalculo eq {spec.params['base_calculo']}")
        else:
            filter_parts.append("baseCalculo eq 0")

        filter_str = " and ".join(filter_parts)

        top = 10000
        skip = 0
        pages: list[bytes] = []
        last_url = url_path

        while True:
            query = odata_query(
                **{
                    "$top": top,
                    "$skip": skip,
                    "$format": "json",
                    "$orderby": "Data",
                    "$filter": filter_str,
                }
            )
            full_url = f"{url_path}?{query}"
            self.client._wait_turn(self.name)
            response = self.client._client.get(full_url)
            if response.status_code >= 400:
                raise SourceError(
                    f"bcb_focus: HTTP {response.status_code} for {full_url}: {response.text[:200]}"
                )
            last_url = str(response.request.url)
            pages.append(response.content)

            try:
                payload = response.json()
            except Exception as exc:
                raise SourceError(
                    f"bcb_focus: {spec.native_id}: response is not JSON: {exc}"
                ) from exc

            if "codigo" in payload or "mensagem" in payload:
                msg = payload.get("mensagem") or payload.get("codigo") or str(payload)
                raise SourceError(f"bcb_focus: {spec.native_id}: {msg}")

            value_list = payload.get("value", [])
            if len(value_list) < top:
                break
            skip += top

        body = pages[0] if len(pages) == 1 else b"[" + b",".join(pages) + b"]"

        return RawResponse(body=body, ext="json", url=last_url, covers_from=None)

    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        if not raw.body:
            raise SourceError(f"bcb_focus: {spec.native_id}: empty body")

        try:
            payload = json.loads(raw.body)
        except json.JSONDecodeError as exc:
            raise SourceError(f"bcb_focus: {spec.native_id}: response is not JSON: {exc}") from exc

        items: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            if "codigo" in payload or "mensagem" in payload:
                msg = payload.get("mensagem") or payload.get("codigo") or str(payload)
                raise SourceError(f"bcb_focus: {spec.native_id}: {msg}")
            items = payload.get("value", [])
        elif isinstance(payload, list):
            for elem in payload:
                if isinstance(elem, dict):
                    if "codigo" in elem or "mensagem" in elem:
                        msg = elem.get("mensagem") or elem.get("codigo") or str(elem)
                        raise SourceError(f"bcb_focus: {spec.native_id}: {msg}")
                    if "value" in elem and isinstance(elem["value"], list):
                        items.extend(elem["value"])
                    else:
                        items.append(elem)
                elif isinstance(elem, list):
                    items.extend(elem)
        else:
            raise SourceError(f"bcb_focus: {spec.native_id}: unexpected JSON structure")

        statistic_name = str(spec.params.get("statistic", "Mediana"))
        rows: list[dict[str, Any]] = []

        for row in items:
            if not isinstance(row, dict):
                continue
            if "Data" not in row:
                raise SourceError(f"bcb_focus: {spec.native_id}: missing 'Data' in row {row}")
            try:
                period = dt.date.fromisoformat(str(row["Data"]))
            except ValueError as exc:
                raise SourceError(
                    f"bcb_focus: {spec.native_id}: invalid 'Data' value {row['Data']!r}"
                ) from exc

            raw_val = row.get(statistic_name)
            if raw_val is None:
                continue
            val = to_float(raw_val)
            if math.isnan(val):
                continue

            rows.append({"period": period, "value": val})

        if not rows:
            return pd.DataFrame(columns=["period", "value"])

        frame = pd.DataFrame(rows)
        return frame.sort_values("period").reset_index(drop=True)
