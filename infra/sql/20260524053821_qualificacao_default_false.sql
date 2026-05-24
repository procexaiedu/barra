-- 20260524053821_qualificacao_default_false.sql
-- Atendimentos novos nasciam com sinais_qualificacao = '{}'::jsonb, o que os
-- deixava invisíveis aos filtros que usam jsonb_typeof(...) = 'boolean'
-- (dominio/atendimentos/routes.py) e renderizava o checklist de qualificação
-- vazio no painel. Decisão: toda linha nasce com os 4 sinais filtráveis em
-- false e os registros existentes recebem backfill.
--
-- responde_objetivamente fica de fora do default (não entra em filtro). O
-- comentário do schema (0001 §10) listava 5 sinais; aqui ele passa a refletir
-- os 4 oficiais + reservado.

-- 1. Novo default: os 4 sinais filtráveis em false.
ALTER TABLE barravips.atendimentos
  ALTER COLUMN sinais_qualificacao
  SET DEFAULT '{"envia_pix": false, "aceita_valor": false, "informa_local": false, "informa_horario": false}'::jsonb;

-- 2. Backfill. Merge `default || existente`: chaves já presentes (true/false
--    preenchidos pela IA ou seeds) prevalecem; só as ausentes ganham false.
--    O WHERE restringe a linhas que não têm as 4 chaves, tornando a migration
--    um no-op na 2ª execução (idempotente).
UPDATE barravips.atendimentos
SET sinais_qualificacao =
  '{"envia_pix": false, "aceita_valor": false, "informa_local": false, "informa_horario": false}'::jsonb
  || sinais_qualificacao
WHERE NOT (
      sinais_qualificacao ? 'envia_pix'
  AND sinais_qualificacao ? 'aceita_valor'
  AND sinais_qualificacao ? 'informa_local'
  AND sinais_qualificacao ? 'informa_horario'
);

-- 3. Comentário canônico atualizado.
COMMENT ON COLUMN barravips.atendimentos.sinais_qualificacao IS
  'jsonb com os 4 sinais filtráveis {envia_pix, aceita_valor, informa_local, informa_horario}, nascem em false (default). responde_objetivamente é reservado (não filtrável) — doc 04 §4.4.';
