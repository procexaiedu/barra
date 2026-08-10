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

Start the dev server (background), then drive it.

```bash
# 1. dev server — Ready in <1s, serves on :3000
pnpm dev   # run in background; logs to wherever you redirect

# 2. wait until it answers, then drive a route
node .claude/skills/run-interface/driver.mjs /login --out /tmp/barra-run/login.png
```

The driver prints JSON: `{ url, http, screenshot, console_errors, contrato }`.
**Then actually open the screenshot** (`Read /tmp/barra-run/login.png`) — a 200
with a blank or placeholder render is not success.

Driver usage:

```bash
node .claude/skills/run-interface/driver.mjs <rota> [--out file.png] [--contract <selector>] [--full]
```

**`/login` is the only route without auth.** The public fixtures
(`/verificacao/*`, `/demo-mapa`, `/painel-preview`) were an auth bypass in the
middleware, live in production, and have been **removed** — do not reintroduce
them. Everything else redirects to `/login`.

## Run (authed routes) — e2e `authed` project

Everything under `(interface)/` (painel, atendimentos, agenda, modelos,
dashboard, clientes…) needs a Supabase session. Drive it through Playwright's
`authed` project, which depends on `setup` (`tests/e2e/auth.setup.ts` writes
`tests/e2e/.auth/state.json`):

```bash
E2E_NO_SERVER=1 pnpm e2e --project=authed   # reuses the dev server you started
```

The verification contract (`data-verificacao`, see `docs/verificacao-agente.md`)
is published by four real components — `FunilVendas`/`BlocoNorteCotacao` on
`/dashboard`, `KanbanBoard` on `/atendimentos`, `MapaClientes` on `/clientes` —
so read it **there**, on the authenticated page, with Playwright MCP or a spec
in the `authed` project.

## Run (human path)

```bash
pnpm dev   # → http://localhost:3000 ; open in a browser ; Ctrl-C to stop
```

Useless headless (a window-less server you can't see) — for an agent, use the
driver above instead.

## Gotchas

- **Map needs a Google Maps key.** Without `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`,
  `/clientes` shows *"Configure NEXT_PUBLIC_GOOGLE_MAPS_API_KEY para habilitar
  o mapa."* and never publishes the `mapa` contract. Everything else works
  keyless. This is expected, not a bug.
- **The kanban floods `console_errors` with a hydration warning.**
  @dnd-kit + React 19 emit a benign `aria-describedby` SSR/client mismatch
  (`DndDescribedBy-0` vs `-2`); the page renders fine and the contract still
  parses. Next.js shows it as the "1 Issue" dev badge. Ignore it — not a
  regression.
- **`E2E_NO_SERVER=1` to reuse a running dev server.** Without it, Playwright
  launches a second `pnpm dev` (180s timeout) and you race two servers on :3000.
- **`timeout` is missing on macOS.** Don't wrap commands in `timeout …`; it
  errors `command not found`. Just run them.
- **Middleware deprecation warning** (`use "proxy" instead`) on boot is benign.

## Troubleshooting

- **Driver: `Cannot find module '@playwright/test'`** → run from `interface/`
  (so Node resolves `node_modules`), or `pnpm install` first.
- **Driver: navegação falhou / ECONNREFUSED** → dev server isn't up yet. Poll
  `curl -sf http://localhost:3000/login` before driving.
- **Driver lands on `/login` for any other route** → expected, not a bug: the
  middleware protects everything else. Use the `authed` project.
