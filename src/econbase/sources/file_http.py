import datetime as dt
import io

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.sources.base import RawResponse, Source, SourceError, register


@register
class FileHttpSource(Source):
    """Reads a published spreadsheet or CSV from a URL."""

    name = "file_http"

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
        url = spec.params.get("url")
        if not url:
            raise SourceError(f"Missing 'url' in params for {spec.native_id}")

        resp = self.client.get(url, source=self.name)
        return RawResponse(body=resp.content, ext="auto", covers_from=None)

    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        fmt = spec.params.get("format")
        if not fmt:
            if raw.body.startswith(b"PK"):
                fmt = "xlsx"
                engine = "openpyxl"
            elif raw.body.startswith(b"\xd0\xcf\x11\xe0"):
                fmt = "xls"
                engine = "xlrd"
            else:
                fmt = "csv"
                engine = None
        else:
            engine = "openpyxl" if fmt == "xlsx" else "xlrd" if fmt == "xls" else None

        skiprows = spec.params.get("skiprows", 0)
        sheet = spec.params.get("sheet", 0)
        date_col = spec.params.get("date_col", 0)
        value_col = spec.params.get("value_col", 1)
        date_format = spec.params.get("date_format")
        period_is_end = spec.params.get("period_is_end", False)

        body_io = io.BytesIO(raw.body)

        usecols = None
        if (isinstance(date_col, int) and isinstance(value_col, int)) or (
            isinstance(date_col, str) and isinstance(value_col, str)
        ):
            usecols = [date_col, value_col]

        header = None if isinstance(date_col, int) else 0

        if fmt in ("xls", "xlsx"):
            df = pd.read_excel(
                body_io,
                engine=engine,
                sheet_name=sheet,
                skiprows=skiprows,
                header=header,
                usecols=usecols,
            )
        else:
            df = pd.read_csv(
                body_io,
                skiprows=skiprows,
                header=header,
                usecols=usecols,
            )

        # Standardize column names based on indexes if they were integers
        if isinstance(date_col, int):
            date_col_name = df.columns[0]
            value_col_name = df.columns[1]
        else:
            date_col_name = date_col
            value_col_name = value_col

        df = df[[date_col_name, value_col_name]].copy()
        df.columns = ["period", "value"]

        # Drop rows missing date
        df = df.dropna(subset=["period"])

        # Convert date to datetime if it's not already
        if date_format:
            df["period"] = pd.to_datetime(df["period"], format=date_format).dt.date
        else:
            df["period"] = pd.to_datetime(df["period"]).dt.date

        # Convert value to float
        df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)

        # Shift period to start of month if requested
        if period_is_end:
            # We want to change the date to the first day of its month
            df["period"] = df["period"].apply(lambda d: d.replace(day=1))

        return df
