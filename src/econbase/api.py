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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa

from econbase import schemas, transforms
from econbase.catalog import Catalog, SeriesSpec
from econbase.settings import Settings, get_settings
from econbase.store import Store
from econbase.vintages import VINTAGE_KINDS, VintageError, availability, pseudo_asof


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


#: Coarseness order, so a ragged panel can tell "quarterly onto monthly" (keep the holes) from
#: "daily onto monthly" (still aggregate). Equal ranks are not coarser than one another.
_COARSENESS: dict[str, int] = {"D": 0, "B": 0, "W": 1, "M": 2, "Q": 3, "A": 4}


def _coarser_than(series_freq: str, grid_freq: str) -> bool:
    """Is ``series_freq`` a longer period than ``grid_freq``?"""
    left = _COARSENESS.get(series_freq)
    right = _COARSENESS.get(grid_freq)
    if left is None or right is None:
        raise ApiError(f"cannot compare frequencies {series_freq!r} and {grid_freq!r}")
    return left > right


class Api:
    """Read access to one store through one catalog."""

    def __init__(self, store: Store, catalog: Catalog) -> None:
        self.store = store
        self.catalog = catalog
        #: Which notion of "as of" each series last resolved under, for a result's diagnostics.
        self._last_kind: dict[str, str] = {}

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
    def _observations(
        self, key: Key, asof: dt.date | None, vintage_kind: str = "true"
    ) -> pd.DataFrame:
        """The rows for one series, as of a date, under one notion of "as of"."""
        if vintage_kind not in VINTAGE_KINDS:
            raise ApiError(f"vintage_kind must be one of {VINTAGE_KINDS}, not {vintage_kind!r}")
        if asof is None or vintage_kind == "latest":
            table = self.store.observations([key.series_id], asof=None)
            frame = schemas.to_pandas(table)
            frame = frame[frame["realtime_end"].isna()] if len(frame) else frame
            self._last_kind[key.series_id] = "latest"
            return frame[["period", "value"]].sort_values("period").reset_index(drop=True)

        # include_history, not asof=None: the latter returns only the current value of each
        # period, so every row carries the same open interval and no count of them could ever
        # reveal a revision.
        every = schemas.to_pandas(self.store.observations([key.series_id], include_history=True))
        have = availability(every, key.spec)
        kind = vintage_kind
        if kind == "mixed":
            kind = have.usable_kind

        if kind == "true":
            frame = schemas.to_pandas(self.store.observations([key.series_id], asof=asof))
            # An empty answer is honest when the source itself had published nothing yet — a
            # series with real vintages knows its own first release. It is an artefact when the
            # series has no vintages at all and the only date on record is the day this project
            # happened to collect it.
            artefact = (
                not have.has_true_vintages
                and not every.empty
                and have.earliest_known is not None
                and asof < have.earliest_known
            )
            if frame.empty and artefact:
                raise VintageError(
                    f"{key.series_id} has no recorded history before {have.earliest_known}: this "
                    f"project began collecting it then, so asking as of {asof} returns nothing. "
                    "Use vintage_kind='pseudo' to simulate from the publication lag, or "
                    "'mixed' to take real vintages where they exist and simulate elsewhere."
                )
        else:
            frame = pseudo_asof(every, key.spec, asof)

        self._last_kind[key.series_id] = kind
        return frame[["period", "value"]].sort_values("period").reset_index(drop=True)

    def get(
        self,
        key: str,
        *,
        entity: str | None = None,
        start: dt.date | str | None = None,
        end: dt.date | str | None = None,
        asof: dt.date | str | None = None,
        vintage_kind: str = "true",
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
        frame = self._observations(resolved, asof_date, vintage_kind)

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
        keys: Iterable[str | tuple[str, str]],
        *,
        entity: str | None = None,
        entities: Sequence[str] | None = None,
        start: dt.date | str | None = None,
        end: dt.date | str | None = None,
        asof: dt.date | str | None = None,
        vintage_kind: str = "true",
        freq: str | None = None,
        agg: str | None = None,
        transform: str | None = None,
        how: str = "outer",
        mixed_freq: bool = False,
    ) -> pd.DataFrame:
        """Several series aligned on one period index, one column each.

        A key is a concept, a series id, or a ``(concept, entity)`` pair. The pair form is what
        a model spanning two countries needs: uncovered parity wants the exchange rate and the
        policy rate for Brazil and the policy rate for the United States, which is neither the
        cross product ``entities`` builds — no series carries ``fx_spot_usd`` for the United
        States — nor the single-country form. A pair always names its column ``concept@entity``.

        With ``entities`` the same concepts are fetched for each country and the columns are
        named ``concept@entity``; otherwise a column takes the concept's name, or the series id
        when the series carries no concept.

        The index is a ``DatetimeIndex``: models resample, filter and shift on it, and every
        test fixture in this repository parses its dates, so returning anything else would mean
        validating a model against one kind of index and running it on another.

        ``mixed_freq`` is the one deliberate exception to the rule that a panel has a frequency.
        Normally a quarterly series asked for on a monthly grid is refused, because interpolating
        between quarters is a modelling choice and not a conversion. A mixed-frequency model is
        precisely the place where that choice is made — with a state space rather than with a
        straight line — so it needs the quarterly figures placed on the monthly grid and the
        eleven months in between left **empty**. Setting the flag does exactly that: every series
        keeps its native periods, nothing is aggregated and nothing is filled, and the result is
        a ragged panel of holes that the model is expected to know how to read. It requires an
        explicit ``freq``, since the grid is no longer inferable from the data.
        """
        wanted = list(keys)
        if not wanted:
            raise ApiError("get_panel needs at least one key")
        if mixed_freq and freq is None:
            raise ApiError(
                "mixed_freq needs an explicit freq: it names the grid the ragged panel sits on, "
                "and with several frequencies present there is nothing to infer it from"
            )
        if mixed_freq and agg is not None:
            raise ApiError("mixed_freq places series on their native periods, so agg cannot apply")
        pairs = [k for k in wanted if isinstance(k, tuple)]
        if pairs and entities:
            raise ApiError(
                "pass either (concept, entity) pairs or `entities`, not both: "
                f"{[f'{c}@{e}' for c, e in pairs]} already name their entity"
            )
        targets: list[tuple[str, str | None, str]] = []
        if entities:
            for ent in entities:
                for k in wanted:
                    targets.append((str(k), ent, f"{k}@{ent}"))
        else:
            for k in wanted:
                if isinstance(k, tuple):
                    concept, ent = k
                    targets.append((concept, ent, f"{concept}@{ent}"))
                    continue
                resolved = self.resolve(k, entity)
                targets.append((k, entity, resolved.label))

        columns: dict[str, pd.Series] = {}
        for key, ent, label in targets:
            # one panel mixes frequencies, so the aggregation only travels to the series that
            # are actually being converted; `get` still rejects a pointless agg on its own
            resolved = self.resolve(key, ent)
            # only a series *coarser* than the grid keeps its native periods. A finer one still
            # has to be aggregated: left alone it would land on dates that are not grid points
            # and the reindex below would drop it without a word.
            coarser = mixed_freq and _coarser_than(resolved.spec.freq, str(freq))
            needs_agg = freq is not None and freq != resolved.spec.freq
            frame = self.get(
                key,
                entity=ent,
                asof=asof,
                vintage_kind=vintage_kind,
                # a ragged panel keeps the coarse series exactly as published
                freq=None if coarser else freq,
                agg=None if coarser else (agg if needs_agg else None),
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
        panel.index = pd.DatetimeIndex(panel.index)
        if mixed_freq:
            # the union of monthly and quarterly periods is not a complete monthly grid: a
            # quarter the monthly series do not reach would leave a hole, and a model that
            # counts periods would silently count wrong
            rule = transforms._PANDAS_RULE.get(str(freq))
            if rule is None:
                raise ApiError(f"unknown freq {freq!r} for a mixed-frequency panel")
            grid = pd.date_range(panel.index.min(), panel.index.max(), freq=rule)
            off_grid = panel.loc[panel.index.difference(grid)]
            if off_grid.notna().to_numpy().any():
                raise ApiError(
                    f"{int(off_grid.notna().to_numpy().sum())} observation(s) fall off the "
                    f"{freq} grid and would be dropped silently by a ragged panel"
                )
            panel = panel.reindex(grid)
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
    """Cut the panel to a date window.

    The bounds arrive as plain dates and the index holds Timestamps. Pandas refuses to compare
    the two rather than guessing, which is the right call and is why this converts the bound
    instead of walking the index — the previous version compared element by element and worked
    only while the index carried date objects.
    """
    if start is not None:
        panel = panel[panel.index >= pd.Timestamp(start)]
    if end is not None:
        panel = panel[panel.index <= pd.Timestamp(end)]
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
