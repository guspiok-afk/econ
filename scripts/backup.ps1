<#
.SYNOPSIS
  Mirror the econbase data directory (closed files only) to a backup folder.

.DESCRIPTION
  Copies raw/ and lake/ with robocopy /MIR, excluding the live DuckDB file, its WAL and the
  in-flight staging directory. Safe to point at a cloud-synced folder (Google Drive, OneDrive):
  the files copied are closed Parquet/gzip files, never a live database (ADR-0003).

.PARAMETER Target
  Destination folder, e.g. 'G:\Meu Drive\econbase-backup'.

.PARAMETER Source
  Data directory. Defaults to $env:ECONBASE_DATA_DIR or %LOCALAPPDATA%\econbase\data.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup.ps1 -Target 'G:\Meu Drive\econbase-backup'
#>
param(
  [Parameter(Mandatory = $true)][string]$Target,
  [string]$Source = ""
)

if ([string]::IsNullOrWhiteSpace($Source)) {
  if (-not [string]::IsNullOrWhiteSpace($env:ECONBASE_DATA_DIR)) { $Source = $env:ECONBASE_DATA_DIR }
  else { $Source = Join-Path $env:LOCALAPPDATA "econbase\data" }
}

if (-not (Test-Path $Source)) { Write-Error "source not found: $Source"; exit 2 }
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
Write-Output "backup ok -> $Target (robocopy code $worst); log: $log"
exit 0
