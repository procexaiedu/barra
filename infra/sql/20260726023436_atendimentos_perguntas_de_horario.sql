-- =============================================================================
-- 20260726023436_atendimentos_perguntas_de_horario.sql
-- Flag de disciplina conversacional (padrão A2) em barravips.atendimentos: quantas
-- vezes a IA PERGUNTOU o horário sem propor nenhum ("Seria que horas ?", "Qual
-- horário amor ?").
--
-- Motivo: quando o cliente desconversa (emoji, elogio, "que bom rs"), a IA
-- reperguntava "que horas ?" turno após turno — a mesma pergunta em loop é o que
-- mais afasta nessa fase. A disciplina era prosa no <conducao_da_venda> e dependia
-- de o LLM contar as próprias perguntas dentro da janela de mensagens; contador é
-- exatamente o que ele não faz bem.
--
-- Molde: n_contrapropostas da 20260723120000 (smallint NOT NULL DEFAULT 0). É
-- CONTADOR, não timestamp, porque a conduta tem dois degraus: na 1ª ela propõe um
-- horário concreto em vez de reperguntar; da 2ª em diante não pergunta mais.
-- Carimbado no write-time (workers/envio.py, mesma transação do INSERT em
-- barravips.mensagens, só quando a bolha foi de fato inserida — o RETURNING do
-- ON CONFLICT DO NOTHING é o que impede o retry de dobrar a contagem); lido por
-- prepare_context.
--
-- A tabela atendimentos já tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration
-- só adiciona coluna, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS).
-- Schema-only — não aplicar seeds em prod.
--
-- Atendimentos ABERTOS antes desta migration começam do zero: a IA pode perguntar
-- o horário mais uma vez. Falso-negativo benigno, que se auto-corrige na pergunta
-- seguinte — o backfill é opcional e é escrita em prod (CLAUDE.md §0).
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260726023436_atendimentos_perguntas_de_horario.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS n_perguntas_de_horario smallint NOT NULL DEFAULT 0;

COMMENT ON COLUMN barravips.atendimentos.n_perguntas_de_horario IS
  'Quantas vezes a IA perguntou o horário SEM propor nenhum ("Seria que horas ?"). '
  'Carimbado no write-time em workers/envio.py, só na 1ª inserção da bolha; fonte do '
  '<ja_perguntou_o_horario> no contexto dinâmico, que tem dois degraus (n=1: proponha '
  'você um horário concreto; n>=2: não pergunte mais, proponha e siga). A bolha que já '
  'carrega hora ("Consigo às 22h, fecha ?") é proposta, não pergunta, e não conta.';
