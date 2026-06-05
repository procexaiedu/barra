-- =============================================================================
-- Rotulagem do golden de calibracao do judge no painel (Loop B / EVAL-10).
--
-- Move a rotulagem do HTML estatico (docs/agente/evals-notas.html, que exige
-- servir por HTTP) para o painel logado. Fernando + a socia marcam cada fala da
-- IA como passou/nao-passou (veredito holistico das 4 rubricas); o acordo entre
-- eles e o TETO da meta de calibracao. E recorrente (varias rodadas).
--
-- Opcao B: persiste a RODADA (snapshot do .jsonl gerado por gerar_conversas.py,
-- subido por upload na tela), as FALAS da IA expandidas dele, e os ROTULOS
-- humanos. O export reconstroi o golden.jsonl que evals/calibracao/calibrar.py
-- ja consome — sem alterar calibrar.py nem merge_rotulos.py.
--
-- Painel-only/Fernando, igual a tarefas (ADR 0017): a IA por modelo nunca le.
-- Tudo idempotente. Aplicar manualmente em prod self-hosted via psycopg.
-- =============================================================================

BEGIN;

-- 1. Rodada: um snapshot nomeado de conversas (1 upload = 1 rodada) ------------
CREATE TABLE IF NOT EXISTS barravips.calibracao_rodadas (
  id          uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  nome        text NOT NULL UNIQUE CHECK (length(btrim(nome)) > 0),
  descricao   text NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.calibracao_rodadas IS
  'Rodada de calibracao do judge (Loop B / EVAL-10): snapshot nomeado das conversas subidas por upload. Painel-only/Fernando; a IA nunca le.';


-- 2. Fala: cada turno papel="ia" expandido do .jsonl da rodada ----------------
-- fala_id = conversa_id::idx (idx = contador das falas da IA, igual gerar_conversas.py).
-- texto_resposta/historico congelam o que o judge avalia — snapshot, nao FK ao agente.
CREATE TABLE IF NOT EXISTS barravips.calibracao_falas (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  rodada_id       uuid NOT NULL REFERENCES barravips.calibracao_rodadas(id) ON DELETE CASCADE,
  fala_id         text NOT NULL,            -- conversa_id::idx
  conversa_id     text NOT NULL,
  cenario         text NOT NULL,
  texto_resposta  text NOT NULL,
  historico       jsonb NOT NULL,           -- array de strings: cliente:/ia:/[ato]
  ordem           int NOT NULL,             -- ordem de exibicao na rodada
  CONSTRAINT calibracao_falas_unq UNIQUE (rodada_id, fala_id)
);

COMMENT ON TABLE barravips.calibracao_falas IS
  'Fala da IA (turno papel=ia) expandida do .jsonl da rodada. fala_id=conversa_id::idx. texto_resposta/historico = snapshot que o judge avalia.';

CREATE INDEX IF NOT EXISTS calibracao_falas_rodada_idx
  ON barravips.calibracao_falas (rodada_id, ordem);


-- 3. Rotulo: veredito holistico de UM rotulador sobre UMA fala -----------------
-- (fala, rotulador) unico -> re-marcar a mesma fala faz UPSERT (idempotente).
-- Os dois rotuladores marcam INDEPENDENTEMENTE; o GET so devolve o do proprio.
CREATE TABLE IF NOT EXISTS barravips.calibracao_rotulos (
  id          uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  fala_pk     uuid NOT NULL REFERENCES barravips.calibracao_falas(id) ON DELETE CASCADE,
  rotulador   text NOT NULL CHECK (rotulador IN ('fernando', 'socia')),
  passou      boolean NOT NULL,             -- veredito holistico (✓/✕)
  observacao  text NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT calibracao_rotulos_unq UNIQUE (fala_pk, rotulador)
);

COMMENT ON TABLE barravips.calibracao_rotulos IS
  'Rotulo holistico (passou/nao) de um rotulador sobre uma fala. (fala,rotulador) unico = upsert idempotente. GET nunca cruza os dois rotuladores (independencia).';

CREATE INDEX IF NOT EXISTS calibracao_rotulos_fala_idx
  ON barravips.calibracao_rotulos (fala_pk);

DROP TRIGGER IF EXISTS set_updated_at_calibracao_rotulos ON barravips.calibracao_rotulos;
CREATE TRIGGER set_updated_at_calibracao_rotulos
  BEFORE UPDATE ON barravips.calibracao_rotulos
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();


-- 4. RLS: ENABLE + FORCE + policy fernando_full_access (igual tarefas) ---------
ALTER TABLE barravips.calibracao_rodadas ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.calibracao_rodadas FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fernando_full_access ON barravips.calibracao_rodadas;
CREATE POLICY fernando_full_access ON barravips.calibracao_rodadas
  AS PERMISSIVE FOR ALL TO authenticated
  USING ((SELECT barravips.is_fernando()))
  WITH CHECK ((SELECT barravips.is_fernando()));

ALTER TABLE barravips.calibracao_falas ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.calibracao_falas FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fernando_full_access ON barravips.calibracao_falas;
CREATE POLICY fernando_full_access ON barravips.calibracao_falas
  AS PERMISSIVE FOR ALL TO authenticated
  USING ((SELECT barravips.is_fernando()))
  WITH CHECK ((SELECT barravips.is_fernando()));

ALTER TABLE barravips.calibracao_rotulos ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.calibracao_rotulos FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fernando_full_access ON barravips.calibracao_rotulos;
CREATE POLICY fernando_full_access ON barravips.calibracao_rotulos
  AS PERMISSIVE FOR ALL TO authenticated
  USING ((SELECT barravips.is_fernando()))
  WITH CHECK ((SELECT barravips.is_fernando()));

COMMIT;
