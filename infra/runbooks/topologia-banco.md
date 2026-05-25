# Topologia do banco de dados

Onde os dados do Barra vivem, como conectar e o que evitar. Levantado e verificado em 2026-05-25.

## Resumo em uma frase

Existe **um único banco PostgreSQL**, um **Supabase self-hosted** rodando na infra da empresa (Docker/Portainer). Não há mais separação "dev" e "prod" — tudo aponta para o mesmo lugar.

## O que é

O projeto começou no **Supabase Cloud** (gerenciado em `supabase.com`, projeto `zinrqzsxvpqfoogohrwg`). Em 2026-05-25 isso foi **abandonado** e migrado para um **Supabase self-hosted**: o mesmo software do Supabase (PostgreSQL + Auth/GoTrue + Storage + Realtime), mas hospedado pela empresa em vez da nuvem da Supabase.

| Item | Valor |
|---|---|
| Engine | PostgreSQL 15.8 (imagem `supabase/postgres`) |
| Banco | único: `postgres` |
| Schema da aplicação | **`barravips`** (as tabelas do produto) |
| Schemas do Supabase | `auth`, `storage`, `realtime`, `graphql_public`, `_realtime` |
| Servidor real (interno) | `10.0.0.62:5432` |
| Endereço externo | `db.procexai.tech:5433` — **proxy/pooler** na frente do servidor real |
| Realtime | publication `supabase_realtime` ativa (o painel usa para atualizar em tempo real) |

`db.procexai.tech:5433` e `10.0.0.62:5432` são **o mesmo Postgres** — o `:5433` é só o ponto de entrada publicado. Confirme com `SELECT current_database(), inet_server_addr(), inet_server_port();`.

## Como conectar

- **Backend / app**: `DATABASE_URL` em `api/.env` → `postgresql://postgres:...@db.procexai.tech:5433/postgres` (`sslmode=disable`). É também o que roda em prod (secret no Portainer).
- **MCP postgres** (Claude Code): conexão default já aponta para o **mesmo banco** (via `10.0.0.62:5432`). Verificado: uma migration aplicada pelo MCP aparece numa leitura via `DATABASE_URL`. Serve para consultar e para aplicar migrations de schema.
- **Supabase Studio (web)**: `https://supabase.procexai.tech`.
- **Auth (GoTrue self-hosted)**: usa `SUPABASE_JWT_SECRET` próprio. Token emitido pelo cloud antigo é **rejeitado**. O `SUPABASE_URL=...supabase.co` que ainda aparece em alguns lugares é resíduo enganoso do cloud.

## ⚠️ Risco principal: dev = prod

Como há **um banco só**, `api/.env` local, o painel em produção e o MCP apontam todos para ele. Consequências práticas:

- `make dev` (uvicorn local) lê e escreve **direto em produção**.
- Testes `needs_db` rodam contra prod — use `TEST_DATABASE_URL` apontando para o self-hosted e **sempre com rollback**.
- **Nunca** rode `make migrate` cego: ele aplica os seeds `00NN_seed_*` (dados de teste) em prod. Aplique migrations seletivamente — ver [aplicar-migrations-prod.md](aplicar-migrations-prod.md).

Tratar a falta de um banco de dev separado como dívida: até existir, qualquer experimento local é em produção.

## Deploy não aplica migrations

O deploy clona a `main` (apenas **código**) no startup do serviço no Portainer. **Nenhuma migration roda no startup** — uma migration mergeada fica só no repo até ser aplicada à mão. Procedimento em [aplicar-migrations-prod.md](aplicar-migrations-prod.md).
