-- ---------------------------------------------------------------------------
-- 20260702210000_julgamentos_turno.sql
-- Telemetria do judge PÓS-ENVIO (produção assistida, semana 1): 1 linha por
-- turno da IA já ENVIADO ao cliente, julgado assincronamente pelo LLM-judge
-- (workers/judge_pos_envio.py) em 3 eixos fixos:
--   - rastro_llm : um cliente atento perceberia rastro de IA? (incidente
--                  NÃO-CONTIDO — o gate pré-envio não segurou);
--   - voz        : fidelidade à voz da persona (1-5);
--   - conduta    : coerência de conduta comercial (1-5).
-- Fonte durável dos gatilhos de rollback (workers/rollback_watch.py) e do
-- digest semanal (workers/digest_semanal.py). Telemetria dev: nunca vira
-- tarefa para Fernando nem volta ao contexto da IA ao vivo.
--
-- Idempotente (IF NOT EXISTS em tudo). Aplicação em prod: manual via
-- scripts/aplicar_sql.py (nunca make migrate — ver runbook).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.julgamentos_turno (
  id            uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  -- turno_id determinístico do coordenador (job_id:loop_idx) — dedupe natural.
  turno_id      text NOT NULL UNIQUE,
  conversa_id   uuid NOT NULL REFERENCES barravips.conversas(id) ON DELETE CASCADE,
  modelo_id     uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  rastro_llm    boolean NOT NULL,
  voz           smallint NOT NULL CHECK (voz BETWEEN 1 AND 5),
  conduta       smallint NOT NULL CHECK (conduta BETWEEN 1 AND 5),
  comentario    text NOT NULL DEFAULT '',
  julgado_em    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.julgamentos_turno IS
  'interna: sem RLS porque é telemetria worker-only (escrita pelo job julgar_turno_pos_envio, lida pelos crons rollback_watch/digest_semanal) e nunca é exposta via PostgREST/painel. Judge pós-envio (100% dos turnos enviados): rastro-de-LLM/voz/conduta por turno; nunca gera ação para Fernando.';
COMMENT ON COLUMN barravips.julgamentos_turno.rastro_llm IS
  'true = o judge viu rastro de IA num turno JÁ enviado (incidente não-contido; gatilho de rollback quando >=2/semana).';

-- Janela deslizante de 7d do rollback_watch e agregação do digest.
CREATE INDEX IF NOT EXISTS julgamentos_turno_julgado_idx
  ON barravips.julgamentos_turno (julgado_em DESC);
CREATE INDEX IF NOT EXISTS julgamentos_turno_modelo_idx
  ON barravips.julgamentos_turno (modelo_id, julgado_em DESC);
