"""The connector contract.

A connector turns a :class:`~econbase.catalog.SeriesSpec` into a long frame of
``period, value`` (plus ``realtime_start``/``realtime_end`` when the source publishes
vintages) and hands back the raw HTTP body so the pipeline can archive it.
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


@dataclass(slots=True)
class FetchResult:
    """What a connector returns for one series.

    ``frame`` columns: ``period`` (date), ``value`` (float) and, for vintaged sources,
    ``realtime_start`` (date) and ``realtime_end`` (date or null). ``covers_from`` says from
    which period the frame is a complete picture: ``None`` means the whole history, so a
    period missing from the frame counts as removed by the source. A windowed fetch sets it
    to the first period in the window so nothing outside is touched.
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


class Source(ABC):
    """Base class for connectors. Subclasses set ``name`` and implement :meth:`fetch`."""

    name: ClassVar[str]

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    @abstractmethod
    def fetch(self, spec: SeriesSpec, since: dt.date | None = None) -> FetchResult:
        """Fetch the full history (or from ``since`` when the source supports windows)."""


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

    def fetch(self, spec: SeriesSpec, since: dt.date | None = None) -> FetchResult:
        if spec.series_id not in self.frames:
            raise KeyError(f"StaticSource has no frame for {spec.series_id}")
        frame = self.frames[spec.series_id].copy()
        body = json.dumps(
            frame.astype(str).to_dict(orient="records"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return FetchResult(
            frame=frame,
            raw_body=body,
            raw_ext="json",
            url=f"static://{spec.series_id}",
            covers_from=self.covers_from.get(spec.series_id),
        )
