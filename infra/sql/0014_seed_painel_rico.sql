-- =============================================================================
-- 0014_seed_painel_rico.sql
-- Seed rico para validar UI/UX do painel: paginação, cards "Aguardando você",
-- agenda dos próximos 7 dias e métricas históricas.
--
-- Conteúdo:
--   Seção A: 10 cards "Aguardando você" (ia_pausada=true) cobrindo todos os
--            ia_pausada_motivo: pix_em_revisao (3), handoff_ia (4),
--            modelo_em_atendimento (3). Com escaladas abertas, comprovantes Pix
--            e bloqueios onde aplicável.
--   Seção B: 5 atendimentos de 3 dias atrás (2026-05-03): 3 Fechados + 2 Perdidos
--            para validar tendência histórica nas métricas.
--   Seção C: 2 atendimentos futuros Confirmados + 10 bloqueios na agenda dos
--            próximos 7 dias (2026-05-07 a 2026-05-13).
--
-- Stephanie ativa: externo + interno | numero_curto próximo = 16
-- Alessia ativa:   apenas interno     | numero_curto próximo = 8
--
-- Bloqueios EXCLUDE (ativos em 0004):
--   Stephanie hoje: B1 em_atendimento 14:00-16:00 BRT; B2 bloqueado 20:00-22:00 BRT
--                   B8 bloqueado amanhã 18:00-19:00 BRT
--   Alessia hoje:   nenhum ativo
-- Todos os novos bloqueios respeitam esses intervalos.
--
-- Idempotente: ON CONFLICT (id) DO NOTHING em todas as tabelas.
-- =============================================================================

SET search_path TO barravips, public;

BEGIN;


-- ============================================================
-- SEÇÃO A — "Aguardando você": 10 cards com ia_pausada=true
-- ============================================================

-- ------------------------------------------------------------
-- A.1  Clientes (10 novos)
-- ------------------------------------------------------------
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id) VALUES
  -- Cards com Stephanie (6)
  ('c11e0000-0014-7000-8000-000000000001', '+5521933330001', 'Igor Bittencourt',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000002', '+5521933330002', 'Renato Machado',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000004', '+5521933330004', 'Sérgio Andrade',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000006', '+5521933330006', 'Wellington Santos',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000009', '+5521933330009', 'Leandro Ramos',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000010', '+5521933330010', 'Eduardo Castro',
   '0e7e1000-0001-7000-8000-000000000001'),
  -- Cards com Alessia (4)
  ('c11e0000-0014-7000-8000-000000000003', '+5521933330003', 'Paulo Vieira',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0014-7000-8000-000000000005', '+5521933330005', 'Cláudio Ferraz',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0014-7000-8000-000000000007', '+5521933330007', 'Fábio Correia',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0014-7000-8000-000000000008', '+5521933330008', 'Gustavo Menezes',
   '0e7e1000-0001-7000-8000-000000000002')
ON CONFLICT (telefone) DO NOTHING;


-- ------------------------------------------------------------
-- A.2  Conversas (10 novos pares cliente×modelo)
-- ------------------------------------------------------------
INSERT INTO barravips.conversas
  (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas)
VALUES
  ('c01f0000-0014-7000-8000-000000000001',
   'c11e0000-0014-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001',
   '5521933330001@s.whatsapp.net', false,
   'Pediu saída para hotel na Barra. Enviou Pix abaixo do valor.'),
  ('c01f0000-0014-7000-8000-000000000002',
   'c11e0000-0014-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001',
   '5521933330002@s.whatsapp.net', false,
   'Fez perguntas ambíguas sobre disponibilidade de terceiros.'),
  ('c01f0000-0014-7000-8000-000000000004',
   'c11e0000-0014-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000001',
   '5521933330004@s.whatsapp.net', false,
   'Titular do comprovante Pix diverge do nome informado.'),
  ('c01f0000-0014-7000-8000-000000000006',
   'c11e0000-0014-7000-8000-000000000006', '0e7e1000-0001-7000-8000-000000000001',
   '5521933330006@s.whatsapp.net', false,
   'Saída confirmada. Modelo a caminho do Grand Hyatt.'),
  ('c01f0000-0014-7000-8000-000000000009',
   'c11e0000-0014-7000-8000-000000000009', '0e7e1000-0001-7000-8000-000000000001',
   '5521933330009@s.whatsapp.net', false,
   'Comprovante Pix ilegível — imagem borrada enviada pelo cliente.'),
  ('c01f0000-0014-7000-8000-000000000010',
   'c11e0000-0014-7000-8000-000000000010', '0e7e1000-0001-7000-8000-000000000001',
   '5521933330010@s.whatsapp.net', false,
   'Histórico suspeito relatado por operação. Avaliar risco antes de prosseguir.'),
  ('c01f0000-0014-7000-8000-000000000003',
   'c11e0000-0014-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000002',
   '5521933330003@s.whatsapp.net', false,
   'Cliente chegou ao apartamento. Foto de portaria recebida.'),
  ('c01f0000-0014-7000-8000-000000000005',
   'c11e0000-0014-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   '5521933330005@s.whatsapp.net', false,
   'Negociação abaixo do mínimo. Pediu R$ 900 para 2h.'),
  ('c01f0000-0014-7000-8000-000000000007',
   'c11e0000-0014-7000-8000-000000000007', '0e7e1000-0001-7000-8000-000000000002',
   '5521933330007@s.whatsapp.net', false,
   'Solicitou serviços fora do escopo padrão do FAQ.'),
  ('c01f0000-0014-7000-8000-000000000008',
   'c11e0000-0014-7000-8000-000000000008', '0e7e1000-0001-7000-8000-000000000002',
   '5521933330008@s.whatsapp.net', false,
   'Foto de portaria recebida. Atendimento em execução.')
ON CONFLICT (cliente_id, modelo_id) DO NOTHING;


-- ------------------------------------------------------------
-- A.3  Atendimentos aguardando você (ia_pausada=true)
-- ------------------------------------------------------------
-- S#16  Igor Bittencourt     — PIX EM REVISÃO   (pix_em_revisao)
-- S#17  Renato Machado       — AGUARDANDO DECISÃO (handoff_ia)
-- S#18  Sérgio Andrade       — PIX EM REVISÃO   (pix_em_revisao)
-- S#19  Wellington Santos    — MODELO COM CLIENTE (modelo_em_atendimento, Confirmado)
-- S#20  Leandro Ramos        — PIX EM REVISÃO   (pix_em_revisao)
-- S#21  Eduardo Castro       — AGUARDANDO DECISÃO (handoff_ia)
-- A#8   Paulo Vieira         — MODELO COM CLIENTE (modelo_em_atendimento, Em_execucao)
-- A#9   Cláudio Ferraz       — AGUARDANDO DECISÃO (handoff_ia)
-- A#10  Fábio Correia        — AGUARDANDO DECISÃO (handoff_ia)
-- A#11  Gustavo Menezes      — MODELO COM CLIENTE (modelo_em_atendimento, Em_execucao)
INSERT INTO barravips.atendimentos
  (id, numero_curto, cliente_id, modelo_id, conversa_id,
   estado, tipo_atendimento, urgencia,
   data_desejada, horario_desejado, duracao_horas,
   endereco, bairro, tipo_local, referencia_local,
   forma_pagamento, valor_acordado,
   pix_status, aviso_saida_em, foto_portaria_em,
   ia_pausada, ia_pausada_motivo, responsavel_atual,
   motivo_escalada, proxima_acao_esperada, resumo_operacional,
   sinais_qualificacao, fonte_decisao_ultima_transicao,
   created_at, updated_at)
VALUES

  -- S#16 Igor — PIX EM REVISÃO: externo, Qualificado, pix_em_revisao
  ('a7e0d000-0014-7000-8000-000000000001', 16,
   'c11e0000-0014-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000001',
   'Qualificado', 'externo', 'agendado',
   CURRENT_DATE, '20:00', 2.0,
   'Av. Lúcio Costa, 3150, Barra da Tijuca', 'Barra da Tijuca', 'hotel',
   'Windsor Barra Hotel — pedir por Igor na recepção',
   'pix', 1500.00,
   'em_revisao', NULL, NULL,
   true, 'pix_em_revisao', 'Fernando',
   'Pix de deslocamento com valor divergente',
   'Validar ou recusar comprovante — cliente enviou R$ 200 mas o valor combinado de deslocamento é R$ 350',
   'Cliente qualificado: confirmou horário, local e valor. Enviou Pix de deslocamento mas valor está incorreto.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'pipeline_pix',
   NOW() - interval '22 hours', NOW() - interval '2 hours'),

  -- S#17 Renato — AGUARDANDO DECISÃO: externo, Triagem, handoff_ia
  ('a7e0d000-0014-7000-8000-000000000002', 17,
   'c11e0000-0014-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000002',
   'Triagem', 'externo', 'imediato',
   NULL, NULL, NULL,
   NULL, NULL, NULL, NULL,
   NULL, NULL,
   'nao_solicitado', NULL, NULL,
   true, 'handoff_ia', 'Fernando',
   'Comportamento ambíguo',
   'Decidir se prossegue ou encerra atendimento — cliente perguntou sobre disponibilidade de terceiros para "programa em grupo"',
   'Cliente entrou em contato solicitando informações fora do escopo. Perguntas ambíguas sobre acompanhantes adicionais.',
   '{"informa_horario": false, "informa_local": false, "aceita_valor": false, "envia_pix": false, "responde_objetivamente": false}'::jsonb,
   'extracao_ia',
   NOW() - interval '5 hours', NOW() - interval '5 hours'),

  -- S#18 Sérgio — PIX EM REVISÃO: externo, Aguardando_confirmacao, pix_em_revisao
  ('a7e0d000-0014-7000-8000-000000000003', 18,
   'c11e0000-0014-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000004',
   'Aguardando_confirmacao', 'externo', 'estimado',
   CURRENT_DATE, '18:00', 3.0,
   'Rua Vinícius de Moraes, 80, Ipanema', 'Ipanema', 'hotel',
   'Hotel Fasano Rio — andar 8, quarto 812',
   'pix', 2500.00,
   'em_revisao', NULL, NULL,
   true, 'pix_em_revisao', 'Fernando',
   'Titular do comprovante Pix não confere com o nome do cliente',
   'Confirmar identidade ou recusar — comprovante em nome de "João Paulo Andrade", mas cliente apresentado como Sérgio',
   'Cliente qualificado para saída no Fasano. Todos os sinais positivos. Pix enviado mas titular diverge.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'pipeline_pix',
   NOW() - interval '3 hours', NOW() - interval '1 hour'),

  -- S#19 Wellington — MODELO COM CLIENTE: externo, Confirmado, modelo_em_atendimento
  -- Bloqueio ativo: hoje 16:00-18:00 BRT (slot livre entre B1 16h e B2 20h)
  ('a7e0d000-0014-7000-8000-000000000004', 19,
   'c11e0000-0014-7000-8000-000000000006', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000006',
   'Confirmado', 'externo', 'agendado',
   CURRENT_DATE, '16:00', 2.0,
   'Avenidas das Américas, 777, Barra da Tijuca', 'Barra da Tijuca', 'hotel',
   'Grand Hyatt Rio de Janeiro — recepção principal, andar térreo',
   'pix', 1800.00,
   'validado', NOW() - interval '1 hour 15 minutes', NULL,
   true, 'modelo_em_atendimento', 'modelo',
   'Pix de deslocamento aprovado — modelo em deslocamento',
   'Modelo a caminho do destino — aguardar confirmação de chegada ao Grand Hyatt',
   'Pix de deslocamento validado pelo pipeline. Modelo saiu para o cliente. Atendimento externo confirmado.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'pipeline_pix',
   NOW() - interval '5 hours', NOW() - interval '1 hour'),

  -- S#20 Leandro — PIX EM REVISÃO: externo, Qualificado, pix_em_revisao
  ('a7e0d000-0014-7000-8000-000000000005', 20,
   'c11e0000-0014-7000-8000-000000000009', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000009',
   'Qualificado', 'externo', 'estimado',
   CURRENT_DATE, '22:00', 2.0,
   'Rua Dias Ferreira, 45, Leblon', 'Leblon', 'apartamento',
   'Portaria Edifício Meridiano — falar com Mario (porteiro)',
   'pix', 1800.00,
   'em_revisao', NULL, NULL,
   true, 'pix_em_revisao', 'Fernando',
   'Comprovante Pix ilegível',
   'Solicitar reenvio ou rejeitar — imagem do comprovante com qualidade insuficiente para extração automática',
   'Cliente qualificado para saída no Leblon. Comprovante de Pix enviado, mas imagem borrada impediu leitura.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'pipeline_pix',
   NOW() - interval '4 hours', NOW() - interval '4 hours'),

  -- S#21 Eduardo — AGUARDANDO DECISÃO: externo, Qualificado, handoff_ia
  ('a7e0d000-0014-7000-8000-000000000006', 21,
   'c11e0000-0014-7000-8000-000000000010', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000010',
   'Qualificado', 'externo', 'indefinido',
   NULL, NULL, NULL,
   NULL, NULL, NULL, NULL,
   'pix', 1500.00,
   'nao_solicitado', NULL, NULL,
   true, 'handoff_ia', 'Fernando',
   'Perfil de risco identificado',
   'Avaliar histórico antes de prosseguir — relatos de comportamento problemático em outras operações',
   'Cliente demonstrou interesse e aceitou valor. IA identificou padrão suspeito e escalou para decisão.',
   '{"informa_horario": false, "informa_local": false, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": false}'::jsonb,
   'extracao_ia',
   NOW() - interval '12 hours', NOW() - interval '12 hours'),

  -- A#8 Paulo — MODELO COM CLIENTE: interno, Em_execucao, modelo_em_atendimento
  -- Bloqueio ativo: hoje 12:30-14:30 BRT (Alessia não tem bloqueio ativo hoje)
  ('a7e0d000-0014-7000-8000-000000000007', 8,
   'c11e0000-0014-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000003',
   'Em_execucao', 'interno', 'imediato',
   CURRENT_DATE, '12:30', 2.0,
   NULL, NULL, NULL, NULL,
   'dinheiro', 1200.00,
   'nao_solicitado', NULL, NOW() - interval '2 hours',
   true, 'modelo_em_atendimento', 'modelo',
   'Foto de portaria recebida — cliente chegou ao apartamento da Alessia',
   'Atendimento em andamento — aguardar encerramento e registro de resultado',
   'Cliente interno. Chegou ao apartamento e enviou foto da portaria. Atendimento em execução.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'webhook_imagem',
   NOW() - interval '4 hours', NOW() - interval '2 hours'),

  -- A#9 Cláudio — AGUARDANDO DECISÃO: interno, Triagem, handoff_ia
  ('a7e0d000-0014-7000-8000-000000000008', 9,
   'c11e0000-0014-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000005',
   'Triagem', 'interno', 'indefinido',
   NULL, NULL, NULL,
   NULL, NULL, NULL, NULL,
   'dinheiro', 900.00,
   'nao_solicitado', NULL, NULL,
   true, 'handoff_ia', 'Fernando',
   'Negociação abaixo do valor mínimo',
   'Autorizar desconto especial ou manter valor padrão — cliente ofereceu R$ 900 para 2h (mínimo Alessia: R$ 1.200)',
   'Cliente em triagem. Aceitou o programa mas tentou negociar valor abaixo do piso.',
   '{"informa_horario": false, "informa_local": false, "aceita_valor": false, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'extracao_ia',
   NOW() - interval '3 hours', NOW() - interval '3 hours'),

  -- A#10 Fábio — AGUARDANDO DECISÃO: interno, Qualificado, handoff_ia
  ('a7e0d000-0014-7000-8000-000000000009', 10,
   'c11e0000-0014-7000-8000-000000000007', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000007',
   'Qualificado', 'interno', 'agendado',
   CURRENT_DATE + 1, '19:00', 2.0,
   NULL, NULL, NULL, NULL,
   'dinheiro', 1200.00,
   'nao_solicitado', NULL, NULL,
   true, 'handoff_ia', 'Fernando',
   'Cliente solicitou serviços fora do escopo padrão',
   'Confirmar quais serviços podem ser oferecidos neste atendimento antes de prosseguir',
   'Cliente qualificado para amanhã às 19h. Perguntou sobre serviços não listados no FAQ de Alessia.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'extracao_ia',
   NOW() - interval '8 hours', NOW() - interval '8 hours'),

  -- A#11 Gustavo — MODELO COM CLIENTE: interno, Em_execucao, modelo_em_atendimento
  -- Bloqueio ativo: hoje 11:00-12:00 BRT (antes do de Paulo, sem sobreposição)
  ('a7e0d000-0014-7000-8000-000000000010', 11,
   'c11e0000-0014-7000-8000-000000000008', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000008',
   'Em_execucao', 'interno', 'imediato',
   CURRENT_DATE, '11:00', 1.0,
   NULL, NULL, NULL, NULL,
   'dinheiro', 1200.00,
   'nao_solicitado', NULL, NOW() - interval '1 hour 30 minutes',
   true, 'modelo_em_atendimento', 'modelo',
   'Cliente chegou ao apartamento — foto de portaria recebida',
   'Atendimento em andamento — aguardar comando de encerramento da Alessia',
   'Atendimento de 1h. Cliente chegou no horário e enviou foto da portaria.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'webhook_imagem',
   NOW() - interval '2 hours', NOW() - interval '1 hour 30 minutes')

ON CONFLICT (id) DO NOTHING;


-- ------------------------------------------------------------
-- A.4  Mensagens para comprovantes Pix em revisão
--      (S#16 Igor, S#18 Sérgio, S#20 Leandro)
-- ------------------------------------------------------------
INSERT INTO barravips.mensagens
  (id, conversa_id, atendimento_id, direcao, tipo, conteudo,
   media_object_key, evolution_message_id, created_at)
VALUES
  ('0e550000-0014-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000001',
   'a7e0d000-0014-7000-8000-000000000001',
   'cliente', 'imagem', '',
   'comprovantes/0014/igor_pix_deslocamento.jpg',
   'evo_msg_0014_pix_igor_001',
   NOW() - interval '2 hours 10 minutes'),

  ('0e550000-0014-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000004',
   'a7e0d000-0014-7000-8000-000000000003',
   'cliente', 'imagem', '',
   'comprovantes/0014/sergio_pix_deslocamento.jpg',
   'evo_msg_0014_pix_sergio_001',
   NOW() - interval '1 hour 5 minutes'),

  ('0e550000-0014-7000-8000-000000000003',
   'c01f0000-0014-7000-8000-000000000009',
   'a7e0d000-0014-7000-8000-000000000005',
   'cliente', 'imagem', '',
   'comprovantes/0014/leandro_pix_deslocamento.jpg',
   'evo_msg_0014_pix_leandro_001',
   NOW() - interval '4 hours 5 minutes')

ON CONFLICT (evolution_message_id) DO NOTHING;


-- ------------------------------------------------------------
-- A.5  Comprovantes Pix (em_revisao — decisao_final pendente)
-- ------------------------------------------------------------
INSERT INTO barravips.comprovantes_pix
  (id, atendimento_id, mensagem_id,
   valor_extraido, chave_extraida, titular_extraido, timestamp_extraido,
   decisao_pipeline, motivo_em_revisao,
   decisao_final, decisao_final_por, created_at)
VALUES
  -- Igor: valor incorreto (R$ 200 vs R$ 350 esperado)
  ('c0510000-0014-7000-8000-000000000001',
   'a7e0d000-0014-7000-8000-000000000001',
   '0e550000-0014-7000-8000-000000000001',
   200.00, '21999990001', 'Stephanie Lima de Souza',
   NOW() - interval '2 hours 8 minutes',
   'em_revisao', 'valor_incorreto',
   NULL, NULL,
   NOW() - interval '2 hours 8 minutes'),

  -- Sérgio: titular divergente
  ('c0510000-0014-7000-8000-000000000002',
   'a7e0d000-0014-7000-8000-000000000003',
   '0e550000-0014-7000-8000-000000000002',
   350.00, 'joao.paulo.andrade@email.com', 'João Paulo Andrade',
   NOW() - interval '1 hour 3 minutes',
   'em_revisao', 'titular_divergente',
   NULL, NULL,
   NOW() - interval '1 hour 3 minutes'),

  -- Leandro: imagem ilegível — sem extração
  ('c0510000-0014-7000-8000-000000000003',
   'a7e0d000-0014-7000-8000-000000000005',
   '0e550000-0014-7000-8000-000000000003',
   NULL, NULL, NULL, NULL,
   'em_revisao', 'comprovante_ilegivel',
   NULL, NULL,
   NOW() - interval '4 hours 3 minutes')

ON CONFLICT (id) DO NOTHING;


-- ------------------------------------------------------------
-- A.6  Bloqueios ativos para os cards Em_execucao / Confirmado
--
-- Stephanie (slots livres hoje entre os existentes do 0004):
--   B1 existente: 14:00-16:00 (em_atendimento) → S#19 Wellington usa 16:00-18:00
-- Alessia (sem bloqueio ativo):
--   A#8 Paulo  12:30-14:30
--   A#11 Gustavo 11:00-12:00 (termina antes de Paulo começar)
-- ------------------------------------------------------------
INSERT INTO barravips.bloqueios
  (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao,
   created_at, updated_at)
VALUES
  -- Wellington (S#19) — Stephanie 16:00-18:00 BRT (entre B1 e B2)
  ('b10c0000-0014-7000-8000-000000000001',
   '0e7e1000-0001-7000-8000-000000000001',
   'a7e0d000-0014-7000-8000-000000000004',
   (CURRENT_DATE + time '16:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE + time '18:00') AT TIME ZONE 'America/Sao_Paulo',
   'bloqueado', 'ia',
   'Saída confirmada Wellington — Grand Hyatt Barra. Pix validado.',
   NOW() - interval '5 hours', NOW() - interval '1 hour'),

  -- Paulo Vieira (A#8) — Alessia 12:30-14:30 BRT
  ('b10c0000-0014-7000-8000-000000000002',
   '0e7e1000-0001-7000-8000-000000000002',
   'a7e0d000-0014-7000-8000-000000000007',
   (CURRENT_DATE + time '12:30') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE + time '14:30') AT TIME ZONE 'America/Sao_Paulo',
   'em_atendimento', 'ia',
   'Atendimento interno Paulo Vieira. Foto de portaria recebida.',
   NOW() - interval '4 hours', NOW() - interval '2 hours'),

  -- Gustavo Menezes (A#11) — Alessia 11:00-12:00 BRT
  ('b10c0000-0014-7000-8000-000000000003',
   '0e7e1000-0001-7000-8000-000000000002',
   'a7e0d000-0014-7000-8000-000000000010',
   (CURRENT_DATE + time '11:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE + time '12:00') AT TIME ZONE 'America/Sao_Paulo',
   'em_atendimento', 'ia',
   'Atendimento interno Gustavo Menezes. 1h.',
   NOW() - interval '2 hours', NOW() - interval '1 hour 30 minutes')

ON CONFLICT (id) DO NOTHING;

-- Vincula bloqueios aos atendimentos (FK circular)
UPDATE barravips.atendimentos SET bloqueio_id = 'b10c0000-0014-7000-8000-000000000001'
 WHERE id = 'a7e0d000-0014-7000-8000-000000000004' AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos SET bloqueio_id = 'b10c0000-0014-7000-8000-000000000002'
 WHERE id = 'a7e0d000-0014-7000-8000-000000000007' AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos SET bloqueio_id = 'b10c0000-0014-7000-8000-000000000003'
 WHERE id = 'a7e0d000-0014-7000-8000-000000000010' AND bloqueio_id IS NULL;


-- ------------------------------------------------------------
-- A.7  Escaladas abertas (uma por card — fechada_em IS NULL)
-- ------------------------------------------------------------
INSERT INTO barravips.escaladas
  (id, atendimento_id, responsavel, motivo, resumo_operacional,
   acao_esperada, card_message_id, aberta_em, fechada_em)
VALUES
  -- S#16 Igor — pix_em_revisao, Fernando
  ('e5ca0000-0014-7000-8000-000000000001',
   'a7e0d000-0014-7000-8000-000000000001',
   'Fernando',
   'Pix de deslocamento com valor divergente',
   'Cliente Igor Bittencourt (Stephanie #16) enviou comprovante Pix de R$ 200 para saída no Windsor Barra, mas o valor combinado de deslocamento é R$ 350. Pipeline identificou inconsistência.',
   'Validar ou recusar comprovante. Se recusar, IA informa cliente para reenviar pelo valor correto.',
   'evo_card_0014_escalada_001',
   NOW() - interval '2 hours', NULL),

  -- S#17 Renato — handoff_ia, Fernando
  ('e5ca0000-0014-7000-8000-000000000002',
   'a7e0d000-0014-7000-8000-000000000002',
   'Fernando',
   'Comportamento ambíguo — possível solicitação de serviços não permitidos',
   'Cliente Renato Machado (Stephanie #17) fez perguntas sobre disponibilidade de "acompanhante extra para programa em grupo". IA não conseguiu classificar com segurança e pausou para decisão.',
   'Decidir se encerra o atendimento ou prossegue com esclarecimento do escopo.',
   'evo_card_0014_escalada_002',
   NOW() - interval '5 hours', NULL),

  -- S#18 Sérgio — pix_em_revisao, Fernando
  ('e5ca0000-0014-7000-8000-000000000003',
   'a7e0d000-0014-7000-8000-000000000003',
   'Fernando',
   'Titular do Pix diverge do nome do cliente',
   'Cliente Sérgio Andrade (Stephanie #18) enviou Pix de deslocamento com titular "João Paulo Andrade". Valor correto (R$ 350), mas identidade não confere com o cadastro.',
   'Confirmar identidade via foto do documento ou recusar o Pix e solicitar reenvio da conta correta.',
   'evo_card_0014_escalada_003',
   NOW() - interval '1 hour', NULL),

  -- S#19 Wellington — modelo_em_atendimento
  ('e5ca0000-0014-7000-8000-000000000004',
   'a7e0d000-0014-7000-8000-000000000004',
   'modelo',
   'Pix de deslocamento aprovado — modelo em deslocamento para o cliente',
   'Wellington Santos (Stephanie #19): saída confirmada às 16h para o Grand Hyatt Barra. Pix de deslocamento aprovado pelo pipeline. Stephanie está a caminho.',
   'Aguardar chegada de Stephanie ao destino e início do atendimento.',
   'evo_card_0014_escalada_004',
   NOW() - interval '1 hour', NULL),

  -- S#20 Leandro — pix_em_revisao, Fernando
  ('e5ca0000-0014-7000-8000-000000000005',
   'a7e0d000-0014-7000-8000-000000000005',
   'Fernando',
   'Comprovante Pix ilegível — imagem borrada',
   'Cliente Leandro Ramos (Stephanie #20) enviou foto do comprovante, mas a qualidade da imagem impede extração dos dados. Não foi possível verificar valor nem titular.',
   'Solicitar reenvio do comprovante em melhor resolução, ou rejeitar e pedir que refaça o Pix.',
   'evo_card_0014_escalada_005',
   NOW() - interval '4 hours', NULL),

  -- S#21 Eduardo — handoff_ia, Fernando
  ('e5ca0000-0014-7000-8000-000000000006',
   'a7e0d000-0014-7000-8000-000000000006',
   'Fernando',
   'Perfil de risco — histórico suspeito identificado',
   'Eduardo Castro (Stephanie #21): cliente demonstrou qualificação mas apresenta padrão de linguagem e histórico relatados como problemáticos. IA escalou antes de avançar para agendamento.',
   'Avaliar perfil e decidir: prosseguir com cautela, solicitar mais informações, ou encerrar atendimento.',
   'evo_card_0014_escalada_006',
   NOW() - interval '12 hours', NULL),

  -- A#8 Paulo — modelo_em_atendimento (Alessia)
  ('e5ca0000-0014-7000-8000-000000000007',
   'a7e0d000-0014-7000-8000-000000000007',
   'modelo',
   'Foto de portaria recebida — cliente chegou ao apartamento',
   'Paulo Vieira (Alessia #8): cliente interno chegou ao apartamento de Alessia e enviou foto da portaria. Atendimento de 2h iniciado às 12:30h.',
   'Alessia em atendimento ativo. Aguardar encerramento e envio do comando "finalizado [valor]".',
   'evo_card_0014_escalada_007',
   NOW() - interval '2 hours', NULL),

  -- A#9 Cláudio — handoff_ia, Fernando (Alessia)
  ('e5ca0000-0014-7000-8000-000000000008',
   'a7e0d000-0014-7000-8000-000000000008',
   'Fernando',
   'Proposta abaixo do valor mínimo de Alessia',
   'Cláudio Ferraz (Alessia #9): em triagem para atendimento interno. Aceita o programa mas insiste em R$ 900 para 2h. Valor mínimo de Alessia é R$ 1.200.',
   'Autorizar desconto especial (até R$ 1.000?) ou manter piso e informar que não é possível negociar.',
   'evo_card_0014_escalada_008',
   NOW() - interval '3 hours', NULL),

  -- A#10 Fábio — handoff_ia, Fernando (Alessia)
  ('e5ca0000-0014-7000-8000-000000000009',
   'a7e0d000-0014-7000-8000-000000000009',
   'Fernando',
   'Solicitação de serviços fora do escopo padrão',
   'Fábio Correia (Alessia #10): agendou para amanhã às 19h mas perguntou especificamente sobre serviços não descritos no FAQ da Alessia. IA pausou aguardando autorização do escopo.',
   'Confirmar quais serviços podem ser oferecidos neste atendimento específico.',
   'evo_card_0014_escalada_009',
   NOW() - interval '8 hours', NULL),

  -- A#11 Gustavo — modelo_em_atendimento (Alessia)
  ('e5ca0000-0014-7000-8000-000000000010',
   'a7e0d000-0014-7000-8000-000000000010',
   'modelo',
   'Cliente chegou ao apartamento — atendimento em execução',
   'Gustavo Menezes (Alessia #11): atendimento de 1h iniciado às 11h. Foto de portaria recebida. Alessia em atendimento.',
   'Aguardar Alessia encerrar e registrar resultado com "finalizado [valor]".',
   'evo_card_0014_escalada_010',
   NOW() - interval '1 hour 30 minutes', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================
-- SEÇÃO B — Histórico 3 dias atrás (2026-05-03)
-- 3 Fechados + 2 Perdidos para comparação de tendência
-- ============================================================

-- ------------------------------------------------------------
-- B.1  Clientes históricos (5)
-- ------------------------------------------------------------
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id) VALUES
  ('c11e0000-0014-7000-8000-000000000011', '+5521944440001', 'Erick Moraes',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000012', '+5521944440002', 'Alessandro Carvalho',
   '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0014-7000-8000-000000000013', '+5521944440003', 'Danilo Freitas',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000014', '+5521944440004', 'Murilo Pinto',
   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0014-7000-8000-000000000015', '+5521944440005', 'Cristiano Leal',
   '0e7e1000-0001-7000-8000-000000000002')
ON CONFLICT (telefone) DO NOTHING;


-- ------------------------------------------------------------
-- B.2  Conversas históricas
-- ------------------------------------------------------------
INSERT INTO barravips.conversas
  (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas)
VALUES
  ('c01f0000-0014-7000-8000-000000000011',
   'c11e0000-0014-7000-8000-000000000011', '0e7e1000-0001-7000-8000-000000000001',
   '5521944440001@s.whatsapp.net', false, 'Cliente recorrente. Voltou para novo atendimento na mesma semana.'),
  ('c01f0000-0014-7000-8000-000000000012',
   'c11e0000-0014-7000-8000-000000000012', '0e7e1000-0001-7000-8000-000000000002',
   '5521944440002@s.whatsapp.net', false, NULL),
  ('c01f0000-0014-7000-8000-000000000013',
   'c11e0000-0014-7000-8000-000000000013', '0e7e1000-0001-7000-8000-000000000001',
   '5521944440003@s.whatsapp.net', false, NULL),
  ('c01f0000-0014-7000-8000-000000000014',
   'c11e0000-0014-7000-8000-000000000014', '0e7e1000-0001-7000-8000-000000000001',
   '5521944440004@s.whatsapp.net', false, 'Sumiu sem aparecer no endereço combinado.'),
  ('c01f0000-0014-7000-8000-000000000015',
   'c11e0000-0014-7000-8000-000000000015', '0e7e1000-0001-7000-8000-000000000002',
   '5521944440005@s.whatsapp.net', false, 'Endereço fora da área de cobertura de Alessia.')
ON CONFLICT (cliente_id, modelo_id) DO NOTHING;


-- ------------------------------------------------------------
-- B.3  Atendimentos históricos (3 dias atrás = 2026-05-03 BRT)
--
-- Stephanie: #22 Fechado R$ 2.200 (externo) | #23 Fechado R$ 1.000 (interno) | #24 Perdido sumiu
-- Alessia:   #12 Fechado R$ 1.500 (interno) | #13 Perdido fora_de_area
--
-- Totais histórico 3 dias:
--   Fechamentos: 3  |  Valor Bruto: R$ 4.700
--   Lucro:  S#22 R$ 2.200×40% = R$ 880 | S#23 R$ 1.000×40% = R$ 400 | A#12 R$ 1.500×30% = R$ 450
--           Total lucro: R$ 1.730
-- ------------------------------------------------------------
INSERT INTO barravips.atendimentos
  (id, numero_curto, cliente_id, modelo_id, conversa_id,
   estado, tipo_atendimento, urgencia,
   forma_pagamento, valor_acordado, valor_final, percentual_repasse_snapshot,
   motivo_perda,
   pix_status, ia_pausada, ia_pausada_motivo,
   responsavel_atual, fonte_decisao_ultima_transicao,
   created_at, updated_at)
VALUES
  -- S#22 Erick Moraes — Fechado, externo, R$ 2.200, repasse 40%
  ('a7e0d000-0014-7000-8000-000000000011', 22,
   'c11e0000-0014-7000-8000-000000000011', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000011',
   'Fechado', 'externo', 'agendado',
   'pix', 2200.00, 2200.00, 40.00,
   NULL, 'validado', false, NULL,
   'Fernando', 'comando_grupo',
   '2026-05-03 10:00:00-03', '2026-05-03 17:00:00-03'),

  -- A#12 Alessandro — Fechado, interno, R$ 1.500, repasse 30%
  ('a7e0d000-0014-7000-8000-000000000012', 12,
   'c11e0000-0014-7000-8000-000000000012', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000012',
   'Fechado', 'interno', 'agendado',
   'dinheiro', 1500.00, 1500.00, 30.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   '2026-05-03 12:00:00-03', '2026-05-03 19:00:00-03'),

  -- S#23 Danilo Freitas — Fechado, interno, R$ 1.000, repasse 40%
  ('a7e0d000-0014-7000-8000-000000000013', 23,
   'c11e0000-0014-7000-8000-000000000013', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000013',
   'Fechado', 'interno', 'imediato',
   'dinheiro', 1000.00, 1000.00, 40.00,
   NULL, 'nao_solicitado', false, NULL,
   'Fernando', 'comando_grupo',
   '2026-05-03 08:00:00-03', '2026-05-03 14:00:00-03'),

  -- S#24 Murilo Pinto — Perdido, externo, sumiu
  ('a7e0d000-0014-7000-8000-000000000014', 24,
   'c11e0000-0014-7000-8000-000000000014', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000014',
   'Perdido', 'externo', 'indefinido',
   NULL, 1200.00, NULL, NULL,
   'sumiu', 'nao_solicitado', false, NULL,
   'IA', 'auto_timeout_interno',
   '2026-05-03 15:00:00-03', '2026-05-03 20:00:00-03'),

  -- A#13 Cristiano Leal — Perdido, interno, fora_de_area
  ('a7e0d000-0014-7000-8000-000000000015', 13,
   'c11e0000-0014-7000-8000-000000000015', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000015',
   'Perdido', 'interno', 'imediato',
   NULL, 1200.00, NULL, NULL,
   'fora_de_area', 'nao_solicitado', false, NULL,
   'IA', 'extracao_ia',
   '2026-05-03 11:00:00-03', '2026-05-03 13:00:00-03')

ON CONFLICT (id) DO NOTHING;


-- ------------------------------------------------------------
-- B.4  Eventos históricos (fechado_registrado / perdido_registrado)
-- ------------------------------------------------------------
INSERT INTO barravips.eventos
  (id, atendimento_id, tipo, origem, autor, payload, created_at)
VALUES
  ('e1e10000-0014-7000-8000-000000000001',
   'a7e0d000-0014-7000-8000-000000000011',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 2200.00, "comando": "finalizado 2200"}'::jsonb,
   '2026-05-03 17:00:00-03'),

  ('e1e10000-0014-7000-8000-000000000002',
   'a7e0d000-0014-7000-8000-000000000012',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1500.00, "comando": "finalizado 1500"}'::jsonb,
   '2026-05-03 19:00:00-03'),

  ('e1e10000-0014-7000-8000-000000000003',
   'a7e0d000-0014-7000-8000-000000000013',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 1000.00, "comando": "finalizado 1000"}'::jsonb,
   '2026-05-03 14:00:00-03'),

  ('e1e10000-0014-7000-8000-000000000004',
   'a7e0d000-0014-7000-8000-000000000014',
   'perdido_registrado', 'cron', 'sistema',
   '{"motivo": "sumiu", "fonte_decisao": "auto_timeout_interno"}'::jsonb,
   '2026-05-03 20:00:00-03'),

  ('e1e10000-0014-7000-8000-000000000005',
   'a7e0d000-0014-7000-8000-000000000015',
   'perdido_registrado', 'painel', 'Fernando',
   '{"motivo": "fora_de_area", "obs": "Endereço em Santa Cruz, fora da área de Alessia"}'::jsonb,
   '2026-05-03 13:00:00-03')

ON CONFLICT (id) DO NOTHING;


-- ============================================================
-- SEÇÃO C — Atendimentos futuros + Agenda dos próximos 7 dias
-- ============================================================

-- ------------------------------------------------------------
-- C.1  Clientes para atendimentos futuros
--      (Erick e Alessandro já existem — os históricos são Fechados,
--       portanto o par pode ter novo atendimento aberto)
-- ------------------------------------------------------------
-- Nenhum cliente novo necessário aqui.

-- ------------------------------------------------------------
-- C.2  Atendimentos futuros (Confirmados, ia_pausada=false)
-- ------------------------------------------------------------
INSERT INTO barravips.atendimentos
  (id, numero_curto, cliente_id, modelo_id, conversa_id,
   estado, tipo_atendimento, urgencia,
   data_desejada, horario_desejado, duracao_horas,
   endereco, bairro, tipo_local, referencia_local,
   forma_pagamento, valor_acordado,
   pix_status, ia_pausada, ia_pausada_motivo,
   responsavel_atual, fonte_decisao_ultima_transicao,
   created_at, updated_at)
VALUES
  -- S#25 Erick Moraes — Confirmado externo, 2026-05-07 14:00 BRT
  ('a7e0d000-0014-7000-8000-000000000016', 25,
   'c11e0000-0014-7000-8000-000000000011', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0014-7000-8000-000000000011',
   'Confirmado', 'externo', 'agendado',
   '2026-05-07', '14:00', 2.0,
   'Av. Vieira Souto, 168, Ipanema', 'Ipanema', 'hotel',
   'Hotel Fasano Rio — recepção, solicitar quarto de Erick Moraes',
   'pix', 2000.00,
   'validado', false, NULL,
   'IA', 'pipeline_pix',
   NOW() - interval '1 hour', NOW() - interval '30 minutes'),

  -- A#14 Alessandro Carvalho — Confirmado interno, 2026-05-08 19:00 BRT
  ('a7e0d000-0014-7000-8000-000000000017', 14,
   'c11e0000-0014-7000-8000-000000000012', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0014-7000-8000-000000000012',
   'Confirmado', 'interno', 'agendado',
   '2026-05-08', '19:00', 2.0,
   NULL, NULL, NULL, NULL,
   'dinheiro', 1500.00,
   'nao_solicitado', false, NULL,
   'IA', 'extracao_ia',
   NOW() - interval '2 hours', NOW() - interval '1 hour')

ON CONFLICT (id) DO NOTHING;


-- ------------------------------------------------------------
-- C.3  Bloqueios agenda — 2026-05-07 a 2026-05-13
--
-- Stephanie ATIVOS existentes amanhã: B8 18:00-19:00 BRT (salão)
-- Todos os novos slots respeitam os existentes.
-- ------------------------------------------------------------
INSERT INTO barravips.bloqueios
  (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao,
   created_at, updated_at)
VALUES

  -- 2026-05-07 14:00-16:00 BRT — Stephanie, S#25 Erick Confirmado
  ('b10c0000-0014-7000-8000-000000000010',
   '0e7e1000-0001-7000-8000-000000000001',
   'a7e0d000-0014-7000-8000-000000000016',
   '2026-05-07 17:00:00+00', '2026-05-07 19:00:00+00',
   'bloqueado', 'ia',
   'Saída confirmada Erick — Fasano Ipanema. 07/05 14h.',
   NOW() - interval '1 hour', NOW() - interval '30 minutes'),

  -- 2026-05-07 20:00-22:00 BRT — Alessia, manual
  ('b10c0000-0014-7000-8000-000000000011',
   '0e7e1000-0001-7000-8000-000000000002',
   NULL,
   '2026-05-07 23:00:00+00', '2026-05-08 01:00:00+00',
   'bloqueado', 'manual',
   'Alessia — compromisso pessoal noturno 07/05.',
   NOW() - interval '6 hours', NOW() - interval '6 hours'),

  -- 2026-05-08 10:00-12:00 BRT — Stephanie, manual
  ('b10c0000-0014-7000-8000-000000000012',
   '0e7e1000-0001-7000-8000-000000000001',
   NULL,
   '2026-05-08 13:00:00+00', '2026-05-08 15:00:00+00',
   'bloqueado', 'manual',
   'Stephanie — reserva stand-by manhã 08/05.',
   NOW() - interval '4 hours', NOW() - interval '4 hours'),

  -- 2026-05-08 19:00-21:00 BRT — Alessia, A#14 Alessandro Confirmado
  ('b10c0000-0014-7000-8000-000000000013',
   '0e7e1000-0001-7000-8000-000000000002',
   'a7e0d000-0014-7000-8000-000000000017',
   '2026-05-08 22:00:00+00', '2026-05-09 00:00:00+00',
   'bloqueado', 'ia',
   'Atendimento interno Alessandro — Leblon 08/05 19h.',
   NOW() - interval '2 hours', NOW() - interval '1 hour'),

  -- 2026-05-09 21:00-23:00 BRT — Stephanie, manual (pré-reserva noturna)
  ('b10c0000-0014-7000-8000-000000000014',
   '0e7e1000-0001-7000-8000-000000000001',
   NULL,
   '2026-05-10 00:00:00+00', '2026-05-10 02:00:00+00',
   'bloqueado', 'painel_fernando',
   'Stephanie — pré-reserva noturna 09/05. Aguardando confirmação do cliente.',
   NOW() - interval '3 hours', NOW() - interval '3 hours'),

  -- 2026-05-10 15:00-18:00 BRT — Stephanie, manual (reserva longa)
  ('b10c0000-0014-7000-8000-000000000015',
   '0e7e1000-0001-7000-8000-000000000001',
   NULL,
   '2026-05-10 18:00:00+00', '2026-05-10 21:00:00+00',
   'bloqueado', 'painel_fernando',
   'Stephanie — reserva 3h confirmada por Fernando, cliente offline.',
   NOW() - interval '5 hours', NOW() - interval '5 hours'),

  -- 2026-05-10 18:00-20:00 BRT — Alessia, manual
  ('b10c0000-0014-7000-8000-000000000016',
   '0e7e1000-0001-7000-8000-000000000002',
   NULL,
   '2026-05-10 21:00:00+00', '2026-05-10 23:00:00+00',
   'bloqueado', 'manual',
   'Alessia — compromisso externo 10/05 tarde.',
   NOW() - interval '7 hours', NOW() - interval '7 hours'),

  -- 2026-05-11 19:00-21:00 BRT — Stephanie, manual
  ('b10c0000-0014-7000-8000-000000000017',
   '0e7e1000-0001-7000-8000-000000000001',
   NULL,
   '2026-05-11 22:00:00+00', '2026-05-12 00:00:00+00',
   'bloqueado', 'manual',
   'Stephanie — reservado para atendimento preferencial recorrente.',
   NOW() - interval '8 hours', NOW() - interval '8 hours'),

  -- 2026-05-12 14:00-16:00 BRT — Alessia, manual
  ('b10c0000-0014-7000-8000-000000000018',
   '0e7e1000-0001-7000-8000-000000000002',
   NULL,
   '2026-05-12 17:00:00+00', '2026-05-12 19:00:00+00',
   'bloqueado', 'manual',
   'Alessia — reserva antecipada cliente novo (aguardando Pix).',
   NOW() - interval '10 hours', NOW() - interval '10 hours'),

  -- 2026-05-13 20:00 BRT a 2026-05-14 00:00 BRT — Stephanie, pernoite
  ('b10c0000-0014-7000-8000-000000000019',
   '0e7e1000-0001-7000-8000-000000000001',
   NULL,
   '2026-05-13 23:00:00+00', '2026-05-14 03:00:00+00',
   'bloqueado', 'painel_fernando',
   'Stephanie — pernoite confirmado por Fernando. Penthouse Barra.',
   NOW() - interval '12 hours', NOW() - interval '12 hours')

ON CONFLICT (id) DO NOTHING;

-- Vincula bloqueios aos atendimentos futuros
UPDATE barravips.atendimentos SET bloqueio_id = 'b10c0000-0014-7000-8000-000000000010'
 WHERE id = 'a7e0d000-0014-7000-8000-000000000016' AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos SET bloqueio_id = 'b10c0000-0014-7000-8000-000000000013'
 WHERE id = 'a7e0d000-0014-7000-8000-000000000017' AND bloqueio_id IS NULL;


COMMIT;
