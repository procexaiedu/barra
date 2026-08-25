-- =============================================================================
-- 20260814013400_pendencia_de_forma_de_pagamento.sql
-- Pendencia de forma de pagamento (spec 0005, ticket 03).
--
-- O ticket 02 ja criou `vendas_registradas.forma_pagamento` NULA. Este ticket a
-- PREENCHE quando alguem diz "foi pix"/"dinheiro" no grupo — as vezes dias
-- depois do anuncio, sempre em mensagem de uma palavra. Duas adicoes, nenhuma
-- tabela nova.
--
-- POR QUE NAO EXISTE TABELA DE PENDENCIAS:
-- "Pendencia de forma de pagamento" e exatamente `forma_pagamento IS NULL`.
-- Materializa-la numa tabela criaria um segundo lugar onde a verdade mora, e
-- pendencia orfa (a venda foi paga, a linha ficou) e o unico jeito de a
-- Pendencia virar TRAVA — o dominio diz que ela bloqueia a conciliacao daquela
-- venda e nada mais. Enquanto for coluna, resolver e um UPDATE e nao ha estado
-- a reconciliar. Os outros tipos de pendencia (comprovante, cobranca, nome
-- desconhecido) seguem a mesma disciplina nos tickets 04/07/08.
--
-- 1) `pagamento_mensagem_id` — QUAL mensagem disse a forma.
-- Ligar "Sim" a venda certa e a UNICA decisao do modulo que depende de contexto
-- de conversa ("O Lucas de ontem" / "Foi pix também amiga ?" / "Sim"), e portanto
-- a unica que erra sem ninguem notar: a venda errada some da cobranca e a certa
-- fica pendente para sempre. A coluna e a prova de auditoria dessa ligacao —
-- mesmo papel que `mensagem_id` tem para o registro. RESTRICT pelo mesmo motivo
-- de la (a prova nao pode evaporar); NULA para toda venda cuja forma nunca foi
-- dita, e tambem para as que vierem a ser corrigidas fora do grupo.
--
-- 2) Indice parcial da fila de pendencia.
-- `WHERE forma_pagamento IS NULL` e a leitura mais quente do modulo daqui para
-- frente: roda a CADA mensagem que fala de pagamento (para saber quais vendas
-- disputam a resposta) e a cada rodada da rotina da manha (ticket 10). Parcial
-- porque o interesse e so pela minoria aberta — venda conciliada nunca e
-- consultada por aqui e nao precisa ocupar o indice.
--
-- Idempotente (ADD COLUMN IF NOT EXISTS + DO $$ guardado para a FK + CREATE
-- INDEX IF NOT EXISTS): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814013400_pendencia_de_forma_de_pagamento.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.vendas_registradas
--   SELECT count(*) FROM barravips.vendas_registradas WHERE forma_pagamento IS NULL;
-- =============================================================================

BEGIN;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS pagamento_mensagem_id uuid;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_constraint
     WHERE conname = 'vendas_registradas_pagamento_mensagem_fk'
       AND conrelid = 'barravips.vendas_registradas'::regclass
  ) THEN
    ALTER TABLE barravips.vendas_registradas
      ADD CONSTRAINT vendas_registradas_pagamento_mensagem_fk
      FOREIGN KEY (pagamento_mensagem_id)
      REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT;
  END IF;
END
$$;

COMMENT ON COLUMN barravips.vendas_registradas.pagamento_mensagem_id IS
  'Mensagem do grupo que disse a forma de pagamento ("Dinheiro", "Pix", "Sim" apos "foi pix?"). '
  'Auditoria da unica decisao contextual do Agente financeiro: a que venda aquela resposta foi '
  'ligada. NULA enquanto a forma nao for dita (Pendencia de forma de pagamento).';

-- Fila de Pendencia de forma de pagamento: quem disputa a proxima resposta do grupo.
CREATE INDEX IF NOT EXISTS vendas_registradas_forma_pendente_idx
  ON barravips.vendas_registradas (modelo_id, data)
  WHERE forma_pagamento IS NULL;

COMMIT;
