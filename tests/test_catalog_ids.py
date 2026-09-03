"""The real catalog must never lose an identifier (docs/IDENTIFIERS.md rule 2).

``catalog/ids.txt`` lists every series_id ever published. Each must still resolve, either as
a live series or as an alias of one. New series must be appended to the list so the guard
covers them from their first release.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from econbase.catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "catalog"
IDS_FILE = CATALOG_DIR / "ids.txt"


def _baseline_ids() -> list[str]:
    lines = IDS_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def test_real_catalog_loads() -> None:
    cat = Catalog.load(CATALOG_DIR)
    assert cat.concepts, "concepts.yaml must define at least one concept"
    assert {"BR", "US"} <= set(cat.entities)


def test_no_published_id_was_removed_without_an_alias() -> None:
    cat = Catalog.load(CATALOG_DIR)
    missing = []
    for sid in _baseline_ids():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            try:
                cat.resolve_alias(sid)
            except KeyError:
                missing.append(sid)
    assert not missing, (
        f"published ids removed from the catalog without an alias: {missing}. "
        "Add them to `aliases:` of the successor entry (never delete an id)."
    )


def test_every_live_id_is_in_the_baseline() -> None:
    cat = Catalog.load(CATALOG_DIR)
    baseline = set(_baseline_ids())
    unlisted = sorted(set(cat.series) - baseline)
    assert not unlisted, f"new series ids must be appended to catalog/ids.txt: {unlisted}"
