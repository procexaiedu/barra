#Requires -Version 5.1
<#
.SYNOPSIS
  Devolve o próximo número NNNN livre para uma nova migration em infra/sql/.
.DESCRIPTION
  Migrations são `NNNN_descricao.sql` sequenciais e imutáveis. Quando
  múltiplas worktrees criam migrations em paralelo (overnight do
  pipeline), todas adotam o mesmo NNNN → colisão no merge.

  Este helper resolve o próximo número considerando:
    1. Migrations já em `infra/sql/` no repo principal.
    2. Migrations em worktrees ativas (`.claude/worktrees/*/infra/sql/`).
    3. Reservas vivas em `.claude/state/migrations-reserved.json` —
       arquivos NNNN reservados por outras sessões mas ainda não escritos
       em disco (TTL 30min, configurável).

  Usa lock por arquivo (`.claude/state/migrations.lock`) com retry curto
  para serializar o read-modify-write entre processos paralelos.

  Por padrão IMPRIME só o número (4 dígitos) em stdout; nada mais. Use
  -Verbose para diagnóstico.
.PARAMETER Reserve
  Slug para reserva (ex: `clientes_arquivamento`). Se passado, reserva o
  número devolvido por TTL minutos e grava no JSON de reservas. Sem
  -Reserve, devolve o número mas NÃO reserva (modo dry-run).
.PARAMETER TtlMinutes
  Duração da reserva (default 30). Reservas expiradas são descartadas.
.PARAMETER Release
  Slug de uma reserva para liberar imediatamente (após criar o arquivo
  .sql ou ao abortar). Não devolve número novo — só libera.
.PARAMETER Timestamp
  Em vez de NNNN sequencial, devolve `yyyyMMddHHmmss` UTC. Não usa lock
  nem reservas — colisão por segundo entre worktrees é praticamente
  impossível, e o ordering lexicográfico continua funcionando misturado
  com migrations NNNN_ legacy (4 chars de prefixo < 14 chars sempre).
.PARAMETER RepoRoot
  Raiz do repo. Default C:\barra.
.EXAMPLE
  # Dry-run: só pergunta qual seria o próximo NNNN livre
  powershell -NoProfile -File scripts\proxima-migration.ps1
.EXAMPLE
  # Reserva 0031 para a feature `clientes_arquivamento` por 30min
  powershell -NoProfile -File scripts\proxima-migration.ps1 -Reserve 'clientes_arquivamento'
.EXAMPLE
  # Libera reserva após criar o arquivo
  powershell -NoProfile -File scripts\proxima-migration.ps1 -Release 'clientes_arquivamento'
.EXAMPLE
  # Timestamp UTC (recomendado para overnight/worktrees paralelas)
  powershell -NoProfile -File scripts\proxima-migration.ps1 -Timestamp
  # stdout: 20260513212347
.NOTES
  Compatível com ambos os formatos descritos em `infra/sql/CLAUDE.md`:
  `NNNN_slug.sql` (legacy) e `yyyyMMddHHmmss_slug.sql` (UTC).
  Não chama git — apenas lê o sistema de arquivos. Falha loud se não
  conseguir adquirir lock após retries (modo NNNN).
#>
[CmdletBinding()]
param(
    [string]$Reserve,
    [int]$TtlMinutes = 30,
    [string]$Release,
    [switch]$Timestamp,
    [string]$RepoRoot = 'C:\barra'
)

# Modo Timestamp: bypass total — não precisa lock nem reserva.
if ($Timestamp) {
    Write-Output ([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))
    exit 0
}

$ErrorActionPreference = 'Stop'

$sqlDir       = Join-Path $RepoRoot 'infra\sql'
$worktreesDir = Join-Path $RepoRoot '.claude\worktrees'
$stateDir     = Join-Path $RepoRoot '.claude\state'
$lockFile     = Join-Path $stateDir 'migrations.lock'
$reservesFile = Join-Path $stateDir 'migrations-reserved.json'

if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}

function Acquire-Lock {
    $maxTries = 50
    $sleepMs  = 100
    for ($i = 0; $i -lt $maxTries; $i++) {
        try {
            $stream = [System.IO.File]::Open($lockFile, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            return $stream
        } catch {
            Start-Sleep -Milliseconds $sleepMs
        }
    }
    throw "Nao consegui adquirir lock em $lockFile apos $($maxTries * $sleepMs)ms. Verifique se outra sessao travou ou apague o arquivo manualmente."
}

function Release-Lock($stream) {
    if ($null -ne $stream) {
        $stream.Dispose()
    }
    if (Test-Path $lockFile) {
        Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    }
}

function Read-Reserves {
    if (-not (Test-Path $reservesFile)) { return @() }
    try {
        $json = Get-Content -Raw -Path $reservesFile -Encoding utf8
        if ([string]::IsNullOrWhiteSpace($json)) { return @() }
        $arr = $json | ConvertFrom-Json
        if ($null -eq $arr) { return @() }
        # Force array shape
        if ($arr -isnot [System.Array]) { return @($arr) }
        return $arr
    } catch {
        Write-Verbose "Reserves JSON corrompido — descartando: $_"
        return @()
    }
}

function Write-Reserves($items) {
    if ($null -eq $items -or $items.Count -eq 0) {
        Set-Content -Path $reservesFile -Value '[]' -Encoding utf8
        return
    }
    $json = $items | ConvertTo-Json -Depth 4 -Compress
    # ConvertTo-Json envolve array de 1 elemento numa string solta; garantir array
    if ($items.Count -eq 1 -and $json -notmatch '^\[') { $json = "[$json]" }
    Set-Content -Path $reservesFile -Value $json -Encoding utf8
}

function Get-LiveReserves {
    $now = Get-Date
    $all = Read-Reserves
    $live = New-Object System.Collections.ArrayList
    foreach ($r in $all) {
        try {
            $expires = [DateTime]::Parse($r.expires_at, $null, [System.Globalization.DateTimeStyles]::RoundtripKind)
            if ($expires -gt $now) {
                [void]$live.Add($r)
            }
        } catch {
            # expirada ou malformada: descartar
        }
    }
    # Devolve array tipado para o `+=` do caller funcionar mesmo com 0/1 itens.
    return ,@($live.ToArray())
}

function Get-NNNN-FromDir($dir) {
    if (-not (Test-Path $dir)) { return @() }
    $files = Get-ChildItem -Path $dir -Filter '*.sql' -File -ErrorAction SilentlyContinue
    $nums = @()
    foreach ($f in $files) {
        if ($f.Name -match '^(\d{4})_') {
            $nums += [int]$matches[1]
        }
    }
    return $nums
}

function Get-NNNN-FromWorktrees {
    if (-not (Test-Path $worktreesDir)) { return @() }
    $nums = @()
    $worktrees = Get-ChildItem -Path $worktreesDir -Directory -ErrorAction SilentlyContinue
    foreach ($wt in $worktrees) {
        $wtSqlDir = Join-Path $wt.FullName 'infra\sql'
        $nums += Get-NNNN-FromDir $wtSqlDir
    }
    return $nums
}

# ---- Modo Release: libera reserva e sai
if ($Release) {
    $lock = $null
    try {
        $lock = Acquire-Lock
        $live = Get-LiveReserves
        $remaining = @($live | Where-Object { $_.slug -ne $Release })
        Write-Reserves $remaining
        Write-Verbose "Reserva '$Release' liberada."
        # Sem stdout — apenas exit code 0
        exit 0
    } finally {
        Release-Lock $lock
    }
}

# ---- Modo normal: calcula próximo livre

$lock = $null
try {
    $lock = Acquire-Lock

    $inMain      = Get-NNNN-FromDir $sqlDir
    $inWorktrees = Get-NNNN-FromWorktrees
    $live        = Get-LiveReserves
    $inReserves  = @($live | ForEach-Object { [int]$_.nnnn })

    $todos = @($inMain) + @($inWorktrees) + @($inReserves)
    if ($todos.Count -eq 0) {
        $proximo = 1
    } else {
        $max = ($todos | Measure-Object -Maximum).Maximum
        $proximo = [int]$max + 1
    }

    Write-Verbose ("infra/sql/ max: {0}; worktrees max: {1}; reservas vivas: {2}; proximo: {3:0000}" -f `
        $(if ($inMain.Count -gt 0) { ($inMain | Measure-Object -Maximum).Maximum } else { 0 }), `
        $(if ($inWorktrees.Count -gt 0) { ($inWorktrees | Measure-Object -Maximum).Maximum } else { 0 }), `
        $live.Count, `
        $proximo)

    if ($Reserve) {
        $now = Get-Date
        $expires = $now.AddMinutes($TtlMinutes)
        $newReserve = [PSCustomObject]@{
            nnnn        = ('{0:0000}' -f $proximo)
            slug        = $Reserve
            reserved_at = $now.ToString('o')
            expires_at  = $expires.ToString('o')
            pid         = $PID
        }
        $live += $newReserve
        Write-Reserves $live
        Write-Verbose ("Reserva '{0}' criada para {1:0000} (expira {2})" -f $Reserve, $proximo, $expires.ToString('o'))
    }

    # Stdout: só o número, sempre 4 dígitos. Nada mais — esse e o
    # contrato pro skill capturar.
    Write-Output ('{0:0000}' -f $proximo)
    exit 0
} finally {
    Release-Lock $lock
}
