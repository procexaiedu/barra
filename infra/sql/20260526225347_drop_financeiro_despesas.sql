-- =============================================================================
-- Remove o escopo de Despesas do Módulo Financeiro (Update do ADR 0011).
--
-- Motivação: o operador (Fernando) administra atendimentos, não contabilidade
-- de escritório. Categorias como `anuncios`, `software`, `juridico`, `taxas`
-- não fazem parte da rotina de uma agência de acompanhantes — vivem em
-- planilha/ERP externo. Mantemos receita (projeção de atendimentos) e
-- repasses pagos à modelo, que são operacionais.
--
-- DROP em ordem reversa às dependências: a tabela `financeiro_despesas`
-- referencia `financeiro_despesas_recorrentes` via FK; ambas usam o enum
-- `categoria_despesa_enum`.
--
-- Idempotente. Aplicar manualmente em prod self-hosted via psycopg.
-- =============================================================================

BEGIN;

-- 1. Tabela de lançamentos (pontuais + materializações) -----------------------
DROP TABLE IF EXISTS barravips.financeiro_despesas;

-- 2. Tabela de templates recorrentes ------------------------------------------
DROP TABLE IF EXISTS barravips.financeiro_despesas_recorrentes;

-- 3. Enum de categoria (não usado em outras tabelas) --------------------------
DROP TYPE IF EXISTS barravips.categoria_despesa_enum;

COMMIT;
