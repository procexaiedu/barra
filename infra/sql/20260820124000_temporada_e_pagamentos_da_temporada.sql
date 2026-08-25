-- =============================================================================
-- 20260820124000_temporada_e_pagamentos_da_temporada.sql
-- **Temporada** como entidade (ADR-0045 §7) e os PAGAMENTOS FEITOS como fato.
--
-- O QUE E: a modelo viaja para uma cidade e trabalha 7/10/14 dias; o pagamento e
-- POR TEMPORADA, nao por atendimento ("comecou a ter muita desistencia no meio
-- do caminho, ai eu falei: vou combinar uma data"). O comando do dono e
-- literalmente "fecha pra mim a temporada da fulana, do dia tal ao dia tal".
--
-- ⚠️ A TEMPORADA **NAO CONGELA O CALCULO** (ADR-0045 §7, e a alternativa
-- explicitamente rejeitada la). Nao existe tabela de saldo, de fechamento nem de
-- snapshot — e nao e esquecimento, e a decisao. O saldo do razao segue DERIVADO
-- (o principio do `fechamento.py` fica intacto): um comprovante que chega depois
-- de "fechada" recalcula o saldo, e a diferenca contra o ja pago aparece como
-- "falta pagar R$ X" (ou credito, se pagou a mais). Nao existe reabertura,
-- porque nunca houve congelamento. Congelar criaria dois numeros concorrentes
-- para a mesma temporada.
--
-- O ESTADO EXISTE APENAS COMO MARCA DE ROTINA, nao como trava de calculo:
-- `aberta` (a viagem esta valendo), `fechada` (o dono mandou fechar e o
-- pagamento foi feito), `cancelada` (a viagem nao aconteceu). Fechar e ACAO DO
-- PAINEL, nunca frase solta no grupo (ADR-0045 §8) — move dinheiro de verdade, e
-- o grupo tem a modelo dentro.
--
-- POR QUE OS PAGAMENTOS REUSAM `financeiro_repasses_pagos` E NAO GANHAM TABELA
-- PROPRIA: aquela tabela ja E, desde o ADR-0011, "pagamentos livres de repasse a
-- modelo", com `modelo_id`, `data_pagamento`, `valor`, `forma_pagamento`,
-- `observacao` e `comprovante_object_key`. Um `temporada_pagamentos` paralelo
-- criaria DUAS tabelas com o mesmo significado ("a casa pagou a modelo") e o
-- razao teria que somar as duas — a primeira soma que esquecer uma delas paga a
-- modelo duas vezes, ou nenhuma. Aqui a temporada e apenas um RECORTE: pagamento
-- com `temporada_id` e "o pagamento daquela temporada"; sem, e o repasse avulso
-- de sempre. `ON DELETE RESTRICT`: apagar uma temporada nao pode evaporar a
-- prova de que o dinheiro saiu.
--
-- POR QUE `cidade` E TEXTO: nao existe tabela de cidades no schema e inventar uma
-- so para isto seria cadastro novo para manter; a cidade e rotulo de viagem
-- ("fecha a temporada da fulana em Goiania"), nao chave de nada.
--
-- O QUE ESTA MIGRATION **NAO** FAZ: nao impede duas temporadas sobrepostas da
-- mesma modelo (exigiria `btree_gist` + EXCLUDE, extensao que nao esta em uso no
-- projeto; a sobreposicao e erro de operacao, checavel no painel), nao guarda
-- percentual proprio (o percentual e da modelo, `modelos.percentual_repasse` com
-- snapshot na venda — ADR-0045 §3 e a alternativa "percentual na Temporada",
-- rejeitada por criar segunda fonte de verdade) e nao mostra comissao de
-- telefonista no extrato dela (ADR-0048, ultima consequencia: sao duas contas de
-- pessoas diferentes, e a modelo le o grupo dela).
--
-- Idempotente (enum em DO $$, CREATE TABLE/INDEX IF NOT EXISTS, ADD COLUMN IF
-- NOT EXISTS, DROP TRIGGER/POLICY antes de criar). Sem seed: schema puro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260820124000_temporada_e_pagamentos_da_temporada.sql
--
-- Conferir DEPOIS:
--   \d barravips.temporadas
--   SELECT column_name FROM information_schema.columns
--    WHERE table_schema='barravips' AND table_name='financeiro_repasses_pagos'
--      AND column_name='temporada_id';
-- =============================================================================

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'temporada_estado_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.temporada_estado_enum AS ENUM (
      'aberta',
      'fechada',
      'cancelada'
    );
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS barravips.temporadas (
  id           uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id    uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  cidade       text NOT NULL,
  data_inicio  date NOT NULL,
  data_fim     date NOT NULL,
  estado       barravips.temporada_estado_enum NOT NULL DEFAULT 'aberta',
  observacao   text,
  fechada_em   timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  created_by   uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
  CONSTRAINT temporadas_cidade_nao_vazia CHECK (btrim(cidade) <> ''),
  CONSTRAINT temporadas_periodo_valido CHECK (data_fim >= data_inicio),
  CONSTRAINT temporadas_fechada_tem_data CHECK ((estado = 'fechada') = (fechada_em IS NOT NULL))
);

COMMENT ON TABLE barravips.temporadas IS
  'Temporada (ADR-0045 §7): a viagem da modelo para uma cidade por N dias, que e a unidade de '
  'pagamento do negocio ("fecha pra mim a temporada da fulana, do dia tal ao dia tal"). NAO '
  'congela calculo nenhum — nao existe saldo, fechamento nem snapshot gravado aqui; o saldo do '
  'razao segue derivado, e comprovante que chega depois recalcula.';
COMMENT ON COLUMN barravips.temporadas.cidade IS
  'Rotulo da viagem, texto livre. Nao ha cadastro de cidades no schema e a cidade nao e chave de '
  'nada — inventar a tabela seria cadastro novo para manter sem uso.';
COMMENT ON COLUMN barravips.temporadas.estado IS
  'aberta | fechada | cancelada. Marca de ROTINA, nunca trava de calculo: `fechada` significa '
  'que o dono mandou fechar e o pagamento foi feito, nao que o numero parou de mudar. Nao existe '
  'reabertura porque nunca houve congelamento (ADR-0045 §7). Fechar e acao do PAINEL, nunca '
  'frase solta no grupo (§8) — move dinheiro de verdade e a modelo esta no grupo.';
COMMENT ON COLUMN barravips.temporadas.fechada_em IS
  'Quando o painel fechou a temporada. Serve para explicar o extrato ("o que chegou depois disto '
  'e a diferenca a pagar"), nao para filtrar dinheiro de fora.';

CREATE INDEX IF NOT EXISTS temporadas_modelo_periodo_idx
  ON barravips.temporadas (modelo_id, data_inicio DESC);
CREATE INDEX IF NOT EXISTS temporadas_abertas_idx
  ON barravips.temporadas (modelo_id, data_fim)
  WHERE estado = 'aberta';

DROP TRIGGER IF EXISTS set_updated_at_temporadas ON barravips.temporadas;
CREATE TRIGGER set_updated_at_temporadas
  BEFORE UPDATE ON barravips.temporadas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.temporadas ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.temporadas FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.temporadas;
CREATE POLICY fernando_full_access
  ON barravips.temporadas
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.temporadas TO authenticated;
GRANT ALL PRIVILEGES ON barravips.temporadas TO service_role;

-- --- Os pagamentos FEITOS: recorte de `financeiro_repasses_pagos` -----------------------------

ALTER TABLE barravips.financeiro_repasses_pagos
  ADD COLUMN IF NOT EXISTS temporada_id uuid
    REFERENCES barravips.temporadas(id) ON DELETE RESTRICT;

COMMENT ON COLUMN barravips.financeiro_repasses_pagos.temporada_id IS
  'A Temporada que este pagamento quitou (ADR-0045 §7 — "o que a temporada guarda como fato sao '
  'os pagamentos feitos"). NULA = repasse avulso, como sempre foi. Esta coluna existe para que '
  'nao haja uma segunda tabela com o mesmo significado ("a casa pagou a modelo"): o razao soma '
  'ESTA tabela inteira, e a temporada e so um recorte dela. RESTRICT: apagar a temporada nao '
  'apaga a prova de que o dinheiro saiu.';

CREATE INDEX IF NOT EXISTS financeiro_repasses_temporada_idx
  ON barravips.financeiro_repasses_pagos (temporada_id)
  WHERE temporada_id IS NOT NULL;

COMMIT;
