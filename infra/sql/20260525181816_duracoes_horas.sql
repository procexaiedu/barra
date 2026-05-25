-- Horas numéricas por duração, para sugerir automaticamente a duração do atendimento.
-- A "duração" era só rótulo de texto (1 hora, 2 horas, Pernoite) sem horas numéricas.
-- O campo numérico atendimentos.duracao_horas (que dirige o bloqueio/conflito de agenda)
-- passa a ser sugerido no painel como o MAX das horas dos serviços selecionados — nunca a soma.

ALTER TABLE barravips.duracoes
  ADD COLUMN IF NOT EXISTS horas numeric(4,2) CHECK (horas IS NULL OR horas > 0);

-- Backfill das durações padrão (seed 0010). WHERE horas IS NULL preserva ajustes manuais
-- em re-execuções. Pernoite = 12h (precedente do seed original 0007).
UPDATE barravips.duracoes SET horas = 1  WHERE nome = '1 hora'   AND horas IS NULL;
UPDATE barravips.duracoes SET horas = 2  WHERE nome = '2 horas'  AND horas IS NULL;
UPDATE barravips.duracoes SET horas = 3  WHERE nome = '3 horas'  AND horas IS NULL;
UPDATE barravips.duracoes SET horas = 4  WHERE nome = '4 horas'  AND horas IS NULL;
UPDATE barravips.duracoes SET horas = 12 WHERE nome = 'Pernoite' AND horas IS NULL;
