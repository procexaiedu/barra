-- Externo com pickup (ADR 0020): cliente busca a modelo de carro -- e externo, mas SEM Pix de
-- deslocamento (nao ha Uber dela para antecipar). `cliente_busca` sinaliza o subcaso dentro de
-- tipo_atendimento='externo'; a extracao promove Qualificado -> Aguardando_confirmacao (bloqueio
-- previo, pix_status segue nao_solicitado) e o cron confirmar_em_execucao pausa a IA no horario
-- (escalada tipo 'cliente_busca' hospeda o card "Cliente vem te buscar").
--
-- Sem backfill: atendimentos antigos ficam false (o subcaso nao existia antes do ADR 0020).
-- APLICAR ANTES do redeploy do worker: o cron e a extracao referenciam a coluna e o valor novo
-- do enum.
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS cliente_busca boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN barravips.atendimentos.cliente_busca IS
  'Subcaso do externo (ADR 0020): cliente busca a modelo de carro. Sem Pix de deslocamento; promocao via extracao e pausa pelo cron no horario do bloqueio.';

-- ADD VALUE e idempotente via IF NOT EXISTS; fora de bloco DO/transacao explicita (PG >= 12
-- aceita em transacao, mas o valor novo nao pode ser USADO na mesma transacao -- nenhum uso
-- neste arquivo).
ALTER TYPE barravips.tipo_escalada_enum ADD VALUE IF NOT EXISTS 'cliente_busca';
