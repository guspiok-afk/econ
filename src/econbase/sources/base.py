"""The connector contract.

A connector is split in two so the pipeline can archive the bytes it received **before**
anything tries to interpret them (ADR-0002: a parsing bug must stay recoverable):

* :meth:`Source.fetch_raw` performs the request(s) and returns the exact bytes.
* :meth:`Source.parse` turns those bytes into a long frame of ``period, value``
  (plus ``realtime_start`` / ``realtime_end`` when the source publishes vintages).

:meth:`Source.fetch` combines both and exists for interactive use; the pipeline always calls
the two halves separately.
"""

from __future__ import annotations

import datetime as dt
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

import pandas as pd

from econbase.catalog import SeriesSpec
from econbase.settings import Settings


class SourceError(RuntimeError):
    """A connector could not obtain or interpret the data for one series."""


@dataclass(slots=True)
class RawResponse:
    """The bytes a connector received, before any interpretation.

    ``covers_from`` says from which period the response is a complete picture: ``None`` means
    the whole history, so a period missing from it counts as removed by the source. A windowed
    fetch sets it to the first period of the window, and the pipeline then refuses to touch
    anything outside that window (in either direction).
    """

    body: bytes | None = None
    ext: str = "json"
    url: str | None = None
    covers_from: dt.date | None = None
    fetched_at: dt.datetime | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class FetchResult:
    """A :class:`RawResponse` together with the frame parsed from it.

    ``frame`` columns: ``period`` (date), ``value`` (float) and, for vintaged sources,
    ``realtime_start`` (date) and ``realtime_end`` (date or ``None``).
    """

    frame: pd.DataFrame
    raw_body: bytes | None = None
    raw_ext: str = "json"
    url: str | None = None
    covers_from: dt.date | None = None
    fetched_at: dt.datetime | None = None
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def has_vintages(self) -> bool:
        return "realtime_start" in self.frame.columns

    @property
    def raw(self) -> RawResponse:
        return RawResponse(
            body=self.raw_body,
            ext=self.raw_ext,
            url=self.url,
            covers_from=self.covers_from,
            fetched_at=self.fetched_at,
            extra=self.extra,
        )


class Source(ABC):
    """Base class for connectors.

    Subclasses set ``name`` and implement :meth:`fetch_raw` and :meth:`parse`. Never do the
    parsing inside :meth:`fetch_raw`: the pipeline archives its result before parsing, so a
    parse failure must still leave the bytes on disk.
    """

    name: ClassVar[str]

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    @abstractmethod
    def fetch_raw(self, spec: SeriesSpec, since: dt.date | None = None) -> RawResponse:
        """Request the data and return the bytes received, unparsed."""

    @abstractmethod
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        """Turn ``raw`` into a long frame (``period``, ``value``[, ``realtime_*``])."""

    def fetch(self, spec: SeriesSpec, since: dt.date | None = None) -> FetchResult:
        """Convenience wrapper: :meth:`fetch_raw` then :meth:`parse`. Not used by the pipeline."""
        raw = self.fetch_raw(spec, since)
        return FetchResult(
            frame=self.parse(raw, spec),
            raw_body=raw.body,
            raw_ext=raw.ext,
            url=raw.url,
            covers_from=raw.covers_from,
            fetched_at=raw.fetched_at,
            extra=raw.extra,
        )


_REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    """Class decorator: make a connector available to :func:`build_registry`."""
    name = getattr(cls, "name", None)
    if not name:
        raise ValueError(f"{cls.__name__} must define a class attribute 'name'")
    _REGISTRY[name] = cls
    return cls


def available() -> dict[str, type[Source]]:
    """Registered connector classes by source name."""
    return dict(_REGISTRY)


class StaticSource(Source):
    """In-memory connector for tests, demos and derived-series experiments.

    ``frames`` maps ``series_id`` to a frame; swap frames between runs to simulate revisions.
    The frame is serialized to JSON as the "raw body" so the archive path is exercised too.
    """

    name = "static"

    def __init__(
        self,
        frames: dict[str, pd.DataFrame] | None = None,
        *,
        covers_from: dict[str, dt.date] | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(settings)
        self.frames: dict[str, pd.DataFrame] = dict(frames or {})
        self.covers_from: dict[str, dt.date] = dict(covers_from or {})

    def fetch_raw(self, spec: SeriesSpec, since: dt.date | None = None) -> RawResponse:
        if spec.series_id not in self.frames:
            raise SourceError(f"StaticSource has no frame for {spec.series_id}")
        frame = self.frames[spec.series_id]
        body = json.dumps(
            frame.astype(str).to_dict(orient="records"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return RawResponse(
            body=body,
            ext="json",
            url=f"static://{spec.series_id}",
            covers_from=self.covers_from.get(spec.series_id),
        )

    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame:
        return self.frames[spec.series_id].copy()
