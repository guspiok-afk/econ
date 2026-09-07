# ADR-0008 — Weekly frequency convention: 7-day relative grid (7D)

Date: 2026-09-06 · Status: accepted

## Context
The data contract (`docs/CONTRACT.md`) specifies that `period` represents the START of a period
for aggregate/frequency series (M/Q/A/W) or the observation date for daily/business series (D/B).
However, for weekly series (`freq="W"`), four conflicting conventions existed in the codebase and stored data:
1. `src/econbase/transforms.py`: `_PANDAS_RULE["W"] = "W"` (which in pandas defaults to `W-SUN`, anchored to Sunday period ends).
2. `src/econmodels/base.py`: `_GRID["W"] = "W-MON"` (enforcing a fixed Monday period start).
3. `fred:ICSA` in store: observations labeled on Saturdays (e.g., 1967-01-07, 1967-01-14, 1967-01-21).
4. `fred:TOTCI` in store: observations labeled on Wednesdays (e.g., 1973-01-03, 1973-01-10, 1973-01-17).

As a result, calling `check_frequency(panel_ICSA, "W")` failed with `PanelError: the panel is not W: 3113 period(s) fall off the W grid, first 1967-01-07`, rejecting all legitimate weekly observations and preventing models from declaring `freq="W"`.

### Distinction Between Flow and Point-in-Time Stock Series
Weekly series fall into two distinct nature categories:
- **Weekly Flows (e.g., `ICSA` - Initial Claims):** A cumulative aggregate over a 7-day window ending on the reported date (typically Saturday). Forced relabeling to the start of the week (e.g., previous Sunday/Monday) without accounting for the end-date nature distorts the temporal meaning of the series.
- **Weekly Stocks (e.g., `TOTCI` - Commercial and Industrial Loans):** Point-in-time snapshot measurements taken on a specific day of the week (e.g., Wednesday). These are not aggregated over 7 days; the label represents the exact date the balance was measured.

Forcing a single fixed calendar day-of-week anchor (such as mandatory `W-MON` or `W-SUN`) onto all weekly series misrepresents one or both types of data, or causes grid validation to fail for native source calendars.

## Decision
1. **Adopt "7D" (7-day relative spacing) as the convention for `freq="W"`:**
   - In `src/econmodels/base.py`: set `_GRID["W"] = "7D"`. `check_frequency` verifies that consecutive periods in a weekly panel are spaced exactly 7 days apart (`freq="7D"`) starting from the minimum date present in the panel (`index.min()`), rather than enforcing a fixed calendar day of the week (such as Monday).
   - In `src/econbase/transforms.py`: set `_PANDAS_RULE["W"] = "7D"`.

2. **Respect native source labels without forcing alignment:**
   - Both Saturday-ending flows (`ICSA`) and Wednesday point-in-time stocks (`TOTCI`) retain their native observation dates.
   - Under `freq="7D"`, any regular weekly series spaced 7 days apart passes `check_frequency(panel, "W")` regardless of which day of the week it starts/ends on.

## Migration Strategy for Lake Data
Since this decision adopts `7D` relative spacing that matches native source labeling (Saturdays for `ICSA`, Wednesdays for `TOTCI`), **no data rewriting or lake migration is required** for existing stored weekly series. Raw observations in `lake/observations/` already follow exact 7-day intervals.
If future developments require normalizing weekly period starts to period-beginning dates in line with `CONTRACT.md` for weekly flows, a separate data migration issue will be opened. Writing to the store is explicitly out of scope for this PR.

## Consequences
- `check_frequency(panel_ICSA, "W")` and `check_frequency(panel_TOTCI, "W")` both pass successfully.
- Models can now declare `ConceptRequest(freq="W")` and validate weekly panels.
- `transforms.py` and `econmodels/base.py` agree with each other and are fully consistent.
