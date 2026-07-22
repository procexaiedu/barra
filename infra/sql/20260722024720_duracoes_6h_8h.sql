-- Durações globais 6h e 8h (feedback Fernando 21/07: "Normalmente o pernoite tem duração de
-- 6, 8h / Ou 12h" — pernoite é produto vendível nessas faixas; docs/feedbacks/
-- 2026-07-21-pernoite-cadastrar-duracoes-precos.md). Catálogo global, não seed: os preços por
-- modelo (modelo_programas) entram via painel/MCP quando Fernando definir os valores.
--
-- Idempotente por `horas`, não por nome: em prod existem "Pernoite" (horas=12) e uma "12 horas"
-- duplicada (ordem 999) — os INSERTs não tocam nenhuma das duas; o UPDATE abaixo reordena SÓ o
-- Pernoite (keying por nome, nunca pelo `ordem` acidental da duplicada).

INSERT INTO barravips.duracoes (nome, ordem, horas)
SELECT '6 horas', 5, 6
WHERE NOT EXISTS (SELECT 1 FROM barravips.duracoes WHERE horas = 6);

INSERT INTO barravips.duracoes (nome, ordem, horas)
SELECT '8 horas', 6, 8
WHERE NOT EXISTS (SELECT 1 FROM barravips.duracoes WHERE horas = 8);

-- Pernoite (12h) veio com ordem 4 do seed 0010; com 6h/8h em 5/6, ele ficaria fora de ordem no
-- painel. Empurra para depois das novas durações; a "12 horas" duplicada (999) permanece onde está.
UPDATE barravips.duracoes SET ordem = 7 WHERE nome = 'Pernoite' AND horas = 12 AND ordem < 7;
