#Requires -Version 5.1
<#
.SYNOPSIS
  Roda /processa-fila-barra em loop headless via `claude -p`.
.DESCRIPTION
  Cada INVOCAÇÃO de `claude -p` executa o skill, que drena ate
  MAX_ITERATIONS_POR_SESSAO (20) tasks internamente.

  Este loop externo faz no maximo -MaxInvocations chamadas, com sleep
  30s entre elas, encerrando cedo se detectar "fila vazia, encerrando"
  na ultima invocacao.

  Use -MaxTasks <N> para impor um teto adicional de tasks totais (o
  loop encerra ao atingir N, mesmo que -MaxInvocations ainda permita
  mais).

  Use -MaxWallMinutes <N> para um teto de tempo de parede: o loop
  encerra antes de iniciar a proxima invocacao se ja decorreu mais que
  N minutos desde o inicio. Alem disso, 2 invocacoes consecutivas que
  nao produziram nenhum LOG_ITER (provavel quota/auth falhou) abortam
  o loop para nao desperdicar as restantes.
.PARAMETER MaxInvocations
  Maximo de invocacoes de `claude -p`. Default 30. Cada invocacao pode
  drenar ate 20 tasks. Alias: -MaxRuns (compatibilidade).
.PARAMETER MaxTasks
  Teto adicional de tasks totais processadas (PASS + rework + blocked +
  timeout + exception + trunc). 0 = sem teto. Default 0.
.PARAMETER MaxWallMinutes
  Teto de tempo de parede em minutos. Antes de iniciar cada nova
  invocacao, se o tempo decorrido desde o inicio do loop for >= a este
  valor, o loop encerra. 0 = sem teto. Default 0.
.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-loop.ps1 -MaxInvocations 1
  # Roda 1 invocacao, drena ate 20 tasks dentro dela.
.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-loop.ps1 -MaxInvocations 30 -MaxTasks 5
  # Roda ate 30 invocacoes, mas para no momento em que 5 tasks foram processadas.
.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-loop.ps1 -MaxInvocations 30 -MaxWallMinutes 240
  # Roda ate 30 invocacoes OU 4 horas de wall-clock, o que vier primeiro.
.NOTES
  Sem push, sem merge, sem PR. Status terminal de cada task e "Review".
#>
[CmdletBinding()]
param(
    [Alias('MaxRuns')]
    [int]$MaxInvocations = 30,

    [int]$MaxTasks = 0,

    [int]$MaxWallMinutes = 0
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$PSDefaultParameterValues['Out-File:Encoding']    = 'utf8'
$PSDefaultParameterValues['Add-Content:Encoding'] = 'utf8'

$repoRoot = 'C:\barra'
Set-Location -Path $repoRoot
$logsDir  = Join-Path $repoRoot '.claude\logs'
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $logsDir "overnight-$stamp.log"

# Expoe teto via env var para o skill ler (futuro hook em SKILL.md).
if ($MaxTasks -gt 0) {
    $env:BARRA_OVERNIGHT_MAX_TASKS = "$MaxTasks"
} else {
    Remove-Item Env:BARRA_OVERNIGHT_MAX_TASKS -ErrorAction SilentlyContinue
}

$welcome = @"

=========================================================================
  /processa-fila-barra - overnight loop
=========================================================================
  Vou invocar 'claude -p' ate $MaxInvocations vez(es). Cada invocacao
  drena ate 20 tasks da fila do BarraVIPs. Status terminal por task:
  'Review' no devcontext. SEM merge, SEM push, SEM PR.
"@
if ($MaxTasks -gt 0) {
    $welcome += "`n  Teto adicional: parar ao atingir $MaxTasks task(s) processada(s)."
}
if ($MaxWallMinutes -gt 0) {
    $welcome += "`n  Teto wall-clock: parar apos $MaxWallMinutes minuto(s) decorrido(s)."
} else {
    $welcome += "`n  Teto wall-clock: sem teto."
}
$welcome += @"

  Logs:    $logPath
  Status:  powershell -File scripts\overnight-status.ps1
  Abortar: Ctrl+C
=========================================================================

"@
Write-Host $welcome

$header = @"
=== overnight-loop start ===
ts:              $(Get-Date -Format o)
maxInvocations:  $MaxInvocations
maxTasks:        $(if ($MaxTasks -gt 0) { $MaxTasks } else { 'sem teto' })
maxWallMinutes:  $(if ($MaxWallMinutes -gt 0) { $MaxWallMinutes } else { 'sem teto' })
log:             $logPath
repo:            $repoRoot
PID:             $PID
"@
$header | Out-File -FilePath $logPath -Encoding utf8 -Append

$started        = Get-Date
$totalPass      = 0
$totalBlocked   = 0
$totalRework    = 0
$totalTimeout   = 0
$totalException = 0
$totalTrunc     = 0
$totalNothing   = 0
$totalHumanOnly = 0
$runsExecuted   = 0
$drained         = $false
$hitMaxTasks     = $false
$hitMaxWall      = $false
$hitEmptyStreak  = $false
$emptyRunsStreak = 0

for ($i = 1; $i -le $MaxInvocations; $i++) {
    # Wall-clock budget: corta o loop antes de gastar a proxima invocacao
    # se ja excedeu o teto de minutos definido por -MaxWallMinutes.
    $elapsedMin = ((Get-Date) - $started).TotalMinutes
    if ($MaxWallMinutes -gt 0 -and $elapsedMin -ge $MaxWallMinutes) {
        $msg = "MAX_WALL_MINUTES atingido ($([int]$elapsedMin)/$MaxWallMinutes), encerrando loop"
        Add-Content -Path $logPath -Encoding utf8 -Value $msg
        Write-Host $msg
        $hitMaxWall = $true
        break
    }

    $runStart = Get-Date
    $banner   = "[run $i/$MaxInvocations] $($runStart.ToString('HH:mm:ss')) - starting headless /processa-fila-barra"
    Add-Content -Path $logPath -Encoding utf8 -Value "`n--- $banner ---"
    Write-Host $banner

    $runMarker = "::RUN_${i}_START::"
    Add-Content -Path $logPath -Encoding utf8 -Value $runMarker

    # Executa claude via cmd.exe para isolar do error handling do PS 5.1.
    # `< NUL` evita o warning "no stdin data received in 3s" do CLI; o redirecionamento
    # direto (em vez de `*>> $logPath` + try/catch) impede que linhas de stderr de native
    # exe sejam capturadas como ErrorRecord quando $ErrorActionPreference='Stop'.
    $cmdLine = 'claude -p "/processa-fila-barra" --output-format stream-json --verbose --permission-mode bypassPermissions < NUL >> "' + $logPath + '" 2>&1'
    & cmd.exe /c $cmdLine
    $exitCode = $LASTEXITCODE

    $runEnd      = Get-Date
    $runDuration = [int]($runEnd - $runStart).TotalSeconds

    $endMarker = "::RUN_${i}_END::"
    Add-Content -Path $logPath -Encoding utf8 -Value $endMarker
    Add-Content -Path $logPath -Encoding utf8 -Value "run-exit-code: $exitCode"
    Add-Content -Path $logPath -Encoding utf8 -Value "run-duration-sec: $runDuration"

    $runContent = Get-Content -Path $logPath -Raw
    $runSlice   = $runContent.Substring($runContent.LastIndexOf($runMarker))

    # Aceita ambos formatos do LOG_ITER:
    #  literal:    "review_status":"PASS"
    #  escapado:   \"review_status\":\"PASS\"   (stream-json wrap do claude headless)
    $passCount       = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")PASS(?:"|\\")')).Count
    $reworkCount     = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")needs-rework(?:"|\\")')).Count
    $blockedCount    = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")blocked-clarification(?:"|\\")')).Count
    $timeoutCount    = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")timeout(?:"|\\")')).Count
    $exceptionCount  = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")exception(?:"|\\")')).Count
    $truncCount      = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")descricao-truncada(?:"|\\")')).Count
    $nothingCount    = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")nothing-to-do(?:"|\\")')).Count
    $humanOnlyCount  = ([regex]::Matches($runSlice, '(?:"|\\")review_status(?:"|\\"):(?:"|\\")human-validation-only(?:"|\\")')).Count
    $tasksDone       = $passCount + $reworkCount + $blockedCount + $timeoutCount + $exceptionCount + $truncCount + $nothingCount + $humanOnlyCount

    # Streak de invocacoes sem LOG_ITER algum (provavel quota/auth falhou).
    if ($tasksDone -eq 0) { $emptyRunsStreak++ } else { $emptyRunsStreak = 0 }

    $totalPass      += $passCount
    $totalRework    += $reworkCount
    $totalBlocked   += $blockedCount
    $totalTimeout   += $timeoutCount
    $totalException += $exceptionCount
    $totalTrunc     += $truncCount
    $totalNothing   += $nothingCount
    $totalHumanOnly += $humanOnlyCount
    $runsExecuted++

    $emptySignal = ($runSlice -match 'fila vazia, encerrando')
    $limitSignal = ($runSlice -match 'limite de itera')

    $totalTasksSoFar = $totalPass + $totalRework + $totalBlocked + $totalTimeout + $totalException + $totalTrunc + $totalNothing + $totalHumanOnly
    $summary = "[run $i/$MaxInvocations] $($runEnd.ToString('HH:mm:ss')) - tasks: $tasksDone (PASS:$passCount rework:$reworkCount blocked:$blockedCount timeout:$timeoutCount exception:$exceptionCount trunc:$truncCount nothing:$nothingCount humanOnly:$humanOnlyCount) - dur: ${runDuration}s - exit:$exitCode - acumulado:$totalTasksSoFar"
    Add-Content -Path $logPath -Encoding utf8 -Value $summary
    Write-Host $summary

    if ($exitCode -ne 0 -and $exitCode -ne -1) {
        Add-Content -Path $logPath -Encoding utf8 -Value "ERROR run $i (exit $exitCode)"
        Write-Warning "ERROR run $i (exit $exitCode) - continuando ate MaxInvocations"
    }

    if ($emptySignal) {
        Add-Content -Path $logPath -Encoding utf8 -Value 'DRAINED - fila vazia detectada, encerrando loop overnight'
        Write-Host 'DRAINED - fila vazia detectada, encerrando loop overnight'
        $drained = $true
        break
    }

    if ($MaxTasks -gt 0 -and $totalTasksSoFar -ge $MaxTasks) {
        Add-Content -Path $logPath -Encoding utf8 -Value "MAX_TASKS atingido ($totalTasksSoFar/$MaxTasks), encerrando loop"
        Write-Host "MAX_TASKS atingido ($totalTasksSoFar/$MaxTasks), encerrando loop"
        $hitMaxTasks = $true
        break
    }

    if ($emptyRunsStreak -ge 2) {
        $msg = "[run $i/$MaxInvocations] 2 invocacoes consecutivas sem LOG_ITER - provavelmente quota/auth falhou, encerrando loop"
        Add-Content -Path $logPath -Encoding utf8 -Value $msg
        Write-Host $msg
        $hitEmptyStreak = $true
        break
    }

    if ($limitSignal) {
        Add-Content -Path $logPath -Encoding utf8 -Value "LIMITE_ATINGIDO run $i - sessao parou em 20 iteracoes; proximo run continua a fila"
    }

    if ($i -lt $MaxInvocations) {
        Write-Host '  ...sleep 30s (cache cooldown)'
        Start-Sleep -Seconds 30
    }
}

# Limpa env var de teto para nao vazar pra sessoes subsequentes.
Remove-Item Env:BARRA_OVERNIGHT_MAX_TASKS -ErrorAction SilentlyContinue

$ended      = Get-Date
$totalSecs  = [int]($ended - $started).TotalSeconds
$totalMin   = [math]::Round($totalSecs / 60.0, 1)

$footer = @"

=== overnight-loop fim ===
invocacoes executadas:  $runsExecuted / $MaxInvocations
fila esvaziada:         $drained
parou por MaxTasks:     $hitMaxTasks
parou por MaxWall:      $hitMaxWall
parou por empty-streak: $hitEmptyStreak
tasks Review (PASS):    $totalPass
tasks needs-rework:     $totalRework
tasks blocked:          $totalBlocked
tasks timeout:          $totalTimeout
tasks exception:        $totalException
tasks descricao-trunc:  $totalTrunc
tasks nothing-to-do:    $totalNothing
tasks human-validation: $totalHumanOnly
tempo total:            ${totalSecs}s (${totalMin}min)
log:                    $logPath
"@
Add-Content -Path $logPath -Encoding utf8 -Value $footer
Write-Host $footer
