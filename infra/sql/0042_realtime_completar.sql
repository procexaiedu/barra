-- =============================================================================
-- 0042_realtime_completar.sql
-- Auditoria de Supabase Realtime (task Sistema — auditar Supabase Realtime).
--
-- A publication supabase_realtime já cobre todas as tabelas assinadas pelo
-- painel (atendimentos, mensagens, bloqueios, comprovantes_pix, eventos,
-- conversas, clientes, escaladas, modelos, modelo_midia, modelo_servicos,
-- programas, modelo_programas, duracoes). Nenhuma tabela assinada em
-- interface/src/lib/realtime.ts ficou de fora — não há ADD TABLE pendente.
--
-- Gap encontrado: barravips.duracoes (criada em 0010) está na publication e tem
-- RLS habilitada, MAS nunca recebeu policy. Como o Realtime herda RLS, sem
-- policy de SELECT para `authenticated` o evento de Postgres Changes nunca chega
-- ao painel (e qualquer SELECT direto via PostgREST com sessão de Fernando
-- retorna zero linhas). O backend usa service_role (BYPASSRLS), por isso o
-- /v1/duracoes via REST continua funcionando — o buraco é só no canal Realtime
-- e em leitura direta pelo client autenticado.
--
-- Esta migration adiciona a policy faltante de `duracoes`, no mesmo padrão das
-- demais tabelas (fernando_full_access FOR ALL TO authenticated). Idempotente.
--
-- Aplicação:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 0042_realtime_completar.sql
-- =============================================================================

SET search_path TO barravips, public;

-- 1) Policy faltante em duracoes (RLS já habilitada em 0010, sem policy).
--    DROP IF EXISTS antes do CREATE garante idempotência (rodar 2x sem quebrar).
DROP POLICY IF EXISTS fernando_full_access ON barravips.duracoes;
CREATE POLICY fernando_full_access
  ON barravips.duracoes
  AS PERMISSIVE
  FOR ALL
  TO authenticated
  USING ((SELECT barravips.is_fernando()))
  WITH CHECK ((SELECT barravips.is_fernando()));

-- 2) GRANTs explícitos (schema customizado não herda grants automáticos no
--    Supabase). Demais migrations de tabela já fazem isso; duracoes/0010 não fez.
GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.duracoes TO authenticated;
GRANT ALL PRIVILEGES ON barravips.duracoes TO service_role;

-- 3) Garante que duracoes está na publication (já adicionada em 0010, mas
--    deixamos a checagem idempotente caso a 0010 não tenha sido aplicada).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_publication_tables
     WHERE pubname = 'supabase_realtime'
       AND schemaname = 'barravips'
       AND tablename = 'duracoes'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE barravips.duracoes;
  END IF;
END $$;
