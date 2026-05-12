-- =============================================================================
-- 0030_remove_modelo_faq.sql
-- Remove a tabela modelo_faq. A seção de Dúvidas/FAQ foi descontinuada no
-- painel: conhecimento da IA passa a ser gerido pela equipe via prompts
-- versionados (api/src/barra/agente/prompts/faq.md).
--
-- Roda DEPOIS dos seeds 0013-0027 (que ainda fazem INSERT em modelo_faq) e
-- depois das migrations de schema 0028/0029, para preservar a ordem de
-- install limpo. Conflito anterior em 0025 colidia com 0025_seed_caio.sql.
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
