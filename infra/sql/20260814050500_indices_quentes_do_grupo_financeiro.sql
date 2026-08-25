-- =============================================================================
-- 20260814050500_indices_quentes_do_grupo_financeiro.sql
-- Dois indices que faltaram no encanamento do Agente financeiro (spec 0005).
-- Sem mudanca de schema logico: so caminho de acesso.
--
-- 1) `grupo_financeiro_mensagens (grupo_id, evolution_message_id)`
--    A tabela nasceu (20260814004920) com `(grupo_id, recebida_em DESC)` + o
--    UNIQUE de `chave_dedup`. Nenhum dos dois serve as TRES consultas quentes
--    que filtram pelo id da mensagem na plataforma:
--      * `marcar_mensagem_apagada` (repo.py) — todo evento de delecao;
--      * `vendas_da_mensagem_citada` (repo.py) — toda correcao por quote;
--      * `venda_aberta_da_mensagem_citada` (repo.py) — toda resposta citando.
--    Quote e o gesto cotidiano do grupo: sem indice, cada um deles e seq scan
--    numa tabela que cresce com CADA mensagem de grupo (o numero da ProceX e
--    compartilhado). Parcial em `IS NOT NULL` porque a fala reservada da rotina
--    da manha entra sem id de plataforma e nunca e procurada por ele.
--
-- 2) `vendas_registradas_forma_pendente_idx` refeito
--    A versao de 20260814013400 e `(modelo_id, data) WHERE forma_pagamento IS
--    NULL`, criada antes de `anulada_em` existir e recortada por MODELO. A
--    consulta real (`vendas_sem_forma_de_pagamento`) filtra por GRUPO (via a
--    mensagem-fonte) e exige `anulada_em IS NULL` — venda anulada nao tem
--    pendencia. O indice antigo, alem de nao casar, mantinha no indice as linhas
--    anuladas para sempre. Recriado como
--    `(mensagem_id) WHERE forma_pagamento IS NULL AND anulada_em IS NULL`, que e
--    o lado pelo qual o JOIN entra.
--
-- Idempotente (IF NOT EXISTS / DROP IF EXISTS): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814050500_indices_quentes_do_grupo_financeiro.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   SELECT indexname FROM pg_indexes
--    WHERE schemaname='barravips'
--      AND tablename IN ('grupo_financeiro_mensagens','vendas_registradas');
-- =============================================================================

BEGIN;

CREATE INDEX IF NOT EXISTS grupo_financeiro_mensagens_evolution_id_idx
  ON barravips.grupo_financeiro_mensagens (grupo_id, evolution_message_id)
  WHERE evolution_message_id IS NOT NULL;

DROP INDEX IF EXISTS barravips.vendas_registradas_forma_pendente_idx;

CREATE INDEX IF NOT EXISTS vendas_registradas_forma_pendente_idx
  ON barravips.vendas_registradas (mensagem_id)
  WHERE forma_pagamento IS NULL AND anulada_em IS NULL;

COMMIT;
