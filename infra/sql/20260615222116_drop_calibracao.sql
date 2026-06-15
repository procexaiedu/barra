-- =============================================================================
-- Remove a feature "Calibrar judge" (rotulagem do golden no painel, Loop B /
-- EVAL-10): tabelas calibracao_rotulos, calibracao_falas e calibracao_rodadas.
--
-- O codigo da feita (barra/calibracao/* + interface/.../calibracao/*) foi
-- removido; estas tabelas ficam orfas. DROP CASCADE leva junto as FKs, indices,
-- policies RLS e o trigger set_updated_at_calibracao_rotulos.
--
-- A funcao barravips.set_updated_at() e compartilhada (outras tabelas usam) ->
-- NAO dropar. Idempotente (IF EXISTS). Aplicar manualmente em prod self-hosted
-- via psycopg (schema-only).
-- =============================================================================

BEGIN;

DROP TABLE IF EXISTS barravips.calibracao_rotulos CASCADE;
DROP TABLE IF EXISTS barravips.calibracao_falas CASCADE;
DROP TABLE IF EXISTS barravips.calibracao_rodadas CASCADE;

COMMIT;
