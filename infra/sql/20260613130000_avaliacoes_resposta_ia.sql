-- Avaliacao humana das respostas do agente (página /observabilidade): Fernando/sócia visualizam
-- cada resposta da IA (mensagens.direcao='ia') no contexto da mensagem do cliente e a avaliam.
-- Vira o GROUND-TRUTH humano que faltava ao eval (camada 3 / revisão humana, docs 08c §1):
-- calibra os juízes da Camada 2 (shadow head-to-head) e mede "a IA substitui o Vendedor".
--
-- Granularidade: UMA avaliacao por RESPOSTA da IA (mensagem_id UNIQUE) — upsert ao reavaliar.
-- A garantia de que mensagem_id aponta para uma resposta da IA (direcao='ia') é do service/repo
-- (sem CHECK cross-table no Postgres).

BEGIN;

-- Enum do veredito (idempotente).
DO $$ BEGIN
  CREATE TYPE barravips.veredito_avaliacao_enum AS ENUM ('bom', 'ruim');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS barravips.avaliacoes_resposta_ia (
  id            uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  mensagem_id   uuid NOT NULL REFERENCES barravips.mensagens(id) ON DELETE CASCADE,
  veredito      barravips.veredito_avaliacao_enum NOT NULL,  -- o Vendedor faria assim? bom|ruim
  nota          integer CHECK (nota IS NULL OR (nota >= 1 AND nota <= 5)),  -- 1-5, opcional
  comentario    text,
  avaliado_por  uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
  avaliado_em   timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT avaliacoes_resposta_ia_mensagem_unica UNIQUE (mensagem_id)
);

COMMENT ON TABLE barravips.avaliacoes_resposta_ia IS
  'Avaliacao humana (Fernando) de cada resposta da IA, da página /observabilidade. Ground-truth de calibracao do eval (camada 3). Uma por mensagem da IA (upsert).';

CREATE INDEX IF NOT EXISTS idx_avaliacoes_resposta_ia_avaliado_em
  ON barravips.avaliacoes_resposta_ia (avaliado_em DESC);

-- RLS: padrão do schema (ENABLE + FORCE + policy fernando_full_access; service_role bypassa).
ALTER TABLE barravips.avaliacoes_resposta_ia ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.avaliacoes_resposta_ia FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.avaliacoes_resposta_ia;
CREATE POLICY fernando_full_access
  ON barravips.avaliacoes_resposta_ia
  AS PERMISSIVE
  FOR ALL
  TO authenticated
  USING ((SELECT barravips.is_fernando()))
  WITH CHECK ((SELECT barravips.is_fernando()));

GRANT USAGE ON SCHEMA barravips TO service_role, authenticated;
GRANT ALL ON barravips.avaliacoes_resposta_ia TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.avaliacoes_resposta_ia TO authenticated;

COMMIT;
