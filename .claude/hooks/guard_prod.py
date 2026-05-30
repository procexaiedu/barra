"""PreToolUse guard — protege o banco de PRODUCAO contra footguns conhecidos.

Le o JSON do hook no stdin e decide via permissionDecision:
- BLOQUEIA `make migrate` (aplica TODO infra/sql/, incluindo seeds descartaveis).
- BLOQUEIA aplicacao de arquivos *_seed_*.sql via psql/psycopg.
- PEDE CONFIRMACAO ao editar api/.env (aponta pra producao; segredos reais).

Falha aberta: qualquer erro de parse/execucao deixa a chamada seguir (exit 0).
Regra de dominio: ver CLAUDE.md ("make migrate e proibido contra producao").
"""

import json
import re
import sys


def _decide(decision: str, reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    if tool == "Bash":
        cmd = tool_input.get("command") or ""
        # Ancorado a posicao de comando (inicio ou apos ; && || | ( ou nova linha)
        # para pegar a EXECUCAO real, nao mencoes em grep/echo/ls/cat.
        if re.search(
            r"(?:^|&&|\|\||[\n;|(])\s*(?:cd\s+[^\n;&|]*&&\s*)?make\s+migrate\b",
            cmd,
            re.I,
        ):
            _decide(
                "deny",
                "BLOQUEADO: `make migrate` aplica TODO o infra/sql/, incluindo os seeds "
                "descartaveis (*_seed_*.sql), no banco de DATABASE_URL — e api/.env aponta "
                "pra PRODUCAO. Use a skill /aplicar-schema-prod (so schema, pula seeds).",
            )
        if re.search(
            r"(?:^|&&|\|\||[\n;|(])\s*(?:sudo\s+)?(?:psql|python\d?|uv\s+run\s+\S+)\b"
            r"[^\n]*_seed_[\w-]*\.sql",
            cmd,
            re.I,
        ):
            _decide(
                "deny",
                "BLOQUEADO: este comando aplica um arquivo *_seed_*.sql (dados de teste "
                "descartaveis). Em producao aplique apenas migrations de schema "
                "(NNNN_<nome>.sql, sem 'seed').",
            )
        sys.exit(0)

    if tool in ("Edit", "Write"):
        fp = (tool_input.get("file_path") or "").replace("\\", "/")
        if re.search(r"/api/\.env$", fp):
            _decide(
                "ask",
                "ATENCAO: api/.env aponta para o banco/instancia de PRODUCAO (segredos reais). "
                "Confirme que a edicao e intencional. Para template, edite api/.env.example.",
            )
        sys.exit(0)

    sys.exit(0)


main()
