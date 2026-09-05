from __future__ import annotations

from pathlib import Path

import pytest

from econbase import schemas
from econbase.catalog import Catalog, CatalogError, ConceptSpec, EntitySpec, SeriesSpec, path_safe


def test_load_and_resolve(catalog: Catalog) -> None:
    assert set(catalog.series) == {"static:ipca", "static:selic", "static:gdp_us"}
    assert catalog.sources == ["static"]
    assert catalog.resolve("BR", "cpi_headline").series_id == "static:ipca"
    assert catalog.resolve("US", "gdp_real").native_id == "gdp_us"
    assert catalog.series["static:selic"].freq == "D"
    assert catalog.series["static:ipca"].expected_lag_days == 12  # from defaults
    assert catalog.entities["BR"].attributes == {"currency": "BRL"}
    with pytest.raises(KeyError):
        catalog.resolve("BR", "gdp_real")


def test_alias_resolves_with_deprecation_warning(catalog: Catalog) -> None:
    with pytest.warns(DeprecationWarning, match="alias"):
        assert catalog.resolve_alias("static:selic_old") == "static:selic"
    with pytest.warns(DeprecationWarning):
        assert catalog.get("static:selic_old").native_id == "selic"
    assert catalog.resolve_alias("static:ipca") == "static:ipca"
    with pytest.raises(KeyError):
        catalog.resolve_alias("static:nope")


def _spec(**kw) -> SeriesSpec:
    base = {"source": "s", "native_id": "1", "entity_id": "BR", "title": "t", "freq": "M"}
    return SeriesSpec(**{**base, **kw})


def test_identifier_grammar() -> None:
    with pytest.raises(ValueError):
        _spec(source="BCB")
    with pytest.raises(ValueError):
        _spec(native_id="with space")
    with pytest.raises(ValueError):
        _spec(entity_id="bra")
    with pytest.raises(ValueError):
        _spec(concept_id="CPI")
    with pytest.raises(ValueError):
        _spec(aliases=["not-an-id"])
    assert _spec(native_id="1737/2266").series_id == "s:1737/2266"
    assert path_safe("sidra:1737/2266") == "sidra__1737__2266"
    assert _spec(entity_id="b3:PETR4").entity_id == "b3:PETR4"


def test_duplicate_concept_mapping_is_rejected() -> None:
    concepts = [ConceptSpec(concept_id="cpi_headline", description="x")]
    a = _spec(native_id="1", concept_id="cpi_headline")
    b = _spec(native_id="2", concept_id="cpi_headline")
    with pytest.raises(CatalogError, match="mapped twice"):
        Catalog([a, b], concepts)


def test_undefined_concept_and_entity_are_rejected() -> None:
    with pytest.raises(CatalogError, match="not defined in concepts"):
        Catalog([_spec(concept_id="cpi_headline")])
    with pytest.raises(CatalogError, match="not defined in entities"):
        Catalog([_spec(entity_id="b3:PETR4")])
    # two-letter country codes are auto-created
    cat = Catalog([_spec(entity_id="AR")])
    assert cat.entities["AR"].entity_type == "country"


def test_alias_collisions_are_rejected() -> None:
    a = _spec(native_id="1", aliases=["s:2"])
    b = _spec(native_id="2")
    with pytest.raises(CatalogError, match="alias"):
        Catalog([a, b])
    with pytest.raises(CatalogError, match="alias"):
        Catalog([b, a])


def test_catalog_hash_is_stable_and_sensitive(catalog_root: Path) -> None:
    h1 = Catalog.load(catalog_root).catalog_hash
    h2 = Catalog.load(catalog_root).catalog_hash
    assert h1 == h2 and len(h1) == 64
    p = catalog_root / "br" / "static.yaml"
    p.write_text(
        p.read_text(encoding="utf-8").replace("IPCA monthly change", "IPCA"), encoding="utf-8"
    )
    assert Catalog.load(catalog_root).catalog_hash != h1


def test_bad_yaml_entry_reports_file(catalog_root: Path) -> None:
    (catalog_root / "br" / "bad.yaml").write_text(
        "source: bad\nseries:\n  - native_id: 'x y'\n"
        "    entity_id: BR\n    title: t\n    freq: M\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match=r"bad\.yaml"):
        Catalog.load(catalog_root)


def test_tables_conform_to_contract(catalog: Catalog) -> None:
    st = catalog.series_table()
    assert st.schema.equals(schemas.SERIES)
    assert st.num_rows == 3
    et = catalog.entities_table()
    assert et.schema.equals(schemas.ENTITIES)
    assert set(et.column("entity_id").to_pylist()) == {"BR", "US"}
    assert EntitySpec(entity_id="US", entity_type="country", name="US").attributes == {}


def test_the_literals_here_match_the_tuples_in_schemas() -> None:
    """The same vocabulary is written twice, so it can drift; this is what notices.

    `schemas` holds the runtime tuples and `catalog` holds the pydantic literals, because a
    Literal cannot be built from a tuple at runtime. When `compound` was added to the
    aggregations it reached only one of the two, and every catalog using it stopped loading.
    """
    from typing import get_args

    from econbase import catalog as cat
    from econbase import schemas as sch

    assert set(get_args(cat.Aggregation)) == set(sch.AGGREGATIONS)
    assert set(get_args(cat.Frequency)) == set(sch.FREQUENCIES)
    assert set(get_args(cat.EntityType)) == set(sch.ENTITY_TYPES)
