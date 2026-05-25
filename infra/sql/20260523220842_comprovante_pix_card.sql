-- =============================================================================
-- 20260523220842_comprovante_pix_card.sql
-- Adiciona comprovantes_pix.card_message_id para idempotencia do card no grupo de
-- Coordenacao por modelo (doc 06 §2.5 / §0 item 9, decisao grilling 2026-05-23).
--
-- O consumer do stream evolution:card so envia o card de Pix se card_message_id IS NULL
-- e grava o id retornado pela Evolution apos enviar. Ancora a idempotencia no dado
-- duravel (Redis Streams entregam at-least-once) e da o mesmo papel que
-- escaladas.card_message_id cumpre para os handoffs.
--
-- (O "0014" citado no doc colide com 0014_seed_eduardo.sql; migrations aplicadas sao
--  imutaveis, por isso esta usa nome timestamp — ver infra/sql/CLAUDE.md.)
--
-- Aplicacao: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260523220842_comprovante_pix_card.sql
-- =============================================================================

ALTER TABLE barravips.comprovantes_pix
  ADD COLUMN IF NOT EXISTS card_message_id text;

COMMENT ON COLUMN barravips.comprovantes_pix.card_message_id IS
  'id da mensagem do card no grupo de Coordenacao. NULL = card ainda nao enviado; '
  'preenchido apos envio para idempotencia (doc 06 §2.5).';
