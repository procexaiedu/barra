-- 0034_seed_servicos_confirmados.sql
-- Enriquece seeds de atendimentos Confirmados (Bruno e Pedro) com programa+duracao em atendimento_servicos.
-- Os atendimentos Fechados (Thiago, Lucas, Diego, Ricardo) ja tinham entradas; os Confirmados ficavam
-- sem programa/duracao contratados, o que fazia a tela de detalhe da conversa nao mostrar contexto
-- relevante (o atendimento aberto so apresentava tipo + urgencia + valor).
--
-- Idempotente: roda 2x sem efeito colateral.

BEGIN;

-- ATD_BRUN_1 (Bruno x Bruna): duracao_horas estava 1.5, mas modelo_programas da Bruna so cobre 1h e 2h.
-- Alinhamos para 1.0 (combina com Programa Completo 1h por R$ 1.200 de Bruna).
UPDATE barravips.atendimentos
   SET duracao_horas = 1.0
 WHERE id = '91000000-0000-0000-0000-000000000008'
   AND duracao_horas = 1.5;

-- ATD_BRUN_1: Programa Completo 1h (Bruna -> R$ 1.200)
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000008',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000001',
  1200.00
)
ON CONFLICT DO NOTHING;

-- ATD_PEDR_1: Programa Completo 2h (Alessia -> R$ 2.500 programa; valor_acordado R$ 2.800 inclui R$ 300 deslocamento)
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000014',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000002',
  2500.00
)
ON CONFLICT DO NOTHING;

COMMIT;
