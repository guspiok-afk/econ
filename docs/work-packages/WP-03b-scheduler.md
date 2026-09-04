# WP-03b — The daily routine and the scheduler

| Field | Value |
|---|---|
| Status | done |
| Executor | `agent:claude` (the single writer; ADR-0003) |
| Branch | `wp/03b-scheduler` |
| Depends on | WP-02a..e (merged), WP-03a (merged) |

## Goal

Make the base keep itself up to date. Twice a day, without being asked.

## Result

Delivered. 9 new tests, 276 in the whole suite, ruff clean.

`scripts/daily.ps1` runs four steps in an order that matters:

1. **fetch** — the only slow step; a series that fails is recorded and does not stop the others
2. **rebuild the query cache** — the DuckDB views name concrete Parquet files and the fetch has
   just replaced them, so a query made after a fetch would otherwise read files the manifest no
   longer lists
3. **check freshness** — never fatal; a late series is information, not a failure
4. **back up** — last, so it copies a consolidated state

`$ErrorActionPreference = "Continue"` is deliberate: one source being down must not prevent the
backup of the other fifty-four series. Each step is timed and logged to a file beside the data
directory, with the CLI's own output indented under it, and logs older than sixty days are
removed.

If `agent-kit` is installed, the routine also refreshes `.pma/state.json`, so the manager above
sees the new state without anyone remembering to run it.

### The failure this package was most likely to have

A renamed CLI command would break the twice-daily run **silently**: the script keeps going by
design, so the only symptom would be data that quietly stopped arriving. `tests/test_daily_script.py`
ties the script to the command surface — every command it calls must still be registered, the
three that matter must still be called, and they must appear in the right order.

### Also delivered

`docs/OPERATION.md`: how to switch the schedule on, where to look when something did not
arrive, a table of symptoms and their causes, and the one-time backup restore test. A backup
never tested is not a backup.

## For the maintainer

The scheduled tasks are created on your machine, not by this package:

```powershell
schtasks /Create /TN "econbase-manha" /SC DAILY /ST 09:15 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\econ\scripts\daily.ps1 -Backup 'G:\Meu Drive\econbase-backup'"
schtasks /Create /TN "econbase-tarde" /SC DAILY /ST 18:45 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\econ\scripts\daily.ps1 -Backup 'G:\Meu Drive\econbase-backup'"
schtasks /Run /TN "econbase-manha"
```
