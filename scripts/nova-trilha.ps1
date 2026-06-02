<#
.SYNOPSIS
  Cria uma worktree dedicada para uma trilha de tasks isolada.

.DESCRIPTION
  Faz `git worktree add` a partir de uma branch base (default: main), copia o
  api/.env (que e gitignored e nao vai junto na worktree) e garante
  TEST_DATABASE_URL derivado de DATABASE_URL (mesmo banco; os testes usam
  rollback). Imprime os proximos passos.

.PARAMETER Nome
  Nome curto da trilha (ex.: evals, webhook-sec, infra). Vira ../barra-<Nome>
  e a branch track-<Nome>.

.PARAMETER Branch
  Nome da branch (default: track-<Nome>).

.PARAMETER Base
  Branch/commit base de onde ramificar (default: main).

.EXAMPLE
  scripts/nova-trilha.ps1 -Nome evals
.EXAMPLE
  scripts/nova-trilha.ps1 -Nome infra -Base main
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
  [string]$Nome,

  [string]$Branch,
  [string]$Base = 'main'
)

$ErrorActionPreference = 'Stop'

# Raiz do repo = pasta-mae de scripts/
$RepoRoot = Split-Path $PSScriptRoot -Parent
if (-not $Branch) { $Branch = "track-$Nome" }
$WorktreePath = Join-Path (Split-Path $RepoRoot -Parent) "barra-$Nome"

Write-Host "Repo:     $RepoRoot"
Write-Host "Worktree: $WorktreePath"
Write-Host "Branch:   $Branch (a partir de $Base)"
Write-Host ""

if (Test-Path $WorktreePath) {
  Write-Error "Ja existe '$WorktreePath'. Remova com 'git worktree remove $WorktreePath' ou escolha outro -Nome."
}

# 1. Cria a worktree numa branch nova a partir da base.
Write-Host "==> git worktree add"
& git -C $RepoRoot worktree add $WorktreePath -b $Branch $Base
if ($LASTEXITCODE -ne 0) { Write-Error "git worktree add falhou (branch '$Branch' ja existe? base '$Base' existe?)." }

# 2. Copia o api/.env (gitignored -> nao vem na worktree).
$SrcEnv = Join-Path $RepoRoot 'api\.env'
$DstEnv = Join-Path $WorktreePath 'api\.env'
if (-not (Test-Path $SrcEnv)) {
  Write-Warning "api/.env nao encontrado na raiz; pulei a copia. build_graph vai falhar sem ANTHROPIC_API_KEY."
} else {
  Copy-Item $SrcEnv $DstEnv -Force
  Write-Host "==> copiado api/.env"

  # 3. Garante TEST_DATABASE_URL (= DATABASE_URL; testes rodam com rollback).
  $envLines = Get-Content $DstEnv
  $hasTest = $envLines | Where-Object { $_ -match '^\s*TEST_DATABASE_URL\s*=' }
  if ($hasTest) {
    Write-Host "==> TEST_DATABASE_URL ja presente; mantido"
  } else {
    $dbLine = $envLines | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
    if ($dbLine) {
      $dbVal = ($dbLine -split '=', 2)[1].Trim()
      Add-Content -Path $DstEnv -Value "TEST_DATABASE_URL=$dbVal" -Encoding utf8
      Write-Host "==> TEST_DATABASE_URL derivado de DATABASE_URL"
    } else {
      Write-Warning "DATABASE_URL nao encontrado no .env; nao derivei TEST_DATABASE_URL."
    }
  }
}

Write-Host ""
Write-Host "Pronto. Proximos passos:" -ForegroundColor Green
Write-Host "  1. Abra um Claude Code em: $WorktreePath"
Write-Host "  2. Trabalhe SO nesta branch isolada; git add por caminho explicito."
Write-Host "  3. Evals do lock precisam de fakeredis[lua] (uv sync ja cobre)."
Write-Host ""
Write-Host "Ao terminar a trilha (apos mesclar/promover a branch):"
Write-Host "  git worktree remove $WorktreePath"
