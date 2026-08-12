-- =============================================================================
-- 20260812010500_parceria_catarina_yasmin.sql
-- DADO DE CONFIGURACAO (nao e schema, e nao e seed descartavel): o primeiro par de
-- barravips.modelo_parcerias -- a Catarina (canal) e a Yasmin (parceira,
-- id 019ff2e1-339a-7a7f-ae5c-a63e5796883f, mesmo hotel), ADR-0042.
--
-- Separado do schema (20260812010000_parceria_de_modelos.sql) de proposito: schema e'
-- estrutura e vale para toda instalacao; par de modelos e' configuracao de UMA operacao,
-- e o id da Catarina difere entre ambientes.
--
-- SEM a palavra "seed" no nome, e nao por estilo: `scripts/aplicar_sql.py` (seed_bloqueado)
-- e o hook `.claude/hooks/guard_prod.py` RECUSAM qualquer arquivo cujo nome case
-- `_seed_*.sql` quando AMBIENTE=producao, e seeds nao entram em
-- `barravips.schema_migrations` (o drift-check nunca acusaria a ausencia). Esta linha E a
-- whitelist closed-world do ADR-0042: sem ela os dois fluxos simplesmente nao existem, e um
-- arquivo silenciosamente inaplicavel deixaria o ADR morto em prod. Mesmo regime dos
-- data-fixes de configuracao que ja rodam em prod (ex.:
-- 20260720233000_menage_pago_correcao_dado.sql).
--
-- O par nasce com:
--   dupla_ativa            = true    (fluxo B liberado: a Catarina fecha as duas sozinha)
--   encaminhamento_ativo   = true    (fluxo A liberado)
--   encaminhamento_atos    = {anal}  (o unico ato que a Yasmin faz e a Catarina nao)
-- Ampliar o array e' o que abre novos atos ao encaminhamento -- nao ha nada em prompt nem
-- em codigo listando ato nenhum.
--
-- ANTES DE APLICAR, confira os dois ids (autorizar a modelo ERRADA entrega o telefone real
-- da Yasmin ao cliente dela, pelo fluxo A):
--   SELECT id, nome, status FROM barravips.modelos WHERE nome ILIKE 'catarina%';
--   SELECT id, nome, status FROM barravips.modelos
--    WHERE id = '019ff2e1-339a-7a7f-ae5c-a63e5796883f'::uuid;
-- Se a primeira devolver mais de uma linha, TROQUE a subquery abaixo pelo literal do id
-- certo. Enquanto ela e' subquery ESCALAR, mais de uma linha ABORTA o arquivo com
-- "more than one row returned by a subquery used as an expression" -- fail-closed de
-- proposito: melhor abortar que autorizar N parcerias em silencio.
--
-- Idempotente (INSERT ... ON CONFLICT DO NOTHING, sem target): roda 2x sem erro e engole
-- tanto o par duplicado (modelo_parcerias_par_unico) quanto uma outra parceria ja ativa da
-- mesma modelo (modelo_parcerias_uma_ativa_por_modelo), em vez de abortar o arquivo.
--
-- Aplicacao MANUAL (nunca `make migrate`), DEPOIS do schema:
--   uv run python scripts/aplicar_sql.py infra/sql/20260812010500_parceria_catarina_yasmin.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script -- o INSERT vira no-op silencioso se
-- algum dos dois ids nao existir):
--   SELECT p.*, c.nome AS canal, y.nome AS parceira
--     FROM barravips.modelo_parcerias p
--     JOIN barravips.modelos c ON c.id = p.modelo_id
--     JOIN barravips.modelos y ON y.id = p.parceira_id
--    WHERE p.parceira_id = '019ff2e1-339a-7a7f-ae5c-a63e5796883f'::uuid;
-- CORREÇÃO ANTES DA 1ª APLICAÇÃO (12/08/2026): o lookup era por
--   `nome ILIKE 'catarina%' AND status = 'ativa'`, e a Catarina está `pausada` — ela vai a
--   produção com o cadastro pronto e a IA ainda desligada. Com aquele filtro esta migration
--   aplicaria ZERO linhas e sairia com exit 0: o par nunca existiria e nenhum dos dois fluxos
--   da parceira armaria, em silêncio. Verificado no momento da aplicação que há exatamente UMA
--   Catarina (019ff23a-912d-7396-bb6c-9568fa71dc32, pausada) e UMA Yasmin
--   (019ff2e1-339a-7a7f-ae5c-a63e5796883f, inativa), então vale o id LITERAL — que é o que o
--   próprio cabeçalho manda fazer quando o lookup por nome não é seguro. Status não é critério
--   de parceria: a autorização do par é `ativo`, nesta tabela.
-- =============================================================================

BEGIN;

INSERT INTO barravips.modelo_parcerias
  (modelo_id, parceira_id, encaminhamento_ativo, encaminhamento_atos, dupla_ativa, ativo)
SELECT '019ff23a-912d-7396-bb6c-9568fa71dc32'::uuid,
       '019ff2e1-339a-7a7f-ae5c-a63e5796883f'::uuid,
       true,
       ARRAY['anal']::text[],
       true,
       true
 WHERE EXISTS (SELECT 1 FROM barravips.modelos c
                WHERE c.id = '019ff23a-912d-7396-bb6c-9568fa71dc32'::uuid)
   AND EXISTS (SELECT 1 FROM barravips.modelos y
                WHERE y.id = '019ff2e1-339a-7a7f-ae5c-a63e5796883f'::uuid)
ON CONFLICT DO NOTHING;

COMMIT;
