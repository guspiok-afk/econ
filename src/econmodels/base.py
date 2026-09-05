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


# --------------------------------------------------------------------- the panel a model gets
#: Calendar grids a declared frequency implies. Daily and business-daily series have no grid to
#: check against — holidays are not holes — so they are deliberately absent.
_GRID: dict[str, str] = {"M": "MS", "Q": "QS", "A": "YS", "W": "W-MON"}


class PanelError(ValueError):
    """The panel a model was handed is not the panel it declared it needed."""


def column_for(panel: pd.DataFrame, concept: str, entity: str) -> str:
    """The one column name the contract allows, or a refusal that names what was there.

    No fallback and no prefix matching. Two models have shipped a resolver that guessed — one
    fell back to "the only column there is", the other matched by prefix and ignored the entity
    entirely, so a panel holding both countries would answer with the wrong one and return a
    perfectly plausible regression of the wrong country.
    """
    wanted = f"{concept}@{entity}"
    if wanted in panel.columns:
        return wanted
    raise PanelError(
        f"the panel has no column {wanted!r}; it carries {sorted(map(str, panel.columns))}. "
        "Build it with api.get_panel, which names columns concept@entity."
    )


def series_for(panel: pd.DataFrame, concept: str, entity: str) -> pd.Series:
    """One column of the panel, as a float series indexed by period."""
    return panel[column_for(panel, concept, entity)].astype(float)


def check_frequency(panel: pd.DataFrame, freq: str) -> None:
    """Refuse a panel whose index is not a regular grid at ``freq``.

    Every model in this repository shifts and lags by row: ``value.shift(4)`` for a four-quarter
    change, ``gap.shift(1)`` for a lagged gap. That is only a four-quarter change when the index
    really is quarterly and has no holes, and nothing enforced it — ``ConceptRequest(freq="Q")``
    declared the need and no code read it. On a monthly panel, which is what ``api.get_panel``
    returns by default because the price index is monthly in both countries, a four-row shift is
    a four-month change reported as annual: six percentage points of error in a prescribed policy
    rate, with no exception and no warning.
    """
    rule = _GRID.get(freq)
    if rule is None or panel.empty:
        return
    index = panel.index
    if not isinstance(index, pd.DatetimeIndex):
        raise PanelError(
            f"the panel index is {type(index).__name__}, not a DatetimeIndex; "
            "a model that shifts by row needs a real time index"
        )
    expected = pd.date_range(index.min(), index.max(), freq=rule)
    extra = index.difference(expected)
    if len(extra):
        raise PanelError(
            f"the panel is not {freq}: {len(extra)} period(s) fall off the {freq} grid, "
            f"first {extra[0].date()}. Ask api.get_panel for freq={freq!r}."
        )
    missing = expected.difference(index)
    if len(missing):
        raise PanelError(
            f"the panel has {len(missing)} hole(s) in its {freq} grid, first {missing[0].date()}. "
            "A shift by row is not a shift by period across a hole."
        )


def panel_for(model: Model, panel: pd.DataFrame, *, entity: str | None = None) -> pd.DataFrame:
    """Check a panel against what ``model.requires`` declares, and return it unchanged.

    This is what makes ``requires`` mean something. Until it existed the field was decorative:
    three models declared the frequency they needed and nothing ever read the declaration.
    """
    default_entity = entity or getattr(model, "entity", None) or getattr(model, "base", None)
    for request in model.requires:
        who = request.entity or default_entity
        if who is None:
            raise PanelError(
                f"{request.concept!r} does not say which entity it wants and the model does "
                "not carry one; pass entity= explicitly"
            )
        if request.optional and f"{request.concept}@{who}" not in panel.columns:
            continue
        column_for(panel, request.concept, who)
        if request.freq:
            check_frequency(panel, request.freq)
    return panel
