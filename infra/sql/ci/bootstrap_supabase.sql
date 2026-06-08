-- =============================================================================
-- infra/sql/ci/bootstrap_supabase.sql  (F0.1)
-- Stub dos objetos que o Supabase já provê em prod mas um Postgres limpo NÃO tem,
-- p/ que `infra/sql/*.sql` aplique inteiro num service container `postgres:NN` na CI.
--
-- NÃO faz parte da sequência de migrations: vive em infra/sql/ci/ (fora do glob
-- `infra/sql/*.sql` do `make migrate` e do drift-check). Aplicado SÓ na CI/dev,
-- antes do `make migrate`. NUNCA rodar contra o banco de produção (lá esses
-- objetos são geridos pelo Supabase / GoTrue).
--
-- Cobre exatamente o que as migrations referenciam:
--   - roles anon / authenticated / service_role  (GRANTs e policies em 0001..)
--   - schema auth + auth.users + auth.uid()       (FK e trigger de 0001)
--   - publication supabase_realtime               (ALTER PUBLICATION ADD TABLE)
-- Idempotente: pode rodar mais de uma vez.
-- =============================================================================

-- Roles do Supabase (NOLOGIN — só alvos de GRANT/policy, ninguém conecta como eles).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
  END IF;
END
$$;

-- Schema auth + tabela mínima auth.users (o GoTrue cria a real em prod).
-- 0001 cria FK barravips.usuarios.id -> auth.users(id) e um trigger AFTER INSERT
-- que lê NEW.email e NEW.raw_user_meta_data.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
  id                 uuid PRIMARY KEY,
  email              text,
  raw_user_meta_data jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- auth.uid() do JWT (claim sub); na CI roda como superuser/sem JWT -> NULL.
CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

-- Publication do Realtime: criada vazia p/ os `ALTER PUBLICATION ... ADD TABLE`.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
    CREATE PUBLICATION supabase_realtime;
  END IF;
END
$$;
