-- =============================================================================
-- 20260820121000_ficha_de_agendamento.sql
-- A **Ficha de agendamento** vira entidade (ADR-0044 §1, revisto pelo ADR-0046),
-- com os campos exatos do card em `docs/dominio/fichas-do-telefonista.md`.
--
-- O QUE ELA E: o telefonista posta um card padronizado ANTES do servico; ele
-- carrega TODO o dado (cliente, perfil, site, data, hora, duracao, local, tipo
-- de local, endereco, valores) e ainda NAO e receita. A Venda registrada nasce
-- depois, no PAGAMENTO, herdando daqui (ADR-0044 §2). O caso que decide: ficha
-- do Igor, R$ 700, 1h, as 19h; as 22h a modelo escreve so "recebi, foi
-- dinheiro". Sem a ficha guardada, a unica saida seria interrogar a modelo — a
-- metralhadora de perguntas que o dominio proibe.
--
-- POR QUE ENTIDADE PROPRIA E NAO "venda em estado previsto" (alternativa
-- rejeitada no ADR-0044): misturar combinado com recebido faz toda consulta de
-- receita depender de filtrar estado, e o primeiro `WHERE` esquecido soma
-- dinheiro que nao aconteceu.
--
-- POR QUE A FICHA **NAO** TEM `modelo_id` E SIM `ficha_participantes`:
-- sao tres documentos (ADR-0046 §1) e dois deles sao ficha: a individual (uma
-- modelo) e a de grupo (`Modelo 1..N` + `Valor de cada modelo`). Uma coluna
-- `modelo_id` mais uma tabela de participantes daria DOIS lugares onde uma
-- modelo aparece na mesma ficha, e a festinha e exatamente o caso em que os dois
-- divergem. Aqui a lista e SEMPRE a tabela filha: ficha individual = exatamente
-- UMA linha em `ficha_participantes`. A contagem de modelos sai da lista — o
-- card nao tem campo "quantidade de modelos" de proposito
-- ("voce colocando o nome delas, acho que ja e suficiente").
--
-- ISSO E TAMBEM O QUE FAZ O CLOSED-WORLD FUNCIONAR (ADR-0046 §2): o alvo deixa
-- de ser escopado por GRUPO e passa a ser escopado por MODELO. A lista numerada
-- de fichas abertas que a LLM enxerga no grupo individual da Yasmin e a lista
-- das fichas DA YASMIN, venham elas de onde vierem (inclusive do Grupo de
-- fichas, que nao tem dona). Consulta canonica:
--   SELECT f.* FROM barravips.fichas_de_agendamento f
--     JOIN barravips.ficha_participantes p ON p.ficha_id = f.id
--    WHERE p.modelo_id = %s AND f.estado IN ('aberta','confirmada')
--    ORDER BY f.data, f.hora, f.id;   -- a LLM aponta por INDICE, nunca por id.
--
-- POR QUE `tipo_atendimento` REUSA `barravips.tipo_atendimento_enum`:
-- o card tem `( ) Local proprio  ( ) Saida`, que e o MESMO fato que
-- `atendimentos.tipo_atendimento` (interno = no local dela | externo = ela se
-- desloca) e que `bloqueios.tipo_atendimento` ja reusa. Inventar um enum
-- proprio daria dois vocabularios para "quem se desloca?".
--
-- POR QUE `tipo_local` GANHA ENUM NOVO (`ficha_tipo_local_enum`): o
-- `tipo_local_enum` original ('hotel','casa','apartamento','outro') foi DROPADO
-- em `0033_tipo_local_text.sql` e a lista do card e outra
-- (casa|hotel|motel|festa|passeio|jantar_almoco). Enum e nao text porque aqui a
-- lista e fechada pelo proprio card, com `( )` para marcar — nao ha "criar novo"
-- como havia no combobox do painel que motivou a 0033.
--
-- POR QUE OS TRES VALORES DE DESLOCAMENTO MORAM AQUI **E TAMBEM** EM
-- `deslocamentos_da_venda`: aqui eles sao o COMBINADO (campos do card); la eles
-- sao o FATO, com a atribuicao casa x modelo que o card nao tem. Mesma relacao
-- de `fichas.valor_total` -> `vendas_registradas.valor`.
--
-- `chave_conteudo`: identidade do fato para absorver o REPOST (um dos quatro
-- gestos do ADR-0044 §4). UNIQUE entre as nao-canceladas, como a venda e a
-- cobranca ja fazem — a cancelada solta a chave.
--
-- SEM RECIBO: a ficha e gravada CALADA (ADR-0044 §1) — o telefonista nao pediu
-- confirmacao de nada. Isso e conduta, nao schema; fica registrado aqui para que
-- ninguem procure uma coluna de "recibo enviado" que nao existe.
--
-- Idempotente (enums em DO $$, CREATE TABLE/INDEX IF NOT EXISTS, DROP
-- TRIGGER/POLICY antes de criar). Sem seed: schema puro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py infra/sql/20260820121000_ficha_de_agendamento.sql
--
-- Conferir DEPOIS:
--   \d barravips.fichas_de_agendamento
--   \d barravips.ficha_participantes
--   \d barravips.ficha_de_agendamento_eventos
-- =============================================================================

BEGIN;

-- --- Enums da ficha --------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'ficha_estado_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.ficha_estado_enum AS ENUM (
      'aberta',
      'confirmada',
      'realizada',
      'cancelada'
    );
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'origem_anuncio_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.origem_anuncio_enum AS ENUM (
      'proprio',
      'fake'
    );
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'ficha_tipo_local_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.ficha_tipo_local_enum AS ENUM (
      'casa',
      'hotel',
      'motel',
      'festa',
      'passeio',
      'jantar_almoco'
    );
  END IF;
END
$$;

-- --- A ficha ---------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.fichas_de_agendamento (
  id                    uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  estado                barravips.ficha_estado_enum NOT NULL DEFAULT 'aberta',
  mensagem_id           uuid NOT NULL
                        REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  vendedor_id           uuid REFERENCES barravips.vendedores(id) ON DELETE SET NULL,

  -- 👤 CLIENTE
  cliente_nome          text,
  cliente_whatsapp      text,

  -- 📝 CONTRATACAO
  nome_anuncio          text,
  site                  text,
  origem                barravips.origem_anuncio_enum,

  -- 🕒 HORARIO
  data                  date,
  hora                  time,
  duracao_minutos       int CHECK (duracao_minutos IS NULL OR duracao_minutos > 0),

  -- 📍 LOCAL
  tipo_atendimento      barravips.tipo_atendimento_enum,
  tipo_local            barravips.ficha_tipo_local_enum,
  endereco              text,
  endereco_complemento  text,

  -- 💰 VALORES
  valor_total           numeric(10,2) CHECK (valor_total IS NULL OR valor_total >= 0),
  valor_transporte      numeric(10,2) CHECK (valor_transporte IS NULL OR valor_transporte >= 0),
  valor_antecipado      numeric(10,2) CHECK (valor_antecipado IS NULL OR valor_antecipado >= 0),
  forma_antecipado      text,

  -- 💳 PAGAMENTO
  forma_pagamento       text,

  -- ✏️ OBSERVACOES
  observacoes           text,

  chave_conteudo        text NOT NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT fichas_de_agendamento_forma_pagamento_valida
    CHECK (forma_pagamento IS NULL
           OR forma_pagamento IN ('dinheiro', 'pix', 'debito', 'credito', 'link')),
  CONSTRAINT fichas_de_agendamento_forma_antecipado_valida
    CHECK (forma_antecipado IS NULL OR forma_antecipado IN ('pix', 'link')),
  CONSTRAINT fichas_de_agendamento_chave_conteudo_nao_vazia
    CHECK (btrim(chave_conteudo) <> '')
);

COMMENT ON TABLE barravips.fichas_de_agendamento IS
  'Ficha de agendamento (ADR-0044 §1, ADR-0046): o card padronizado que o telefonista posta '
  'ANTES do servico. Carrega todo o dado do combinado e NAO e receita — a Venda registrada nasce '
  'no pagamento, herdando daqui (ADR-0044 §2). Gravada CALADA, sem recibo. Uma ficha, N '
  'participantes (`ficha_participantes`): a modelo NUNCA e coluna daqui.';

COMMENT ON COLUMN barravips.fichas_de_agendamento.estado IS
  'aberta -> confirmada -> realizada, ou cancelada (ADR-0044 §1). `realizada` e promovida por '
  'QUALQUER UM dos dois gestos, o que vier primeiro (ADR-0046 §5): a fala da modelo ("recebi, '
  'foi dinheiro") ou o ✅ do telefonista; o segundo nao duplica, pela chave de conteudo da venda. '
  'Ficha aberta que envelhece vira pendencia da rotina da manha ("o do Igor de ontem rolou?") e '
  'nunca trava nada.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.mensagem_id IS
  'A mensagem do card que originou a ficha — origem auditavel e ancora dos quatro gestos '
  '(reacao, repost, quote, edicao). RESTRICT: apagar o log nao pode evaporar o combinado. Pode '
  'vir de um grupo com papel `fichas` (sem dona) — nao deduza a modelo pelo grupo.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.vendedor_id IS
  'O telefonista que postou o card, resolvido pelo autor da mensagem contra '
  '`vendedores.whatsapp_jid` (ADR-0048 §5). A Venda registrada herda daqui. Autor desconhecido = '
  'NULL = sem comissao; nunca chuta.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.cliente_nome IS
  'Cliente como TEXTO LIVRE. NUNCA vira linha em `clientes`: Cliente e telefone E.164 '
  '(CONTEXT.md) e o card so tem nome — mesmo criterio de `vendas_registradas.cliente_nome`.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.cliente_whatsapp IS
  'O WhatsApp do cliente como o card escreve. So existe na ficha COMPLETA — o Comunicado da '
  'modelo nao o carrega ("o numero ja nao entra"). Nao vira Cliente E.164 nem Conversa.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.nome_anuncio IS
  'Nome do perfil/anuncio sob o qual o cliente comprou (ex.: Sofia). E o mesmo vocabulario de '
  '`modelo_nomes_anuncio` — o resolver closed-world casa por aqui quando o card nao traz o nome '
  'real da modelo.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.site IS
  'A plataforma onde o anuncio esta (Barra Vips, GSEX, Viva Local, Garota com Local, Instagram, '
  'Tinder...). Texto livre de proposito: a lista muda por campanha, nao por migration.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.origem IS
  'proprio | fake — se o anuncio pelo qual o cliente comprou e da propria modelo ou um perfil '
  'fake ("o fake so vai ser sites especificos"). O site quase sempre ja diz.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.data IS
  'Dia do atendimento COMBINADO (nao o dia do post). A Venda registrada tem `data` propria, do '
  'fato consumado; quando a ficha promove, ela e a herdeira natural desta.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.hora IS
  'Hora combinada, sem timezone: o card escreve hora local (BRT) e a operacao inteira e BRT. '
  'Nao entra no Comunicado da modelo — la e previa, "a hora ainda nao se sabe".';
COMMENT ON COLUMN barravips.fichas_de_agendamento.tipo_atendimento IS
  'O `( ) Local proprio  ( ) Saida` do card, no vocabulario ja existente de '
  '`atendimentos.tipo_atendimento`: interno = local proprio da modelo | externo = saida (ela se '
  'desloca) | remoto = ninguem se desloca (nao aparece no card, mas o enum e o mesmo).';
COMMENT ON COLUMN barravips.fichas_de_agendamento.tipo_local IS
  'casa | hotel | motel | festa | passeio | jantar_almoco (ADR-0046 §4). Enum NOVO: o '
  '`tipo_local_enum` original foi dropado na 0033 e a lista do card e outra.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.endereco_complemento IS
  'O campo `Numero / bloco / complemento` do card, separado do endereco porque e ele que a '
  'modelo precisa na portaria e e ele que costuma vir depois, por quote.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.valor_total IS
  'O bruto que o cliente paga por TUDO (numa festinha de R$ 2.000 com tres modelos, 2.000). O '
  'valor de cada uma vive em `ficha_participantes.valor`.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.valor_transporte IS
  'Quanto o Uber ida-e-volta custou de fato — CUSTO (ADR-0046 §6). Nao e o mesmo numero que '
  '`valor_antecipado`, e a diferenca entre os dois e margem ou prejuizo.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.valor_antecipado IS
  'Quanto o cliente mandou pelo transporte (tipicamente R$ 100) — RECEITA (ADR-0046 §6). Zero '
  'quando a casa bancou o Uber sem cobrar. Fora da base de comissao dos dois lados (ADR-0045 §5, '
  'ADR-0048 §3): reembolso de custo nao e venda.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.forma_antecipado IS
  'pix | link — o `Forma do antecipado` do card. Padrao Pix.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.forma_pagamento IS
  'dinheiro | pix | debito | credito | link (ADR-0046 §4). O que o card marcou; a venda pode '
  'nascer com outra, porque quem fecha a forma e quem a DISSER no pagamento.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.observacoes IS
  'Tudo que a modelo tem que saber para nao chegar boiando ("o cliente pediu para nao passar '
  'perfume"). Vai inteiro para o Comunicado da modelo.';
COMMENT ON COLUMN barravips.fichas_de_agendamento.chave_conteudo IS
  'Identidade do FATO combinado, para absorver o REPOST do card (gesto 2 dos quatro do ADR-0044 '
  '§4) sem criar ficha nova. Escrita pela aplicacao, legivel. UNIQUE entre as NAO canceladas '
  '(indice parcial): a cancelada solta a chave, senao o repost nunca substituiria a ficha morta.';

-- A leitura dominante: as fichas em aberto, por dia (rotina da manha e alvo do pagamento).
CREATE INDEX IF NOT EXISTS fichas_de_agendamento_abertas_idx
  ON barravips.fichas_de_agendamento (data, hora, id)
  WHERE estado IN ('aberta', 'confirmada');
-- "Que ficha nasceu desta mensagem?" — reacao, quote, edicao e repost do card.
CREATE INDEX IF NOT EXISTS fichas_de_agendamento_mensagem_idx
  ON barravips.fichas_de_agendamento (mensagem_id);
CREATE UNIQUE INDEX IF NOT EXISTS fichas_de_agendamento_chave_conteudo_viva_uniq
  ON barravips.fichas_de_agendamento (chave_conteudo)
  WHERE estado <> 'cancelada';

DROP TRIGGER IF EXISTS set_updated_at_fichas_de_agendamento ON barravips.fichas_de_agendamento;
CREATE TRIGGER set_updated_at_fichas_de_agendamento
  BEFORE UPDATE ON barravips.fichas_de_agendamento
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.fichas_de_agendamento ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.fichas_de_agendamento FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.fichas_de_agendamento;
CREATE POLICY fernando_full_access
  ON barravips.fichas_de_agendamento
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.fichas_de_agendamento TO authenticated;
GRANT ALL PRIVILEGES ON barravips.fichas_de_agendamento TO service_role;

-- --- Participantes (uma linha SEMPRE, N na ficha de grupo) ------------------------------------

CREATE TABLE IF NOT EXISTS barravips.ficha_participantes (
  id          uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  ficha_id    uuid NOT NULL
              REFERENCES barravips.fichas_de_agendamento(id) ON DELETE CASCADE,
  modelo_id   uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  valor       numeric(10,2) CHECK (valor IS NULL OR valor >= 0),
  ordem       smallint NOT NULL DEFAULT 1,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ficha_participantes_modelo_unica UNIQUE (ficha_id, modelo_id),
  CONSTRAINT ficha_participantes_ordem_positiva CHECK (ordem >= 1)
);

COMMENT ON TABLE barravips.ficha_participantes IS
  'As modelos de uma Ficha de agendamento (ADR-0046 §1). SEMPRE ao menos uma linha: a ficha '
  'individual e o caso N=1, a ficha de grupo tem `Modelo 1..N`. E aqui que o closed-world por '
  'MODELO (ADR-0046 §2) enxerga "as fichas da Yasmin", venha o card do grupo dela ou do Grupo de '
  'fichas. CASCADE porque a lista e filha da ficha e o telefonista reescreve a lista no repost.';
COMMENT ON COLUMN barravips.ficha_participantes.modelo_id IS
  'Resolvido pelo campo `Nome da modelo` (real) ou pelo `Nome do perfil/anuncio` do card, '
  'CLOSED-WORLD contra `modelos.nome` + `modelo_nomes_anuncio`. Nome que nao esta cadastrado NAO '
  'vira participante por palpite — vira pergunta no grupo.';
COMMENT ON COLUMN barravips.ficha_participantes.valor IS
  'O `Valor desta modelo` (individual) ou `Valor de cada modelo` (grupo). NAO e derivado de '
  '`valor_total / N`: o rateio e do telefonista e pode ser desigual. E este numero — nao o total '
  '— que a modelo ve no Comunicado dela.';
COMMENT ON COLUMN barravips.ficha_participantes.ordem IS
  'A posicao no card (`Modelo 1`, `Modelo 2`...). So para reproduzir a ficha na mesma ordem em '
  'que o telefonista a escreveu; nao tem significado de dominio.';

CREATE INDEX IF NOT EXISTS ficha_participantes_modelo_idx
  ON barravips.ficha_participantes (modelo_id);
CREATE INDEX IF NOT EXISTS ficha_participantes_ficha_idx
  ON barravips.ficha_participantes (ficha_id, ordem);

ALTER TABLE barravips.ficha_participantes ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.ficha_participantes FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.ficha_participantes;
CREATE POLICY fernando_full_access
  ON barravips.ficha_participantes
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.ficha_participantes TO authenticated;
GRANT ALL PRIVILEGES ON barravips.ficha_participantes TO service_role;

-- --- Rastro dos quatro gestos ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.ficha_de_agendamento_eventos (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  ficha_id        uuid NOT NULL
                  REFERENCES barravips.fichas_de_agendamento(id) ON DELETE RESTRICT,
  tipo            text NOT NULL,
  campo           text,
  valor_anterior  text,
  valor_novo      text,
  mensagem_id     uuid REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ficha_de_agendamento_eventos_tipo_valido
    CHECK (tipo IN ('alteracao', 'confirmacao', 'realizacao', 'cancelamento')),
  CONSTRAINT ficha_de_agendamento_eventos_alteracao_tem_campo
    CHECK (tipo <> 'alteracao' OR campo IS NOT NULL)
);

COMMENT ON TABLE barravips.ficha_de_agendamento_eventos IS
  'Rastro de tudo que mudou numa Ficha de agendamento — os quatro gestos do ADR-0044 §4 (reacao '
  '✅/❌, repost alterado, resposta por quote, edicao da mensagem). APPEND-ONLY, espelhando '
  '`venda_registrada_eventos`: auditoria que se edita nao e auditoria. Uma linha por CAMPO '
  'alterado; confirmacao/realizacao/cancelamento sao uma linha so, sem campo.';
COMMENT ON COLUMN barravips.ficha_de_agendamento_eventos.mensagem_id IS
  'A mensagem que causou o evento (o repost, o quote, a reacao, a edicao). Nula quando a origem '
  'for o painel.';

CREATE INDEX IF NOT EXISTS ficha_de_agendamento_eventos_ficha_idx
  ON barravips.ficha_de_agendamento_eventos (ficha_id, created_at DESC);

ALTER TABLE barravips.ficha_de_agendamento_eventos ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.ficha_de_agendamento_eventos FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.ficha_de_agendamento_eventos;
CREATE POLICY fernando_full_access
  ON barravips.ficha_de_agendamento_eventos
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT ON barravips.ficha_de_agendamento_eventos TO authenticated;
GRANT ALL PRIVILEGES ON barravips.ficha_de_agendamento_eventos TO service_role;

COMMIT;
