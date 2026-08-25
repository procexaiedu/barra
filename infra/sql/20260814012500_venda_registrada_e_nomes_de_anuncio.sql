-- =============================================================================
-- 20260814012500_venda_registrada_e_nomes_de_anuncio.sql
-- Venda registrada + cadastro de Nome de anuncio (spec 0005, ticket 02).
--
-- A **Venda registrada** e a entidade central do Agente financeiro e mora FORA
-- de `atendimentos` por decisao estrutural (ADR-0043): a venda anunciada no
-- Grupo financeiro nao tem cliente E.164 nem Conversa cliente, nao percorreu a
-- maquina de estados do Atendimento e pode ter DUAS modelos — fabricar um
-- `Fechado` sintetico exigiria cliente-fantasma e quebraria o invariante "um
-- atendimento, uma modelo". Aqui: modelo + valor + data e o MINIMO; cliente e
-- **texto livre** (nunca vira linha em `clientes`); local e duracao entram so se
-- ditos; a mensagem do grupo fica como origem auditavel.
--
-- POR QUE `duracao_minutos` E NAO FK PARA `duracoes`:
-- `duracoes` e o cardapio da IA de venda (nomes fechados: '1 hora', 'Pernoite').
-- O grupo escreve "1h", "2h", "30min" sobre um servico JA REALIZADO; amarrar a
-- venda ao cardapio faria um anuncio fora do cardapio deixar de registrar — e
-- registro nunca pode travar (docs/dominio/grupo-financeiro.md, "Pendencia").
--
-- POR QUE `forma_pagamento` JA NASCE AQUI, NULA:
-- ela e parte da entidade no ADR-0043 ("opcional ate conciliar") e o anuncio
-- SEMPRE precede o pagamento no grupo real ("Foi pix ou din ?" chega dias
-- depois). Quem a preenche e o ticket 03 (Pendencia de forma de pagamento);
-- este ticket so cria a coluna para a venda nao precisar mudar de forma depois.
--
-- NOME DE ANUNCIO — `modelo_nomes_anuncio`:
-- o nome de perfil pelo qual a modelo se anuncia ("Perfil bianca/yasmin" =
-- bianca e o anuncio, Yasmin e ela — a MESMA mulher). O resolver e
-- **closed-world** sobre este cadastro + `modelos.nome`: nome que nao esta aqui
-- NAO vira venda por palpite (o ticket 04 pergunta no grupo e grava a resposta).
-- `nome_normalizado` (minusculo, sem acento, espacos colapsados) e UNIQUE
-- GLOBAL de proposito: se dois cadastros reivindicassem "bianca" o resolver
-- teria que adivinhar, e adivinhar e exatamente o que o dominio proibe. O
-- UNIQUE cobre tambem as linhas inativas — inativar um apelido mantem o nome
-- reservado, que e o comportamento certo para um nome que ja circulou.
--
-- ON DELETE RESTRICT (e nao CASCADE) em `modelo_id` e `mensagem_id`: venda e
-- dinheiro. O padrao da casa para tabela de dinheiro ja e RESTRICT
-- (`financeiro_*`), e a mensagem-fonte e a prova de auditoria do registro —
-- apagar o grupo nao pode evaporar a receita. Anulacao de venda e ESTADO com
-- rastro (ticket 05), nunca DELETE.
--
-- Idempotente (CREATE ... IF NOT EXISTS, DROP TRIGGER/POLICY antes de criar,
-- seed com ON CONFLICT DO NOTHING): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814012500_venda_registrada_e_nomes_de_anuncio.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.vendas_registradas
--   \d barravips.modelo_nomes_anuncio
--   SELECT m.nome, a.nome FROM barravips.modelo_nomes_anuncio a
--     JOIN barravips.modelos m ON m.id = a.modelo_id;
-- =============================================================================

BEGIN;

-- --- Nome de anuncio (cadastro do resolver closed-world) -------------------------------------

CREATE TABLE IF NOT EXISTS barravips.modelo_nomes_anuncio (
  id                uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id         uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  nome              text NOT NULL,
  nome_normalizado  text NOT NULL,
  ativo             boolean NOT NULL DEFAULT true,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT modelo_nomes_anuncio_normalizado_unico UNIQUE (nome_normalizado),
  CONSTRAINT modelo_nomes_anuncio_nome_nao_vazio CHECK (btrim(nome) <> ''),
  CONSTRAINT modelo_nomes_anuncio_normalizado_nao_vazio CHECK (btrim(nome_normalizado) <> '')
);

COMMENT ON TABLE barravips.modelo_nomes_anuncio IS
  'Nome de anuncio (spec 0005): os apelidos de perfil por modelo que o Grupo financeiro usa '
  '("Perfil bianca/yasmin"). Materia-prima do resolver CLOSED-WORLD — nome ausente daqui nunca '
  'e resolvido por similaridade; vira pergunta no grupo (ticket 04).';
COMMENT ON COLUMN barravips.modelo_nomes_anuncio.nome IS
  'O apelido na grafia em que foi cadastrado/dito, para eco humano no recibo e na pergunta.';
COMMENT ON COLUMN barravips.modelo_nomes_anuncio.nome_normalizado IS
  'Chave de casamento EXATO: minusculo, sem acento, espacos colapsados. Escrita pela aplicacao '
  '(nao ha `unaccent` garantido no banco). UNIQUE global: um nome resolve para UMA mulher.';
COMMENT ON COLUMN barravips.modelo_nomes_anuncio.ativo IS
  'Aposenta o apelido sem apagar historico. O UNIQUE continua valendo para linha inativa: nome '
  'que ja circulou no grupo fica reservado a mesma modelo.';

CREATE INDEX IF NOT EXISTS modelo_nomes_anuncio_modelo_idx
  ON barravips.modelo_nomes_anuncio (modelo_id);

DROP TRIGGER IF EXISTS set_updated_at_modelo_nomes_anuncio ON barravips.modelo_nomes_anuncio;
CREATE TRIGGER set_updated_at_modelo_nomes_anuncio
  BEFORE UPDATE ON barravips.modelo_nomes_anuncio
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.modelo_nomes_anuncio ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_nomes_anuncio FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.modelo_nomes_anuncio;
CREATE POLICY fernando_full_access
  ON barravips.modelo_nomes_anuncio
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.modelo_nomes_anuncio TO authenticated;
GRANT ALL PRIVILEGES ON barravips.modelo_nomes_anuncio TO service_role;

-- --- Venda registrada (ADR-0043) -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.vendas_registradas (
  id                uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id         uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  valor             numeric(10,2) NOT NULL CHECK (valor > 0),
  data              date NOT NULL,
  cliente_nome      text,
  local_atendimento text,
  duracao_minutos   int CHECK (duracao_minutos IS NULL OR duracao_minutos > 0),
  forma_pagamento   text,
  mensagem_id       uuid NOT NULL
                    REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT vendas_registradas_forma_pagamento_valida
    CHECK (forma_pagamento IS NULL OR forma_pagamento IN ('pix', 'dinheiro'))
);

COMMENT ON TABLE barravips.vendas_registradas IS
  'Venda registrada (ADR-0043): servico JA REALIZADO anunciado em texto livre no Grupo '
  'financeiro. Entidade propria, fora de `atendimentos` — sem cliente E.164, sem conversa, sem '
  'maquina de estados. Segunda fonte de receita do Modulo Financeiro.';
COMMENT ON COLUMN barravips.vendas_registradas.data IS
  'Dia da venda. Default de registro = dia BRT da mensagem que a anunciou (o grupo posta a venda '
  'no mesmo dia, muitas vezes de madrugada — por isso BRT e nao UTC).';
COMMENT ON COLUMN barravips.vendas_registradas.cliente_nome IS
  'Cliente como TEXTO LIVRE ("Gabriel", "Igor e um amigo"). NUNCA vira linha em `clientes`: '
  'Cliente e telefone E.164 (CONTEXT.md) e o grupo nao tem telefone nenhum (ADR-0043).';
COMMENT ON COLUMN barravips.vendas_registradas.local_atendimento IS
  'Local como dito no anuncio ("no nosso local", "externo bar"). Opcional: falta de local nunca '
  'impede o registro.';
COMMENT ON COLUMN barravips.vendas_registradas.duracao_minutos IS
  'Duracao dita ("1h" -> 60), em minutos. Deliberadamente NAO e FK para `duracoes` (cardapio '
  'fechado da IA de venda): o grupo relata o que aconteceu, nao escolhe do cardapio.';
COMMENT ON COLUMN barravips.vendas_registradas.forma_pagamento IS
  'pix | dinheiro. Nula ate alguem dizer — e a Pendencia mais comum do grupo (ticket 03). '
  'Venda em dinheiro fica "em especie com a modelo", fora da expectativa de comprovante.';
COMMENT ON COLUMN barravips.vendas_registradas.mensagem_id IS
  'Mensagem-fonte do anuncio (origem auditavel e ancora da correcao por quote / anulacao por '
  'delecao, ticket 05). RESTRICT: apagar o log nao pode evaporar receita.';

-- Extrato/fechamento por modelo (a leitura dominante: vendas da modelo por dia).
CREATE INDEX IF NOT EXISTS vendas_registradas_modelo_data_idx
  ON barravips.vendas_registradas (modelo_id, data DESC);
-- "Que venda nasceu desta mensagem?" — correcao por quote e anulacao por delecao (ticket 05).
CREATE INDEX IF NOT EXISTS vendas_registradas_mensagem_idx
  ON barravips.vendas_registradas (mensagem_id);

DROP TRIGGER IF EXISTS set_updated_at_vendas_registradas ON barravips.vendas_registradas;
CREATE TRIGGER set_updated_at_vendas_registradas
  BEFORE UPDATE ON barravips.vendas_registradas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

ALTER TABLE barravips.vendas_registradas ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.vendas_registradas FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.vendas_registradas;
CREATE POLICY fernando_full_access
  ON barravips.vendas_registradas
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.vendas_registradas TO authenticated;
GRANT ALL PRIVILEGES ON barravips.vendas_registradas TO service_role;

-- --- Seed dos Nomes de anuncio vistos no grupo da Yasmin --------------------------------------
-- Apelidos que o export "Modelo Yasmin Ruiva/financeiro" ja usa como fato consumado
-- ("Perfil bianca/yasmin", "Perfil sophia/julia"). Seed GUARDADO: so grava quando existe
-- EXATAMENTE UMA modelo ativa com aquele nome verdadeiro — em banco com homonimo (o `barra_test`
-- tem varias "Yasmin" de residuo de teste) o INSERT vira no-op em vez de apontar o apelido para
-- a mulher errada. Mesma disciplina do resolver: na duvida, nao adivinha.
-- ("Alicia"/"fran loira", do anuncio de 10/08, ficam DE FORA de proposito: sao justamente o caso
-- de nome desconhecido que o ticket 04 resolve perguntando no grupo.)

INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
SELECT m.id, apelido.nome, apelido.normalizado
  FROM (VALUES
          ('Yasmin', 'bianca', 'bianca'),
          ('Julia',  'sophia', 'sophia')
       ) AS apelido(nome_verdadeiro, nome, normalizado)
  JOIN barravips.modelos m
    ON lower(btrim(m.nome)) = lower(apelido.nome_verdadeiro)
   AND m.status = 'ativa'::barravips.modelo_status_enum
 WHERE (
         SELECT count(*)
           FROM barravips.modelos m2
          WHERE lower(btrim(m2.nome)) = lower(apelido.nome_verdadeiro)
            AND m2.status = 'ativa'::barravips.modelo_status_enum
       ) = 1
ON CONFLICT (nome_normalizado) DO NOTHING;

COMMIT;
