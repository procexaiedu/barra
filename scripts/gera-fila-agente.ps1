#requires -Version 5.1
<#
.SYNOPSIS
  Gera docs/agente/fila-agente.yml a partir de docs/agente/09-roteiro.md.

.DESCRIPTION
  Parser simples que detecta secoes "## Mx -- titulo" no roteiro e converte cada
  marco em entrada da fila com:
    - id (slug: mx-...)
    - titulo (linha do header)
    - depends_on (mapa fixo do roteiro)
    - coluna inicial ("Backlog" se M0 ainda nao implementado, senao "To Do")
    - implementation_plan (corpo da secao integral, ate o proximo ## Mx ou ---)
    - eval_required (true a partir de M2; gate completo so em M6)
    - eval_config (datasets relevantes por marco)

  Idempotente: regravar o YAML zera o status se voce nao passar -PreserveStatus.

.PARAMETER PreserveStatus
  Se presente, le o YAML existente e mantem o campo "coluna" de cada marco.
  Util para regerar quando o roteiro mudou mas o progresso ja avancou.

.EXAMPLE
  pwsh -NoProfile -File C:\barra\scripts\gera-fila-agente.ps1
  pwsh -NoProfile -File C:\barra\scripts\gera-fila-agente.ps1 -PreserveStatus
#>
[CmdletBinding()]
param(
    [switch]$PreserveStatus
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Roteiro  = Join-Path $RepoRoot "docs\agente\09-roteiro.md"
$FilaYml  = Join-Path $RepoRoot "docs\agente\fila-agente.yml"

if (-not (Test-Path $Roteiro)) {
    Write-Error "Roteiro nao encontrado: $Roteiro"
    exit 1
}

# Mapa fixo de dependencias entre marcos (espelha 09-roteiro.md "Cronograma")
$Dependencias = @{
    "m0" = @()
    "m1" = @("m0")
    "m2" = @("m0")
    "m3" = @("m1","m2")
    "m4" = @("m3")
    "m5" = @("m3")
    "m6" = @("m4","m5")
}

# Mapa fixo de eval_config por marco
$EvalConfig = @{
    "m0" = @{ required = $false; suites = @() }
    "m1" = @{ required = $true;  suites = @("canonicos/leitura"); threshold = 0.80 }
    "m2" = @{ required = $true;  suites = @("canonicos/cache_hit"); threshold = 0.70; metric = "cache_hit_rate" }
    "m3" = @{ required = $true;  suites = @("canonicos/coordenador","canonicos/escrita_idempotente"); threshold = 0.85 }
    "m4" = @{ required = $true;  suites = @("canonicos/humanizacao"); threshold = 0.85 }
    "m5" = @{ required = $true;  suites = @("canonicos/midia"); threshold = 0.90 }
    "m6" = @{ required = $true;  suites = @("canonicos/scripted_5","adversariais/disclosure","adversariais/jailbreak","adversariais/cross_modelo","adversariais/gaslighting","adversariais/prova","adversariais/explicito"); threshold = 0.90; per_category = $true }
}

# Estado preservado (se aplicavel)
$StatusAtual = @{}
if ($PreserveStatus -and (Test-Path $FilaYml)) {
    $linhas = Get-Content -Raw -Path $FilaYml -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($linhas) {
        # parser ingenuo: pega pares (id, coluna) sem depender de modulo YAML
        $regex = [regex]'(?ms)^\s*-\s*id:\s*"?(?<id>m[0-9]+)"?\s*$.*?^\s*coluna:\s*"?(?<col>[^"\r\n]+)"?\s*$'
        foreach ($m in $regex.Matches($linhas)) {
            $StatusAtual[$m.Groups['id'].Value] = $m.Groups['col'].Value.Trim()
        }
    }
}

# Parse do roteiro
$texto = Get-Content -Raw -Path $Roteiro -Encoding UTF8

# Divide em blocos por header "## Mx -- titulo"
$blocos = [System.Collections.Generic.List[object]]::new()
# Aceita qualquer separador nao-espaco entre Mx e o titulo (hifen, en-dash, em-dash, etc).
# Construir via codepoints para nao depender de encoding do .ps1.
$dashClass = "[" + [char]0x2D + [char]0x2013 + [char]0x2014 + "]"
$headerRegex = [regex]("(?m)^##\s+M(?<num>\d+)\s+" + $dashClass + "\s+(?<titulo>.+?)\s*$")
$matches = $headerRegex.Matches($texto)
for ($i = 0; $i -lt $matches.Count; $i++) {
    $m = $matches[$i]
    $inicio = $m.Index + $m.Length
    $fim = if ($i + 1 -lt $matches.Count) { $matches[$i + 1].Index } else { $texto.Length }
    $corpo = $texto.Substring($inicio, $fim - $inicio).Trim()
    # corta no "---" horizontal se houver (separador de marco no roteiro)
    $idxSep = $corpo.IndexOf("`r`n---`r`n")
    if ($idxSep -lt 0) { $idxSep = $corpo.IndexOf("`n---`n") }
    if ($idxSep -gt 0) { $corpo = $corpo.Substring(0, $idxSep).Trim() }

    $id = "m{0}" -f $m.Groups['num'].Value
    $titulo = $m.Groups['titulo'].Value

    $blocos.Add([pscustomobject]@{
        id              = $id
        titulo          = $titulo
        implementation_plan = $corpo
    }) | Out-Null
}

if ($blocos.Count -eq 0) {
    Write-Error "Nenhum marco detectado em $Roteiro. Esperado header '## Mx -- titulo'."
    exit 2
}

# Emite YAML manualmente (sem dependencia de modulo externo)
$sb = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine("# fila-agente.yml")
[void]$sb.AppendLine("# Gerado por scripts/gera-fila-agente.ps1 a partir de docs/agente/09-roteiro.md")
[void]$sb.AppendLine("# NAO editar manualmente; rode o script novamente apos alterar o roteiro.")
[void]$sb.AppendLine("# Para preservar progresso ao regerar: -PreserveStatus")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("schema_version: 1")
[void]$sb.AppendLine("gerado_em: ""$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')""")
[void]$sb.AppendLine("fonte: docs/agente/09-roteiro.md")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("filas:")

foreach ($b in $blocos) {
    $coluna = if ($StatusAtual.ContainsKey($b.id)) { $StatusAtual[$b.id] } else { "Backlog" }
    $deps = $Dependencias[$b.id]
    $ev = $EvalConfig[$b.id]

    [void]$sb.AppendLine("  - id: ""$($b.id)""")
    [void]$sb.AppendLine("    titulo: |")
    [void]$sb.AppendLine("      $($b.titulo)")
    [void]$sb.AppendLine("    coluna: ""$coluna""")
    [void]$sb.AppendLine("    priority: ""high""")

    if ($deps.Count -eq 0) {
        [void]$sb.AppendLine("    depends_on: []")
    } else {
        [void]$sb.AppendLine("    depends_on:")
        foreach ($d in $deps) { [void]$sb.AppendLine("      - ""$d""") }
    }

    # eval_config
    [void]$sb.AppendLine("    eval_required: $(if ($ev.required) {'true'} else {'false'})")
    if ($ev.required) {
        [void]$sb.AppendLine("    eval_config:")
        [void]$sb.AppendLine("      suites:")
        foreach ($s in $ev.suites) { [void]$sb.AppendLine("        - ""$s""") }
        [void]$sb.AppendLine("      threshold: $($ev.threshold)")
        if ($ev.PSObject.Properties.Name -contains "metric") {
            [void]$sb.AppendLine("      metric: ""$($ev.metric)""")
        }
        if ($ev.PSObject.Properties.Name -contains "per_category" -and $ev.per_category) {
            [void]$sb.AppendLine("      per_category: true")
        }
    }

    [void]$sb.AppendLine("    implementation_plan: |")
    foreach ($linha in ($b.implementation_plan -split "`r?`n")) {
        [void]$sb.AppendLine("      $linha")
    }
    [void]$sb.AppendLine("")
}

# Garante diretorio
$dir = Split-Path -Parent $FilaYml
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

# Escreve UTF-8 sem BOM (padrao do projeto)
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($FilaYml, $sb.ToString(), $utf8NoBom)

Write-Output "Fila gerada: $FilaYml"
Write-Output "Marcos: $($blocos.Count)"
foreach ($b in $blocos) {
    $col = if ($StatusAtual.ContainsKey($b.id)) { $StatusAtual[$b.id] } else { "Backlog" }
    Write-Output ("  {0} [{1}] -- {2}" -f $b.id, $col, $b.titulo)
}
