-- =============================================================================
-- 20260814213000_anulacao_do_comprovante.sql
-- Apagar a FOTO do comprovante desfaz o abate (spec 0005, tickets 05 e 07).
--
-- O QUE ACONTECIA ATE AQUI:
-- apagar-e-repostar e como o grupo corrige (08/08: "Mensagem apagada" seguida
-- do anuncio de novo), e a delecao ja anulava a Venda registrada e a Cobranca
-- da agencia nascidas da mensagem apagada. O COMPROVANTE nao: a modelo mandava
-- a foto errada (o Pix de outra pessoa, o valor errado), apagava — e a venda
-- seguia marcada como paga, com o extrato fechando.
--
-- Medido no barra_test em 14/08/2026: venda de R$ 600,00 em pix, comprovante de
-- R$ 600,00, foto apagada em seguida. Resultado: `conciliado=True`, comprovado
-- R$ 600,00, zero divergencias. Dinheiro provado por uma prova que nao existe
-- mais no grupo — e, como o extrato bate, ninguem procura.
--
-- POR QUE `anulado_em` (e nao DELETE):
-- mesmo criterio da Venda registrada e da Cobranca da agencia: o que aconteceu
-- continua no banco provando o que aconteceu. O comprovante anulado sai da
-- conferencia (o repo filtra) e o abate dele e desfeito — as vendas voltam para
-- a fila de "falta comprovar", que e onde elas estavam antes da foto errada.
--
-- POR QUE O INDICE DE CONTEUDO VIRA PARCIAL TAMBEM POR `anulado_em`:
-- o dedup de conteudo (migration anterior) recusa a mesma foto duas vezes. Sem
-- liberar a chave na anulacao, quem apagasse a foto por engano nao conseguiria
-- reenviar A MESMA foto — o agente responderia "ja tinha conferido" sobre um
-- comprovante que ele mesmo acabou de anular. Mesmo remedio do `chave_conteudo`
-- da cobranca (`WHERE anulada_em IS NULL`).
--
-- IDEMPOTENTE: IF NOT EXISTS/IF EXISTS em tudo.
--
-- CONFERIR DEPOIS:
--   \d barravips.comprovantes_do_grupo
--   SELECT indexdef FROM pg_indexes
--    WHERE schemaname='barravips' AND tablename='comprovantes_do_grupo';
-- =============================================================================

BEGIN;

ALTER TABLE barravips.comprovantes_do_grupo
  ADD COLUMN IF NOT EXISTS anulado_em timestamptz;

COMMENT ON COLUMN barravips.comprovantes_do_grupo.anulado_em IS
  'Quando a mensagem-fonte da imagem foi apagada no grupo (spec 0005, ticket 05). Comprovante '
  'anulado sai da conferencia e devolve as vendas que ele abateu para a fila — mas continua na '
  'tabela, porque o que aconteceu nao deixa de ter acontecido.';

DROP INDEX IF EXISTS barravips.comprovantes_do_grupo_conteudo_uk;

CREATE UNIQUE INDEX IF NOT EXISTS comprovantes_do_grupo_conteudo_uk
  ON barravips.comprovantes_do_grupo (grupo_id, conteudo_hash)
  WHERE conteudo_hash IS NOT NULL AND anulado_em IS NULL;

-- A conferencia so olha comprovante vivo, e ela e por grupo.
CREATE INDEX IF NOT EXISTS comprovantes_do_grupo_vivos_idx
  ON barravips.comprovantes_do_grupo (grupo_id, created_at)
  WHERE anulado_em IS NULL;

-- --- o rastro do abate desfeito -----------------------------------------------------------------
--
-- A venda volta de "conciliada" para "falta comprovar" sem ninguem ter tocado NELA — quem olhar o
-- painel precisa achar o porque. Terceiro tipo de evento, ao lado de correcao e anulacao.

ALTER TABLE barravips.venda_registrada_eventos
  DROP CONSTRAINT IF EXISTS venda_registrada_eventos_tipo_valido;

ALTER TABLE barravips.venda_registrada_eventos
  ADD CONSTRAINT venda_registrada_eventos_tipo_valido
    CHECK (tipo IN ('correcao', 'anulacao', 'abate_desfeito'));

COMMENT ON COLUMN barravips.venda_registrada_eventos.tipo IS
  'correcao (um campo mudou, com de->para), anulacao (a mensagem-fonte foi apagada) ou '
  'abate_desfeito (o COMPROVANTE que fechava esta venda foi apagado no grupo, e ela voltou para a '
  'fila de falta comprovar).';

COMMIT;
