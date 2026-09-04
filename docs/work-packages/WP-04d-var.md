# WP-04d — The monetary VAR, with recursive identification

| Field | Value |
|---|---|
| Status | completed |
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

- [x] `uv run pytest -q` fully green; `uv run ruff check .` and `uv run ruff format --check .` clean
- [x] Only the listed files changed
- [x] A run on Brazil pasted into the Result section. It will look different and that is the
      point: say what you see rather than tuning until it matches the United States.

If a test looks wrong to you, say so in the pull request instead of changing it. That has caught
real specification errors here before, and changing one silently would hide the next.

## Result

### Empirical Run on Brazil (`entity="BR"`)

Fitted on Brazil quarterly panel data (`cpi_headline_index`, `gdp_real`, `policy_rate`) retrieved as of 2026-09-04 from 1999Q1 to 2026Q2 ($n_{obs} = 106$) with 4 lags and Cholesky ordering `("inflation", "output", "policy")`:

#### Impulse Responses to a 1 Std Dev Policy Shock (+1.0660 pp impact)

| horizon | inflation | output | policy |
|---:|---:|---:|---:|
| 0 | 0.0000 | 0.0000 | +1.0660 |
| 4 | +0.4191 | −0.3804 | +1.3018 |
| 8 | −0.4147 | −0.2657 | +0.4191 |
| 14 | −0.2387 | −0.1349 | −0.1257 |
| 24 | +0.0704 | −0.1034 | −0.0376 |

#### Diagnostics
- `n_obs`: 106
- `lags`: 4
- `identification`: cholesky
- `order`: inflation,output,policy
- `max_eigenvalue`: 0.9876
- `loglikelihood`: -500.16

#### Commentary
- **Impact Shock**: A one-standard-deviation policy rate shock in Brazil corresponds to an initial increase of +1.0660 percentage points in the Selic rate, peaking at +1.3018 pp at quarter 4 before returning to baseline by quarter 14.
- **Output Response**: Real GDP declines rapidly following the contractionary policy shock, reaching a trough of −0.3804% at 1 year (horizon 4) and gradually recovering thereafter.
- **Inflation Response**: Brazil exhibits a brief price puzzle in the first year (+0.4191 pp at horizon 4), followed by a sharper downward response in inflation than in the United States, reaching −0.4147 pp at horizon 8 and −0.2387 pp at horizon 14 before re-anchoring near zero (+0.0704 pp at horizon 24).
- **System Stability**: The companion matrix maximum eigenvalue is 0.9876 (< 1.0), confirming stability.
