-- Disponibilidade da modelo (ADR 0005; CONTEXT.md "Disponibilidade").
-- Regras compostas: cada linha = (intervalo de datas) x (dia da semana) x (janela horária).
-- Disponibilidade efetiva = UNIÃO das regras; modelo sem nenhuma regra é reservável SEMPRE
-- (preserva o fluxo atual). A janela pode CRUZAR a meia-noite (hora_fim <= hora_inicio):
-- pertence ao dia da semana do início e transborda para o dia civil seguinte — por isso
-- NÃO há CHECK hora_inicio < hora_fim. dia_semana segue EXTRACT(DOW): 0=domingo .. 6=sábado.

CREATE TABLE IF NOT EXISTS barravips.modelo_disponibilidade (
  id            uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id     uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  data_inicio   date NOT NULL,
  data_fim      date,                      -- NULL = período aberto/indefinido
  dia_semana    smallint NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
  hora_inicio   time NOT NULL,
  hora_fim      time NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT modelo_disponibilidade_periodo_valido
    CHECK (data_fim IS NULL OR data_fim >= data_inicio)
);

CREATE INDEX IF NOT EXISTS modelo_disponibilidade_modelo_idx
  ON barravips.modelo_disponibilidade (modelo_id, dia_semana, data_inicio);

DROP TRIGGER IF EXISTS set_updated_at_modelo_disponibilidade ON barravips.modelo_disponibilidade;
CREATE TRIGGER set_updated_at_modelo_disponibilidade
  BEFORE UPDATE ON barravips.modelo_disponibilidade
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.modelo_disponibilidade ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_disponibilidade FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.modelo_disponibilidade;
CREATE POLICY fernando_full_access
  ON barravips.modelo_disponibilidade
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.modelo_disponibilidade TO authenticated;
GRANT ALL PRIVILEGES ON barravips.modelo_disponibilidade TO service_role;
