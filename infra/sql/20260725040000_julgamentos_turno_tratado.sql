-- =============================================================================
-- 20260725040000_julgamentos_turno_tratado.sql
-- Marca de TRIAGEM nos julgamentos pós-envio, para o gatilho `nao_contidos` do
-- rollback_watch medir risco ABERTO em vez de acúmulo histórico.
--
-- Motivo: o gatilho conta linhas com `rastro_llm` na janela de 7 dias. Um
-- incidente já diagnosticado e corrigido continua na janela até envelhecer,
-- então o alerta segue disparando por 7 dias depois do fix — e um alerta que
-- não some quando o problema some deixa de ser lido (2026-07-25).
--
-- `tratado_em` NÃO é "o judge errou": é "este incidente foi diagnosticado e o
-- fix está em produção". Para julgamento errado (o judge marcando rastro_llm
-- num implicância de voz), a marca também serve, e a `tratado_nota` diz qual
-- dos dois casos é — o histórico fica intacto para auditoria, só sai da conta.
--
-- Como marcar (escrita em prod, CLAUDE.md §0 — uma linha por incidente tratado):
--   UPDATE barravips.julgamentos_turno
--      SET tratado_em = now(), tratado_nota = 'eco de região — fix f1455bd'
--    WHERE turno_id = '<turno_id>';
--
-- Idempotente (ADD COLUMN IF NOT EXISTS). Schema-only — não aplicar seeds em prod.
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260725040000_julgamentos_turno_tratado.sql
-- =============================================================================

ALTER TABLE barravips.julgamentos_turno
  ADD COLUMN IF NOT EXISTS tratado_em timestamptz,
  ADD COLUMN IF NOT EXISTS tratado_nota text;

COMMENT ON COLUMN barravips.julgamentos_turno.tratado_em IS
  'Instante em que o incidente foi triado: diagnosticado e com o fix em produção, '
  'OU julgamento reconhecido como falso positivo do judge. Linha marcada sai da '
  'contagem do gatilho nao_contidos (workers/rollback_watch) sem sumir do histórico.';
COMMENT ON COLUMN barravips.julgamentos_turno.tratado_nota IS
  'Por que este julgamento foi tratado — o commit/fix que o resolveu, ou a razão de '
  'ser falso positivo. Obrigatória por convenção: marca sem justificativa é o mesmo '
  'que apagar o sinal.';
