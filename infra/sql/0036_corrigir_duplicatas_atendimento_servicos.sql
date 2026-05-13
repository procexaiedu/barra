-- 0036_corrigir_duplicatas_atendimento_servicos.sql
-- Limpeza pos-aplicacao iterativa das migrations 0034/0035: o seed do Bruno
-- recebeu 3 linhas em atendimento_servicos por causa de runs paralelos. Esta
-- migration:
--   1. Remove duplicatas conhecidas do Bruno (mantem 1 canonica: PC 1h R$ 1.200)
--   2. Ajusta duracao_horas do Bruno de 1.5 para 1.0 (alinha com PC 1h cadastrado)
--   3. Adiciona UNIQUE em atendimento_servicos (atendimento_id, programa_id, duracao_id)
--      para impedir que duplicatas voltem a surgir.
--
-- Idempotente: roda 2x sem efeito colateral.

BEGIN;

-- 1. Deletar duplicatas geradas pelo seed iterativo do Bruno
DELETE FROM barravips.atendimento_servicos
 WHERE id IN (
   'c117f691-8c1f-4105-9c7d-625cf5573394',
   '29bf872c-081b-48b5-b71e-39731148fe74'
 );

-- 2. Ajustar duracao_horas do Bruno para casar com Programa Completo 1h
UPDATE barravips.atendimentos
   SET duracao_horas = 1.0
 WHERE id = '91000000-0000-0000-0000-000000000008'
   AND duracao_horas = 1.5;

-- 3. UNIQUE constraint idempotente
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'atendimento_servicos_unico'
       AND conrelid = 'barravips.atendimento_servicos'::regclass
  ) THEN
    ALTER TABLE barravips.atendimento_servicos
      ADD CONSTRAINT atendimento_servicos_unico
      UNIQUE (atendimento_id, programa_id, duracao_id);
  END IF;
END$$;

COMMIT;
