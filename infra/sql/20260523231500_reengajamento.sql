-- Reengajamento proativo (decisão grilling 2026-05-23; docs/agente/07 §4, CONTEXT.md "Reengajamento").
-- Marca quando a IA já reabriu proativamente um atendimento — garante 1 toque por atendimento
-- (o cron varrer_timeouts filtra reengajado_em IS NULL). Não reseta o relógio do timeout de 24h,
-- que conta da última mensagem do cliente.
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS reengajado_em timestamptz;
