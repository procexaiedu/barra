---
name: run-interface
description: Run, launch, start, build, or screenshot the Elite Baby painel (interface/ — Next.js 16 frontend). Use to boot the dev server, drive public routes headlessly, capture screenshots, read the agent-native verification contract, or confirm a frontend change works in the real app (not just unit tests).
---

# Run the painel (interface/)

Next.js 16 (App Router, Turbopack) + Tailwind v4 + shadcn/ui. Driven headlessly
by **`driver.mjs`** (this dir), which launches the Chromium that ships with the
project's `@playwright/test`, navigates a route, screenshots it, and reads the
`data-verificacao` contract published in the DOM.

**All paths below are relative to `interface/`.** Verified on macOS (Node 22,
pnpm 11); the driver is platform-agnostic (`apt-get install` not needed —
Playwright's Chromium is already in the cache).

## Prerequisites

```bash
pnpm install   # lockfile up to date → "Already up to date"; ignored-build warnings are benign
```

Node 20+ and pnpm. Playwright's Chromium is already installed (used by the e2e
suite); if it isn't, `pnpm exec playwright install chromium`.

## Run (agent path) — dev server + driver

Start the dev server (background), then drive it. **No auth, no DB, no Maps key
needed** for the public routes.

```bash
# 1. dev server — Ready in <1s, serves on :3000
pnpm dev   # run in background; logs to wherever you redirect

# 2. wait until it answers, then drive a route
node .claude/skills/run-interface/driver.mjs /verificacao/funil --out /tmp/barra-run/funil.png --contract '[data-verificacao]'
```

The driver prints JSON: `{ url, http, screenshot, console_errors, contrato }`.
On `/verificacao/funil` it returns the live funnel contract
(`{topo, perdidos_total, etapas:[...]}`) — the same JSON `pnpm verify` validates.
**Then actually open the screenshot** (`Read /tmp/barra-run/funil.png`) — a 200
with a blank or placeholder render is not success.

Driver usage:

```bash
node .claude/skills/run-interface/driver.mjs <rota> [--out file.png] [--contract <selector>] [--full]
```

**Public routes** (allowlisted in `src/proxy.ts`/middleware — no login):

| Rota | O que mostra |
|---|---|
| `/verificacao` | índice das specs agent-native (sem contrato próprio) |
| `/verificacao/funil` | fixture do funil + contrato `data-verificacao` |
| `/verificacao/kanban` | fixture do kanban + contrato |
| `/demo-mapa` | favos do Mapa de clientes (deck.gl) — **exige Maps key**, senão placeholder |
| `/painel-preview` | preview visual do painel |

Authed routes under `(interface)/` (atendimentos, agenda, modelos, dashboard…)
require a Supabase session — drive them with the e2e `authed` project, not the
public driver.

## Run (verification gate) — pnpm verify

The project's own agent-native gate. Reuse the already-running dev server with
`E2E_NO_SERVER=1` (otherwise Playwright spawns its own `pnpm dev`):

```bash
E2E_NO_SERVER=1 pnpm verify   # Playwright project "verificacao"
```

Expect **2 passed (funil, kanban), 1 failed (mapa)** on a machine **without**
`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` — the map renders a placeholder that never
publishes its contract, so the `mapa` spec fails. Set the key for a clean pass.

## Run (human path)

```bash
pnpm dev   # → http://localhost:3000 ; open in a browser ; Ctrl-C to stop
```

Useless headless (a window-less server you can't see) — for an agent, use the
driver above instead.

## Gotchas

- **Map needs a Google Maps key.** Without `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`,
  `/demo-mapa` shows *"Configure NEXT_PUBLIC_GOOGLE_MAPS_API_KEY para habilitar
  o mapa."* and the `mapa` verification spec fails. Everything else works
  keyless. This is expected, not a bug.
- **Contract lives on subpages, not `/verificacao`.** The index has no
  `data-verificacao`; drive `/verificacao/funil` or `/verificacao/kanban`.
- **`/verificacao/kanban` floods `console_errors` with a hydration warning.**
  @dnd-kit + React 19 emit a benign `aria-describedby` SSR/client mismatch
  (`DndDescribedBy-0` vs `-2`); the page renders fine and the contract still
  parses. Next.js shows it as the "1 Issue" dev badge. Ignore it — not a
  regression.
- **`E2E_NO_SERVER=1` to reuse a running dev server.** Without it, `pnpm verify`
  launches a second `pnpm dev` (180s timeout) and you race two servers on :3000.
- **`timeout` is missing on macOS.** Don't wrap commands in `timeout …`; it
  errors `command not found`. Just run them.
- **Middleware deprecation warning** (`use "proxy" instead`) on boot is benign.

## Troubleshooting

- **Driver: `Cannot find module '@playwright/test'`** → run from `interface/`
  (so Node resolves `node_modules`), or `pnpm install` first.
- **Driver: navegação falhou / ECONNREFUSED** → dev server isn't up yet. Poll
  `curl -sf http://localhost:3000/verificacao` before driving.
- **`pnpm verify` fails only on `mapa`** → missing Maps key (see Gotchas), not a
  regression.
