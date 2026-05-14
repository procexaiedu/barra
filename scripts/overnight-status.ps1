#Requires -Version 5.1
<#
.SYNOPSIS
  Resume o log overnight mais recente em .claude/logs/.
.DESCRIPTION
  Le o log mais novo de overnight-*.log e exibe:
   - quantas tasks moveram para Review (PASS)
   - quantas needs-rework / blocked / timeout
   - IDs e titulos por categoria
   - branches unicos criados
   - duracao total e numero de runs
.PARAMETER LogPath
  Caminho explicito do log a inspecionar. Se omitido, pega o mais recente.
.EXAMPLE
  powershell -NoProfile -File C:\barra\scripts\overnight-status.ps1
#>
[CmdletBinding()]
param(
    [string]$LogPath
)

$ErrorActionPreference = 'Stop'

$logsDir = 'C:\barra\.claude\logs'

if (-not $LogPath) {
    # Busca recursiva: layout antigo ($logsDir\overnight-*.log) e novo
    # ($logsDir\overnight\<data>\overnight-*.log).
    $latest = Get-ChildItem -Path $logsDir -Filter 'overnight-*.log' -Recurse -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending |
              Select-Object -First 1
    if (-not $latest) {
        Write-Warning "Nenhum overnight-*.log encontrado em $logsDir (incluindo subpastas)"
        return
    }
    $LogPath = $latest.FullName
}

if (-not (Test-Path $LogPath)) {
    Write-Warning "Log nao encontrado: $LogPath"
    return
}

$content = Get-Content -Path $LogPath -Raw

Write-Host ""
Write-Host "=== overnight-status ==="
Write-Host "log:    $LogPath"
$fi = Get-Item $LogPath
$sizeKb = [math]::Round($fi.Length/1KB,1)
Write-Host "size:   $sizeKb KB"
Write-Host "mtime:  $($fi.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host ""

# LOG_ITER aparece em dois formatos:
#  1. Linha solta (claude --output-format text):  LOG_ITER {"ts":"...","review_status":"PASS",...}
#  2. Embutido em stream-json (escapado):        ...\"text\":\"...LOG_ITER {\\"ts\\":\\"...\\",...}\\n\"...
# O regex aceita ambos: captura `LOG_ITER {...}` (objeto JSON flat sem nested {}).
# Pós-processamento: se o conteudo veio escapado, desescapa \" -> " antes de ConvertFrom-Json.
$iterLines = [regex]::Matches($content, 'LOG_ITER (\{[^{}]+\})') | ForEach-Object { $_.Groups[1].Value }
$iters = @()
foreach ($l in $iterLines) {
    $raw = $l
    if ($raw -match '\\"') {
        $raw = $raw -replace '\\"', '"'
    }
    try {
        $iters += ($raw | ConvertFrom-Json)
    } catch {
        # linha mal formada - ignorar
    }
}

if (-not $iters -or $iters.Count -eq 0) {
    Write-Host "Nenhuma iteracao registrada (LOG_ITER) - skill nao emitiu logs estruturados ou o run falhou cedo."
} else {
    $byStatus = $iters | Group-Object -Property review_status

    Write-Host "Iteracoes totais: $($iters.Count)"
    foreach ($g in $byStatus | Sort-Object Name) {
        Write-Host ("  {0,-22} {1}" -f $g.Name, $g.Count)
    }
    Write-Host ""

    $pass      = $iters | Where-Object { $_.review_status -eq 'PASS' }
    $rework    = $iters | Where-Object { $_.review_status -eq 'needs-rework' }
    $blocked   = $iters | Where-Object { $_.review_status -eq 'blocked-clarification' }
    $nothing   = $iters | Where-Object { $_.review_status -eq 'nothing-to-do' }
    $humanOnly = $iters | Where-Object { $_.review_status -eq 'human-validation-only' }
    $timeout   = $iters | Where-Object { $_.review_status -eq 'timeout' }
    $trunc     = $iters | Where-Object { $_.review_status -eq 'descricao-truncada' }
    $excep     = $iters | Where-Object { $_.review_status -eq 'exception' }

    function Show-Group($label, $items) {
        if (-not $items -or $items.Count -eq 0) { return }
        Write-Host "--- $label ($($items.Count)) ---"
        foreach ($it in $items) {
            $idVal  = if ($it.task_id) { $it.task_id.Substring(0, [Math]::Min(8, $it.task_id.Length)) } else { '????????' }
            $brVal  = if ($it.branch)  { $it.branch } else { '-' }
            $titVal = if ($it.titulo)  { $it.titulo } else { '(sem titulo)' }
            $durVal = if ($it.duracao_seg) { "$($it.duracao_seg)s" } else { '?s' }
            $line   = '  {0} | {1} | {2} | {3}' -f $idVal, $durVal, $brVal, $titVal
            Write-Host $line
        }
        Write-Host ""
    }

    Show-Group 'Movidas para Review (PASS)'              $pass
    Show-Group 'Nothing-to-do (ja em main)'              $nothing
    Show-Group 'Human-validation-only (manual externo)'  $humanOnly
    Show-Group 'Needs-rework'                            $rework
    Show-Group 'Blocked-clarification'                   $blocked
    Show-Group 'Timeout'                                 $timeout
    Show-Group 'Descricao truncada'                      $trunc
    Show-Group 'Exception'                               $excep

    $branches = $iters | Where-Object { $_.branch -and $_.branch -ne 'null' } | ForEach-Object { $_.branch } | Sort-Object -Unique
    if ($branches.Count -gt 0) {
        Write-Host ('--- Branches criados ({0}) ---' -f $branches.Count)
        foreach ($b in $branches) { Write-Host "  $b" }
        Write-Host ""
    }
}

$runStarts   = ([regex]::Matches($content, '::RUN_\d+_START::')).Count
$runEnds     = ([regex]::Matches($content, '::RUN_\d+_END::')).Count
$drained     = $content -match 'DRAINED - fila vazia'
$footerMatch = [regex]::Match($content, 'tempo total:\s+(\d+)s')

Write-Host "--- Loop overnight ---"
Write-Host "runs iniciados:   $runStarts"
Write-Host "runs encerrados:  $runEnds"
Write-Host "fila esvaziada:   $drained"
if ($footerMatch.Success) {
    $tot = [int]$footerMatch.Groups[1].Value
    $totMin = [math]::Round($tot/60.0,1)
    Write-Host "tempo total:      ${tot}s (${totMin}min)"
}
Write-Host ""
