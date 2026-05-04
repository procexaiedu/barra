-- =============================================================================
-- 0012_seed_painel_hoje.sql
-- Seed focado nos tiles de métricas do Painel Geral.
--
-- Popula para HOJE (BRT):
--   · 3 fechamentos — Valor Bruto R$ 5.500 | Lucro R$ 3.480
--   · 2 perdas
--
-- Popula para ONTEM (BRT, tendência vs ontem):
--   · 1 fechamento  — Valor Bruto R$ 1.800
--   · 1 perda
--
-- Timestamps ancorados pelo horário BRT do momento da execução:
--   hoje  = NOW() - N hours  (sempre dentro do dia corrente BRT se rodado de dia)
--   ontem = noon do dia anterior em BRT, calculado via:
--           (((NOW() AT TIME ZONE 'America/Sao_Paulo')::date - 1)::timestamp
--             + interval '12 hours') AT TIME ZONE 'America/Sao_Paulo'
--
-- Idempotente via ON CONFLICT (id) DO NOTHING.
-- =============================================================================

SET search_path TO barravips, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- Variáveis de conveniência (via CTE reutilizável abaixo em cada bloco)
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. Clientes
-- ---------------------------------------------------------------------------
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES
  ('c11e0000-0012-7000-8000-000000000001', '+5521911110001', 'Bruno Santos',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0012-7000-8000-000000000002', '+5521911110002', 'Carlos Mendes',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0012-7000-8000-000000000003', '+5521911110003', 'Rafael Costa',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0012-7000-8000-000000000004', '+5521911110004', 'Lucas Prado',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0012-7000-8000-000000000005', '+5521911110005', 'Thiago Nunes',
   '0e7e1000-0001-7000-8000-000000000002')
ON CONFLICT (telefone) DO NOTHING;


-- ---------------------------------------------------------------------------
-- 2. Conversas — uma por par (cliente, modelo)
-- ---------------------------------------------------------------------------
INSERT INTO barravips.conversas
  (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas)
VALUES
  ('c01f0000-0012-7000-8000-000000000001',
   'c11e0000-0012-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001',
   '5521911110001@s.whatsapp.net', false, NULL),
  ('c01f0000-0012-7000-8000-000000000002',
   'c11e0000-0012-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001',
   '5521911110002@s.whatsapp.net', false, NULL),
  ('c01f0000-0012-7000-8000-000000000003',
   'c11e0000-0012-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000002',
   '5521911110003@s.whatsapp.net', false, NULL),
  ('c01f0000-0012-7000-8000-000000000004',
   'c11e0000-0012-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000001',
   '5521911110004@s.whatsapp.net', false, NULL),
  ('c01f0000-0012-7000-8000-000000000005',
   'c11e0000-0012-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   '5521911110005@s.whatsapp.net', false, NULL)
ON CONFLICT (cliente_id, modelo_id) DO NOTHING;


-- ---------------------------------------------------------------------------
-- 3. Atendimentos — 3 Fechados (hoje) + 2 Perdidos (hoje)
-- ---------------------------------------------------------------------------
-- Stephanie #13 · Bruno Santos — Fechado, externo, R$ 1.500, repasse 40%
-- Stephanie #14 · Carlos Mendes — Fechado, interno, R$ 2.200, repasse 40%
-- Alessia   #6  · Rafael Costa  — Fechado, interno, R$ 1.800, repasse 30%
-- Stephanie #15 · Lucas Prado   — Perdido, externo, motivo: sumiu
-- Alessia   #7  · Thiago Nunes  — Perdido, interno, motivo: indisponibilidade
INSERT INTO barravips.atendimentos
  (id, numero_curto, cliente_id, modelo_id, conversa_id,
   estado, tipo_atendimento, urgencia,
   forma_pagamento, valor_acordado, valor_final, percentual_repasse_snapshot,
   motivo_perda,
   pix_status, ia_pausada, ia_pausada_motivo,
   responsavel_atual, fonte_decisao_ultima_transicao,
   created_at, updated_at)
VALUES
  -- S#13 Bruno Santos — Fechado hoje, externo, R$ 1.500
  ('a7e0d000-0012-7000-8000-000000000001', 13,
   'c11e0000-0012-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0012-7000-8000-000000000001',
   'Fechado', 'externo', 'agendado',
   'pix', 1500.00, 1500.00, 40.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '6 hours', NOW() - interval '4 hours'),

  -- S#14 Carlos Mendes — Fechado hoje, interno, R$ 2.200
  ('a7e0d000-0012-7000-8000-000000000002', 14,
   'c11e0000-0012-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0012-7000-8000-000000000002',
   'Fechado', 'interno', 'imediato',
   'dinheiro', 2200.00, 2200.00, 40.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '5 hours', NOW() - interval '2 hours'),

  -- A#6 Rafael Costa — Fechado hoje, interno, R$ 1.800
  ('a7e0d000-0012-7000-8000-000000000003', 6,
   'c11e0000-0012-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0012-7000-8000-000000000003',
   'Fechado', 'interno', 'agendado',
   'dinheiro', 1800.00, 1800.00, 30.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   NOW() - interval '4 hours', NOW() - interval '3 hours'),

  -- S#15 Lucas Prado — Perdido hoje, externo, sumiu
  ('a7e0d000-0012-7000-8000-000000000004', 15,
   'c11e0000-0012-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0012-7000-8000-000000000004',
   'Perdido', 'externo', 'indefinido',
   NULL, 1000.00, NULL, NULL,
   'sumiu', 'nao_solicitado', false, NULL,
   'IA', 'auto_timeout',
   NOW() - interval '3 hours', NOW() - interval '1 hour'),

  -- A#7 Thiago Nunes — Perdido hoje, interno, indisponibilidade
  ('a7e0d000-0012-7000-8000-000000000005', 7,
   'c11e0000-0012-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0012-7000-8000-000000000005',
   'Perdido', 'interno', 'agendado',
   'dinheiro', 1200.00, NULL, NULL,
   'indisponibilidade', 'nao_solicitado', false, NULL,
   'IA', 'extracao_ia',
   NOW() - interval '2 hours', NOW() - interval '30 minutes')
ON CONFLICT (id) DO NOTHING;


-- ---------------------------------------------------------------------------
-- 4. Eventos — fechado_registrado e perdido_registrado (HOJE)
-- ---------------------------------------------------------------------------
-- O backend filtra por:
--   e.tipo = 'fechado_registrado' | 'perdido_registrado'
--   e.created_at AT TIME ZONE 'America/Sao_Paulo' dentro do dia BRT
-- Usar NOW() aqui garante que os eventos caem no dia corrente em BRT
-- desde que o seed seja aplicado durante o dia.
INSERT INTO barravips.eventos
  (id, atendimento_id, tipo, origem, autor, payload, created_at)
VALUES
  -- Fechamentos hoje
  ('e1e10000-0012-7000-8000-000000000001',
   'a7e0d000-0012-7000-8000-000000000001',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1500.00, "comando": "finalizado 1500"}'::jsonb,
   NOW() - interval '4 hours'),

  ('e1e10000-0012-7000-8000-000000000002',
   'a7e0d000-0012-7000-8000-000000000002',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 2200.00, "comando": "finalizado 2200"}'::jsonb,
   NOW() - interval '2 hours'),

  ('e1e10000-0012-7000-8000-000000000003',
   'a7e0d000-0012-7000-8000-000000000003',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1800.00, "comando": "finalizado 1800"}'::jsonb,
   NOW() - interval '3 hours'),

  -- Perdas hoje
  ('e1e10000-0012-7000-8000-000000000004',
   'a7e0d000-0012-7000-8000-000000000004',
   'perdido_registrado', 'cron', 'sistema',
   '{"motivo": "sumiu", "fonte_decisao": "auto_timeout"}'::jsonb,
   NOW() - interval '1 hour'),

  ('e1e10000-0012-7000-8000-000000000005',
   'a7e0d000-0012-7000-8000-000000000005',
   'perdido_registrado', 'agente', 'IA',
   '{"motivo": "indisponibilidade"}'::jsonb,
   NOW() - interval '30 minutes')
ON CONFLICT (id) DO NOTHING;


-- ---------------------------------------------------------------------------
-- 5. Eventos de ontem (tendência vs ontem)
-- ---------------------------------------------------------------------------
-- Aponta para atendimentos já existentes do 0004_seed.sql:
--   #A2 Henrique (Alessia, Fechado) — a7e0d000-0001-7000-8000-000000000012
--   #S4 João    (Stephanie, Perdido) — a7e0d000-0001-7000-8000-000000000004
--
-- Usa noon do dia anterior em BRT para garantir que a query do backend
-- os coloque na janela "ontem" independente do horário de execução:
--   (((NOW() AT TIME ZONE 'America/Sao_Paulo')::date - 1)::timestamp
--     + interval '12 hours') AT TIME ZONE 'America/Sao_Paulo'
INSERT INTO barravips.eventos
  (id, atendimento_id, tipo, origem, autor, payload, created_at)
VALUES
  ('e1e10000-0012-7000-8000-000000000006',
   'a7e0d000-0001-7000-8000-000000000012',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 2500.00, "seed": "ontem_tendencia"}'::jsonb,
   (((NOW() AT TIME ZONE 'America/Sao_Paulo')::date - 1)::timestamp
     + interval '12 hours') AT TIME ZONE 'America/Sao_Paulo'),

  ('e1e10000-0012-7000-8000-000000000007',
   'a7e0d000-0001-7000-8000-000000000004',
   'perdido_registrado', 'agente', 'IA',
   '{"motivo": "preco", "seed": "ontem_tendencia"}'::jsonb,
   (((NOW() AT TIME ZONE 'America/Sao_Paulo')::date - 1)::timestamp
     + interval '13 hours') AT TIME ZONE 'America/Sao_Paulo')
ON CONFLICT (id) DO NOTHING;

COMMIT;

-- =============================================================================
-- Resultado esperado no painel (dia corrente em BRT):
--   FECHAMENTOS HOJE  → 3    (tendência: +2 vs ontem que teve 1)
--   PERDAS HOJE       → 2    (tendência: +1 vs ontem que teve 1)
--   VALOR BRUTO HOJE  → R$ 5.500,00  (tendência: +R$ 3.000 vs ontem R$ 2.500)
--   LUCRO HOJE        → R$ 3.480,00
--     Stephanie #13: 1500 × 60% = R$ 900
--     Stephanie #14: 2200 × 60% = R$ 1.320
--     Alessia   #6:  1800 × 70% = R$ 1.260
-- =============================================================================
