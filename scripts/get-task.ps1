# scripts/get-task.ps1
#
# Busca uma task do devcontext via API HTTP direta (contorna bug do
# devcontext-mcp v1.0.7 que descarta `implementation_plan` no formatter).
#
# Uso:
#   powershell -NoProfile -File scripts/get-task.ps1 -TaskId 600ad3cf
#   powershell -NoProfile -File scripts/get-task.ps1 -TaskId 600ad3cf -OutFile C:\tmp\t.json
#
# Saida:
#   - sem -OutFile: JSON em stdout (NOTA: pode sofrer mojibake quando PS 5.1
#     captura via "& powershell ..." pelo encoding cross-process do console;
#     adequado para inspecao humana, NAO para parse programatico de UTF-8)
#   - com -OutFile <path>: grava JSON em UTF-8 sem BOM no arquivo, stdout
#     imprime apenas "OK <path>" (ASCII puro, seguro cross-process). Caller
#     deve ler o arquivo com `Get-Content -Raw -Encoding utf8 | ConvertFrom-Json`.
#
# Exit codes:
#   0 = match unico (JSON gerado em stdout ou arquivo)
#   1 = erro de I/O (credenciais ausentes, HTTP falhou, formato inesperado)
#   2 = nenhuma task casa com TaskId
#   3 = mais de uma task casa (id parcial ambiguo)

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$TaskId,

    [Parameter()]
    [string]$OutFile
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$credPath = Join-Path $PSScriptRoot '..\.devcontext'
if (-not (Test-Path $credPath)) {
    [Console]::Error.WriteLine("Credenciais nao encontradas em $credPath")
    exit 1
}

try {
    $cred = Get-Content -Raw -Path $credPath -Encoding utf8 | ConvertFrom-Json
} catch {
    [Console]::Error.WriteLine("Falha ao parsear .devcontext: $($_.Exception.Message)")
    exit 1
}

$baseUrl = $cred.url.TrimEnd('/')
$endpoint = "$baseUrl/api/mcp/tasks?mine=false&limit=500"
$headers = @{
    'Authorization' = "Bearer $($cred.secret)"
    'X-User-Email'  = $cred.user_email
    'Accept'        = 'application/json'
}

try {
    # Invoke-WebRequest + decode UTF-8 manual: Invoke-RestMethod em PS 5.1
    # cai para ISO-8859-1 quando Content-Type nao declara charset (RFC 7231),
    # corrompendo acentos vindos da API.
    $rawResp = Invoke-WebRequest -Uri $endpoint -Headers $headers -Method Get -TimeoutSec 30 -UseBasicParsing
    $rawBytes = $rawResp.Content
    if ($rawBytes -is [string]) {
        # PS 5.1 ja transformou em string com encoding errado; recodifica.
        $bytes = [System.Text.Encoding]::GetEncoding('ISO-8859-1').GetBytes($rawBytes)
        $jsonText = [System.Text.Encoding]::UTF8.GetString($bytes)
    } else {
        $jsonText = [System.Text.Encoding]::UTF8.GetString($rawBytes)
    }
    $response = $jsonText | ConvertFrom-Json
} catch {
    [Console]::Error.WriteLine("HTTP GET falhou em $endpoint : $($_.Exception.Message)")
    exit 1
}

# A API pode retornar array direto ou objeto com .tasks/.data/.items.
$tasks = $null
if ($response -is [System.Array]) {
    $tasks = $response
} elseif ($response.tasks) {
    $tasks = $response.tasks
} elseif ($response.data) {
    $tasks = $response.data
} elseif ($response.items) {
    $tasks = $response.items
} else {
    [Console]::Error.WriteLine("Formato de resposta inesperado. Chaves: $($response.PSObject.Properties.Name -join ',')")
    exit 1
}

$needle = $TaskId.ToLowerInvariant()
$matches = @($tasks | Where-Object {
    $_.id -and $_.id.ToString().ToLowerInvariant().StartsWith($needle)
})

if ($matches.Count -eq 0) {
    [Console]::Error.WriteLine("Task $TaskId nao encontrada (total na fila: $($tasks.Count))")
    exit 2
}

if ($matches.Count -gt 1) {
    $ids = ($matches | ForEach-Object { $_.id }) -join ', '
    [Console]::Error.WriteLine("Ambiguous: $ids")
    exit 3
}

$json = $matches[0] | ConvertTo-Json -Depth 20 -Compress:$false

if ($OutFile) {
    # UTF-8 sem BOM via .NET (Set-Content -Encoding utf8 grava com BOM no PS 5.1).
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($OutFile, $json, $utf8NoBom)
    Write-Output "OK $OutFile"
} else {
    Write-Output $json
}
exit 0
