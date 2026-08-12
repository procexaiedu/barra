-- =============================================================================
-- 20260812020000_julgamentos_turno_vazou_dado_duro.sql
-- Eixo REAL de vazamento de dado duro no judge PÓS-ENVIO (produção assistida).
--
-- Até aqui o vazamento de dado que só o sistema anexa — número da UNIDADE
-- (apartamento/quarto), chave Pix/dado bancário e telefone — vivia SÓ no
-- prefixo `[dado]` do `comentario` (prompt-only, grepável mas não contável) e
-- afundava o eixo `conduta` para 1. Não havia coluna: o sinal de vazamento não
-- tinha série própria, misturava-se ao ruído de conduta e não dava para alertar.
--
-- O judge (workers/judge_pos_envio.py) agora produz o booleano `vazou_dado_duro`
-- no schema estruturado; esta coluna o torna durável ao lado dos outros eixos,
-- para o rollback_watch/digest e a série Prometheus `agente_judge_vazamento_dado`.
--
-- Aditiva e idempotente (ADD COLUMN IF NOT EXISTS, NOT NULL DEFAULT false — as
-- linhas antigas viram `false`, o mesmo que "não medido = não vazou"). Não muda
-- os consumidores existentes (todos selecionam colunas por nome). Schema-only.
--
-- Aplicação em prod: manual via scripts/aplicar_sql.py (nunca make migrate).
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260812020000_julgamentos_turno_vazou_dado_duro.sql
-- =============================================================================

ALTER TABLE barravips.julgamentos_turno
  ADD COLUMN IF NOT EXISTS vazou_dado_duro boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN barravips.julgamentos_turno.vazou_dado_duro IS
  'true = o turno JÁ enviado escreveu na fala um dado que só o sistema anexa '
  '(número da unidade/apartamento, chave Pix/dado bancário ou telefone). Eixo de '
  'vazamento separado de rastro_llm (não entrega a IA) e do prefixo [dado] do '
  'comentario. Alimenta a série Prometheus agente_judge_vazamento_dado_total.';
