-- =============================================================================
-- Piso ABSOLUTO por linha de tabela (`modelo_programas.preco_minimo`) + duração de
-- 30 minutos no catálogo global.
--
-- Motivação (Fernando, 11/08/2026, ao subir a Catarina): "400 1h / com desconto 300 1h /
-- mínimo 250 30min". Os dois primeiros o sistema já entregava por acidente aritmético
-- (400 × (1 − desconto_teto_pct=0,25) = 300); o terceiro não existia de duas maneiras:
--
--   1. Não havia duração de 30min em `barravips.duracoes` (só 1h/2h/3h/4h/6h/8h/12h),
--      então o pacote de 250 não era nem cadastrável — e o `<girias_do_cliente>` do
--      prompt manda a IA NEGAR meia hora quando ela não está na tabela ("30min não tenho
--      amor, mínimo 1h 400"). O cliente de bolso curto era recusado em vez de comprar.
--   2. A escada de desconto (ADR-0031) é PERCENTUAL sobre cada linha da tabela, sem
--      noção de piso absoluto: cadastrar 250 sozinho faria a IA poder ofertar 219 (degrau)
--      e 188 (teto) em cima dele. "Mínimo" que desconta não é mínimo.
--
-- `preco_minimo` resolve (2) e, de quebra, transforma o "com desconto 300" em DADO
-- CADASTRADO em vez de efeito colateral de `settings.desconto_teto_pct` — hoje mexer no
-- percentual global mexeria no piso da Catarina junto. Semântica: quando preenchido, é o
-- menor valor que a IA pode ofertar naquela linha; degrau e teto ficam clampados nele
-- (`max(conta_percentual, preco_minimo)`). `preco_minimo = preco` = linha não descontável.
-- NULL preserva o comportamento de hoje (só o percentual manda), então a coluna é inerte
-- para todo o cadastro existente.
--
-- O mínimo NUNCA é renderizado no prompt (ADR-0004 §Decisão item 5: expor o piso ensina a
-- IA a ancorar nele ou a vazá-lo). Ele só clampa os números que o código calcula e injeta.
--
-- Preços por modelo (a Catarina 30min = 250) NÃO entram aqui: entram via painel/MCP, como
-- prescreve a 20260722024720_duracoes_6h_8h.sql. Esta migration é schema + catálogo global.
--
-- Idempotente: roda 2x sem quebrar. A duração é keyed por `horas = 0.5`, não por nome —
-- mesmo cuidado da 20260722024720 (em prod já existe "Pernoite" e uma "12 horas" duplicada
-- com nomes diferentes para as mesmas 12h).
--
-- Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA `make migrate`.
-- =============================================================================

BEGIN;

ALTER TABLE barravips.modelo_programas
  ADD COLUMN IF NOT EXISTS preco_minimo numeric;

COMMENT ON COLUMN barravips.modelo_programas.preco_minimo IS
  'Piso ABSOLUTO desta linha da tabela: menor valor que a IA pode ofertar no par (programa, duração), clampando degrau e teto da escada de desconto (ADR-0031) por cima do percentual global. Igual a `preco` = linha não descontável. NULL = só o percentual de settings manda (comportamento pré-11/08/2026). Nunca renderizado no prompt (ADR-0004 §Decisão item 5).';

-- Piso maior que o próprio preço seria um "mínimo" que a tabela já não cumpre — a escada
-- clampada devolveria um valor ACIMA da tabela e a IA cotaria mais caro no desconto.
ALTER TABLE barravips.modelo_programas
  DROP CONSTRAINT IF EXISTS modelo_programas_preco_minimo_ate_preco;

ALTER TABLE barravips.modelo_programas
  ADD CONSTRAINT modelo_programas_preco_minimo_ate_preco
  CHECK (preco_minimo IS NULL OR (preco_minimo >= 0 AND preco_minimo <= preco));

-- Duração de 30 minutos. `ordem = 0` a põe antes da "1 hora" (ordem 1) no painel e no
-- render de <programas>, que lista da menor para a maior.
INSERT INTO barravips.duracoes (nome, ordem, horas)
SELECT '30 minutos', 0, 0.5
WHERE NOT EXISTS (SELECT 1 FROM barravips.duracoes WHERE horas = 0.5);

COMMIT;
