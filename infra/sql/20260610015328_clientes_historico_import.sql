-- =============================================================================
-- Histórico estruturado do import de contatos reais (09/06/2026).
--
-- O export de contatos do Google do Fernando codifica, no nome de cada contato,
-- o histórico operacional do cliente: acompanhante(s) que atenderam, valor pago,
-- duração, tipo (presencial/vídeo chamada/presente) e flags de comportamento
-- ("não marca", "marcou e sumiu", risco). O lar canônico desse dado é a Conversa
-- cliente (observacoes_internas, por par cliente×modelo), mas as modelos reais
-- ainda não estão cadastradas — então o parse fica estacionado aqui, 1 linha por
-- cliente, até a hidratação por par.
--
-- `dados` (jsonb): { fixo: bool, flags: text[], obs: text|null,
--   historico: [{ modelos: text[], valor, duracao_horas, tipo, obs }] }
-- (modelos por NOME — sem FK, ainda não existem). `migrado_em` marca quando o
-- histórico virou observacoes_internas das conversas; até lá fica NULL.
--
-- NÃO criar atendimentos históricos a partir daqui (datas falsas poluem o
-- financeiro). Tabela interna, painel-only futuro; sem RLS, como
-- schema_migrations (escrita só pelo operador, nunca exposta ao PostgREST).
--
-- Idempotente. Schema-only (os dados entram via psycopg, não são seed).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS barravips.clientes_historico_import (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  cliente_id      uuid NOT NULL UNIQUE REFERENCES barravips.clientes(id) ON DELETE CASCADE,
  dados           jsonb NOT NULL,
  nomes_originais text[] NOT NULL,
  importado_em    timestamptz NOT NULL DEFAULT now(),
  migrado_em      timestamptz
);

COMMENT ON TABLE barravips.clientes_historico_import IS
  'interna: sem RLS porque escrita só pelo operador via psycopg, nunca exposta ao painel/PostgREST. Parse estruturado do import de contatos 09/06/2026 (acompanhante/valor/duração/flags por cliente); transitório até hidratar observacoes_internas das conversas por par quando as modelos reais forem cadastradas.';

COMMIT;
