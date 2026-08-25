-- =============================================================================
-- 20260820120500_forma_de_pagamento_debito_credito_link.sql
-- "Cartao" deixa de existir como forma: vira **debito, credito e link**
-- (ADR-0046 §4, `docs/dominio/fichas-do-telefonista.md`). O vocabulario completo
-- da Venda registrada passa a ser:
--
--     dinheiro | pix | debito | credito | link
--
-- POR QUE: o card do telefonista tem `💳 *PAGAMENTO* ( ) Dinheiro ( ) Pix
-- ( ) Debito ( ) Credito ( ) Link` — a reuniao de 20/08 desmembrou "cartao"
-- porque as tres coisas nao se comportam igual (link e um Pix por outro trilho,
-- credito tem taxa e prazo, debito cai na hora) e porque a maquininha pode estar
-- no celular da modelo (ADR-0047 §6) — o que muda o BOLSO, nao a forma.
--
-- POR QUE **NAO** MEXO EM `barravips.forma_pagamento_enum`:
-- aquele enum ('pix','dinheiro','outro','cartao') e do Modulo Financeiro do
-- PAINEL — `atendimentos.forma_pagamento`, `financeiro_despesas`,
-- `financeiro_repasses_pagos`, `financeiro_comissoes_pagas` — e o combobox do
-- painel oferece "Cartao" hoje. Adicionar valores la (a) mudaria a tela de
-- Atendimentos, que ninguem pediu, e (b) `ALTER TYPE ... ADD VALUE` tem regra
-- propria de transacao. O vocabulario da ficha e o do grupo, nao o do painel.
--
-- POR QUE TEXT + CHECK E NAO UM ENUM NOVO: `vendas_registradas.forma_pagamento`
-- JA e `text` com CHECK desde o ticket 02, e o modulo inteiro (repo, recibo,
-- pendencia, fechamento) le e escreve string. Converter a coluna para enum so
-- para ganhar um tipo obrigaria ALTER COLUMN TYPE numa coluna com indice parcial
-- (`vendas_registradas_pix_a_comprovar_idx`) e com codigo em producao lendo —
-- risco sem retorno. **Todas** as tabelas novas desta v2 repetem este mesmo
-- CHECK de 5 valores, de proposito: uma vocabulario so, uma representacao so.
--
-- O QUE ESTA MIGRATION **NAO** FAZ: nao faz backfill (nenhuma venda tem 'cartao'
-- — o CHECK anterior so aceitava 'pix' e 'dinheiro'), nao apaga nada, e nao
-- inclui 'cartao' no conjunto novo justamente para que o parser do card nao
-- consiga gravar de volta a palavra que a reuniao desmembrou.
--
-- Idempotente (DROP CONSTRAINT IF EXISTS antes de ADD): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260820120500_forma_de_pagamento_debito_credito_link.sql
--
-- Conferir DEPOIS:
--   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conrelid = 'barravips.vendas_registradas'::regclass
--      AND conname = 'vendas_registradas_forma_pagamento_valida';
--   SELECT forma_pagamento, count(*) FROM barravips.vendas_registradas
--    GROUP BY forma_pagamento;
-- =============================================================================

BEGIN;

ALTER TABLE barravips.vendas_registradas
  DROP CONSTRAINT IF EXISTS vendas_registradas_forma_pagamento_valida;

ALTER TABLE barravips.vendas_registradas
  ADD CONSTRAINT vendas_registradas_forma_pagamento_valida
    CHECK (
      forma_pagamento IS NULL
      OR forma_pagamento IN ('dinheiro', 'pix', 'debito', 'credito', 'link')
    );

COMMENT ON COLUMN barravips.vendas_registradas.forma_pagamento IS
  'dinheiro | pix | debito | credito | link (ADR-0046 §4 — "cartao" foi desmembrado em debito, '
  'credito e link). Nula ate alguem dizer — e a Pendencia mais comum do grupo (ticket 03), e '
  'entra na cobranca consolidada da manha ao lado do `bolso` nao dito. NAO diz em que bolso o '
  'dinheiro caiu: isso e a coluna `bolso` (ADR-0047). Unica excecao com implicacao direta: '
  'dinheiro e SEMPRE bolso `dela` (especie nao tem outro bolso).';

COMMIT;
