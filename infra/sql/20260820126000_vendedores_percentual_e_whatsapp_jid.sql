-- =============================================================================
-- 20260820126000_vendedores_percentual_e_whatsapp_jid.sql
-- Comissao do telefonista: percentual **por vendedor** (ADR-0048 §1) e o vinculo
-- que diz QUEM vendeu (§5).
--
-- O QUE MUDA: o ADR-0012 pos o percentual no NIVEL do vendedor
-- (`financeiro_comissao_niveis`, 4/5/6%) e deixou "override por vendedor para
-- depois". O depois chegou, pedido pelo Rossi sem que ninguem puxasse o assunto:
-- "a gente pode colocar uma porcentagem pro telefonista que a gente possa
-- alterar, de 1% a 10%. Isso vai depender da experiencia do vendedor."
--
-- `financeiro_comissao_niveis` E O ENUM DE NIVEL **SOBREVIVEM** (ADR-0048 §1),
-- como DEFAULT DE CADASTRO: o nivel preenche o percentual na criacao e para de
-- ser consultado no calculo. Ninguem perde historico e a tabela nao e dropada.
--
-- DEFAULT 7.00 e a referencia que o Rossi deu. CHECK 0..100, NAO 1..10: a faixa
-- 1-10 e operacional, nao invariante — "ou ate 100%", disse ele mesmo ao divagar
-- sobre o calculo (ADR-0048, alternativas rejeitadas). Mesmo intervalo de
-- `financeiro_comissao_niveis.percentual` e de `modelos.percentual_repasse`.
--
-- `whatsapp_jid` — quem e o telefonista da venda vem do AUTOR da mensagem
-- (ADR-0048 §5): a ficha e postada por uma pessoa, e o JID do participante
-- identifica quem. UNICO (indice parcial: NULL nao colide no Postgres, entao um
-- UNIQUE de coluna nullable nao serviria de nada — a mesma licao que custou 7
-- dias de resposta duplicada no myEYE e que `grupo_financeiro_mensagens.chave_dedup`
-- ja carrega escrita). NULLABLE porque vendedor cadastrado antes disto nao tem
-- JID, e autor desconhecido -> venda sem vendedor -> sem comissao: nunca chuta.
--
-- ⚠️ O JID DO AUTOR PODE VIR COMO `@lid` OPACO (e por isso
-- `grupo_financeiro_mensagens.autor_nome` existe). Casar por `autor_nome` seria
-- palpite; esta coluna guarda o que for estavel para aquele telefonista e o
-- resolver e closed-world: nao achou, nao atribui.
--
-- O QUE ESTA MIGRATION **NAO** FAZ: nao faz o backfill do percentual — ele esta
-- na migration IRMA `20260820127000_backfill_percentual_comissao_do_nivel.sql`,
-- separada de proposito (schema x dado, infra/sql/CLAUDE.md) e com guarda de
-- execucao unica. Enquanto ela nao rodar, TODO vendedor existente fica com 7.00,
-- que e reprecificacao retroativa — as duas sao um par, aplique as duas.
--
-- Idempotente (ADD COLUMN IF NOT EXISTS, DROP CONSTRAINT antes de ADD, CREATE
-- INDEX IF NOT EXISTS). Sem seed: schema puro.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod):
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260820126000_vendedores_percentual_e_whatsapp_jid.sql
--
-- Conferir DEPOIS:
--   SELECT nome, nivel, percentual_comissao, whatsapp_jid FROM barravips.vendedores;
-- =============================================================================

BEGIN;

ALTER TABLE barravips.vendedores
  ADD COLUMN IF NOT EXISTS percentual_comissao numeric(5,2) NOT NULL DEFAULT 7.00;

ALTER TABLE barravips.vendedores
  DROP CONSTRAINT IF EXISTS vendedores_percentual_comissao_valido;
ALTER TABLE barravips.vendedores
  ADD CONSTRAINT vendedores_percentual_comissao_valido
    CHECK (percentual_comissao >= 0 AND percentual_comissao <= 100);

ALTER TABLE barravips.vendedores
  ADD COLUMN IF NOT EXISTS whatsapp_jid text;

COMMENT ON COLUMN barravips.vendedores.percentual_comissao IS
  'Percentual de Comissao do telefonista, POR VENDEDOR (ADR-0048 §1). Substitui a consulta a '
  '`financeiro_comissao_niveis`, que sobrevive apenas como default de cadastro (o nivel preenche '
  'este numero na criacao). Base = BRUTO VENDIDO (§2): taxa de cartao NAO e descontada, alinhado '
  'a comissao da modelo (ADR-0045 §3), e deslocamento NAO entra (§3 — reembolso de custo nao e '
  'venda). Incide sobre `atendimentos` Fechado E sobre `vendas_registradas` (§4). PROJECAO, sem '
  'snapshot por venda (§6): mudou aqui, mudou a projecao. Faixa operacional 1-10%, default 7.00; '
  'o CHECK e 0..100 porque a faixa e operacional, nao invariante.';
COMMENT ON COLUMN barravips.vendedores.whatsapp_jid IS
  'O JID do telefonista no WhatsApp — o vinculo que diz QUEM vendeu (ADR-0048 §5): a ficha e '
  'postada por uma pessoa, e o `autor_jid` da mensagem identifica quem. UNICO entre os nao '
  'nulos (indice parcial `vendedores_whatsapp_jid_uniq`; UNIQUE de coluna nullable nao colide no '
  'Postgres). Pode chegar como `@lid` opaco. Resolver CLOSED-WORLD: autor que nao esta aqui -> '
  'venda sem vendedor -> sem comissao, como o ADR-0012 ja trata o atendimento da IA. Nunca casar '
  'por nome de exibicao — isso e palpite.';

CREATE UNIQUE INDEX IF NOT EXISTS vendedores_whatsapp_jid_uniq
  ON barravips.vendedores (whatsapp_jid)
  WHERE whatsapp_jid IS NOT NULL;

COMMIT;
