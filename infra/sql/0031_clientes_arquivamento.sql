-- =============================================================================
-- 0031_clientes_arquivamento.sql
-- Soft delete administrativo em clientes. Não cascateia em conversas nem em
-- atendimentos: a coluna serve para esconder o cliente das listagens default
-- do CRM sem perder histórico ou impactar IA/agenda.
-- RLS já está habilitado para barravips.clientes desde 0001 — nenhuma policy
-- nova é necessária.
-- =============================================================================

ALTER TABLE barravips.clientes
  ADD COLUMN IF NOT EXISTS arquivado_em timestamptz;

CREATE INDEX IF NOT EXISTS clientes_arquivados_idx
  ON barravips.clientes (arquivado_em)
  WHERE arquivado_em IS NOT NULL;

COMMENT ON COLUMN barravips.clientes.arquivado_em IS
  'Soft delete administrativo. NULL = ativo. Não cascadeia em conversas/atendimentos.';
