-- =============================================================================
-- Módulo de tarefas interno (ADR 0017).
--
-- Gestão de tarefas da operação dentro do sistema (estilo ClickUp), MVP enxuto:
-- sem RBAC, notificação, time-tracking, comentários, histórico ou recorrência.
-- Ator (criador/responsável) é POLIMÓRFICO — par (tipo, id) sem FK (psycopg puro,
-- integridade na app, ADR 0002) — para já suportar modelos/vendedores como
-- responsáveis no futuro sem migration nova. Painel-only: a IA nunca lê tarefas.
--
-- Tudo idempotente. Aplicar manualmente em prod self-hosted via psycopg.
-- =============================================================================

BEGIN;

-- 1. Enums ---------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'tarefa_status_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.tarefa_status_enum AS ENUM ('a_fazer', 'fazendo', 'feita');
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'tarefa_prioridade_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.tarefa_prioridade_enum AS ENUM ('baixa', 'media', 'alta');
  END IF;

  -- Universo de atores que criam/recebem tarefas. No MVP só 'usuario' é populado
  -- em criado_por; o seletor de responsável já aceita 'modelo'/'vendedor' como rótulo.
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'tarefa_ator_tipo' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.tarefa_ator_tipo AS ENUM ('usuario', 'modelo', 'vendedor');
  END IF;
END
$$;

COMMENT ON TYPE barravips.tarefa_ator_tipo IS
  'Tipo do ator (criador/responsável) de uma tarefa. Par (tipo, id) sem FK — integridade na app (ADR 0002/0017). Habilita modelos/vendedores como responsáveis sem migration futura.';


-- 2. Tabela tarefas ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS barravips.tarefas (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  titulo          text NOT NULL CHECK (length(btrim(titulo)) > 0),
  descricao       text NULL,
  status          barravips.tarefa_status_enum NOT NULL DEFAULT 'a_fazer',
  prioridade      barravips.tarefa_prioridade_enum NOT NULL DEFAULT 'media',
  -- Data sem hora (granularidade de dia; evita bug de timezone). NULL = backlog.
  prazo           date NULL,
  -- Criador: no MVP sempre ('usuario', Fernando). Polimórfico p/ futuro multi-login.
  criado_por_tipo barravips.tarefa_ator_tipo NOT NULL,
  criado_por_id   uuid NOT NULL,
  -- Responsável (rótulo de execução; não controla acesso no MVP). NULL = não atribuída.
  atribuido_tipo  barravips.tarefa_ator_tipo NULL,
  atribuido_id    uuid NULL,
  concluida_em    timestamptz NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  -- tipo e id do responsável andam juntos: ou ambos preenchidos, ou ambos NULL.
  CONSTRAINT tarefas_atribuido_consistente
    CHECK ((atribuido_tipo IS NULL) = (atribuido_id IS NULL))
);

COMMENT ON TABLE barravips.tarefas IS
  'Tarefas internas da operação (ADR 0017). Painel-only: a IA por modelo nunca lê. Ator polimórfico (tipo,id) sem FK. MVP sem RBAC/notificação/recorrência.';

CREATE INDEX IF NOT EXISTS tarefas_status_idx        ON barravips.tarefas (status);
CREATE INDEX IF NOT EXISTS tarefas_prazo_idx         ON barravips.tarefas (prazo);
CREATE INDEX IF NOT EXISTS tarefas_atribuido_idx     ON barravips.tarefas (atribuido_tipo, atribuido_id);
CREATE INDEX IF NOT EXISTS tarefas_created_at_idx    ON barravips.tarefas (created_at DESC);


-- 3. Trigger set_updated_at (reusa função existente) --------------------------
DROP TRIGGER IF EXISTS set_updated_at_tarefas ON barravips.tarefas;
CREATE TRIGGER set_updated_at_tarefas
  BEFORE UPDATE ON barravips.tarefas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();


-- 4. RLS: ENABLE + FORCE + policy fernando_full_access ------------------------
ALTER TABLE barravips.tarefas ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.tarefas FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.tarefas;
CREATE POLICY fernando_full_access
  ON barravips.tarefas
  AS PERMISSIVE
  FOR ALL
  TO authenticated
  USING ((SELECT barravips.is_fernando()))
  WITH CHECK ((SELECT barravips.is_fernando()));

COMMIT;
