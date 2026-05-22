-- =============================================================================
-- 0041_atendimentos_endereco_geo.sql
-- Endereço geocodificado do atendimento via Google Places Autocomplete.
-- Espelha 0028_modelos_endereco_geo.sql. Mantém `endereco`/`bairro` (texto livre
-- legado); atendimentos antigos sem geo continuam válidos (colunas nullable).
-- RLS da tabela já existe (0001) — nada a fazer.
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS endereco_formatado text NULL,
  ADD COLUMN IF NOT EXISTS latitude  numeric(10,7) NULL,
  ADD COLUMN IF NOT EXISTS longitude numeric(10,7) NULL,
  ADD COLUMN IF NOT EXISTS place_id  text NULL;

-- Constraint idempotente (ADD CONSTRAINT não aceita IF NOT EXISTS): só cria se faltar.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'atendimentos_latlng_coerente'
       AND conrelid = 'barravips.atendimentos'::regclass
  ) THEN
    ALTER TABLE barravips.atendimentos
      ADD CONSTRAINT atendimentos_latlng_coerente
        CHECK ((latitude IS NULL) = (longitude IS NULL))
        NOT VALID;
    ALTER TABLE barravips.atendimentos VALIDATE CONSTRAINT atendimentos_latlng_coerente;
  END IF;
END $$;

COMMENT ON COLUMN barravips.atendimentos.endereco_formatado IS
  'Endereço completo retornado por Google Places (formattedAddress). NULL quando endereço é texto livre legado.';
COMMENT ON COLUMN barravips.atendimentos.latitude IS
  'Latitude do place selecionado. NULL quando endereço é texto livre legado.';
COMMENT ON COLUMN barravips.atendimentos.longitude IS
  'Longitude do place selecionado. NULL quando endereço é texto livre legado.';
COMMENT ON COLUMN barravips.atendimentos.place_id IS
  'Google Place ID — referência estável para reconstituir endereço ou solicitar detalhes.';
