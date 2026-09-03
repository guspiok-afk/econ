"""The model contract every analysis implements.

A model declares which concepts it needs, receives a panel built as of a date, and returns a
:class:`Result` whose tables are long DataFrames. This is the seam that lets a results store
and a backtest driver be added later (see plan: deferred behind ``RunContext``/``Result``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ConceptRequest:
    """One input a model needs, expressed as a concept (never a series id)."""

    concept: str
    entity: str | None = None
    freq: str | None = None
    transform: str | None = None
    min_history: int | None = None
    optional: bool = False


@dataclass(slots=True)
class RunContext:
    """Everything that must be fixed for a fit to be reproducible."""

    asof: dt.date
    seed: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    vintage_kind: str = "latest"  # latest | true | pseudo | mixed
    rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)


@runtime_checkable
class Result(Protocol):
    """What a fit returns. ``tables()`` are long DataFrames ready for a results store."""

    def tables(self) -> Mapping[str, pd.DataFrame]: ...

    def artifacts(self) -> Sequence[Any]: ...


@dataclass(slots=True)
class TablesResult:
    """Minimal :class:`Result` implementation: a dict of tables and optional artifacts."""

    _tables: dict[str, pd.DataFrame]
    _artifacts: list[Any] = field(default_factory=list)

    def tables(self) -> Mapping[str, pd.DataFrame]:
        return self._tables

    def artifacts(self) -> Sequence[Any]:
        return self._artifacts


@runtime_checkable
class Model(Protocol):
    """A registered analysis."""

    model_id: str
    model_version: str
    requires: Sequence[ConceptRequest]

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...


_REGISTRY: dict[str, type[Model]] = {}


def register(cls: type[Model]) -> type[Model]:
    """Class decorator registering a model under its ``model_id``."""
    model_id = getattr(cls, "model_id", None)
    if not model_id:
        raise ValueError(f"{cls.__name__} must define 'model_id'")
    _REGISTRY[model_id] = cls
    return cls


def available() -> dict[str, type[Model]]:
    return dict(_REGISTRY)
