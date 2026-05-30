"""PostToolUse — formata e corrige arquivos .py do backend apos Edit/Write.

Roda `uv run ruff format` + `uv run ruff check --fix` no arquivo editado, a partir
do diretorio api/ (onde vive a config do ruff no pyproject.toml). Best-effort:
qualquer falha (uv ausente, erro do ruff) e silenciosa e NUNCA bloqueia a edicao.
"""

import json
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

    if not norm.endswith(".py") or "/api/" not in norm:
        sys.exit(0)

    api_dir = norm[: norm.rfind("/api/")] + "/api"
    try:
        subprocess.run(["uv", "run", "ruff", "format", fp], cwd=api_dir, capture_output=True)
        subprocess.run(
            ["uv", "run", "ruff", "check", "--fix", fp], cwd=api_dir, capture_output=True
        )
    except (FileNotFoundError, OSError):
        pass
    sys.exit(0)


main()
