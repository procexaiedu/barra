"""PostToolUse — lembra do reload do worker ao editar o agente (api/src/barra/agente/).

O LangGraph roda no servico barra-worker, NAO na API. Editar codigo do agente ou os prompts
(agente/prompts/*.md) nao reflete em producao ate o worker recarregar — em Swarm isso e
`docker service update --force <stack>_barra-worker`, NUNCA `docker restart` (cria task orfa
que duplica entregas via ARQ). Este hook so injeta um lembrete; nunca bloqueia.

Memorias: deploy_agente_roda_no_worker, workers_orfaos_swarm_redis.
Falha aberta: qualquer erro deixa a edicao seguir (exit 0).
"""

import json
import sys

LEMBRETE = (
    "Voce editou codigo/prompt do agente (api/src/barra/agente/). O LangGraph roda no servico "
    "barra-worker, nao na API: a mudanca so vale em PRODUCAO depois de recarregar o worker com "
    "`docker service update --force <stack>_barra-worker` (NUNCA `docker restart` em Swarm — "
    "cria task orfa que duplica entregas ARQ). Em dev, reinicie o `make worker`. Procedimento "
    "completo: skill /redeploy-prod."
)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    fp = (tool_input.get("file_path") or "").replace("\\", "/")

    if "/api/src/barra/agente/" not in fp:
        sys.exit(0)

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": LEMBRETE,
                },
                "systemMessage": (
                    "ATENCAO: agente editado — prod so reflete apos reload do barra-worker "
                    "(docker service update --force; nunca docker restart)."
                ),
            }
        )
    )
    sys.exit(0)


main()
