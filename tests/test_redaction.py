"""Secrets must never reach the tables the pipeline persists."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from econbase import pipeline, schemas
from econbase.catalog import Catalog
from econbase.sources.base import FetchResult, Source
from econbase.store import Store

T1 = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
KEY = "abcdef0123456789abcdef0123456789"


class LeakySource(Source):
    """Puts the key in the URL (like FRED does) and in an exception message."""

    name = "static"

    def fetch(self, spec, since=None) -> FetchResult:
        if spec.native_id == "selic":
            raise RuntimeError(
                f"HTTP 500 for https://x/api?series=selic&api_key={KEY}&file_type=json"
            )
        frame = pd.DataFrame({"period": [dt.date(2026, 1, 1)], "value": [1.0]})
        return FetchResult(
            frame=frame,
            raw_body=b"{}",
            raw_ext="js/../on",
            url=f"https://api.stlouisfed.org/fred/series/observations?series_id=X&api_key={KEY}",
        )


def test_redact_masks_credential_parameters() -> None:
    assert pipeline.redact(f"https://h/p?api_key={KEY}&x=1") == "https://h/p?api_key=REDACTED&x=1"
    assert pipeline.redact(f"token={KEY}") == "token=REDACTED"
    assert pipeline.redact("https://h/p?series_id=CPIAUCSL") == "https://h/p?series_id=CPIAUCSL"
    assert pipeline.redact(None) is None


def test_persisted_tables_never_contain_the_key(store: Store, catalog: Catalog) -> None:
    summary = pipeline.update(
        store,
        catalog,
        {"static": LeakySource()},
        now=T1,
        tz="UTC",
        series_ids=["static:ipca", "static:selic"],
    )
    assert summary.n_errors == 1
    for table in ("raw_index", "run_series", "runs", "series"):
        text = schemas.to_pandas(store.read(table)).to_string()
        assert KEY not in text, table
    raw = schemas.to_pandas(store.read("raw_index"))
    assert raw.loc[0, "url"].endswith("api_key=REDACTED")
    # the raw extension is sanitized before it becomes a file name ("js/../on" -> "json")
    assert raw.loc[0, "path"].endswith(".json.gz")
    assert ".." not in raw.loc[0, "path"]
    assert (store.raw_dir / raw.loc[0, "path"]).exists()
    err = next(o.error for o in summary.outcomes if o.error)
    assert "api_key=REDACTED" in err and KEY not in err
