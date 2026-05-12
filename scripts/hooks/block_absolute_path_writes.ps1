#Requires -Version 5.1
<#
.SYNOPSIS
  Hook PreToolUse para Edit/Write/MultiEdit: bloqueia paths absolutos
  vindos de subagentes em worktree que apontem pra fora do proprio worktree.
.DESCRIPTION
  Recebe via stdin JSON {tool_input:{file_path:"..."}, cwd:"...", agent_id:"..."}.
  Logica:
   - Sem agent_id no JSON  -> sessao principal, NAO bloqueia.
   - file_path nao absoluto -> sempre PASS.
   - file_path absoluto E dentro do cwd do subagente -> PASS.
   - file_path absoluto E fora do cwd do subagente -> BLOCK (exit 2).

  Motivo: o Agent tool com isolation:"worktree" NAO redireciona paths
  absolutos. Subagente que escreve em C:\barra\... acaba contaminando o
  repo principal silenciosamente (incidente 2026-05-12, task 9a49dde8).

  Conservador: se nao conseguir extrair cwd/file_path, apenas emite warning
  em stderr e NAO bloqueia. Falsa-positiva atrapalha mais que ajuda.
.PARAMETER Test
  Modo self-test: roda 4 cenarios inline.
.NOTES
  Schema oficial do hook: https://code.claude.com/docs/en/hooks
  - top-level: cwd, agent_id (so em subagente), tool_name, tool_input
  - tool_input.file_path para Edit/Write/MultiEdit
#>
[CmdletBinding()]
param(
    [switch]$Test
)
$ErrorActionPreference = 'Stop'

function Normalize-Path([string]$p) {
    if ([string]::IsNullOrWhiteSpace($p)) { return $null }
    $n = $p -replace '\\', '/'
    # Lowercase drive letter para C:/ vs c:/ etc.
    if ($n -match '^([A-Za-z]):/') {
        $n = ($Matches[1].ToLower()) + ':/' + $n.Substring(3)
    }
    # Remove trailing slash exceto na raiz drive.
    if ($n.Length -gt 3 -and $n.EndsWith('/')) { $n = $n.TrimEnd('/') }
    return $n
}

function Is-AbsolutePath([string]$p) {
    if ([string]::IsNullOrWhiteSpace($p)) { return $false }
    # Windows: C:\... ou C:/...  Posix-on-Windows (Git Bash): /c/barra/...
    return ($p -match '^[A-Za-z]:[\\/]') -or ($p -match '^/[a-zA-Z]/')
}

function Path-IsInside([string]$child, [string]$parent) {
    if (-not $child -or -not $parent) { return $false }
    $c = Normalize-Path $child
    $pr = Normalize-Path $parent
    if (-not $c -or -not $pr) { return $false }
    # Garante separador apos parent pra evitar match parcial de prefixo (ex: /foo vs /foobar).
    $prWithSep = $pr.TrimEnd('/') + '/'
    return ($c -eq $pr) -or ($c.StartsWith($prWithSep, [StringComparison]::OrdinalIgnoreCase))
}

function Decide([hashtable]$ctx) {
    # $ctx: @{ file_path; cwd; agent_id }
    $fp      = $ctx.file_path
    $cwd     = $ctx.cwd
    $agentId = $ctx.agent_id

    # Sessao principal (sem agent_id): nunca bloqueia.
    if ([string]::IsNullOrWhiteSpace($agentId)) {
        return @{ blocked = $false; reason = 'sessao principal (sem agent_id)' }
    }

    # Sem file_path no input: nao temos o que avaliar.
    if ([string]::IsNullOrWhiteSpace($fp)) {
        return @{ blocked = $false; reason = 'sem file_path no tool_input' }
    }

    # Path relativo: sempre OK.
    if (-not (Is-AbsolutePath $fp)) {
        return @{ blocked = $false; reason = 'path relativo' }
    }

    # Path absoluto + subagente. Precisa estar dentro do cwd do subagente.
    if ([string]::IsNullOrWhiteSpace($cwd)) {
        # Sem cwd nao da pra decidir. Conservador: nao bloqueia, soh avisa.
        return @{ blocked = $false; reason = 'subagente sem cwd informado (warn)'; warn = $true }
    }

    if (Path-IsInside $fp $cwd) {
        return @{ blocked = $false; reason = 'path absoluto dentro do worktree do subagente' }
    }

    return @{
        blocked = $true
        reason  = "subagente em worktree '$cwd' tentou escrever path absoluto fora do worktree: '$fp'. Use path relativo (ex: 'api/src/barra/...') para que isolation:worktree funcione."
    }
}

if ($Test) {
    $worktree = 'C:/barra/.claude/worktrees/agent-afe276a359da37fc1'
    $cases = @(
        @{
            name = 'relativo de subagente'
            ctx  = @{ file_path='api/src/barra/dominio/x.py'; cwd=$worktree; agent_id='codificador-api' }
            expect = 'PASS'
        },
        @{
            name = 'absoluto em main de sessao humana'
            ctx  = @{ file_path='C:\barra\api\src\barra\dominio\x.py'; cwd='C:/barra'; agent_id=$null }
            expect = 'PASS'
        },
        @{
            name = 'absoluto em main vindo de subagente em worktree (CASO DO INCIDENTE)'
            ctx  = @{ file_path='C:\barra\api\src\barra\dominio\x.py'; cwd=$worktree; agent_id='codificador-api' }
            expect = 'BLOCK'
        },
        @{
            name = 'absoluto dentro do proprio worktree (caso valido)'
            ctx  = @{ file_path="$worktree/api/src/barra/dominio/x.py"; cwd=$worktree; agent_id='codificador-api' }
            expect = 'PASS'
        },
        @{
            name = 'absoluto posix-style em main vindo de subagente'
            ctx  = @{ file_path='/c/barra/api/src/barra/x.py'; cwd=$worktree; agent_id='codificador-api' }
            expect = 'BLOCK'
        }
    )

    $fails = 0
    foreach ($c in $cases) {
        $r = Decide $c.ctx
        $actual = if ($r.blocked) { 'BLOCK' } else { 'PASS' }
        $ok = ($actual -eq $c.expect)
        if (-not $ok) { $fails++ }
        $mark = if ($ok) { 'OK ' } else { 'FAIL' }
        Write-Host ("{0}  {1,-5} (exp {2,-5}) :: {3}" -f $mark, $actual, $c.expect, $c.name)
        Write-Host ("       reason: {0}" -f $r.reason)
    }
    Write-Host ""
    if ($fails -eq 0) {
        Write-Host ("Todos os {0} casos passaram." -f $cases.Count)
        exit 0
    } else {
        Write-Host ("{0} caso(s) falharam de {1}." -f $fails, $cases.Count)
        exit 1
    }
}

# Modo normal: le stdin do harness.
$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }

try {
    $event = $raw | ConvertFrom-Json
} catch {
    # JSON invalido: nao da pra avaliar. Conservador.
    exit 0
}

if (-not $event) { exit 0 }

$ctx = @{
    file_path = $null
    cwd       = $null
    agent_id  = $null
}

if ($event.tool_input -and $event.tool_input.file_path) {
    $ctx.file_path = [string]$event.tool_input.file_path
}
if ($event.cwd) { $ctx.cwd = [string]$event.cwd }
# agent_id soh aparece quando o tool eh chamado de dentro de um subagente.
if ($event.agent_id) { $ctx.agent_id = [string]$event.agent_id }

$result = Decide $ctx

if ($result.warn) {
    [Console]::Error.WriteLine("[block_absolute_path_writes] WARN: $($result.reason)")
}

if ($result.blocked) {
    [Console]::Error.WriteLine("Bloqueado pelo hook de paths absolutos: $($result.reason)")
    exit 2
}

exit 0
