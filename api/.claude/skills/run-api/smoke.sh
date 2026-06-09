#!/usr/bin/env bash
# Smoke do backend FastAPI (api/). Bate só endpoints read-only de infra —
# nenhum mutation, nenhuma chamada à API Anthropic (não gasta crédito), não
# dispara o agente. Pressupõe `make dev` rodando em :8000.
#
# Uso (a partir de api/):
#   .claude/skills/run-api/smoke.sh
#   BASE_URL=http://localhost:8000 .claude/skills/run-api/smoke.sh
#
# Sai 0 se /health, /ready, /metrics, /openapi.json e /docs respondem como
# esperado; 1 na primeira falha.

set -u
BASE="${BASE_URL:-http://localhost:8000}"
falhou=0

checa() {
  local nome="$1" url="$2" esperado="$3" jqf="${4:-}"
  local code body
  body=$(curl -s -w $'\n%{http_code}' "$BASE$url" 2>/dev/null)
  code="${body##*$'\n'}"
  body="${body%$'\n'*}"
  if [ "$code" != "$esperado" ]; then
    echo "✗ $nome  $url → HTTP $code (esperado $esperado)"
    falhou=1
    return
  fi
  if [ -n "$jqf" ]; then
    local got
    got=$(printf '%s' "$body" | jq -r "$jqf" 2>/dev/null)
    echo "✓ $nome  $url → HTTP $code  ($jqf = $got)"
  else
    echo "✓ $nome  $url → HTTP $code  (${#body} bytes)"
  fi
}

echo "== smoke @ $BASE =="
checa health   /health        200 '.status'
checa ready    /ready         200 '.status, .db, .redis'   # status pode ser "degraded" sem Redis — ainda 200
checa metrics  /metrics       200
checa openapi  /openapi.json  200 '.info.title'
checa docs     /docs          200

if [ "$falhou" = 0 ]; then echo "== OK =="; else echo "== FALHOU =="; fi
exit "$falhou"
