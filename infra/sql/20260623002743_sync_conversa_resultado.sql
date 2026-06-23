-- =============================================================================
-- Sincroniza a Conversa cliente com o resultado do atendimento (CONTEXT.md
-- "Conversa cliente" / "Atendimento").
--
-- Dois campos da conversa eram lidos (pelo agente em prepare_context e pelo CRM)
-- mas NUNCA escritos — ficavam presos no default:
--   - conversas.recorrente       (bool)  → sempre false
--   - conversas.ultimo_motivo_perda (enum) → sempre NULL
--
-- Trigger AFTER UPDATE OF estado em atendimentos, espelhando
-- `sync_bloqueio_estado` (0001 §4.3/§7.3) — pega TODOS os caminhos de transição
-- terminal num único lugar: registro no painel/grupo (escaladas.service), correção
-- (_corrigir_registro), timeout determinístico (workers/timeouts → 'sumiu') e a
-- reativação pós-ressurreição quando ela vier a fechar (ADR 0027).
--
-- Semântica:
--   - → Fechado: marca conversas.recorrente = true a partir do 2º Fechado do par
--     (cliente repetiu negócio). Monotônico: nunca volta a false.
--   - → Perdido: copia o motivo para conversas.ultimo_motivo_perda (só quando há
--     motivo; Perdido sempre exige um).
--
-- Idempotente (CREATE OR REPLACE + DROP TRIGGER IF EXISTS). Sem tabela nova → sem
-- RLS a declarar. Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA
-- `make migrate` (aplicaria seeds). Ver memória `migrations_pendentes_prod_selfhosted`.
-- =============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION barravips.sync_conversa_resultado()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.conversa_id IS NULL THEN
    RETURN NEW;
  END IF;

  IF NEW.estado = 'Fechado' AND (OLD.estado IS DISTINCT FROM 'Fechado') THEN
    -- O próprio NEW já está visível como 'Fechado' nesta transação (AFTER UPDATE):
    -- count >= 2 ⇒ é pelo menos o 2º Fechado do par ⇒ recorrente.
    UPDATE barravips.conversas c
       SET recorrente = true,
           updated_at = now()
     WHERE c.id = NEW.conversa_id
       AND c.recorrente = false
       AND (
         SELECT count(*) FROM barravips.atendimentos a
          WHERE a.conversa_id = NEW.conversa_id
            AND a.estado = 'Fechado'
       ) >= 2;

  ELSIF NEW.estado = 'Perdido'
        AND (OLD.estado IS DISTINCT FROM 'Perdido')
        AND NEW.motivo_perda IS NOT NULL THEN
    UPDATE barravips.conversas
       SET ultimo_motivo_perda = NEW.motivo_perda,
           updated_at = now()
     WHERE id = NEW.conversa_id;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_conversa_resultado_atendimentos ON barravips.atendimentos;
CREATE TRIGGER sync_conversa_resultado_atendimentos
  AFTER UPDATE OF estado ON barravips.atendimentos
  FOR EACH ROW
  WHEN (NEW.estado IN ('Fechado', 'Perdido') AND OLD.estado IS DISTINCT FROM NEW.estado)
  EXECUTE FUNCTION barravips.sync_conversa_resultado();

COMMIT;
