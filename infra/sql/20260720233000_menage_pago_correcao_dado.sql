-- =============================================================================
-- Menage vira fetiche PAGO (correção de dado, ADR-0030 / spec 0001-fetiche-calculado).
--
-- Menage segue a MESMA fórmula de qualquer fetiche pago (preço-hora efetivo do
-- pacote vendido, calculado em runtime — dominio/atendimentos/service.py:
-- calcular_preco_extra_fetiche). Não existe multiplicador especial "dobro":
-- a leitura de "dobro do pacote" é só a aritmética normal quando o pacote
-- vendido é de 1h (CONTEXT.md "Menage"; ADR-0030).
--
-- Hoje (pré-fix) existe pelo menos uma modelo com Menage cadastrado como
-- INCLUSO (preco NULL) — dado errado herdado do cadastro antigo por valor
-- fixo (ADR-0014). Este script:
--   1. Garante o item "Menage" no catálogo global (idempotente).
--   2. Corrige qualquer vínculo modelo×Menage hoje incluso para pago.
--
-- Sem migration de schema em modelo_fetiches.preco (reaproveita NULL/NOT NULL
-- como flag — ver 20260529220000_fetiches.sql e dominio/modelos/routes.py
-- _PRECO_PAGO_SENTINEL). Idempotente: roda 2x sem quebrar.
--
-- "Menage" não nasce de nenhum seed deste repo (nenhum infra/sql/*.sql o cria) — foi cadastrado
-- direto em prod via Studio, fora do controle de versão (mesmo gotcha de
-- `prod_modelos_schema_diverge_repo`). `fetiches.nome` não tem UNIQUE, então o guard casa por
-- `lower(btrim(nome))` em vez de igualdade exata, pra não duplicar o catálogo se a grafia real em
-- prod vier com variação de caixa/espaço.
--
-- Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA `make migrate`.
-- =============================================================================

BEGIN;

INSERT INTO barravips.fetiches (nome)
SELECT 'Menage'
 WHERE NOT EXISTS (
   SELECT 1 FROM barravips.fetiches WHERE lower(btrim(nome)) = 'menage'
 );

-- Sentinel truthy (mesmo valor de dominio/modelos/routes.py _PRECO_PAGO_SENTINEL):
-- o número em si nunca é lido pelo cálculo do extra, só a presença NOT NULL importa.
UPDATE barravips.modelo_fetiches mf
   SET preco = 1
  FROM barravips.fetiches f
 WHERE f.id = mf.fetiche_id
   AND lower(btrim(f.nome)) = 'menage'
   AND mf.preco IS NULL;

COMMIT;
