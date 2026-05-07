-- Renomeia bucket de 'media' para 'barra-media' nos registros existentes e no default da coluna.
UPDATE barravips.modelo_midia SET bucket = 'barra-media' WHERE bucket = 'media';

ALTER TABLE barravips.modelo_midia
    ALTER COLUMN bucket SET DEFAULT 'barra-media';

COMMENT ON TABLE barravips.modelo_midia IS
    'Mídia pré-aprovada armazenada em MinIO (bucket "barra-media"). Mínimo 10 por modelo antes do piloto.';
