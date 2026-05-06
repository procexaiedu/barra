-- 0017: backfill defensivo de atendimento_servicos restantes
--
-- A seed 0016 depende de nomes especificos de programas/duracoes. Em bases onde
-- o catalogo esta diferente, ela pode inserir apenas parte dos atendimentos.
-- Esta migration preenche todo atendimento que ainda nao tem servico, escolhendo
-- um programa/duracao existentes e preservando o valor negociado como snapshot.

SET search_path TO barravips, public;

BEGIN;

WITH atendimentos_sem_servico AS (
  SELECT a.*
  FROM barravips.atendimentos a
  WHERE NOT EXISTS (
    SELECT 1
    FROM barravips.atendimento_servicos ats
    WHERE ats.atendimento_id = a.id
  )
),
escolha_por_modelo AS (
  SELECT
    a.id AS atendimento_id,
    mp.programa_id,
    mp.duracao_id,
    mp.preco,
    row_number() OVER (
      PARTITION BY a.id
      ORDER BY
        abs(
          CASE
            WHEN d.nome ILIKE '%pernoite%' THEN 12.0
            WHEN d.nome ~ '^[0-9]+' THEN substring(d.nome from '^[0-9]+')::numeric
            ELSE COALESCE(a.duracao_horas, 1)
          END - COALESCE(a.duracao_horas, 1)
        ),
        d.ordem,
        p.nome
    ) AS rn
  FROM atendimentos_sem_servico a
  JOIN barravips.modelo_programas mp ON mp.modelo_id = a.modelo_id
  JOIN barravips.programas p ON p.id = mp.programa_id
  JOIN barravips.duracoes d ON d.id = mp.duracao_id
),
catalogo_fallback AS (
  SELECT
    p.id AS programa_id,
    d.id AS duracao_id,
    row_number() OVER (
      ORDER BY
        CASE
          WHEN p.nome ILIKE '%pad%' THEN 0
          ELSE 1
        END,
        d.ordem,
        p.nome
    ) AS rn
  FROM barravips.programas p
  CROSS JOIN barravips.duracoes d
),
servicos AS (
  SELECT
    a.id AS atendimento_id,
    COALESCE(epm.programa_id, cf.programa_id) AS programa_id,
    COALESCE(epm.duracao_id, cf.duracao_id) AS duracao_id,
    COALESCE(a.valor_final, a.valor_acordado, epm.preco, m.valor_padrao, 0)::numeric(10,2) AS preco_snapshot
  FROM atendimentos_sem_servico a
  JOIN barravips.modelos m ON m.id = a.modelo_id
  LEFT JOIN escolha_por_modelo epm ON epm.atendimento_id = a.id AND epm.rn = 1
  LEFT JOIN catalogo_fallback cf ON cf.rn = 1
)
INSERT INTO barravips.atendimento_servicos (
  atendimento_id,
  programa_id,
  duracao_id,
  preco_snapshot
)
SELECT
  atendimento_id,
  programa_id,
  duracao_id,
  preco_snapshot
FROM servicos
WHERE programa_id IS NOT NULL
  AND duracao_id IS NOT NULL
  AND preco_snapshot >= 0;

COMMIT;
