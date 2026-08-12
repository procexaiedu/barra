-- =============================================================================
-- Vídeo chamada no catálogo GLOBAL: durações de 15min e 45min, o programa
-- "Vídeo chamada" e `duracoes.ordem` virando função das horas.
--
-- Motivação (Fernando, 11/08/2026, ao subir a Catarina): a vídeo chamada é R$10/minuto com
-- piso de 15 minutos — 15min 150, 30min 300, 45min 450, 60min 600, todas NÃO descontáveis
-- (o preço É o mínimo, então cada linha entra com `preco_minimo = preco`, a coluna da
-- 20260811193150). O corpus do vendedor humano já vendia exatamente assim ("Faço sim / 150
-- 15min a vídeo chamada", funil_*.json), então a grade de preços não é invenção nova: o que
-- faltava era o catálogo global conseguir REPRESENTÁ-LA. Faltava em três lugares:
--
--   1. Não havia duração de 15min nem de 45min em `barravips.duracoes` (só 0.5/1/2/3/4/6/12h
--      hoje em prod) — as duas pontas da grade não eram nem cadastráveis, e o pacote de
--      entrada da chamada (o de 150, que é o que o cliente pede) ficava de fora.
--   2. Não havia NENHUM programa com "chamada" no nome. `e_video_chamada` (persona.py, site
--      único; `nos/prepare_context.py` o importa) decide por substring do nome normalizado, e
--      com zero linhas casando o `_carregar_bp3` deriva `sem_video_chamada = True`: chega o
--      `<sem_video_chamada>` na cauda e a conduta INVERTE de sinal. A modelo passa a NEGAR o
--      que vende — "Não faço chamada amor" no <protocolo_disclosure> e no <tipos_de_encontro>,
--      onde "nada aqui se aplica" quando o bloco chega. Cadastrar o preço no painel sem o
--      programa certo no catálogo não resolve nada: o gate é pelo NOME.
--   3. `ordem` não tinha inteiro livre entre "30 minutos" (0) e "1 hora" (1) para os 45min. O
--      render de <programas> ordena `ORDER BY p.categoria, p.nome, d.ordem ASC` — com os 45min
--      empurrados para o fim, a tabela que a IA lê (e recita) sairia fora de ordem de duração.
--
-- NOME ESCOLHIDO: "Vídeo chamada" — deliberadamente o mesmo substantivo em três camadas.
-- (a) casa o predicado (`normalizar("Vídeo chamada")` = "video chamada" ⊃ "chamada");
-- (b) é a palavra da operação — verbete "Vídeo chamada" do CONTEXT.md, card "Hora da sua
--     vídeo chamada", cenário `remoto_videochamada` do eval e2e (que já usa este literal);
-- (c) é a palavra da BOCA da IA: o nome do programa aparece na tabela renderizada e as falas
--     canônicas do regras.md.j2 são "Podemos fazer uma vídeo chamada amor" e "ofereça a menor
--     da tabela". Nome de catálogo e nome falado coincidindo, não há tradução para a IA errar.
--     Um "Chamada de vídeo" casaria o predicado igual, mas obrigaria a IA a reescrever o nome
--     ao cotar; um "Vídeo" (sem "chamada") não casaria e recriaria o problema (2).
--
-- Consequências do predicado que são QUERIDAS, não efeito colateral: a linha da vídeo chamada
-- fica fora do `<fetiches>` (fetiche pago só existe em programa presencial — senão a chamada
-- de 60min da Catarina viraria "Vídeo chamada (1h) | R$1.000") e fora do `_menu_primeira_cotacao`,
-- que só conta programas presenciais para decidir a tabela de duas portas. Uma Catarina com
-- Encontro + Completo + Vídeo chamada continua com o menu de duas portas montando.
--
-- `ordem` VIRA DERIVADA: `(horas * 40)::int`, com +1 no "Pernoite". Antes era posição arbitrária
-- e cada duração nova exigia renumerar o resto (foi o que a 20260722024720 teve de fazer com o
-- Pernoite). Como função das horas ela é monotônica por construção, dá folga de 10 entre
-- quartos de hora (o menor incremento que a operação vende) e de 40 entre horas cheias, e
-- QUALQUER duração futura calcula a própria posição sem renumeração — inclusive a de 8h, que a
-- 20260722024720 criou e que hoje não está mais em prod (apagada pelo painel, presumivelmente);
-- se voltar, ela cai sozinha no lugar certo (320).
--
-- Estado final (as linhas que existem em prod hoje; as demais são a fórmula aplicada):
--   15 minutos   0.25 →  10      6 horas    6.00 → 240
--   30 minutos   0.50 →  20      Pernoite   6.00 → 241
--   45 minutos   0.75 →  30      (8 horas   8.00 → 320, se recriada)
--   1 hora       1.00 →  40      12 horas  12.00 → 480
--   2 horas      2.00 →  80
--   3 horas      3.00 → 120
--   4 horas      4.00 → 160
--
-- Decisão sobre o SENTINELA 999: o "12 horas" SAI dele (999 → 480) e continua sendo o último da
-- lista — só que agora por ser a duração mais longa, não por convenção. O 999 era um "fim de
-- lista" que só funcionava enquanto nada passasse de 12h; com `ordem` derivada de `horas` ele
-- deixa de ter função (uma "24 horas"/Viagem, se um dia entrar, ficaria DEPOIS dele em duração e
-- ANTES dele em ordem — exatamente o bug que o sentinela criaria).
--
-- O +1 do Pernoite é um desempate NECESSÁRIO, não estética: "Pernoite" e "6 horas" têm as mesmas
-- 6h desde a 20260811210338, e `ORDER BY p.categoria, p.nome, d.ordem` precisa ser uma ordem
-- TOTAL — empate em `ordem` deixa a linha do render em ordem indefinida pelo Postgres e quebra a
-- estabilidade byte-a-byte do prefixo cacheável (agente/CLAUDE.md). O Pernoite fica logo depois
-- da "6 horas", que é a posição relativa que ele já tinha (5 vs 7). Toda duração futura que
-- empatar em `horas` com outra precisa do mesmo tratamento.
--
-- Consequência ACEITA (risco conhecido, fora do escopo desta migration): duração criada pelo
-- painel entra por `POST /modelos/duracoes` → `INSERT (nome, ordem)` com `ordem = duracoes.length`
-- e SEM `horas` (DuracaoCreate não tem o campo). Ela fica fora da escala — um `ordem = 11` agora
-- cai no TOPO da lista, em vez de perto do fim como caía na numeração 0..7 — e o UPDATE abaixo
-- não a corrige, porque só toca linhas com `horas` preenchida. Duração sem `horas` já hoje fica
-- fora de todas as contas do agente (extra de fetiche por preço-hora, `tabela_max_horas`), então
-- o conserto certo é no painel (exigir `horas` e usar `max(ordem) + 10`), não aqui.
--
-- Preços por modelo (a grade 150/300/450/600 da Catarina) NÃO entram aqui: entram via painel/MCP,
-- como prescrevem a 20260722024720 e a 20260811193150. Esta migration é catálogo global.
--
-- Idempotente: roda 2x sem quebrar. As durações são keyed por `horas`, não por nome (lição das
-- 20260722024720/20260811193150: em prod já há nomes diferentes para as mesmas horas). O UPDATE é
-- CONVERGENTE — calcula o alvo a partir de `horas`, nunca a partir do `ordem` atual, então chega
-- ao mesmo estado final de qualquer estado inicial (não depende de os valores de hoje serem os
-- 0..7/999 listados acima), e o `IS DISTINCT FROM` deixa a 2ª passada em 0 linhas afetadas. O
-- programa é keyed pelo PRÓPRIO PREDICADO DO CÓDIGO (`lower(nome) LIKE '%chamada%'`), não pelo
-- literal: se o painel já tiver criado uma "Videochamada", esta migration não cria uma segunda
-- linha que competiria com ela na tabela da modelo.
--
-- Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA `make migrate`.
-- =============================================================================

BEGIN;

-- 1) As duas pontas da grade da vídeo chamada. `ordem` já entra no valor da fórmula (o UPDATE
-- abaixo confirmaria, mas assim a linha nasce certa mesmo se alguém rodar só este trecho).
INSERT INTO barravips.duracoes (nome, ordem, horas)
SELECT '15 minutos', 10, 0.25
WHERE NOT EXISTS (SELECT 1 FROM barravips.duracoes WHERE horas = 0.25);

INSERT INTO barravips.duracoes (nome, ordem, horas)
SELECT '45 minutos', 30, 0.75
WHERE NOT EXISTS (SELECT 1 FROM barravips.duracoes WHERE horas = 0.75);

-- 2) `ordem` recalculada a partir de `horas` para TODA duração que tem horas. Não é uma
-- renumeração pontual dos 45min: é a coluna inteira passando a ser derivada.
UPDATE barravips.duracoes AS d
   SET ordem = alvo.ordem
  FROM (
        SELECT id,
               (horas * 40)::int + CASE WHEN nome = 'Pernoite' THEN 1 ELSE 0 END AS ordem
          FROM barravips.duracoes
         WHERE horas IS NOT NULL
       ) AS alvo
 WHERE alvo.id = d.id
   AND d.ordem IS DISTINCT FROM alvo.ordem;

COMMENT ON COLUMN barravips.duracoes.ordem IS
  'Posição no render de <programas> e no painel. DERIVADA de `horas` desde 11/08/2026: `(horas * 40)::int`, +1 no "Pernoite" para desempatar com a "6 horas" (a ordem precisa ser TOTAL — empate deixa o prefixo cacheável instável). Duração nova deve entrar com a fórmula, não com a próxima posição livre; duração sem `horas` fica fora da escala e cai no topo da lista.';

-- 3) O programa de vídeo chamada no catálogo global. Sem preço: a linha por modelo
-- (modelo_programas, com `preco` e `preco_minimo = preco`) entra pelo painel/MCP.
INSERT INTO barravips.programas (nome)
SELECT 'Vídeo chamada'
WHERE NOT EXISTS (
    SELECT 1 FROM barravips.programas WHERE lower(nome) LIKE '%chamada%'
);

COMMIT;
