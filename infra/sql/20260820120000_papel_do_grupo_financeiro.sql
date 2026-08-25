-- =============================================================================
-- 20260820120000_papel_do_grupo_financeiro.sql
-- O PAPEL do grupo: alem do Grupo financeiro individual (um grupo, uma modelo),
-- um JID pode ser o **Grupo de fichas** ou o **caixa dos telefonistas**
-- (ADR-0046 §2 e §3).
--
-- POR QUE NA MESMA TABELA E NAO NUMA TABELA NOVA DE "grupos_operacionais":
--   1. `grupos_financeiros.jid` e UNIQUE e e a UNICA porta closed-world do
--      webhook (`buscar_grupo_por_jid`). Duas tabelas com o mesmo JID possivel
--      dariam DOIS cadastros para a mesma pergunta ("que grupo e esse?") e a
--      primeira divergencia entre elas rotearia a mensagem para o agente errado
--      — no numero da ProceX, que e compartilhado (myEYE + estes grupos), rotear
--      errado e falar no lugar errado.
--   2. `grupo_financeiro_mensagens.grupo_id` e NOT NULL e referencia ESTA
--      tabela. Sem uma linha aqui, a mensagem do Grupo de fichas nao teria onde
--      ser logada — e e justamente dela que a Ficha de agendamento nasce
--      (`fichas_de_agendamento.mensagem_id`).
--
-- POR QUE `modelo_id` VIRA NULLABLE: o Grupo de fichas e o caixa dos
-- telefonistas NAO tem dona. A ficha completa pode ser postada la e a modelo sai
-- do campo `Nome da modelo` do card, pelo resolver closed-world (ADR-0046 §2:
-- "o codigo nao pode assumir que a ficha chega no grupo daquela modelo"). O
-- CHECK `grupos_financeiros_papel_exige_modelo` amarra os dois lados: papel
-- 'modelo' EXIGE modelo_id, e qualquer outro papel EXIGE modelo_id NULL — nao
-- existe grupo de fichas "de uma modelo so".
--
-- ⚠️ CONSEQUENCIA PARA QUEM LE ESTA TABELA (o unico jeito de isto morder):
-- consulta que quer "os grupos DAS MODELOS" passa a PRECISAR de `papel =
-- 'modelo'`. Os dois chamadores existentes em `dominio/grupo_financeiro/repo.py`:
--   * `buscar_grupo_por_jid` — ja da INNER JOIN em `modelos`, entao ele ignora
--     sozinho as linhas sem modelo (responde "nao cadastrado", que e SILENCIO,
--     o default seguro). Nao quebra; so nao enxerga o grupo novo ate o
--     roteamento novo existir;
--   * `grupos_financeiros_ativos` (rotina da manha) — NAO tem JOIN e passaria a
--     devolver o Grupo de fichas com `modelo_id = None`, fazendo a rotina falar
--     num grupo que nao tem dona. Ele PRECISA ganhar `AND papel = 'modelo'`.
-- Nenhuma linha com papel <> 'modelo' existe ate alguem cadastrar uma pelo
-- painel, entao esta migration nao muda comportamento nenhum sozinha.
--
-- O QUE ESTA MIGRATION **NAO** FAZ: nao decide se o Grupo de fichas vai existir
-- (a reuniao de 20/08 deixou "a gente pode testar"), nao limita a UM grupo por
-- papel (pode haver caixa por cidade; se virar invariante, e outra migration) e
-- nao cadastra grupo nenhum — schema puro, sem seed.
--
-- Idempotente (enum em DO $$, ADD COLUMN IF NOT EXISTS, DROP CONSTRAINT antes de
-- criar, DROP NOT NULL e no-op na 2a vez): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod), pelo caminho canonico
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260820120000_papel_do_grupo_financeiro.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   SELECT column_name, data_type, is_nullable FROM information_schema.columns
--    WHERE table_schema='barravips' AND table_name='grupos_financeiros'
--      AND column_name IN ('papel','modelo_id');
--   SELECT papel, count(*) FROM barravips.grupos_financeiros GROUP BY papel;
-- =============================================================================

BEGIN;

-- --- Enum do papel ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t
      JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'grupo_financeiro_papel_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.grupo_financeiro_papel_enum AS ENUM (
      'modelo',
      'fichas',
      'caixa_telefonistas'
    );
  END IF;
END
$$;

-- --- A coluna, o afrouxamento do modelo_id e a amarra entre os dois ---------------------------

ALTER TABLE barravips.grupos_financeiros
  ADD COLUMN IF NOT EXISTS papel barravips.grupo_financeiro_papel_enum NOT NULL DEFAULT 'modelo';

ALTER TABLE barravips.grupos_financeiros
  ALTER COLUMN modelo_id DROP NOT NULL;

ALTER TABLE barravips.grupos_financeiros
  DROP CONSTRAINT IF EXISTS grupos_financeiros_papel_exige_modelo;
ALTER TABLE barravips.grupos_financeiros
  ADD CONSTRAINT grupos_financeiros_papel_exige_modelo
    CHECK ((papel = 'modelo') = (modelo_id IS NOT NULL));

COMMENT ON COLUMN barravips.grupos_financeiros.papel IS
  'O que este JID e para o Agente financeiro (ADR-0046). `modelo` = Grupo financeiro individual '
  'da modelo dona dele (o unico papel que existia ate aqui, e o default de toda linha antiga). '
  '`fichas` = Grupo de fichas do telefonista: recebe a ficha COMPLETA, nao tem dona, e a modelo '
  'sai do campo "Nome da modelo" do card pelo resolver closed-world. `caixa_telefonistas` = o '
  'caixa dos telefonistas. ⚠️ Consulta que quer "os grupos das modelos" PRECISA filtrar por '
  'papel = ''modelo'' — sem isso a rotina da manha fala num grupo sem dona.';

COMMENT ON COLUMN barravips.grupos_financeiros.modelo_id IS
  'A modelo dona do grupo. NOT NULL somente quando papel = ''modelo'' (CHECK '
  '`grupos_financeiros_papel_exige_modelo`): Grupo de fichas e caixa dos telefonistas nao tem '
  'dona, e assumir uma seria vazamento cross-modelo.';

-- Roteamento por papel (a lista de grupos de fichas / do caixa, poucos e quentes).
CREATE INDEX IF NOT EXISTS grupos_financeiros_papel_idx
  ON barravips.grupos_financeiros (papel)
  WHERE ativo;

COMMIT;
