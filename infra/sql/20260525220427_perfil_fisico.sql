-- 20260525220427_perfil_fisico.sql
-- Perfil físico preferido do cliente (ADR 0006).
--
-- Eixo único, lista plana. A MODELO recebe 1 valor (tipo_fisico); o CLIENTE
-- declara N (perfis_preferidos). Modelos existentes nascem NULL (sem backfill);
-- clientes nascem com array vazio (= sem preferência). Slugs ASCII; rótulos
-- acentuados ficam só no front. 'outra' = classificada mas nenhuma destas
-- (distinto de NULL = ainda não classificada).

-- 1) Enum canônico ------------------------------------------------------
DO $$ BEGIN
  CREATE TYPE barravips.perfil_fisico_enum AS ENUM (
    'loira',
    'morena',
    'ruiva',
    'negra',
    'asiatica',
    'outra'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE barravips.perfil_fisico_enum IS
  'Tipo físico (eixo único). Slug ASCII; rótulo acentuado no front. ''outra'' = classificada mas nenhuma destas; NULL na modelo = não classificada.';

-- 2) Classificação da modelo (1 valor, nullable) ------------------------
ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS tipo_fisico barravips.perfil_fisico_enum;

COMMENT ON COLUMN barravips.modelos.tipo_fisico IS
  'Tipo físico da modelo (1 valor). NULL = ainda não classificada; alimenta o breakdown calculado do cliente.';

-- 3) Preferência declarada do cliente (N valores, default vazio) --------
ALTER TABLE barravips.clientes
  ADD COLUMN IF NOT EXISTS perfis_preferidos barravips.perfil_fisico_enum[]
    NOT NULL DEFAULT '{}'::barravips.perfil_fisico_enum[];

COMMENT ON COLUMN barravips.clientes.perfis_preferidos IS
  'Perfil físico preferido DECLARADO (cross-modelo, painel-only). Array vazio = sem preferência. A IA conversacional por modelo nunca lê nem escreve (ADR 0006).';

-- 4) Índice GIN para o filtro por overlap (perfis_preferidos && ARRAY) ---
CREATE INDEX IF NOT EXISTS clientes_perfis_preferidos_idx
  ON barravips.clientes USING GIN (perfis_preferidos);
