-- 0008: Catálogo global de programas e vínculos por modelo
-- Substitui a arquitetura de modelo_servicos (deprecada, mantida intocada)

CREATE TABLE barravips.programas (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nome text NOT NULL CHECK (length(trim(nome)) > 0),
  duracao_horas numeric(4,2) NOT NULL CHECK (duracao_horas > 0),
  descricao text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE barravips.modelo_programas (
  modelo_id uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  programa_id uuid NOT NULL REFERENCES barravips.programas(id) ON DELETE RESTRICT,
  preco numeric(10,2) NOT NULL CHECK (preco >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (modelo_id, programa_id)
);

CREATE INDEX modelo_programas_modelo_idx ON barravips.modelo_programas (modelo_id);

CREATE OR REPLACE FUNCTION barravips.set_updated_at_programas()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

CREATE TRIGGER set_updated_at_programas
  BEFORE UPDATE ON barravips.programas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at_programas();

CREATE OR REPLACE FUNCTION barravips.set_updated_at_modelo_programas()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

CREATE TRIGGER set_updated_at_modelo_programas
  BEFORE UPDATE ON barravips.modelo_programas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at_modelo_programas();

-- RLS
ALTER TABLE barravips.programas ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_programas ENABLE ROW LEVEL SECURITY;

CREATE POLICY fernando_full_access ON barravips.programas
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY fernando_full_access ON barravips.modelo_programas
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE barravips.programas;
ALTER PUBLICATION supabase_realtime ADD TABLE barravips.modelo_programas;

-- Seed com programas padrão da agência
INSERT INTO barravips.programas (nome, duracao_horas, descricao) VALUES
  ('1 hora',          1.00, NULL),
  ('2 horas',         2.00, NULL),
  ('3 horas',         3.00, NULL),
  ('Pernoite',       12.00, 'Pernoite completo'),
  ('Jantar',          3.00, 'Acompanhamento para jantar'),
  ('Viagem',         24.00, 'Viagem nacional ou internacional'),
  ('Programa social', 4.00, 'Evento social, festa ou confraternização');
