-- Introduz duracoes como entidade global reutilizável.
-- modelo_programas passa a ter (modelo_id, programa_id, duracao_id) como chave composta.

CREATE TABLE barravips.duracoes (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nome       text NOT NULL CHECK (length(trim(nome)) > 0),
    ordem      int  NOT NULL DEFAULT 0,
    created_at timestamptz DEFAULT now()
);

INSERT INTO barravips.duracoes (nome, ordem) VALUES
    ('1 hora',   1),
    ('2 horas',  2),
    ('3 horas',  3),
    ('Pernoite', 4);

-- Recria modelo_programas com a nova chave composta
ALTER TABLE barravips.modelo_programas DROP CONSTRAINT modelo_programas_pkey;
ALTER TABLE barravips.modelo_programas
    ADD COLUMN duracao_id uuid REFERENCES barravips.duracoes(id) ON DELETE RESTRICT;

-- Replica identity necessária para DELETE em tabela publicada no Realtime
ALTER TABLE barravips.modelo_programas REPLICA IDENTITY FULL;

-- MVP: sem dados de produção, limpa vínculos antigos
DELETE FROM barravips.modelo_programas;

ALTER TABLE barravips.modelo_programas ALTER COLUMN duracao_id SET NOT NULL;
ALTER TABLE barravips.modelo_programas
    ADD PRIMARY KEY (modelo_id, programa_id, duracao_id);

-- Atualiza seed de programas para nomes de serviços
TRUNCATE barravips.programas CASCADE;
INSERT INTO barravips.programas (nome, categoria) VALUES
    ('Padrão',  NULL),
    ('Casal',   NULL),
    ('Jantar',  NULL),
    ('Viagem',  NULL),
    ('Social',  NULL);

ALTER TABLE barravips.duracoes ENABLE ROW LEVEL SECURITY;
ALTER PUBLICATION supabase_realtime ADD TABLE barravips.duracoes;
