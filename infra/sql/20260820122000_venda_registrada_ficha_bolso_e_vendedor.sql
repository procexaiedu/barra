-- =============================================================================
-- 20260820122000_venda_registrada_ficha_bolso_e_vendedor.sql
-- A Venda registrada da v2: de onde ela veio (`ficha_id`), em que BOLSO o
-- dinheiro caiu (ADR-0047), quem recebeu (ADR-0045 §6), por qual anuncio/site
-- ela entrou (ADR-0046 §4) e qual telefonista a vendeu (ADR-0048 §5).
--
-- A venda continua sendo FATO CONSUMADO e continua nascendo no PAGAMENTO
-- (ADR-0044 §2). Nada aqui muda isso: sao colunas de proveniencia e de razao.
--
-- `ficha_id` NULLABLE de proposito (ADR-0044, ultima consequencia): o backfill
-- historico e o leitor de texto livre continuam produzindo venda SEM ficha — o
-- parser do card tem precedencia, mas "o telefonista vai esquecer o card"
-- (ADR-0044 §5) e registro nunca pode travar.
--
-- `bolso` — ADR-0047 revogou `modelos.recebe_no_proprio_pix` (ADR-0045 §4)
-- inteiro. O bolso NAO e cadastro: "varia, nao existe so um padrao". E fato
-- DESTA venda, pela tabela de evidencia (ADR-0047 §2, em ordem de precedencia):
--   comprovante da modelo -> casa, casando com a venda .... dela
--   comprovante do cliente -> casa ........................ empresa
--   fala explicita ("caiu na minha conta", "ficou com voce") o que foi dito
--   forma = dinheiro ...................................... dela, SEMPRE
--   nada disso ............................................ nao_dito
-- `nao_dito` e ESTADO LEGITIMO, nao erro (§3): entra na cobranca consolidada da
-- manha ao lado da forma de pagamento, com a mesma frase, sem pergunta nova.
-- Nunca trava a venda, nunca vira palpite. O DEFAULT DO RAZAO para `nao_dito` e
-- **dela** (§4) — errar para esse lado e conservador (o saldo mostra a modelo
-- devendo, alguem confere, o comprovante corrige); errar para o outro esconde
-- dinheiro na mao dela e ninguem procura. Repare: o default do RAZAO, nao o
-- default da COLUNA. A coluna guarda a ignorancia; quem a interpreta e o calculo.
--
-- ⚠️ POR QUE **NAO** HA CHECK "forma = dinheiro -> bolso = dela", mesmo sendo
-- regra dura do ADR-0047: a forma chega DEPOIS da venda, por
-- `repo.atualizar_forma_pagamento` (ticket 03), que nao escreve bolso. Um CHECK
-- transformaria a primeira resposta "Dinheiro" do grupo num erro de constraint
-- no meio do turno. A regra e do dominio (`bolso.py`), nao do banco.
--
-- `recebido_por_modelo_id` (ADR-0045 §6): numa venda com N modelos, diz DE QUEM
-- e o debito. Na festinha em que uma recebe por todas, as N vendas apontam para
-- ela: ela carrega o debito do bruto total e as outras ficam so com o credito da
-- comissao delas. O repasse entre modelos fica fora do sistema. NULL = ninguem
-- disse -> o razao assume a propria `modelo_id` da venda.
--
-- `percentual_repasse_snapshot` (ADR-0045 §3, NAO revogado): a comissao da
-- modelo reusa `modelos.percentual_repasse` com SNAPSHOT na venda — mesma
-- disciplina do `atendimentos.percentual_repasse_snapshot`. Sem ele, mudar o
-- percentual no cadastro reescreveria temporada passada em silencio. 50% e
-- default de cadastro, nunca constante de codigo. (Nao confundir com a comissao
-- do TELEFONISTA, que e projecao sem snapshot — ADR-0048 §6.)
--
-- `vendedor_id` (ADR-0048 §4 e §5): a comissao do telefonista passa a incidir
-- tambem sobre a Venda registrada, e nao so sobre `atendimentos`. Quem e o
-- telefonista vem do AUTOR da mensagem, resolvido contra `vendedores.whatsapp_jid`
-- (ou herdado da ficha). Autor desconhecido -> venda sem vendedor -> sem
-- comissao, exatamente como o ADR-0012 ja trata o atendimento conduzido pela IA.
-- ON DELETE SET NULL, igual a `atendimentos.vendedor_id`.
--
-- `origem` e `site` (ADR-0046 §4): campos do card que a venda herda para o
-- faturamento saber por qual anuncio e por qual plataforma o cliente entrou.
--
-- SEM BACKFILL: toda venda existente fica com ficha NULL, bolso `nao_dito`,
-- origem/site/vendedor/snapshot NULL. Nenhuma linha antiga muda de significado.
--
-- Idempotente (enum em DO $$, ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT
-- EXISTS). Sem seed: schema puro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260820122000_venda_registrada_ficha_bolso_e_vendedor.sql
--
-- Conferir DEPOIS:
--   \d barravips.vendas_registradas
--   SELECT bolso, count(*) FROM barravips.vendas_registradas GROUP BY bolso;
-- =============================================================================

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'bolso_da_venda_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.bolso_da_venda_enum AS ENUM (
      'dela',
      'empresa',
      'nao_dito'
    );
  END IF;
END
$$;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS ficha_id uuid
    REFERENCES barravips.fichas_de_agendamento(id) ON DELETE RESTRICT;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS bolso barravips.bolso_da_venda_enum NOT NULL DEFAULT 'nao_dito';

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS bolso_mensagem_id uuid
    REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS recebido_por_modelo_id uuid
    REFERENCES barravips.modelos(id) ON DELETE RESTRICT;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS origem barravips.origem_anuncio_enum;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS site text;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS vendedor_id uuid
    REFERENCES barravips.vendedores(id) ON DELETE SET NULL;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS percentual_repasse_snapshot numeric(5,2);

ALTER TABLE barravips.vendas_registradas
  DROP CONSTRAINT IF EXISTS vendas_registradas_percentual_repasse_snapshot_valido;
ALTER TABLE barravips.vendas_registradas
  ADD CONSTRAINT vendas_registradas_percentual_repasse_snapshot_valido
    CHECK (percentual_repasse_snapshot IS NULL
           OR (percentual_repasse_snapshot >= 0 AND percentual_repasse_snapshot <= 100));

COMMENT ON COLUMN barravips.vendas_registradas.ficha_id IS
  'A Ficha de agendamento de onde esta venda nasceu (ADR-0044 §2): valor, cliente, duracao, '
  'local, perfil e deslocamento vem dela. NULA quando a venda veio de texto livre ou de backfill '
  'historico — o parser do card tem precedencia, mas nunca e pre-requisito.';
COMMENT ON COLUMN barravips.vendas_registradas.bolso IS
  'dela | empresa | nao_dito (ADR-0047). Em que bolso o dinheiro DESTA venda caiu — FATO da '
  'venda, nunca herdado do cadastro da modelo (`modelos.recebe_no_proprio_pix` foi revogado '
  'antes de existir). `nao_dito` e estado legitimo e entra na cobranca consolidada da manha; o '
  'razao o trata como `dela` por default conservador (ADR-0047 §4). Regra do dominio, NAO '
  'checada pelo banco: forma = dinheiro e SEMPRE `dela` (especie nao tem outro bolso). '
  '"Ficou com ela" nao e bolso novo: e bolso `dela` mais a ausencia da transferencia (§5).';
COMMENT ON COLUMN barravips.vendas_registradas.bolso_mensagem_id IS
  'A mensagem que decidiu o bolso (a fala "caiu na minha conta"/"ficou com voce", ou a que '
  'trouxe o comprovante). Auditoria da decisao contextual, mesmo papel de '
  '`pagamento_mensagem_id`: quando o bolso estiver errado, e essa coluna que mostra em que '
  'evidencia o agente se apoiou. NULA quando o bolso e `nao_dito` ou veio do painel.';
COMMENT ON COLUMN barravips.vendas_registradas.recebido_por_modelo_id IS
  'De quem e o DEBITO do bruto (ADR-0045 §6): a modelo que efetivamente recebeu o dinheiro desta '
  'venda. Na festinha em que uma recebe por todas, as N vendas apontam para ela — ela carrega o '
  'debito do bruto total e as outras ficam so com o credito da comissao delas. NULA = ninguem '
  'disse -> o razao usa a propria `modelo_id`. O repasse entre modelos fica fora do sistema.';
COMMENT ON COLUMN barravips.vendas_registradas.origem IS
  'proprio | fake — o campo `Origem` do card (ADR-0046 §4): se o anuncio pelo qual o cliente '
  'comprou e da propria modelo ou um perfil fake.';
COMMENT ON COLUMN barravips.vendas_registradas.site IS
  'A plataforma do anuncio (Barra Vips, GSEX, Viva Local, Instagram...). Texto livre, mesma '
  'razao de `fichas_de_agendamento.site`: a lista muda por campanha, nao por migration.';
COMMENT ON COLUMN barravips.vendas_registradas.vendedor_id IS
  'O telefonista que vendeu (ADR-0048 §4/§5). Vem do AUTOR da mensagem do card, resolvido contra '
  '`vendedores.whatsapp_jid`, ou herdado de `fichas_de_agendamento.vendedor_id`. NULL = autor '
  'desconhecido = sem comissao; nunca chuta. A comissao e PROJECAO sobre o bruto (`valor`), sem '
  'snapshot — mudou `vendedores.percentual_comissao`, mudou a projecao (ADR-0048 §6).';
COMMENT ON COLUMN barravips.vendas_registradas.percentual_repasse_snapshot IS
  'Percentual de repasse DA MODELO no momento da venda (ADR-0045 §3), copiado de '
  '`modelos.percentual_repasse`. Snapshot porque o numero dela e negociado com ela e temporada '
  'passada nao pode ser reescrita em silencio — mesma disciplina de '
  '`atendimentos.percentual_repasse_snapshot`. Incide sobre o BRUTO: taxa de cartao NAO e '
  'descontada (decisao do dono do produto). NULL = venda anterior a esta migration.';

-- "Que vendas nasceram desta ficha?" — promocao, correcao e o extrato da ficha.
CREATE INDEX IF NOT EXISTS vendas_registradas_ficha_idx
  ON barravips.vendas_registradas (ficha_id)
  WHERE ficha_id IS NOT NULL;

-- O razao da modelo pelo lado do DEBITO: o que ela recebeu na mao (ADR-0045 §1/§6).
CREATE INDEX IF NOT EXISTS vendas_registradas_recebido_por_idx
  ON barravips.vendas_registradas (recebido_por_modelo_id, data)
  WHERE recebido_por_modelo_id IS NOT NULL AND anulada_em IS NULL;

-- Faturamento bruto por telefonista (base da comissao do ADR-0048 §2).
CREATE INDEX IF NOT EXISTS vendas_registradas_vendedor_data_idx
  ON barravips.vendas_registradas (vendedor_id, data)
  WHERE vendedor_id IS NOT NULL AND anulada_em IS NULL;

-- A fila da cobranca consolidada da manha pelo lado do bolso (ADR-0047 §3),
-- irma de `vendas_registradas_forma_pendente_idx`.
CREATE INDEX IF NOT EXISTS vendas_registradas_bolso_pendente_idx
  ON barravips.vendas_registradas (modelo_id, data)
  WHERE bolso = 'nao_dito' AND anulada_em IS NULL;

COMMIT;
