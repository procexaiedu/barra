#Requires -Version 5.1
<#
.SYNOPSIS
  Vigia o log do overnight atual e dispara sessao de revisao batch
  (claude -p headless) automaticamente quando o overnight terminar.
.DESCRIPTION
  Roda em background. A cada 30s checa o log mais recente em
  .claude\logs\overnight-*.log. Quando detecta um dos sinais terminais:
    - "DRAINED - fila vazia"
    - "MAX_WALL_MINUTES atingido"
    - "=== overnight-loop fim ==="
    - "MAX_TASKS atingido"
  encerra polling e dispara:
    claude -p <conteudo de prompt-revisao-batch.md> --output-format stream-json
  Log de saida em .claude\logs\auto-revisao-<timestamp>.log.

  Encerra naturalmente apos disparar a sessao de revisao.
.PARAMETER LogPath
  Caminho explicito do log overnight a vigiar. Default: mais recente
  em .claude\logs\overnight-*.log.
.PARAMETER PromptPath
  Caminho do prompt em markdown. Default:
  .claude\state\prompt-revisao-batch.md
.PARAMETER PollIntervalSec
  Intervalo de polling. Default 30s.
.PARAMETER MaxWaitMinutes
  Tempo maximo de espera (defesa contra runaway). Default 360 (6h).
.EXAMPLE
  Start-Process powershell -ArgumentList '-NoProfile','-File','C:\barra\scripts\auto-revisar-pos-overnight.ps1' -WindowStyle Minimized
#>
[CmdletBinding()]
param(
    [string]$LogPath,
    [string]$PromptPath = 'C:\barra\.claude\state\prompt-revisao-batch.md',
    [int]$PollIntervalSec = 30,
    [int]$MaxWaitMinutes = 360
)

$ErrorActionPreference = 'Continue'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$logsDir = 'C:\barra\.claude\logs'
if (-not $LogPath) {
    $latest = Get-ChildItem -Path $logsDir -Filter 'overnight-*.log' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Output "ABORT: nenhum log overnight-*.log em $logsDir"
        exit 1
    }
    $LogPath = $latest.FullName
}

if (-not (Test-Path $PromptPath)) {
    Write-Output "ABORT: prompt nao encontrado em $PromptPath"
    exit 1
}

# Sinais terminais
$signals = @(
    'DRAINED - fila vazia',
    'MAX_WALL_MINUTES atingido',
    'MAX_TASKS atingido',
    '=== overnight-loop fim ==='
)

$start  = Get-Date
$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$autoLog = Join-Path $logsDir "auto-revisao-$stamp.log"

$header = @"
=== auto-revisar-pos-overnight inicio ===
ts:              $($start.ToString('o'))
overnight log:   $LogPath
prompt:          $PromptPath
poll interval:   ${PollIntervalSec}s
max wait:        ${MaxWaitMinutes}min
output deste:    $autoLog
"@
$header | Out-File -FilePath $autoLog -Encoding utf8 -Append
Write-Output $header

$iter = 0
$triggered = $false
$matchedSignal = $null

while (-not $triggered) {
    $iter++
    $elapsed = ((Get-Date) - $start).TotalMinutes
    if ($elapsed -ge $MaxWaitMinutes) {
        $msg = "MAX_WAIT_MINUTES atingido ($([int]$elapsed) min) sem sinal terminal - encerrando sem disparar"
        Add-Content -Path $autoLog -Encoding utf8 -Value $msg
        Write-Output $msg
        exit 2
    }

    try {
        $content = Get-Content -Path $LogPath -Raw -ErrorAction Stop
        foreach ($sig in $signals) {
            if ($content -match [regex]::Escape($sig)) {
                $matchedSignal = $sig
                $triggered = $true
                break
            }
        }
    } catch {
        Add-Content -Path $autoLog -Encoding utf8 -Value "WARN iter ${iter}: leitura do log falhou: $($_.Exception.Message)"
    }

    if (-not $triggered) {
        Start-Sleep -Seconds $PollIntervalSec
    }
}

$detected = Get-Date
$waitMin = [math]::Round(($detected - $start).TotalMinutes, 1)
$msg = "SINAL DETECTADO apos $waitMin min: '$matchedSignal' - disparando claude -p"
Add-Content -Path $autoLog -Encoding utf8 -Value ""
Add-Content -Path $autoLog -Encoding utf8 -Value $msg
Write-Output $msg

# Dispara claude -p headless. Em vez de tentar passar o prompt inteiro inline
# (~8KB, risco de estourar limite de comando do Windows), passamos uma instrucao
# minima que manda o claude ler e seguir o arquivo de prompt literal.
$claudeLog = Join-Path $logsDir "auto-revisao-claude-$stamp.log"
Add-Content -Path $autoLog -Encoding utf8 -Value "claude log: $claudeLog"

$inlineInstrucao = "Leia o arquivo $PromptPath na integra e siga exatamente as instrucoes literais dele. Esse arquivo eh seu briefing completo. Nao pergunte confirmacoes - execute ate o relatorio final."

$cmdLine = 'claude -p "' + $inlineInstrucao + '" --output-format stream-json --verbose --permission-mode bypassPermissions < NUL >> "' + $claudeLog + '" 2>&1'
Add-Content -Path $autoLog -Encoding utf8 -Value "comando: $cmdLine"

$runStart = Get-Date
& cmd.exe /c $cmdLine
$exitCode = $LASTEXITCODE
$runEnd = Get-Date
$runDur = [int]($runEnd - $runStart).TotalSeconds

$footer = @"
=== auto-revisar-pos-overnight fim ===
sinal detectado:      $matchedSignal
tempo de espera:      ${waitMin}min
claude exit code:     $exitCode
claude duracao:       ${runDur}s
claude log:           $claudeLog
"@
$footer | Out-File -FilePath $autoLog -Encoding utf8 -Append
Write-Output $footer

exit $exitCode
