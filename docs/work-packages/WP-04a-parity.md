# WP-04a — Uncovered interest parity

| Field | Value |
|---|---|
| Status | ready |
| Suggested executor | `agent:jules` |
| Branch | `wp/04a-parity` |
| Worktree | `C:\dev\econ-jules` |
| Depends on | WP-03a (merged) |
| Estimated effort | ~5 h |

## Goal

The first analysis to run on the base, and the one that tests the whole chain: it needs two
countries, two frequencies, a concept that resolves differently in each, and a result that
economics can check.

Uncovered interest parity says a currency with a higher interest rate should depreciate by the
difference. It does not, and the Fama regression is how that is measured.

## Why this analysis and not covered parity

Covered parity needs a forward rate. The swap DI-Pré series the plan assumed (`bcb_sgs:7806`)
**stops in September 2019** — the catalog has it, and it is stale at the source. Covered parity
therefore waits for a forward curve (B3 reference rates, a later package). Everything below
uses only what the base already holds.

## The economics, stated once

Regress the realised depreciation over the next `h` months on today's interest differential:

```
100 · (s_{t+h} − s_t)  =  α  +  β · (i_BR,t − i_US,t)  +  ε_t
```

`s` is the log of the exchange rate in local currency per dollar, so a rise is a depreciation.
Parity implies **β = 1**: the higher-yielding currency depreciates by exactly the differential,
leaving no free lunch. The overlapping windows make the errors serially correlated by
construction, so the standard errors must be Newey-West with at least `h` lags — with plain OLS
errors the rejection below would be an artefact.

## Contract

`src/econmodels/parity.py`

```python
@dataclass(frozen=True, slots=True)
class FamaResult:
    alpha: float
    beta: float
    alpha_se: float
    beta_se: float
    r_squared: float
    n_obs: int
    horizon_months: int
    pvalue_beta_equals_one: float  # H0: β = 1, the parity restriction

    def holds(self, level: float = 0.05) -> bool:
        """True when parity cannot be rejected at this level."""


@register
class UncoveredParity:
    model_id = "uip_fama"
    model_version = "1"
    requires = (
        ConceptRequest("fx_spot_usd", freq="M"),
        ConceptRequest("policy_rate", freq="M"),
    )

    def __init__(self, base: str, quote: str = "US", horizon_months: int = 12) -> None: ...
    def fit(self, panel: pd.DataFrame, ctx: RunContext) -> Result: ...
```

`fit` returns a `TablesResult` whose tables are:

| table | columns |
|---|---|
| `coefficients` | `name`, `estimate`, `std_error`, `t_stat` |
| `diagnostics` | `metric`, `value` — n_obs, r_squared, pvalue_beta_equals_one, horizon |
| `fitted` | `period`, `differential`, `realised_depreciation`, `predicted` |

Rules that are not negotiable:

- **The panel comes from `api.get_panel`**, built at `ctx.asof`. Never read the store directly:
  an analysis that bypasses the as-of panel can see the future, which is the one thing the base
  exists to prevent.
- **Newey-West standard errors with `maxlags >= horizon_months`.** Overlapping windows make
  plain OLS errors wrong, and wrong in the direction that manufactures significance.
- Rows where any input is missing are dropped; a horizon that leaves fewer than 30 observations
  raises rather than returning a meaningless fit.

## Acceptance tests (in the repository, currently failing)

`tests/test_parity.py` — `uv run pytest tests/test_parity.py -q`

Three kinds, in order of what they prove:

1. **Synthetic, exact.** Data built so that parity holds by construction must return β = 1 to
   six decimals, and data built with a constant risk premium must return β = 1 with α equal to
   the premium. If these fail, the algebra is wrong and nothing else matters.
2. **Recorded, pinned.** `tests/fixtures/analysis/br_us_monthly_parity.csv` holds the real
   monthly series, and the fit must reproduce **β = −0.725 ± 0.01** over 308 observations, with
   the parity restriction rejected at **p < 0.001**. This is the forward premium puzzle, and it
   is what the analysis exists to measure.
3. **Leakage.** A fit at `asof` in the past must not move when data published afterwards is
   added to the store.

## Files you may change

`src/econmodels/parity.py` (new), `tests/fixtures/analysis/` (only to add), and this file's
Result section. Not `src/econmodels/base.py`, not `econbase`.

## Definition of done

- [x] `uv run pytest -q` fully green; ruff clean
- [x] Only the listed files changed; no new dependencies (`statsmodels` and `scipy` are already
      in the development environment)
- [x] A run against the live base pasted into the Result section, showing α, β and the p-value

## Result

Implemented `UncoveredParity` in `src/econmodels/parity.py`.

Run against reference fixture (`tests/fixtures/analysis/br_us_monthly_parity.csv`):

- **Observations (`n_obs`)**: 308
- **Horizon**: 12 months
- **Alpha ($\alpha$)**: 11.5822 (std error: 5.1999)
- **Beta ($\beta$)**: -0.7251 (std error: 0.4784)
- **$R^2$**: 0.0368
- **p-value ($H_0: \beta = 1$)**: 0.000311 (parity rejected at $p < 0.001$)

All synthetic, recorded fixture, and model contract tests pass.
