-- =============================================================================
-- 20260814120000_cobranca_da_agencia.sql
-- Cobranca da agencia + a segunda classe do comprovante (spec 0005, ticket 08).
--
-- O QUE O GRUPO FAZ HOJE (export "Modelo Yasmin Ruiva/financeiro", 13/08):
-- um gestor posta a cobranca do anuncio no grupo da modelo
-- ("*3RJ Suporte/Anuncio:* 3 DIAS | R$ 385,80 / envia para o site e envia o
-- comprovante"), a modelo pergunta a chave, paga e posta o comprovante. Ninguem
-- registra nada: a divida da modelo com a agencia vive na memoria do gestor, e
-- o Pix que a quita e indistinguivel — para o sistema — de um Pix de fechamento
-- de vendas.
--
-- POR QUE UMA TABELA PROPRIA, E NAO UMA "venda negativa":
-- a Cobranca da agencia e **debito da modelo para com a agencia** (3RJ), nao
-- receita (docs/dominio/grupo-financeiro.md). Emula-la como venda de valor
-- negativo poluiria as tres colunas do Fechamento (vendido/comprovado/especie),
-- a receita do Modulo Financeiro e o dedup de conteudo. Ela e um eixo A PARTE:
-- entra no extrato como coluna de debito e some de la quando o comprovante
-- chega. Tambem nao e `financeiro_despesas`: despesa e da CASA, isto e divida
-- DA MODELO.
--
-- POR QUE `comprovante_id` + `quitada_em` (e nao um booleano `paga`):
-- quitar e um FATO com prova. O comprovante que quitou fica amarrado a cobranca,
-- e e por esse par que o extrato explica para onde foi o R$ 385,80 que antes
-- aparecia como divergencia `comprovante_sem_par` (ticket 09). Um booleano
-- perderia a prova exatamente no dado que existe para provar pagamento.
--
-- POR QUE `chave_conteudo` COM UNIQUE PARCIAL:
-- mesmo gesto e mesmo remedio da Venda registrada (ticket 04/05): a cobranca
-- repostada (ou postada nos dois grupos da mesma modelo) nao pode virar dois
-- debitos, e a cobranca ANULADA por delecao da mensagem-fonte precisa liberar a
-- chave para o repost. Chave legivel (data|valor|modelo|descricao normalizada),
-- nao hash, pelo mesmo motivo de la: quando uma cobranca "sumir" no dedup, quem
-- investiga le a chave no banco e ve por que ela colidiu.
--
-- POR QUE `anulada_em` (e nao DELETE):
-- apagar-e-repostar e o gesto de correcao do grupo (ticket 05). Cobranca cuja
-- mensagem-fonte foi apagada deixa de cobrar a modelo, mas continua no banco
-- provando o que aconteceu. So a cobranca AINDA PENDENTE e anulada pela
-- delecao: apagar a mensagem depois de a modelo ter pago nao pode desfazer um
-- pagamento que tem comprovante amarrado.
--
-- A SEGUNDA CLASSE DO COMPROVANTE (`classificacao = 'cobranca'`):
-- ate aqui o comprovante da cobranca caia em `nao_classificado` — retido,
-- visivel, perguntado (ticket 07, decisao deliberada). Agora ele tem nome: o
-- comprovante que casa com uma cobranca aberta **abate a cobranca, nunca as
-- vendas** (docs/dominio, "Cobranca da agencia"). Sem essa distincao o Pix da
-- cobranca poluiria o Fechamento — ou como venda comprovada que ninguem vendeu,
-- ou como divergencia eterna.
--
-- Idempotente (IF NOT EXISTS, DROP ... IF EXISTS antes de criar): roda 2x sem
-- erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814120000_cobranca_da_agencia.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.cobrancas_da_agencia
--   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conrelid = 'barravips.comprovantes_do_grupo'::regclass;
-- =============================================================================

BEGIN;

-- --- a Cobranca da agencia ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.cobrancas_da_agencia (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  grupo_id        uuid NOT NULL
                  REFERENCES barravips.grupos_financeiros(id) ON DELETE RESTRICT,
  modelo_id       uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  mensagem_id     uuid NOT NULL
                  REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  descricao       text NOT NULL,
  valor           numeric(10,2) NOT NULL CHECK (valor > 0),
  data            date NOT NULL,
  chave_conteudo  text NOT NULL,
  comprovante_id  uuid REFERENCES barravips.comprovantes_do_grupo(id) ON DELETE RESTRICT,
  quitada_em      timestamptz,
  anulada_em      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT cobrancas_da_agencia_descricao_nao_vazia CHECK (btrim(descricao) <> ''),
  -- Quitar e um fato COM PROVA: os dois lados andam juntos. Sem isto seria possivel marcar uma
  -- cobranca como paga sem comprovante nenhum — que e exatamente o "conferi no olho" que este
  -- modulo veio substituir.
  CONSTRAINT cobrancas_da_agencia_quitacao_tem_prova
    CHECK ((quitada_em IS NULL) = (comprovante_id IS NULL))
);

COMMENT ON TABLE barravips.cobrancas_da_agencia IS
  'Cobranca da agencia (spec 0005, ticket 08): valor que a agencia cobra da modelo pelo Grupo '
  'financeiro (anuncio/site — "3RJ Suporte/Anuncio: 3 DIAS | R$ 385,80"). Debito DELA para com a '
  'agencia, nunca receita: entra no Fechamento como coluna de debito e sai quando o comprovante '
  'do pagamento chega. Nao confundir com `financeiro_despesas` (despesa da casa).';
COMMENT ON COLUMN barravips.cobrancas_da_agencia.descricao IS
  'A rubrica como o gestor a escreveu, sem a cifra ("3RJ Suporte/Anuncio: 3 DIAS"). Texto livre: '
  'e o que o recibo ecoa e o que identifica a cobranca para quem le o extrato.';
COMMENT ON COLUMN barravips.cobrancas_da_agencia.data IS
  'Dia (BRT) em que a cobranca foi postada no grupo — mesma regra de data da Venda registrada.';
COMMENT ON COLUMN barravips.cobrancas_da_agencia.chave_conteudo IS
  'Identidade do FATO (data|valor|modelo|descricao normalizada) para o dedup de repost. UNIQUE '
  'entre as VIVAS (indice parcial abaixo): a anulada solta a chave, senao o repost do ticket 05 '
  'nunca conseguiria substituir a cobranca apagada.';
COMMENT ON COLUMN barravips.cobrancas_da_agencia.comprovante_id IS
  'O Comprovante de transferencia que quitou esta cobranca. E a PROVA do pagamento — e o par que '
  'explica, no extrato, o Pix que antes aparecia como divergencia `comprovante_sem_par`.';
COMMENT ON COLUMN barravips.cobrancas_da_agencia.anulada_em IS
  'Mensagem-fonte apagada no grupo (ticket 05). Cobranca anulada nao cobra mais nada e solta a '
  '`chave_conteudo`; so a PENDENTE e anulavel — quitacao com comprovante nao se desfaz apagando '
  'mensagem.';

-- A leitura quente do modulo: "o que esta modelo ainda deve?" — extrato sob comando (ticket 09),
-- rotina da manha (10) e o casamento do comprovante (este ticket) passam todos por aqui.
CREATE INDEX IF NOT EXISTS cobrancas_da_agencia_abertas_idx
  ON barravips.cobrancas_da_agencia (modelo_id, data, id)
  WHERE quitada_em IS NULL AND anulada_em IS NULL;

-- "Que cobranca nasceu desta mensagem?" — anulacao por delecao.
CREATE INDEX IF NOT EXISTS cobrancas_da_agencia_mensagem_idx
  ON barravips.cobrancas_da_agencia (mensagem_id);

CREATE UNIQUE INDEX IF NOT EXISTS cobrancas_da_agencia_chave_conteudo_viva_uniq
  ON barravips.cobrancas_da_agencia (chave_conteudo)
  WHERE anulada_em IS NULL;

DROP TRIGGER IF EXISTS set_updated_at_cobrancas_da_agencia ON barravips.cobrancas_da_agencia;
CREATE TRIGGER set_updated_at_cobrancas_da_agencia
  BEFORE UPDATE ON barravips.cobrancas_da_agencia
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.cobrancas_da_agencia ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.cobrancas_da_agencia FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.cobrancas_da_agencia;
CREATE POLICY fernando_full_access
  ON barravips.cobrancas_da_agencia
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.cobrancas_da_agencia TO authenticated;
GRANT ALL PRIVILEGES ON barravips.cobrancas_da_agencia TO service_role;

-- --- a segunda classe do comprovante -----------------------------------------------------------

ALTER TABLE barravips.comprovantes_do_grupo
  DROP CONSTRAINT IF EXISTS comprovantes_do_grupo_classificacao_valida;

ALTER TABLE barravips.comprovantes_do_grupo
  ADD CONSTRAINT comprovantes_do_grupo_classificacao_valida
    CHECK (classificacao IN ('fechamento', 'cobranca', 'nao_classificado', 'ilegivel'));

-- `cobranca` tem valor pelo mesmo motivo que `fechamento`: sem valor nao ha o que casar, e a
-- classificacao seria palpite sobre uma imagem que ninguem leu.
ALTER TABLE barravips.comprovantes_do_grupo
  DROP CONSTRAINT IF EXISTS comprovantes_do_grupo_fechamento_tem_valor;

ALTER TABLE barravips.comprovantes_do_grupo
  ADD CONSTRAINT comprovantes_do_grupo_fechamento_tem_valor
    CHECK (classificacao NOT IN ('fechamento', 'cobranca') OR valor IS NOT NULL);

COMMENT ON COLUMN barravips.comprovantes_do_grupo.valor_abatido IS
  'Quanto deste comprovante encontrou par: a soma das vendas abatidas em FIFO, ou o valor da '
  'Cobranca da agencia que ele quitou (ticket 08). A diferenca para `valor` continua sendo a '
  'sobra — credito da modelo que segue no saldo corrente, sem picar linha de venda.';

COMMENT ON COLUMN barravips.comprovantes_do_grupo.classificacao IS
  'fechamento (abateu venda pix aberta) | cobranca (quitou uma Cobranca da agencia — abate a '
  'cobranca, NUNCA as vendas, ticket 08) | nao_classificado (nao casou com nada, ou casaria com '
  'as duas coisas: pergunta no grupo e fica retido) | ilegivel (OCR nao leu; o agente pediu '
  'reenvio).';

COMMIT;
