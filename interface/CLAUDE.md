@AGENTS.md

# interface/CLAUDE.md

Escopo: tudo abaixo de `interface/` (Next.js 16 App Router). Complementa o CLAUDE.md raiz; não repete route groups, `lib` EN / `tipos` PT-BR nem Tailwind/shadcn (já estão lá).

## Gerenciador: pnpm (nunca npm/yarn)

`pnpm-lock.yaml` é a fonte de verdade. `npm install` quebra o lock. Adicionar dep: `pnpm add <pkg>`.

## Comandos não listados na raiz

A raiz cobre `dev`/`build`/`lint`. Aqui também há:

| Comando | O que roda |
|---|---|
| `pnpm test` / `pnpm test:watch` | vitest (unit) |
| `pnpm e2e` / `pnpm e2e:ui` | Playwright (e2e completo) |
| `pnpm verify` | **gate de verificação** — Playwright `--project=verificacao` |

`pnpm lint` é `eslint` (não `next lint`).

## Verificação agent-native é o gate desta pasta

Padrão em `src/lib/verify/` (ver `contract.ts`). Um componente publica seu estado relevante no DOM via `emitirContrato("id", estado)` → atributo `data-verificacao` (JSON) + `data-verify`. Três superfícies — dashboard, agente pelo browser (Playwright MCP) e headless/CI — leem o blob de volta e rodam as **mesmas invariantes TS puras** (`src/lib/verify/specs/`).

Mexeu numa superfície verificável (dashboard, mapa, funil)? Instrumente o contrato + spec e rode `pnpm verify` antes de considerar pronto — é a aplicação concreta do princípio §5 do CLAUDE.md raiz.

## `src/tipos/` é espelho manual do backend (por enquanto)

O script de geração a partir do OpenAPI ainda **não existe** (a raiz o marca como "planejado"). Até lá, os tipos em `src/tipos/*.ts` são escritos à mão espelhando os DTOs do backend. Alterou um schema HTTP em `api/`? Atualize o tipo PT-BR correspondente aqui à mão — não há geração automática que o faça.
