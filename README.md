# Elite Baby

Central inteligente de atendimento da agência Elite Baby. Cada modelo opera no próprio WhatsApp; uma IA dedicada (LangGraph) atende os clientes em nome dela, pausa para handoff e escala decisões para Fernando ou para a modelo. O painel é a central operacional onde tudo é monitorado e gerenciado.

Monorepo do MVP (estamos no P0). Backend FastAPI + frontend Next.js + infra self-host.

## Estrutura

- `api/` — backend Python: FastAPI, LangGraph (agente), ARQ (workers).
- `interface/` — frontend Next.js (App Router), Tailwind v4, shadcn/ui.
- `infra/` — deploy: Docker Compose, SQL (`infra/sql/`) e runbooks operacionais.
- `docs/` — produto, arquitetura (ADRs) e histórico.
- `scripts/` — utilitários de desenvolvimento.

## Pré-requisitos

- [uv](https://docs.astral.sh/uv/) e Python `>=3.12,<3.13` (backend).
- [pnpm](https://pnpm.io/) e Node 20+ (frontend).
- Acesso a Postgres (Supabase), Redis e Evolution API — ver `infra/`.

## Quick start

**Backend** (a partir de `api/`):

```bash
cp .env.example .env   # preencha as credenciais
uv sync                # instala dependências do uv.lock
make dev               # FastAPI em http://localhost:8000
make worker            # ARQ worker (segundo terminal — roda o agente e os jobs)
```

**Frontend** (a partir de `interface/`):

```bash
cp .env.example .env.local   # preencha as credenciais
pnpm install
pnpm dev                     # Next.js em http://localhost:3000
```

## Comandos comuns

Backend (`api/`):

| Comando | O que faz |
|---|---|
| `make dev` | FastAPI local |
| `make worker` | ARQ worker (agente + jobs) |
| `make test` | pytest |
| `make lint` / `make format` | ruff |
| `make typecheck` | mypy (rode antes de PR) |
| `make migrate` | aplica `infra/sql/*.sql` (exige `DATABASE_URL`) |

Frontend (`interface/`):

| Comando | O que faz |
|---|---|
| `pnpm dev` | dev server |
| `pnpm build` | build de produção |
| `pnpm lint` | eslint |
| `pnpm test` | vitest |
| `pnpm verify` | testes de verificação (Playwright) |

## Documentação

- `CONTEXT.md` — vocabulário de domínio. **Leia antes de qualquer mudança.**
- `CLAUDE.md` — princípios de implementação do projeto.
- `docs/estrutura-codebase.md` — convenção completa da árvore do monorepo.
- `docs/adr/` — decisões arquiteturais (numeradas, nunca apagadas).
- `docs/mvp/` — escopo, fluxos e regras de produto do P0.
- `docs/agente/` — arquitetura do agente LangGraph.
