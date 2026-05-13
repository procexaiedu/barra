-- 0037_seed_painel_dados_hoje.sql
-- Popula dados para o Painel mostrar metricas do "Hoje" (fechamentos, perdas, valor bruto, lucro,
-- ticket medio, conversao, tendencia vs ontem) e agenda dos proximos 7 dias.
--
-- Hoje (referencia): 2026-05-13 (quarta).
-- Janela: 2026-05-12 (ontem) ate 2026-05-20 (proxima quarta).
--
-- Reusa clientes/conversas/modelos ja existentes (a1..., c1..., f1...).
-- IDs determinist­icos no padrao 91000000-...-00ab para idempotencia via ON CONFLICT DO NOTHING.
--
-- Numero curto: Alessia ate 13 -> novos #14..#22; Bruna ate 4 -> novos #5..#9.
--
-- Idempotente: roda 2x sem efeito colateral.

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
-- ONTEM (12/05) -- fechamento Alessia x Adriano (interno)
(
  '91000000-0000-0000-0000-0000000000a1', 14,
  'c1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000004',
  'Fechado', 'interno', 'agendado',
  '2026-05-12', '17:00:00', 2.0,
  NULL, NULL, 'apartamento',
  'pix', 2200.00, 2200.00, 40.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Atendimento interno 2h fechado em 12/05. Pagamento Pix validado.',
  '2026-05-12 16:00:00-03'::timestamptz, '2026-05-12 19:30:00-03'::timestamptz
),
-- ONTEM (12/05) -- perda Bruna x Renato (externo)
(
  '91000000-0000-0000-0000-0000000000b1', 5,
  'c1000000-0000-0000-0000-000000000014', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000014',
  'Perdido', 'externo', 'agendado',
  '2026-05-12', '20:00:00', 2.0,
  NULL, NULL, NULL,
  NULL, 1500.00, NULL, NULL,
  'preco', NULL,
  'nao_solicitado', false, 'IA',
  'Cliente desistiu por preco apos negociacao.',
  '2026-05-12 18:30:00-03'::timestamptz, '2026-05-12 21:15:00-03'::timestamptz
),
-- HOJE (13/05) -- fechamento Alessia x Ricardo (externo, recorrente)
(
  '91000000-0000-0000-0000-0000000000a2', 15,
  'c1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000001',
  'Fechado', 'externo', 'agendado',
  '2026-05-13', '09:00:00', 2.0,
  'Av. Atlantica, 1500 - Copacabana', 'Copacabana', 'hotel',
  'pix', 2800.00, 3000.00, 40.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Cliente recorrente. Massagem Tantrica 2h, fechado em 13/05 manha.',
  '2026-05-13 07:30:00-03'::timestamptz, '2026-05-13 11:15:00-03'::timestamptz
),
-- HOJE (13/05) -- fechamento Alessia x Felipe (interno)
(
  '91000000-0000-0000-0000-0000000000a3', 16,
  'c1000000-0000-0000-0000-000000000007', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000007',
  'Fechado', 'interno', 'agendado',
  '2026-05-13', '12:00:00', 2.0,
  NULL, NULL, 'apartamento',
  'pix', 2500.00, 2800.00, 40.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 2h interno fechado em 13/05.',
  '2026-05-13 10:00:00-03'::timestamptz, '2026-05-13 14:20:00-03'::timestamptz
),
-- HOJE (13/05) -- fechamento Bruna x Lucas (externo)
(
  '91000000-0000-0000-0000-0000000000b2', 6,
  'c1000000-0000-0000-0000-000000000010', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000010',
  'Fechado', 'externo', 'agendado',
  '2026-05-13', '10:00:00', 2.0,
  'Rua Visconde de Piraja, 200 - Ipanema', 'Ipanema', 'hotel',
  'pix', 2200.00, 2400.00, 35.00,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 2h, fechado em 13/05.',
  '2026-05-13 08:00:00-03'::timestamptz, '2026-05-13 12:30:00-03'::timestamptz
),
-- HOJE (13/05) -- perda Alessia x Julio (externo)
(
  '91000000-0000-0000-0000-0000000000a4', 17,
  'c1000000-0000-0000-0000-000000000015', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000015',
  'Perdido', 'externo', 'indefinido',
  NULL, NULL, NULL,
  NULL, NULL, NULL,
  NULL, NULL, NULL, NULL,
  'preco', NULL,
  'nao_solicitado', false, 'IA',
  'Cliente nao aceitou faixa de preco.',
  '2026-05-13 13:30:00-03'::timestamptz, '2026-05-13 15:10:00-03'::timestamptz
),
-- HOJE (13/05) -- perda Bruna x Rodrigo (externo)
(
  '91000000-0000-0000-0000-0000000000b3', 7,
  'c1000000-0000-0000-0000-000000000008', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000008',
  'Perdido', 'externo', 'agendado',
  '2026-05-13', '14:00:00', 1.0,
  NULL, NULL, NULL,
  NULL, 1200.00, NULL, NULL,
  'indisponibilidade', NULL,
  'nao_solicitado', false, 'IA',
  'Modelo sem disponibilidade no horario solicitado.',
  '2026-05-13 12:00:00-03'::timestamptz, '2026-05-13 16:20:00-03'::timestamptz
),
-- HOJE A NOITE (13/05 19h) -- Alessia x Thiago (externo, confirmado, vai aparecer na agenda)
(
  '91000000-0000-0000-0000-0000000000a5', 18,
  'c1000000-0000-0000-0000-000000000009', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000009',
  'Confirmado', 'externo', 'agendado',
  '2026-05-13', '19:00:00', 3.0,
  'Av. Vieira Souto, 800 - Ipanema', 'Ipanema', 'hotel',
  'pix', 3500.00, NULL, NULL,
  NULL, NULL,
  'validado', false, 'IA',
  'Programa Completo 3h confirmado para hoje 19h. Pix de deslocamento ja validado.',
  '2026-05-13 09:45:00-03'::timestamptz, '2026-05-13 11:00:00-03'::timestamptz
),
-- AMANHA (14/05 22h) -- Alessia x Ricardo (recorrente) Aguardando_confirmacao Pernoite
(
  '91000000-0000-0000-0000-0000000000a6', 19,
  'c1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000001',
  'Aguardando_confirmacao', 'externo', 'agendado',
  '2026-05-14', '22:00:00', 6.0,
  'Av. Atlantica, 1500 - Copacabana', 'Copacabana', 'hotel',
  'pix', 4500.00, NULL, NULL,
  NULL, NULL,
  'aguardando', false, 'IA',
  'Pernoite para 14/05. Cliente vai enviar Pix de deslocamento.',
  '2026-05-13 11:30:00-03'::timestamptz, '2026-05-13 11:35:00-03'::timestamptz
),
-- 15/05 20h -- Alessia x Diego Confirmado interno
(
  '91000000-0000-0000-0000-0000000000a7', 20,
  'c1000000-0000-0000-0000-000000000011', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000011',
  'Confirmado', 'interno', 'agendado',
  '2026-05-15', '20:00:00', 2.0,
  NULL, NULL, 'apartamento',
  'pix', 2500.00, NULL, NULL,
  NULL, NULL,
  'nao_solicitado', false, 'IA',
  'Atendimento interno confirmado para 15/05 20h.',
  '2026-05-12 22:00:00-03'::timestamptz, '2026-05-13 09:00:00-03'::timestamptz
),
-- 17/05 21h -- Alessia x Felipe Aguardando_confirmacao
(
  '91000000-0000-0000-0000-0000000000a8', 21,
  'c1000000-0000-0000-0000-000000000007', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000007',
  'Aguardando_confirmacao', 'externo', 'agendado',
  '2026-05-17', '21:00:00', 2.0,
  'Av. Lucio Costa, 2000 - Barra da Tijuca', 'Barra da Tijuca', 'hotel',
  'pix', 2200.00, NULL, NULL,
  NULL, NULL,
  'aguardando', false, 'IA',
  'Aguardando Pix de deslocamento para 17/05 21h.',
  '2026-05-13 10:00:00-03'::timestamptz, '2026-05-13 10:15:00-03'::timestamptz
),
-- 19/05 19h -- Alessia x Adriano Confirmado externo
(
  '91000000-0000-0000-0000-0000000000a9', 22,
  'c1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000004',
  'Confirmado', 'externo', 'agendado',
  '2026-05-19', '19:00:00', 2.0,
  'Rua Prudente de Morais, 500 - Ipanema', 'Ipanema', 'hotel',
  'pix', 1800.00, NULL, NULL,
  NULL, NULL,
  'validado', false, 'IA',
  'Confirmado para 19/05. Pix de deslocamento validado.',
  '2026-05-12 20:00:00-03'::timestamptz, '2026-05-13 08:00:00-03'::timestamptz
),
-- 16/05 20h -- Bruna x Lucas Confirmado externo
(
  '91000000-0000-0000-0000-0000000000b4', 8,
  'c1000000-0000-0000-0000-000000000010', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000010',
  'Confirmado', 'externo', 'agendado',
  '2026-05-16', '20:00:00', 2.0,
  'Rua Visconde de Piraja, 200 - Ipanema', 'Ipanema', 'hotel',
  'pix', 2200.00, NULL, NULL,
  NULL, NULL,
  'validado', false, 'IA',
  'Confirmado para 16/05 20h.',
  '2026-05-13 09:30:00-03'::timestamptz, '2026-05-13 09:40:00-03'::timestamptz
),
-- 18/05 21h -- Bruna x Renato Aguardando_confirmacao externo
(
  '91000000-0000-0000-0000-0000000000b5', 9,
  'c1000000-0000-0000-0000-000000000014', 'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000014',
  'Aguardando_confirmacao', 'externo', 'agendado',
  '2026-05-18', '21:00:00', 1.0,
  NULL, 'Leblon', 'hotel',
  'pix', 1200.00, NULL, NULL,
  NULL, NULL,
  'aguardando', false, 'IA',
  'Aguardando confirmacao para 18/05 21h.',
  '2026-05-13 10:30:00-03'::timestamptz, '2026-05-13 10:32:00-03'::timestamptz
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- ATENDIMENTO_SERVICOS (programa + duracao contratados)
-- ========================================================================

-- Resolve programa/duracao por nome (uuids de Alessia: e0... vs Beijo Grego: 4ea4...)
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot)
SELECT v.atendimento_id, p.id, d.id, v.preco
FROM (VALUES
  -- ONTEM Adriano: Programa Completo 2h Alessia (R$ 2500)
  ('91000000-0000-0000-0000-0000000000a1', 'Programa Completo', '2 horas', 2500.00),
  -- HOJE Ricardo: Massagem Tantrica 2h Alessia (R$ 3000)
  ('91000000-0000-0000-0000-0000000000a2', 'Massagem Tântrica', '2 horas', 3000.00),
  -- HOJE Felipe: Programa Completo 2h Alessia (R$ 2500)
  ('91000000-0000-0000-0000-0000000000a3', 'Programa Completo', '2 horas', 2500.00),
  -- HOJE Lucas: Programa Completo 2h Bruna (R$ 2200)
  ('91000000-0000-0000-0000-0000000000b2', 'Programa Completo', '2 horas', 2200.00),
  -- HOJE Thiago noite: Programa Completo 3h Alessia (R$ 3500)
  ('91000000-0000-0000-0000-0000000000a5', 'Programa Completo', '3 horas', 3500.00),
  -- AMANHA Ricardo: Pernoite (R$ 5500) — usar programa Pernoite (e0000000-...-04) duracao Pernoite
  ('91000000-0000-0000-0000-0000000000a6', 'Pernoite', 'Pernoite', 5500.00),
  -- 15/05 Diego: Programa Completo 2h Alessia (R$ 2500)
  ('91000000-0000-0000-0000-0000000000a7', 'Programa Completo', '2 horas', 2500.00),
  -- 17/05 Felipe: Programa Completo 2h Alessia (R$ 2500)
  ('91000000-0000-0000-0000-0000000000a8', 'Programa Completo', '2 horas', 2500.00),
  -- 19/05 Adriano: Programa Completo 2h Alessia (R$ 2500)
  ('91000000-0000-0000-0000-0000000000a9', 'Programa Completo', '2 horas', 2500.00),
  -- 16/05 Lucas: Programa Completo 2h Bruna (R$ 2200)
  ('91000000-0000-0000-0000-0000000000b4', 'Programa Completo', '2 horas', 2200.00),
  -- 18/05 Renato: Programa Completo 1h Bruna (R$ 1200)
  ('91000000-0000-0000-0000-0000000000b5', 'Programa Completo', '1 hora', 1200.00)
) AS v(atendimento_id, programa_nome, duracao_nome, preco)
JOIN barravips.programas p ON p.nome = v.programa_nome
JOIN barravips.duracoes d ON d.nome = v.duracao_nome
WHERE NOT EXISTS (
  SELECT 1 FROM barravips.atendimento_servicos a_s
   WHERE a_s.atendimento_id = v.atendimento_id::uuid
);

-- ========================================================================
-- EVENTOS (fechado_registrado / perdido_registrado) -- imprescindiveis para o painel contar
-- ========================================================================

INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
-- ONTEM
(
  'ef000000-0000-0000-0000-0000000000a1',
  '91000000-0000-0000-0000-0000000000a1',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 2200.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-12 19:30:00-03'::timestamptz
),
(
  'ef000000-0000-0000-0000-0000000000b1',
  '91000000-0000-0000-0000-0000000000b1',
  'perdido_registrado', 'grupo_coordenacao', 'modelo',
  '{"motivo": "preco"}'::jsonb,
  '2026-05-12 21:15:00-03'::timestamptz
),
-- HOJE
(
  'ef000000-0000-0000-0000-0000000000a2',
  '91000000-0000-0000-0000-0000000000a2',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 3000.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-13 11:15:00-03'::timestamptz
),
(
  'ef000000-0000-0000-0000-0000000000a3',
  '91000000-0000-0000-0000-0000000000a3',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 2800.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-13 14:20:00-03'::timestamptz
),
(
  'ef000000-0000-0000-0000-0000000000b2',
  '91000000-0000-0000-0000-0000000000b2',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"valor_final": 2400.00, "via": "comando_grupo"}'::jsonb,
  '2026-05-13 12:30:00-03'::timestamptz
),
(
  'ef000000-0000-0000-0000-0000000000a4',
  '91000000-0000-0000-0000-0000000000a4',
  'perdido_registrado', 'painel', 'Fernando',
  '{"motivo": "preco"}'::jsonb,
  '2026-05-13 15:10:00-03'::timestamptz
),
(
  'ef000000-0000-0000-0000-0000000000b3',
  '91000000-0000-0000-0000-0000000000b3',
  'perdido_registrado', 'painel', 'Fernando',
  '{"motivo": "indisponibilidade"}'::jsonb,
  '2026-05-13 16:20:00-03'::timestamptz
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- BLOQUEIOS (agenda) — concluidos (de hoje) + futuros (proxima semana) + pessoais
-- ========================================================================

INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao) VALUES
-- ONTEM 17h-19h Alessia (concluido) atrelado a Adriano
(
  'b1000000-0000-0000-0000-0000000000a1',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a1',
  '2026-05-12 17:00:00-03'::timestamptz, '2026-05-12 19:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
-- ONTEM 20h-22h Bruna (cancelado) atrelado a Renato (perda)
(
  'b1000000-0000-0000-0000-0000000000b1',
  'a1000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-0000000000b1',
  '2026-05-12 20:00:00-03'::timestamptz, '2026-05-12 22:00:00-03'::timestamptz,
  'cancelado', 'ia', NULL
),
-- HOJE 09h-11h Alessia (concluido) — Ricardo
(
  'b1000000-0000-0000-0000-0000000000a2',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a2',
  '2026-05-13 09:00:00-03'::timestamptz, '2026-05-13 11:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
-- HOJE 12h-14h Alessia (concluido) — Felipe
(
  'b1000000-0000-0000-0000-0000000000a3',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a3',
  '2026-05-13 12:00:00-03'::timestamptz, '2026-05-13 14:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
-- HOJE 10h-12h Bruna (concluido) — Lucas
(
  'b1000000-0000-0000-0000-0000000000b2',
  'a1000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-0000000000b2',
  '2026-05-13 10:00:00-03'::timestamptz, '2026-05-13 12:00:00-03'::timestamptz,
  'concluido', 'ia', NULL
),
-- HOJE 19h-22h Alessia (bloqueado) — Thiago (futuro hoje)
(
  'b1000000-0000-0000-0000-0000000000a5',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a5',
  '2026-05-13 19:00:00-03'::timestamptz, '2026-05-13 22:00:00-03'::timestamptz,
  'bloqueado', 'ia', NULL
),
-- HOJE 23h-24h Alessia bloqueio pessoal (origem painel_fernando, sem atendimento)
(
  'b1000000-0000-0000-0000-0000000000f1',
  'a1000000-0000-0000-0000-000000000001',
  NULL,
  '2026-05-13 23:00:00-03'::timestamptz, '2026-05-14 00:30:00-03'::timestamptz,
  'bloqueado', 'painel_fernando', 'Horario pessoal'
),
-- 14/05 22h-04h(15) Alessia (bloqueado) — Ricardo Pernoite
(
  'b1000000-0000-0000-0000-0000000000a6',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a6',
  '2026-05-14 22:00:00-03'::timestamptz, '2026-05-15 04:00:00-03'::timestamptz,
  'bloqueado', 'ia', NULL
),
-- 15/05 14h-18h Bruna bloqueio pessoal
(
  'b1000000-0000-0000-0000-0000000000f2',
  'a1000000-0000-0000-0000-000000000002',
  NULL,
  '2026-05-15 14:00:00-03'::timestamptz, '2026-05-15 18:00:00-03'::timestamptz,
  'bloqueado', 'painel_fernando', 'Horario pessoal'
),
-- 15/05 20h-22h Alessia (bloqueado) — Diego
(
  'b1000000-0000-0000-0000-0000000000a7',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a7',
  '2026-05-15 20:00:00-03'::timestamptz, '2026-05-15 22:00:00-03'::timestamptz,
  'bloqueado', 'ia', NULL
),
-- 16/05 20h-22h Bruna (bloqueado) — Lucas
(
  'b1000000-0000-0000-0000-0000000000b4',
  'a1000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-0000000000b4',
  '2026-05-16 20:00:00-03'::timestamptz, '2026-05-16 22:00:00-03'::timestamptz,
  'bloqueado', 'ia', NULL
),
-- 17/05 21h-23h Alessia (bloqueado) — Felipe
(
  'b1000000-0000-0000-0000-0000000000a8',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a8',
  '2026-05-17 21:00:00-03'::timestamptz, '2026-05-17 23:00:00-03'::timestamptz,
  'bloqueado', 'ia', NULL
),
-- 18/05 21h-22h Bruna (bloqueado) — Renato
(
  'b1000000-0000-0000-0000-0000000000b5',
  'a1000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-0000000000b5',
  '2026-05-18 21:00:00-03'::timestamptz, '2026-05-18 22:00:00-03'::timestamptz,
  'bloqueado', 'ia', NULL
),
-- 19/05 19h-21h Alessia (bloqueado) — Adriano
(
  'b1000000-0000-0000-0000-0000000000a9',
  'a1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a9',
  '2026-05-19 19:00:00-03'::timestamptz, '2026-05-19 21:00:00-03'::timestamptz,
  'bloqueado', 'ia', NULL
),
-- 20/05 dia inteiro Alessia bloqueio pessoal (folga)
(
  'b1000000-0000-0000-0000-0000000000f3',
  'a1000000-0000-0000-0000-000000000001',
  NULL,
  '2026-05-20 00:00:00-03'::timestamptz, '2026-05-21 00:00:00-03'::timestamptz,
  'bloqueado', 'painel_fernando', 'Folga'
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- Liga atendimentos aos bloqueios criados (atendimentos.bloqueio_id)
-- ========================================================================

UPDATE barravips.atendimentos a
   SET bloqueio_id = v.bloqueio_id::uuid,
       updated_at  = COALESCE(a.updated_at, now())
  FROM (VALUES
    ('91000000-0000-0000-0000-0000000000a1', 'b1000000-0000-0000-0000-0000000000a1'),
    ('91000000-0000-0000-0000-0000000000b1', 'b1000000-0000-0000-0000-0000000000b1'),
    ('91000000-0000-0000-0000-0000000000a2', 'b1000000-0000-0000-0000-0000000000a2'),
    ('91000000-0000-0000-0000-0000000000a3', 'b1000000-0000-0000-0000-0000000000a3'),
    ('91000000-0000-0000-0000-0000000000b2', 'b1000000-0000-0000-0000-0000000000b2'),
    ('91000000-0000-0000-0000-0000000000a5', 'b1000000-0000-0000-0000-0000000000a5'),
    ('91000000-0000-0000-0000-0000000000a6', 'b1000000-0000-0000-0000-0000000000a6'),
    ('91000000-0000-0000-0000-0000000000a7', 'b1000000-0000-0000-0000-0000000000a7'),
    ('91000000-0000-0000-0000-0000000000a8', 'b1000000-0000-0000-0000-0000000000a8'),
    ('91000000-0000-0000-0000-0000000000a9', 'b1000000-0000-0000-0000-0000000000a9'),
    ('91000000-0000-0000-0000-0000000000b4', 'b1000000-0000-0000-0000-0000000000b4'),
    ('91000000-0000-0000-0000-0000000000b5', 'b1000000-0000-0000-0000-0000000000b5')
  ) AS v(atendimento_id, bloqueio_id)
 WHERE a.id = v.atendimento_id::uuid
   AND a.bloqueio_id IS NULL;

COMMIT;
