#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

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

$patterns = @(
    @{ rx = '\bgit\s+push\b';                                  msg = 'git push (somente humano faz push)' },
    @{ rx = '--no-verify\b';                                   msg = '--no-verify (proibido pelo pipeline)' },
    @{ rx = '--no-gpg-sign\b';                                 msg = '--no-gpg-sign (proibido)' },
    @{ rx = '-c\s+commit\.gpgsign\s*=\s*false';                msg = 'desativar gpgsign via -c (proibido)' },
    @{ rx = '\bgit\s+push\b.*(--force|\s-f\b)';                msg = 'git push --force (proibido)' },
    @{ rx = '\bgit\s+reset\s+--hard\b';                        msg = 'git reset --hard (proibido sem autorizacao humana)' },
    @{ rx = '\bgit\s+branch\s+-D\b';                           msg = 'git branch -D (proibido sem autorizacao humana)' },
    @{ rx = '\bgit\s+checkout\s+\.';                           msg = 'git checkout . (proibido)' },
    @{ rx = '\bgit\s+restore\s+\.';                            msg = 'git restore . (proibido)' },
    @{ rx = '\bgit\s+clean\s+-f';                              msg = 'git clean -f (proibido)' },
    @{ rx = '\brm\s+-rf\b';                                    msg = 'rm -rf (proibido sem autorizacao humana)' },
    @{ rx = '\bRemove-Item\b.*-Recurse.*-Force';               msg = 'Remove-Item -Recurse -Force (proibido sem autorizacao humana)' },
    @{ rx = '\bdrop\s+table\b';                                msg = 'DROP TABLE (proibido sem autorizacao humana)' }
)

foreach ($p in $patterns) {
    if ([System.Text.RegularExpressions.Regex]::IsMatch(
            $cmd, $p.rx,
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
        [Console]::Error.WriteLine(
            "Bloqueado pelo hook de seguranca: $($p.msg) nao e permitido em pipeline autonomo. Peca autorizacao explicita ao humano.")
        exit 2
    }
}

exit 0
