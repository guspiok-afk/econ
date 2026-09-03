"""econbase: open-data economic database with real-time vintages.

Public surface for consumers (analyses, sibling projects):

- ``econbase.api`` (arrives in WP-03) for concept-based reads
- ``econbase.schemas`` for the data contract
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("econ")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
