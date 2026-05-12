-- task #56e06228: converte atendimentos.tipo_local para text
-- permite lista dinamica de valores no painel (combobox com criar novo)

BEGIN;

ALTER TABLE barravips.atendimentos
    ALTER COLUMN tipo_local TYPE text
    USING tipo_local::text;

-- Verifica se o enum ainda e usado em outra coluna antes de dropar.
-- Consulta via pg_type para que a 2a execucao (apos drop) nao quebre.
DO $$
DECLARE
    tipo_oid oid;
    cnt int;
BEGIN
    SELECT t.oid INTO tipo_oid
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'barravips' AND t.typname = 'tipo_local_enum';

    IF tipo_oid IS NULL THEN
        RETURN;
    END IF;

    SELECT count(*) INTO cnt
    FROM pg_attribute
    WHERE atttypid = tipo_oid
      AND attisdropped = false;

    IF cnt = 0 THEN
        EXECUTE 'DROP TYPE barravips.tipo_local_enum';
    END IF;
END $$;

COMMIT;
