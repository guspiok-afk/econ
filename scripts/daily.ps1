<#
.SYNOPSIS
  A rotina diária: coleta, verifica o frescor, atualiza o cache de consultas e faz o backup.

.DESCRIPTION
  Isto é o escritor único do projeto (docs/adr/0003). O Windows Task Scheduler o chama duas
  vezes por dia; a integração contínua nunca grava dados.

  A ordem importa. A coleta vem primeiro porque é a única etapa que pode demorar; o cache de
  consultas é reconstruído depois dela para não apontar para arquivos que a coleta substituiu; e
  o backup vem por último, para copiar o estado já consolidado.

  Nada aqui interrompe o que vem depois por causa de um problema em uma série. Uma fonte fora do
  ar não deve impedir o backup das outras 54.

.PARAMETER Backup
  Pasta de destino do backup, tipicamente dentro do Google Drive ou do OneDrive. Sem ela, o
  backup é pulado.

.PARAMETER SkipUpdate
  Só verifica, reconstrói e faz backup, sem coletar. Útil para testar o agendamento.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily.ps1 -Backup 'G:\Meu Drive\econbase-backup'
#>
param(
  [string]$Backup = "",
  [switch]$SkipUpdate
)

$ErrorActionPreference = "Continue"   # uma etapa que falha não cancela as seguintes
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}  # acentos legíveis no console
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo                    # o .env e o catálogo são resolvidos a partir daqui

$dataDir = $env:ECONBASE_DATA_DIR
if (-not $dataDir) { $dataDir = Join-Path $env:LOCALAPPDATA "econbase\data" }
$logDir = Join-Path (Split-Path $dataDir -Parent) "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("daily-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))

function Write-Log {
  param([string]$Message)
  $line = "{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Message
  # Write-Host e não Write-Output: dentro de Invoke-Step, a saída padrão vira o valor de retorno
  # da função, e o chamador que descarta esse valor descartaria o registro junto
  Write-Host $line
  Add-Content -Path $log -Value $line -Encoding utf8
}

function Invoke-Step {
  param([string]$Name, [scriptblock]$Body)
  Write-Log "início: $Name"
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    $out = & $Body 2>&1
    $code = $LASTEXITCODE
    foreach ($l in $out) { Add-Content -Path $log -Value "    $l" -Encoding utf8 }
    $sw.Stop()
    Write-Log ("fim:    {0}  ({1:n0}s, saída {2})" -f $Name, $sw.Elapsed.TotalSeconds, $code)
    return $code
  } catch {
    $sw.Stop()
    Write-Log "ERRO em ${Name}: $_"
    return 1
  }
}

Write-Log "repositório $repo | dados $dataDir"

$failures = 0

if (-not $SkipUpdate) {
  # a coleta reporta 1 quando alguma série falhou; as demais foram gravadas assim mesmo
  $code = Invoke-Step "coleta" { uv run python -m econbase.cli update --trigger scheduler }
  if ($code -ne 0) { $failures++; Write-Log "aviso: pelo menos uma série falhou; veja a tabela acima e a tabela runs" }
}

# o cache de consultas nomeia arquivos concretos, então envelhece a cada coleta
$null = Invoke-Step "cache de consultas" { uv run python -m econbase.cli rebuild-db }

# saída 2 significa série parada, não falha de execução: registre e siga
$code = Invoke-Step "frescor" { uv run python -m econbase.cli check }
if ($code -eq 2) { Write-Log "aviso: há séries paradas além do prazo esperado de divulgação" }

if ($Backup) {
  $code = Invoke-Step "backup" { & (Join-Path $PSScriptRoot "backup.ps1") -Target $Backup }
  if ($code -ne 0) { $failures++ }
} else {
  Write-Log "backup pulado (parâmetro -Backup não informado)"
}

# o manifesto que o gerente externo lê; ausente se o agent-kit não estiver instalado
$pma = "C:\dev\agent-kit\scripts\pma-state.ps1"
if (Test-Path $pma) { $null = Invoke-Step "manifesto pma" { & $pma } }

Write-Log "concluído com $failures falha(s) de etapa | log: $log"

# limpa logs com mais de 60 dias
Get-ChildItem $logDir -Filter "daily-*.log" -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-60) } |
  Remove-Item -Force -ErrorAction SilentlyContinue

exit $failures
