CREATE TABLE IF NOT EXISTS barravips.modelo_servicos (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id       uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  nome            text NOT NULL CHECK (length(trim(nome)) > 0),
  duracao_horas   numeric(4,2) NOT NULL CHECK (duracao_horas > 0),
  preco           numeric(10,2) NOT NULL CHECK (preco >= 0),
  ativo           boolean NOT NULL DEFAULT true,
  ordem           smallint NOT NULL DEFAULT 0,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT modelo_servicos_nome_duracao_unique UNIQUE (modelo_id, nome, duracao_horas)
);

CREATE INDEX IF NOT EXISTS modelo_servicos_modelo_idx
  ON barravips.modelo_servicos (modelo_id, ordem, duracao_horas);

DROP TRIGGER IF EXISTS set_updated_at_modelo_servicos ON barravips.modelo_servicos;
CREATE TRIGGER set_updated_at_modelo_servicos
  BEFORE UPDATE ON barravips.modelo_servicos
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

INSERT INTO barravips.modelo_servicos (modelo_id, nome, duracao_horas, preco, ordem)
SELECT id, 'Programa', 1, valor_padrao, 0
  FROM barravips.modelos
 WHERE valor_padrao > 0
ON CONFLICT DO NOTHING;

ALTER TABLE barravips.modelo_servicos ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_servicos FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.modelo_servicos;
CREATE POLICY fernando_full_access
  ON barravips.modelo_servicos
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.modelo_servicos TO authenticated;
GRANT ALL PRIVILEGES ON barravips.modelo_servicos TO service_role;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_publication_tables
     WHERE pubname = 'supabase_realtime'
       AND schemaname = 'barravips'
       AND tablename = 'modelo_servicos'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE barravips.modelo_servicos;
  END IF;
END $$;
