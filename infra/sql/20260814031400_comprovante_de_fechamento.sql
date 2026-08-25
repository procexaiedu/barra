-- =============================================================================
-- 20260814031400_comprovante_de_fechamento.sql
-- Comprovante de transferencia lido por OCR + chaves Pix conhecidas da casa +
-- abate FIFO das vendas pix abertas (spec 0005, ticket 07).
--
-- O QUE O GRUPO FAZ HOJE (export "Modelo Yasmin Ruiva/financeiro", 12/08):
-- a gestora confere de cabeca ("600 pix / 600 pix"), pede a transferencia
-- ("Pode enviar nesse pix") e a modelo posta a foto do comprovante de
-- R$ 1.200,00. Ninguem registra nada: a conferencia vendido x comprovado mora
-- na cabeca do gestor.
--
-- POR QUE UMA TABELA DE COMPROVANTE, E NAO SO UMA COLUNA NA VENDA:
-- um comprovante abate N vendas (o de R$ 1.200,00 fecha as duas de R$ 600,00) e
-- pode nao abater NENHUMA (o de R$ 385,80, que e pagamento de Cobranca da
-- agencia — ticket 08). Comprovante que nao casa com venda **nao pode sumir**:
-- ele e a prova de que dinheiro saiu da modelo. Como linha propria ele fica
-- retido, classificado `nao_classificado`, visivel no painel e reclassificavel
-- depois; como coluna na venda, ele simplesmente nao existiria.
--
-- POR QUE `vendas_registradas.comprovante_id` (e nao um valor abatido por venda):
-- o abate e FIFO e por venda INTEIRA — uma venda esta comprovada ou nao esta.
-- Abater meia venda criaria um terceiro estado ("parcialmente comprovada") que
-- nenhuma conversa do grupo produz: o que sobra do comprovante fica no proprio
-- comprovante (`valor` - `valor_abatido`) e continua sendo saldo da modelo no
-- Fechamento (ticket 09), sem picar linha de venda.
--
-- POR QUE AS CHAVES CONHECIDAS SAO CADASTRO (closed-world) E NAO UMA TRAVA:
-- destino fora da lista **nunca** trava o abate (docs/dominio: "travar algo por
-- comprovante duvidoso" e proibido — mesma filosofia do Pix da venda). A lista
-- serve para SINALIZAR ao gestor: dinheiro indo para chave desconhecida e erro
-- de digitacao ou golpe, e o valor de pegar isso esta em avisar cedo, nao em
-- segurar a operacao.
--
-- SEM SEED AQUI, E SEM SEED EM LUGAR NENHUM DO REPOSITORIO. Esta migration cria
-- SCHEMA; a chave de fechamento da casa e DADO OPERACIONAL (chave Pix viva +
-- nome civil do titular) e por decisao do dono (14/08/2026) nao entra no git —
-- nem aqui, nem em arquivo de seed proprio. Ela vira um INSERT manual, feito uma
-- vez por ambiente, descrito em `infra/runbooks/aplicar-migrations-prod.md`
-- ("Dado operacional que nao mora no repositorio: a chave Pix de fechamento").
-- Enquanto essa linha nao existir, `chave_e_conhecida()` devolve False para todo
-- comprovante e o agente sinaliza "destino fora da lista da casa" em TODOS eles:
-- fail-safe conhecido e aceito — ruidoso, nunca travante (o abate acontece do
-- mesmo jeito). O codigo NAO muda por causa disso: a tabela continua sendo a
-- unica fonte.
--
-- Idempotente (IF NOT EXISTS, ON CONFLICT DO NOTHING): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814031400_comprovante_de_fechamento.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.comprovantes_do_grupo
--   \d barravips.chaves_pix_conhecidas
--   SELECT indexdef FROM pg_indexes
--    WHERE schemaname='barravips' AND tablename='vendas_registradas';
-- =============================================================================

BEGIN;

-- --- chaves Pix conhecidas da casa -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.chaves_pix_conhecidas (
  id                 uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  chave              text NOT NULL,
  chave_normalizada  text NOT NULL UNIQUE,
  titular            text,
  descricao          text,
  ativo              boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.chaves_pix_conhecidas IS
  'Chaves Pix conhecidas da casa (spec 0005, ticket 07): para onde o dinheiro do fechamento '
  'legitimamente vai. Comprovante com destino FORA desta lista nao trava nada — gera sinalizacao '
  'ao gestor no grupo e flag no painel.';
COMMENT ON COLUMN barravips.chaves_pix_conhecidas.chave_normalizada IS
  'A chave sem espaco, pontuacao e sinal, em minusculo — a mesma normalizacao que o codigo aplica '
  'ao que o OCR leu ("+55 71 99984 0879" e "+5571999840879" sao a MESMA chave). UNIQUE aqui e o '
  'que impede a mesma chave cadastrada duas vezes com grafias diferentes.';
COMMENT ON COLUMN barravips.chaves_pix_conhecidas.ativo IS
  'Inativar nunca deletar: chave que saiu de uso precisa continuar explicando os comprovantes '
  'antigos que apontam para ela.';

DROP TRIGGER IF EXISTS set_updated_at ON barravips.chaves_pix_conhecidas;
DROP TRIGGER IF EXISTS set_updated_at_chaves_pix_conhecidas ON barravips.chaves_pix_conhecidas;
CREATE TRIGGER set_updated_at_chaves_pix_conhecidas
  BEFORE UPDATE ON barravips.chaves_pix_conhecidas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.chaves_pix_conhecidas ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.chaves_pix_conhecidas FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.chaves_pix_conhecidas;
CREATE POLICY fernando_full_access
  ON barravips.chaves_pix_conhecidas
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.chaves_pix_conhecidas TO authenticated;
GRANT ALL PRIVILEGES ON barravips.chaves_pix_conhecidas TO service_role;

-- --- o comprovante lido ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.comprovantes_do_grupo (
  id                  uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  grupo_id            uuid NOT NULL
                      REFERENCES barravips.grupos_financeiros(id) ON DELETE RESTRICT,
  mensagem_id         uuid NOT NULL UNIQUE
                      REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  classificacao       text NOT NULL,
  valor               numeric(10,2),
  data_transferencia  date,
  pagador             text,
  chave_destino       text,
  titular_destino     text,
  chave_conhecida     boolean NOT NULL DEFAULT false,
  valor_abatido       numeric(10,2) NOT NULL DEFAULT 0,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT comprovantes_do_grupo_classificacao_valida
    CHECK (classificacao IN ('fechamento', 'nao_classificado', 'ilegivel')),
  -- Comprovante classificado como fechamento TEM valor: sem valor nao ha o que abater, e a
  -- classificacao seria um palpite sobre uma imagem que ninguem leu.
  CONSTRAINT comprovantes_do_grupo_fechamento_tem_valor
    CHECK (classificacao <> 'fechamento' OR valor IS NOT NULL),
  -- O abate nunca e negativo e nunca passa o que a modelo transferiu. E o invariante da terceira
  -- coluna do Fechamento: `valor - valor_abatido` e a sobra (credito da modelo), e sobra negativa
  -- seria o sistema afirmando que ela comprovou mais do que mandou.
  CONSTRAINT comprovantes_do_grupo_abatido_no_intervalo
    CHECK (valor_abatido >= 0 AND (valor IS NULL OR valor_abatido <= valor))
);

COMMENT ON TABLE barravips.comprovantes_do_grupo IS
  'Comprovante de transferencia postado no Grupo financeiro, lido por OCR (spec 0005, ticket 07). '
  'UMA linha por mensagem-imagem (UNIQUE em mensagem_id: reentrega do webhook nao le a imagem duas '
  'vezes, e OCR reentregue e dinheiro queimado). Comprovante que nao casa com venda nenhuma fica '
  'aqui como `nao_classificado` — prova de que dinheiro saiu, esperando reclassificacao.';
COMMENT ON COLUMN barravips.comprovantes_do_grupo.classificacao IS
  'fechamento (abateu venda pix aberta) | nao_classificado (nao casou com nenhuma — pergunta no '
  'grupo, ticket 08 reclassifica como pagamento de Cobranca da agencia) | ilegivel (OCR nao leu; '
  'o agente pediu reenvio).';
COMMENT ON COLUMN barravips.comprovantes_do_grupo.chave_conhecida IS
  'A chave de destino estava em `chaves_pix_conhecidas` no momento da leitura? FALSE nao trava '
  'nada — e a flag que o painel mostra e o aviso que o agente posta ao gestor.';
COMMENT ON COLUMN barravips.comprovantes_do_grupo.valor_abatido IS
  'Quanto deste comprovante virou venda comprovada (soma das vendas abatidas em FIFO). A '
  'diferenca para `valor` e a sobra — credito da modelo que segue no saldo corrente, sem picar '
  'linha de venda.';
COMMENT ON COLUMN barravips.comprovantes_do_grupo.pagador IS
  'Quem fez a transferencia, como o comprovante escreve (tipicamente a propria modelo). Texto '
  'livre: nao vira Cliente nem Modelo — o mesmo criterio de `vendas_registradas.cliente_nome`.';

CREATE INDEX IF NOT EXISTS comprovantes_do_grupo_grupo_idx
  ON barravips.comprovantes_do_grupo (grupo_id, created_at DESC);

-- A fila de comprovante retido: e a leitura quente do painel (ticket 11) e a do ticket 08, que
-- reclassifica o que ficou aqui.
CREATE INDEX IF NOT EXISTS comprovantes_do_grupo_nao_classificado_idx
  ON barravips.comprovantes_do_grupo (grupo_id, created_at DESC)
  WHERE classificacao = 'nao_classificado';

DROP TRIGGER IF EXISTS set_updated_at ON barravips.comprovantes_do_grupo;
DROP TRIGGER IF EXISTS set_updated_at_comprovantes_do_grupo ON barravips.comprovantes_do_grupo;
CREATE TRIGGER set_updated_at_comprovantes_do_grupo
  BEFORE UPDATE ON barravips.comprovantes_do_grupo
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.comprovantes_do_grupo ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.comprovantes_do_grupo FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.comprovantes_do_grupo;
CREATE POLICY fernando_full_access
  ON barravips.comprovantes_do_grupo
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.comprovantes_do_grupo TO authenticated;
GRANT ALL PRIVILEGES ON barravips.comprovantes_do_grupo TO service_role;

-- --- a venda comprovada ------------------------------------------------------------------------

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS comprovante_id uuid
    REFERENCES barravips.comprovantes_do_grupo(id) ON DELETE RESTRICT;

COMMENT ON COLUMN barravips.vendas_registradas.comprovante_id IS
  'O Comprovante de transferencia que abateu esta venda (spec 0005, ticket 07). Nulo + '
  'forma_pagamento=pix = **Pendencia de comprovante**; dinheiro nunca entra nessa fila (fica em '
  'especie com a modelo, fora da expectativa de comprovante).';

-- A fila FIFO do abate e a Pendencia de comprovante sao a MESMA consulta — este indice parcial e
-- ela. Dinheiro e venda anulada ficam de fora do indice, nao so do WHERE: elas nunca entram na
-- expectativa de comprovante.
CREATE INDEX IF NOT EXISTS vendas_registradas_pix_a_comprovar_idx
  ON barravips.vendas_registradas (modelo_id, data, id)
  WHERE forma_pagamento = 'pix' AND comprovante_id IS NULL AND anulada_em IS NULL;

-- A chave de fechamento da casa NAO e semeada por migration nenhuma: e INSERT
-- manual por ambiente — ver infra/runbooks/aplicar-migrations-prod.md.

COMMIT;
