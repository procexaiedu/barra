-- 0039_escalada_tipo_enum.sql
-- Substitui a coluna text livre escaladas.motivo por um enum canônico
-- (tipo) + texto livre opcional (observacao). Mantém escaladas.motivo
-- intacto para retrocompatibilidade de leitura, mas todas as agregações
-- do dashboard passam a usar escaladas.tipo.
--
-- Backfill heurístico: classifica registros existentes por prefixo do
-- texto antigo. Casos não reconhecidos viram 'outro' e preservam o
-- texto original em observacao para investigação manual.

-- 1) Enum canônico ------------------------------------------------------
DO $$ BEGIN
  CREATE TYPE barravips.tipo_escalada_enum AS ENUM (
    'pix_validado',
    'pix_duvidoso',
    'foto_portaria',
    'aviso_saida',
    'fora_de_oferta',
    'comportamento_atipico',
    'indisponibilidade',
    'outro'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE barravips.tipo_escalada_enum IS
  'Taxonomia fechada de motivos de escalada (substitui texto livre em escaladas.motivo). Texto descritivo segue em escaladas.observacao.';

-- 2) Colunas novas ------------------------------------------------------
ALTER TABLE barravips.escaladas
  ADD COLUMN IF NOT EXISTS tipo barravips.tipo_escalada_enum,
  ADD COLUMN IF NOT EXISTS observacao text;

-- 3) Backfill heurístico ------------------------------------------------
UPDATE barravips.escaladas
   SET tipo = CASE
     WHEN motivo ILIKE 'Pix de deslocamento%'
       OR motivo ILIKE '%pix validado%'                                            THEN 'pix_validado'::barravips.tipo_escalada_enum
     WHEN motivo ILIKE 'Pix duvidoso%'
       OR motivo ILIKE '%aguardando decisao%'
       OR motivo ILIKE '%pix_em_revisao%'                                          THEN 'pix_duvidoso'::barravips.tipo_escalada_enum
     WHEN motivo ILIKE 'Cliente chegou%'
       OR motivo ILIKE '%foto de portaria%'                                        THEN 'foto_portaria'::barravips.tipo_escalada_enum
     WHEN motivo ILIKE 'Aviso de saida%'
       OR motivo ILIKE 'Aviso de saída%'
       OR motivo ILIKE 'Cliente saiu%'                                             THEN 'aviso_saida'::barravips.tipo_escalada_enum
     WHEN motivo ILIKE '%fora_de_oferta%'
       OR motivo ILIKE '%abaixo da tabela%'
       OR motivo ILIKE '%desconto%'                                                THEN 'fora_de_oferta'::barravips.tipo_escalada_enum
     WHEN motivo ILIKE '%foto ao vivo%'
       OR motivo ILIKE '%comportamento incomum%'
       OR motivo ILIKE '%comportamento%'                                           THEN 'comportamento_atipico'::barravips.tipo_escalada_enum
     WHEN motivo ILIKE '%indisponibilidade%'
       OR motivo ILIKE '%sem agenda%'
       OR motivo ILIKE '%sem horario%'                                             THEN 'indisponibilidade'::barravips.tipo_escalada_enum
     ELSE 'outro'::barravips.tipo_escalada_enum
   END
 WHERE tipo IS NULL;

UPDATE barravips.escaladas
   SET observacao = motivo
 WHERE observacao IS NULL;

-- 4) Constraint final ---------------------------------------------------
ALTER TABLE barravips.escaladas
  ALTER COLUMN tipo SET NOT NULL;

-- 5) Índice para o dashboard -------------------------------------------
CREATE INDEX IF NOT EXISTS escaladas_tipo_aberta_em_idx
  ON barravips.escaladas (tipo, aberta_em DESC);
