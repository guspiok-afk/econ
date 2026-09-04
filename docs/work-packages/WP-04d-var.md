# WP-04d — The monetary VAR, with recursive identification

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:jules` |
| Branch | `wp/04d-var` |
| Depends on | WP-03a (merged) |
| Estimated effort | ~8 h |

## Goal

The workhorse of empirical macro: a small vector autoregression of inflation, output and the
policy rate, identified recursively, producing impulse responses and a variance decomposition
that can be argued with.

Sign restrictions are **not** in this package. They are the answer to something this one is
required to show, and they come next.

## What the data says, so you know when you are right

Fitted on `tests/fixtures/analysis/us_quarterly_var.csv` from 1961Q1 to 2019Q4 with four lags
and the ordering (inflation, output, policy), a one-standard-deviation policy shock gives:

| horizon | inflation | output | policy |
|---:|---:|---:|---:|
| 0 | 0.0000 | 0.0000 | +0.7545 |
| 4 | **+0.3779** | −0.2261 | +0.6411 |
| 8 | +0.2112 | −0.4134 | +0.4389 |
| 14 | — | **−0.4602** | — |
| 24 | −0.0360 | −0.4309 | +0.0815 |

Two things to take from it. Output falls, troughing around half a per cent after three and a
half years, which is the textbook result. And **inflation rises for the first year**, which is
not: it is the price puzzle, it is genuinely in this sample under this ordering, and a run that
does not show it is not fitting the same data. Do not try to make it go away.

2020 is excluded from the sample. A single quarter in which output fell nine per cent dominates
any linear VAR estimated through it, and the package documents the cut rather than hiding it.

## Contract

`src/econmodels/var.py`

```python
@register
class VectorAutoregression:
    model_id = "var_monetary"
    model_version = "1"
    requires = (
        ConceptRequest("cpi_headline_index", freq="Q"),
        ConceptRequest("gdp_real", freq="Q"),
        ConceptRequest("policy_rate", freq="Q"),
    )

    def __init__(
        self,
        entity: str,
        lags: int | str = 4,                 # an integer, or "aic" | "bic" | "hqic"
        max_lags: int = 8,                   # only consulted when lags is a criterion
        horizon: int = 24,
        order: tuple[str, str, str] = ("inflation", "output", "policy"),
        identification: str = "cholesky",
    ) -> None: ...

    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
```

The three variables are built inside `fit` from the panel it is given:

- `inflation` — four-quarter log change of the price index, times 100
- `output` — 100 × log of real GDP (levels in logs, not a gap: the VAR handles the trend)
- `policy` — the policy rate as it comes, in percent per year

Tables returned:

| table | columns |
|---|---|
| `irf` | `horizon`, `shock`, `response`, `value` — orthogonalised, one row per triple |
| `fevd` | `horizon`, `response`, `shock`, `value` — shares, summing to 1 per (horizon, response) |
| `coefficients` | `equation`, `regressor`, `estimate`, `std_error` |
| `diagnostics` | `metric`, `value` — `n_obs`, `lags`, `identification`, `order`, `max_eigenvalue`, `loglikelihood` |

Rules that are not negotiable:

- **The panel comes from `api.get_panel` at `ctx.asof`.** Never read the store directly.
- **The ordering is an economic assumption and must reach the result.** It goes in
  `diagnostics`, and changing it must change the answer — there is a test for exactly that,
  because an implementation that ignores the ordering still draws convincing pictures.
- **Report stability.** The largest eigenvalue of the companion matrix goes in `diagnostics`.
  An explosive system produces impulse responses that grow without bound and look decisive.

## Acceptance tests (in the repository, currently skipping)

`tests/test_var.py` — `uv run pytest tests/test_var.py -q`

Thirteen, in three groups: identification (recursive zeros on impact, the ordering matters, the
ordering is recorded), the pinned economics (output trough, impact response, the price puzzle,
sample size), and the model itself (stability, lag selection, the decomposition exhausting the
variance, reproducibility, portability, refusal on too short a sample).

## Files you may change

`src/econmodels/var.py` (new), and the Result section of this file. Not
`src/econmodels/base.py`, not anything under `src/econbase/`, not the tests. `statsmodels` is
already in the development environment; add no dependency.

## Definition of done

- [ ] `uv run pytest -q` fully green; `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] Only the listed files changed
- [ ] A run on Brazil pasted into the Result section. It will look different and that is the
      point: say what you see rather than tuning until it matches the United States.

If a test looks wrong to you, say so in the pull request instead of changing it. That has caught
real specification errors here before, and changing one silently would hide the next.

## Result

(filled in by the executor)
