-- 0035_seed_servicos_remanescentes.sql
-- Adiciona entradas em atendimento_servicos para os clientes seedados restantes
-- (Adriano, Caio, Eduardo, Felipe, Gustavo, Julio, Renato, Rodrigo) que tinham
-- programa+duracao implicitos via duracao_horas e valor_acordado mas nao tinham
-- linha em atendimento_servicos. Sem essas linhas, a tela de detalhe da conversa
-- nao mostrava Programa nem Duracao no card de atendimento aberto nem no historico.
--
-- Marcos Lima e pulado: o atendimento dele esta em Triagem (sem duracao_horas nem
-- valor_acordado), o que reflete que o programa ainda nao foi acordado com o
-- cliente -- o card deve mesmo aparecer sem programa/duracao.
--
-- Idempotente: roda 2x sem efeito colateral (ON CONFLICT DO NOTHING).

BEGIN;

-- Adriano Santana (Perdido, externo, 1h Alessia, R$ 1.500) -> Programa Completo 1h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000003',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000001',
  1500.00
)
ON CONFLICT DO NOTHING;

-- Caio Reis (Aguardando_confirmacao, externo, 2h Alessia, R$ 2.500) -> Programa Completo 2h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000015',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000002',
  2500.00
)
ON CONFLICT DO NOTHING;

-- Eduardo Luz (Qualificado, externo, 2h Alessia, R$ 2.500) -> Programa Completo 2h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000005',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000002',
  2500.00
)
ON CONFLICT DO NOTHING;

-- Felipe Ramos (Perdido, interno, 2h Alessia, R$ 1.500) -> Massagem Relaxante 2h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000009',
  'e0000000-0000-0000-0000-000000000001',
  'd0000000-0000-0000-0000-000000000002',
  1500.00
)
ON CONFLICT DO NOTHING;

-- Gustavo Moraes (Em_execucao, externo, 2h Alessia, R$ 1.500) -> Massagem Relaxante 2h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000006',
  'e0000000-0000-0000-0000-000000000001',
  'd0000000-0000-0000-0000-000000000002',
  1500.00
)
ON CONFLICT DO NOTHING;

-- Julio Souza (Perdido fora_de_area, externo, 2h Alessia, sem valor) -> Programa Completo 2h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000017',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000002',
  2500.00
)
ON CONFLICT DO NOTHING;

-- Renato Oliveira (Perdido indisponibilidade, externo, 2h Bruna, R$ 2.200) -> Programa Completo 2h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000016',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000002',
  2200.00
)
ON CONFLICT DO NOTHING;

-- Rodrigo Teixeira (Perdido risco, externo, 1h Bruna, R$ 1.200) -> Programa Completo 1h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000010',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000001',
  1200.00
)
ON CONFLICT DO NOTHING;

COMMIT;
