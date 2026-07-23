-- =============================================================================
-- 20260723120000_atendimentos_flags_disciplina.sql
-- Materializa as 3 flags de disciplina conversacional (padrão A2) em
-- barravips.atendimentos, para que prepare_context não releia TODAS as falas da
-- IA do atendimento (SELECT ... LIMIT 500) e reaplique regex a cada turno.
--
-- As flags passam a ser carimbadas no write-time (workers/envio.py, mesma
-- transação do INSERT em barravips.mensagens), espelhando marcar_cotacao_enviada:
--   - n_contrapropostas: contador de contrapropostas de desconto (ADR-0031, até 2).
--     Molde: disclosure_tentativas (smallint NOT NULL DEFAULT 0).
--   - dia_sondado_em: 1º instante em que a IA sondou o dia ("seria hoje?").
--   - book_enviado_em: 1º instante em que a IA enviou mídia (book) na negociação.
--     Molde dos dois: cotacao_enviada_em (timestamptz nullable, first-write-wins).
--
-- A tabela atendimentos já tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration
-- só adiciona colunas, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS):
-- roda 2x sem erro. Schema-only — não aplicar seeds em prod.
--
-- (Nome timestamp porque o NNNN sequencial já foi além de 0039 e migrations
--  aplicadas são imutáveis -- ver infra/sql/CLAUDE.md.)
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260723120000_atendimentos_flags_disciplina.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS n_contrapropostas smallint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS dia_sondado_em timestamptz,
  ADD COLUMN IF NOT EXISTS book_enviado_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.n_contrapropostas IS
  'Contador de contrapropostas de desconto que a IA já fez (ADR-0031, até 2). '
  'Carimbado no write-time em workers/envio.py; substitui o scan das falas da IA '
  'em prepare_context. Idempotente no retry (RETURNING do INSERT ON CONFLICT).';
COMMENT ON COLUMN barravips.atendimentos.dia_sondado_em IS
  'Instante em que a IA sondou o dia ("seria hoje?") pela 1ª vez (first-write-wins). '
  'Fonte durável do <ja_sondou_o_dia>; OR com o window-scan em prepare_context.';
COMMENT ON COLUMN barravips.atendimentos.book_enviado_em IS
  'Instante em que a IA enviou mídia (book) na negociação pela 1ª vez (first-write-wins). '
  'Fonte do <ja_enviou_book>; substitui o scan de tipo=imagem em prepare_context.';
