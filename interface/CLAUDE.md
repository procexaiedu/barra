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

`pnpm lint` é `eslint` (não `next lint`).

## Verificação agent-native: só o contrato sobrou

Padrão em `src/lib/verify/contract.ts`. Um componente publica seu estado relevante no DOM via `emitirContrato("id", estado)` → atributo `data-verificacao` (JSON) + `data-verify`, e quem verifica lê o blob em vez de raspar a UI.

**`pnpm verify` não existe mais.** O gate headless, o dashboard `/verificacao` e as invariantes (`specs/*.ts`) dependiam de **fixtures públicas** (`/verificacao/*`, `/demo-mapa`, `/painel-preview`) que eram bypass de auth no middleware, expostas em produção — removidas por auditoria de segurança. Detalhes e o caminho para reconstruir o gate **sem** rota pública: `docs/verificacao-agente.md`.

Mexeu numa superfície verificável (dashboard, mapa, funil)? Mantenha o `emitirContrato` e verifique lendo o contrato na **rota autenticada real** (Playwright MCP / project `authed`) — é a aplicação concreta do princípio §5 do CLAUDE.md raiz. Nunca reabra rota pública para isso.

## `src/tipos/` é espelho manual do backend (por enquanto)

O script de geração a partir do OpenAPI ainda **não existe** (a raiz o marca como "planejado"). Até lá, os tipos em `src/tipos/*.ts` são escritos à mão espelhando os DTOs do backend. Alterou um schema HTTP em `api/`? Atualize o tipo PT-BR correspondente aqui à mão — não há geração automática que o faça.
