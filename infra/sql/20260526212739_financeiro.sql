-- =============================================================================
-- Módulo Financeiro (ADR 0011).
--
-- Despesas (pontuais + recorrentes via template) e repasses pagos à modelo.
-- Receita NÃO ganha tabela própria: é projeção sobre `atendimentos` filtrada
-- por `eventos.tipo='fechado_registrado'` (mesma fonte do dashboard).
--
-- Tudo idempotente. Aplicar manualmente em prod self-hosted via psycopg.
-- =============================================================================

BEGIN;

-- 1. Enum de categoria ---------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t
      JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'categoria_despesa_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.categoria_despesa_enum AS ENUM (
      'anuncios',
      'software',
      'infraestrutura',
      'juridico',
      'taxas',
      'deslocamento',
      'pessoal',
      'outro'
    );
  END IF;
END
$$;


-- 2. Templates de despesa recorrente ------------------------------------------
CREATE TABLE IF NOT EXISTS barravips.financeiro_despesas_recorrentes (
  id           uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  categoria    barravips.categoria_despesa_enum NOT NULL,
  valor        numeric(10,2) NOT NULL CHECK (valor > 0),
  descricao    text NOT NULL,
  -- 28 evita pegadinha de fevereiro: despesa do "dia 30" cai em mês sem dia 30.
  dia_do_mes   smallint NOT NULL CHECK (dia_do_mes BETWEEN 1 AND 28),
  -- 1º do mês obrigatório: alinha com `competencia_mes` em `financeiro_despesas`.
  ativo_desde  date NOT NULL CHECK (date_trunc('month', ativo_desde) = ativo_desde),
  inativo_em   date NULL CHECK (inativo_em IS NULL OR inativo_em >= ativo_desde),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  created_by   uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL
);

COMMENT ON TABLE barravips.financeiro_despesas_recorrentes IS
  'Templates de despesa fixa mensal (ADR 0011). Projetados sob demanda em `financeiro_despesas` quando Fernando edita uma instância.';


-- 3. Lançamentos de despesa (pontuais + materializações) ----------------------
CREATE TABLE IF NOT EXISTS barravips.financeiro_despesas (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  categoria       barravips.categoria_despesa_enum NOT NULL,
  valor           numeric(10,2) NOT NULL CHECK (valor > 0),
  data            date NOT NULL,
  descricao       text,
  -- Quando vem de um template materializado, ambos preenchidos.
  -- Quando pontual, ambos NULL. CHECK garante consistência.
  recorrente_id   uuid NULL REFERENCES barravips.financeiro_despesas_recorrentes(id) ON DELETE RESTRICT,
  competencia_mes date NULL CHECK (competencia_mes IS NULL OR date_trunc('month', competencia_mes) = competencia_mes),
  CONSTRAINT financeiro_despesas_origem_consistente
    CHECK ((recorrente_id IS NULL) = (competencia_mes IS NULL)),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  created_by      uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL
);

COMMENT ON TABLE barravips.financeiro_despesas IS
  'Despesas lançadas pelo painel (ADR 0011). recorrente_id+competencia_mes NULL = pontual; preenchidos = materialização de template.';

-- Índice único parcial: um template só pode ter UMA materialização por mês.
-- (NULLs nunca conflitam em UNIQUE padrão; o parcial torna isso explícito.)
CREATE UNIQUE INDEX IF NOT EXISTS financeiro_despesas_recorrente_unico
  ON barravips.financeiro_despesas (recorrente_id, competencia_mes)
  WHERE recorrente_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS financeiro_despesas_data_idx
  ON barravips.financeiro_despesas (data DESC);

CREATE INDEX IF NOT EXISTS financeiro_despesas_categoria_data_idx
  ON barravips.financeiro_despesas (categoria, data DESC);


-- 4. Pagamentos de repasse à modelo -------------------------------------------
CREATE TABLE IF NOT EXISTS barravips.financeiro_repasses_pagos (
  id                      uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id               uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  data_pagamento          date NOT NULL,
  valor                   numeric(10,2) NOT NULL CHECK (valor > 0),
  forma_pagamento         barravips.forma_pagamento_enum NOT NULL,
  observacao              text,
  -- object_key no bucket `barra-media` (prefix `repasses/`). Acesso autenticado.
  comprovante_object_key  text NULL,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  created_by              uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL
);

COMMENT ON TABLE barravips.financeiro_repasses_pagos IS
  'Pagamentos livres de repasse à modelo (ADR 0011). Não vinculados 1:1 a atendimento; saldo = calculado(projecao) − SUM(valor).';

CREATE INDEX IF NOT EXISTS financeiro_repasses_modelo_data_idx
  ON barravips.financeiro_repasses_pagos (modelo_id, data_pagamento DESC);

CREATE INDEX IF NOT EXISTS financeiro_repasses_data_idx
  ON barravips.financeiro_repasses_pagos (data_pagamento DESC);


-- 5. Triggers set_updated_at (reusa função existente) -------------------------
DROP TRIGGER IF EXISTS set_updated_at_financeiro_despesas ON barravips.financeiro_despesas;
CREATE TRIGGER set_updated_at_financeiro_despesas
  BEFORE UPDATE ON barravips.financeiro_despesas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

DROP TRIGGER IF EXISTS set_updated_at_financeiro_despesas_recorrentes ON barravips.financeiro_despesas_recorrentes;
CREATE TRIGGER set_updated_at_financeiro_despesas_recorrentes
  BEFORE UPDATE ON barravips.financeiro_despesas_recorrentes
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

DROP TRIGGER IF EXISTS set_updated_at_financeiro_repasses_pagos ON barravips.financeiro_repasses_pagos;
CREATE TRIGGER set_updated_at_financeiro_repasses_pagos
  BEFORE UPDATE ON barravips.financeiro_repasses_pagos
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();


-- 6. RLS habilitada + FORCE + policy fernando_full_access ---------------------
ALTER TABLE barravips.financeiro_despesas             ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_despesas_recorrentes ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_repasses_pagos       ENABLE ROW LEVEL SECURITY;

ALTER TABLE barravips.financeiro_despesas             FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_despesas_recorrentes FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.financeiro_repasses_pagos       FORCE ROW LEVEL SECURITY;

DO $$
DECLARE
  t text;
BEGIN
  FOR t IN
    SELECT unnest(ARRAY[
      'financeiro_despesas',
      'financeiro_despesas_recorrentes',
      'financeiro_repasses_pagos'
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
