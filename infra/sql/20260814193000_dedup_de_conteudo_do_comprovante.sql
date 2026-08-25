-- =============================================================================
-- 20260814193000_dedup_de_conteudo_do_comprovante.sql
-- A MESMA imagem de comprovante nao pode contar dinheiro duas vezes
-- (spec 0005, ticket 07).
--
-- O QUE ACONTECIA ATE AQUI:
-- `comprovantes_do_grupo.mensagem_id UNIQUE` protege a REENTREGA da mesma
-- mensagem pelo router — nao protege o REENVIO da mesma foto, que chega como
-- mensagem nova, com message_id novo. E reenviar a foto e gesto comum no
-- WhatsApp: a modelo manda de novo achando que nao chegou, ou encaminha.
--
-- Medido no barra_test em 14/08/2026, com duas vendas em pix de R$ 700,00
-- abertas e UM comprovante de R$ 700,00 enviado duas vezes: o agente abateu as
-- DUAS, o Fechamento fechou em R$ 1.400,00 comprovados e nao acusou divergencia
-- nenhuma. Dinheiro comprovado que nunca entrou — e, pior, invisivel: o extrato
-- fica bonito exatamente no caso em que ele deveria gritar.
--
-- POR QUE HASH, E NAO CHAVE LEGIVEL:
-- o resto do modulo deduplica por chave de conteudo legivel (venda, cobranca)
-- para que quem investiga entenda a colisao lendo o banco. Aqui a identidade
-- e a IMAGEM, e a chave legivel possivel (valor|data|chave_destino) colide
-- entre dois Pix legitimos do mesmo valor, no mesmo dia, para a mesma chave —
-- que e rotina numa casa com varias vendas de R$ 600,00. Hash dos bytes nao
-- tem esse falso positivo: mesma foto e mesma foto. Em troca, aceita o falso
-- NEGATIVO (um print novo do mesmo Pix passa) — o mal menor, porque este erra
-- para o lado de contar o que existe.
--
-- POR QUE PARCIAL (`WHERE conteudo_hash IS NOT NULL`):
-- o comprovante ILEGIVEL nao grava hash de proposito. O agente acabou de pedir
-- "reenvia a imagem inteira"; se a modelo reenviar a mesma foto, ele precisa
-- poder tentar de novo em vez de recusar calado a unica coisa que pediu.
--
-- POR QUE POR GRUPO:
-- a mesma foto em grupos de modelos diferentes e comprovante de coisas
-- diferentes (e o gestor que repassa o mesmo recibo). O escopo do dedup e o
-- escopo do fato.
--
-- IDEMPOTENTE: IF NOT EXISTS em tudo. Rodar duas vezes nao muda nada.
--
-- CONFERIR DEPOIS:
--   \d barravips.comprovantes_do_grupo
--   SELECT indexdef FROM pg_indexes
--    WHERE schemaname='barravips' AND tablename='comprovantes_do_grupo';
-- =============================================================================

BEGIN;

ALTER TABLE barravips.comprovantes_do_grupo
  ADD COLUMN IF NOT EXISTS conteudo_hash text;

COMMENT ON COLUMN barravips.comprovantes_do_grupo.conteudo_hash IS
  'sha256 dos bytes da imagem que o grupo mandou — a identidade da FOTO, nao da mensagem. '
  'NULL no comprovante ilegivel (o reenvio pedido tem que poder ser a mesma foto) e em tudo que '
  'foi gravado antes desta migration.';

-- Um comprovante legivel por foto, por grupo. E o que impede o mesmo Pix de abater duas vendas.
CREATE UNIQUE INDEX IF NOT EXISTS comprovantes_do_grupo_conteudo_uk
  ON barravips.comprovantes_do_grupo (grupo_id, conteudo_hash)
  WHERE conteudo_hash IS NOT NULL;

COMMIT;
