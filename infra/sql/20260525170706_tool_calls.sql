-- =============================================================================
-- 20260525170706_tool_calls.sql
-- Cria barravips.tool_calls — idempotencia das tools de ESCRITA do agente
-- (doc 04-tools.md §5 / 02-estado-fluxo.md §8.2, M3a do roteiro 09 §4.8).
--
-- Cada chamada de tool de escrita grava aqui com a chave (turno_id, tool_name,
-- call_idx). Um retry do ARQ / replay do turno re-executa a tool com a MESMA
-- chave: o ON CONFLICT deduplica e o helper _executar_idempotente devolve o
-- `resultado` anterior sem repetir o efeito colateral.
--
-- (O "0012_tool_calls.sql" citado no doc 04 §5 colide com 0012_bucket_rename.sql;
--  migrations aplicadas sao imutaveis, por isso esta usa nome timestamp — ver
--  infra/sql/CLAUDE.md e roteiro 09 §4.8.)
--
-- Aplicacao: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260525170706_tool_calls.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS barravips.tool_calls (
  turno_id    uuid        NOT NULL,
  tool_name   text        NOT NULL,
  call_idx    smallint    NOT NULL,   -- enviar_midia pode ser chamada varias vezes por turno
  payload     jsonb       NOT NULL,
  resultado   jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (turno_id, tool_name, call_idx)
);

CREATE INDEX IF NOT EXISTS tool_calls_turno_idx ON barravips.tool_calls (turno_id);

-- TTL via cron diario (ARQ, vive no coordenador — doc 07): DELETE WHERE created_at < now() - interval '7 days'

ALTER TABLE barravips.tool_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.tool_calls FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.tool_calls;
CREATE POLICY fernando_full_access ON barravips.tool_calls
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.tool_calls TO authenticated;
GRANT ALL PRIVILEGES ON barravips.tool_calls TO service_role;
