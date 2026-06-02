-- =============================================================================
-- 20260602010031_modelos_evolution_instance_id_unique.sql
-- Unicidade de evolution_instance_id por modelo (isolamento de roteamento).
--
-- POR QUE: o webhook resolve QUAL modelo é dona de uma mensagem por
-- `SELECT id FROM barravips.modelos WHERE evolution_instance_id = %s`
-- (webhook/routes.py), via fetchone() sem ORDER BY/LIMIT. A unicidade era
-- só disciplina operacional — nada no banco a garantia. Se duas modelos
-- compartilhassem o instance_id (erro de pareamento, restauro, troca de
-- conexão), a resolução escolheria uma modelo arbitrária e a mensagem do
-- cliente seria gravada na Conversa da modelo errada — vazamento cross-modelo.
--
-- Índice PARCIAL (WHERE ... IS NOT NULL) porque a coluna é nullable: modelos
-- ainda não pareadas têm evolution_instance_id NULL e não devem colidir entre
-- si. Mesmo padrão de modelos_cpf_unique nesta tabela.
--
-- Pré-condição verificada em prod (01/06/2026): zero duplicatas atuais, então
-- o índice cria sem erro.
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS modelos_evolution_instance_id_unique
  ON barravips.modelos (evolution_instance_id)
  WHERE evolution_instance_id IS NOT NULL;
