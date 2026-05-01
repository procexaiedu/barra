-- =============================================================================
-- 0003_realtime_crm.sql
-- Adiciona conversas e clientes a publicacao supabase_realtime para a Tela 04 (CRM).
-- =============================================================================

SET search_path TO barravips, public;

ALTER PUBLICATION supabase_realtime ADD TABLE
  barravips.conversas,
  barravips.clientes;
