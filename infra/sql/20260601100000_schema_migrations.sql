-- =============================================================================
-- Tabela de tracking de migrations aplicadas (DEPLOY-05/06).
--
-- Até aqui não havia registro do que já rodou no banco: o estado real era a
-- única fonte de verdade (introspecção do schema, ver runbook). Esta tabela
-- passa a registrar cada arquivo de `infra/sql/` aplicado via
-- `scripts/aplicar_sql.py`, habilitando o drift-check (repo × banco).
--
-- `filename` é o nome do arquivo (sem caminho), ex.: `20260529220000_fetiches.sql`
-- — é a chave natural e estável (migrations aplicadas são imutáveis: nunca
-- renomeadas nem reescritas, ver infra/sql/CLAUDE.md).
--
-- Tabela INTERNA de infraestrutura: sem RLS porque não é exposta ao painel nem
-- ao PostgREST — só o operador/script de deploy escreve nela via service_role.
--
-- Idempotente. Aplicar manualmente em prod self-hosted via psycopg (nunca
-- `make migrate` no prod self-hosted — aplicaria seeds).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS barravips.schema_migrations (
  filename    text PRIMARY KEY,
  aplicada_em timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.schema_migrations IS
  'interna: sem RLS porque é tracking de deploy (qual .sql de infra/sql/ já rodou), escrita só pelo operador/service_role, nunca exposta ao painel/PostgREST. DEPLOY-05/06.';

COMMIT;
