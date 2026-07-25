-- =============================================================================
-- 20260725030000_atendimentos_endereco_enviado.sql
-- Quarta flag de disciplina conversacional (padrão A2) em barravips.atendimentos:
-- o instante em que a IA passou o ENDEREÇO do ponto de encontro ao cliente.
--
-- Motivo (atendimento #41, 2026-07-24 10:03): a IA disse "Vem aqui então / Já
-- sabe onde é" — e o endereço só saiu 7 minutos DEPOIS, às 10:10. O belief dizia
-- <ainda_falta><nada>tudo desta etapa já está combinado</nada>, e "passei o
-- endereço" não era um fato rastreado em lugar nenhum: a janela de 20 msgs é
-- curta demais para servir de memória, e sem coluna não há memória durável.
--
-- Molde: dia_sondado_em / book_enviado_em da 20260723120000 (timestamptz
-- nullable, first-write-wins). Carimbado no write-time (workers/envio.py, mesma
-- transação do INSERT em barravips.mensagens); lido por prepare_context.
--
-- A tabela atendimentos já tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration
-- só adiciona coluna, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS).
-- Schema-only — não aplicar seeds em prod.
--
-- Atendimentos ABERTOS antes desta migration nascem com a coluna NULL: o belief
-- vai dizer "ainda não passou o endereço" mesmo tendo passado, e a IA repete o
-- endereço uma vez. Falso-negativo benigno, que se auto-corrige no próximo envio
-- — o backfill é opcional e é escrita em prod (CLAUDE.md §0).
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260725030000_atendimentos_endereco_enviado.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS endereco_enviado_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.endereco_enviado_em IS
  'Instante em que a IA passou o endereço do ponto de encontro ao cliente pela 1ª vez '
  '(first-write-wins). Carimbado no write-time em workers/envio.py; fonte do status '
  'do <local_de_encontro> no contexto dinâmico, que impede a IA de falar como se o '
  'cliente já soubesse onde é (atendimento #41, 2026-07-24).';
