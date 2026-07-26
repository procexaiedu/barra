-- =============================================================================
-- 20260726031204_atendimentos_motivo_resgate_perguntado.sql
-- Flag de disciplina conversacional (padrão A2) em barravips.atendimentos: o
-- instante em que a IA PERGUNTOU o motivo da despedida ("Poxa, não gostou de
-- mim ?") no resgate do <desconto>.
--
-- Motivo: despedida educada ("obrigado, fica pra próxima") ainda não é perda, e o
-- resgate pergunta o motivo — UMA vez. Repetir a pergunta deixa de ser resgate e
-- vira cobrança, e é justamente quando o cliente volta depois de um silêncio que
-- a pergunta já deslizou pra fora da janela de 20 msgs e o LLM a recola. A
-- disciplina era só prosa no <desconto>; sem coluna não há memória durável dela.
--
-- Molde: dia_sondado_em / book_enviado_em / amiga_ofertada_em (timestamptz
-- nullable, first-write-wins). Carimbado no write-time (workers/envio.py, mesma
-- transação do INSERT em barravips.mensagens); lido por prepare_context.
--
-- O que a flag NÃO toca: o que a resposta dele destrava. Motivo = preço, com
-- contraproposta ainda disponível (degrau ou teto), continua entrando na escada —
-- quem conta isso é n_contrapropostas, não esta coluna.
--
-- A tabela atendimentos já tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration
-- só adiciona coluna, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS).
-- Schema-only — não aplicar seeds em prod.
--
-- Atendimentos ABERTOS antes desta migration nascem com a coluna NULL: a IA pode
-- perguntar o motivo mais uma vez. Falso-negativo benigno, que se auto-corrige na
-- pergunta seguinte — o backfill é opcional e é escrita em prod (CLAUDE.md §0).
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260726031204_atendimentos_motivo_resgate_perguntado.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS motivo_resgate_perguntado_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.motivo_resgate_perguntado_em IS
  'Instante em que a IA perguntou ao cliente o motivo da despedida pela 1ª vez '
  '("Poxa, não gostou de mim ?" — resgate do <desconto>), first-write-wins. '
  'Carimbado no write-time em workers/envio.py; fonte do <ja_perguntou_o_motivo> no '
  'contexto dinâmico, que segura a re-pergunta no resto da conversa, inclusive quando '
  'o cliente volta depois de sumir. A recusa de desconto ("Poxa amor não consigo") e o '
  'empurrão de fechamento ("Podemos confirmar 21h ?") NÃO são resgate e não carimbam.';
