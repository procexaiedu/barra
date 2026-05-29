-- =============================================================================
-- Fetiches no campo de serviços (revisão do ADR 0014).
--
-- Fetiche deixa de ser flag pura sim/não e passa a ser um EXTRA precificável no
-- campo de serviços da modelo, sem duração e com PREÇO OPCIONAL:
--   - modelo_fetiches.preco NULL      => incluso (a modelo faz, sem custo extra)
--   - modelo_fetiches.preco preenchido => extra pago (a IA cota "+R$X")
--   - ausência de vínculo             => não faz (recusa aberta pela IA)
--
-- Catálogo é GLOBAL e curado por Fernando (espelha programas). A composição do
-- atendimento (atendimento_fetiches) guarda snapshot do preço no fechamento,
-- também nullable (fetiche incluso). O Valor final continua digitado manualmente
-- pela modelo — fetiche não auto-soma, entra só na decomposição/breakdown.
--
-- Tudo idempotente. Aplicar manualmente em prod self-hosted via psycopg (nunca
-- `make migrate` no prod self-hosted — aplicaria seeds).
-- =============================================================================

BEGIN;

-- 1. Catálogo global de fetiches ----------------------------------------------
CREATE TABLE IF NOT EXISTS barravips.fetiches (
  id         uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  nome       text NOT NULL CHECK (length(btrim(nome)) > 0),
  ordem      int  NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.fetiches IS
  'Catálogo global de fetiches (revisão ADR 0014). Curado por Fernando, como programas. Sem duração e sem preço próprio — o preço vive por modelo em modelo_fetiches.';


-- 2. Vínculo modelo↔fetiche (preço opcional) ----------------------------------
CREATE TABLE IF NOT EXISTS barravips.modelo_fetiches (
  modelo_id  uuid NOT NULL REFERENCES barravips.modelos(id)  ON DELETE CASCADE,
  fetiche_id uuid NOT NULL REFERENCES barravips.fetiches(id) ON DELETE RESTRICT,
  -- NULL = incluso (faz, sem custo); preenchido = extra pago. Presença = faz.
  preco      numeric(10,2) CHECK (preco IS NULL OR preco >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (modelo_id, fetiche_id)
);
-- REPLICA IDENTITY FULL: necessário para DELETE em tabela publicada no Realtime
-- (mesmo motivo de modelo_programas, migration 0010).
ALTER TABLE barravips.modelo_fetiches REPLICA IDENTITY FULL;

COMMENT ON TABLE barravips.modelo_fetiches IS
  'Fetiches que a modelo faz, com preço opcional (NULL = incluso). Ausência de linha = não faz. É "coisa dela": entra no contexto da IA por modelo (ADR 0014 revisado).';


-- 3. Composição do atendimento (snapshot de preço) ----------------------------
CREATE TABLE IF NOT EXISTS barravips.atendimento_fetiches (
  id             uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  atendimento_id uuid NOT NULL REFERENCES barravips.atendimentos(id) ON DELETE CASCADE,
  fetiche_id     uuid NOT NULL REFERENCES barravips.fetiches(id)     ON DELETE RESTRICT,
  -- NULL = incluso (snapshot de modelo_fetiches.preco no momento do registro).
  preco_snapshot numeric(10,2) CHECK (preco_snapshot IS NULL OR preco_snapshot >= 0),
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (atendimento_id, fetiche_id)
);

CREATE INDEX IF NOT EXISTS atf_atendimento_idx ON barravips.atendimento_fetiches (atendimento_id);

COMMENT ON TABLE barravips.atendimento_fetiches IS
  'Fetiches registrados num atendimento, com snapshot de preço (nullable = incluso). Composição/breakdown — o Valor final segue digitado manualmente, não é auto-somado.';


-- 4. RLS: ENABLE + FORCE + policy fernando_full_access ------------------------
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['fetiches', 'modelo_fetiches', 'atendimento_fetiches'] LOOP
    EXECUTE format('ALTER TABLE barravips.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE barravips.%I FORCE  ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS fernando_full_access ON barravips.%I', t);
    EXECUTE format(
      'CREATE POLICY fernando_full_access ON barravips.%I '
      'AS PERMISSIVE FOR ALL TO authenticated '
      'USING ((SELECT barravips.is_fernando())) '
      'WITH CHECK ((SELECT barravips.is_fernando()))', t);
    -- GRANTs explícitos (schema customizado não herda grants no Supabase).
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.%I TO authenticated', t);
    EXECUTE format('GRANT ALL PRIVILEGES ON barravips.%I TO service_role', t);
  END LOOP;
END
$$;


-- 5. Realtime: catálogo e vínculo na publication (paridade com programas) ------
--    atendimento_fetiches fica fora (composição não é assinada, igual a
--    atendimento_servicos).
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['fetiches', 'modelo_fetiches'] LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_publication_tables
       WHERE pubname = 'supabase_realtime'
         AND schemaname = 'barravips'
         AND tablename = t
    ) THEN
      EXECUTE format('ALTER PUBLICATION supabase_realtime ADD TABLE barravips.%I', t);
    END IF;
  END LOOP;
END
$$;

COMMIT;
