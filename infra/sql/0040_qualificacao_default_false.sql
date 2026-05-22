-- =============================================================================
-- 0040_qualificacao_default_false.sql
-- task #3c34fe19: atendimentos.sinais_qualificacao nasce com os 4 sinais
-- filtraveis em `false` em vez de `{}`.
--
-- Motivo: o default '{}'::jsonb deixava atendimentos novos invisiveis aos
-- filtros que usam jsonb_typeof(...) = 'boolean'
-- (api/src/barra/dominio/atendimentos/routes.py:99-116) e renderizava o
-- checklist de qualificacao vazio no frontend. Decisao da reuniao: nascer com
-- os 4 sinais que entram em filtro (envia_pix, aceita_valor, informa_local,
-- informa_horario) em `false`. `responde_objetivamente` fica de fora.
--
-- Idempotente: SET DEFAULT e re-aplicavel; o backfill usa
-- `<default> || sinais_qualificacao` para que as chaves JA existentes (incl.
-- valores `true` setados pela IA) PREVALECAM sobre os defaults `false`.
-- RLS de barravips.atendimentos ja habilitado desde 0001 — nada a fazer.
-- =============================================================================

BEGIN;

ALTER TABLE barravips.atendimentos
  ALTER COLUMN sinais_qualificacao
  SET DEFAULT '{"envia_pix": false, "aceita_valor": false, "informa_local": false, "informa_horario": false}'::jsonb;

-- Backfill: mescla os 4 defaults `false` SOMENTE nas chaves ausentes.
-- A ordem `default || existente` faz o operando da direita (o valor ja gravado)
-- vencer em caso de colisao — preserva qualquer sinal ja marcado `true`.
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

COMMENT ON COLUMN barravips.atendimentos.sinais_qualificacao IS
  'jsonb com os 4 sinais filtraveis canonicos (default false): '
  '{envia_pix, aceita_valor, informa_local, informa_horario} — doc 04 §4.4. '
  'responde_objetivamente fica reservado (fora dos filtros, decisao da reuniao).';

COMMIT;
