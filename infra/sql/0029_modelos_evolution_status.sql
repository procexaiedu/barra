-- =============================================================================
-- 0029_modelos_evolution_status.sql
-- Pareamento Evolution explícito por modelo.
--
-- ANTES: `evolution_instance_id IS NOT NULL` era o único sinal de "pareada",
-- mas o instance_id é gravado no POST /conectar-whatsapp (antes do scan),
-- então o badge mentia entre "pediu QR" e "scaneou". Agora há uma máquina de
-- estados explícita: desconectado → pareando → conectado, atualizada pelo
-- webhook CONNECTION_UPDATE (state=open).
-- =============================================================================

CREATE TYPE barravips.evolution_pareamento_enum AS ENUM (
  'desconectado',
  'pareando',
  'conectado'
);

ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS evolution_status barravips.evolution_pareamento_enum
    NOT NULL DEFAULT 'desconectado',
  ADD COLUMN IF NOT EXISTS evolution_pareado_em timestamptz NULL;

-- Backfill: modelos que já tinham evolution_instance_id preenchido herdam
-- 'conectado' para preservar a semântica antiga. Operador revalida na próxima
-- mensagem ou no botão "Trocar conexão" se o estado real divergir.
UPDATE barravips.modelos
   SET evolution_status = 'conectado',
       evolution_pareado_em = COALESCE(evolution_pareado_em, now())
 WHERE evolution_instance_id IS NOT NULL
   AND evolution_status = 'desconectado';

COMMENT ON COLUMN barravips.modelos.evolution_status IS
  'Estado do pareamento Evolution: desconectado | pareando | conectado. Atualizado pelo webhook CONNECTION_UPDATE.';
COMMENT ON COLUMN barravips.modelos.evolution_pareado_em IS
  'Timestamp do último CONNECTION_UPDATE state=open recebido para esta instância.';
