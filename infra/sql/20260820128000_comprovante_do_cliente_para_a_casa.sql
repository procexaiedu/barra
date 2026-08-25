-- =============================================================================
-- 20260820128000_comprovante_do_cliente_para_a_casa.sql
-- A SEXTA classe de comprovante: o CLIENTE pagando a CASA (ADR-0047 §2, ticket
-- 14). Irma de `entrada_da_modelo` (20260814233000) e distinguida pelo MESMO
-- criterio de duas pernas — quem pagou e quem recebeu, sempre as duas juntas:
--
--   pagou      | recebeu   | classe                | efeito
--   -----------+-----------+-----------------------+-------------------------
--   a modelo   | a casa    | fechamento / cobranca | abate pix (FIFO) / quita
--   o cliente  | a modelo  | entrada_da_modelo     | nada (prova do pagamento)
--   o cliente  | a casa    | cliente_para_a_casa   | fixa o BOLSO em `empresa`
--
-- Por que ela precisa existir. Depois do ADR-0047 o bolso da venda e resolvido
-- por evidencia, e esta imagem e a segunda linha da tabela de precedencia: o
-- cliente pagou a casa direto, entao o dinheiro NUNCA passou pela mao da modelo.
-- Se a venda ficasse com `bolso = 'dela'` — inclusive pelo default conservador
-- que o razao aplica a `nao_dito` — o razao debitaria dela um bruto que ela nunca
-- teve, e o saldo ficaria torto EM SILENCIO, que e o unico erro deste modulo que
-- ninguem descobre olhando o grupo.
--
-- O que ela NAO faz, e e por isso que ela e classe e nao um `fechamento` com
-- flag: ela nao abate venda em pix (nao ha transferencia dela para abater) e nao
-- quita Cobranca da agencia. Sem esta linha, o mesmo Pix que prova que a casa
-- recebeu direto do cliente daria por comprovada uma transferencia que a modelo
-- nunca fez — e a venda sairia da fila de cobranca pelo motivo errado.
--
-- ⚠️ A classificacao exige o PAGADOR positivamente lido (regra do dominio, em
-- `dominio/grupo_financeiro/comprovante.py::e_do_cliente_para_a_casa`, NAO do
-- banco). O OCR falha no nome do pagador com frequencia, e "pagador desconhecido
-- + destino da casa" e como metade dos fechamentos legitimos chega: classificar
-- esses aqui pararia o abate FIFO da casa inteira em silencio.
--
-- Sem CHECK novo de valor: a mesma razao de 20260814233000 — a leitura ilegivel
-- morre antes, em `ilegivel`, e amarrar a constraint tambem a esta classe custaria
-- uma migration nova no dia em que a conduta mudar.
--
-- SEM BACKFILL: nenhum comprovante ja gravado muda de classe. Reclassificar o
-- passado exigiria reprocessar o par (pagador, destino) de imagens que ja nao
-- estao no disco — e mudaria o saldo de temporadas ja pagas.
--
-- Idempotente (DROP CONSTRAINT IF EXISTS + ADD). Sem seed: schema puro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260820128000_comprovante_do_cliente_para_a_casa.sql
--
-- Conferir DEPOIS:
--   SELECT classificacao, count(*) FROM barravips.comprovantes_do_grupo
--    GROUP BY classificacao;
-- =============================================================================

BEGIN;

ALTER TABLE barravips.comprovantes_do_grupo
  DROP CONSTRAINT IF EXISTS comprovantes_do_grupo_classificacao_valida;

ALTER TABLE barravips.comprovantes_do_grupo
  ADD CONSTRAINT comprovantes_do_grupo_classificacao_valida
    CHECK (classificacao IN
      ('fechamento',
       'cobranca',
       'entrada_da_modelo',
       'cliente_para_a_casa',
       'nao_classificado',
       'ilegivel'));

COMMENT ON COLUMN barravips.comprovantes_do_grupo.classificacao IS
  'fechamento (abateu venda pix aberta) | cobranca (quitou uma Cobranca da agencia — abate a '
  'cobranca, NUNCA as vendas, ticket 08) | entrada_da_modelo (o cliente pagou A modelo: fica de '
  'prova, nao abate nada) | cliente_para_a_casa (o cliente pagou A CASA direto: nao abate nem '
  'quita — fixa o bolso da venda em `empresa`, ADR-0047 §2) | nao_classificado (nao casou com '
  'nada, ou casaria com as duas coisas: pergunta no grupo e fica retido) | ilegivel (OCR nao '
  'leu; o agente pediu reenvio).';

COMMIT;
