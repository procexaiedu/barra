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

.PARAMETER DryRun
  Modo ensaio. Skill roda Plan+Code+Eval normalmente mas NAO atualiza
  fila-agente.yml (status do marco preservado). Util para validar
  mudancas em prompts sem queimar marcos reais. Sinalizado via env var
  BARRA_PIPELINE_DRY_RUN=1.

.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-agente.ps1 -MaxInvocations 1
  # Drena ate 7 marcos em uma invocacao.

.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-agente.ps1 -MaxInvocations 3 -MaxMarcos 2
  # Ate 3 invocacoes, mas para apos 2 marcos processados.

.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-agente.ps1 -MaxInvocations 1 -DryRun
  # Dry-run: marcos sao planejados/codificados, mas YAML nao muda.

.NOTES
  Sem push, sem merge, sem PR. Status terminal de cada marco eh "Review" no YAML.
#>
[CmdletBinding()]
param(
    [int]$MaxInvocations = 5,
    [int]$MaxMarcos = 0,
    [int]$MaxWallMinutes = 0,

    # Modo ensaio (ver Description). Sinaliza skill via env BARRA_PIPELINE_DRY_RUN=1.
    [switch]$DryRun
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
$today  = Get-Date -Format 'yyyy-MM-dd'
$dayDir = Join-Path $logsDir "overnight\$today"
if (-not (Test-Path $dayDir)) {
    New-Item -ItemType Directory -Path $dayDir -Force | Out-Null
}
$histDir = Join-Path $repoRoot '.claude\state\overnight'
if (-not (Test-Path $histDir)) {
    New-Item -ItemType Directory -Path $histDir -Force | Out-Null
}
$histPath = Join-Path $histDir 'runs.jsonl'

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath  = Join-Path $dayDir "overnight-agente-$stamp.log"
$jsonlPath = Join-Path $dayDir "overnight-agente-$stamp.jsonl"

# Helper: append 1 linha JSON ao .jsonl (1 evento por linha).
function Write-Jsonl([hashtable]$obj) {
    $obj['ts'] = (Get-Date -Format 'o')
    $json = $obj | ConvertTo-Json -Compress -Depth 5
    Add-Content -Path $jsonlPath -Encoding utf8 -Value $json
}

# Expoe teto via env var para o skill (lera em iteracoes futuras).
# Convencao: BARRA_PIPELINE_<fila>_<unidade>, alinhado com overnight-loop.ps1.
if ($MaxMarcos -gt 0) {
    $env:BARRA_PIPELINE_AGENTE_MAX_MARCOS = "$MaxMarcos"
} else {
    Remove-Item Env:BARRA_PIPELINE_AGENTE_MAX_MARCOS -ErrorAction SilentlyContinue
}

# Sinaliza dry-run: skill nao atualiza fila-agente.yml; Plan/Code/Eval rodam normais.
if ($DryRun) {
    $env:BARRA_PIPELINE_DRY_RUN = '1'
} else {
    Remove-Item Env:BARRA_PIPELINE_DRY_RUN -ErrorAction SilentlyContinue
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
if ($DryRun) {
    $welcome += "`n  MODO DRY-RUN: BARRA_PIPELINE_DRY_RUN=1 -- fila-agente.yml fica intacto."
}
$welcome += @"

  Logs:    $logPath
  Abortar: Ctrl+C
=========================================================================

"@
Write-Output $welcome
Add-Content -Path $logPath -Value $welcome

# Avisa sobre rebase-blocked pendentes (mesma fonte que overnight-loop).
$rbPath = Join-Path $repoRoot '.claude\state\overnight\rebase-blocked.yml'
if (Test-Path $rbPath) {
    $rbCount = ([regex]::Matches((Get-Content -Raw $rbPath), '(?m)^- branch:')).Count
    if ($rbCount -gt 0) {
        $rbMsg = ">>> AVISO: $rbCount branch(es) em rebase-blocked desde overnight anterior. Veja $rbPath"
        Write-Output $rbMsg
        Add-Content -Path $logPath -Value $rbMsg
    }
}

Write-Jsonl @{
    type = 'start'
    fila = 'agente'
    maxInvocations = $MaxInvocations
    maxMarcos = $MaxMarcos
    maxWallMinutes = $MaxWallMinutes
    dryRun = [bool]$DryRun
    pid = $PID
    log = $logPath
}

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
            Write-Jsonl @{ type='event'; event='max_wall'; elapsedMin=[int]$decorrido.TotalMinutes; cap=$MaxWallMinutes }
            break
        }
    }

    # Teto marcos
    if ($MaxMarcos -gt 0 -and $marcosProcessados -ge $MaxMarcos) {
        $msg = "[$([DateTime]::Now.ToString('s'))] teto de $MaxMarcos marco(s) atingido, abortando."
        Write-Output $msg
        Add-Content -Path $logPath -Value $msg
        Write-Jsonl @{ type='event'; event='max_marcos'; total=$marcosProcessados; cap=$MaxMarcos }
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

    Write-Jsonl @{
        type = 'run'
        run = $invocacao
        marcosDone = $logIters
        cumulative = $marcosProcessados
    }

    # Sinais terminais
    if ($invocOutput -match 'fila vazia, encerrando' -or `
        $invocOutput -match 'limite atingido' -or `
        $invocOutput -match 'limite de iteracoes atingido') {
        $msg = "[$([DateTime]::Now.ToString('s'))] sinal terminal detectado, encerrando loop."
        Write-Output $msg
        Add-Content -Path $logPath -Value $msg
        Write-Jsonl @{ type='event'; event='drained' }
        break
    }

    if ($vaziasConsecutivas -ge 2) {
        $msg = "[$([DateTime]::Now.ToString('s'))] 2 invocacoes vazias consecutivas, abortando (provavel quota/auth)."
        Write-Output $msg
        Add-Content -Path $logPath -Value $msg
        Write-Jsonl @{ type='event'; event='empty_streak'; streak=$vaziasConsecutivas }
        break
    }

    # Deteccao precoce: padroes inequivocos de quota/auth no output da invocacao.
    # Aborta sem esperar 2 vazios consecutivos (cada vazio custa 5-60 min).
    $authPatterns = @(
        'authentication[_ ]?required',
        'invalid[_ ]?api[_ ]?key',
        '\bunauthorized\b',
        '\b401\b.*(auth|unauth)',
        'rate[_ ]?limit',
        'quota[_ ]?exceeded',
        'usage limit reached',
        '\b429\b'
    )
    $authHit = $null
    foreach ($pat in $authPatterns) {
        if ($invocOutput -imatch $pat) { $authHit = $pat; break }
    }
    if ($authHit) {
        $msg = "[$([DateTime]::Now.ToString('s'))] sinal quota/auth detectado ('$authHit'), encerrando loop imediatamente."
        Write-Output $msg
        Add-Content -Path $logPath -Value $msg
        Write-Jsonl @{ type='event'; event='auth_quota'; pattern=$authHit }
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

Write-Jsonl @{
    type = 'end'
    invocacoes = $invocacao
    marcosProcessados = $marcosProcessados
    duracaoMin = [Math]::Round($duracao.TotalMinutes, 1)
}

# Alerta: main local a frente de origin/main (snapshot local, sem fetch).
$commitsAhead = $null
try {
    $out = & git rev-list --count origin/main..main 2>$null
    if ($LASTEXITCODE -eq 0 -and $out -match '^\d+$') { $commitsAhead = [int]$out.Trim() }
} catch {}
if ($commitsAhead -ne $null -and $commitsAhead -gt 0) {
    $alerta = @"

>>> ATENCAO: main local esta $commitsAhead commit(s) a frente de origin/main.
>>>          Revise e rode 'git push origin main' quando pronto.
"@
    Add-Content -Path $logPath -Value $alerta
    Write-Output $alerta
    Write-Jsonl @{ type='event'; event='push_pendente'; commitsAhead=$commitsAhead }
}

# Histórico append-only para tendência ao longo do tempo.
$histRecord = [ordered]@{
    ts = (Get-Date -Format 'o')
    fila = 'agente'
    stampLog = $stamp
    duracaoSec = [int]$duracao.TotalSeconds
    invocacoes = $invocacao
    invocacoesCap = $MaxInvocations
    marcosTotal = $marcosProcessados
    marcosCap = $MaxMarcos
    commitsAheadOrigin = $commitsAhead
    log = $logPath
}
Add-Content -Path $histPath -Encoding utf8 -Value ($histRecord | ConvertTo-Json -Compress -Depth 5)

exit 0
