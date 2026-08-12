-- =============================================================================
-- Composições no catálogo global: QUATRO itens por COMPOSIÇÃO (quem acompanha quem),
-- no lugar dos dois itens ambíguos de hoje ("Casal" e "Menage").
--
-- REGRA DURA DESTA MIGRATION, e o critério de toda decisão abaixo: ela NÃO PODE fazer
-- nenhuma modelo passar a OFERECER algo que ela não oferecia. Onde houve dúvida, o
-- cadastro fica INCOMPLETO (a IA recusa, closed-world) e nunca AFIRMADO (a IA promete).
-- Cadastro é decisão de cada modelo, e ninguém perguntou nada a elas para escrever isto.
--
-- MOTIVAÇÃO (Fernando, 11/08/2026). Hoje `barravips.fetiches` tem dois itens com
-- `cobra_por_pessoa = true` — "Casal" (vinculado à Catarina e à Tatiane) e "Menage"
-- (vinculado às três: Catarina, Lucia e Tatiane). "Menage" é ambíguo por construção:
-- ménage pode ser duas mulheres e dois homens, ou uma mulher e um homem. E a Catarina
-- NÃO atende dois homens — restrição que o cadastro de hoje não tem como expressar,
-- porque o item que ele oferece cobre as duas leituras de uma vez.
--
-- O GANHO, e a razão de a mudança valer a pena: com um item POR COMPOSIÇÃO, "ela não
-- atende dois homens" vira AUSÊNCIA no cardápio — a recusa closed-world que o sistema
-- inteiro já sabe fazer sozinho (`render_fetiches`: "a ausência de um fetiche da lista
-- significa que ela NÃO faz") — em vez de uma exceção escrita em prosa que depende de a
-- LLM ler certo. Recusa por DADO, não por parágrafo.
--
-- A TAXONOMIA (4 itens, todos `cobra_por_pessoa = true`):
--   Acompanhante dele — mulher   1 modelo + ele + 1 mulher    (é o "casal" da linguagem comum)
--   Acompanhante dele — homem    1 modelo + ele + 1 homem     (dois homens)
--   Dupla de modelos             1 cliente + 2 modelos
--   Dois casais (2 modelos)      2 homens + 2 modelos
--
-- Os nomes são DESCRITIVOS de propósito, e isso não vaza para a fala: `regras.md.j2`
-- (<composicoes>) mantém a regra que já valia para o "Casal" — "o rótulo da lista é
-- interno: na fala, espelhe quem ele disse que vem". O nome existe para o PAINEL e para
-- o casamento com a fala do cliente (`_FAMILIAS_FETICHE`), não para sair da boca dela.
--
-- ARITMÉTICA: nada muda. Composição segue o regime do ADR-0039 (o extra é a linha de 1h
-- do mesmo programa, no patamar vigente; o pacote NÃO dobra). Esta migration mexe em
-- NOMES e em quem oferece o quê — nenhum número é tocado, nem aqui nem no código.
--
-- -----------------------------------------------------------------------------
-- AS TRÊS DECISÕES DE DADO, e por quê
-- -----------------------------------------------------------------------------
--
-- (1) "Casal" -> "Acompanhante dele — mulher", RENOMEADO NO LUGAR (mesmo `id`, mesmos
--     vínculos, mesmo preço). É o único movimento semanticamente seguro do conjunto:
--     "casal", na linguagem comum, é ele + a mulher dele — exatamente a composição do
--     item novo. O sistema hoje ESTICA esse item para "qualquer segunda pessoa,
--     inclusive outro homem" (CONTEXT.md, verbete Menage), então o rename ESTREITA o
--     que o cadastro afirma. Estreitar é a direção segura: nenhuma modelo passa a
--     oferecer nada, e Catarina/Tatiane continuam declarando o que "casal" sempre quis
--     dizer. Preservar o `id` também preserva `modelo_fetiches` (e qualquer
--     `atendimento_fetiches` futuro) sem migrar linha nenhuma.
--
-- (2) "Menage" -> NADA. Ele é APOSENTADO: vínculos removidos e a linha do catálogo
--     apagada. Não existe rename seguro porque o item significa coisas DIFERENTES para
--     modelos diferentes — para a Catarina ele inclui uma leitura (dois homens) que ela
--     não atende, e para a Lucia e a Tatiane ninguém sabe qual leitura elas aceitaram
--     quando alguém marcou a caixinha. Renomear "Menage" para qualquer um dos quatro
--     itens novos seria escrever no cadastro delas uma afirmação que elas não fizeram —
--     precisamente o que a regra dura proíbe. Apagar erra para o lado da recusa.
--     Também não basta desvincular e deixar a linha no catálogo: ela reapareceria na
--     lista do painel e alguém a re-vincularia, reintroduzindo a ambiguidade.
--
-- (3) OS ITENS NOVOS NASCEM SEM VÍNCULO NENHUM. `atendimento_fetiches` está VAZIA em
--     prod, então não há histórico a migrar; e `modelo_fetiches` é a declaração da
--     modelo, não uma dedução nossa. Vincular a Catarina a "Dupla de modelos"/"Dois
--     casais" teria, além disso, um efeito que esta frente não quer: hoje TODO pedido de
--     composição com OUTRA MODELO segue o trilho de escalada do `<composicoes>` ("deixa
--     eu ver com ela" + `escalar(outro)`), e um vínculo faria a IA passar a COTAR ali.
--     Essa conduta é de outra frente (a que vai revogar a escalada), não desta.
--     Coerente com o resto do repo: catálogo global entra por migration, cadastro
--     por-modelo entra por painel/MCP (20260722024720, 20260811193150, 20260811214743).
--
-- -----------------------------------------------------------------------------
-- O QUE ISTO DEIXA PARA A OPERAÇÃO (não é efeito colateral: é a escolha acima)
-- -----------------------------------------------------------------------------
--   Catarina  fica com "Acompanhante dele — mulher" (o ex-"Casal", intacto) e SEM
--             "Acompanhante dele — homem" — que é justamente o fato que motivou tudo:
--             ela não atende dois homens, e agora o cardápio diz isso sozinho.
--   Lucia     tinha SÓ "Menage". Fica sem composição nenhuma -> o gate `<sem_menage>`
--             passa a valer para ela e a IA recusa qualquer segunda pessoa. Ela não está
--             em operação hoje; o cadastro dela precisa ser REFEITO no painel depois de
--             Fernando perguntar a ela, item a item, o que ela faz.
--   Tatiane   tinha "Casal" + "Menage". Fica com "Acompanhante dele — mulher" (o Casal
--             preservado). O que o "Menage" dela dizia A MAIS era justamente a parte
--             ambígua — some, e volta pelo painel se e quando ela disser o que aceita.
--             Também não está em operação hoje.
--
-- Idempotente: roda 2x sem quebrar. O rename só casa 'casal' (na 2ª passada não há mais
-- nenhum) e é guardado contra criar nome duplicado; os INSERTs são `WHERE NOT EXISTS`;
-- os DELETEs de 'menage' viram 0 linhas depois da 1ª passada. A comparação de nome dobra
-- TRAÇO (o painel pode gravar hífen no lugar do travessão) e ACENTO no 'menage' (prod tem
-- item criado por Studio, e um "Ménage" escaparia de um literal exato) — dois itens com o
-- mesmo significado no catálogo é pior que qualquer alternativa.
--
-- -----------------------------------------------------------------------------
-- PRÉ-VOO E PÓS-CHECK — OBRIGATÓRIOS, e a razão é estrutural
-- -----------------------------------------------------------------------------
-- Todo statement daqui é guardado por `NOT EXISTS`, então TODO modo de falha desta
-- migration é "0 linhas afetadas, exit 0" — nunca um erro. Sem olhar o dado antes e
-- depois, uma aplicação que não fez NADA é indistinguível de uma que funcionou. Rode
-- isto numa sessão à parte, antes e depois:
--
--   SELECT id, nome, ordem, cobra_por_pessoa,
--          (SELECT count(*) FROM barravips.modelo_fetiches mf WHERE mf.fetiche_id = f.id)
--            AS vinculos
--     FROM barravips.fetiches f ORDER BY ordem, nome;
--   SELECT count(*) FROM barravips.atendimento_fetiches;  -- o header afirma 0; reconfirme
--   SELECT conrelid::regclass AS tabela, conname FROM pg_constraint
--    WHERE confrelid = 'barravips.fetiches'::regclass AND contype = 'f';  -- FK criada à mão?
--
-- ANTES, os dois estados que esta migration NÃO sabe consertar sozinha e nos quais ela
-- termina com sucesso sem ter feito o que devia (`fetiches.nome` não tem UNIQUE):
--   - DUAS linhas 'Casal': o UPDATE do passo 1 renomeia AS DUAS e o catálogo fica com um
--     par duplicado. Resolva à mão antes (uma delas é lixo — veja qual tem vínculo).
--   - 'Casal' E 'Acompanhante dele — mulher' coexistindo: o guard do passo 1 é uma trava
--     GLOBAL, não correlacionada por linha — o UPDATE não roda, o 'Casal' sobrevive com
--     os vínculos e o item novo fica órfão ao lado. Mover vínculo entre ids é MERGE de
--     dado e não entra numa migration automática: decida à mão, com o dado na frente.
--
-- DEPOIS, o estado esperado: nenhuma linha 'casal'/'menage'/'ménage'; exatamente 4
-- composições; a de "mulher" com os vínculos de Catarina e Tatiane preservados; as
-- outras 3 com 0 vínculos.
--
-- Aplicar com o papel `postgres` (as três tabelas têm RLS com FORCE — um papel sem
-- BYPASSRLS faria todo INSERT/UPDATE/DELETE afetar 0 linhas EM SILÊNCIO).
--
-- Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA `make migrate`.
-- =============================================================================

BEGIN;

-- 1) "Casal" renomeado NO LUGAR. Guardado: se o nome novo já existir (2ª passada, ou um
-- painel adiantado), o UPDATE não roda e não nasce um par duplicado no catálogo.
UPDATE barravips.fetiches
   SET nome = 'Acompanhante dele — mulher'
 WHERE lower(btrim(nome)) = 'casal'
   AND NOT EXISTS (
     SELECT 1
       FROM barravips.fetiches f
      WHERE translate(lower(btrim(f.nome)), '—–‑‒−', '-----') = 'acompanhante dele - mulher'
   );

-- 2) Os quatro itens da taxonomia, SEM vínculo nenhum (cadastro é decisão de cada
-- modelo, e ninguém perguntou a elas). O de "mulher" já existe aqui quando o passo 1
-- renomeou o "Casal" — o `NOT EXISTS` o pula e preserva id/vínculos/preço; ele só nasce
-- do zero num banco que nunca teve "Casal" (dev, teste, prod futuro).
-- `ordem`: as quatro herdam a posição que a composição já tinha (a menor `ordem` entre as
-- `cobra_por_pessoa`), para ficarem onde o "Casal" já estava; sem nenhuma composição no
-- catálogo, vão para o fim da lista. Isso NÃO garante que fiquem agrupadas: se em prod a
-- `ordem` do "Casal" for o default 0 — que todo fetiche criado pelo painel também recebe —
-- o `ORDER BY f.ordem, f.nome` do render as intercala com os atos. É cosmético (o
-- agrupamento visual do painel), não afeta prompt nem preço; o pré-voo mostra as `ordem`
-- reais e o ajuste, se valer a pena, é um UPDATE à parte.
WITH ordem_das_composicoes AS (
  SELECT COALESCE(
           (SELECT min(ordem) FROM barravips.fetiches WHERE cobra_por_pessoa),
           (SELECT COALESCE(max(ordem), 0) + 1 FROM barravips.fetiches)
         ) AS ordem
), taxonomia (nome) AS (
  VALUES ('Acompanhante dele — mulher'),
         ('Acompanhante dele — homem'),
         ('Dupla de modelos'),
         ('Dois casais (2 modelos)')
)
INSERT INTO barravips.fetiches (nome, ordem, cobra_por_pessoa)
SELECT t.nome, o.ordem, true
  FROM taxonomia t
 CROSS JOIN ordem_das_composicoes o
 WHERE NOT EXISTS (
   SELECT 1
     FROM barravips.fetiches f
    WHERE translate(lower(btrim(f.nome)), '—–‑‒−', '-----')
        = translate(lower(btrim(t.nome)), '—–‑‒−', '-----')
 );

-- 3) A flag do catálogo nos quatro. Convergente: o ex-"Casal" já vem com ela desde a
-- 20260723064620, mas um item recriado à mão pelo painel (que não expõe a flag) chegaria
-- sem — e sem ela a composição cairia na seção "Extras pagos" dos ATOS, com a fala
-- errada ("+2 fetiches" no lugar de "Total com a 2ª pessoa") e sem sustentar o
-- `<sem_menage>`.
UPDATE barravips.fetiches
   SET cobra_por_pessoa = true
 WHERE translate(lower(btrim(nome)), '—–‑‒−', '-----') IN (
         'acompanhante dele - mulher',
         'acompanhante dele - homem',
         'dupla de modelos',
         'dois casais (2 modelos)'
       )
   AND NOT cobra_por_pessoa;

-- 4) "Menage" aposentado. Primeiro os VÍNCULOS: é aqui que a Lucia perde a composição
-- inteira e a Tatiane perde a metade ambígua do que declarava. É a direção segura da
-- regra dura — sem cadastro a IA recusa; com o cadastro ambíguo ela prometeria dois
-- homens para quem talvez não atenda.
DELETE FROM barravips.modelo_fetiches mf
 USING barravips.fetiches f
 WHERE f.id = mf.fetiche_id
   AND translate(lower(btrim(f.nome)), 'éèê', 'eee') = 'menage';

-- Depois a linha do catálogo, para que ninguém a re-vincule pelo painel. O `NOT EXISTS`
-- sobre `atendimento_fetiches` é a trava: hoje a tabela está VAZIA em prod (verificado
-- 11/08/2026) e o DELETE passa; se um atendimento já tiver referenciado o item, a FK é
-- `ON DELETE RESTRICT` e o certo é NÃO apagar histórico de venda — a linha fica, sem
-- vínculo com modelo nenhuma (que já basta para sumir de todo prompt), e a limpeza vira
-- decisão de quem estiver olhando o painel.
DELETE FROM barravips.fetiches f
 WHERE translate(lower(btrim(f.nome)), 'éèê', 'eee') = 'menage'
   AND NOT EXISTS (
     SELECT 1 FROM barravips.atendimento_fetiches af WHERE af.fetiche_id = f.id
   );

COMMENT ON COLUMN barravips.fetiches.cobra_por_pessoa IS
  'true = COMPOSIÇÃO (quem acompanha quem no encontro): abre a seção "Por pessoa" do <fetiches>, sustenta o gate <sem_menage> e o <composicao_em_pauta> do foco do turno. Desde o ADR-0039 é só CLASSIFICAÇÃO, não regime de preço — a 2ª pessoa soma o MESMO extra dos atos (a linha de 1h do programa, no patamar vigente; o pacote não dobra). Desde 11/08/2026 há um item por COMPOSIÇÃO (acompanhante dele mulher/homem, dupla de modelos, dois casais) no lugar do par ambíguo "Casal"/"Menage": a modelo que não atende uma delas simplesmente não a tem vinculada, e a recusa sai do closed-world do cardápio em vez de uma exceção em prosa.';

COMMIT;
