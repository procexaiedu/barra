-- =============================================================================
-- 20260814020000_dedup_de_conteudo_da_venda.sql
-- Dedup cross-grupo da Venda registrada (spec 0005, ticket 04).
--
-- Uma venda com DUAS modelos e anunciada nos dois Grupos financeiros (cada
-- gestora posta o mesmo texto no grupo da sua modelo), e o gesto de correcao do
-- grupo e apagar-e-repostar. Nos dois casos chega uma mensagem NOVA: o dedup de
-- ENTREGA do ticket 01 (`grupo_financeiro_mensagens.chave_dedup`) nao ve nada de
-- errado, e a venda nasce duas vezes. Duas linhas iguais no extrato nao parecem
-- erro — parecem dois atendimentos, e o total da modelo infla calado.
--
-- `chave_conteudo` e a identidade do FATO (data | valor | modelo | cliente), no
-- espirito do dedup de NF do myEYE. Escrita pela aplicacao
-- (`barra.dominio.grupo_financeiro.dedup.chave_de_conteudo`) e nao por trigger:
-- a normalizacao do nome do cliente (minusculo, sem acento, espacos colapsados)
-- e a MESMA do resolver de nomes e mora no Python, porque nao ha `unaccent`
-- garantido neste banco.
--
-- POR QUE UNIQUE GLOBAL (e nao por grupo):
-- o ponto e justamente atravessar grupos — o mesmo anuncio no grupo da outra
-- participante tem que colidir. Como a venda ja e uma linha POR MODELO
-- (ADR-0043), a modelo entra na chave e as duas linhas do mesmo anuncio nao
-- colidem entre si.
--
-- POR QUE TEXTO LEGIVEL E NAO HASH:
-- quando uma venda "sumir" no dedup, quem investigar le a chave no banco e ve na
-- hora por que ela colidiu. O volume e de dezenas de linhas por dia.
--
-- BACKFILL `legado:<id>`:
-- linha gravada ANTES desta migration nasceu sem chave e nao ha como recompor a
-- que a aplicacao geraria (o cliente foi normalizado no Python). Em vez de
-- inventar uma chave plausivel — que faria um repost antigo NAO deduplicar por
-- um motivo invisivel — cada linha velha recebe uma chave unica e explicitamente
-- marcada: ela nao participa do dedup, e isso fica legivel no proprio dado. Em
-- producao o efeito e nenhum: a tabela ainda nao existe la.
--
-- Idempotente (ADD COLUMN IF NOT EXISTS, UPDATE guardado por IS NULL, SET NOT
-- NULL, CREATE UNIQUE INDEX IF NOT EXISTS): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814020000_dedup_de_conteudo_da_venda.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.vendas_registradas
--   SELECT chave_conteudo FROM barravips.vendas_registradas ORDER BY created_at DESC LIMIT 5;
-- =============================================================================

BEGIN;

ALTER TABLE barravips.vendas_registradas
  ADD COLUMN IF NOT EXISTS chave_conteudo text;

UPDATE barravips.vendas_registradas
   SET chave_conteudo = 'legado:' || id
 WHERE chave_conteudo IS NULL;

ALTER TABLE barravips.vendas_registradas
  ALTER COLUMN chave_conteudo SET NOT NULL;

COMMENT ON COLUMN barravips.vendas_registradas.chave_conteudo IS
  'Identidade do FATO para o dedup cross-grupo: "data|valor|modelo|cliente normalizado". O mesmo '
  'anuncio postado no grupo da outra participante (ou repostado apos correcao) colide aqui e nao '
  'cria linha nova. Escrita pela aplicacao (dedup.chave_de_conteudo). "legado:<id>" = linha '
  'anterior a esta coluna, que nao participa do dedup.';

-- Idempotencia REAL, e nao so `IF NOT EXISTS`: a migration seguinte
-- (20260814022300) dropa este indice global e o substitui pela versao PARCIAL
-- (`WHERE anulada_em IS NULL`), porque venda anulada nao pode mais segurar a
-- chave. Rodar o conjunto de novo — que e o que `make migrate` faz — recriaria
-- aqui o indice global, e ele FALHA assim que existirem uma linha anulada e uma
-- viva com a mesma `chave_conteudo` (o cenario "apaga + reposta" do ticket 05).
-- Pior: se passasse, o global ressuscitado faria o repost levantar
-- UniqueViolation de verdade (o arbiter do ON CONFLICT e o parcial), abortando a
-- transacao do webhook -> 500 -> reentrega em loop da Evolution.
-- A guarda e a presenca da coluna `anulada_em`: ela so existe depois da 022300.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM information_schema.columns
     WHERE table_schema = 'barravips'
       AND table_name = 'vendas_registradas'
       AND column_name = 'anulada_em'
  ) THEN
    CREATE UNIQUE INDEX IF NOT EXISTS vendas_registradas_chave_conteudo_uniq
      ON barravips.vendas_registradas (chave_conteudo);
  END IF;
END $$;

COMMIT;
