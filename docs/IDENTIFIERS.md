# Identifiers

## series_id — immutable, primary key everywhere

`series_id = "{source}:{native_id}"`

- `source` matches `^[a-z][a-z0-9_]*$` and names a connector module
  (`bcb_sgs`, `bcb_ptax`, `bcb_focus`, `sidra`, `ipeadata`, `fred`, `dbnomics`, `b3_taxas_ref`,
  `nyfed`, `derived`).
- `native_id` matches `^[A-Za-z0-9][A-Za-z0-9_./\-]*$` and is the identifier the source itself
  uses (`433`, `CPIAUCSL`, `1737/2266`, `OECD/MEI/BRA.CPALTT01.IXOB.M`).
- Examples: `bcb_sgs:433`, `fred:CPIAUCSL`, `sidra:1737/2266`, `dbnomics:OECD/MEI/BRA.CPALTT01.IXOB.M`,
  `derived:sticky_cpi_br`.

Rules:
1. A `series_id` is never renamed or reused. If a source retires an id, the entry stays in the
   catalog with `status: retired` (added in a later schema version if needed) and history is kept.
2. A consumer-facing rename is done by adding the old id to `aliases` of the new entry.
   `api.get` resolves aliases and emits `DeprecationWarning`. A test forbids removing an id
   without leaving an alias.
3. A breaking change in the method of a derived series mints a new id
   (`derived:sticky_cpi_br_v2`) rather than overwriting history; `method_version` records
   non-breaking method changes.
4. On disk, `series_id` is made path-safe by replacing `:` and `/` with `__`
   (`sidra__1737__2266`).

## concept_id — analysis-facing key

`^[a-z][a-z0-9_]*$`, defined once in `catalog/concepts.yaml` with a description, a unit kind
and a default aggregation for frequency conversion. Examples: `cpi_headline`, `cpi_core`,
`policy_rate`, `gdp_real`, `unemployment_rate`, `fx_spot_usd`.

The pair `(entity_id, concept_id)` is unique across the catalog: exactly one series per
country per concept. Alternative/fallback series for the same concept are a later feature
(trigger: third country) and will be expressed as a priority list, not as duplicates.

## entity_id

- Countries: ISO 3166-1 alpha-2 (`BR`, `US`).
- Instruments (future): `{scheme}:{code}` in lower-case scheme (`b3:PETR4`, `isin:BRPETRACNPR6`).
- `entity_type` in `entities.yaml`: `country | instrument | issuer | index | region`.

## run_id

`YYYYmmddTHHMMSSZ-<6 hex>` in UTC; sortable, unique per process start.
