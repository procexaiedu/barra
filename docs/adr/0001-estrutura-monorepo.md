---
data: 2026-04-29
status: aceito
---

# ADR-0001 — Estrutura monorepo plana com `api/` e `interface/`

> **Nota 2026-05-13**: pasta originalmente nomeada `painel/` foi renomeada para `interface/` durante o P0 sem mudança arquitetural. Conteúdo do ADR mantido com o nome atual.

## Contexto

MVP da Central Inteligente de Atendimento Barra Vips precisa hospedar dois deployáveis: backend Python (FastAPI + LangGraph + ARQ) e painel Next.js. Equipe é Lucas + sócio + Fernando como cliente. Não há, no horizonte do MVP, pacote compartilhado entre frontend e backend (tipos OpenAPI são gerados, não compartilhados como pacote npm).

## Decisão

Adotar monorepo **plano** com pastas raiz `api/`, `interface/`, `infra/`, `docs/`, `scripts/`. Não usar Turborepo, pnpm workspace, nem `apps/` + `packages/`. Backend Python segue **src layout** (`api/src/barra/`) com organização **feature-first** por bounded context (`dominio/<contexto>/`), agente LangGraph isolado em `agente/`, webhook em `webhook/`, workers ARQ em `workers/`.

## Consequências

**Positivas**
- Zero overhead de ferramenta de monorepo enquanto não há pacote compartilhado.
- Cada deployável tem ciclo de build/CI independente (Vercel para painel, Portainer para api+worker).
- Bounded contexts do `docs/mvp/03` mapeiam 1:1 em pastas — mudança cirúrgica fica natural.

**Negativas**
- Sem cache de build cross-app (Turborepo).
- Tipos OpenAPI precisam ser gerados manualmente via `scripts/gera_tipos_openapi.sh`.

**Reversíveis**
- Migrar para `apps/` + `packages/` é renomear pasta + adicionar `pnpm-workspace.yaml`. Custo baixo, fica como caminho aberto.
