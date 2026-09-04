import datetime as dt
import json

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.sources.base import RawResponse, Source, SourceError, register

ENDPOINT = "https://api.db.nomics.world/v22/series/{native_id}"


@register
class DbnomicsSource(Source):
    """Client for DBnomics."""

    name = "dbnomics"

    def __init__(self, settings=None, client=None) -> None:
        super().__init__(settings)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from econbase.sources.http import Client

            self._client = Client(self.settings)
        return self._client

    def fetch_raw(self, spec: SeriesSpec, since: dt.date | None = None) -> RawResponse:
        url = ENDPOINT.format(native_id=spec.native_id)
        # The shared client raises SourceError on its own for 404s.
        resp = self.client.get(url, params={"observations": 1, "format": "json"}, source=self.name)
        return RawResponse(body=resp.content, ext="json", covers_from=None)

    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        data = json.loads(raw.body)
        docs = data.get("series", {}).get("docs", [])
        if not docs:
            raise SourceError(f"No series docs in DBnomics response for {spec.native_id}")

        doc = docs[0]
        freq = doc.get("@frequency")

        freq_map = {
            "annual": "A",
            "quarterly": "Q",
            "monthly": "M",
            "daily": "D",
        }

        if freq not in freq_map:
            raise SourceError(f"Unknown DBnomics @frequency: {freq}")

        if freq_map[freq] != spec.freq:
            raise SourceError(f"DBnomics frequency {freq} contradicts spec freq {spec.freq}")

        periods = doc.get("period", [])
        values = doc.get("value", [])

        parsed_periods = []
        for p in periods:
            if freq == "annual":
                parsed_periods.append(dt.date(int(p), 1, 1))
            elif freq == "quarterly":
                year, q = p.split("-Q")
                month = (int(q) - 1) * 3 + 1
                parsed_periods.append(dt.date(int(year), month, 1))
            elif freq == "monthly":
                year, month = p.split("-")
                parsed_periods.append(dt.date(int(year), int(month), 1))
            elif freq == "daily":
                parsed_periods.append(dt.date.fromisoformat(p))

        df = pd.DataFrame({"period": parsed_periods, "value": values})
        # Map JSON nulls to NaN implicitly by converting to float
        df["value"] = df["value"].astype(float)
        return df
