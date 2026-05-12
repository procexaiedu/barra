#Requires -Version 5.1
<#
.SYNOPSIS
  Hook PreToolUse para Bash: bloqueia comandos destrutivos de git/shell.
.DESCRIPTION
  Recebe via stdin um JSON `{tool_input:{command:"..."}}` do harness.
  Compara o comando contra patterns curados; se algum casar, escreve
  mensagem em stderr e sai com exit 2 (bloqueio do harness).

  Patterns são CASE-SENSITIVE para flags (-d != -D). `git restore .` /
  `git checkout .` casam apenas quando `.` é o argumento literal, não
  parte de um path como `.claude/x.json`.
.PARAMETER Test
  Modo self-test: executa array inline de casos PASS/BLOCK e devolve
  resumo. Sai com 0 se todos passaram, 1 caso contrário.
.EXAMPLE
  echo '{"tool_input":{"command":"git push"}}' | powershell -File hook.ps1
.NOTES
  Patterns curados após overnight 2026-05-12: regex anterior tinha
  falso-positivo em `git restore .claude/x.json` e ignorava o caso de
  `git branch -d` (lowercase, seguro).
#>
[CmdletBinding()]
param(
    [switch]$Test
)
$ErrorActionPreference = 'Stop'

# Cada pattern é case-sensitive por padrão (sem IgnoreCase) porque
# flags do git distinguem maiúscula/minúscula (-D destrutivo, -d seguro).
$patterns = @(
    @{ rx = '\bgit\s+push\b';                                  msg = 'git push (somente humano faz push)' },
    @{ rx = '--no-verify\b';                                   msg = '--no-verify (proibido pelo pipeline)' },
    @{ rx = '--no-gpg-sign\b';                                 msg = '--no-gpg-sign (proibido)' },
    @{ rx = '-c\s+commit\.gpgsign\s*=\s*false';                msg = 'desativar gpgsign via -c (proibido)' },
    @{ rx = '\bgit\s+push\b.*(--force|\s-f\b)';                msg = 'git push --force (proibido)' },
    @{ rx = '\bgit\s+reset\s+--hard\b';                        msg = 'git reset --hard (proibido sem autorizacao humana)' },
    # `-D` destrutivo (uppercase) é proibido; `-d` minúsculo só apaga branch já mergeada — permitido.
    @{ rx = '\bgit\s+branch\s+-D\b';                           msg = 'git branch -D (proibido sem autorizacao humana)' },
    # `git restore .` / `git checkout .` SÓ quando `.` é o argumento completo (lookahead garante separador ou fim).
    @{ rx = '\bgit\s+checkout\s+\.(?=\s|$)';                   msg = 'git checkout . (proibido)' },
    @{ rx = '\bgit\s+restore\s+\.(?=\s|$)';                    msg = 'git restore . (proibido)' },
    @{ rx = '\bgit\s+clean\s+-f';                              msg = 'git clean -f (proibido)' },
    @{ rx = '\brm\s+-rf\b';                                    msg = 'rm -rf (proibido sem autorizacao humana)' },
    @{ rx = '\bRemove-Item\b.*-Recurse.*-Force';               msg = 'Remove-Item -Recurse -Force (proibido sem autorizacao humana)' },
    @{ rx = '\bdrop\s+table\b';                                msg = 'DROP TABLE (proibido sem autorizacao humana)' }
)

function Test-Command([string]$cmd) {
    foreach ($p in $patterns) {
        # Sem IgnoreCase: flags são case-sensitive. `drop table` em SQL fica em $false negative
        # quando vier UPPERCASE? Não — `drop table` aparece sempre lowercase no SQL gerado
        # pelos codificadores; quando humano escreve manual, vê stderr antes do exit. Mantemos
        # case-sensitive global para flags do git, que é onde ferimos antes.
        if ([System.Text.RegularExpressions.Regex]::IsMatch($cmd, $p.rx)) {
            return @{ blocked = $true; reason = $p.msg }
        }
    }
    # Cobertura extra para SQL: DROP TABLE em qualquer caso.
    if ([System.Text.RegularExpressions.Regex]::IsMatch(
            $cmd, '\bdrop\s+table\b',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
        return @{ blocked = $true; reason = 'DROP TABLE (proibido sem autorizacao humana)' }
    }
    return @{ blocked = $false; reason = $null }
}

if ($Test) {
    $cases = @(
        # PASS — comandos seguros que NÃO devem ser bloqueados
        @{ cmd = 'git restore .claude/settings.local.json';   expect = 'PASS' },
        @{ cmd = 'git restore --staged file.py';              expect = 'PASS' },
        @{ cmd = 'git branch -d feature/x';                   expect = 'PASS' },
        @{ cmd = 'git checkout main';                         expect = 'PASS' },
        @{ cmd = 'git checkout -b feat/foo';                  expect = 'PASS' },
        @{ cmd = 'git status';                                expect = 'PASS' },
        @{ cmd = 'git commit -m "fix: x"';                    expect = 'PASS' },
        # BLOCK — comandos destrutivos que DEVEM ser bloqueados
        @{ cmd = 'git restore .';                             expect = 'BLOCK' },
        @{ cmd = 'git restore . && echo done';                expect = 'BLOCK' },
        @{ cmd = 'git checkout .';                            expect = 'BLOCK' },
        @{ cmd = 'git branch -D feature/x';                   expect = 'BLOCK' },
        @{ cmd = 'git push';                                  expect = 'BLOCK' },
        @{ cmd = 'git push --force origin main';              expect = 'BLOCK' },
        @{ cmd = 'git reset --hard origin/main';              expect = 'BLOCK' },
        @{ cmd = 'git commit --no-verify -m "x"';             expect = 'BLOCK' },
        @{ cmd = 'rm -rf node_modules';                       expect = 'BLOCK' },
        @{ cmd = 'Remove-Item -Recurse -Force .next';         expect = 'BLOCK' },
        @{ cmd = 'DROP TABLE atendimentos;';                  expect = 'BLOCK' },
        @{ cmd = 'drop table atendimentos;';                  expect = 'BLOCK' }
    )

    $fails = 0
    foreach ($c in $cases) {
        $r = Test-Command $c.cmd
        $actual = if ($r.blocked) { 'BLOCK' } else { 'PASS' }
        $ok     = ($actual -eq $c.expect)
        if (-not $ok) { $fails++ }
        $mark = if ($ok) { 'OK ' } else { 'FAIL' }
        $reason = if ($r.reason) { " <- $($r.reason)" } else { '' }
        Write-Host ("{0}  {1,-5} (exp {2,-5}) :: {3}{4}" -f $mark, $actual, $c.expect, $c.cmd, $reason)
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

# Modo normal: lê stdin do harness.
$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }

try {
    $event = $raw | ConvertFrom-Json
} catch {
    exit 0
}

$cmd = $null
if ($event -and $event.tool_input) {
    $cmd = $event.tool_input.command
}
if ([string]::IsNullOrWhiteSpace($cmd)) { exit 0 }

$result = Test-Command $cmd
if ($result.blocked) {
    [Console]::Error.WriteLine(
        "Bloqueado pelo hook de seguranca: $($result.reason) nao e permitido em pipeline autonomo. Peca autorizacao explicita ao humano.")
    exit 2
}

exit 0
