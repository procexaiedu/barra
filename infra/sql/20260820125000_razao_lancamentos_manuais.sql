-- =============================================================================
-- 20260820125000_razao_lancamentos_manuais.sql
-- **Vale** e lancamento manual do razao — a terceira classe de dado do Modulo
-- Financeiro (ADR-0045, ultima consequencia), ao lado das duas fontes de receita
-- do ADR-0043.
--
-- O RAZAO E DERIVADO, ESTA TABELA NAO E O RAZAO. O razao (ADR-0045 §1) e uma
-- conta corrente unica por modelo, calculada a partir de fatos que ja existem em
-- outras tabelas:
--   venda cujo dinheiro caiu na mao dela ...... debito  (vendas_registradas.bolso)
--   comissao da venda ......................... credito (percentual_repasse_snapshot)
--   venda paga no Pix/cartao da empresa ....... nao toca
--   transferencia dela -> casa ................ credito (comprovantes_do_grupo)
--   cobranca da agencia (3RJ, site) ........... debito  (cobrancas_da_agencia)
--   deslocamento recebido por ela ............. debito  (deslocamentos_da_venda)
--   pagamento da casa -> ela .................. debito  (financeiro_repasses_pagos)
-- Sobra UMA linha da tabela do ADR-0045 §1 que nao tem fato de origem em lugar
-- nenhum: o **vale adiantado**. E o que mora aqui, junto com o ajuste manual que
-- todo razao precisa quando a realidade nao coube em nenhuma das linhas acima.
-- O nome da tabela diz MANUAIS de proposito: quem procurar aqui o saldo da
-- modelo esta procurando no lugar errado, e nao ha saldo materializado nenhum
-- neste modulo (ADR-0045 §7).
--
-- POR QUE `origem` (painel x grupo): o vale e dito no grupo o tempo todo
-- ("adiantei 500 pra ela") e o agente aprende a le-lo LA, com recibo corrigivel,
-- alem da entrada pelo painel (ADR-0045 §8). Sao dois caminhos com confiabilidade
-- diferente: o do grupo tem mensagem-fonte e pode ser anulado por delecao; o do
-- painel tem usuario. O CHECK amarra: `origem = 'grupo'` EXIGE `mensagem_id`.
--
-- POR QUE `sentido` E NAO VALOR COM SINAL: `valor > 0` sempre, e a direcao e
-- enum. Numero negativo em coluna de dinheiro e a forma mais barata de somar
-- errado — basta um `SUM(abs(...))` ou um sinal invertido na escrita para o
-- saldo virar do avesso, calado. Vale e SEMPRE `debito` (CHECK): adiantamento e
-- dinheiro que ela ja pegou.
--
-- ⚠️ O QUE **NAO** E VALE (ADR-0047 §5): "ficou com ela" — o gestor dizendo que
-- a modelo ficou com o dinheiro de uma venda — NAO gera lancamento aqui. Isso e
-- a venda com `bolso = 'dela'` MAIS a ausencia da transferencia, e o razao ja
-- produz o resultado certo sem conceito novo. Lancar tambem um vale contaria o
-- mesmo dinheiro duas vezes. A palavra "vale" na fala do gestor so vira linha
-- aqui quando houver adiantamento FORA de uma venda.
--
-- Idempotente (enums em DO $$, CREATE TABLE/INDEX IF NOT EXISTS, DROP
-- TRIGGER/POLICY antes de criar). Sem seed: schema puro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py infra/sql/20260820125000_razao_lancamentos_manuais.sql
--
-- Conferir DEPOIS:
--   \d barravips.razao_lancamentos_manuais
-- =============================================================================

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'razao_lancamento_tipo_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.razao_lancamento_tipo_enum AS ENUM (
      'vale',
      'ajuste'
    );
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'razao_lancamento_sentido_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.razao_lancamento_sentido_enum AS ENUM (
      'debito',
      'credito'
    );
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'razao_lancamento_origem_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.razao_lancamento_origem_enum AS ENUM (
      'painel',
      'grupo'
    );
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS barravips.razao_lancamentos_manuais (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id       uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  tipo            barravips.razao_lancamento_tipo_enum NOT NULL,
  sentido         barravips.razao_lancamento_sentido_enum NOT NULL,
  valor           numeric(10,2) NOT NULL CHECK (valor > 0),
  data            date NOT NULL,
  descricao       text,
  origem          barravips.razao_lancamento_origem_enum NOT NULL,
  mensagem_id     uuid REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  temporada_id    uuid REFERENCES barravips.temporadas(id) ON DELETE RESTRICT,
  chave_conteudo  text,
  anulado_em      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  created_by      uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
  CONSTRAINT razao_lancamentos_manuais_vale_e_debito
    CHECK (tipo <> 'vale' OR sentido = 'debito'),
  CONSTRAINT razao_lancamentos_manuais_grupo_tem_mensagem
    CHECK (origem <> 'grupo' OR mensagem_id IS NOT NULL)
);

COMMENT ON TABLE barravips.razao_lancamentos_manuais IS
  'Vale adiantado e ajuste manual do razao da modelo (ADR-0045 §1 e §8). MANUAIS no nome de '
  'proposito: o razao e DERIVADO das tabelas de fato (vendas, comissao, comprovantes, cobrancas, '
  'deslocamento, repasses pagos) e esta tabela guarda so a unica linha daquela tabela que nao '
  'tem fato proprio — o adiantamento — mais o ajuste que a realidade exigir. Nao ha saldo '
  'materializado em lugar nenhum deste modulo.';
COMMENT ON COLUMN barravips.razao_lancamentos_manuais.tipo IS
  'vale (adiantamento FORA de uma venda: "adiantei 500 pra ela") | ajuste (correcao declarada '
  'que nao cabe em nenhum fato). ⚠️ "Ficou com ela", dito sobre uma venda, NAO e vale: e a venda '
  'com bolso `dela` mais a ausencia da transferencia (ADR-0047 §5) — lancar aqui tambem contaria '
  'o mesmo dinheiro duas vezes.';
COMMENT ON COLUMN barravips.razao_lancamentos_manuais.sentido IS
  'debito = ela deve a casa | credito = a casa deve a ela. Direcao em enum e `valor > 0` sempre: '
  'numero negativo em coluna de dinheiro e a forma mais barata de somar errado em silencio. Vale '
  'e SEMPRE debito (CHECK) — adiantamento e dinheiro que ela ja pegou.';
COMMENT ON COLUMN barravips.razao_lancamentos_manuais.origem IS
  'painel (entrada do gestor, com `created_by`) | grupo (o agente leu a fala e gravou com recibo '
  'corrigivel, com `mensagem_id` obrigatorio pelo CHECK). Os dois caminhos existem porque o vale '
  'e dito no grupo o tempo todo (ADR-0045 §8).';
COMMENT ON COLUMN barravips.razao_lancamentos_manuais.temporada_id IS
  'A Temporada em que o vale foi adiantado, quando houver ("existe vale adiantado no meio, que e '
  'descontado no fim"). NULA nao muda nada no razao — o saldo e corrente e continuo; a temporada '
  'e recorte de leitura.';
COMMENT ON COLUMN barravips.razao_lancamentos_manuais.chave_conteudo IS
  'Identidade do fato para o dedup do que veio do GRUPO (repost/reentrega), no mesmo formato '
  'legivel das demais chaves do modulo. NULA no que veio do painel — la o gestor e responsavel '
  'pelo que digita. UNIQUE entre os vivos (indice parcial).';
COMMENT ON COLUMN barravips.razao_lancamentos_manuais.anulado_em IS
  'Estado com rastro, nunca DELETE (mensagem-fonte apagada no grupo, ou estorno pelo painel). '
  'Lancamento anulado sai do razao e solta a `chave_conteudo`.';

CREATE INDEX IF NOT EXISTS razao_lancamentos_manuais_modelo_data_idx
  ON barravips.razao_lancamentos_manuais (modelo_id, data)
  WHERE anulado_em IS NULL;
CREATE INDEX IF NOT EXISTS razao_lancamentos_manuais_mensagem_idx
  ON barravips.razao_lancamentos_manuais (mensagem_id)
  WHERE mensagem_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS razao_lancamentos_manuais_temporada_idx
  ON barravips.razao_lancamentos_manuais (temporada_id)
  WHERE temporada_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS razao_lancamentos_manuais_chave_conteudo_viva_uniq
  ON barravips.razao_lancamentos_manuais (chave_conteudo)
  WHERE chave_conteudo IS NOT NULL AND anulado_em IS NULL;

DROP TRIGGER IF EXISTS set_updated_at_razao_lancamentos_manuais
  ON barravips.razao_lancamentos_manuais;
CREATE TRIGGER set_updated_at_razao_lancamentos_manuais
  BEFORE UPDATE ON barravips.razao_lancamentos_manuais
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.razao_lancamentos_manuais ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.razao_lancamentos_manuais FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.razao_lancamentos_manuais;
CREATE POLICY fernando_full_access
  ON barravips.razao_lancamentos_manuais
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.razao_lancamentos_manuais TO authenticated;
GRANT ALL PRIVILEGES ON barravips.razao_lancamentos_manuais TO service_role;

COMMIT;
