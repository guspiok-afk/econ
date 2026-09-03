"""Declarative catalog: YAML in, validated specs out.

Layout under the catalog root::

    concepts.yaml            # concept definitions (analysis-facing keys)
    entities.yaml            # countries (and later instruments)
    <group>/<source>.yaml    # one file per source: {source, defaults, series: [...]}

Identifier grammar is documented in ``docs/IDENTIFIERS.md`` and enforced here.
"""

from __future__ import annotations

import hashlib
import json
import re
import warnings
from collections.abc import Iterable
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from econbase import schemas

SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NATIVE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./\-]*$")
SERIES_ID_RE = re.compile(r"^[a-z][a-z0-9_]*:[A-Za-z0-9][A-Za-z0-9_./\-]*$")
CONCEPT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ENTITY_RE = re.compile(r"^[A-Z]{2}$|^[a-z][a-z0-9_]*:[A-Za-z0-9._\-]+$")

Frequency = Literal["D", "B", "W", "M", "Q", "A"]
Aggregation = Literal["last", "mean", "sum", "eop"]
EntityType = Literal["country", "instrument", "issuer", "index", "region"]


class CatalogError(ValueError):
    """The catalog violates a structural rule (duplicate ids, undefined concept, ...)."""


def path_safe(series_id: str) -> str:
    """Filesystem-safe form of a series id (``sidra:1737/2266`` -> ``sidra__1737__2266``)."""
    return series_id.replace(":", "__").replace("/", "__")


class SeriesSpec(BaseModel):
    """One catalog entry. ``series_id`` is derived and immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    native_id: str
    entity_id: str
    title: str
    freq: Frequency
    concept_id: str | None = None
    unit: str = ""
    scale: float = 1.0
    seasonal_adj: bool = False
    calendar: str | None = None
    source_url: str | None = None
    license: str = "unknown"
    redistributable: bool = False
    aliases: tuple[str, ...] = ()
    method_version: str | None = None
    expected_lag_days: int | None = Field(default=None, ge=0)
    table: Literal["observations"] = "observations"
    domain: str = "macro"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        if not SOURCE_RE.match(v):
            raise ValueError(f"source {v!r} must match {SOURCE_RE.pattern}")
        return v

    @field_validator("native_id", mode="before")
    @classmethod
    def _native_id(cls, v: object) -> str:
        s = str(v)
        if not NATIVE_ID_RE.match(s):
            raise ValueError(f"native_id {s!r} must match {NATIVE_ID_RE.pattern}")
        return s

    @field_validator("entity_id")
    @classmethod
    def _entity(cls, v: str) -> str:
        if not ENTITY_RE.match(v):
            raise ValueError(f"entity_id {v!r} must match {ENTITY_RE.pattern}")
        return v

    @field_validator("concept_id")
    @classmethod
    def _concept(cls, v: str | None) -> str | None:
        if v is not None and not CONCEPT_RE.match(v):
            raise ValueError(f"concept_id {v!r} must match {CONCEPT_RE.pattern}")
        return v

    @field_validator("aliases", mode="before")
    @classmethod
    def _aliases(cls, v: object) -> tuple[str, ...]:
        if v is None:
            return ()
        items = tuple(str(a) for a in v)
        for a in items:
            if not SERIES_ID_RE.match(a):
                raise ValueError(f"alias {a!r} must be a series id ({SERIES_ID_RE.pattern})")
        return items

    @computed_field  # type: ignore[prop-decorator]
    @property
    def series_id(self) -> str:
        return f"{self.source}:{self.native_id}"


class ConceptSpec(BaseModel):
    """Analysis-facing concept definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str
    description: str
    unit_kind: str = "level"
    default_agg: Aggregation = "last"

    @field_validator("concept_id")
    @classmethod
    def _concept(cls, v: str) -> str:
        if not CONCEPT_RE.match(v):
            raise ValueError(f"concept_id {v!r} must match {CONCEPT_RE.pattern}")
        return v


class EntitySpec(BaseModel):
    """A country today, an instrument tomorrow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str
    entity_type: EntityType
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_id")
    @classmethod
    def _entity(cls, v: str) -> str:
        if not ENTITY_RE.match(v):
            raise ValueError(f"entity_id {v!r} must match {ENTITY_RE.pattern}")
        return v


class _SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    defaults: dict[str, Any] = Field(default_factory=dict)
    series: list[dict[str, Any]] = Field(default_factory=list)


class Catalog:
    """Validated, immutable view of the catalog directory."""

    def __init__(
        self,
        series: Iterable[SeriesSpec],
        concepts: Iterable[ConceptSpec] = (),
        entities: Iterable[EntitySpec] = (),
        root: Path | None = None,
    ) -> None:
        self.root = root
        self.concepts: dict[str, ConceptSpec] = {c.concept_id: c for c in concepts}
        self.entities: dict[str, EntitySpec] = {e.entity_id: e for e in entities}
        self.series: dict[str, SeriesSpec] = {}
        self._aliases: dict[str, str] = {}
        self._by_concept: dict[tuple[str, str], str] = {}
        for spec in series:
            self._add(spec)

    # ------------------------------------------------------------------ building
    def _add(self, spec: SeriesSpec) -> None:
        sid = spec.series_id
        if sid in self.series:
            raise CatalogError(f"duplicate series_id {sid!r}")
        if sid in self._aliases:
            raise CatalogError(
                f"series_id {sid!r} is already used as an alias of {self._aliases[sid]!r}"
            )
        if spec.entity_id not in self.entities:
            if re.fullmatch(r"[A-Z]{2}", spec.entity_id):
                self.entities[spec.entity_id] = EntitySpec(
                    entity_id=spec.entity_id, entity_type="country", name=spec.entity_id
                )
            else:
                raise CatalogError(
                    f"{sid}: entity {spec.entity_id!r} is not defined in entities.yaml"
                )
        if spec.concept_id is not None:
            if spec.concept_id not in self.concepts:
                raise CatalogError(
                    f"{sid}: concept {spec.concept_id!r} is not defined in concepts.yaml"
                )
            key = (spec.entity_id, spec.concept_id)
            if key in self._by_concept:
                raise CatalogError(
                    f"({spec.entity_id}, {spec.concept_id}) is mapped twice: "
                    f"{self._by_concept[key]!r} and {sid!r}"
                )
            self._by_concept[key] = sid
        for alias in spec.aliases:
            if alias in self.series:
                raise CatalogError(f"{sid}: alias {alias!r} collides with an existing series_id")
            if alias in self._aliases and self._aliases[alias] != sid:
                raise CatalogError(
                    f"alias {alias!r} points to both {self._aliases[alias]!r} and {sid!r}"
                )
            self._aliases[alias] = sid
        self.series[sid] = spec

    @classmethod
    def load(cls, root: Path | str) -> Catalog:
        """Load and validate every YAML file under ``root``."""
        root = Path(root)
        if not root.is_dir():
            raise CatalogError(f"catalog directory not found: {root}")
        concepts = cls._load_concepts(root / "concepts.yaml")
        entities = cls._load_entities(root / "entities.yaml")
        series: list[SeriesSpec] = []
        for path in sorted(root.rglob("*.y*ml")):
            if path.parent == root and path.name in {"concepts.yaml", "entities.yaml"}:
                continue
            series.extend(cls._load_source_file(path))
        return cls(series, concepts.values(), entities.values(), root=root)

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise CatalogError(f"{path}: top level must be a mapping")
        return data

    @classmethod
    def _load_concepts(cls, path: Path) -> dict[str, ConceptSpec]:
        if not path.exists():
            return {}
        data = cls._read_yaml(path).get("concepts", {}) or {}
        out: dict[str, ConceptSpec] = {}
        for cid, body in data.items():
            body = dict(body or {})
            body.setdefault("concept_id", cid)
            if body["concept_id"] != cid:
                raise CatalogError(
                    f"{path}: concept key {cid!r} != concept_id {body['concept_id']!r}"
                )
            out[cid] = ConceptSpec(**body)
        return out

    @classmethod
    def _load_entities(cls, path: Path) -> dict[str, EntitySpec]:
        if not path.exists():
            return {}
        data = cls._read_yaml(path).get("entities", []) or []
        out: dict[str, EntitySpec] = {}
        for body in data:
            spec = EntitySpec(**body)
            if spec.entity_id in out:
                raise CatalogError(f"{path}: duplicate entity {spec.entity_id!r}")
            out[spec.entity_id] = spec
        return out

    @classmethod
    def _load_source_file(cls, path: Path) -> list[SeriesSpec]:
        try:
            sf = _SourceFile(**cls._read_yaml(path))
        except Exception as exc:  # pydantic ValidationError or CatalogError
            raise CatalogError(f"{path}: {exc}") from exc
        specs: list[SeriesSpec] = []
        for entry in sf.series:
            body = {**sf.defaults, **entry}
            body.setdefault("source", sf.source)
            if body["source"] != sf.source:
                raise CatalogError(
                    f"{path}: entry source {body['source']!r} != file source {sf.source!r}"
                )
            try:
                specs.append(SeriesSpec(**body))
            except Exception as exc:
                raise CatalogError(f"{path}: entry {entry.get('native_id')!r}: {exc}") from exc
        return specs

    # ------------------------------------------------------------------ lookups
    def resolve_alias(self, series_id: str) -> str:
        """Canonical id for ``series_id`` (itself or the target of an alias)."""
        if series_id in self.series:
            return series_id
        if series_id in self._aliases:
            target = self._aliases[series_id]
            warnings.warn(
                f"series id {series_id!r} is an alias; use {target!r}",
                DeprecationWarning,
                stacklevel=2,
            )
            return target
        raise KeyError(series_id)

    def get(self, series_id: str) -> SeriesSpec:
        """Spec by id, resolving aliases."""
        return self.series[self.resolve_alias(series_id)]

    def resolve(self, entity_id: str, concept_id: str) -> SeriesSpec:
        """The one series that carries ``concept_id`` for ``entity_id``."""
        try:
            return self.series[self._by_concept[(entity_id, concept_id)]]
        except KeyError as exc:
            raise KeyError(f"no series for ({entity_id!r}, {concept_id!r})") from exc

    def by_source(self, source: str) -> list[SeriesSpec]:
        return [s for s in self.series.values() if s.source == source]

    @property
    def sources(self) -> list[str]:
        return sorted({s.source for s in self.series.values()})

    @property
    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    # ------------------------------------------------------------------ exports
    @cached_property
    def catalog_hash(self) -> str:
        """SHA-256 of the canonical JSON of all specs; changes iff the catalog changes."""
        payload = {
            "series": [
                s.model_dump(mode="json")
                for s in sorted(self.series.values(), key=lambda s: s.series_id)
            ],
            "concepts": [
                c.model_dump(mode="json")
                for c in sorted(self.concepts.values(), key=lambda c: c.concept_id)
            ],
            "entities": [
                e.model_dump(mode="json")
                for e in sorted(self.entities.values(), key=lambda e: e.entity_id)
            ],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def series_table(self) -> pa.Table:
        """The ``series`` table as the catalog describes it (period bounds left null)."""
        rows = []
        for s in self.series.values():
            rows.append(
                {
                    "series_id": s.series_id,
                    "entity_id": s.entity_id,
                    "concept_id": s.concept_id,
                    "source": s.source,
                    "native_id": s.native_id,
                    "title": s.title,
                    "unit": s.unit,
                    "scale": s.scale,
                    "freq": s.freq,
                    "seasonal_adj": s.seasonal_adj,
                    "calendar": s.calendar,
                    "source_url": s.source_url,
                    "license": s.license,
                    "redistributable": s.redistributable,
                    "aliases": list(s.aliases),
                    "method_version": s.method_version,
                    "expected_lag_days": s.expected_lag_days,
                    "table": s.table,
                    "domain": s.domain,
                    "first_period": None,
                    "last_period": None,
                    "last_updated": None,
                }
            )
        import pandas as pd

        return schemas.from_pandas(pd.DataFrame(rows), schemas.SERIES, "series")

    def entities_table(self) -> pa.Table:
        import pandas as pd

        rows = [
            {
                "entity_id": e.entity_id,
                "entity_type": e.entity_type,
                "name": e.name,
                "attributes": json.dumps(e.attributes, sort_keys=True, ensure_ascii=False),
            }
            for e in self.entities.values()
        ]
        return schemas.from_pandas(pd.DataFrame(rows), schemas.ENTITIES, "entities")
