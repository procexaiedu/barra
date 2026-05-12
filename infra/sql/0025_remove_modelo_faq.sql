-- =============================================================================
-- 0021_remove_modelo_faq.sql
-- Remove a tabela modelo_faq. A seção de Dúvidas/FAQ foi descontinuada no
-- painel: conhecimento da IA passa a ser gerido pela equipe via prompts
-- versionados (api/src/barra/agente/prompts/faq.md).
-- =============================================================================

-- 1) Sair da publication antes do DROP (idempotente).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM pg_publication_tables
     WHERE pubname = 'supabase_realtime'
       AND schemaname = 'barravips'
       AND tablename = 'modelo_faq'
  ) THEN
    EXECUTE 'ALTER PUBLICATION supabase_realtime DROP TABLE barravips.modelo_faq';
  END IF;
END $$;

-- 2) DROP CASCADE cobre índices (modelo_faq_modelo_idx, modelo_faq_tags_gin_idx),
--    trigger (set_updated_at_modelo_faq), policy RLS (fernando_full_access) e FK.
DROP TABLE IF EXISTS barravips.modelo_faq CASCADE;
