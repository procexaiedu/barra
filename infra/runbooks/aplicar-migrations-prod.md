# Aplicar migrations de schema no prod

Procedimento para aplicar migrations de `infra/sql/` no banco de **produção self-hosted** sem disparar os seeds descartáveis.

## Por que este runbook existe

Não há migration framework (ADR-0002): migrations são `.sql` puro, aplicadas à mão. Em prod **isso não acontece automaticamente** — o deploy clona a `main` (código), mas nenhuma migration roda no startup. Resultado: uma migration mergeada na `main` fica só no repo até alguém aplicá-la aqui. Foi assim que `sinais_qualificacao` ficou com default `{}` em prod mesmo com a migration commitada (2026-05-25).

**Nunca rode `make migrate` apontando para o prod.** Ele itera *todos* os `*.sql`, incluindo os seeds `00NN_seed_*` (dados de teste da interface) e os `*_seed_*` timestamp — aplicá-los em prod injeta lixo. E **não há um banco de dev separado** para apontá-lo (ver "Banco alvo"): hoje só existe o prod, então `make migrate` não tem alvo seguro. Aplique seletivamente (passo 2).

## Banco alvo

**Existe um banco só.** O antigo Supabase cloud (`zinrqzsxvpqfoogohrwg.supabase.co`) foi **abandonado** em 2026-05-25 — não há mais "dev" e "prod" separados. O `DATABASE_URL` do `api/.env`, o painel em produção e o MCP postgres apontam **todos para o mesmo Postgres**:

- Endereço do app/`.env`: `db.procexai.tech:5433` (proxy/pooler externo).
- Servidor real por trás dele: `10.0.0.62:5432` (Supabase self-hosted, Docker/Portainer).
- O **MCP postgres alcança esse mesmo banco** (verificado 2026-05-25: migration aplicada via MCP aparece numa leitura via `DATABASE_URL`).

Implicação: rodar `make dev`, testes `needs_db` ou aplicar SQL localmente **mexe direto em produção**. Confirme `current_database()` / `inet_server_addr()` antes de aplicar qualquer coisa.

## 1. Descobrir o que falta aplicar

Não há tabela de tracking. O estado real é a fonte de verdade: introspecção do banco contra os artefatos que cada migration cria (coluna, tabela, tipo, default, policy).

Para uma coluna:
```sql
SELECT EXISTS (SELECT 1 FROM information_schema.columns
  WHERE table_schema='barravips' AND table_name='<tabela>' AND column_name='<coluna>');
```
Para uma tabela: `SELECT to_regclass('barravips.<tabela>') IS NOT NULL;`
Para um valor de enum:
```sql
SELECT EXISTS (SELECT 1 FROM pg_enum e
  JOIN pg_type t ON t.oid=e.enumtypid JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='barravips' AND t.typname='<enum>' AND e.enumlabel='<valor>');
```
Para uma policy: `SELECT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='barravips' AND tablename='<tabela>' AND policyname='<policy>');`

Abra cada migration nova desde a última aplicação, identifique o artefato distintivo e cheque um a um. `FALSE` = pendente.

## 2. Aplicar

Dois caminhos equivalentes (ambos batem no mesmo banco). Aplique **só as de schema pendentes**, nunca os `*seed*`.

**A) Script local (`scripts/aplicar_sql.py`)** — aplica **um** arquivo por vez via psycopg, lendo `DATABASE_URL` do `api/.env` (não precisa de `psql` local):

```bash
uv run python scripts/aplicar_sql.py infra/sql/<NNNN_ou_timestamp>_<nome>.sql
```

**B) Via MCP postgres** — a conexão default do MCP alcança o mesmo banco. Cole o corpo da migration em `pg_execute_sql` com `transactional: true`; as checagens do passo 1 rodam em `pg_execute_query`. Foi o caminho usado em 2026-05-25 para a `20260525220427_perfil_fisico`.

Reaplicar uma migration já aplicada é seguro **se** ela for idempotente (regra do `infra/sql/CLAUDE.md`) — mas note que nem todas são (ex.: `0028` tem `ADD CONSTRAINT` sem guarda e quebra na 2ª execução). Por isso aplique seletivamente o que o passo 1 apontou como pendente, em vez de reaplicar em lote.

## 3. Verificar

Rode de novo as checagens do passo 1: o artefato agora deve existir. Para defaults/backfill, confira também uma amostra de linhas.

## Regras que continuam valendo

- Migration já aplicada é **imutável**: não renumere nem edite. Corrija com uma migration nova (`infra/sql/CLAUDE.md`).
- Toda migration nova deve ser idempotente (`IF NOT EXISTS` / `DROP ... IF EXISTS` / guarda `DO $$`).
- Migrations novas usam nome timestamp UTC; `NNNN` sequencial é legacy.
