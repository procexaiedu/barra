#Requires -Version 5.1
<#
.SYNOPSIS
  Remove worktrees do pipeline (`.claude/worktrees/agent-*`) cuja branch
  já foi mergeada em main.
.DESCRIPTION
  Após cada overnight, dezenas de worktrees ficam no disco mesmo quando
  o trabalho já entrou em main. `git worktree remove` falha em PS quando
  há file lock (node_modules, pnpm-store, dev server residual) — esse
  helper tenta:
    1. Detectar worktrees cuja branch foi mergeada em main.
    2. `git worktree unlock` (worktrees do harness vêm locked).
    3. `git worktree remove --force` no caminho.
    4. Se ainda restar pasta órfã: `taskkill node.exe` direcionado e
       retry. -Force adicional permite `Remove-Item -Recurse -Force`
       na pasta órfã.

  Por padrão roda em -DryRun: lista o que faria, não toca em nada.
.PARAMETER DryRun
  Default. Apenas lista o que faria.
.PARAMETER Execute
  Executa as remoções. Implica saída de DryRun.
.PARAMETER Force
  Após `git worktree remove` falhar mesmo com kill de node.exe, faz
  `Remove-Item -Recurse -Force` na pasta. SOMENTE com -Execute também
  ativo. Requer confirmação interativa para cada pasta (a menos que
  -ForceYes seja passado).
.PARAMETER ForceYes
  Bypass do prompt interativo do -Force. NÃO usar em automação noturna
  sem revisão humana.
.PARAMETER RepoRoot
  Raiz do repo. Default C:\barra.
.EXAMPLE
  # Dry-run (default)
  powershell -NoProfile -File scripts\cleanup-merged-worktrees.ps1
.EXAMPLE
  # Limpa worktrees mergeadas (cuidado: -Execute remove de fato)
  powershell -NoProfile -File scripts\cleanup-merged-worktrees.ps1 -Execute
.EXAMPLE
  # Limpa com força total para pastas presas por file lock
  powershell -NoProfile -File scripts\cleanup-merged-worktrees.ps1 -Execute -Force
.NOTES
  NÃO toca em worktrees cuja branch NÃO está mergeada — humano decide.
  NÃO faz `git push`, `git branch -D` nem rebase. Apenas remove worktree
  e (opcional) força pasta órfã.
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Execute,
    [switch]$Force,
    [switch]$ForceYes,
    [string]$RepoRoot = 'C:\barra'
)

$ErrorActionPreference = 'Stop'

# Default behavior: se nada passado, vira DryRun.
if (-not $Execute) { $DryRun = $true }
if ($Force -and -not $Execute) {
    Write-Warning "-Force requer -Execute; ignorando -Force."
    $Force = $false
}

Set-Location $RepoRoot

function Get-MergedBranches {
    # Lista branches locais mergeadas em main (excluindo main).
    $out = & git branch --merged main 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git branch --merged main falhou."
    }
    $branches = @()
    foreach ($line in $out) {
        $clean = $line.Trim().TrimStart('+', '*').Trim()
        if ([string]::IsNullOrWhiteSpace($clean)) { continue }
        if ($clean -eq 'main') { continue }
        $branches += $clean
    }
    return $branches
}

function Get-WorktreeList {
    # Parse `git worktree list --porcelain` → array de objetos
    $raw = & git worktree list --porcelain 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git worktree list falhou."
    }
    $wts = @()
    $cur = $null
    foreach ($line in $raw) {
        if ($line -match '^worktree (.+)$') {
            if ($cur) { $wts += $cur }
            $cur = [PSCustomObject]@{ path = $matches[1]; branch = $null; locked = $false }
        } elseif ($line -match '^branch refs/heads/(.+)$' -and $cur) {
            $cur.branch = $matches[1]
        } elseif ($line -match '^locked' -and $cur) {
            $cur.locked = $true
        }
    }
    if ($cur) { $wts += $cur }
    return $wts
}

function Kill-NodeProcessesUnder($path) {
    # Mata node.exe cujo cwd ou caminho do executável referencia o worktree.
    $norm = ($path -replace '/', '\').TrimEnd('\').ToLower()
    $procs = Get-Process -Name node -ErrorAction SilentlyContinue
    $killed = 0
    foreach ($p in $procs) {
        try {
            $pathExe = ($p.Path -as [string])
            $pathExeNorm = if ($pathExe) { $pathExe.ToLower() } else { '' }
            if ($pathExeNorm -and $pathExeNorm.StartsWith($norm)) {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                $killed++
            }
        } catch {}
    }
    return $killed
}

$merged = Get-MergedBranches
$allWts = Get-WorktreeList

# Filtra: somente worktrees sob .claude/worktrees/ E cuja branch está mergeada
$agentWtPrefix = ($RepoRoot -replace '\\', '/') + '/.claude/worktrees/'
$targets = @()
foreach ($wt in $allWts) {
    $normPath = ($wt.path -replace '\\', '/').ToLower()
    if (-not $normPath.StartsWith($agentWtPrefix.ToLower())) { continue }
    if ($wt.branch -and $merged -contains $wt.branch) {
        $targets += $wt
    }
}

Write-Host ""
Write-Host "=== cleanup-merged-worktrees ==="
Write-Host "repo:                $RepoRoot"
Write-Host "worktrees totais:    $($allWts.Count)"
Write-Host "branches mergeadas:  $($merged.Count)"
Write-Host "alvos (mergeados):   $($targets.Count)"
Write-Host "modo:                $(if ($DryRun) { 'DRY-RUN (use -Execute para remover)' } else { 'EXECUTE' })"
Write-Host ""

if ($targets.Count -eq 0) {
    Write-Host "Nada para limpar."
    exit 0
}

foreach ($t in $targets) {
    Write-Host "--- $($t.path)"
    Write-Host "    branch:  $($t.branch)"
    Write-Host "    locked:  $($t.locked)"

    if ($DryRun) {
        Write-Host "    [dry-run] git worktree remove --force '$($t.path)'"
        if ($Force) { Write-Host "    [dry-run] (com -Force) Remove-Item -Recurse -Force '$($t.path)' se restar" }
        continue
    }

    # 1) unlock
    if ($t.locked) {
        & git worktree unlock $t.path 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "    falha em git worktree unlock — segue tentando remove"
        } else {
            Write-Host "    unlocked"
        }
    }

    # 2) remove
    & git worktree remove --force $t.path 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0 -and -not (Test-Path $t.path)) {
        Write-Host "    OK removido"
        continue
    }

    # 3) kill node.exe locked e retry
    $killed = Kill-NodeProcessesUnder $t.path
    if ($killed -gt 0) {
        Write-Host "    matei $killed node.exe presos, retentando remove"
        Start-Sleep -Milliseconds 500
        & git worktree remove --force $t.path 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0 -and -not (Test-Path $t.path)) {
            Write-Host "    OK removido apos kill"
            continue
        }
    }

    # 4) -Force: Remove-Item bruto
    if ($Force -and (Test-Path $t.path)) {
        $confirm = 'n'
        if ($ForceYes) {
            $confirm = 'y'
        } else {
            $confirm = Read-Host "    git worktree remove falhou. Apagar pasta orfa '$($t.path)' com Remove-Item -Recurse -Force? (y/N)"
        }
        if ($confirm -eq 'y') {
            try {
                Remove-Item -Path $t.path -Recurse -Force -ErrorAction Stop
                Write-Host "    OK removido com Remove-Item"
                # Limpa referência no git
                & git worktree prune 2>$null | Out-Null
            } catch {
                Write-Warning "    Remove-Item falhou: $_"
            }
        } else {
            Write-Warning "    pulado (humano negou)"
        }
    } elseif (Test-Path $t.path) {
        Write-Warning "    pasta ainda existe — passe -Force para tentar Remove-Item"
    }
}

Write-Host ""
Write-Host "Fim."
