#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$stateDir = 'C:\barra\.claude\state'
$marker   = Join-Path $stateDir 'awaiting-verification'

if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}

$raw = [Console]::In.ReadToEnd()
if (-not [string]::IsNullOrWhiteSpace($raw)) {
    try {
        $event = $raw | ConvertFrom-Json
        if ($event -and $event.stop_hook_active -eq $true) { exit 0 }
    } catch {
    }
}

if (-not (Test-Path $marker)) { exit 0 }

$taskId = ''
try {
    $taskId = (Get-Content -LiteralPath $marker -Raw -ErrorAction Stop).Trim()
} catch {
    $taskId = '<desconhecida>'
}
if ([string]::IsNullOrWhiteSpace($taskId)) { $taskId = '<sem-id>' }

[Console]::Error.WriteLine(
    "Iteracao da task $taskId ainda em andamento - marker awaiting-verification presente. Continue o fluxo ate remover o marker ou marcar a task como blocked.")
exit 2
