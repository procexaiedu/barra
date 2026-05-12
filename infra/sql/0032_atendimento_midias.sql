-- =============================================================================
-- 0032_atendimento_midias.sql
-- Anexos internos do atendimento subidos pelo operador no painel.
-- NÃO é Conversa cliente — não vai para Evolution.
-- Distinto de barravips.mensagens (histórico cru WhatsApp) e de
-- barravips.comprovantes_pix (pipeline OCR/vision).
-- =============================================================================

SET search_path TO barravips, public;

CREATE TABLE IF NOT EXISTS barravips.atendimento_midias (
    id                uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
    atendimento_id    uuid NOT NULL REFERENCES barravips.atendimentos(id) ON DELETE CASCADE,
    tipo              text NOT NULL CHECK (tipo IN ('imagem','audio','documento')),
    nome_arquivo      text NOT NULL,
    media_object_key  text NOT NULL,
    created_by        uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS atendimento_midias_atendimento_idx
    ON barravips.atendimento_midias (atendimento_id, created_at DESC);

ALTER TABLE barravips.atendimento_midias ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.atendimento_midias FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.atendimento_midias;
CREATE POLICY fernando_full_access
    ON barravips.atendimento_midias
    AS PERMISSIVE
    FOR ALL
    TO authenticated
    USING ((SELECT barravips.is_fernando()))
    WITH CHECK ((SELECT barravips.is_fernando()));

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.atendimento_midias TO authenticated;
GRANT ALL PRIVILEGES ON barravips.atendimento_midias TO service_role;

COMMENT ON TABLE barravips.atendimento_midias IS
    'Anexos internos do atendimento subidos por Fernando/modelo no painel. NÃO é Conversa cliente — não vai para Evolution. Distinto de mensagens (histórico cru WhatsApp) e de comprovantes_pix (pipeline OCR/vision).';
