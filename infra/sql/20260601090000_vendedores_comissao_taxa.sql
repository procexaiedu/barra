-- =============================================================================
-- Vendedor, Comissão de vendedor e Taxa de cartão (ADRs 0012 + 0013).
--
-- Cria o ator de domínio Vendedor (não-login), a atribuição híbrida do vendedor
-- ao atendimento (herda da modelo, sobrescrevível), o snapshot da taxa de cartão
-- por atendimento, a config de percentual de comissão por nível e a tabela de
-- pagamentos livres de comissão (espelha financeiro_repasses_pagos do ADR 0011).
--
-- Sem backfill (ADR 0012): atendimentos/modelos pré-existentes nascem com
-- vendedor_id NULL; taxa_cartao_snapshot NULL = sem taxa (mesmo padrão de
-- percentual_repasse_snapshot).
--
-- Tudo idempotente. Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA
-- `make migrate` (aplicaria seeds). Ver memória `migrations_pendentes_prod_selfhosted`
-- e infra/runbooks/ (migrations manuais).
-- =============================================================================

BEGIN;

-- 1. Enum de nível do vendedor (ADR 0012) -------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t
      JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'vendedor_nivel_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.vendedor_nivel_enum AS ENUM (
      'iniciante',
      'intermediario',
      'avancado'
    );
  END IF;
END
$$;


-- 2. Vendedores (entidade de domínio, NÃO login) ------------------------------
-- O vendedor não acessa o painel e nunca é exposto à IA conversacional (ADR 0012).
CREATE TABLE IF NOT EXISTS barravips.vendedores (
  id          uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  nome        text NOT NULL,
  nivel       barravips.vendedor_nivel_enum NOT NULL DEFAULT 'iniciante',
  ativo       boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL
);

COMMENT ON TABLE barravips.vendedores IS
  'Respondente humano do número da modelo (ADR 0012). Não é login; gerido no painel. Nível define a Comissão de vendedor. Nunca exposto à IA.';


-- 3. Config de percentual de comissão por nível (ADR 0012) --------------------
-- Single source of truth da alíquota por nível (ref. 4/5/6%, configurável).
-- A comissão é projetada (não lançada): atendimento Fechado JOIN vendedor JOIN
-- esta tabela. Sem snapshot por atendimento — muda a config, muda a projeção.
CREATE TABLE IF NOT EXISTS barravips.financeiro_comissao_niveis (
  nivel       barravips.vendedor_nivel_enum PRIMARY KEY,
  percentual  numeric(5,2) NOT NULL CHECK (percentual >= 0 AND percentual <= 100),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.financeiro_comissao_niveis IS
  'Percentual de Comissão de vendedor por nível (ADR 0012). Incide sobre o valor do serviço (líquido de taxa de cartão), independente do repasse.';

INSERT INTO barravips.financeiro_comissao_niveis (nivel, percentual) VALUES
  ('iniciante',     4.00),
  ('intermediario', 5.00),
  ('avancado',      6.00)
ON CONFLICT (nivel) DO NOTHING;


-- 4. modelos.vendedor_id (vendedor padrão da modelo, ADR 0012) ----------------
-- Nullable: modelo conduzida pela IA fica sem vendedor padrão (sem comissão).
ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS vendedor_id uuid REFERENCES barravips.vendedores(id) ON DELETE SET NULL;

COMMENT ON COLUMN barravips.modelos.vendedor_id IS
  'Vendedor padrão (ADR 0012). O atendimento herda na criação. NULL = IA conduz (sem comissão).';


-- 5. atendimentos.vendedor_id + taxa_cartao_snapshot --------------------------
-- vendedor_id: herdado da modelo na criação, sobrescrevível por Fernando (ADR 0012).
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS vendedor_id uuid REFERENCES barravips.vendedores(id) ON DELETE SET NULL;

COMMENT ON COLUMN barravips.atendimentos.vendedor_id IS
  'Vendedor que conduziu (ADR 0012). NULL = IA conduziu (sem comissão). Herda de modelos.vendedor_id na criação.';

-- taxa_cartao_snapshot: percentual aplicado; NULL/0 = sem taxa. Mesmo padrão de
-- percentual_repasse_snapshot — preserva o histórico se o default da taxa mudar (ADR 0013).
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS taxa_cartao_snapshot numeric(5,2)
    CHECK (taxa_cartao_snapshot IS NULL OR (taxa_cartao_snapshot >= 0 AND taxa_cartao_snapshot <= 100));

COMMENT ON COLUMN barravips.atendimentos.taxa_cartao_snapshot IS
  'Percentual da Taxa de cartão cobrada (ADR 0013). NULL/0 = sem taxa. Valor do serviço = valor_final / (1 + taxa/100); repasse e comissão incidem sobre o serviço, nunca sobre o bruto inflado.';

CREATE INDEX IF NOT EXISTS atendimentos_vendedor_idx
  ON barravips.atendimentos (vendedor_id)
  WHERE vendedor_id IS NOT NULL;


-- 6. Pagamentos livres de comissão (espelha financeiro_repasses_pagos) --------
CREATE TABLE IF NOT EXISTS barravips.financeiro_comissoes_pagas (
  id                      uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  vendedor_id             uuid NOT NULL REFERENCES barravips.vendedores(id) ON DELETE RESTRICT,
  data_pagamento          date NOT NULL,
  valor                   numeric(10,2) NOT NULL CHECK (valor > 0),
  forma_pagamento         barravips.forma_pagamento_enum NOT NULL,
  observacao              text,
  comprovante_object_key  text NULL,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  created_by              uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL
);

COMMENT ON TABLE barravips.financeiro_comissoes_pagas IS
  'Pagamentos livres de Comissão de vendedor (ADR 0012). Saldo do vendedor = calculado(projeção) − SUM(valor); pode ficar negativo após estorno.';

CREATE INDEX IF NOT EXISTS financeiro_comissoes_vendedor_data_idx
  ON barravips.financeiro_comissoes_pagas (vendedor_id, data_pagamento DESC);

CREATE INDEX IF NOT EXISTS financeiro_comissoes_data_idx
  ON barravips.financeiro_comissoes_pagas (data_pagamento DESC);


-- 7. Triggers set_updated_at (reusa função existente) -------------------------
DROP TRIGGER IF EXISTS set_updated_at_vendedores ON barravips.vendedores;
CREATE TRIGGER set_updated_at_vendedores
  BEFORE UPDATE ON barravips.vendedores
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

DROP TRIGGER IF EXISTS set_updated_at_financeiro_comissao_niveis ON barravips.financeiro_comissao_niveis;
CREATE TRIGGER set_updated_at_financeiro_comissao_niveis
  BEFORE UPDATE ON barravips.financeiro_comissao_niveis
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

DROP TRIGGER IF EXISTS set_updated_at_financeiro_comissoes_pagas ON barravips.financeiro_comissoes_pagas;
CREATE TRIGGER set_updated_at_financeiro_comissoes_pagas
  BEFORE UPDATE ON barravips.financeiro_comissoes_pagas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();


-- 8. RLS habilitada + FORCE + policy fernando_full_access ---------------------
-- Mesmo padrão das tabelas financeiras (ADR 0011): painel-only, só Fernando/sócia.
ALTER TABLE barravips.vendedores                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_comissao_niveis   ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_comissoes_pagas   ENABLE ROW LEVEL SECURITY;

ALTER TABLE barravips.vendedores                   FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_comissao_niveis   FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_comissoes_pagas   FORCE ROW LEVEL SECURITY;

DO $$
DECLARE
  t text;
BEGIN
  FOR t IN
    SELECT unnest(ARRAY[
      'vendedores',
      'financeiro_comissao_niveis',
      'financeiro_comissoes_pagas'
    ])
  LOOP
    EXECUTE format($f$
      DROP POLICY IF EXISTS fernando_full_access ON barravips.%I;
      CREATE POLICY fernando_full_access
        ON barravips.%I
        AS PERMISSIVE
        FOR ALL
        TO authenticated
        USING ((SELECT barravips.is_fernando()))
        WITH CHECK ((SELECT barravips.is_fernando()));
    $f$, t, t);
  END LOOP;
END
$$;

COMMIT;
