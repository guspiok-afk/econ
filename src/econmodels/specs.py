"""A specification is a file, not a commit.

One model can be estimated many ways, and the ways are the analysis. A Phillips curve with the
Banco Central's terms and one without exchange-rate pass-through are the same code answering
different questions, and comparing them is the point rather than a detour.

So a variation is a YAML file under ``specs/<model_id>/``, validated here, and a saved run
records which specification produced it. Comparing ten of them becomes a ``GROUP BY`` instead of
ten commits and a memory of what changed.

The hash matters as much as the identifier. A run must stay reproducible when the file is later
edited: without it, changing ``br_bcb_small_scale.yaml`` silently re-labels every earlier run as
belonging to the new specification, and two different things get compared as one. It is the same
discipline as ``catalog_hash`` in the data manifest, for the same reason.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

SPEC_DIR = "specs"


class SpecError(ValueError):
    """A specification file is not usable."""


class Provenance(BaseModel):
    """Where the specification comes from, and where it knowingly departs."""

    model_config = ConfigDict(extra="forbid")

    follows: str
    source_url: str | None = None
    departs: str | None = None


class Term(BaseModel):
    """One regressor, named so a restriction and a result can refer to it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    concept: str
    entity: str | None = None
    transform: str | None = None
    lags: list[int] = Field(default_factory=lambda: [0])

    @model_validator(mode="after")
    def _lags_are_sane(self) -> Term:
        if not self.lags:
            raise ValueError(f"term {self.name!r} has an empty lag list")
        if any(lag < 0 for lag in self.lags):
            raise ValueError(f"term {self.name!r} has a negative lag; leads are not a lag list")
        if len(set(self.lags)) != len(self.lags):
            raise ValueError(f"term {self.name!r} repeats a lag")
        return self


class Restriction(BaseModel):
    """A constraint imposed on the estimate rather than tested for."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sum_to_one", "fixed"]
    over: list[str] = Field(default_factory=list)
    value: float | None = None


class Estimation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["ols", "wls"] = "ols"
    cov: Literal["nonrobust", "hac", "newey_west"] = "newey_west"
    maxlags: int | None = None


class Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str | None = None
    end: str | None = None


class Dependent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str
    entity: str | None = None
    transform: str | None = None


class Spec(BaseModel):
    """One way of estimating one model."""

    model_config = ConfigDict(extra="forbid")

    spec_id: str
    model_id: str
    version: str = "1"
    entity: str
    provenance: Provenance
    dependent: Dependent
    terms: list[Term]
    restrictions: list[Restriction] = Field(default_factory=list)
    estimation: Estimation = Field(default_factory=Estimation)
    sample: Sample = Field(default_factory=Sample)
    notes: str | None = None

    #: Filled in by :func:`load_specs`; not part of the file.
    spec_hash: str = ""
    path: str = ""

    @model_validator(mode="after")
    def _restrictions_name_real_terms(self) -> Spec:
        known = {t.name for t in self.terms}
        if len(known) != len(self.terms):
            raise ValueError("two terms share a name")
        for restriction in self.restrictions:
            unknown = [name for name in restriction.over if name not in known]
            if unknown:
                raise ValueError(
                    f"restriction {restriction.kind!r} names {unknown}, which are not terms; "
                    f"the terms are {sorted(known)}"
                )
        return self

    def term(self, name: str) -> Term:
        for candidate in self.terms:
            if candidate.name == name:
                return candidate
        raise SpecError(f"{self.spec_id} has no term {name!r}")

    def concepts(self) -> list[tuple[str, str]]:
        """Every ``(concept, entity)`` the specification reads, dependent first."""
        pairs = [(self.dependent.concept, self.dependent.entity or self.entity)]
        pairs += [(t.concept, t.entity or self.entity) for t in self.terms]
        seen: dict[tuple[str, str], None] = {}
        for pair in pairs:
            seen.setdefault(pair, None)
        return list(seen)

    def as_params(self) -> dict[str, Any]:
        """What goes into a stored run's ``params``, so a rerun is reconstructible."""
        return self.model_dump(exclude={"path"}, mode="json")


def hash_bytes(raw: bytes) -> str:
    """The identity of a specification's content, short enough to read in a table."""
    return hashlib.sha256(raw).hexdigest()[:16]


def load_spec(path: Path) -> Spec:
    """Read and validate one specification file."""
    raw = path.read_bytes()
    try:
        body = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(body, dict):
        raise SpecError(f"{path} does not hold a mapping")
    try:
        spec = Spec(**body, spec_hash=hash_bytes(raw), path=path.as_posix())
    except Exception as exc:
        raise SpecError(f"{path}: {exc}") from exc
    if spec.spec_id != path.stem and not path.stem.endswith(spec.spec_id):
        raise SpecError(
            f"{path} declares spec_id {spec.spec_id!r}; the file name must match it, so a run "
            "can be traced to a file without opening every one"
        )
    return spec


def load_specs(root: Path | str = SPEC_DIR, *, model_id: str | None = None) -> dict[str, Spec]:
    """Every specification under ``root``, keyed by ``spec_id``."""
    base = Path(root)
    if not base.exists():
        return {}
    out: dict[str, Spec] = {}
    for path in sorted(base.rglob("*.yaml")):
        spec = load_spec(path)
        if model_id is not None and spec.model_id != model_id:
            continue
        if spec.spec_id in out:
            raise SpecError(f"two files declare spec_id {spec.spec_id!r}: {out[spec.spec_id].path}")
        out[spec.spec_id] = spec
    return out
