-- =============================================================================
-- 0028_modelos_endereco_geo.sql
-- Endereço geocodificado da modelo via Google Places Autocomplete.
-- Mantém `localizacao_operacional` (texto humano usado em busca e prompt da IA).
-- =============================================================================

ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS endereco_formatado text NULL,
  ADD COLUMN IF NOT EXISTS latitude  numeric(10,7) NULL,
  ADD COLUMN IF NOT EXISTS longitude numeric(10,7) NULL,
  ADD COLUMN IF NOT EXISTS place_id  text NULL,
  ADD CONSTRAINT modelos_latlng_coerente
    CHECK ((latitude IS NULL) = (longitude IS NULL))
    NOT VALID;

ALTER TABLE barravips.modelos VALIDATE CONSTRAINT modelos_latlng_coerente;

COMMENT ON COLUMN barravips.modelos.endereco_formatado IS
  'Endereço completo retornado por Google Places (formattedAddress). Usado pela IA para enviar localização no atendimento interno.';
COMMENT ON COLUMN barravips.modelos.latitude IS
  'Latitude do place selecionado. NULL quando endereço é texto livre legado.';
COMMENT ON COLUMN barravips.modelos.longitude IS
  'Longitude do place selecionado. NULL quando endereço é texto livre legado.';
COMMENT ON COLUMN barravips.modelos.place_id IS
  'Google Place ID — referência estável para reconstituir endereço ou solicitar detalhes.';
