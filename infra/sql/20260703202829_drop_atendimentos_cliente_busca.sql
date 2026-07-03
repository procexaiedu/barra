-- Descarte do externo-pickup (ADR 0020, status: descartado em 2026-07-03): o subcaso "cliente
-- busca a modelo de carro" saiu do produto — extracao, cron e card removidos do codigo. Esta
-- migration remove a coluna que o sinalizava.
--
-- ⚠️ APLICAR DEPOIS do redeploy do worker/api sem referencias a `cliente_busca` (ordem inversa
-- da migration original 20260610201312): o codigo antigo ainda seleciona a coluna e quebraria.
--
-- O valor 'cliente_busca' de barravips.tipo_escalada_enum PERMANECE: Postgres nao suporta
-- remover valor de enum sem recriar o tipo (e escaladas historicas podem referencia-lo).
-- Fica inerte — nenhum caminho de codigo o insere.

ALTER TABLE barravips.atendimentos
  DROP COLUMN IF EXISTS cliente_busca;
