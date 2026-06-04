---
data: 2026-04-29
status: vivo
---

# Estrutura da codebase — Elite Baby MVP

Documento vivo com a árvore completa do monorepo, convenções de organização e fluxo de git worktree.

Decisões arquiteturais por trás dessa estrutura:
- `docs/adr/0001-estrutura-monorepo.md` — por que monorepo plano em vez de Turborepo/pnpm workspace.
- `docs/adr/0002-psycopg-puro-vs-orm.md` — por que SQL puro em vez de SQLModel/SQLAlchemy.

Legenda:
- ✓ existe no repo (commits `cd4f879` e `6543521`).
- ○ planejado / criado quando a primeira feature do contexto cair.

---

## 1. Árvore completa

```
barra-vips/
├── .git/                                  ✓
├── .gitignore                             ✓ Python + Node + IDE + .env + .trees/
├── .gitattributes                         ✓ eol=lf, *.png/jpg binary, lockfiles preservados
├── .editorconfig                          ✓
├── AGENTS.md                              ✓ pré-existente
├── CLAUDE.md                              ✓ pré-existente — princípios de implementação
├── CONTEXT.md                             ✓ pré-existente — vocabulário de domínio
├── README.md                              ○ a escrever quando o setup ficar estável
├── ata.txt                                ✓ histórico — mover para docs/historico/ depois
├── skills-lock.json                       ✓ gerado pelo Claude Code
│
├── docs/
│   ├── mvp/                               ✓ 00-indice .. 07-stack-tecnica
│   │   ├── 00-indice.md
│   │   ├── 01-contexto-negocio.md
│   │   ├── 02-mvp-escopo.md
│   │   ├── 03-modulos-sistema.md
│   │   ├── 04-fluxos-operacionais.md
│   │   ├── 05-escalada-regras-ia.md
│   │   ├── 06-dados-interfaces.md
│   │   └── 07-stack-tecnica.md
│   ├── adr/                               ✓ Architecture Decision Records
│   │   ├── 0001-estrutura-monorepo.md
│   │   └── 0002-psycopg-puro-vs-orm.md
│   ├── estrutura-codebase.md              ✓ este arquivo
│   └── historico/                         ○ destino sugerido para ata.txt
│
├── api/                                   ✓ backend Python — FastAPI + LangGraph + ARQ
│   ├── pyproject.toml                     ✓ uv project + ruff + mypy + pytest
│   ├── uv.lock                            ✓
│   ├── .python-version                    ✓ 3.12
│   ├── .env.example                       ✓
│   ├── Dockerfile                         ✓ multi-stage com uv 0.5
│   ├── Makefile                           ✓ dev / worker / test / lint / format / migrate / sync
│   │
│   ├── src/
│   │   └── barra/                         ✓ pacote raiz importável (src layout)
│   │       ├── __init__.py                ✓
│   │       ├── main.py                    ✓ FastAPI app + lifespan
│   │       ├── settings.py                ✓ Pydantic BaseSettings
│   │       │
│   │       ├── core/                      ✓ cross-cutting; nada de regra de negócio
│   │       │   ├── __init__.py
│   │       │   ├── db.py                  ✓ stub — AsyncConnectionPool (Supavisor 6543)
│   │       │   ├── redis.py               ✓ stub — ARQ pool + cache + dedupe
│   │       │   ├── storage.py             ✓ stub — MinIO client (tag pinada)
│   │       │   ├── llm.py                 ✓ stub — Anthropic + cache_control
│   │       │   ├── evolution.py           ✓ stub — cliente HTTP Evolution
│   │       │   ├── logging.py             ✓ stub — structlog JSON + correlation id
│   │       │   ├── tracing.py             ✓ stub — LangSmith setup
│   │       │   └── errors.py              ✓ ErroDominio + JidNaoPermitido
│   │       │
│   │       ├── agente/                    ✓ LangGraph — orquestrador da IA
│   │       │   ├── __init__.py
│   │       │   ├── graph.py               ✓ stub — build_graph() + AsyncPostgresSaver
│   │       │   ├── estado.py              ✓ stub — TypedDict do State (espelha 04 §8)
│   │       │   ├── humanizacao.py         ✓ stub — split em chunks + jitter
│   │       │   ├── classificador.py       ✓ stub — saída interna/externa + ambiguity question
│   │       │   ├── nos/                   ✓ vazio — 1 arquivo por estado
│   │       │   ├── ferramentas/           ✓ vazio — tools (bloqueia_agenda, valida_pix...)
│   │       │   └── prompts/               ✓ prefixos cacheados pela Anthropic (TTL 1h)
│   │       │       ├── persona.md
│   │       │       ├── faq.md
│   │       │       └── regras.md
│   │       │
│   │       ├── dominio/                   ✓ bounded contexts (mapeia docs/mvp/03)
│   │       │   ├── conversas/             ✓ contexto exemplo CHEIO
│   │       │   │   ├── __init__.py
│   │       │   │   ├── routes.py          ✓ endpoints HTTP
│   │       │   │   ├── service.py         ✓ stub — casos de uso
│   │       │   │   ├── repo.py            ✓ stub — SQL puro psycopg3
│   │       │   │   ├── modelos.py         ✓ Pydantic v2 (Conversa, Mensagem, DirecaoMensagem)
│   │       │   │   └── schemas.py         ✓ DTOs HTTP
│   │       │   ├── atendimentos/          ✓ stub — replicar layout de conversas/
│   │       │   ├── clientes/              ✓ stub
│   │       │   ├── modelos/               ✓ stub — contexto "Modelos da agência"
│   │       │   ├── agenda/                ✓ stub — bloqueios de agenda
│   │       │   ├── pix/                   ✓ stub — comprovantes
│   │       │   ├── escaladas/             ✓ stub — handoff/devolução, alertas
│   │       │   └── eventos/               ✓ stub — audit log humano-legível
│   │       │
│   │       ├── webhook/                   ✓ entrada Evolution API
│   │       │   ├── __init__.py
│   │       │   ├── routes.py              ✓ POST /webhook/evolution
│   │       │   ├── filtro.py              ✓ placeholder vazio — gates reais em routes.py/despacho.py
│   │       │   ├── debounce.py            ✓ stub — multi-device + 60s (estado em Redis)
│   │       │   └── despacho.py            ✓ stub — roteia para graph.ainvoke
│   │       │
│   │       ├── workers/                   ✓ ARQ
│   │       │   ├── __init__.py
│   │       │   ├── settings.py            ✓ stub — WorkerSettings + dedupe_key
│   │       │   ├── envio.py               ✓ stub — envia chunk humanizado
│   │       │   ├── timeouts.py            ✓ stub — varre interrupts pendentes
│   │       │   └── pix.py                 ✓ stub — validações OCR + checagens
│   │       │
│   │       └── api/                       ✓ composição HTTP — agrega routers
│   │           ├── __init__.py
│   │           ├── deps.py                ✓ stub — Depends() compartilhados
│   │           └── v1.py                  ✓ APIRouter raiz + /saude
│   │
│   ├── tests/
│   │   ├── conftest.py                    ✓ fixture anyio_backend
│   │   ├── test_smoke.py                  ✓ /v1/saude → 200
│   │   ├── unit/                          ✓ vazio — 1 espelho por módulo de dominio/
│   │   ├── integracao/                    ✓ vazio — webhook → graph → db real
│   │   └── conversas/                     ✓ vazio — bateria das 36 conversas (Fase 1.5)
│   │       └── fixtures/                  ○
│   │
│   └── evals/                             ✓ LangSmith datasets + offline eval
│       ├── datasets/                      ✓ vazio
│       └── runners/                       ✓ vazio
│
├── interface/                                ✓ frontend Next.js 16.2 — App Router
│   ├── AGENTS.md                          ✓ aviso do create-next-app sobre breaking changes do Next 16
│   ├── CLAUDE.md                          ✓ aponta para AGENTS.md
│   ├── README.md                          ✓ default do create-next-app
│   ├── components.json                    ✓ shadcn/ui (data-slot pattern)
│   ├── eslint.config.mjs                  ✓
│   ├── next.config.ts                     ✓
│   ├── next-env.d.ts                      gerado, não commitado
│   ├── package.json                       ✓
│   ├── pnpm-lock.yaml                     ✓
│   ├── postcss.config.mjs                 ✓ Tailwind v4 plugin
│   ├── tsconfig.json                      ✓
│   ├── .env.example                       ✓ NEXT_PUBLIC_API_URL + Supabase
│   ├── public/                            ✓ ícones default
│   └── src/
│       ├── app/
│       │   ├── layout.tsx                 ✓ root layout
│       │   ├── globals.css                ✓ Tailwind v4 + shadcn tokens
│       │   ├── page.tsx                   ✓ landing → /login
│       │   ├── (auth)/
│       │   │   └── login/page.tsx         ✓ stub Supabase Auth
│       │   └── (interface)/
│       │       ├── layout.tsx             ✓ sidebar com 7 links
│       │       ├── interface/page.tsx        ✓ interface Geral
│       │       ├── atendimentos/page.tsx  ✓ Central de Atendimentos
│       │       ├── agenda/page.tsx        ✓ Agenda Operacional
│       │       ├── crm/page.tsx           ✓ CRM
│       │       ├── modelos/page.tsx       ✓ Modelos & Base de Conhecimento
│       │       ├── pix/page.tsx           ✓ Pix & Comprovantes
│       │       └── dashboard/page.tsx     ✓ Dashboard
│       ├── components/
│       │   └── ui/                        ✓ shadcn (button.tsx — adicionar mais via CLI)
│       ├── lib/
│       │   ├── utils.ts                   ✓ cn() do shadcn
│       │   ├── supabase.ts                ✓ stub — client + server
│       │   ├── realtime.ts                ✓ stub — Postgres Changes hooks
│       │   └── api.ts                     ✓ fetcher tipado para FastAPI
│       └── tipos/                         ✓ vazio — gerado a partir do OpenAPI do FastAPI
│
├── infra/                                 ✓ Portainer stacks via Git
│   ├── compose/
│   │   ├── stack.barra.yml                ✓ api + worker + redis + minio + evolution + traefik
│   │   ├── traefik/                       ✓ vazio
│   │   │   ├── traefik.yml                ○
│   │   │   └── dynamic/                   ○
│   │   └── env/                           ✓ vazio — .env.exemplo por serviço (sem segredos)
│   ├── sql/                               ✓ SQL puro sequencial — fonte unica das migrations
│   │   ├── 0001_schema_inicial.sql        ✓
│   │   └── 0002_envios_evolution.sql      ✓
│   ├── portainer/                         ○
│   │   └── webhooks.md                    ○ como o redeploy é disparado
│   └── runbooks/                          ✓ vazio
│       ├── restaurar-vps.md               ○
│       ├── migrar-minio-seaweedfs.md      ○ plano B do MinIO arquivado
│       └── rotacao-evolution.md           ○
│
├── scripts/                               ✓ utilitários — nunca código de produção
│   ├── seed_dev.py                        ○
│   ├── gera_tipos_openapi.sh              ○ FastAPI → interface/src/tipos
│   └── conversa_replay.py                 ○
│
├── .agents/                               ✓ pré-existente — skills de agente
└── .claude/                               ✓ pré-existente — settings, skills
    └── settings.json
```

---

## 2. Convenções de organização

### 2.1 Backend (`api/`)

- **src layout**: pacote em `src/barra/`, instalado em modo editable pelo `uv sync`. Evita import-shadowing e força `from barra.x import y` nos testes.
- **Feature-first em `dominio/`**: cada bounded context é uma pasta com seu próprio `routes.py + service.py + repo.py + modelos.py + schemas.py`. Não há `models/` ou `services/` globais.
- **Nomes em PT-BR no domínio, EN no técnico**: `dominio/conversas/`, `dominio/atendimentos/`, `Conversa`, `DirecaoMensagem`. Funções de infra usam vocabulário comum (`build_app`, `lifespan`, `router`).
- **Cuidado com colisão**: `dominio/modelos/` (entidade "Modelo da agência") ≠ `modelos.py` dentro de cada contexto (Pydantic v2). O segundo nunca é importado entre contextos.
- **Camadas internas de cada contexto**:
  - `routes.py` — só HTTP. Pydantic in/out, status codes, `Depends()`.
  - `service.py` — orquestra repo + agente + redis. Recebe e retorna entidades, não DTOs HTTP.
  - `repo.py` — SQL puro psycopg3. Recebe `AsyncConnection` do pool.
  - `modelos.py` — entidades + value objects (Pydantic v2).
  - `schemas.py` — DTOs HTTP (request/response).
- **`agente/` ≠ `dominio/`**: o agente LangGraph chama `dominio/*/service.py` para fazer trabalho real. Domínio não importa nada de `agente/`.
- **`webhook/` ≠ `api/`**: webhook tem token, JID allowlist, debounce, retry. Não é API REST pública. Roteia para `agente.graph` via `webhook/despacho.py`.
- **`workers/` compartilha o pacote**: ARQ worker importa de `core/`, `dominio/`, `agente/`. Container roda com entrypoint diferente.

### 2.2 Frontend (`interface/`)

- **src layout**: `interface/src/app/`, `interface/src/lib/`, `interface/src/components/`.
- **Route groups**: `(auth)/` e `(interface)/` separam contextos sem aparecer na URL.
- **Components em EN**: `src/components/ui/` é convenção forte do shadcn — quebrar isso é fricção. Componentes próprios também ficam em `src/components/`.
- **Lib em EN**: `src/lib/{supabase,realtime,api}.ts` por convenção da comunidade Next.js.
- **`tipos/` em PT-BR**: gerados via `scripts/gera_tipos_openapi.sh` a partir do OpenAPI do FastAPI.

### 2.3 Documentação (`docs/`)

- `mvp/` — produto e domínio, numerados (00..NN).
- `adr/` — uma decisão por arquivo, numerada (0001..NNNN), nunca apagar (substituir com `status: superseded`).
- `historico/` — material descartável de referência (atas, drafts antigos).

### 2.4 Infra (`infra/`)

- `compose/stack.barra.yml` — fonte do redeploy do Portainer (Git + webhook).
- `compose/env/` — `.env.exemplo` por serviço, **nunca** segredos.
- `sql/` — fonte única das migrations da aplicação. SQL puro sequencial (`NNNN_nome.sql`), aplicado em ordem via `psql` ou Supabase Studio. Sem migration framework.
- `runbooks/` — Markdown numerado para operação manual (restauração VPS, migração MinIO, rotação Evolution).

---

## 3. Git worktree — fluxo recomendado

### 3.1 Quando vale a pena

Worktree paga em três cenários do projeto:

1. **Eval rodando em background**: roda `evals/` em worktree A com `main`, mexe em `feat/agente-novo-no` em worktree B.
2. **Bateria de 36 conversas (Fase 1.5)**: cada run leva minutos; isolar em worktree próprio evita travar a branch principal.
3. **Sessões Claude paralelas em features independentes**: ex. `feat/pix-validacao-ocr` + `feat/agente-no-triagem` simultâneos.

Limite prático: **2–4 worktrees ativos**. Acima disso, o overhead de revisão mata o ganho.

### 3.2 Convenção de branches

| Prefixo | Uso |
|---|---|
| `feat/<contexto>-<verbo>` | nova feature: `feat/pix-validacao-ocr`, `feat/agente-no-triagem` |
| `fix/<area>-<descricao>` | correção: `fix/webhook-debounce-multi-device` |
| `chore/...` | manutenção sem efeito em produção |
| `docs/...` | só documentação |
| `infra/...` | mudanças em `infra/` |
| `spike/<tema>` | exploratório, deletável; nunca vai para `main` |

### 3.3 Comandos

Worktrees ficam **fora** do diretório do repo para não confundir o file watcher do Next.js:

```bash
# criar diretório-pai uma vez
mkdir C:\barra-trees

# criar worktree para uma feature
git -C C:\barra worktree add C:\barra-trees\pix-ocr feat/pix-validacao-ocr

# listar worktrees ativos
git -C C:\barra worktree list

# remover quando terminar (após merge da branch)
git -C C:\barra worktree remove C:\barra-trees\pix-ocr
```

Se preferir worktrees dentro do repo, use `.trees/` — já está no `.gitignore`.

### 3.4 Cada worktree precisa de seu próprio ambiente

- **`api/.venv/`** — `uv sync` por worktree (rápido, link de disco do uv).
- **`interface/node_modules/`** — `pnpm install` por worktree (também usa store global do pnpm).
- **`api/.env` e `interface/.env`** — copiar de `.env.example` em cada worktree.

Não compartilhar estado de banco/Redis entre worktrees: configurar prefixos de schema diferentes ou usar Supabase branches (`mcp_supabase__create_branch`) para isolamento.

---

## 4. Status atual

| Item | Estado |
|---|---|
| Commits | `cd4f879` (backend) + `6543521` (interface) na `main` |
| `uv sync` | OK (~100 deps) |
| `uv run pytest` | 1 passed (`test_smoke.py`) |
| `uv run ruff check` | All checks passed |
| `pnpm install` | OK (467 deps) |
| `pnpm run lint` | clean |
| `pnpm run build` | 12 rotas estáticas geradas |

### Próximos passos imediatos

1. `scripts/gera_tipos_openapi.sh` ligando FastAPI → `interface/src/tipos/`.
2. Decidir destino de `ata.txt` (mover para `docs/historico/` ou apagar).
