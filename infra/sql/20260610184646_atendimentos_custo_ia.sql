-- Custo de IA acumulado por atendimento (OBS go-live): o coordenador soma o custo estimado do
-- CHAT (Sonnet, tarifas em api/src/barra/agente/_custo.py) ao fim de cada turno
-- (workers/coordenador.py:acumular_custo_atendimento).
--
-- ESCOPO: so chat. STT (Whisper) e vision (Pix) sao marginais e o STT roda antes de o
-- atendimento existir -- seguem apenas no Prometheus (agente_custo_{stt,vision}_brl).
-- E uma ESTIMATIVA por tarifa publica x settings.usd_brl_cotacao, nao fatura.
-- Sem backfill: atendimentos antigos ficam em 0 (o custo historico vive no Prometheus).
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS custo_ia_brl numeric(12,6) NOT NULL DEFAULT 0;

COMMENT ON COLUMN barravips.atendimentos.custo_ia_brl IS
  'Custo estimado de IA (chat Sonnet, BRL) acumulado por turno pelo coordenador. Estimativa, nao fatura; STT/vision ficam no Prometheus.';
