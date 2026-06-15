# Mapa do repositório

Monorepo plano. Árvore orientativa — pastas novas podem existir sem estar listadas.

```
barra/
├── CLAUDE.md
├── CONTEXT.md
├── docs/
│   ├── mvp/                    # produto e domínio (00-indice …)
│   └── adr/
├── api/                        # backend — FastAPI, LangGraph, ARQ
│   ├── pyproject.toml, uv.lock, Makefile, Dockerfile, .env.example
│   ├── src/barra/
│   │   ├── main.py             # FastAPI app + lifespan
│   │   ├── settings.py
│   │   ├── core/               # cross-cutting (sem regra de negócio)
│   │   │   ├── db.py, redis.py, storage.py, llm.py, evolution.py
│   │   │   ├── errors.py, auth.py, metrics.py, logging.py, tracing.py
│   │   ├── agente/             # LangGraph
│   │   │   ├── graph.py, estado.py, classificador.py, contexto.py, persona.py, llm.py
│   │   │   ├── prompts/       # persona.md, faq.md, regras.md
│   │   │   ├── nos/, ferramentas/
│   │   ├── dominio/            # bounded contexts — cada pasta: routes, service, repo, modelos, schemas
│   │   │   ├── conversas/
│   │   │   ├── atendimentos/
│   │   │   ├── clientes/
│   │   │   ├── modelos/
│   │   │   ├── agenda/
│   │   │   ├── pix/
│   │   │   ├── escaladas/
│   │   │   ├── eventos/
│   │   │   ├── dashboard/
│   │   │   ├── financeiro/
│   │   │   ├── painel/
│   │   │   └── tarefas/
│   │   ├── webhook/            # Evolution — token, allowlist, debounce; não é REST público
│   │   │   ├── routes.py, parser.py, filtro.py, debounce.py, despacho.py
│   │   ├── workers/            # ARQ
│   │   │   ├── settings.py, envio.py, timeouts.py, media.py, pix.py
│   │   └── api/                # deps.py, v1.py
│   └── tests/
├── interface/                  # Next.js 16 — App Router
│   ├── src/app/
│   │   ├── layout.tsx, page.tsx, globals.css
│   │   ├── (auth)/login/
│   │   └── (interface)/        # atendimentos, agenda, clientes, modelos, pix, dashboard, financeiro, tarefas, avaliacao
│   ├── src/components/ui/
│   ├── src/lib/
│   └── src/tipos/              # gerado a partir do OpenAPI (script planejado)
├── infra/
│   ├── compose/stack.barra.yml
│   ├── compose/env/
│   ├── sql/                    # NNNN_*.sql sequencial
│   └── runbooks/
├── scripts/
└── .agents/, .claude/
```
