-- =============================================================================
-- 20260726022209_atendimentos_foto_portaria_pedida.sql
-- Flag de disciplina conversacional (padrão A2) em barravips.atendimentos: o
-- instante em que a IA PEDIU o print da chegada ("Quando chegar me manda uma
-- foto da portaria amor").
--
-- Motivo: pedido o print, a IA espera — mantém presença curta ("Vou me arrumar
-- rs", "Estou te esperando") e NÃO recobra ("vai vir mesmo ?", "chega em quanto
-- tempo ?" repetidos são, pelo próprio prompt, o que mais afasta nessa fase). A
-- disciplina era só prosa no <conducao_da_venda>, e o pedido sai no FIM do
-- combinado: desliza pra fora da janela de 20 msgs justamente enquanto o cliente
-- não chega, que é quando a regra vale.
--
-- Molde: dia_sondado_em / book_enviado_em / amiga_ofertada_em (timestamptz
-- nullable, first-write-wins). Carimbado no write-time (workers/envio.py, mesma
-- transação do INSERT em barravips.mensagens); lido por prepare_context.
--
-- A tabela atendimentos já tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration
-- só adiciona coluna, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS).
-- Schema-only — não aplicar seeds em prod.
--
-- Atendimentos ABERTOS antes desta migration nascem com a coluna NULL: a IA pode
-- recobrar uma vez. Falso-negativo benigno, que se auto-corrige no próximo pedido
-- — o backfill é opcional e é escrita em prod (CLAUDE.md §0).
--
-- Aplicação: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260726022209_atendimentos_foto_portaria_pedida.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS foto_portaria_pedida_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.foto_portaria_pedida_em IS
  'Instante em que a IA pediu ao cliente a foto da portaria pela 1ª vez '
  '(first-write-wins). Carimbado no write-time em workers/envio.py; fonte do '
  '<ja_pediu_a_foto_da_portaria> no contexto dinâmico, a tag que segura a '
  'recobrança (pedido o print, a IA espera com presença curta) depois de o pedido '
  'sair da janela de 20 msgs. NÃO é a chegada em si (essa é a Foto de portaria que '
  'o cliente manda, e é ela que dispara o handoff implícito) — é só o pedido dela.';
