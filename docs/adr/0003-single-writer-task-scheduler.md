# ADR-0003 — One writer (Windows Task Scheduler); GitHub Actions runs tests only

Date: 2026-09-03 · Status: accepted

## Context
GitHub Actions cron schedules drift 5–30 minutes routinely and over an hour at peak, and
scheduled workflows are disabled after 60 days without commits. Committing Parquet to git
bloats history and git cannot delta it. The data already lives on the maintainer's machine.

## Decision
`scripts/daily.ps1` (WP-03) run by Windows Task Scheduler is the single writer, calling
`econbase update` then `econbase check`; each run is recorded in `runs`. GitHub Actions runs
lint and tests on push/PR and never touches data. Backup: nightly `robocopy /MIR` of the closed
files (excluding `*.duckdb*` and `_staging/`) to a cloud-synced folder (Google Drive or
OneDrive), which is safe for closed files and unsafe for a live database.

## Consequences
No cloud infrastructure until a remote consumer appears (then: publish `lake/` to object
storage, ~4 h). The laptop must be on for updates; a missed run is visible in `runs`.
