-- =============================================================================
-- 20260725191159_atendimentos_horario_evidenciado.sql
-- Marca de PROVENIENCIA do horario em barravips.atendimentos (spec
-- .scratch/extracao-proveniencia-horario/spec.md): existe, na Conversa cliente,
-- uma fala do cliente que sustenta o `horario_desejado` gravado?
--
-- Hoje as quatro origens do horario (extrator lendo fala real, fallback de tempo
-- imediato, eco do belief e edicao do painel) sao indistinguiveis: no atendimento
-- #25 (23/07) a IA sondou "Seria agora ?", o cliente ignorou e mesmo assim o
-- sistema gravou 02:00 e passou a exibi-lo a IA como "pedido dele".
--
-- Carimbada pelo detector deterministico do turno (agente/_disciplina.py +
-- nos/prepare_context.py -> dominio/atendimentos/service.py) e pela rota de
-- edicao de dados do painel (operador e fonte forte).
--
-- SEM BACKFILL de proposito: a marca e recomputavel a partir da janela a cada
-- turno — nasce false e o detector a corrige no primeiro turno seguinte de
-- qualquer atendimento vivo. A coluna existe so porque a fala que evidencia pode
-- sair da janela deslizante, nao porque a informacao seja irrecuperavel.
--
-- A tabela atendimentos ja tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration
-- so adiciona coluna, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS).
-- Schema-only — nao aplicar seeds em prod.
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260725191159_atendimentos_horario_evidenciado.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS horario_evidenciado boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN barravips.atendimentos.horario_evidenciado IS
  'Existe fala do cliente na Conversa que sustenta o horario_desejado gravado. '
  'Sobe sempre que o detector do turno encontra evidencia (hora explicita do cliente, '
  'confirmacao curta sobre hora que a IA propos, aceite da sondagem de imediatismo) e '
  'quando o operador edita o horario pelo painel; cai so quando o VALOR muda sem '
  'evidencia nova (fallback de tempo imediato / eco do belief). Sem backfill.';
