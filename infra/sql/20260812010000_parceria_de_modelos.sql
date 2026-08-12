-- =============================================================================
-- 20260812010000_parceria_de_modelos.sql
-- Cria barravips.modelo_parcerias (a PARCEIRA de uma modelo) e as duas colunas de
-- carimbo em barravips.atendimentos que travam os dois fluxos da parceria (ADR-0042).
--
-- POR QUE UMA TABELA, E NAO UM `modelos.parceira_id`:
-- a mesma pessoa (a Yasmin, parceira da Catarina) alimenta DOIS fluxos que divergem
-- em tudo -- o ENCAMINHAMENTO (o cliente quer um ato que a Catarina nao faz; ela passa
-- nome/telefone/fotos e sai da venda) e a DUPLA (o cliente quer duas mulheres; a
-- Catarina conduz, cota as duas na tabela DELA e NUNCA passa telefone). Um FK escalar
-- em `modelos` diria so "quem e a parceira" e nao teria onde guardar as tres coisas que
-- a operacao precisa decidir por PAR:
--   1. o par esta autorizado a ENCAMINHAR?          -> encaminhamento_ativo
--   2. para QUAIS atos?                              -> encaminhamento_atos
--   3. o par esta autorizado a VENDER JUNTO (dupla)? -> dupla_ativa
-- Sao autorizacoes independentes: um par pode vender junto e nao poder encaminhar, e
-- vice-versa. A trava "par de modelos em whitelist" que o dono do produto pediu E esta
-- tabela: sem linha, nenhum dos dois fluxos existe (closed-world, a mesma disciplina do
-- cardapio -- a ausencia E a recusa, sem excecao em prosa).
--
-- A relacao tambem e DIRECIONAL: (Catarina -> Yasmin) e' uma decisao; (Yasmin ->
-- Catarina) e' outra, e hoje nem faz sentido (a Yasmin esta `inativa` e nao tem canal).
-- Um `parceira_id` em `modelos` obrigaria simetria ou a duplicaria implicitamente.
--
-- `encaminhamento_atos` guarda as CHAVES DE FAMILIA de
-- `agente/nos/_foco_do_turno.py:_FAMILIAS_FETICHE` (ex.: 'anal', 'grego', 'fisting') --
-- o mesmo vocabulario que o detector deterministico do burst produz. E' o que faz o
-- discriminante ser uma pergunta sobre a FAMILIA mencionada, e nao uma inferencia da
-- LLM: familia de composicao -> fluxo DUPLA; familia de ATO fora do cardapio dela E
-- dentro deste array -> fluxo ENCAMINHAMENTO.
--
-- CARIMBOS EM `atendimentos`:
--   parceira_encaminhada_em -- trava "uma vez por atendimento" do encaminhamento e
--     memoria duravel (o encaminhamento sai no fim e desliza pra fora da janela de 20
--     msgs, mesmo motivo de `amiga_ofertada_em`, migration 20260726020556).
--   parceira_dupla_em -- a dupla foi vendida neste atendimento: e' o gatilho do card
--     NAO-BLOQUEANTE que avisa o Fernando a confirmar a parceira (que pode estar
--     `inativa`/sem disponibilidade cadastrada -- a Catarina fecha e crava horario mesmo
--     assim, e a confirmacao corre por fora).
-- As duas sao MUTUAMENTE EXCLUSIVAS por atendimento -- a tool `envolver_parceira`
-- recusa o segundo modo quando o primeiro ja carimbou. Nao ha CHECK aqui de proposito:
-- um CHECK entre duas colunas nullable transformaria um erro de conduta (recuperavel,
-- vira ToolException) numa excecao de banco no meio do turno.
--
-- A tabela `atendimentos` ja tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration so
-- adiciona colunas, sem recriar policy. `modelo_parcerias` nasce com o envelope padrao de
-- toda tabela nova do schema (ENABLE + FORCE RLS + policy `fernando_full_access` + GRANTs +
-- trigger de `updated_at`), no molde de `20260525202843_modelo_disponibilidade.sql`.
--
-- Idempotente (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / CREATE INDEX
-- IF NOT EXISTS): roda 2x sem erro.
--
-- Schema-only -- o PAR (Catarina -> Yasmin) vive no seed irmao
-- 20260812010500_parceria_catarina_yasmin.sql e NAO deve ser aplicado junto sem
-- conferir os ids em prod.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260812010000_parceria_de_modelos.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.modelo_parcerias
--   SELECT column_name FROM information_schema.columns
--    WHERE table_schema='barravips' AND table_name='atendimentos'
--      AND column_name LIKE 'parceira_%';
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS barravips.modelo_parcerias (
  id                    uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id             uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  parceira_id           uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  encaminhamento_ativo  boolean NOT NULL DEFAULT false,
  encaminhamento_atos   text[]  NOT NULL DEFAULT ARRAY[]::text[],
  dupla_ativa           boolean NOT NULL DEFAULT false,
  ativo                 boolean NOT NULL DEFAULT true,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT modelo_parcerias_par_unico UNIQUE (modelo_id, parceira_id),
  CONSTRAINT modelo_parcerias_nao_e_ela_mesma CHECK (modelo_id <> parceira_id)
);

-- Uma parceira ATIVA por modelo: o agente resolve "quem e a parceira desta modelo" como
-- uma pergunta de resposta unica (o prompt fala "a amiga", no singular). Parcial de
-- proposito -- linhas inativas ficam como historico, sem disputar a resposta.
CREATE UNIQUE INDEX IF NOT EXISTS modelo_parcerias_uma_ativa_por_modelo
  ON barravips.modelo_parcerias (modelo_id)
  WHERE ativo;

COMMENT ON TABLE barravips.modelo_parcerias IS
  'Parceria DIRECIONAL entre duas modelos (ADR-0042): quem e a parceira de quem, e o que '
  'o par esta autorizado a fazer. Sem linha ativa, nenhum dos dois fluxos existe.';
COMMENT ON COLUMN barravips.modelo_parcerias.modelo_id IS
  'A modelo do CANAL — aquela cujo WhatsApp o cliente procurou e cuja IA conduz a conversa.';
COMMENT ON COLUMN barravips.modelo_parcerias.parceira_id IS
  'A parceira. Pode estar `inativa` e sem disponibilidade cadastrada: a venda da dupla nao '
  'depende disso (o card avisa o Fernando a confirmar).';
COMMENT ON COLUMN barravips.modelo_parcerias.encaminhamento_ativo IS
  'Fluxo A (encaminhamento): o par pode passar nome/telefone/fotos da parceira quando o '
  'cliente quer um ato que a modelo do canal nao faz. Sem isto, nunca sai contato nenhum.';
COMMENT ON COLUMN barravips.modelo_parcerias.encaminhamento_atos IS
  'Chaves de familia de agente/nos/_foco_do_turno.py:_FAMILIAS_FETICHE (ex.: {anal}) que '
  'AUTORIZAM o encaminhamento — os atos que a parceira faz. Vazio = encaminhamento nunca arma.';
COMMENT ON COLUMN barravips.modelo_parcerias.dupla_ativa IS
  'Fluxo B (dupla): o par pode ser vendido junto pela modelo do canal, na tabela DELA, sem '
  'escalada e sem NUNCA passar o telefone da parceira.';
COMMENT ON COLUMN barravips.modelo_parcerias.ativo IS
  'Desligar a parceria inteira sem apagar a linha (inativar, nunca deletar).';

-- Cobertura do CASCADE de `modelos` pelo lado da parceira: o indice de `modelo_id` acima e
-- PARCIAL (`WHERE ativo`) e nao cobre as linhas inativas. Mesmo motivo de
-- `modelo_midia_modelo_idx` (0001 §"cobertura do CASCADE de modelos").
CREATE INDEX IF NOT EXISTS modelo_parcerias_parceira_idx
  ON barravips.modelo_parcerias (parceira_id);

DROP TRIGGER IF EXISTS set_updated_at_modelo_parcerias ON barravips.modelo_parcerias;
CREATE TRIGGER set_updated_at_modelo_parcerias
  BEFORE UPDATE ON barravips.modelo_parcerias
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.modelo_parcerias ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_parcerias FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.modelo_parcerias;
CREATE POLICY fernando_full_access
  ON barravips.modelo_parcerias
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.modelo_parcerias TO authenticated;
GRANT ALL PRIVILEGES ON barravips.modelo_parcerias TO service_role;

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS parceira_encaminhada_em timestamptz;

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS parceira_dupla_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.parceira_encaminhada_em IS
  'Instante do 1o encaminhamento da parceira (fluxo A, ADR-0042). Trava "uma vez por '
  'atendimento" + memoria duravel fora da janela de 20 msgs. First-write-wins.';
COMMENT ON COLUMN barravips.atendimentos.parceira_dupla_em IS
  'Instante em que a venda da DUPLA foi assumida (fluxo B, ADR-0042). Gatilho do card '
  'NAO-BLOQUEANTE que pede ao Fernando confirmar a parceira. First-write-wins.';

COMMIT;
