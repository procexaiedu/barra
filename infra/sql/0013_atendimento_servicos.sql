-- 0013: serviços fechados por atendimento
-- Registra quais programas foram contratados em cada atendimento,
-- com snapshot de preço no momento do fechamento.

CREATE TABLE barravips.atendimento_servicos (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    atendimento_id uuid NOT NULL REFERENCES barravips.atendimentos(id) ON DELETE CASCADE,
    programa_id    uuid NOT NULL REFERENCES barravips.programas(id) ON DELETE RESTRICT,
    duracao_id     uuid NOT NULL REFERENCES barravips.duracoes(id) ON DELETE RESTRICT,
    preco_snapshot numeric(10,2) NOT NULL CHECK (preco_snapshot >= 0),
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ats_atendimento_idx ON barravips.atendimento_servicos (atendimento_id);

ALTER TABLE barravips.atendimento_servicos ENABLE ROW LEVEL SECURITY;

CREATE POLICY fernando_full_access ON barravips.atendimento_servicos
    FOR ALL TO authenticated USING (true) WITH CHECK (true);
