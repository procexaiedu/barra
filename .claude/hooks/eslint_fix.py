"""PostToolUse — roda eslint no frontend (.ts/.tsx em interface/) apos Edit/Write.

Espelha o ruff_format.py do backend: aplica `eslint --fix` no arquivo editado, a partir de
interface/ (onde vive a flat config). Best-effort — qualquer falha (node/eslint ausente) e
silenciosa e NUNCA bloqueia. Se sobrar erro que --fix nao resolve (ex.: a regra de ERRO
set-state-in-effect do React 19), injeta os erros como additionalContext pro Claude corrigir
cedo, em vez de so aparecerem no `pnpm verify`.

Chama o bin do eslint via `node` (sem overhead do pnpm e sem o footgun do pnpm.cmd no Windows).
Falha aberta: qualquer excecao deixa a edicao seguir (exit 0).
"""

import json
import os
import shutil
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    fp = tool_input.get("file_path") or ""
    norm = fp.replace("\\", "/")

    if not norm.endswith((".ts", ".tsx")) or "/interface/" not in norm:
        sys.exit(0)
    if norm.endswith(".d.ts"):
        sys.exit(0)

    interface_dir = norm[: norm.rfind("/interface/")] + "/interface"
    eslint_bin = os.path.join(interface_dir, "node_modules", "eslint", "bin", "eslint.js")
    node = shutil.which("node")
    if not node or not os.path.exists(eslint_bin):
        sys.exit(0)

    try:
        proc = subprocess.run(
            [node, eslint_bin, "--fix", "--format", "compact", fp],
            cwd=interface_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        sys.exit(0)

    if proc.returncode == 0:
        sys.exit(0)  # limpo, ou apenas auto-fixaveis ja corrigidos pelo --fix
    if proc.returncode != 1:
        sys.exit(0)  # >=2: crash do eslint/config, nao erro do codigo — silencia (best-effort)

    saida = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if not saida:
        sys.exit(0)
    if len(saida) > 2000:
        saida = saida[:2000] + "\n... (truncado)"

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"eslint apontou problemas que --fix nao resolve em {fp} "
                        "(mesmo gate do `pnpm verify` — corrija antes de seguir):\n" + saida
                    ),
                }
            }
        )
    )
    sys.exit(0)


main()
