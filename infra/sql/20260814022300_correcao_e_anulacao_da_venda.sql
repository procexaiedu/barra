-- =============================================================================
-- 20260814022300_correcao_e_anulacao_da_venda.sql
-- Correcao pelo grupo: anulacao com rastro + evento de auditoria (spec 0005,
-- ticket 05).
--
-- O grupo real corrige de tres jeitos, e os tres precisam terminar com UM
-- registro vivo e correto (docs/dominio/grupo-financeiro.md, "Venda
-- registrada"):
--   1. responde o recibo com o campo novo ("foi 650", "o cliente era Ramon");
--   2. APAGA a mensagem do anuncio (gesto real visto em 08/08);
--   3. REPOSTA a versao corrigida.
--
-- POR QUE `anulada_em` E NAO DELETE:
-- venda e dinheiro e a linha ja pode ter sido contada. Anulacao e ESTADO com
-- rastro — o `mensagem_id` (RESTRICT) continua provando de onde ela veio e o
-- evento de auditoria diz quando morreu e por causa de qual mensagem. Um DELETE
-- levaria junto a unica prova de que a venda existiu.
--
-- POR QUE O UNIQUE DE `chave_conteudo` VIRA PARCIAL:
-- o dedup do ticket 04 existe para o mesmo FATO nao entrar duas vezes VIVAS. Com
-- o UNIQUE global, apagar-e-repostar o anuncio IDENTICO (o gesto de 08/08, em
-- que a gestora reposta a mesma coisa) terminaria em ZERO registros vivos: a
-- linha antiga anulada seguraria a chave e o repost cairia no
-- `ON CONFLICT DO NOTHING`. Restringindo o indice as linhas vivas, o dedup
-- continua exatamente igual enquanto ninguem anula nada, e o repost depois da
-- delecao volta a registrar — que e o criterio do ticket ("apagar + repostar
-- termina com exatamente UM registro vivo").
-- Consequencia para a aplicacao: o `ON CONFLICT` precisa repetir o predicado
-- (`ON CONFLICT (chave_conteudo) WHERE anulada_em IS NULL`), senao o Postgres
-- nao infere o indice parcial.
--
-- POR QUE `apagada_em` NA MENSAGEM:
-- o estado conversacional do modulo e DERIVADO do log de origem (ticket 03: o
-- "600" solto so significa algo a luz do anuncio anterior). Se a mensagem
-- apagada continuasse no contexto, um anuncio que a gestora apagou seguiria
-- esperando resposta e capturaria o proximo numero solto do grupo. Apagada sai
-- do contexto — e ela some da conversa exatamente como sumiu da tela de todo
-- mundo.
--
-- `venda_registrada_eventos` e APPEND-ONLY (sem updated_at, sem UPDATE/DELETE
-- para `authenticated`): auditoria que se edita nao e auditoria. Uma linha por
-- CAMPO corrigido — e assim que "o que mudou" fica consultavel sem diff de
-- JSON, no mesmo espirito da `chave_conteudo` legivel do ticket 04.
--
-- Idempotente (ADD COLUMN IF NOT EXISTS, DROP INDEX/TRIGGER/POLICY IF EXISTS,
-- CREATE ... IF NOT EXISTS): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814022300_correcao_e_anulacao_da_venda.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.vendas_registradas
--   \d barravips.venda_registrada_eventos
--   SELECT indexdef FROM pg_indexes
--    WHERE schemaname='barravips' AND tablename='vendas_registradas';
-- =============================================================================

BEGIN;

-- --- a mensagem-fonte apagada ------------------------------------------------------------------

ALTER TABLE barravips.grupo_financeiro_mensagens
  ADD COLUMN IF NOT EXISTS apagada_em timestamptz;

COMMENT ON COLUMN barravips.grupo_financeiro_mensagens.apagada_em IS
  'Quando o evento de delecao da plataforma chegou para esta mensagem (spec 0005, ticket 05). A '
  'linha do log NAO e apagada — ela e a origem auditavel da venda que nasceu dali. Mensagem '
  'apagada sai do CONTEXTO conversacional: um anuncio que a gestora apagou nao pode continuar '
  'esperando o "600" que responde a pergunta minima.';

-- --- a Venda registrada anulada ----------------------------------------------------------------

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS anulada_em timestamptz;

COMMENT ON COLUMN barravips.vendas_registradas.anulada_em IS
  'Venda anulada (spec 0005, ticket 05): a mensagem-fonte foi apagada no grupo. Estado com '
  'rastro, NUNCA DELETE — a linha continua provando de onde veio e o rastro do que mudou fica em '
  '`venda_registrada_eventos`. Linha anulada nao conta em receita, extrato, fechamento nem '
  'pendencia, e nao segura mais a `chave_conteudo` do dedup.';

-- O dedup do ticket 04 passa a valer so entre linhas VIVAS (ver cabecalho).
DROP INDEX IF EXISTS barravips.vendas_registradas_chave_conteudo_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS vendas_registradas_chave_conteudo_viva_uniq
  ON barravips.vendas_registradas (chave_conteudo)
  WHERE anulada_em IS NULL;

-- --- o evento de auditoria ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.venda_registrada_eventos (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  venda_id        uuid NOT NULL
                  REFERENCES barravips.vendas_registradas(id) ON DELETE RESTRICT,
  tipo            text NOT NULL,
  campo           text,
  valor_anterior  text,
  valor_novo      text,
  mensagem_id     uuid REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT venda_registrada_eventos_tipo_valido
    CHECK (tipo IN ('correcao', 'anulacao')),
  CONSTRAINT venda_registrada_eventos_correcao_tem_campo
    CHECK (tipo <> 'correcao' OR campo IS NOT NULL)
);

COMMENT ON TABLE barravips.venda_registrada_eventos IS
  'Rastro de toda correcao e anulacao de Venda registrada (spec 0005, ticket 05). APPEND-ONLY: '
  'auditoria que se edita nao e auditoria. Uma linha por CAMPO corrigido; a anulacao e uma linha '
  'so, sem campo.';
COMMENT ON COLUMN barravips.venda_registrada_eventos.tipo IS
  'correcao (quote no recibo trocou um campo) | anulacao (a mensagem-fonte foi apagada).';
COMMENT ON COLUMN barravips.venda_registrada_eventos.campo IS
  'Campo corrigido: valor | data | cliente | duracao | forma_pagamento. Nulo na anulacao.';
COMMENT ON COLUMN barravips.venda_registrada_eventos.valor_anterior IS
  'Como o campo estava, em TEXTO legivel ("R$ 700,00", "Gabriel"). Texto e nao coluna tipada '
  'porque o evento cobre campos de tipos diferentes e quem le e humano — a mesma escolha da '
  '`chave_conteudo` legivel do ticket 04.';
COMMENT ON COLUMN barravips.venda_registrada_eventos.mensagem_id IS
  'A mensagem do grupo que causou o evento (a correcao por quote, ou o anuncio que foi apagado). '
  'Nula quando a origem nao for o grupo — correcao pelo painel nao existe ainda, mas nasceria '
  'sem mensagem.';

CREATE INDEX IF NOT EXISTS venda_registrada_eventos_venda_idx
  ON barravips.venda_registrada_eventos (venda_id, created_at DESC);

ALTER TABLE barravips.venda_registrada_eventos ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.venda_registrada_eventos FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.venda_registrada_eventos;
CREATE POLICY fernando_full_access
  ON barravips.venda_registrada_eventos
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

-- Sem UPDATE/DELETE de proposito (o resto do schema concede os quatro): append-only e uma
-- garantia do banco, nao uma convencao da aplicacao.
GRANT SELECT, INSERT ON barravips.venda_registrada_eventos TO authenticated;
GRANT ALL PRIVILEGES ON barravips.venda_registrada_eventos TO service_role;

COMMIT;
