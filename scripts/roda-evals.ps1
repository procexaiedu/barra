#Requires -Version 5.1
<#
.SYNOPSIS
  Roda evals do agente em api/evals/ e emite resultado JSON estruturado para o
  eval-runner-agente consumir.

.DESCRIPTION
  No P0 (Fase 1 do plano de adocao), este script eh um STUB FUNCIONAL: le os
  JSONL das suites pedidas, conta fixtures e emite resultado "skip" estruturado
  (pass_rate: 0.0, fixtures: <count>, falhas: []) quando o runner Python real
  ainda nao existe.

  No M6, este script chama api/evals/runners/<canonicos|adversariais>/_runner.py
  via `uv run python -m api.evals.runners.<X>` e parseia o JSON de saida.

  Sempre emite JSON em -OutputJson para o eval-runner-agente parsear, mesmo em
  caso de erro -- assim o pipeline trata SKIP/FAIL com motivo claro.

.PARAMETER Suites
  Lista de suites a rodar, separadas por virgula. Caminhos relativos a api/evals/.
  Exemplo: "canonicos/leitura,adversariais/disclosure"

.PARAMETER Threshold
  Pass-rate minimo. Default 0.85.

.PARAMETER Metric
  Metrica especifica (em vez de pass-rate geral). Exemplo: "cache_hit_rate".

.PARAMETER PerCategory
  Se true, threshold deve ser atendido em CADA suite (e nao na media).

.PARAMETER OutputJson
  Caminho do arquivo JSON de saida. Default: $env:TEMP\roda-evals-<ts>.json

.EXAMPLE
  pwsh -File scripts\roda-evals.ps1 -Suites "canonicos/leitura" -Threshold 0.85
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Suites,

    [double]$Threshold = 0.85,

    [string]$Metric = '',

    [bool]$PerCategory = $false,

    [string]$OutputJson = ''
)

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\barra'
$evalsRoot = Join-Path $repoRoot 'api\evals'

if (-not (Test-Path $evalsRoot)) {
    Write-Error "Pasta api/evals nao encontrada: $evalsRoot"
    exit 2
}

if (-not $OutputJson) {
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $OutputJson = Join-Path $env:TEMP "roda-evals-$ts.json"
}

$inicio = Get-Date

$resultadoSuites = [System.Collections.Generic.List[object]]::new()
$suitesList = $Suites.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }

foreach ($suite in $suitesList) {
    $suiteDir = Join-Path $evalsRoot ($suite -replace '/', '\')
    $fixturas = 0
    $arquivos = @()

    if (Test-Path $suiteDir) {
        $arquivos = @(Get-ChildItem -Path $suiteDir -Filter '*.jsonl' -File -ErrorAction SilentlyContinue)
        foreach ($a in $arquivos) {
            $linhas = @(Get-Content -Path $a.FullName -Encoding utf8 -ErrorAction SilentlyContinue | Where-Object { $_.Trim() })
            $fixturas += $linhas.Count
        }
    }

    # P0 stub: nao ha runner Python que execute fixtures. Reporta fixtures contadas
    # mas pass_rate=null para sinalizar SKIP. eval-runner-agente trata isso.
    $resultadoSuites.Add([pscustomobject]@{
        nome      = $suite
        fixtures  = $fixturas
        pass_rate = $null
        falhas    = @()
        nota      = if ($fixturas -eq 0) { "sem fixtures" } else { "runner Python nao implementado (P0 stub)" }
    }) | Out-Null
}

$totalFixtures = ($resultadoSuites | Measure-Object -Property fixtures -Sum).Sum
if (-not $totalFixtures) { $totalFixtures = 0 }

# Decisao SKIP (P0 stub sempre SKIP enquanto runner nao existe)
$decisao = 'SKIP'
$motivo  = "P0: runner Python ainda nao implementado em api/evals/runners/. Total de fixtures encontradas: $totalFixtures."

$duracao = ((Get-Date) - $inicio).TotalSeconds

$saida = [pscustomobject]@{
    decisao      = $decisao
    motivo       = $motivo
    threshold    = $Threshold
    metric       = $Metric
    per_category = $PerCategory
    suites       = $resultadoSuites
    metric_observada = @{}
    duracao_seg  = [Math]::Round($duracao, 1)
    timestamp    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
}

$jsonOut = $saida | ConvertTo-Json -Depth 10
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($OutputJson, $jsonOut, $utf8NoBom)

# Tambem imprime no stdout para visibilidade no log
Write-Output "Resultado: $decisao"
Write-Output "Motivo: $motivo"
Write-Output "Suites avaliadas: $($resultadoSuites.Count)"
foreach ($s in $resultadoSuites) {
    Write-Output ("  {0}: {1} fixtures ({2})" -f $s.nome, $s.fixtures, $s.nota)
}
Write-Output "Total fixtures: $totalFixtures"
Write-Output "JSON em: $OutputJson"

# Exit code: 0 (SKIP eh nao-falha; FAIL real sera codigo 1 quando runner existir)
exit 0
