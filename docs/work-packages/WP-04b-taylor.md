# WP-04b — The Taylor rule

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:antigravity`, with a reasoning model |
| Branch | `wp/04b-taylor` |
| Worktree | `C:\dev\econ-taylor` |
| Depends on | WP-03a (merged) |
| Estimated effort | ~6 h |

## Goal

A monetary policy rule that runs on either country by changing one argument, and that can be
checked against the paper that introduced it.

## Why this needs judgement, and is not for a mechanical executor

The formula is three lines. Everything difficult is in the inputs:

- **Which output gap.** The gap is unobservable. A Hodrick-Prescott filter is the convention
  and is also the thing most likely to be wrong, because it uses the whole sample to date each
  point — including the future, if you let it. In a backtest that is leakage.
- **Which inflation.** Headline or core, and over what horizon. Taylor used four-quarter GDP
  deflator inflation; this base has the CPI index, so the choice must be stated rather than
  assumed.
- **Which neutral rate.** Taylor assumed two per cent, permanently. That is defensible for the
  1987-1992 sample and indefensible for 2010-2020, so it is a parameter and not a constant.

Take a position on each, write it in the docstring, and make it a parameter so the next person
can disagree without editing code.

## The rule

```
i_t  =  r*  +  π_t  +  a_π · (π_t − π*)  +  a_y · gap_t
```

Taylor (1993): `r* = 2`, `π* = 2`, `a_π = a_y = 0.5`, inflation over four quarters, gap in
percent of potential output.

## Contract

`src/econmodels/taylor.py`

```python
@register
class TaylorRule:
    model_id = "taylor_rule"
    model_version = "1"
    requires = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    def __init__(
        self,
        entity: str,
        neutral_real_rate: float = 2.0,
        inflation_target: float = 2.0,
        weight_inflation: float = 0.5,
        weight_gap: float = 0.5,
        gap_method: str = "hp",  # "hp" | "hamilton"
        hp_lambda: float = 1600.0,
    ) -> None: ...

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
    def estimate(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
```

`fit` applies the rule with the given coefficients. `estimate` regresses the actual policy rate
on inflation and the gap to recover them from the data.

Tables returned:

| table | columns |
|---|---|
| `prescription` | `period`, `actual`, `prescribed`, `gap`, `inflation`, `deviation` |
| `coefficients` | `name`, `estimate`, `std_error` — from `estimate` only |
| `diagnostics` | `metric`, `value` — correlation, mean absolute deviation, n_obs, settings |

Rules that are not negotiable:

- **The panel comes from `api.get_panel` at `ctx.asof`.** Never read the store directly.
- **The gap is computed inside `fit`, on the panel it was given.** Not stored, not precomputed:
  a filter run on today's data and then applied to a past date is leakage of exactly the kind
  the vintages exist to prevent.
- Every setting lands in `diagnostics`, so a result carries the assumptions that produced it.

## Acceptance tests (in the repository, currently failing)

`tests/test_taylor.py` — `uv run pytest tests/test_taylor.py -q`

1. **The arithmetic.** With inflation and gap supplied directly, the prescription must equal the
   formula to twelve decimals, and doubling the inflation weight must move it by exactly the
   right amount.
2. **Taylor's own sample.** `tests/fixtures/analysis/us_quarterly_taylor.csv` holds United
   States data from 1979. Over **1987Q1 to 1992Q3**, with Taylor's settings, the prescribed rate
   must track the actual federal funds rate with **correlation ≥ 0.75** and **mean absolute
   deviation ≤ 1.2 points**. That is the paper's central claim, reproduced from the base.
3. **Leakage.** The gap for a quarter, computed on a panel ending at that quarter, must not
   change when later quarters are appended — or, if the filter is two-sided and it does change,
   the model must say so in `diagnostics` rather than pretend otherwise.

## Files you may change

`src/econmodels/taylor.py` (new), `tests/fixtures/analysis/` (only to add), this file's Result
section. Not `src/econmodels/base.py`, not `econbase`.

## Definition of done

- [ ] `uv run pytest -q` fully green; ruff clean
- [ ] Only the listed files changed; no new dependencies
- [ ] A run on Brazil pasted into the Result section — the rule must run on both countries by
      changing `entity`, and Brazil's neutral rate and target are not two per cent

## Result

Implementado pelo Antigravity; revisado, corrigido e verificado contra a base viva pelo arquiteto.

### Três correções na revisão

1. **A inflação "anual" era um deslocamento de quatro linhas.** `shift(4)` é posicional, e nada
   verificava que o índice era trimestral. Na chamada que o próprio pacote manda usar —
   `api.get_panel` sem `freq`, que devolve um painel mensal porque o índice de preços é mensal
   nos dois países — a inflação saía como variação de quatro **meses** rotulada como anual, e a
   taxa prescrita vinha **seis pontos abaixo** do correto, sem exceção, sem aviso, e com o
   diagnóstico ainda afirmando ter medido quatro trimestres. Agora `panel_for` recusa antes de
   qualquer conta.
2. **`gap_method` era aceito, nunca consultado, e escrito no diagnóstico como o método usado.**
   Passar `"hamilton"` devolvia um hiato Hodrick-Prescott com rótulo errado. O filtro de Hamilton
   está implementado e os dois produzem hiatos genuinamente diferentes; qualquer outro valor é
   recusado com o motivo.
3. **`estimate` aceitava uma regressão exatamente identificada.** A guarda era `len < 3` para
   três parâmetros: os pontos eram interpolados, os erros-padrão ficavam indefinidos e a tabela
   saía como qualquer outra. Agora exige graus de liberdade residuais.

### Ao vivo, painel trimestral construído pelo `api.get_panel` em 2026-09-05

| | n | correlação | desvio médio | último trimestre |
|---|---:|---:|---:|---|
| Estados Unidos (r\* 2,0, meta 2,0) | 106 | 0,419 | 3,04 | efetivo 3,63 · prescrito 6,40 · hiato −0,61 |
| Brasil (r\* 4,5, meta 3,0) | 106 | 0,582 | 3,41 | efetivo 14,25 · prescrito 9,94 · hiato +0,13 |

A regra roda nos dois países trocando um argumento, e o Brasil não usa dois por cento nem de
juro neutro nem de meta — que era o item da definição de pronto.

Os dois resultados dizem coisas opostas e ambas plausíveis: a taxa americana está bem abaixo do
que a regra prescreve, e a brasileira bem acima. Uma regra de Taylor com juro neutro fixo é uma
referência, não um alvo, e é para isso que o `r*` é parâmetro e vai no diagnóstico.
