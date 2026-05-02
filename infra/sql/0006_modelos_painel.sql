-- =============================================================================
-- 0006_modelos_painel.sql
-- Campos e realtime exigidos pela Tela 06 - Modelos.
-- =============================================================================

ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS foto_perfil_object_key text NULL,
  ADD COLUMN IF NOT EXISTS coordenacao_chat_id text NULL,
  ADD COLUMN IF NOT EXISTS coordenacao_verificada_em timestamptz NULL;

ALTER TYPE barravips.tipo_evento_enum ADD VALUE IF NOT EXISTS 'modelo_pausada';
ALTER TYPE barravips.tipo_evento_enum ADD VALUE IF NOT EXISTS 'modelo_reativada';

CREATE INDEX IF NOT EXISTS modelos_status_created_idx
  ON barravips.modelos (status, created_at);

CREATE INDEX IF NOT EXISTS modelos_coordenacao_chat_idx
  ON barravips.modelos (coordenacao_chat_id)
  WHERE coordenacao_chat_id IS NOT NULL;

DO $$
DECLARE
  item record;
BEGIN
  FOR item IN
    SELECT * FROM (VALUES
      ('barravips', 'modelos'),
      ('barravips', 'modelo_faq'),
      ('barravips', 'modelo_midia')
    ) AS t(schemaname, tablename)
  LOOP
    IF NOT EXISTS (
      SELECT 1
        FROM pg_publication_tables
       WHERE pubname = 'supabase_realtime'
         AND schemaname = item.schemaname
         AND tablename = item.tablename
    ) THEN
      EXECUTE format(
        'ALTER PUBLICATION supabase_realtime ADD TABLE %I.%I',
        item.schemaname,
        item.tablename
      );
    END IF;
  END LOOP;
END $$;

COMMENT ON COLUMN barravips.modelos.foto_perfil_object_key IS
  'Object key MinIO da foto de perfil da modelo. Nao cria registro em modelo_midia.';
COMMENT ON COLUMN barravips.modelos.coordenacao_chat_id IS
  'JID Evolution do grupo de Coordenacao por modelo.';
COMMENT ON COLUMN barravips.modelos.coordenacao_verificada_em IS
  'Ultima verificacao do grupo de Coordenacao por modelo via Evolution.';
