-- =============================================================================
-- 20260726020556_atendimentos_amiga_ofertada.sql
-- Flag de disciplina conversacional (padrão A2) em barravips.atendimentos: o
-- instante em que a IA CONVIDOU o cliente para conhecer a amiga ("Tenho uma
-- amiga aqui no mesmo hotel, no apartamento dela rs, quer conhecer as duas ?").
--
-- Motivo: a disciplina ("você PODE oferecer uma vez, como quem convida") era só
-- prosa no <menage> do regras.md.j2, e o convite é pós-venda — acontece no FIM da
-- negociação, que é justamente quando ele desliza para fora da janela de 20 msgs
-- e o LLM reoferece. Sem coluna não há memória durável do convite.
--
-- Molde: dia_sondado_em / book_enviado_em da 20260723120000 (timestamptz
-- nullable, first-write-wins). Carimbado no write-time (workers/envio.py, mesma
-- transação do INSERT em barravips.mensagens); lido por prepare_context.
--
-- A tabela atendimentos já tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration
-- só adiciona coluna, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS).
-- Schema-only — não aplicar seeds em prod.
--
-- Atendimentos ABERTOS antes desta migration nascem com a coluna NULL: a IA pode
-- reoferecer a amiga uma vez. Falso-negativo benigno, que se auto-corrige no
-- próximo convite — o backfill é opcional e é escrita em prod (CLAUDE.md §0).
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260726020556_atendimentos_amiga_ofertada.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS amiga_ofertada_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.amiga_ofertada_em IS
  'Instante em que a IA convidou o cliente para conhecer a amiga pela 1ª vez '
  '(first-write-wins). Carimbado no write-time em workers/envio.py; fonte do '
  '<ja_ofereceu_a_amiga> no contexto dinâmico, que sustenta o "uma vez" do '
  '<menage> depois de o convite sair da janela de 20 msgs. A resposta de escalada '
  '("Deixa eu ver com ela e já te retorno amor"), quando é o CLIENTE quem pede a '
  'dupla, NÃO é oferta e não carimba.';
