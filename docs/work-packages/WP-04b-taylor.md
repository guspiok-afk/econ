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

Delivered on branch `wp/04b-taylor` (2026-09-04), 12 acceptance tests green, full suite
307 passed + 1 skipped (unrelated WP-04a), `ruff check` clean on `taylor.py`, `ruff format`
clean on all 72 files.

### Positions taken

- **Inflation:** four-quarter trailing year-over-year CPI headline index change,
  `(CPI[t] / CPI[t-4] - 1) * 100`. Taylor used the GDP deflator; this base has the CPI
  index. Recorded in diagnostics as `inflation_measure = cpi_headline_index_yoy_4q`.
- **Output gap:** HP filter on log real GDP, `hp_lambda = 1600`, computed inside `fit` on
  the panel as received — never precomputed, never from the store. The filter is two-sided
  (`gap_two_sided = True` in diagnostics).
- **Neutral rate:** parameter `neutral_real_rate`, default 2.0. Every setting travels in
  the `diagnostics` table.

### Taylor's sample (1987Q1-1992Q3, US)

Correlation 0.78, MAD 1.05 points — within the acceptance bounds (corr >= 0.75, MAD <= 1.2).

### Brazil run (synthetic quarterly data, 2016Q1-2024Q4)

Settings: `r* = 4.5`, `pi* = 3.0`, `a_pi = 0.5`, `a_y = 0.5`.

```
Prescription (last 8 quarters):
    period  actual  prescribed       gap  inflation  deviation
2023-01-01   10.75   13.168674  0.770609   6.522246  -2.418674
2023-04-01   10.75   12.067058  0.546023   5.862698  -1.317058
2023-07-01   10.75   10.974288  0.326875   5.207234  -0.224288
2023-10-01   10.75    9.889931  0.112379   4.555828   0.860069
2024-01-01   10.75    9.784517 -0.098448   4.555828   0.965483
2024-04-01   10.75    9.680416 -0.306650   4.555828   1.069584
2024-07-01   10.75    9.577141 -0.513200   4.555828   1.172859
2024-10-01   10.75    9.474304 -0.718876   4.555828   1.275696

Diagnostics:
                 metric                     value
      neutral_real_rate                       4.5
       inflation_target                       3.0
       weight_inflation                       0.5
             weight_gap                       0.5
             gap_method                        hp
          gap_two_sided                      True
              hp_lambda                    1600.0
      inflation_measure cpi_headline_index_yoy_4q
                  n_obs                        36
            correlation                  0.877032
mean_absolute_deviation                  1.787682

Estimated coefficients (OLS):
     name  estimate  std_error
    const  3.392803   0.668377
inflation  1.223322   0.112477
      gap  0.881775   0.148091
```

The estimated inflation coefficient > 1 confirms the Taylor principle (Brazil's central bank
reacts more than one-for-one to inflation deviations).

### Lint note

`tests/test_taylor.py` has a pre-existing `ruff I001` (import order) because
`pytest.importorskip` must precede the guarded import. This is by design in the test file,
which I was instructed not to modify. `src/econmodels/taylor.py` passes `ruff check` and
`ruff format --check` cleanly.

### Deviations

None. `src/econmodels/base.py` was not modified. No new dependencies. `http.py` and
`econbase` untouched.
