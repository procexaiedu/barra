-- =============================================================================
-- 20260820130000_papel_da_chave_pix.sql
-- `chaves_pix_conhecidas` deixa de ser lista plana e vira o REGISTRO UNICO de
-- "de quem e esta chave" (ADR-0049 §2, ticket 02).
--
-- O booleano e a raiz da confusao operacional. `chave_e_conhecida() -> bool`
-- responde "esta na lista da casa?", e o "nao" engloba duas coisas que nao tem
-- nada a ver uma com a outra: a chave da PROPRIA MODELO — informacao valiosa,
-- que resolve o bolso da venda (ADR-0047 §2) — e a chave de um terceiro
-- qualquer, que e ruido. O aviso "⚠️ Esse Pix foi pra uma chave fora da lista
-- da casa" dispara igual nos dois, e o gestor aprende a ignora-lo.
--
-- Esta migration so muda o CADASTRO. Quem le o papel e o ticket 03
-- (`papel_da_chave` substituindo `chave_e_conhecida`); ate la nada no caminho
-- de producao consulta as colunas novas, e por isso ela e segura de aplicar
-- sozinha.
--
-- O QUE CADA COISA E:
--
--   papel        casa | modelo | telefonista | terceiro
--   modelo_id    o dono, quando papel = 'modelo'      (exclusivo com vendedor_id)
--   vendedor_id  o dono, quando papel = 'telefonista' (exclusivo com modelo_id)
--   padrao       a UMA chave da casa que a operacao usa por default — o
--                *"vou botar a Pix, que normalmente e o padrao que a gente mais
--                recebe"* do dono. No maximo uma no banco inteiro, garantido por
--                indice unico parcial (`... WHERE padrao`), nao por convencao.
--
-- Uma modelo pode ter VARIAS chaves (CPF, telefone, aleatoria — e ela troca de
-- banco). Por isso o dono e coluna da chave e nao o contrario: nao ha UNIQUE em
-- `modelo_id`.
--
-- ⚠️ NENHUMA LINHA EXISTENTE PERDE SIGNIFICADO — nem nenhum INSERT ja escrito. A
-- tabela nasceu (20260814031400) como "as chaves da casa" e so isso. Duas coisas
-- decorrem desse significado, e as duas sao a MESMA decisao:
--   * o backfill escreve `papel = 'casa'` nas linhas que ja estavam la;
--   * o DEFAULT da coluna e 'casa', porque um INSERT que nao nomeia o papel e um
--     INSERT escrito quando a tabela SO tinha chave da casa, e ele continua
--     querendo dizer exatamente isso. Sem o DEFAULT, todo escritor anterior a
--     este ADR (runbook, fixture de teste) passa a estourar NotNullViolation —
--     "nao perder significado" inclui nao quebrar quem ja escreve aqui.
--
-- A exigencia de declarar o papel mora onde ha um humano para declara-lo: no
-- painel. `ChavePixCriar.papel` NAO tem default (schemas.py) — nenhuma chave
-- nasce pela aba sem alguem dizer de quem ela e. O DEFAULT do banco e
-- compatibilidade com o passado, nao a politica de cadastro.
--
-- ⚠️ `modelos.chave_pix` NAO VIRA O REGISTRO, e ganha aqui um COMMENT que fecha a
-- ambiguidade (ADR-0049 §3). "Chave da modelo" tem dois sentidos que hoje colidem
-- no mesmo campo: DE ONDE o dinheiro do cliente cai (evidencia de bolso) e PARA
-- ONDE a casa manda o dinheiro dela (destino de repasse). Juntos, um repasse da
-- casa PARA ela e lido como uma venda DELA e o razao dobra. A partir daqui ela
-- tem um sentido so — destino de repasse — e a evidencia de bolso mora nesta
-- tabela.
--
-- SEM SEED: schema puro. As chaves vivas (a da casa, as das modelos, as dos
-- telefonistas) sao dado operacional e entram pelo painel — aba Chaves Pix —,
-- nunca pelo repositorio.
--
-- INATIVAR NUNCA DELETAR continua valendo, agora com uma consequencia nova: a
-- chave `padrao` tem que estar `ativo` (CHECK). Inativar a padrao e perder a
-- padrao — alguem precisa escolher outra —, e o painel limpa `padrao` junto ao
-- inativar em vez de deixar a constraint estourar na cara do gestor.
--
-- Idempotente: DO $$ para o enum, ADD COLUMN IF NOT EXISTS, DROP CONSTRAINT IF
-- EXISTS + ADD, CREATE INDEX IF NOT EXISTS, UPDATE guardado por `IS NULL`.
-- Roda 2x sem erro e sem reescrever nada na segunda vez.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py infra/sql/20260820130000_papel_da_chave_pix.sql
--
-- Conferir DEPOIS:
--   \d barravips.chaves_pix_conhecidas
--   SELECT papel, count(*), count(*) FILTER (WHERE padrao)
--     FROM barravips.chaves_pix_conhecidas GROUP BY papel;
-- =============================================================================

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = 'papel_da_chave_enum' AND n.nspname = 'barravips'
  ) THEN
    CREATE TYPE barravips.papel_da_chave_enum AS ENUM (
      'casa',
      'modelo',
      'telefonista',
      'terceiro'
    );
  END IF;
END
$$;

-- --- as colunas novas ---------------------------------------------------------------------------

ALTER TABLE barravips.chaves_pix_conhecidas
  ADD COLUMN IF NOT EXISTS papel barravips.papel_da_chave_enum DEFAULT 'casa';

ALTER TABLE barravips.chaves_pix_conhecidas
  ADD COLUMN IF NOT EXISTS modelo_id uuid
    REFERENCES barravips.modelos(id) ON DELETE RESTRICT;

ALTER TABLE barravips.chaves_pix_conhecidas
  ADD COLUMN IF NOT EXISTS vendedor_id uuid
    REFERENCES barravips.vendedores(id) ON DELETE RESTRICT;

ALTER TABLE barravips.chaves_pix_conhecidas
  ADD COLUMN IF NOT EXISTS padrao boolean NOT NULL DEFAULT false;

-- --- backfill: o que era "conhecida da casa" E da casa -------------------------------------------
-- Guardado por `IS NULL`: na segunda execucao nao ha linha para reescrever, e uma chave que ja foi
-- classificada como `terceiro` pelo painel NUNCA volta a ser `casa`.

UPDATE barravips.chaves_pix_conhecidas
   SET papel = 'casa'
 WHERE papel IS NULL;

ALTER TABLE barravips.chaves_pix_conhecidas
  ALTER COLUMN papel SET NOT NULL;

-- Explicito, e nao herdado do ADD COLUMN acima: na re-execucao a coluna ja existe, o ADD nao roda
-- e sem esta linha o DEFAULT dependeria de quem chegou primeiro.
ALTER TABLE barravips.chaves_pix_conhecidas
  ALTER COLUMN papel SET DEFAULT 'casa';

-- --- coerencia papel x dono ----------------------------------------------------------------------
-- O dono e obrigatorio quando o papel o pede e PROIBIDO quando nao pede. Sem a segunda metade,
-- `papel='casa' + modelo_id=<alguem>` seria aceito e o leitor do ticket 03 teria que escolher em
-- qual das duas informacoes acreditar — que e uma escolha que ninguem consegue fazer certo.

ALTER TABLE barravips.chaves_pix_conhecidas
  DROP CONSTRAINT IF EXISTS chaves_pix_conhecidas_papel_x_dono;
ALTER TABLE barravips.chaves_pix_conhecidas
  ADD CONSTRAINT chaves_pix_conhecidas_papel_x_dono
    CHECK (
      CASE papel
        WHEN 'modelo'      THEN modelo_id IS NOT NULL AND vendedor_id IS NULL
        WHEN 'telefonista' THEN vendedor_id IS NOT NULL AND modelo_id IS NULL
        ELSE modelo_id IS NULL AND vendedor_id IS NULL
      END
    );

-- --- a padrao e da casa, e esta viva --------------------------------------------------------------
-- "Chave padrao" e o destino que a operacao usa HOJE. Uma chave de terceiro padrao nao quer dizer
-- nada, e uma chave inativa padrao e um default que ninguem pode usar.

ALTER TABLE barravips.chaves_pix_conhecidas
  DROP CONSTRAINT IF EXISTS chaves_pix_conhecidas_padrao_e_da_casa_viva;
ALTER TABLE barravips.chaves_pix_conhecidas
  ADD CONSTRAINT chaves_pix_conhecidas_padrao_e_da_casa_viva
    CHECK (NOT padrao OR (papel = 'casa' AND ativo));

-- No maximo UMA padrao no banco inteiro. `(padrao) WHERE padrao` indexa so linhas cujo valor e
-- `true`, entao o UNIQUE sobre essa unica coluna admite exatamente uma linha. Trocar a padrao e
-- limpar a antiga e marcar a nova na MESMA transacao (`repo.definir_chave_pix_padrao`) — sem isso o
-- segundo UPDATE bate no indice.
CREATE UNIQUE INDEX IF NOT EXISTS chaves_pix_conhecidas_padrao_uniq
  ON barravips.chaves_pix_conhecidas (padrao)
  WHERE padrao;

-- "Quais chaves sao desta modelo?" — o extrato dela e a resolucao de bolso do ticket 04.
CREATE INDEX IF NOT EXISTS chaves_pix_conhecidas_modelo_idx
  ON barravips.chaves_pix_conhecidas (modelo_id)
  WHERE modelo_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS chaves_pix_conhecidas_vendedor_idx
  ON barravips.chaves_pix_conhecidas (vendedor_id)
  WHERE vendedor_id IS NOT NULL;

-- --- os comentarios que fecham a ambiguidade -----------------------------------------------------

COMMENT ON TABLE barravips.chaves_pix_conhecidas IS
  'O REGISTRO UNICO de "de quem e esta chave Pix" (ADR-0049 §2). Nasceu como a lista plana das '
  'chaves da casa (spec 0005, ticket 07) e passou a tipar o dono: casa, modelo, telefonista ou '
  'terceiro. E a entrada de `papel_da_chave()`, que serve os DOIS caminhos que comparavam chave '
  'em duplicata — o comprovante do grupo financeiro e o Pix de deslocamento. Closed-world: chave '
  'que nao esta aqui e `desconhecida`, nunca "da casa por omissao". Nada aqui trava fluxo: '
  'destino fora do registro gera sinalizacao ao gestor, nao rejeicao.';

COMMENT ON COLUMN barravips.chaves_pix_conhecidas.papel IS
  'casa (conta da operacao) | modelo (a chave DA MODELO, de onde o dinheiro do cliente cai — '
  'evidencia de bolso do ADR-0047 §2, exige `modelo_id`) | telefonista (a conta em que o '
  'deslocamento as vezes cai, exige `vendedor_id`) | terceiro (legitimo e conhecido — fornecedor, '
  'divida pessoal dela — sem dono no sistema: existe para PARAR de alarmar, nao para atribuir '
  'dinheiro). DEFAULT casa por compatibilidade com os INSERTs escritos quando esta tabela SO '
  'tinha chave da casa; quem cadastra pelo painel e obrigado a declarar (`ChavePixCriar.papel` '
  'nao tem default).';

COMMENT ON COLUMN barravips.chaves_pix_conhecidas.modelo_id IS
  'A dona da chave quando `papel = modelo`. NAO e unico: uma modelo tem varias chaves (CPF, '
  'telefone, aleatoria) e troca de banco. NULL em qualquer outro papel, pelo CHECK '
  '`chaves_pix_conhecidas_papel_x_dono`. ON DELETE RESTRICT porque apagar a modelo apagaria a '
  'explicacao de comprovantes antigos que apontam para a chave dela.';

COMMENT ON COLUMN barravips.chaves_pix_conhecidas.vendedor_id IS
  'O telefonista dono da chave quando `papel = telefonista` — o caso do deslocamento que cai na '
  'conta dele (*"ele sempre manda pra conta da empresa? — vai depender"*). NULL em qualquer outro '
  'papel. `barravips.vendedores` e a tabela do "telefonista" no vocabulario do painel.';

COMMENT ON COLUMN barravips.chaves_pix_conhecidas.padrao IS
  'A UMA chave da casa que a operacao usa por default (*"vou botar a Pix, que normalmente e o '
  'padrao que a gente mais recebe"*). No maximo uma no banco inteiro '
  '(`chaves_pix_conhecidas_padrao_uniq`), sempre com `papel = casa` e `ativo` '
  '(`chaves_pix_conhecidas_padrao_e_da_casa_viva`). Nao e "a unica valida": as outras chaves da '
  'casa recebem tao legitimamente quanto ela.';

COMMENT ON COLUMN barravips.chaves_pix_conhecidas.ativo IS
  'Inativar nunca deletar: chave que saiu de uso precisa continuar explicando os comprovantes '
  'antigos que apontam para ela. Chave inativa continua respondendo o PAPEL (ela continua sendo '
  'da modelo tal) — o que ela deixa de ser e destino esperado de dinheiro novo.';

-- ⚠️ ADR-0049 §3: o campo do cadastro da modelo passa a ter UM sentido so.
COMMENT ON COLUMN barravips.modelos.chave_pix IS
  'A chave preferida da modelo para RECEBER REPASSE — destino de pagamento, e a chave que a IA '
  'entrega ao cliente no Pix de deslocamento. ⚠️ NAO e registro de origem: para responder "de '
  'quem e a chave que apareceu neste comprovante" existe `barravips.chaves_pix_conhecidas` '
  '(ADR-0049 §2). Os dois sentidos no mesmo campo fazem um repasse da casa PARA ela ser lido '
  'como uma venda DELA, e o razao dobra.';

COMMENT ON COLUMN barravips.modelos.titular_chave IS
  'O nome do titular de `modelos.chave_pix`, para a IA dizer ao cliente para quem ele esta '
  'pagando quando a conta nao esta no nome dela. Mesmo escopo da coluna irma: destino de repasse, '
  'nao registro de origem.';

COMMIT;
