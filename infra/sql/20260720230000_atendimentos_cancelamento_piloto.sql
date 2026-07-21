-- Cancelamento automatico de seguranca do piloto de teste (ADR-0033, spec 0004).
--
-- aguardando_confirmacao_em: ancora do cron (first-write-wins, mesmo padrao de
-- cotacao_enviada_em/ADR-0022) -- carimba o instante em que o Atendimento ENTROU em
-- Aguardando_confirmacao (horario combinado cravado). Distinto de bloqueios.inicio (o horario do
-- encontro em si, que pode estar minutos a frente por causa do agenda_buffer_min): o timer de
-- 10min do cron conta da ENTRADA no estado, nao do horario marcado.
--
-- piloto_cancelado_em: marcador de idempotencia do cron cancelar_piloto_teste (mesmo padrao de
-- reengajado_em) -- evita reprocessar o mesmo atendimento entre varreduras.
--
-- Schema-only -- nao aplicar seeds em prod.
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS aguardando_confirmacao_em timestamptz;

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS piloto_cancelado_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.aguardando_confirmacao_em IS
  'Instante em que o Atendimento entrou em Aguardando_confirmacao (first-write-wins). Ancora do cron cancelar_piloto_teste (ADR-0033).';

COMMENT ON COLUMN barravips.atendimentos.piloto_cancelado_em IS
  'Marcador de idempotencia do cron cancelar_piloto_teste (ADR-0033) -- nao reprocessa entre varreduras.';
