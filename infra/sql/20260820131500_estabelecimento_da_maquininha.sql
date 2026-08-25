-- =============================================================================
-- 20260820131500_estabelecimento_da_maquininha.sql
-- O CARTAO entra pelo mesmo mecanismo da chave Pix, sem campo novo na ficha
-- (ADR-0049 §6, ticket 06).
--
-- O PROBLEMA. Depois do ADR-0047 o bolso da venda e fato resolvido por
-- EVIDENCIA, e o ticket 03 deu evidencia ao Pix: o comprovante carrega a chave
-- de destino, e o registro tipado diz de quem ela e. O cartao ficou de fora por
-- um detalhe de forma — ele nao tem chave. Mas o dinheiro do cartao cai em dois
-- lugares diferentes e a ata descreve os dois como normais: *"o ideal e ser na
-- nossa conta"* e *"a mina tem a maquina no celular dela, que e aquele
-- PagBank/InfinitePay"*; *"se o cara tiver so aproximacao, ai ela recebe no
-- dela"*. Perguntado de quem e a maquininha de cada uma das quatro modelos
-- ativas, o dono respondeu *"nao sei te responder"*.
--
-- O QUE ESTA MIGRATION FAZ. O print da maquininha — que a modelo ja manda como
-- prova (ticket 11) — carrega o NOME DO ESTABELECIMENTO. E a mesma evidencia,
-- noutro campo. Entao:
--
--   1. nasce `estabelecimentos_conhecidos`, irmao de `chaves_pix_conhecidas`:
--      mesma pergunta ("de quem e este destino?"), mesmo enum de papel, mesma
--      regra de dono, mesmo closed-world (o que nao esta aqui e `desconhecida`);
--   2. `comprovantes_do_grupo` ganha o campo lido — e nada mais: o print de
--      cartao e uma linha da MESMA tabela, com as MESMAS classes
--      (`entrada_da_modelo` quando a maquininha e dela, `cliente_para_a_casa`
--      quando e da casa). Nenhuma classificacao nova, nenhum fluxo novo.
--
-- O QUE ELA NAO FAZ, e as duas ausencias sao decisao registrada:
--   * NAO cria `maquininha_da_modelo` no cadastro da modelo. Isso seria o
--     cadastro de confianca por modelo que o ADR-0047 revogou — e que o dono nao
--     sabe preencher. O registro aqui e do ESTABELECIMENTO (um objeto do mundo,
--     que alguem reconhece no cupom), nao um parametro de pessoa.
--   * NAO acrescenta campo na ficha do telefonista. A Lula ja disse que ela nao
--     sobrevive ao dia de pico, e o print entrega de graca o que o campo pediria.
--
-- ⚠️ POR QUE `estabelecimento_normalizado` E COLUNA, e a chave Pix nao tem uma.
-- A comparacao de chave normaliza so ruido de digitacao, e o mesmo regex roda no
-- Postgres (`regexp_replace`) com o padrao vindo do codigo como PARAMETRO. Nome
-- de estabelecimento precisa de DOBRA DE ACENTO ("Sao Joao" = "SÃO JOÃO"), e o
-- Postgres desta casa nao tem `unaccent` instalado (medido). As saidas seriam
-- reescrever a dobra em SQL — uma segunda normalizacao esperando divergir da do
-- Python, que e exatamente a duplicacao que o ticket 03 acabou de encerrar — ou
-- guardar a forma de comparacao ja normalizada. Guardar e mais barato e nao tem
-- como divergir: quem escreve e `repo.registrar_comprovante`, chamando a UNICA
-- normalizacao que existe (`comprovante.normalizar_estabelecimento`).
--
-- SEM SEED e SEM BACKFILL: schema puro. Nenhum comprovante ja gravado tinha
-- estabelecimento para ler, e as maquininhas vivas sao dado operacional — elas
-- entram pela fila de sugestoes (ticket 05), que e como o dono descobre a
-- resposta que hoje ele nao tem.
--
-- Idempotente: CREATE TABLE/INDEX IF NOT EXISTS, ADD COLUMN IF NOT EXISTS,
-- DROP CONSTRAINT IF EXISTS + ADD, DROP POLICY/TRIGGER IF EXISTS + CREATE.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260820131500_estabelecimento_da_maquininha.sql
--
-- Conferir DEPOIS:
--   \d barravips.estabelecimentos_conhecidos
--   SELECT papel, count(*) FROM barravips.estabelecimentos_conhecidos GROUP BY papel;
--   SELECT count(*) FILTER (WHERE estabelecimento IS NOT NULL)
--     FROM barravips.comprovantes_do_grupo;
-- =============================================================================

BEGIN;

-- --- o registro de estabelecimentos ---------------------------------------------------------------
-- `papel` reusa `barravips.papel_da_chave_enum` (ticket 02) DE PROPOSITO: e a mesma pergunta e a
-- mesma resposta, e dois enums fariam o painel e o dominio carregarem dois vocabularios para dizer
-- "da casa" e "dela". Na pratica so `casa` e `modelo` aparecem; nao ha CHECK restringindo a esses
-- dois porque isso custaria uma migration no dia em que um telefonista tiver maquininha, e a
-- constraint que importa — o dono coerente com o papel — e a mesma da chave.

CREATE TABLE IF NOT EXISTS barravips.estabelecimentos_conhecidos (
  id                 uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  nome               text NOT NULL,
  nome_normalizado   text NOT NULL UNIQUE,
  papel              barravips.papel_da_chave_enum NOT NULL,
  modelo_id          uuid REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  vendedor_id        uuid REFERENCES barravips.vendedores(id) ON DELETE RESTRICT,
  descricao          text,
  ativo              boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE barravips.estabelecimentos_conhecidos
  DROP CONSTRAINT IF EXISTS estabelecimentos_conhecidos_papel_x_dono;
ALTER TABLE barravips.estabelecimentos_conhecidos
  ADD CONSTRAINT estabelecimentos_conhecidos_papel_x_dono
    CHECK (
      CASE papel
        WHEN 'modelo'      THEN modelo_id IS NOT NULL AND vendedor_id IS NULL
        WHEN 'telefonista' THEN vendedor_id IS NOT NULL AND modelo_id IS NULL
        ELSE modelo_id IS NULL AND vendedor_id IS NULL
      END
    );

CREATE INDEX IF NOT EXISTS estabelecimentos_conhecidos_modelo_idx
  ON barravips.estabelecimentos_conhecidos (modelo_id)
  WHERE modelo_id IS NOT NULL;

COMMENT ON TABLE barravips.estabelecimentos_conhecidos IS
  'De quem e a MAQUININHA que imprimiu este print (ADR-0049 §6). Irmao de '
  '`chaves_pix_conhecidas`: mesma pergunta, mesmo enum de papel, mesma regra de dono — muda so o '
  'campo que identifica quem recebeu, porque cartao nao tem chave Pix. Closed-world: '
  'estabelecimento que nao esta aqui e `desconhecida`, nunca "da casa por omissao" — assumir a '
  'casa fixaria o bolso da venda em `empresa` sem evidencia. Nada aqui trava fluxo. NAO e cadastro '
  'de confianca por modelo (revogado pelo ADR-0047): o registro e do estabelecimento, que alguem '
  'reconhece no cupom, e nao um parametro da pessoa.';

COMMENT ON COLUMN barravips.estabelecimentos_conhecidos.nome IS
  'O nome como aparece no comprovante da maquininha — e a grafia que o gestor classificou na fila '
  'de sugestoes, que por sua vez e a grafia que o OCR leu.';

COMMENT ON COLUMN barravips.estabelecimentos_conhecidos.nome_normalizado IS
  'O nome sem acento, sem pontuacao e sem espaco, em minusculo: a forma de COMPARACAO, produzida '
  'por `comprovante.normalizar_estabelecimento` (a unica que existe). UNIQUE aqui e o que impede '
  'a mesma maquininha cadastrada duas vezes com grafias diferentes.';

COMMENT ON COLUMN barravips.estabelecimentos_conhecidos.papel IS
  'casa (a maquininha da operacao) | modelo (a maquininha no celular DELA — *"aquele '
  'PagBank/InfinitePay"* —, exige `modelo_id`) | telefonista (exige `vendedor_id`) | terceiro '
  '(conhecido e nao e nosso: existe para PARAR de alarmar, nao para atribuir dinheiro). Sem '
  'DEFAULT, ao contrario da chave: esta tabela nasce depois do ADR-0049 e nenhum INSERT anterior '
  'a ela quer dizer "casa".';

COMMENT ON COLUMN barravips.estabelecimentos_conhecidos.ativo IS
  'Inativar nunca deletar: a maquininha devolvida mes passado continua explicando o print de tres '
  'semanas atras. Chave inativa continua respondendo o PAPEL — o que ela deixa de ser e destino '
  'esperado de dinheiro novo.';

DROP TRIGGER IF EXISTS set_updated_at_estabelecimentos_conhecidos
  ON barravips.estabelecimentos_conhecidos;
CREATE TRIGGER set_updated_at_estabelecimentos_conhecidos
  BEFORE UPDATE ON barravips.estabelecimentos_conhecidos
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.estabelecimentos_conhecidos ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.estabelecimentos_conhecidos FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.estabelecimentos_conhecidos;
CREATE POLICY fernando_full_access
  ON barravips.estabelecimentos_conhecidos
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.estabelecimentos_conhecidos TO authenticated;
GRANT ALL PRIVILEGES ON barravips.estabelecimentos_conhecidos TO service_role;

-- --- o que o OCR leu no print de cartao -----------------------------------------------------------
-- Duas colunas na tabela que ja existe, e nenhuma classificacao nova: o print de cartao responde as
-- MESMAS duas perguntas (quem pagou x quem recebeu) e cai nas MESMAS classes de entrada —
-- `entrada_da_modelo` (maquininha dela) e `cliente_para_a_casa` (maquininha da casa). Nenhuma delas
-- abate venda em pix nem quita Cobranca da agencia, que e o criterio do ticket.

ALTER TABLE barravips.comprovantes_do_grupo
  ADD COLUMN IF NOT EXISTS estabelecimento text;

ALTER TABLE barravips.comprovantes_do_grupo
  ADD COLUMN IF NOT EXISTS estabelecimento_normalizado text;

COMMENT ON COLUMN barravips.comprovantes_do_grupo.estabelecimento IS
  'O nome do estabelecimento impresso no print da maquininha, como o OCR leu (ADR-0049 §6). NULL '
  'em comprovante de transferencia — ali quem identifica o destino e `chave_destino`. Sao '
  'exclusivos: um comprovante de venda no cartao nao tem chave Pix, e o leitor descarta a chave '
  'quando marca cartao (`ExtracaoDoComprovante.como_leitura`).';

COMMENT ON COLUMN barravips.comprovantes_do_grupo.estabelecimento_normalizado IS
  'A forma de comparacao de `estabelecimento` (sem acento/pontuacao/espaco, minusculo), escrita '
  'pelo Python com `comprovante.normalizar_estabelecimento`. Existe como coluna porque a dobra de '
  'acento nao e expressavel no Postgres desta casa (sem `unaccent`), e reescreve-la em SQL criaria '
  'uma segunda normalizacao — a duplicacao que o ticket 03 encerrou. E por ela que a fila de '
  'sugestoes agrupa "PagBank" e "PAG BANK" como a mesma maquininha.';

-- A fila de sugestoes do painel (ticket 05) agrupa por aqui, e o alarme de primeira aparicao conta
-- por aqui. Parcial porque a esmagadora maioria dos comprovantes e transferencia.
CREATE INDEX IF NOT EXISTS comprovantes_do_grupo_estabelecimento_idx
  ON barravips.comprovantes_do_grupo (estabelecimento_normalizado)
  WHERE estabelecimento_normalizado IS NOT NULL;

COMMIT;
