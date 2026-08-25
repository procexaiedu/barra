-- =============================================================================
-- 20260820123000_deslocamento_da_venda.sql
-- Deslocamento como LANCAMENTO PROPRIO, ligado a venda, com **DOIS** valores
-- (ADR-0045 §5, revisto pelo ADR-0046 §6).
--
-- POR QUE DOIS VALORES E NAO UM: `valor_antecipado` e o que o CLIENTE mandou
-- pelo transporte (receita, tipicamente R$ 100); `valor_transporte` e o que o
-- Uber CUSTOU (custo). "Quando o Rossi paga R$ 15 de um Uber curto sem cobrar do
-- cliente, o antecipado e zero e o transporte nao e." Um campo so nao distingue
-- "o cliente mandou 100 e o Uber custou 60" de "o cliente nao mandou nada e o
-- Uber custou 15" — e a diferenca entre os dois e exatamente a margem (ou o
-- prejuizo) que some se o sistema guardar um numero so. Foi o desenho do
-- ADR-0045 §5 e o ADR-0046 §6 o corrigiu.
--
-- POR QUE UMA TABELA E NAO DUAS COLUNAS EM `vendas_registradas`: o deslocamento
-- fica **FORA da base de comissao** dos dois lados (ADR-0045 §5 para a modelo,
-- ADR-0048 §3 para o telefonista: "o Valor antecipado que o cliente manda pelo
-- Uber nao e venda"). Como coluna da venda, ele estaria a um SUM() distraido de
-- entrar no faturamento; como lancamento separado, quem quiser soma-lo precisa
-- ir busca-lo. Alem disso ele tem duas ATRIBUICOES proprias que a venda nao tem
-- (quem recebeu, quem pagou) e pode simplesmente nao existir.
--
-- AS DUAS ATRIBUICOES SAO O QUE FAZ O RAZAO FECHAR (ADR-0045 §5):
--   recebido por ELA e pago pela CASA .......... debito dela (ela ficou com o dinheiro)
--   recebido e pago pela CASA .................. nao toca o razao dela
--   recebido pela CASA e pago por ELA .......... credito dela (ela bancou o Uber)
--   recebido e pago por ELA .................... nao toca o razao dela
-- O enum e `casa | modelo`, e "modelo" e a modelo da venda (ou
-- `vendas_registradas.recebido_por_modelo_id`, quando ele existir) — nao ha
-- coluna de modelo aqui de proposito: duas verdades sobre "de quem e" e
-- exatamente o que o ADR-0045 §6 resolveu na venda.
--
-- ONDE ELE NASCE: os tres valores do card (`Valor do transporte`, `Valor
-- antecipado`, `Forma do antecipado`) ficam na FICHA, que e o combinado. Esta
-- tabela e o FATO, e so existe depois que a venda existe. Mesma relacao de
-- `fichas.valor_total` -> `vendas_registradas.valor`.
--
-- UMA POR VENDA (indice unico parcial sobre as vivas): a corrida ida-e-volta e
-- um numero so. Numa festinha em que cada modelo pega o proprio Uber, cada venda
-- tem o seu; numa em que um Uber leva todas, o lancamento fica na venda de quem
-- recebeu/pagou — nunca replicado nas N vendas, senao o custo aparece N vezes.
--
-- `CHECK (valor_antecipado > 0 OR valor_transporte > 0)`: lancamento com os dois
-- zerados e ruido — deslocamento que nao houve nao se registra, se omite.
--
-- Idempotente (enum em DO $$, CREATE TABLE/INDEX IF NOT EXISTS, DROP
-- TRIGGER/POLICY antes de criar). Sem seed: schema puro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py infra/sql/20260820123000_deslocamento_da_venda.sql
--
-- Conferir DEPOIS:
--   \d barravips.deslocamentos_da_venda
-- =============================================================================

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'parte_do_deslocamento_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.parte_do_deslocamento_enum AS ENUM (
      'casa',
      'modelo'
    );
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS barravips.deslocamentos_da_venda (
  id                        uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  venda_id                  uuid NOT NULL
                            REFERENCES barravips.vendas_registradas(id) ON DELETE RESTRICT,
  valor_antecipado          numeric(10,2) NOT NULL DEFAULT 0 CHECK (valor_antecipado >= 0),
  valor_transporte          numeric(10,2) NOT NULL DEFAULT 0 CHECK (valor_transporte >= 0),
  forma_antecipado          text,
  recebedor_do_antecipado   barravips.parte_do_deslocamento_enum NOT NULL DEFAULT 'casa',
  pagador_do_transporte     barravips.parte_do_deslocamento_enum NOT NULL DEFAULT 'casa',
  mensagem_id               uuid
                            REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  anulado_em                timestamptz,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  created_by                uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
  CONSTRAINT deslocamentos_da_venda_forma_antecipado_valida
    CHECK (forma_antecipado IS NULL OR forma_antecipado IN ('pix', 'link')),
  CONSTRAINT deslocamentos_da_venda_tem_algum_valor
    CHECK (valor_antecipado > 0 OR valor_transporte > 0)
);

COMMENT ON TABLE barravips.deslocamentos_da_venda IS
  'Deslocamento como lancamento proprio, ligado a Venda registrada (ADR-0045 §5, ADR-0046 §6). '
  'DOIS valores que nao sao o mesmo numero: o antecipado que o cliente mandou (receita) e o que '
  'o transporte custou (custo). FORA da base de comissao da modelo (ADR-0045 §5) E do '
  'telefonista (ADR-0048 §3): reembolso de custo nao e venda. As duas atribuicoes (quem recebeu, '
  'quem pagou) sao o que decide se isto toca o razao dela.';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.venda_id IS
  'A venda a que este deslocamento pertence. RESTRICT porque e dinheiro. UMA por venda viva '
  '(`deslocamentos_da_venda_por_venda_viva_uniq`): a corrida ida-e-volta e um numero so. Se um '
  'Uber levou N modelos, o lancamento fica na venda de quem recebeu/pagou — replicar nas N '
  'vendas contaria o custo N vezes.';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.valor_antecipado IS
  'Quanto o CLIENTE mandou pelo transporte (receita). Zero quando a casa bancou o Uber sem '
  'cobrar — e um caso real, nao um erro de leitura.';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.valor_transporte IS
  'Quanto o Uber ida-e-volta CUSTOU de fato (custo). A diferenca para `valor_antecipado` e '
  'margem ou prejuizo — e some se o sistema guardar um numero so (ADR-0046 §6).';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.forma_antecipado IS
  'pix | link — como o cliente mandou o antecipado (`Forma do antecipado` do card). Padrao Pix.';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.recebedor_do_antecipado IS
  'casa | modelo — quem recebeu o dinheiro que o cliente mandou pelo transporte. `modelo` = a '
  'modelo da venda (ou `vendas_registradas.recebido_por_modelo_id`, quando preenchido); nao ha '
  'coluna de modelo aqui para nao criar segunda verdade sobre de quem e o lancamento.';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.pagador_do_transporte IS
  'casa | modelo — quem pagou o Uber. Cruzado com `recebedor_do_antecipado` da a regra do razao '
  '(ADR-0045 §5): recebido por ela e pago pela casa -> debito dela; recebido e pago pela casa -> '
  'nao toca o razao dela; recebido pela casa e pago por ela -> credito dela.';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.mensagem_id IS
  'A mensagem do grupo que declarou o deslocamento (ou o card, via a ficha da venda). NULA '
  'quando o lancamento nasceu no painel.';
COMMENT ON COLUMN barravips.deslocamentos_da_venda.anulado_em IS
  'Estado com rastro, nunca DELETE — mesma disciplina de `vendas_registradas.anulada_em`. '
  'Lancamento anulado nao entra no razao e solta o unico por venda.';

CREATE UNIQUE INDEX IF NOT EXISTS deslocamentos_da_venda_por_venda_viva_uniq
  ON barravips.deslocamentos_da_venda (venda_id)
  WHERE anulado_em IS NULL;
CREATE INDEX IF NOT EXISTS deslocamentos_da_venda_mensagem_idx
  ON barravips.deslocamentos_da_venda (mensagem_id)
  WHERE mensagem_id IS NOT NULL;

DROP TRIGGER IF EXISTS set_updated_at_deslocamentos_da_venda ON barravips.deslocamentos_da_venda;
CREATE TRIGGER set_updated_at_deslocamentos_da_venda
  BEFORE UPDATE ON barravips.deslocamentos_da_venda
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.deslocamentos_da_venda ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.deslocamentos_da_venda FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.deslocamentos_da_venda;
CREATE POLICY fernando_full_access
  ON barravips.deslocamentos_da_venda
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.deslocamentos_da_venda TO authenticated;
GRANT ALL PRIVILEGES ON barravips.deslocamentos_da_venda TO service_role;

COMMIT;
