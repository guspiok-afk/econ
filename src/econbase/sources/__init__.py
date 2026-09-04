"""Connectors. Each source module defines a :class:`Source` subclass and registers it.

Connector modules are imported lazily by :func:`build_registry` so that a broken optional
connector never prevents the CLI from starting.
"""

from __future__ import annotations

import importlib
import logging

from econbase.settings import Settings
from econbase.sources.base import (
    FetchResult,
    RawResponse,
    Source,
    SourceError,
    StaticSource,
    available,
    register,
)

log = logging.getLogger(__name__)

#: Connector modules to import when building the registry (WP-02 fills this list).
CONNECTOR_MODULES: tuple[str, ...] = (
    "econbase.sources.fred",
    "econbase.sources.sidra",
    "econbase.sources.ipeadata",
)


def build_registry(settings: Settings | None = None) -> dict[str, Source]:
    """Instantiate every registered connector; import connector modules first."""
    for mod in CONNECTOR_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("connector module %s failed to import: %s", mod, exc)
    return {name: cls(settings=settings) for name, cls in available().items()}


__all__ = [
    "CONNECTOR_MODULES",
    "FetchResult",
    "RawResponse",
    "Source",
    "SourceError",
    "StaticSource",
    "available",
    "build_registry",
    "register",
]
