---
name: run-api
description: Run, launch, start, boot, smoke-test, or test the Elite Baby backend (api/ — FastAPI + LangGraph + ARQ). Use to start the dev server, hit its HTTP surface with the curl smoke driver, check readiness, or run the pytest gate — without spending Anthropic credits or touching prod data.
---

# Run the backend (api/)

FastAPI (LangGraph agent + ARQ workers) on Python 3.12 via `uv`. The HTTP
surface is driven by **`smoke.sh`** (this dir) — curl against read-only infra
endpoints only: no mutations, no Anthropic calls, no agent turn.

**All paths below are relative to `api/`.** Verified on macOS (Python via uv,
uv 0.11).

> ⚠️ **`api/.env` points `DATABASE_URL` at the prod self-hosted Postgres**
> (`db.procexai.tech`). Booting locally connects to **prod**. The smoke driver
> is read-only (`/health`, `/ready`'s `SELECT 1`) and safe. Do **not** run
> `make migrate` (applies seeds to prod) or any mutating flow against this boot.

## Prerequisites

```bash
uv sync   # installs from uv.lock; "Checked NNN packages" when already synced
```

`uv` and Python `>=3.12,<3.13`. `jq` is used by the smoke driver for pretty
field output (it still passes without `jq`, just less readable). Never `pip
install` — it breaks the lock (see api/CLAUDE.md).

## Run (agent path) — dev server + smoke

```bash
# 1. boot — "Application startup complete." in ~1s
make dev   # = uv run python -m barra ; serves on :8000 ; run in background

# 2. smoke the HTTP surface
.claude/skills/run-api/smoke.sh
```

Expected smoke output — all ✓, exit 0:

```
✓ health  /health → HTTP 200  (.status = ok)
✓ ready  /ready → HTTP 200  (.status, .db, .redis = degraded / true / false)
✓ metrics  /metrics → HTTP 200
✓ openapi  /openapi.json → HTTP 200  (.info.title = Elite Baby API)
✓ docs  /docs → HTTP 200
== OK ==
```

`/ready` returning **`degraded` with `db:true, redis:false` is normal in dev** —
the DB (prod) is reachable, Redis lives in the swarm and isn't. `/v1/*` routes
require a Supabase JWT; the smoke covers the unauthenticated infra surface.

## Test (gate)

```bash
make test        # uv run pytest -m "not needs_key" → ~820 passed, ~75 skipped, ~18s
make typecheck   # mypy src — run before any PR
make lint        # ruff check
```

- The ~75 **skipped** tests are `needs_db` — they want a `TEST_DATABASE_URL`
  (separate test DB with rollback). Set it to run them; skipping is expected.
- `make test-llm` (`-m needs_key`) hits the real Anthropic API and **costs
  credit** — run it deliberately, not as routine sanity.

## Run (human path)

```bash
make dev   # → http://localhost:8000 ; interactive docs at /docs ; Ctrl-C to stop
```

## Worker / agent (not smoke-tested here)

`make worker` (`arq barra.workers.settings.WorkerSettings`) runs the LangGraph
agent that processes WhatsApp turns. It needs a **reachable Redis** (swarm only —
unreachable from local dev) **and Anthropic credits**, so it's out of scope for
the local smoke. Don't assume it runs from a plain `make dev` machine.

## Gotchas

- **Dev boots against prod DB.** `api/.env` has `AMBIENTE=desenvolvimento` but a
  prod `DATABASE_URL`. Reads are fine; never mutate. `make migrate` is forbidden
  here (would push seeds into prod).
- **Redis/MinIO are swarm-only.** In dev they're unreachable → the lifespan
  fails *soft* (logs `redis_indisponivel_dev` / `minio_indisponivel_dev`, boots
  without ARQ/media). In `AMBIENTE=producao` the same failures are fatal.
- **`make dev`, never raw `uvicorn`.** `python -m barra` sets the event-loop
  policy before the loop is created — required on Windows (raw `uvicorn` hangs on
  the ProactorEventLoop and 500s every DB endpoint). See `src/barra/__main__.py`.
- **`/docs` is disabled when `AMBIENTE=producao`** (so a prod smoke would 404 on
  `/docs` by design — it's 200 only in dev/teste).
- **`needs_db` tests skip silently** without `TEST_DATABASE_URL` — a green
  `make test` with 75 skips hasn't exercised the SQL integration layer.

## Troubleshooting

- **`make dev` hangs / 500s on DB endpoints** → almost always Windows on the
  ProactorEventLoop; use `make dev` (not raw uvicorn) and check `__main__.py`.
- **Smoke `/ready` shows `db:false`** → DB unreachable (VPN/host down). The prod
  Postgres is `db.procexai.tech`; `/health` (no DB) still returns 200.
- **`smoke.sh` fields blank** → `jq` not installed; HTTP codes still validate, or
  `brew install jq`.
- **Boot logs a Redis TimeoutError then continues** → expected in dev (fail-soft,
  see Gotchas), not a failure.
