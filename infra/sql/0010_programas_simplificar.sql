-- Remove campos que não agregam valor operacional dos programas.
-- O nome já descreve a duração/serviço; descrição nunca foi usada.
ALTER TABLE barravips.programas DROP COLUMN IF EXISTS duracao_horas;
ALTER TABLE barravips.programas DROP COLUMN IF EXISTS descricao;
