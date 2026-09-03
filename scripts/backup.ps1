<#
.SYNOPSIS
  Mirror the econbase data directory (closed files only) to a backup folder.

.DESCRIPTION
  Copies raw/ and lake/ with robocopy /MIR, excluding the live DuckDB file, its WAL and the
  in-flight staging directory. Safe to point at a cloud-synced folder (Google Drive, OneDrive):
  the files copied are closed Parquet/gzip files, never a live database (ADR-0003).

  The source directory is resolved in this order: -Source parameter, ECONBASE_DATA_DIR
  environment variable, ECONBASE_DATA_DIR in the repository .env file, then the default
  %LOCALAPPDATA%\econbase\data. This mirrors how the Python settings resolve it.

.PARAMETER Target
  Destination folder, e.g. 'G:\Meu Drive\econbase-backup'. raw\ and lake\ are created inside it;
  nothing outside those two subfolders is ever touched or deleted.

.PARAMETER Source
  Data directory. Optional (see resolution order above).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup.ps1 -Target 'G:\Meu Drive\econbase-backup'
#>
param(
  [Parameter(Mandatory = $true)][string]$Target,
  [string]$Source = ""
)

$repoRoot = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $repoRoot ".env"

if ([string]::IsNullOrWhiteSpace($Source) -and -not [string]::IsNullOrWhiteSpace($env:ECONBASE_DATA_DIR)) {
  $Source = $env:ECONBASE_DATA_DIR
}
if ([string]::IsNullOrWhiteSpace($Source) -and (Test-Path $envFile)) {
  foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*ECONBASE_DATA_DIR\s*=\s*(.+?)\s*$') {
      $Source = $Matches[1].Trim().Trim('"').Trim("'")
    }
  }
}
if ([string]::IsNullOrWhiteSpace($Source)) {
  $Source = Join-Path $env:LOCALAPPDATA "econbase\data"
}

if (-not (Test-Path $Source)) { Write-Error "source not found: $Source"; exit 2 }
if (-not (Test-Path (Join-Path $Source "lake"))) { Write-Error "not an econbase data dir (no lake\): $Source"; exit 2 }
New-Item -ItemType Directory -Force -Path $Target | Out-Null

$logDir = Join-Path (Split-Path $Source -Parent) "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("backup-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))

$exitCodes = @()
foreach ($sub in @("raw", "lake")) {
  $from = Join-Path $Source $sub
  $to = Join-Path $Target $sub
  if (-not (Test-Path $from)) { continue }
  # /MIR mirror, /XD exclude dirs, /XF exclude files, /R:2 retries, /W:5 wait, /NP no progress, /NDL no dir list
  robocopy $from $to /MIR /XD "_staging" /XF "*.duckdb" "*.duckdb.wal" "*.tmp-*" /R:2 /W:5 /NP /NDL /LOG+:$log | Out-Null
  $exitCodes += $LASTEXITCODE
}

# robocopy: 0-7 success (with copies/extras), >= 8 failure
$worst = ($exitCodes | Measure-Object -Maximum).Maximum
if ($null -eq $worst) { $worst = 0 }
if ($worst -ge 8) {
  Write-Error "backup finished with errors (robocopy code $worst); see $log"
  exit 1
}
Write-Output "backup ok: $Source -> $Target (robocopy code $worst); log: $log"
exit 0
