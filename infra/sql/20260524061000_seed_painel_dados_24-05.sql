-- 20260524061000_seed_painel_dados_24-05.sql
-- Popula metricas do Painel/Dashboard para a janela "Hoje" = 2026-05-24 (domingo) e
-- "Ontem" = 2026-05-23, de modo que os cards Fechamentos/Perdas/Valor bruto/Lucro/Ticket/
-- Conversao saiam do zero e o comparativo "vs ontem" tenha base.
--
-- Espelha o padrao do 0037_seed_painel_dados_hoje.sql (que cravou 2026-05-13), agora para 24/05.
-- Reusa clientes/conversas/modelos existentes (a1..., c1..., f1...).
-- IDs deterministicos com prefixos novos para nao colidir com o 0037:
--   atendimentos  92000000-...-00NN   eventos ef100000-...   bloqueios b2000000-...
-- numero_curto livre: Alessia ate #25 -> #26..#31 ; Bruna ate #10 -> #11..#13.
--
-- Cards do dashboard leem: atendimentos (estado Fechado/Perdido) + eventos
-- (fechado_registrado/perdido_registrado, created_at na janela). Tudo em BRT (-03).
--
-- Resultado esperado HOJE (24/05): 4 fechamentos, bruto R$ 11.100, liquido R$ 6.780,
--   ticket medio R$ 2.775, 2 perdas, conversao 66,7%.
-- ONTEM (23/05): 2 fechamentos (bruto R$ 5.000), 1 perda.
--
-- Idempotente: roda 2x sem efeito colateral (ON CONFLICT DO NOTHING / NOT EXISTS).

BEGIN;

-- ========================================================================
-- ATENDIMENTOS
-- ========================================================================

INSERT INTO barravips.atendimentos (
  id, numero_curto, cliente_id, modelo_id, conversa_id,
  estado, tipo_atendimento, urgencia,
  data_desejada, horario_desejado, duracao_horas,
  endereco, bairro, tipo_local,
  forma_pagamento, valor_acordado, valor_final, percentual_repasse_snapshot,
  motivo_perda, motivo_perda_obs,
  pix_status, ia_pausada, responsavel_atual,
  resumo_operacional,
  created_at, updated_at
) VALUES
-- HOJE (24/05) -- fechamento Alessia x Ricardo (externo, recorrente) Massagem Tantrica 3h
(
  '92000000-0000-0000-0000-000000000026', 26,
  'c1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000001',
  'Fechado', 'externo', 'agendado',
  '2026-05-24', '00:00:00', 3.0,
  'Av. Atlantica, 1500 - Copacabana', 'Copacabana', 'hotel',
  'pix', 2800.00, 3200.00, 40.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Cliente recorrente. Massagem Tantrica 3h, fechado na madrugada de 24/05.',
  '2026-05-23 22:30:00-03'::timestamptz, '2026-05-24 01:05:00-03'::timestamptz
),
-- HOJE (24/05) -- fechamento Alessia x Gustavo (interno) Programa Completo 2h
(
  '92000000-0000-0000-0000-000000000027', 27,
  'c1000000-0000-0000-0000-000000000003', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000003',
  'Fechado', 'interno', 'agendado',
  '2026-05-24', '01:00:00', 2.0,
  NULL, NULL, 'apartamento',
  'pix', 2500.00, 2500.00, 40.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 2h interno fechado em 24/05.',
  '2026-05-23 23:00:00-03'::timestamptz, '2026-05-24 02:05:00-03'::timestamptz
),
-- HOJE (24/05) -- fechamento Alessia x Marcos (externo) Programa Completo 2h
(
  '92000000-0000-0000-0000-000000000028', 28,
  'c1000000-0000-0000-0000-000000000005', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000005',
  'Fechado', 'externo', 'agendado',
  '2026-05-24', '02:00:00', 2.0,
  'Rua Visconde de Piraja, 414 - Ipanema', 'Ipanema', 'hotel',
  'pix', 2800.00, 3000.00, 40.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 2h externo fechado em 24/05.',
  '2026-05-23 23:40:00-03'::timestamptz, '2026-05-24 02:50:00-03'::timestamptz
),
-- HOJE (24/05) -- fechamento Bruna x Lucas (externo) Programa Completo 2h
(
  '92000000-0000-0000-0000-000000000011', 11,
  'c1000000-0000-0000-0000-000000000010', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000010',
  'Fechado', 'externo', 'agendado',
  '2026-05-24', '00:00:00', 2.0,
  'Av. Vieira Souto, 120 - Ipanema', 'Ipanema', 'hotel',
  'pix', 2200.00, 2400.00, 35.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 2h, fechado na madrugada de 24/05.',
  '2026-05-23 22:00:00-03'::timestamptz, '2026-05-24 02:20:00-03'::timestamptz
),
-- HOJE (24/05) -- perda Alessia x Julio (externo) preco
(
  '92000000-0000-0000-0000-000000000029', 29,
  'c1000000-0000-0000-0000-000000000015', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000015',
  'Perdido', 'externo', 'indefinido',
  NULL, NULL, NULL,
  NULL, NULL, NULL,
  NULL, NULL, NULL, NULL,
  'preco', NULL,
  'nao_solicitado', false, 'IA',
  'Cliente nao aceitou a faixa de preco.',
  '2026-05-24 00:30:00-03'::timestamptz, '2026-05-24 01:40:00-03'::timestamptz
),
-- HOJE (24/05) -- perda Bruna x Rodrigo (externo) indisponibilidade
(
  '92000000-0000-0000-0000-000000000012', 12,
  'c1000000-0000-0000-0000-000000000008', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000008',
  'Perdido', 'externo', 'agendado',
  '2026-05-24', '01:00:00', 1.0,
  NULL, NULL, NULL,
  NULL, 1200.00, NULL, NULL,
  'indisponibilidade', NULL,
  'nao_solicitado', false, 'IA',
  'Sem disponibilidade no horario solicitado.',
  '2026-05-24 00:10:00-03'::timestamptz, '2026-05-24 02:30:00-03'::timestamptz
),
-- ONTEM (23/05) -- fechamento Alessia x Eduardo (externo) Programa Completo 2h
(
  '92000000-0000-0000-0000-000000000030', 30,
  'c1000000-0000-0000-0000-000000000002', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000002',
  'Fechado', 'externo', 'agendado',
  '2026-05-23', '20:00:00', 2.0,
  'Rua Prudente de Morais, 729 - Ipanema', 'Ipanema', 'hotel',
  'pix', 2600.00, 2800.00, 40.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 2h externo fechado em 23/05.',
  '2026-05-23 18:00:00-03'::timestamptz, '2026-05-23 22:10:00-03'::timestamptz
),
-- ONTEM (23/05) -- fechamento Bruna x Bruno (externo) Programa Completo 2h
(
  '92000000-0000-0000-0000-000000000013', 13,
  'c1000000-0000-0000-0000-000000000006', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000006',
  'Fechado', 'externo', 'agendado',
  '2026-05-23', '21:00:00', 2.0,
  'Av. das Americas, 500 - Barra da Tijuca', 'Barra da Tijuca', 'hotel',
  'pix', 2200.00, 2200.00, 35.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 2h externo fechado em 23/05.',
  '2026-05-23 19:00:00-03'::timestamptz, '2026-05-23 23:10:00-03'::timestamptz
),
-- ONTEM (23/05) -- perda Alessia x Pedro (externo) sumiu
(
  '92000000-0000-0000-0000-000000000031', 31,
  'c1000000-0000-0000-0000-000000000012', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000012',
  'Perdido', 'externo', 'agendado',
  '2026-05-23', '22:00:00', 2.0,
  NULL, NULL, NULL,
  NULL, NULL, NULL, NULL,
  'sumiu', NULL,
  'nao_solicitado', false, 'IA',
  'Cliente sumiu apos a cotacao.',
  '2026-05-23 17:00:00-03'::timestamptz, '2026-05-23 21:30:00-03'::timestamptz
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- ATENDIMENTO_SERVICOS (programa + duracao contratados) -- apenas fechados
-- ========================================================================

INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot)
SELECT v.atendimento_id::uuid, p.id, d.id, v.preco
FROM (VALUES
  ('92000000-0000-0000-0000-000000000026', 'Massagem Tântrica',  '3 horas', 3000.00),
  ('92000000-0000-0000-0000-000000000027', 'Programa Completo',  '2 horas', 2500.00),
  ('92000000-0000-0000-0000-000000000028', 'Programa Completo',  '2 horas', 2500.00),
  ('92000000-0000-0000-0000-000000000011', 'Programa Completo',  '2 horas', 2200.00),
  ('92000000-0000-0000-0000-000000000030', 'Programa Completo',  '2 horas', 2500.00),
  ('92000000-0000-0000-0000-000000000013', 'Programa Completo',  '2 horas', 2200.00)
) AS v(atendimento_id, programa_nome, duracao_nome, preco)
JOIN barravips.programas p ON p.nome = v.programa_nome
JOIN barravips.duracoes d ON d.nome = v.duracao_nome
WHERE NOT EXISTS (
  SELECT 1 FROM barravips.atendimento_servicos a_s
   WHERE a_s.atendimento_id = v.atendimento_id::uuid
);

-- ========================================================================
-- EVENTOS (fechado_registrado / perdido_registrado) -- o painel conta por estes
-- ========================================================================

INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
-- HOJE fechamentos
(
  'ef100000-0000-0000-0000-000000000026', '92000000-0000-0000-0000-000000000026',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 3200.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-24 01:05:00-03'::timestamptz
),
(
  'ef100000-0000-0000-0000-000000000027', '92000000-0000-0000-0000-000000000027',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 2500.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-24 02:05:00-03'::timestamptz
),
(
  'ef100000-0000-0000-0000-000000000028', '92000000-0000-0000-0000-000000000028',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 3000.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-24 02:50:00-03'::timestamptz
),
(
  'ef100000-0000-0000-0000-000000000011', '92000000-0000-0000-0000-000000000011',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 2400.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-24 02:20:00-03'::timestamptz
),
-- HOJE perdas
(
  'ef100000-0000-0000-0000-000000000029', '92000000-0000-0000-0000-000000000029',
  'perdido_registrado', 'painel', 'Fernando',
  '{"motivo": "preco"}'::jsonb,
  '2026-05-24 01:40:00-03'::timestamptz
),
(
  'ef100000-0000-0000-0000-000000000012', '92000000-0000-0000-0000-000000000012',
  'perdido_registrado', 'painel', 'Fernando',
  '{"motivo": "indisponibilidade"}'::jsonb,
  '2026-05-24 02:30:00-03'::timestamptz
),
-- ONTEM fechamentos
(
  'ef100000-0000-0000-0000-000000000030', '92000000-0000-0000-0000-000000000030',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 2800.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-23 22:10:00-03'::timestamptz
),
(
  'ef100000-0000-0000-0000-000000000013', '92000000-0000-0000-0000-000000000013',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 2200.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-23 23:10:00-03'::timestamptz
),
-- ONTEM perda
(
  'ef100000-0000-0000-0000-000000000031', '92000000-0000-0000-0000-000000000031',
  'perdido_registrado', 'painel', 'Fernando',
  '{"motivo": "sumiu"}'::jsonb,
  '2026-05-23 21:30:00-03'::timestamptz
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- BLOQUEIOS -- concluido (fechados) e cancelado (perdas).
-- Ambos sao isentos da EXCLUDE bloqueios_sem_sobreposicao (so vale p/ bloqueado/em_atendimento),
-- entao as faixas podem coincidir sem violar a constraint.
-- ========================================================================

INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao) VALUES
-- HOJE concluidos
(
  'b2000000-0000-0000-0000-000000000026', 'a1000000-0000-0000-0000-000000000001',
  '92000000-0000-0000-0000-000000000026',
  '2026-05-24 00:00:00-03'::timestamptz, '2026-05-24 03:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
(
  'b2000000-0000-0000-0000-000000000027', 'a1000000-0000-0000-0000-000000000001',
  '92000000-0000-0000-0000-000000000027',
  '2026-05-24 01:00:00-03'::timestamptz, '2026-05-24 03:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
(
  'b2000000-0000-0000-0000-000000000028', 'a1000000-0000-0000-0000-000000000001',
  '92000000-0000-0000-0000-000000000028',
  '2026-05-24 02:00:00-03'::timestamptz, '2026-05-24 04:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
(
  'b2000000-0000-0000-0000-000000000011', 'a1000000-0000-0000-0000-000000000002',
  '92000000-0000-0000-0000-000000000011',
  '2026-05-24 00:00:00-03'::timestamptz, '2026-05-24 02:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
-- HOJE cancelados (perdas)
(
  'b2000000-0000-0000-0000-000000000029', 'a1000000-0000-0000-0000-000000000001',
  '92000000-0000-0000-0000-000000000029',
  '2026-05-24 04:00:00-03'::timestamptz, '2026-05-24 05:00:00-03'::timestamptz,
  'cancelado', 'ia', NULL
),
(
  'b2000000-0000-0000-0000-000000000012', 'a1000000-0000-0000-0000-000000000002',
  '92000000-0000-0000-0000-000000000012',
  '2026-05-24 01:00:00-03'::timestamptz, '2026-05-24 02:00:00-03'::timestamptz,
  'cancelado', 'ia', NULL
),
-- ONTEM concluidos
(
  'b2000000-0000-0000-0000-000000000030', 'a1000000-0000-0000-0000-000000000001',
  '92000000-0000-0000-0000-000000000030',
  '2026-05-23 20:00:00-03'::timestamptz, '2026-05-23 22:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
(
  'b2000000-0000-0000-0000-000000000013', 'a1000000-0000-0000-0000-000000000002',
  '92000000-0000-0000-0000-000000000013',
  '2026-05-23 21:00:00-03'::timestamptz, '2026-05-23 23:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
-- ONTEM cancelado (perda)
(
  'b2000000-0000-0000-0000-000000000031', 'a1000000-0000-0000-0000-000000000001',
  '92000000-0000-0000-0000-000000000031',
  '2026-05-23 22:00:00-03'::timestamptz, '2026-05-24 00:00:00-03'::timestamptz,
  'cancelado', 'ia', NULL
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- Liga atendimentos aos bloqueios criados (atendimentos.bloqueio_id)
-- ========================================================================

UPDATE barravips.atendimentos a
   SET bloqueio_id = v.bloqueio_id::uuid,
       updated_at  = COALESCE(a.updated_at, now())
  FROM (VALUES
    ('92000000-0000-0000-0000-000000000026', 'b2000000-0000-0000-0000-000000000026'),
    ('92000000-0000-0000-0000-000000000027', 'b2000000-0000-0000-0000-000000000027'),
    ('92000000-0000-0000-0000-000000000028', 'b2000000-0000-0000-0000-000000000028'),
    ('92000000-0000-0000-0000-000000000011', 'b2000000-0000-0000-0000-000000000011'),
    ('92000000-0000-0000-0000-000000000029', 'b2000000-0000-0000-0000-000000000029'),
    ('92000000-0000-0000-0000-000000000012', 'b2000000-0000-0000-0000-000000000012'),
    ('92000000-0000-0000-0000-000000000030', 'b2000000-0000-0000-0000-000000000030'),
    ('92000000-0000-0000-0000-000000000013', 'b2000000-0000-0000-0000-000000000013'),
    ('92000000-0000-0000-0000-000000000031', 'b2000000-0000-0000-0000-000000000031')
  ) AS v(atendimento_id, bloqueio_id)
 WHERE a.id = v.atendimento_id::uuid
   AND a.bloqueio_id IS NULL;

COMMIT;
