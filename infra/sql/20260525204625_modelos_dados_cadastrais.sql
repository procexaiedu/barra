-- 20260525204625_modelos_dados_cadastrais.sql
-- Ficha cadastral pessoal da modelo (ADR 0007).
--
-- Adiciona dados cadastrais (RG, CPF, endereço residencial, cor de pele, cor de
-- cabelo, altura, tamanho do pé) SEM mexer em `tipo_fisico` (ADR 0006): aquele é o
-- balde de venda que alimenta o breakdown do cliente; estes descrevem quem a pessoa
-- é (gestão), são painel-only e nunca alimentam breakdown nem persona da IA.
--
-- PII sensível: rg, cpf, endereço residencial. A RLS de modelos já fecha em Fernando
-- (policy fernando_full_access / is_fernando()); estes campos só saem no detalhe.
-- Slugs ASCII nos enums; rótulos acentuados ficam só no front. NULL = não preenchido.

-- 1) Enums cadastrais (distintos do perfil_fisico_enum do ADR 0006) -----------
DO $$ BEGIN
  CREATE TYPE barravips.cor_pele_enum AS ENUM (
    'branca',
    'parda',
    'negra',
    'asiatica',
    'indigena',
    'outra'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE barravips.cor_pele_enum IS
  'Cor de pele (ficha cadastral da modelo, ADR 0007). Slug ASCII; rótulo acentuado no front. Vocabulário alinhado ao perfil_fisico_enum (negra, asiatica). ''outra'' = preenchida mas nenhuma destas; NULL = não preenchida.';

DO $$ BEGIN
  CREATE TYPE barravips.cor_cabelo_enum AS ENUM (
    'loiro',
    'castanho_claro',
    'castanho_escuro',
    'preto',
    'ruivo',
    'grisalho',
    'colorido',
    'outra'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE barravips.cor_cabelo_enum IS
  'Cor de cabelo (ficha cadastral da modelo, ADR 0007). Slug ASCII; rótulo acentuado no front. ''outra'' = preenchida mas nenhuma destas; NULL = não preenchida.';

-- 2) Colunas cadastrais (todas nullable; sem backfill) ------------------------
ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS rg text,
  ADD COLUMN IF NOT EXISTS cpf text,
  ADD COLUMN IF NOT EXISTS endereco_residencial_formatado text,
  ADD COLUMN IF NOT EXISTS place_id_residencial text,
  ADD COLUMN IF NOT EXISTS cor_pele barravips.cor_pele_enum,
  ADD COLUMN IF NOT EXISTS cor_cabelo barravips.cor_cabelo_enum,
  ADD COLUMN IF NOT EXISTS altura_cm integer
    CONSTRAINT modelos_altura_cm_check CHECK (altura_cm BETWEEN 100 AND 230),
  ADD COLUMN IF NOT EXISTS tamanho_pe integer
    CONSTRAINT modelos_tamanho_pe_check CHECK (tamanho_pe BETWEEN 28 AND 50);

COMMENT ON COLUMN barravips.modelos.rg IS
  'PII sensível. RG da modelo (texto livre — formato varia por estado). Painel-only; não logar.';
COMMENT ON COLUMN barravips.modelos.cpf IS
  'PII sensível. CPF normalizado em 11 dígitos (sem máscara); DV validado no backend. Único por índice parcial. Painel-only; não logar.';
COMMENT ON COLUMN barravips.modelos.endereco_residencial_formatado IS
  'PII sensível. Endereço residencial formatado (Google Places), distinto do operacional. Sem lat/lng (PII mínima). Painel-only.';
COMMENT ON COLUMN barravips.modelos.place_id_residencial IS
  'place_id do Google para reconstituir o endereço residencial se necessário (sem lat/lng).';
COMMENT ON COLUMN barravips.modelos.cor_pele IS
  'Ficha cadastral (ADR 0007). NÃO alimenta o breakdown do cliente (esse usa tipo_fisico).';
COMMENT ON COLUMN barravips.modelos.cor_cabelo IS
  'Ficha cadastral (ADR 0007). NÃO alimenta o breakdown do cliente (esse usa tipo_fisico).';
COMMENT ON COLUMN barravips.modelos.altura_cm IS
  'Altura em centímetros (100–230). Ficha cadastral.';
COMMENT ON COLUMN barravips.modelos.tamanho_pe IS
  'Numeração do pé (BR, 28–50). Ficha cadastral.';

-- 3) Unicidade de CPF: índice parcial (permite múltiplos NULL) ----------------
CREATE UNIQUE INDEX IF NOT EXISTS modelos_cpf_unique
  ON barravips.modelos (cpf)
  WHERE cpf IS NOT NULL;
