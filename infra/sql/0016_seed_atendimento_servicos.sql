-- 0016: seed de programas por modelo e servicos por atendimento
--
-- Mantem a modelagem normalizada:
-- - programas/duracoes/modelo_programas definem catalogo e preco vigente por modelo;
-- - atendimento_servicos registra o snapshot do que foi combinado no atendimento.
--
-- Idempotente: pode ser reaplicado sem duplicar servicos.

SET search_path TO barravips, public;

BEGIN;

-- Garante precos operacionais para os programas/duracoes usados pelo painel.
-- Stephanie: valor base R$ 1.000/h; Alessia: valor base R$ 1.200/h; Larissa: valor base R$ 800/h.
WITH precos(modelo_nome, programa_nome, duracao_nome, preco) AS (
  VALUES
    ('Stephanie Lima', 'Padrão', '1 hora',    1000.00::numeric),
    ('Stephanie Lima', 'Padrão', '2 horas',   1800.00::numeric),
    ('Stephanie Lima', 'Padrão', '3 horas',   2500.00::numeric),
    ('Stephanie Lima', 'Padrão', 'Pernoite',  7000.00::numeric),
    ('Stephanie Lima', 'Casal',  '1 hora',    1500.00::numeric),
    ('Stephanie Lima', 'Casal',  '2 horas',   2600.00::numeric),
    ('Stephanie Lima', 'Jantar', '3 horas',   3000.00::numeric),
    ('Stephanie Lima', 'Social', '3 horas',   2800.00::numeric),
    ('Stephanie Lima', 'Viagem', 'Pernoite', 10000.00::numeric),

    ('Alessia Conti',  'Padrão', '1 hora',    1200.00::numeric),
    ('Alessia Conti',  'Padrão', '2 horas',   2200.00::numeric),
    ('Alessia Conti',  'Padrão', '3 horas',   3000.00::numeric),
    ('Alessia Conti',  'Padrão', 'Pernoite',  8000.00::numeric),
    ('Alessia Conti',  'Casal',  '1 hora',    1800.00::numeric),
    ('Alessia Conti',  'Casal',  '2 horas',   3200.00::numeric),
    ('Alessia Conti',  'Jantar', '3 horas',   3500.00::numeric),
    ('Alessia Conti',  'Social', '3 horas',   3300.00::numeric),
    ('Alessia Conti',  'Viagem', 'Pernoite', 12000.00::numeric),

    ('Larissa Mello',  'Padrão', '1 hora',     800.00::numeric),
    ('Larissa Mello',  'Padrão', '2 horas',   1500.00::numeric),
    ('Larissa Mello',  'Padrão', '3 horas',   2100.00::numeric),
    ('Larissa Mello',  'Padrão', 'Pernoite',  5500.00::numeric)
)
INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco)
SELECT m.id, p.id, d.id, precos.preco
FROM precos
JOIN barravips.modelos m ON m.nome = precos.modelo_nome
JOIN barravips.programas p ON lower(p.nome) = lower(precos.programa_nome)
JOIN barravips.duracoes d ON d.nome = precos.duracao_nome
ON CONFLICT (modelo_id, programa_id, duracao_id) DO UPDATE
SET preco = EXCLUDED.preco;

-- Cria um servico principal para todo atendimento sem servico registrado.
-- A escolha prioriza o que a ficha ja capturou:
-- - texto com casal/grupo -> Casal;
-- - texto com jantar -> Jantar;
-- - duracao longa -> Pernoite/Viagem;
-- - restante -> Padrao.
-- O preco_snapshot usa valor_final/valor_acordado quando existem, preservando o que
-- foi negociado no atendimento; senao cai no preco vigente da modelo.
WITH atendimentos_sem_servico AS (
  SELECT a.*
  FROM barravips.atendimentos a
  WHERE NOT EXISTS (
    SELECT 1
    FROM barravips.atendimento_servicos ats
    WHERE ats.atendimento_id = a.id
  )
),
classificados AS (
  SELECT
    a.id AS atendimento_id,
    a.modelo_id,
    COALESCE(a.valor_final, a.valor_acordado) AS valor_atendimento,
    CASE
      WHEN (COALESCE(a.resumo_operacional, '') || ' ' || COALESCE(a.proxima_acao_esperada, '') || ' ' || COALESCE(a.motivo_escalada, '')) ILIKE '%casal%'
        OR (COALESCE(a.resumo_operacional, '') || ' ' || COALESCE(a.proxima_acao_esperada, '') || ' ' || COALESCE(a.motivo_escalada, '')) ILIKE '%grupo%'
        THEN 'Casal'
      WHEN (COALESCE(a.resumo_operacional, '') || ' ' || COALESCE(a.proxima_acao_esperada, '') || ' ' || COALESCE(a.motivo_escalada, '')) ILIKE '%jantar%'
        THEN 'Jantar'
      WHEN COALESCE(a.duracao_horas, 1) >= 8
        THEN 'Viagem'
      ELSE 'Padrão'
    END AS programa_nome,
    CASE
      WHEN COALESCE(a.duracao_horas, 1) >= 8 THEN 'Pernoite'
      WHEN COALESCE(a.duracao_horas, 1) >= 2.5 THEN '3 horas'
      WHEN COALESCE(a.duracao_horas, 1) >= 1.5 THEN '2 horas'
      ELSE '1 hora'
    END AS duracao_nome
  FROM atendimentos_sem_servico a
),
servicos AS (
  SELECT
    c.atendimento_id,
    p.id AS programa_id,
    d.id AS duracao_id,
    COALESCE(c.valor_atendimento, mp.preco, m.valor_padrao, 0)::numeric(10,2) AS preco_snapshot
  FROM classificados c
  JOIN barravips.modelos m ON m.id = c.modelo_id
  JOIN barravips.programas p ON lower(p.nome) = lower(c.programa_nome)
  JOIN barravips.duracoes d ON d.nome = c.duracao_nome
  LEFT JOIN barravips.modelo_programas mp
    ON mp.modelo_id = c.modelo_id
   AND mp.programa_id = p.id
   AND mp.duracao_id = d.id
)
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot)
SELECT atendimento_id, programa_id, duracao_id, preco_snapshot
FROM servicos
WHERE preco_snapshot >= 0;

COMMIT;
