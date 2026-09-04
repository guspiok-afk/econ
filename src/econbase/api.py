"""The read API: what analyses use, and the only surface `econmodels` may import.

Analyses ask for **concepts**, not series ids (`api.get("cpi_headline", entity="BR")`), so a
model written for Brazil runs on the United States by changing one argument. The catalog turns
the pair into the one series that carries that concept for that country.

The other half of the contract is `asof`. Passing it rebuilds the panel as it stood on that
date, using the vintage intervals the store keeps, and every transformation is then computed on
that panel. Nothing published later can leak into it, which is what makes a nowcasting backtest
worth running.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa

from econbase import schemas, transforms
from econbase.catalog import Catalog, SeriesSpec
from econbase.settings import Settings, get_settings
from econbase.store import Store


class ApiError(ValueError):
    """The request cannot be answered as asked."""


@dataclass(frozen=True, slots=True)
class Key:
    """What was asked for, resolved to a series."""

    spec: SeriesSpec
    concept: str | None
    entity: str

    @property
    def series_id(self) -> str:
        return self.spec.series_id

    @property
    def label(self) -> str:
        """Column name in a panel: the concept when there is one, else the series id."""
        return self.concept or self.spec.series_id


class Api:
    """Read access to one store through one catalog."""

    def __init__(self, store: Store, catalog: Catalog) -> None:
        self.store = store
        self.catalog = catalog

    # ------------------------------------------------------------------ resolution
    def resolve(self, key: str, entity: str | None = None) -> Key:
        """Turn a concept (with an entity) or a series id into a :class:`Key`."""
        if ":" in key:
            spec = self.catalog.get(key)
            if entity is not None and entity != spec.entity_id:
                raise ApiError(
                    f"{key} belongs to {spec.entity_id}, not {entity}; drop the entity argument"
                )
            return Key(spec, spec.concept_id, spec.entity_id)
        if entity is None:
            raise ApiError(f"asking for the concept {key!r} needs an entity, e.g. entity='BR'")
        if key not in self.catalog.concepts:
            known = ", ".join(sorted(self.catalog.concepts)[:8])
            raise ApiError(f"unknown concept {key!r}; some that exist: {known}, ...")
        try:
            spec = self.catalog.resolve(entity, key)
        except KeyError:
            have = sorted(e for (e, c) in self.catalog.concept_map if c == key)
            raise ApiError(
                f"no series carries {key!r} for {entity}"
                + (f"; it exists for {', '.join(have)}" if have else "")
            ) from None
        return Key(spec, key, entity)

    def concepts(self, entity: str | None = None) -> list[str]:
        """Concepts available, optionally restricted to those a country actually has."""
        if entity is None:
            return sorted(self.catalog.concepts)
        return sorted(c for (e, c) in self.catalog.concept_map if e == entity)

    def entities(self, concept: str | None = None) -> list[str]:
        """Countries available, optionally restricted to those carrying a concept."""
        if concept is None:
            return sorted(self.catalog.entities)
        return sorted(e for (e, c) in self.catalog.concept_map if c == concept)

    # ------------------------------------------------------------------ reading
    def _observations(self, key: Key, asof: dt.date | None) -> pd.DataFrame:
        table = self.store.observations([key.series_id], asof=asof)
        frame = schemas.to_pandas(table)[["period", "value"]]
        return frame.sort_values("period").reset_index(drop=True)

    def get(
        self,
        key: str,
        *,
        entity: str | None = None,
        start: dt.date | str | None = None,
        end: dt.date | str | None = None,
        asof: dt.date | str | None = None,
        freq: str | None = None,
        agg: str | None = None,
        transform: str | None = None,
        as_pandas: bool = True,
    ) -> pd.DataFrame | pa.Table:
        """One series as a ``period``/``value`` frame.

        Order of operations, which matters: read as of the requested date, convert the
        frequency, apply the transformation, then trim to ``start``/``end``. Trimming last means
        a year-over-year change at the start of the window is computed from the observation a
        year earlier rather than silently coming back empty.
        """
        resolved = self.resolve(key, entity)
        asof_date = _as_date(asof, "asof")
        frame = self._observations(resolved, asof_date)

        source_freq = resolved.spec.freq
        out_freq = freq or source_freq
        if out_freq != source_freq:
            chosen = agg or self._default_agg(resolved)
            frame = transforms.resample(frame, from_freq=source_freq, to_freq=out_freq, agg=chosen)
        elif agg is not None:
            raise ApiError("agg only applies when freq changes the frequency")

        if transform:
            frame = transforms.apply(frame, transform, freq=out_freq)

        frame = _trim(frame, _as_date(start, "start"), _as_date(end, "end"))
        if as_pandas:
            return frame.reset_index(drop=True)
        return pa.Table.from_pandas(frame.reset_index(drop=True), preserve_index=False)

    def _default_agg(self, key: Key) -> str:
        if key.concept and key.concept in self.catalog.concepts:
            return self.catalog.concepts[key.concept].default_agg
        raise ApiError(
            f"{key.series_id} has no concept, so the aggregation cannot be guessed; pass agg="
        )

    def get_panel(
        self,
        keys: Iterable[str],
        *,
        entity: str | None = None,
        entities: Sequence[str] | None = None,
        start: dt.date | str | None = None,
        end: dt.date | str | None = None,
        asof: dt.date | str | None = None,
        freq: str | None = None,
        agg: str | Mapping[str, str] | None = None,
        transform: str | None = None,
        how: str = "outer",
    ) -> pd.DataFrame:
        """Several series aligned on one period index, one column each.

        With ``entities`` the same concepts are fetched for each country and the columns are
        named ``concept@entity``; otherwise a column takes the concept's name, or the series id
        when the series carries no concept.

        ``agg`` accepts a mapping from key to aggregation as well as a single string. Prefer
        the mapping, or nothing at all: a panel mixes a price change, a policy rate and an
        index, and one aggregation cannot be right for all three. Left out, each concept uses
        the aggregation its catalog entry declares.
        """
        wanted = list(keys)
        if not wanted:
            raise ApiError("get_panel needs at least one key")
        targets: list[tuple[str, str | None, str]] = []
        if entities:
            for ent in entities:
                for k in wanted:
                    targets.append((k, ent, f"{k}@{ent}"))
        else:
            for k in wanted:
                resolved = self.resolve(k, entity)
                targets.append((k, entity, resolved.label))

        columns: dict[str, pd.Series] = {}
        for key, ent, label in targets:
            # one panel mixes frequencies, so the aggregation only travels to the series that
            # are actually being converted; `get` still rejects a pointless agg on its own
            resolved = self.resolve(key, ent)
            needs_agg = freq is not None and freq != resolved.spec.freq
            chosen = agg.get(key) if isinstance(agg, dict) else agg
            frame = self.get(
                key,
                entity=ent,
                asof=asof,
                freq=freq,
                agg=chosen if needs_agg else None,
                transform=transform,
                as_pandas=True,
            )
            columns[label] = pd.Series(
                frame["value"].to_numpy(dtype="float64"),
                index=pd.DatetimeIndex(pd.to_datetime(frame["period"])),
                name=label,
            )
        panel = pd.concat(columns.values(), axis=1, join="inner" if how == "inner" else "outer")
        panel = panel.sort_index()
        panel.index = pd.DatetimeIndex(panel.index).date
        panel.index.name = "period"
        return _trim_index(panel, _as_date(start, "start"), _as_date(end, "end"))

    # ------------------------------------------------------------------ metadata
    def series(self) -> pa.Table:
        """The catalog as the store recorded it, including coverage and last update."""
        return self.store.read("series")

    def describe(self, key: str, entity: str | None = None) -> dict[str, object]:
        """Everything worth knowing about one series before using it in a model."""
        resolved = self.resolve(key, entity)
        stored = schemas.to_pandas(self.store.read("series"))
        row = stored[stored["series_id"] == resolved.series_id]
        info: dict[str, object] = {
            "series_id": resolved.series_id,
            "concept_id": resolved.concept,
            "entity_id": resolved.entity,
            "title": resolved.spec.title,
            "unit": resolved.spec.unit,
            "freq": resolved.spec.freq,
            "seasonal_adj": resolved.spec.seasonal_adj,
            "source": resolved.spec.source,
            "source_url": resolved.spec.source_url,
            "license": resolved.spec.license,
            "redistributable": resolved.spec.redistributable,
            "expected_lag_days": resolved.spec.expected_lag_days,
        }
        if not row.empty:
            info |= {
                "first_period": row.iloc[0]["first_period"],
                "last_period": row.iloc[0]["last_period"],
                "last_updated": row.iloc[0]["last_updated"],
            }
        return info

    def vintages(self, key: str, entity: str | None = None) -> pd.DataFrame:
        """Every reading ever stored for a series: the audit trail behind ``asof``."""
        resolved = self.resolve(key, entity)
        table = self.store.observations([resolved.series_id], include_history=True)
        return schemas.to_pandas(table).sort_values(["period", "realtime_start"])


# ---------------------------------------------------------------------------- helpers
def _as_date(value: dt.date | str | None, label: str) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        raise ApiError(f"{label} must be an ISO date, got {value!r}") from None


def _trim(frame: pd.DataFrame, start: dt.date | None, end: dt.date | None) -> pd.DataFrame:
    if start is not None:
        frame = frame[frame["period"] >= start]
    if end is not None:
        frame = frame[frame["period"] <= end]
    return frame


def _trim_index(panel: pd.DataFrame, start: dt.date | None, end: dt.date | None) -> pd.DataFrame:
    if start is not None:
        panel = panel[[d >= start for d in panel.index]]
    if end is not None:
        panel = panel[[d <= end for d in panel.index]]
    return panel


def connect(
    catalog_dir: Path | str = "catalog",
    *,
    data_dir: Path | str | None = None,
    settings: Settings | None = None,
) -> Api:
    """Open the store and the catalog with the project's settings."""
    settings = settings or get_settings()
    return Api(Store(data_dir or settings.data_dir), Catalog.load(catalog_dir))
