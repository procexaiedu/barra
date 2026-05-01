-- =============================================================================
-- 0005_realtime_escaladas.sql
-- Adiciona escaladas a publicacao supabase_realtime para a Tela 07 (Dashboard).
-- =============================================================================

SET search_path TO barravips, public;

ALTER PUBLICATION supabase_realtime ADD TABLE
  barravips.escaladas;
