#Requires -Version 5.1
<#
.SYNOPSIS
  Roda /processa-fila-agente em loop headless via `claude -p`.

.DESCRIPTION
  Analogo de overnight-loop.ps1, mas para a fila do AGENTE (docs/agente/fila-agente.yml).
  Cada invocacao de `claude -p "/processa-fila-agente"` drena ate
  MAX_ITERATIONS_POR_SESSAO (7) marcos. Loop externo faz ate -MaxInvocations
  chamadas com sleep 60s entre elas (marcos sao mais pesados que tasks de UI).

  Sinais terminais detectados em log:
    "fila vazia, encerrando"       -> aborta o loop com codigo 0
    "limite atingido"              -> aborta o loop com codigo 0
    nenhum LOG_ITER_AGENTE em 2 invocacoes consecutivas -> aborta (quota/auth)

.PARAMETER MaxInvocations
  Maximo de invocacoes de `claude -p`. Default 5 (M0..M6 cabem em 1-3 invocacoes
  na pratica; 5 da folga). Cada invocacao pode drenar ate 7 marcos.

.PARAMETER MaxMarcos
  Teto adicional de marcos totais processados (PASS + rework + eval-failed + ...).
  0 = sem teto. Default 0.

.PARAMETER MaxWallMinutes
  Teto wall-clock em minutos. 0 = sem teto. Default 0.

.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-agente.ps1 -MaxInvocations 1
  # Drena ate 7 marcos em uma invocacao.

.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-agente.ps1 -MaxInvocations 3 -MaxMarcos 2
  # Ate 3 invocacoes, mas para apos 2 marcos processados.

.NOTES
  Sem push, sem merge, sem PR. Status terminal de cada marco eh "Review" no YAML.
#>
[CmdletBinding()]
param(
    [int]$MaxInvocations = 5,
    [int]$MaxMarcos = 0,
    [int]$MaxWallMinutes = 0
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$PSDefaultParameterValues['Out-File:Encoding']    = 'utf8'
$PSDefaultParameterValues['Add-Content:Encoding'] = 'utf8'

$repoRoot = 'C:\barra'
Set-Location -Path $repoRoot
$logsDir = Join-Path $repoRoot '.claude\logs'
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $logsDir "overnight-agente-$stamp.log"

# Expoe teto via env var para o skill (lera em iteracoes futuras)
if ($MaxMarcos -gt 0) {
    $env:BARRA_AGENTE_OVERNIGHT_MAX_MARCOS = "$MaxMarcos"
} else {
    Remove-Item Env:BARRA_AGENTE_OVERNIGHT_MAX_MARCOS -ErrorAction SilentlyContinue
}

$welcome = @"

=========================================================================
  /processa-fila-agente - overnight loop (M0..M6)
=========================================================================
  Vou invocar 'claude -p' ate $MaxInvocations vez(es). Cada invocacao
  drena ate 7 marcos. Status terminal por marco: 'Review' no YAML.
  SEM merge, SEM push, SEM PR.
"@
if ($MaxMarcos -gt 0) {
    $welcome += "`n  Teto adicional: parar ao atingir $MaxMarcos marco(s) processado(s)."
}
if ($MaxWallMinutes -gt 0) {
    $welcome += "`n  Teto wall-clock: parar apos $MaxWallMinutes minuto(s) decorrido(s)."
} else {
    $welcome += "`n  Teto wall-clock: sem teto."
}
$welcome += @"

  Logs:    $logPath
  Abortar: Ctrl+C
=========================================================================

"@
Write-Output $welcome
Add-Content -Path $logPath -Value $welcome

$inicio = Get-Date
$invocacao = 0
$marcosProcessados = 0
$vaziasConsecutivas = 0

while ($invocacao -lt $MaxInvocations) {
    # Teto wall-clock
    if ($MaxWallMinutes -gt 0) {
        $decorrido = (Get-Date) - $inicio
        if ($decorrido.TotalMinutes -ge $MaxWallMinutes) {
            $msg = "[$([DateTime]::Now.ToString('s'))] wall-clock teto $MaxWallMinutes min atingido, abortando."
            Write-Output $msg
            Add-Content -Path $logPath -Value $msg
            break
        }
    }

    # Teto marcos
    if ($MaxMarcos -gt 0 -and $marcosProcessados -ge $MaxMarcos) {
        $msg = "[$([DateTime]::Now.ToString('s'))] teto de $MaxMarcos marco(s) atingido, abortando."
        Write-Output $msg
        Add-Content -Path $logPath -Value $msg
        break
    }

    $invocacao++
    $msgInvoc = "[$([DateTime]::Now.ToString('s'))] === Invocacao $invocacao/$MaxInvocations ==="
    Write-Output $msgInvoc
    Add-Content -Path $logPath -Value $msgInvoc

    # Captura stdout + stderr da invocacao
    $tmpOut = New-TemporaryFile
    $proc = Start-Process -FilePath 'claude' `
        -ArgumentList '-p','/processa-fila-agente' `
        -NoNewWindow -PassThru -Wait `
        -RedirectStandardOutput $tmpOut.FullName `
        -RedirectStandardError  ($tmpOut.FullName + '.err')

    $invocOutput = Get-Content -Raw -Path $tmpOut.FullName -Encoding utf8 -ErrorAction SilentlyContinue
    if (-not $invocOutput) { $invocOutput = "" }
    $errOutput = Get-Content -Raw -Path ($tmpOut.FullName + '.err') -Encoding utf8 -ErrorAction SilentlyContinue
    if ($errOutput) { $invocOutput += "`n[STDERR]`n$errOutput" }

    Add-Content -Path $logPath -Value $invocOutput
    Remove-Item $tmpOut.FullName -Force -ErrorAction SilentlyContinue
    Remove-Item ($tmpOut.FullName + '.err') -Force -ErrorAction SilentlyContinue

    # Conta LOG_ITER_AGENTE nesta invocacao
    $logIters = ([regex]::Matches($invocOutput, '(?m)^LOG_ITER_AGENTE ')).Count
    $marcosProcessados += $logIters

    if ($logIters -eq 0) {
        $vaziasConsecutivas++
        $msgWarn = "[$([DateTime]::Now.ToString('s'))] WARN: invocacao sem LOG_ITER_AGENTE (vazias consecutivas: $vaziasConsecutivas)"
        Write-Output $msgWarn
        Add-Content -Path $logPath -Value $msgWarn
    } else {
        $vaziasConsecutivas = 0
    }

    # Sinais terminais
    if ($invocOutput -match 'fila vazia, encerrando' -or `
        $invocOutput -match 'limite atingido' -or `
        $invocOutput -match 'limite de iteracoes atingido') {
        $msg = "[$([DateTime]::Now.ToString('s'))] sinal terminal detectado, encerrando loop."
        Write-Output $msg
        Add-Content -Path $logPath -Value $msg
        break
    }

    if ($vaziasConsecutivas -ge 2) {
        $msg = "[$([DateTime]::Now.ToString('s'))] 2 invocacoes vazias consecutivas, abortando (provavel quota/auth)."
        Write-Output $msg
        Add-Content -Path $logPath -Value $msg
        break
    }

    if ($invocacao -lt $MaxInvocations) {
        Start-Sleep -Seconds 60
    }
}

# Relatorio final
$duracao = (Get-Date) - $inicio
$relatorio = @"

=========================================================================
  Encerramento -- duracao: $([Math]::Round($duracao.TotalMinutes, 1)) min
  Invocacoes: $invocacao / $MaxInvocations
  Marcos processados (LOG_ITER_AGENTE): $marcosProcessados
  Log completo: $logPath
=========================================================================
"@
Write-Output $relatorio
Add-Content -Path $logPath -Value $relatorio

exit 0
