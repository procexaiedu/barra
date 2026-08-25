-- =============================================================================
-- 20260814004920_grupo_financeiro_encanamento.sql
-- Encanamento do Grupo financeiro (spec 0005, ticket 01): o CADASTRO do vinculo
-- grupo<->modelo e o LOG de mensagens que entram pela porta unica do Agente
-- financeiro. Nenhuma extracao aqui — Venda registrada (ADR-0043), Cobranca da
-- agencia, comprovantes e pendencias vem nos tickets seguintes.
--
-- POR QUE UMA TABELA DE VINCULO, E NAO UM `modelos.financeiro_chat_id`:
-- o campo escalar ja existe para a Coordenacao por modelo (`coordenacao_chat_id`)
-- e resolveria "qual o grupo da modelo". Mas o Grupo financeiro tem cadastro
-- proprio a manter vivo (nome do grupo como o gestor o conhece, ligar/desligar a
-- ingestao sem apagar historico) e vai ganhar irmaos no mesmo contexto (nomes de
-- anuncio, cobrancas, chaves Pix conhecidas) — tabela propria e o lugar onde
-- essas colunas cabem sem inflar `modelos`. Alem disso o numero do Agente
-- financeiro e o da ProceX (compartilhado com o myEYE), NAO a instance da modelo:
-- pendurar o JID em `modelos` misturaria dois canais que nao tem a mesma dona.
--
-- CLOSED-WORLD (spec 0005 / docs/dominio/grupo-financeiro.md): sem linha ATIVA
-- aqui, a mensagem daquele grupo e ignorada com log — nunca cai em outro agente e
-- nunca gera resposta. A ausencia E a recusa (mesma disciplina do cardapio e da
-- whitelist de parceria). `ativo=false` inativa sem deletar.
--
-- `grupo_financeiro_mensagens` e o LOG DE ORIGEM da porta unica: cada mensagem
-- aceita fica com de quem veio (grupo + autor JID + nome de exibicao), o que era
-- (tipo/texto/legenda/midia) e a que ela respondia (quote). E a materia-prima dos
-- tickets seguintes (extracao, OCR, correcao por quote) e a prova de auditoria de
-- "o agente viu isto".
--
-- DEDUP — `chave_dedup`, NOT NULL e UNIQUE (o coracao do criterio "entrega
-- duplicada nao gera processamento duplo"):
--   * com id de mensagem  -> `evo:<evolution_message_id>`;
--   * sem id (replay, envelope da EvoGo que nao traz o ID, futuro import do
--     export do grupo) -> `conteudo:<sha256 de grupo|autor|texto|bucket de 5s>`.
-- Coluna NOT NULL de proposito: no Postgres cada NULL e distinto, entao um indice
-- unico sobre `evolution_message_id` nullable NAO colide — foi exatamente assim
-- que o myEYE respondeu 2x por 7 dias com o indice ja aplicado no banco (vault
-- `myeye/ia-notas-resposta-duplicada-janela-1s`). O router do numero ProceX
-- entrega a MESMA requisicao duas vezes (medido: 1-56 ms de diferenca), e e essa
-- chave — nao a boa vontade do router — que absorve.
--
-- Idempotente (CREATE TABLE/INDEX IF NOT EXISTS, DROP TRIGGER/POLICY antes de
-- criar): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814004920_grupo_financeiro_encanamento.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.grupos_financeiros
--   \d barravips.grupo_financeiro_mensagens
-- =============================================================================

BEGIN;

-- --- Cadastro do vinculo grupo<->modelo ------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.grupos_financeiros (
  id          uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id   uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  jid         text NOT NULL,
  nome        text NOT NULL DEFAULT '',
  ativo       boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT grupos_financeiros_jid_unico UNIQUE (jid),
  CONSTRAINT grupos_financeiros_jid_de_grupo CHECK (jid LIKE '%@g.us')
);

COMMENT ON TABLE barravips.grupos_financeiros IS
  'Grupo financeiro (spec 0005): o vinculo CLOSED-WORLD entre o JID do grupo de WhatsApp e a '
  'modelo dona dele. Sem linha ativa, a mensagem do grupo e ignorada com log — o numero da '
  'ProceX e compartilhado (myEYE + grupos financeiros) e nunca deve responder no lugar errado.';
COMMENT ON COLUMN barravips.grupos_financeiros.jid IS
  'JID do grupo (`...@g.us`), a chave do roteamento. UNIQUE: um grupo pertence a UMA modelo — a '
  'venda com duas modelos e anunciada no grupo de cada uma e resolvida por dedup cross-grupo.';
COMMENT ON COLUMN barravips.grupos_financeiros.nome IS
  'Nome do grupo como o gestor o conhece (ex.: "Modelo Yasmin Ruiva/financeiro"). So para o '
  'painel e o log: o roteamento nunca depende dele.';
COMMENT ON COLUMN barravips.grupos_financeiros.ativo IS
  'Desliga a ingestao daquele grupo sem apagar o historico (inativar, nunca deletar). '
  'Inativo = mesmo tratamento de nao cadastrado: ignora com log.';

-- Grupos da modelo (payload do painel) + cobertura do CASCADE de `modelos`.
CREATE INDEX IF NOT EXISTS grupos_financeiros_modelo_idx
  ON barravips.grupos_financeiros (modelo_id);

DROP TRIGGER IF EXISTS set_updated_at_grupos_financeiros ON barravips.grupos_financeiros;
CREATE TRIGGER set_updated_at_grupos_financeiros
  BEFORE UPDATE ON barravips.grupos_financeiros
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.grupos_financeiros ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.grupos_financeiros FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.grupos_financeiros;
CREATE POLICY fernando_full_access
  ON barravips.grupos_financeiros
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.grupos_financeiros TO authenticated;
GRANT ALL PRIVILEGES ON barravips.grupos_financeiros TO service_role;

-- --- Log de origem das mensagens aceitas pela porta unica ------------------------------------

CREATE TABLE IF NOT EXISTS barravips.grupo_financeiro_mensagens (
  id                    uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  grupo_id              uuid NOT NULL REFERENCES barravips.grupos_financeiros(id) ON DELETE CASCADE,
  chave_dedup           text NOT NULL,
  evolution_message_id  text,
  autor_jid             text,
  autor_nome            text,
  de_mim                boolean NOT NULL DEFAULT false,
  tipo                  text NOT NULL,
  texto                 text NOT NULL DEFAULT '',
  caption               text,
  media_url             text,
  quoted_message_id     text,
  recebida_em           timestamptz NOT NULL DEFAULT now(),
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT grupo_financeiro_mensagens_dedup_unico UNIQUE (chave_dedup),
  CONSTRAINT grupo_financeiro_mensagens_tipo_valido
    CHECK (tipo IN ('texto', 'audio', 'imagem'))
);

COMMENT ON TABLE barravips.grupo_financeiro_mensagens IS
  'Log de ORIGEM da porta unica do Agente financeiro (spec 0005): tudo que entrou por um Grupo '
  'financeiro cadastrado, com de quem veio, o que era e a que respondia. Materia-prima dos '
  'tickets de extracao/OCR/correcao e prova de auditoria do que o agente viu.';
COMMENT ON COLUMN barravips.grupo_financeiro_mensagens.chave_dedup IS
  'Chave de idempotencia da entrega: `evo:<id>` quando ha id de mensagem, `conteudo:<sha256>` '
  '(grupo|autor|texto|bucket de 5s) quando nao ha. NOT NULL de proposito — NULL nao colide no '
  'Postgres e o unico sobre id nullable nunca dispara (vault myeye/ia-notas-resposta-duplicada).';
COMMENT ON COLUMN barravips.grupo_financeiro_mensagens.autor_jid IS
  'Quem postou (participant do grupo). Pode ser `@lid` opaco — por isso `autor_nome` existe.';
COMMENT ON COLUMN barravips.grupo_financeiro_mensagens.autor_nome IS
  'Nome de exibicao do autor (pushName) — como o gestor aparece no grupo (Dani, FEH, Parcerias). '
  'E o unico rotulo humano do autor quando o JID vem como `@lid`.';
COMMENT ON COLUMN barravips.grupo_financeiro_mensagens.de_mim IS
  'A mensagem saiu do proprio numero da ProceX (eco de envio ou humano digitando nele). Fica '
  'gravada para o historico do grupo ficar completo; quem ingere dado filtra por aqui.';
COMMENT ON COLUMN barravips.grupo_financeiro_mensagens.recebida_em IS
  'Instante em que a porta unica aceitou a mensagem. Ordena o historico do grupo e alimenta o '
  'bucket da chave de conteudo.';

-- Historico do grupo em ordem (leitura de contexto dos tickets seguintes) + CASCADE do grupo.
CREATE INDEX IF NOT EXISTS grupo_financeiro_mensagens_grupo_idx
  ON barravips.grupo_financeiro_mensagens (grupo_id, recebida_em DESC);

ALTER TABLE barravips.grupo_financeiro_mensagens ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.grupo_financeiro_mensagens FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.grupo_financeiro_mensagens;
CREATE POLICY fernando_full_access
  ON barravips.grupo_financeiro_mensagens
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.grupo_financeiro_mensagens TO authenticated;
GRANT ALL PRIVILEGES ON barravips.grupo_financeiro_mensagens TO service_role;

COMMIT;
