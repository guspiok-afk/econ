# WP-02e-br — Fourteen more Brazilian series

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:ollama` (local model; mechanical, one file) |
| Branch | `wp/02e-br-catalog` |
| Worktree | `C:\dev\econ-ollama-br` (prepared, dependencies installed) |
| Depends on | WP-02b (merged) |
| Estimated effort | ~1 h |

## Goal

Fourteen series the Banco Central publishes that the catalog does not yet carry: three core
inflation measures, seasonally adjusted activity, net public debt, the credit split between
households and free-market lending, and the external accounts.

The three cores matter most: a Phillips curve without a core measure is a curve fitted to food
and fuel.

## Why this is a transcription job

Every identifier below was requested from the live API on 2026-09-04, and **every title is the
one the Banco Central itself publishes**, taken from the open data portal rather than written
from memory. That check changed seven of them: series 11427 is not the double-weighted core but
the exclusion core without administered prices and food at home; 20717 is not corporate lending
but free-market lending overall; 22707 is the trade balance and not exports. Do not improve the
titles — they are the official names, and they are what a future reader will trust.

## What to write

### One file: `catalog/br/bcb_sgs.yaml`

Keep every entry already there and add the fourteen below, in the same shape and under the same
`defaults:` block. `source_url` is `https://www3.bcb.gov.br/sgspub/` for all of them.

**Every title contains a colon or an accent, so every title must be quoted with double quotes.**
This is the one formatting rule of the package. Example, copy it exactly:

```yaml
  - native_id: '4466'
    concept_id: cpi_core
    title: "Índice nacional de preços ao consumidor-Amplo (IPCA) - Núcleo médias aparadas com suavização"
    unit: pct
    freq: M
    expected_lag_days: 12
    source_url: https://www3.bcb.gov.br/sgspub/
```

`native_id` is quoted because it is numeric. `concept_id` appears only where the table shows one.

| native_id | concept_id | unit | lag | title (exact) |
|---|---|---|---|---|
| 4466 | cpi_core | pct | 12 | Índice nacional de preços ao consumidor-Amplo (IPCA) - Núcleo médias aparadas com suavização |
| 11427 | — | pct | 12 | Índice nacional de preços ao consumidor - Amplo (IPCA) - Núcleo por exclusão - Sem monitorados e alimentos no domicílio |
| 16121 | — | pct | 12 | Índice nacional de preços ao consumidor - Amplo (IPCA) - Núcleo por exclusão - ex2 |
| 24364 | — | index | 45 | Índice de Atividade Econômica do Banco Central (IBC-Br) - com ajuste sazonal |
| 4513 | — | pct of GDP | 30 | Dívida Líquida do Setor Público (% PIB) - Total - Setor público consolidado |
| 20541 | — | BRL million | 30 | Saldo da carteira de crédito - Pessoas físicas - Total |
| 20542 | — | BRL million | 30 | Saldo da carteira de crédito com recursos livres - Total |
| 20716 | — | pct per year | 30 | Taxa média de juros das operações de crédito - Pessoas físicas - Total |
| 20717 | — | pct per year | 30 | Taxa média de juros das operações de crédito com recursos livres - Total |
| 21084 | — | pct | 30 | Inadimplência da carteira de crédito - Pessoas físicas - Total |
| 21085 | — | pct | 30 | Inadimplência da carteira de crédito com recursos livres - Total |
| 22707 | trade_balance | USD million | 25 | Balança comercial - Balanço de Pagamentos - mensal - saldo |
| 22708 | — | USD million | 25 | Exportação de bens - Balanço de Pagamentos - mensal |
| 22701 | — | USD million | 25 | Transações correntes - mensal - saldo |

All fourteen are monthly (`freq: M`), none is seasonally adjusted except 24364
(`seasonal_adj: true`; the others take `seasonal_adj: false`), and none needs `params`.

### Then, and only then: `catalog/ids.txt`

Append `bcb_sgs:<native_id>` for each of the fourteen, one per line. **This is a separate step
and it has been forgotten before.** The test will tell you if it is missing.

## Files you may change

`catalog/br/bcb_sgs.yaml`, `catalog/ids.txt`, and the Result section of this file. No code.

## Acceptance test

`tests/test_catalog_br.py` — already in the repository and failing.

```
uv run pytest tests/test_catalog_br.py -q
```

It reads the file as raw text before parsing it, so a stray markdown fence fails with a clear
message, and it compares every title character by character against the official name.

## Definition of done

- [ ] `uv run pytest -q` fully green
- [ ] `uv run ruff check .` clean
- [ ] Only the two catalog files and this one changed
- [ ] `uv run python -m econbase.cli update --source bcb_sgs` run live, **output pasted below**

## Result

Written by Claude after three attempts with `qwen3-coder:30b` through Aider: the model produced
the right content every time and never produced a usable edit block — it stopped after its plan
twice, and on the third run emitted a malformed diff whose filename line Aider read as
`source_url: https://www3.bcb.gov.br/sgspub/`. Lesson 5 of the kit holds and is now paid for:
the local model is worth its cost on mechanical content, not on file surgery.

`uv run pytest tests/test_catalog_br.py -q` — 19 passed. Full suite 286 passed, ruff clean.

`uv run python -m econbase.cli update --source bcb_sgs`:

```
    series_id  rows_fetched  rows_new  rows_revised  rows_closed error
  bcb_sgs:433           559       559             0            0  None
bcb_sgs:13522           548       548             0            0  None
  bcb_sgs:432         10046     10046             0            0  None
   bcb_sgs:11         10092     10092             0            0  None
bcb_sgs:24363           282       282             0            0  None
    bcb_sgs:1         10468     10468             0            0  None
 bcb_sgs:7806          5006      5006             0            0  None
bcb_sgs:20539           458       458             0            0  None
bcb_sgs:20714           185       185             0            0  None
bcb_sgs:21082           185       185             0            0  None
 bcb_sgs:4649           296       296             0            0  None
bcb_sgs:13762           236       236             0            0  None
 bcb_sgs:4466           416       416             0            0  None
bcb_sgs:11427           427       427             0            0  None
bcb_sgs:16121           427       427             0            0  None
bcb_sgs:24364           282       282             0            0  None
 bcb_sgs:4513           296       296             0            0  None
bcb_sgs:20541           233       233             0            0  None
bcb_sgs:20542           233       233             0            0  None
bcb_sgs:20716           185       185             0            0  None
bcb_sgs:20717           185       185             0            0  None
bcb_sgs:21084           185       185             0            0  None
bcb_sgs:21085           185       185             0            0  None
bcb_sgs:22707           379       379             0            0  None
bcb_sgs:22708           379       379             0            0  None
bcb_sgs:22701           379       379             0            0  None
run 20260904T171755Z-635b6e (ok): 26 series, 0 error(s)
```

All fourteen new identifiers answered with data and parsed: the three cores go back to 1991
(4466) and 1990 (11427, 16121), the seasonally adjusted IBC-Br matches the unadjusted series in
length, and the three balance-of-payments series carry 379 months each.

`rows_new` equals `rows_fetched` for every series because this run wrote into an empty store —
see the note on the desktop app's private data directory in `docs/OPERATION.md`. It is a first
load, not a revision, and says nothing about the store the scheduled task maintains.
