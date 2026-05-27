-- =============================================================================
-- 20260527154854_modelo_midia_ultimo_envio.sql
-- M5e: adiciona barravips.modelo_midia.ultimo_envio_em (rotacao menos-recente
-- em enviar_midia, doc 04 §3.3 / 09 §4.8).
--
-- A tool enviar_midia escolhe a foto da tag ordenando por (ultimo_envio_em
-- NULLS FIRST, created_at) e marca now() no registro escolhido, evitando
-- repetir a mesma midia turno apos turno. Antes deste roteiro a coluna era
-- `descricao`; trocada porque a IA nao escolhe mais por descricao (so por tag).
--
-- Idempotente (ADD COLUMN IF NOT EXISTS); herda RLS da tabela (modelo_midia ja
-- tem ENABLE ROW LEVEL SECURITY em 0001).
--
-- Aplicacao: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260527154854_modelo_midia_ultimo_envio.sql
-- =============================================================================

ALTER TABLE barravips.modelo_midia
  ADD COLUMN IF NOT EXISTS ultimo_envio_em timestamptz;

COMMENT ON COLUMN barravips.modelo_midia.ultimo_envio_em IS
  'Rotacao menos-recente em enviar_midia (04 §3.3): a tool escolhe ORDER BY ultimo_envio_em NULLS FIRST, created_at e marca now() na escolha. NULL = nunca enviada.';
