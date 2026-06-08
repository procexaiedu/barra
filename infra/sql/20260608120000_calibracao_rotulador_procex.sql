-- =============================================================================
-- 3o rotulador de calibracao: 'procex' (Loop B / EVAL-10).
--
-- Estende o CHECK de calibracao_rotulos.rotulador p/ aceitar 'procex' (revisor
-- independente, alem de fernando + socia). 'procex' tem bucket proprio (UNIQUE
-- (fala_pk, rotulador) ja garante a independencia) e NUNCA sobrescreve os outros.
-- O golden.jsonl exportado segue sendo o acordo fernando×socia: as marcas de
-- 'procex' ficam de fora (ver barra/calibracao/export.py:separar_rotulos), entao
-- calibrar.py / merge_rotulos.py nao mudam.
--
-- Idempotente (DROP IF EXISTS + ADD pelo nome confirmado em prod). Aplicar
-- manualmente em prod self-hosted via psycopg (schema-only).
-- =============================================================================

BEGIN;

ALTER TABLE barravips.calibracao_rotulos
  DROP CONSTRAINT IF EXISTS calibracao_rotulos_rotulador_check;

ALTER TABLE barravips.calibracao_rotulos
  ADD CONSTRAINT calibracao_rotulos_rotulador_check
  CHECK (rotulador IN ('fernando', 'socia', 'procex'));

COMMIT;
