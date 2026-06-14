-- Marca a ORIGEM de uma conversa: 'prod' (trafego real do WhatsApp) vs 'e2e' (corrida de
-- avaliacao do harness evals/e2e — cliente = Claude Code, agente real). O painel
-- /observabilidade esconde e2e por padrao (filtro `origem`), para nao misturar as conversas
-- sinteticas de teste com as reais que o Fernando avalia no dia a dia. e2e nunca chega a
-- 'Fechado' (a conversa so conduz ate Aguardando_confirmacao), entao nao entra no financeiro.
--
-- Coluna nullable-com-default: backfill implicito 'prod' nas conversas existentes. Idempotente
-- (ADD COLUMN IF NOT EXISTS + DROP/ADD da constraint). So schema — sem seed.

BEGIN;

ALTER TABLE barravips.conversas
  ADD COLUMN IF NOT EXISTS origem text NOT NULL DEFAULT 'prod';

-- CHECK idempotente: DROP IF EXISTS antes do ADD (padrao do infra/sql/CLAUDE.md).
ALTER TABLE barravips.conversas DROP CONSTRAINT IF EXISTS conversas_origem_check;
ALTER TABLE barravips.conversas
  ADD CONSTRAINT conversas_origem_check CHECK (origem IN ('prod', 'e2e'));

COMMENT ON COLUMN barravips.conversas.origem IS
  'prod=trafego real; e2e=corrida de avaliacao do harness (evals/e2e). Painel /observabilidade esconde e2e por padrao.';

COMMIT;
