-- =============================================================================
-- 0002_envios_evolution.sql
-- Registro transacional de envios outbound feitos pelo backend via Evolution.
-- =============================================================================

SET search_path TO barravips, public;

CREATE TABLE barravips.envios_evolution (
  id                    uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  evolution_message_id  text NOT NULL UNIQUE,
  instance_id           text NOT NULL,
  remote_jid            text NOT NULL,
  contexto              text NOT NULL,
  direcao               text NOT NULL DEFAULT 'outbound_backend',
  tipo                  text NOT NULL,
  atendimento_id        uuid REFERENCES barravips.atendimentos(id) ON DELETE SET NULL,
  conversa_id           uuid REFERENCES barravips.conversas(id) ON DELETE SET NULL,
  payload               jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT envios_evolution_contexto_check
    CHECK (contexto IN ('conversa_cliente', 'grupo_coordenacao')),
  CONSTRAINT envios_evolution_direcao_check
    CHECK (direcao = 'outbound_backend'),
  CONSTRAINT envios_evolution_tipo_check
    CHECK (tipo IN ('ia', 'card', 'confirmacao', 'erro_comando', 'midia'))
);

CREATE INDEX envios_evolution_remote_jid_created_idx
  ON barravips.envios_evolution (remote_jid, created_at DESC);

CREATE INDEX envios_evolution_atendimento_created_idx
  ON barravips.envios_evolution (atendimento_id, created_at DESC)
  WHERE atendimento_id IS NOT NULL;

CREATE INDEX envios_evolution_conversa_created_idx
  ON barravips.envios_evolution (conversa_id, created_at DESC)
  WHERE conversa_id IS NOT NULL;

ALTER TABLE barravips.envios_evolution ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.envios_evolution FORCE ROW LEVEL SECURITY;

CREATE POLICY fernando_full_access
  ON barravips.envios_evolution
  AS PERMISSIVE
  FOR ALL
  TO authenticated
  USING ((SELECT barravips.is_fernando()))
  WITH CHECK ((SELECT barravips.is_fernando()));

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.envios_evolution TO authenticated;
GRANT ALL PRIVILEGES ON barravips.envios_evolution TO service_role;

COMMENT ON TABLE barravips.envios_evolution IS
  'Outbound enviado pelo backend via Evolution. Usado para distinguir backend/IA/sistema de ação manual no número operado.';

