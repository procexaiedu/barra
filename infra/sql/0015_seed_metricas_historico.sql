-- =============================================================================
-- 0015_seed_metricas_historico.sql
-- Seed para popular os tiles de métricas do painel com dados reais ao longo
-- dos últimos 3 dias e oferecer comparação "vs ontem" significativa.
--
-- Timestamps ancorados via NOW() — aplicar durante o dia BRT para garantir
-- que os eventos caiam na data correta (mesmo mecanismo do 0012).
--
-- Resultado esperado nos tiles de métricas (dia da aplicação):
--
--   HOJE:
--     Fechamentos: 3  |  Valor Bruto: R$ 5.200  |  Lucro: R$ 3.100
--     Perdas: 2  |  Ticket Médio: R$ 1.733  |  Conversão: 60%
--
--   ONTEM (vs ontem nos tiles):
--     Fechamentos: 2  (+1 vs ontem)
--     Perdas: 1       (+1 vs ontem)
--     Valor Bruto: R$ 2.800  (+R$ 2.400 vs ontem)
--
--   2 DIAS ATRÁS:
--     Fechamentos: 2  |  Valor Bruto: R$ 4.000
--     Perdas: 1
--
--   (3 DIAS ATRÁS já populado pelo 0014 em timestamps fixos 2026-05-03)
--
-- Idempotente: ON CONFLICT (id) DO NOTHING.
-- =============================================================================

SET search_path TO barravips, public;

BEGIN;


-- ============================================================
-- 1. Clientes (11 novos — hoje + ontem + 2 dias atrás)
-- ============================================================
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id) VALUES
  -- Hoje (5)
  ('c11e0000-0015-7000-8000-000000000001', '+5521955550001', 'Caio Peixoto',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0015-7000-8000-000000000002', '+5521955550002', 'Thiago Batista',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0015-7000-8000-000000000003', '+5521955550003', 'Rafael Siqueira',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0015-7000-8000-000000000004', '+5521955550004', 'Mauricio Luz',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0015-7000-8000-000000000005', '+5521955550005', 'Flávio Dias',
   '0e7e1000-0001-7000-8000-000000000002'),
  -- Ontem (3)
  ('c11e0000-0015-7000-8000-000000000006', '+5521955550006', 'Breno Cavalcanti',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0015-7000-8000-000000000007', '+5521955550007', 'Lucas Borges',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0015-7000-8000-000000000008', '+5521955550008', 'Natan Serrano',
   '0e7e1000-0001-7000-8000-000000000001'),
  -- 2 dias atrás (3)
  ('c11e0000-0015-7000-8000-000000000009', '+5521955550009', 'Diogo Assunção',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0015-7000-8000-000000000010', '+5521955550010', 'Marcus Aragão',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0015-7000-8000-000000000011', '+5521955550011', 'Tiago Cintra',
   '0e7e1000-0001-7000-8000-000000000001')
ON CONFLICT (telefone) DO NOTHING;


-- ============================================================
-- 2. Conversas (11 novos pares)
-- ============================================================
INSERT INTO barravips.conversas
  (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas)
VALUES
  ('c01f0000-0015-7000-8000-000000000001',
   'c11e0000-0015-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001',
   '5521955550001@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000002',
   'c11e0000-0015-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001',
   '5521955550002@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000003',
   'c11e0000-0015-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000002',
   '5521955550003@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000004',
   'c11e0000-0015-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000001',
   '5521955550004@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000005',
   'c11e0000-0015-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   '5521955550005@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000006',
   'c11e0000-0015-7000-8000-000000000006', '0e7e1000-0001-7000-8000-000000000001',
   '5521955550006@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000007',
   'c11e0000-0015-7000-8000-000000000007', '0e7e1000-0001-7000-8000-000000000002',
   '5521955550007@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000008',
   'c11e0000-0015-7000-8000-000000000008', '0e7e1000-0001-7000-8000-000000000001',
   '5521955550008@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000009',
   'c11e0000-0015-7000-8000-000000000009', '0e7e1000-0001-7000-8000-000000000001',
   '5521955550009@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000010',
   'c11e0000-0015-7000-8000-000000000010', '0e7e1000-0001-7000-8000-000000000002',
   '5521955550010@s.whatsapp.net', false, NULL),
  ('c01f0000-0015-7000-8000-000000000011',
   'c11e0000-0015-7000-8000-000000000011', '0e7e1000-0001-7000-8000-000000000001',
   '5521955550011@s.whatsapp.net', false, NULL)
ON CONFLICT (cliente_id, modelo_id) DO NOTHING;


-- ============================================================
-- 3. Atendimentos — Fechados e Perdidos (3 dias de histórico)
-- ============================================================
-- HOJE: S#26 Fechado externo R$ 2.000 (40%) | S#27 Fechado interno R$ 1.400 (40%)
--       A#15 Fechado interno R$ 1.800 (30%) | S#28 Perdido preco | A#16 Perdido risco
-- ONTEM: S#29 Fechado externo R$ 1.600 (40%) | A#17 Fechado interno R$ 1.200 (30%)
--        S#30 Perdido sumiu
-- 2 DIAS ATRÁS: S#31 Fechado interno R$ 2.400 (40%) | A#18 Fechado interno R$ 1.600 (30%)
--               S#32 Perdido indisponibilidade
INSERT INTO barravips.atendimentos
  (id, numero_curto, cliente_id, modelo_id, conversa_id,
   estado, tipo_atendimento, urgencia,
   forma_pagamento, valor_acordado, valor_final, percentual_repasse_snapshot,
   motivo_perda,
   pix_status, ia_pausada, ia_pausada_motivo,
   responsavel_atual, fonte_decisao_ultima_transicao,
   created_at, updated_at)
VALUES

  -- ── HOJE ──────────────────────────────────────────────────────────

  -- S#26 Caio Peixoto — Fechado hoje, externo, R$ 2.000, repasse 40%
  ('a7e0d000-0015-7000-8000-000000000001', 26,
   'c11e0000-0015-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0015-7000-8000-000000000001',
   'Fechado', 'externo', 'agendado',
   'pix', 2000.00, 2000.00, 40.00,
   NULL, 'validado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '7 hours', NOW() - interval '5 hours'),

  -- S#27 Thiago Batista — Fechado hoje, interno, R$ 1.400, repasse 40%
  ('a7e0d000-0015-7000-8000-000000000002', 27,
   'c11e0000-0015-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0015-7000-8000-000000000002',
   'Fechado', 'interno', 'imediato',
   'dinheiro', 1400.00, 1400.00, 40.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '5 hours', NOW() - interval '3 hours'),

  -- A#15 Rafael Siqueira — Fechado hoje, interno, R$ 1.800, repasse 30%
  ('a7e0d000-0015-7000-8000-000000000003', 15,
   'c11e0000-0015-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0015-7000-8000-000000000003',
   'Fechado', 'interno', 'agendado',
   'dinheiro', 1800.00, 1800.00, 30.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '4 hours', NOW() - interval '2 hours'),

  -- S#28 Mauricio Luz — Perdido hoje, externo, preco
  ('a7e0d000-0015-7000-8000-000000000004', 28,
   'c11e0000-0015-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0015-7000-8000-000000000004',
   'Perdido', 'externo', 'indefinido',
   NULL, 1500.00, NULL, NULL,
   'preco', 'nao_solicitado', false, NULL,
   'IA', 'extracao_ia',
   NOW() - interval '6 hours', NOW() - interval '4 hours'),

  -- A#16 Flávio Dias — Perdido hoje, interno, risco
  ('a7e0d000-0015-7000-8000-000000000005', 16,
   'c11e0000-0015-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0015-7000-8000-000000000005',
   'Perdido', 'interno', 'imediato',
   NULL, 1200.00, NULL, NULL,
   'risco', 'nao_solicitado', false, NULL,
   'Fernando', 'painel_fernando',
   NOW() - interval '3 hours', NOW() - interval '1 hour'),

  -- ── ONTEM ─────────────────────────────────────────────────────────

  -- S#29 Breno Cavalcanti — Fechado ontem, externo, R$ 1.600, repasse 40%
  ('a7e0d000-0015-7000-8000-000000000006', 29,
   'c11e0000-0015-7000-8000-000000000006', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0015-7000-8000-000000000006',
   'Fechado', 'externo', 'agendado',
   'pix', 1600.00, 1600.00, 40.00,
   NULL, 'validado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '1 day' - interval '6 hours',
   NOW() - interval '1 day' - interval '4 hours'),

  -- A#17 Lucas Borges — Fechado ontem, interno, R$ 1.200, repasse 30%
  ('a7e0d000-0015-7000-8000-000000000007', 17,
   'c11e0000-0015-7000-8000-000000000007', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0015-7000-8000-000000000007',
   'Fechado', 'interno', 'agendado',
   'dinheiro', 1200.00, 1200.00, 30.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '1 day' - interval '4 hours',
   NOW() - interval '1 day' - interval '2 hours'),

  -- S#30 Natan Serrano — Perdido ontem, externo, sumiu
  ('a7e0d000-0015-7000-8000-000000000008', 30,
   'c11e0000-0015-7000-8000-000000000008', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0015-7000-8000-000000000008',
   'Perdido', 'externo', 'estimado',
   NULL, 1000.00, NULL, NULL,
   'sumiu', 'nao_solicitado', false, NULL,
   'IA', 'auto_timeout',
   NOW() - interval '1 day' - interval '5 hours',
   NOW() - interval '1 day' - interval '2 hours'),

  -- ── 2 DIAS ATRÁS ──────────────────────────────────────────────────

  -- S#31 Diogo Assunção — Fechado 2 dias atrás, interno, R$ 2.400, repasse 40%
  ('a7e0d000-0015-7000-8000-000000000009', 31,
   'c11e0000-0015-7000-8000-000000000009', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0015-7000-8000-000000000009',
   'Fechado', 'interno', 'agendado',
   'pix', 2400.00, 2400.00, 40.00,
   NULL, 'validado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '2 days' - interval '5 hours',
   NOW() - interval '2 days' - interval '3 hours'),

  -- A#18 Marcus Aragão — Fechado 2 dias atrás, interno, R$ 1.600, repasse 30%
  ('a7e0d000-0015-7000-8000-000000000010', 18,
   'c11e0000-0015-7000-8000-000000000010', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0015-7000-8000-000000000010',
   'Fechado', 'interno', 'imediato',
   'dinheiro', 1600.00, 1600.00, 30.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '2 days' - interval '7 hours',
   NOW() - interval '2 days' - interval '4 hours'),

  -- S#32 Tiago Cintra — Perdido 2 dias atrás, externo, indisponibilidade
  ('a7e0d000-0015-7000-8000-000000000011', 32,
   'c11e0000-0015-7000-8000-000000000011', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0015-7000-8000-000000000011',
   'Perdido', 'externo', 'agendado',
   NULL, 1800.00, NULL, NULL,
   'indisponibilidade', 'nao_solicitado', false, NULL,
   'Fernando', 'painel_fernando',
   NOW() - interval '2 days' - interval '4 hours',
   NOW() - interval '2 days' - interval '2 hours')

ON CONFLICT (id) DO NOTHING;


-- ============================================================
-- 4. Eventos — fechado_registrado e perdido_registrado
--    Timestamp dos eventos determina qual "dia BRT" o tile contabiliza.
-- ============================================================
INSERT INTO barravips.eventos
  (id, atendimento_id, tipo, origem, autor, payload, created_at)
VALUES

  -- ── HOJE ──────────────────────────────────────────────────────────

  ('e1e10000-0015-7000-8000-000000000001',
   'a7e0d000-0015-7000-8000-000000000001',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 2000.00, "comando": "finalizado 2000"}'::jsonb,
   NOW() - interval '5 hours'),

  ('e1e10000-0015-7000-8000-000000000002',
   'a7e0d000-0015-7000-8000-000000000002',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1400.00, "comando": "finalizado 1400"}'::jsonb,
   NOW() - interval '3 hours'),

  ('e1e10000-0015-7000-8000-000000000003',
   'a7e0d000-0015-7000-8000-000000000003',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1800.00, "comando": "finalizado 1800"}'::jsonb,
   NOW() - interval '2 hours'),

  ('e1e10000-0015-7000-8000-000000000004',
   'a7e0d000-0015-7000-8000-000000000004',
   'perdido_registrado', 'painel', 'Fernando',
   '{"motivo": "preco", "obs": "Cliente recusou valor padrão após longa negociação"}'::jsonb,
   NOW() - interval '4 hours'),

  ('e1e10000-0015-7000-8000-000000000005',
   'a7e0d000-0015-7000-8000-000000000005',
   'perdido_registrado', 'painel', 'Fernando',
   '{"motivo": "risco", "obs": "Perfil de risco confirmado após análise manual"}'::jsonb,
   NOW() - interval '1 hour'),

  -- ── ONTEM ─────────────────────────────────────────────────────────

  ('e1e10000-0015-7000-8000-000000000006',
   'a7e0d000-0015-7000-8000-000000000006',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1600.00, "comando": "finalizado 1600"}'::jsonb,
   NOW() - interval '1 day' - interval '4 hours'),

  ('e1e10000-0015-7000-8000-000000000007',
   'a7e0d000-0015-7000-8000-000000000007',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1200.00, "comando": "finalizado 1200"}'::jsonb,
   NOW() - interval '1 day' - interval '2 hours'),

  ('e1e10000-0015-7000-8000-000000000008',
   'a7e0d000-0015-7000-8000-000000000008',
   'perdido_registrado', 'cron', 'sistema',
   '{"motivo": "sumiu", "fonte_decisao": "auto_timeout"}'::jsonb,
   NOW() - interval '1 day' - interval '2 hours'),

  -- ── 2 DIAS ATRÁS ──────────────────────────────────────────────────

  ('e1e10000-0015-7000-8000-000000000009',
   'a7e0d000-0015-7000-8000-000000000009',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 2400.00, "comando": "finalizado 2400"}'::jsonb,
   NOW() - interval '2 days' - interval '3 hours'),

  ('e1e10000-0015-7000-8000-000000000010',
   'a7e0d000-0015-7000-8000-000000000010',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1600.00, "comando": "finalizado 1600"}'::jsonb,
   NOW() - interval '2 days' - interval '4 hours'),

  ('e1e10000-0015-7000-8000-000000000011',
   'a7e0d000-0015-7000-8000-000000000011',
   'perdido_registrado', 'painel', 'Fernando',
   '{"motivo": "indisponibilidade", "obs": "Horário solicitado fora da disponibilidade de Stephanie"}'::jsonb,
   NOW() - interval '2 days' - interval '2 hours')

ON CONFLICT (id) DO NOTHING;


COMMIT;
