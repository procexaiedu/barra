-- 20260528175427_modelos_cadastro_extras.sql
-- Extras do cadastro da modelo (Lane A): medidas (peso/cintura), signo/Instagram/e-mail,
-- nível A/B/C (painel-only) e simplificação das listas de cor de pele/cabelo (ADR 0007).
--
-- Todos os campos novos são nullable e painel-only. A RLS de modelos já fecha em Fernando
-- (policy fernando_full_access / is_fernando()) — colunas novas herdam a RLS da tabela, sem
-- policy adicional. NENHUM destes campos entra na persona/contexto da IA conversacional:
-- o agente lê só colunas explícitas (prepare_context._carregar_bp3 / ferramentas), nunca
-- SELECT * da tabela modelos, então `nivel` e os demais nunca vazam para a IA.

-- 1) Medidas adicionais (Task 8) — altura_cm/tamanho_pe já existem (20260525204625) ---------
ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS peso_kg numeric(5,2)
    CONSTRAINT modelos_peso_kg_check CHECK (peso_kg BETWEEN 30 AND 200),
  ADD COLUMN IF NOT EXISTS cintura_cm integer
    CONSTRAINT modelos_cintura_cm_check CHECK (cintura_cm BETWEEN 40 AND 120);

COMMENT ON COLUMN barravips.modelos.peso_kg IS
  'Peso em quilos (30–200). Ficha cadastral (ADR 0007). Painel-only; não entra na persona.';
COMMENT ON COLUMN barravips.modelos.cintura_cm IS
  'Cintura em centímetros (40–120). Ficha cadastral (ADR 0007). Painel-only; não entra na persona.';

-- 2) Signo, Instagram, e-mail (Task 4) — todos nullable/opcionais -------------------------
ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS signo varchar(20),
  ADD COLUMN IF NOT EXISTS instagram varchar(120),
  ADD COLUMN IF NOT EXISTS email varchar(255);

COMMENT ON COLUMN barravips.modelos.signo IS
  'Signo (seleção manual entre os 12; não há data_nascimento, só idade). Ficha cadastral, painel-only.';
COMMENT ON COLUMN barravips.modelos.instagram IS
  'Instagram da modelo (normalizado para handle ''@usuario'' no backend). Ficha cadastral, painel-only.';
COMMENT ON COLUMN barravips.modelos.email IS
  'E-mail de contato da modelo (não é login — a modelo não acessa o sistema). Ficha cadastral, painel-only.';

-- 3) Nível A/B/C (Task 1) — atribuído na edição, painel-only -----------------------------
-- NUNCA chega à IA conversacional: agregação/classificação interna da operação. NULL = "Sem
-- classificação". Espelha o padrão de tipo_fisico (enum próprio, 1 valor nullable).
DO $$ BEGIN
  CREATE TYPE barravips.nivel_modelo_enum AS ENUM ('A', 'B', 'C');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE barravips.nivel_modelo_enum IS
  'Nível/categoria interna da modelo (A=ouro, B=prata, C=bronze). Painel-only; a IA conversacional NUNCA lê.';

ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS nivel barravips.nivel_modelo_enum;

COMMENT ON COLUMN barravips.modelos.nivel IS
  'Nível/categoria (A/B/C). NULL = sem classificação. Atribuído na edição, painel-only. NUNCA entra na persona/contexto da IA.';

-- 4) Simplificação das listas de cor de pele/cabelo (Task 11) -----------------------------
-- Listas novas: cabelo = loiro/castanho/preto/ruivo/colorido/outro;
--               pele   = branca/parda/negra/asiatica/outra.
-- Postgres não permite remover valor de enum em uso, então criamos enums novos, mapeamos os
-- dados existentes e trocamos a coluna. Idempotente: se a coluna já é do enum novo, os blocos
-- de migração de dados/tipo só rodam quando ainda apontam para o enum antigo.

-- 4.1) Enum novo de cor de cabelo (Loiro, Castanho, Preto, Ruivo, Colorido, Outro) --------
DO $$ BEGIN
  CREATE TYPE barravips.cor_cabelo_enum_v2 AS ENUM (
    'loiro',
    'castanho',
    'preto',
    'ruivo',
    'colorido',
    'outro'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 4.2) Enum novo de cor de pele (Branca, Parda, Negra, Asiática, Outra) -------------------
DO $$ BEGIN
  CREATE TYPE barravips.cor_pele_enum_v2 AS ENUM (
    'branca',
    'parda',
    'negra',
    'asiatica',
    'outra'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 4.3) Troca da coluna cor_cabelo para o enum novo, mapeando valores antigos -------------
--   castanho_claro/castanho_escuro -> castanho ; grisalho -> outro ; 'outra' -> 'outro'.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'barravips' AND table_name = 'modelos'
       AND column_name = 'cor_cabelo' AND udt_name = 'cor_cabelo_enum'
  ) THEN
    ALTER TABLE barravips.modelos
      ALTER COLUMN cor_cabelo TYPE barravips.cor_cabelo_enum_v2
      USING (
        CASE cor_cabelo::text
          WHEN 'castanho_claro'  THEN 'castanho'
          WHEN 'castanho_escuro' THEN 'castanho'
          WHEN 'grisalho'        THEN 'outro'
          WHEN 'outra'           THEN 'outro'
          ELSE cor_cabelo::text
        END::barravips.cor_cabelo_enum_v2
      );
  END IF;
END $$;

-- 4.4) Troca da coluna cor_pele para o enum novo, mapeando valores antigos ---------------
--   indigena -> outra ; demais inalterados.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'barravips' AND table_name = 'modelos'
       AND column_name = 'cor_pele' AND udt_name = 'cor_pele_enum'
  ) THEN
    ALTER TABLE barravips.modelos
      ALTER COLUMN cor_pele TYPE barravips.cor_pele_enum_v2
      USING (
        CASE cor_pele::text
          WHEN 'indigena' THEN 'outra'
          ELSE cor_pele::text
        END::barravips.cor_pele_enum_v2
      );
  END IF;
END $$;

-- 4.5) Aposenta os enums antigos e renomeia os novos para o nome canônico ----------------
DROP TYPE IF EXISTS barravips.cor_cabelo_enum;
DROP TYPE IF EXISTS barravips.cor_pele_enum;

DO $$ BEGIN
  ALTER TYPE barravips.cor_cabelo_enum_v2 RENAME TO cor_cabelo_enum;
EXCEPTION WHEN undefined_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TYPE barravips.cor_pele_enum_v2 RENAME TO cor_pele_enum;
EXCEPTION WHEN undefined_object THEN NULL; END $$;

COMMENT ON TYPE barravips.cor_cabelo_enum IS
  'Cor de cabelo (ficha cadastral da modelo, ADR 0007). Slug ASCII; rótulo acentuado no front. ''outro'' = preenchida mas nenhuma destas; NULL = não preenchida.';
COMMENT ON TYPE barravips.cor_pele_enum IS
  'Cor de pele (ficha cadastral da modelo, ADR 0007). Slug ASCII; rótulo acentuado no front. ''outra'' = preenchida mas nenhuma destas; NULL = não preenchida.';
