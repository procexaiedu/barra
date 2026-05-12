BEGIN;

-- ============================================================
-- BLOCO A — INFRAESTRUTURA COMPARTILHADA (idempotente)
-- ============================================================

-- === usuarios ===
INSERT INTO barravips.usuarios (id, nome, email, papel, ativo, created_at)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Fernando',
  'contato@procexai.tech',
  'fernando',
  true,
  NOW() - INTERVAL '90 days'
)
ON CONFLICT (id) DO NOTHING;

-- === duracoes ===
INSERT INTO barravips.duracoes (id, nome, ordem) VALUES
  ('d0000000-0000-0000-0000-000000000001', '1 hora',   1),
  ('d0000000-0000-0000-0000-000000000002', '2 horas',  2),
  ('d0000000-0000-0000-0000-000000000003', '3 horas',  3),
  ('d0000000-0000-0000-0000-000000000004', '4 horas',  4),
  ('d0000000-0000-0000-0000-000000000005', 'Pernoite', 5)
ON CONFLICT (id) DO NOTHING;

-- === programas ===
INSERT INTO barravips.programas (id, nome, categoria) VALUES
  ('e0000000-0000-0000-0000-000000000001', 'Massagem Relaxante',  'relaxamento'),
  ('e0000000-0000-0000-0000-000000000002', 'Acompanhante Jantar', 'social'),
  ('e0000000-0000-0000-0000-000000000003', 'Programa Completo',   'completo'),
  ('e0000000-0000-0000-0000-000000000004', 'Pernoite',            'pernoite'),
  ('e0000000-0000-0000-0000-000000000005', 'Massagem Tântrica',   'tantrica')
ON CONFLICT (id) DO NOTHING;

-- === modelos ===
INSERT INTO barravips.modelos (
  id, nome, numero_whatsapp, evolution_instance_id, status,
  valor_padrao, percentual_repasse, chave_pix, titular_chave,
  idade, idiomas, localizacao_operacional, tipo_atendimento_aceito,
  foto_perfil_object_key, coordenacao_chat_id, coordenacao_verificada_em
) VALUES
(
  'a1000000-0000-0000-0000-000000000001',
  'Alessia Viana', '+5521999990100', 'evo_alessia', 'ativa',
  1500.00, 40.00, '21999990100', 'Alessia Viana',
  24, ARRAY['pt-BR','en-US'],
  'Zona Sul e Barra da Tijuca, Rio de Janeiro',
  ARRAY['interno','externo']::barravips.tipo_atendimento_enum[],
  'modelos/a1000000-0000-0000-0000-000000000001/perfil/perfil.jpg',
  '120363111111111001@g.us',
  NOW() - INTERVAL '1 hour'
),
(
  'a1000000-0000-0000-0000-000000000002',
  'Bruna Martins', '+5521999990200', NULL, 'pausada',
  1200.00, 35.00, '21999990200', 'Bruna Martins',
  26, ARRAY['pt-BR'],
  'Barra da Tijuca e Recreio, Rio de Janeiro',
  ARRAY['externo']::barravips.tipo_atendimento_enum[],
  'modelos/a1000000-0000-0000-0000-000000000002/perfil/perfil.jpg',
  NULL, NULL
)
ON CONFLICT (id) DO NOTHING;

-- === modelo_faq — Alessia (5 FAQs) ===
INSERT INTO barravips.modelo_faq (id, modelo_id, pergunta, resposta, tags) VALUES
(
  'fa100000-0000-0000-0000-000000000001',
  'a1000000-0000-0000-0000-000000000001',
  'Você atende em qual região?',
  'Atendo em toda Zona Sul e Barra da Tijuca. Para outras regiões consulte disponibilidade e taxa de deslocamento.',
  ARRAY['localização','região','bairro']
),
(
  'fa100000-0000-0000-0000-000000000002',
  'a1000000-0000-0000-0000-000000000001',
  'Qual o valor do programa?',
  'Meus valores variam por duração e programa. O básico começa em R$ 800 por hora. Me conta o que você tem em mente!',
  ARRAY['valor','preço','programa']
),
(
  'fa100000-0000-0000-0000-000000000003',
  'a1000000-0000-0000-0000-000000000001',
  'Você é real? As fotos são suas?',
  'Claro que sim! 😊 Minhas fotos são recentes e autênticas. Posso fazer uma chamada de vídeo rápida para você se certificar.',
  ARRAY['verificação','autenticidade','fotos']
),
(
  'fa100000-0000-0000-0000-000000000004',
  'a1000000-0000-0000-0000-000000000001',
  'Aceita Pix?',
  'Sim! Para atendimentos externos, cobro um Pix de deslocamento antecipado. Presencialmente aceito dinheiro ou Pix.',
  ARRAY['pagamento','pix','dinheiro']
),
(
  'fa100000-0000-0000-0000-000000000005',
  'a1000000-0000-0000-0000-000000000001',
  'Qual a duração mínima?',
  'A duração mínima é 1 hora. Para programas completos ou pernoite, temos opções especiais — basta perguntar!',
  ARRAY['duração','tempo','programa']
)
ON CONFLICT (id) DO NOTHING;

-- === modelo_faq — Bruna (2 FAQs) ===
INSERT INTO barravips.modelo_faq (id, modelo_id, pergunta, resposta, tags) VALUES
(
  'fa200000-0000-0000-0000-000000000001',
  'a1000000-0000-0000-0000-000000000002',
  'Você faz externo?',
  'Faço sim, em hotéis e flats na Barra e Recreio. Cobro Pix de deslocamento antecipado.',
  ARRAY['externo','hotel','deslocamento']
),
(
  'fa200000-0000-0000-0000-000000000002',
  'a1000000-0000-0000-0000-000000000002',
  'Qual o valor?',
  'A partir de R$ 1.200 por hora. Depende do programa e duração. Me fala o que você quer!',
  ARRAY['valor','preço']
)
ON CONFLICT (id) DO NOTHING;

-- === modelo_midia — Alessia (10 mídias) ===
INSERT INTO barravips.modelo_midia (id, modelo_id, tipo, tag, bucket, object_key, aprovada) VALUES
  ('0d100000-0000-0000-0000-000000000001','a1000000-0000-0000-0000-000000000001','foto','apresentacao','barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/apresentacao-01.jpg',true),
  ('0d100000-0000-0000-0000-000000000002','a1000000-0000-0000-0000-000000000001','foto','apresentacao','barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/apresentacao-02.jpg',true),
  ('0d100000-0000-0000-0000-000000000003','a1000000-0000-0000-0000-000000000001','foto','apresentacao','barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/apresentacao-03.jpg',true),
  ('0d100000-0000-0000-0000-000000000004','a1000000-0000-0000-0000-000000000001','foto','corpo',       'barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/corpo-01.jpg',        true),
  ('0d100000-0000-0000-0000-000000000005','a1000000-0000-0000-0000-000000000001','foto','corpo',       'barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/corpo-02.jpg',        true),
  ('0d100000-0000-0000-0000-000000000006','a1000000-0000-0000-0000-000000000001','foto','corpo',       'barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/corpo-03.jpg',        true),
  ('0d100000-0000-0000-0000-000000000007','a1000000-0000-0000-0000-000000000001','foto','lifestyle',   'barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/lifestyle-01.jpg',    true),
  ('0d100000-0000-0000-0000-000000000008','a1000000-0000-0000-0000-000000000001','foto','lifestyle',   'barra-media','modelos/a1000000-0000-0000-0000-000000000001/foto/lifestyle-02.jpg',    true),
  ('0d100000-0000-0000-0000-000000000009','a1000000-0000-0000-0000-000000000001','video','evento',     'barra-media','modelos/a1000000-0000-0000-0000-000000000001/video/evento-01.mp4',      true),
  ('0d100000-0000-0000-0000-000000000010','a1000000-0000-0000-0000-000000000001','video','evento',     'barra-media','modelos/a1000000-0000-0000-0000-000000000001/video/evento-02.mp4',      true)
ON CONFLICT (id) DO NOTHING;

-- === modelo_midia — Bruna (5 fotos) ===
INSERT INTO barravips.modelo_midia (id, modelo_id, tipo, tag, bucket, object_key, aprovada) VALUES
  ('0d200000-0000-0000-0000-000000000001','a1000000-0000-0000-0000-000000000002','foto','apresentacao','barra-media','modelos/a1000000-0000-0000-0000-000000000002/foto/apresentacao-01.jpg',true),
  ('0d200000-0000-0000-0000-000000000002','a1000000-0000-0000-0000-000000000002','foto','apresentacao','barra-media','modelos/a1000000-0000-0000-0000-000000000002/foto/apresentacao-02.jpg',true),
  ('0d200000-0000-0000-0000-000000000003','a1000000-0000-0000-0000-000000000002','foto','corpo',       'barra-media','modelos/a1000000-0000-0000-0000-000000000002/foto/corpo-01.jpg',        true),
  ('0d200000-0000-0000-0000-000000000004','a1000000-0000-0000-0000-000000000002','foto','corpo',       'barra-media','modelos/a1000000-0000-0000-0000-000000000002/foto/corpo-02.jpg',        true),
  ('0d200000-0000-0000-0000-000000000005','a1000000-0000-0000-0000-000000000002','foto','lifestyle',   'barra-media','modelos/a1000000-0000-0000-0000-000000000002/foto/lifestyle-01.jpg',    true)
ON CONFLICT (id) DO NOTHING;

-- === modelo_servicos — Alessia (5 serviços) ===
INSERT INTO barravips.modelo_servicos (modelo_id, nome, duracao_horas, preco, ativo, ordem) VALUES
  ('a1000000-0000-0000-0000-000000000001', 'Programa 1h',  1.0,  1500.00, true, 1),
  ('a1000000-0000-0000-0000-000000000001', 'Programa 2h',  2.0,  2800.00, true, 2),
  ('a1000000-0000-0000-0000-000000000001', 'Programa 3h',  3.0,  3800.00, true, 3),
  ('a1000000-0000-0000-0000-000000000001', 'Massagem 1h',  1.0,   800.00, true, 4),
  ('a1000000-0000-0000-0000-000000000001', 'Pernoite',    12.0,  6000.00, true, 5)
ON CONFLICT ON CONSTRAINT modelo_servicos_nome_duracao_unique DO NOTHING;

-- === modelo_servicos — Bruna (2 serviços) ===
INSERT INTO barravips.modelo_servicos (modelo_id, nome, duracao_horas, preco, ativo, ordem) VALUES
  ('a1000000-0000-0000-0000-000000000002', 'Programa 1h', 1.0, 1200.00, true, 1),
  ('a1000000-0000-0000-0000-000000000002', 'Programa 2h', 2.0, 2200.00, true, 2)
ON CONFLICT ON CONSTRAINT modelo_servicos_nome_duracao_unique DO NOTHING;

-- === modelo_programas — Alessia (7 combinações) ===
INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco) VALUES
  ('a1000000-0000-0000-0000-000000000001','e0000000-0000-0000-0000-000000000001','d0000000-0000-0000-0000-000000000001',  800.00),
  ('a1000000-0000-0000-0000-000000000001','e0000000-0000-0000-0000-000000000001','d0000000-0000-0000-0000-000000000002', 1500.00),
  ('a1000000-0000-0000-0000-000000000001','e0000000-0000-0000-0000-000000000003','d0000000-0000-0000-0000-000000000002', 2500.00),
  ('a1000000-0000-0000-0000-000000000001','e0000000-0000-0000-0000-000000000003','d0000000-0000-0000-0000-000000000003', 3500.00),
  ('a1000000-0000-0000-0000-000000000001','e0000000-0000-0000-0000-000000000004','d0000000-0000-0000-0000-000000000005', 5500.00),
  ('a1000000-0000-0000-0000-000000000001','e0000000-0000-0000-0000-000000000005','d0000000-0000-0000-0000-000000000001', 1800.00),
  ('a1000000-0000-0000-0000-000000000001','e0000000-0000-0000-0000-000000000005','d0000000-0000-0000-0000-000000000002', 3000.00)
ON CONFLICT (modelo_id, programa_id, duracao_id) DO NOTHING;

-- === modelo_programas — Bruna (2 combinações) ===
INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco) VALUES
  ('a1000000-0000-0000-0000-000000000002','e0000000-0000-0000-0000-000000000003','d0000000-0000-0000-0000-000000000001', 1200.00),
  ('a1000000-0000-0000-0000-000000000002','e0000000-0000-0000-0000-000000000003','d0000000-0000-0000-0000-000000000002', 2200.00)
ON CONFLICT (modelo_id, programa_id, duracao_id) DO NOTHING;

-- ============================================================
-- BLOCO B — CLIENTE: EDUARDO LUZ
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000002',
  '+5521999990002',
  'Eduardo Luz',
  'a1000000-0000-0000-0000-000000000001'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000002',
  'c1000000-0000-0000-0000-000000000002',
  'a1000000-0000-0000-0000-000000000001',
  '5521999990002@s.whatsapp.net',
  false,
  'Cliente novo. Fez perguntas sobre autenticidade. IA escalou por comportamento ambíguo.',
  NULL,
  NOW() - INTERVAL '30 minutes',
  'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios (atendimento_id=NULL; UPDATE cruzado abaixo) ===
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem) VALUES
(
  'b1000000-0000-0000-0000-000000000001',
  'a1000000-0000-0000-0000-000000000001', NULL,
  (NOW()::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  (NOW()::date + TIME '22:00') AT TIME ZONE 'America/Sao_Paulo',
  'bloqueado', 'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos (bloqueio_id=NULL; UPDATE cruzado abaixo) ===

-- ATD_EDUA_1: Qualificado hoje, externo, handoff_ia (Fernando decide)
INSERT INTO barravips.atendimentos (
  id, numero_curto, cliente_id, modelo_id, conversa_id, bloqueio_id,
  estado, tipo_atendimento, urgencia,
  data_desejada, horario_desejado, duracao_horas,
  endereco, bairro, tipo_local, referencia_local,
  forma_pagamento, valor_acordado, valor_final, percentual_repasse_snapshot,
  motivo_perda, motivo_perda_obs, pix_status,
  aviso_saida_em, foto_portaria_em,
  ia_pausada, ia_pausada_motivo, responsavel_atual,
  proxima_acao_esperada, motivo_escalada, resumo_operacional,
  sinais_qualificacao, fonte_decisao_ultima_transicao,
  created_at, updated_at
) VALUES (
  '91000000-0000-0000-0000-000000000005', 5,
  'c1000000-0000-0000-0000-000000000002',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000002',
  NULL,
  'Qualificado', 'externo', 'agendado',
  NOW()::date, '20:00', 2.0,
  NULL, 'Barra da Tijuca', 'hotel', 'Hotel Windsor Barra',
  'pix', 2500.00, NULL, 40.00,
  NULL, NULL, 'nao_solicitado',
  NULL, NULL,
  true, 'handoff_ia', 'Fernando',
  'Fernando avaliar o cliente e decidir se prossegue, recusa ou orienta a IA.',
  'Cliente solicitou foto ao vivo com data de hoje para verificar autenticidade. Comportamento incomum antes de confirmar.',
  'Eduardo Luz, novo, externo. Hotel Windsor Barra, hoje 20h, 2h, R$ 2.500. Qualificação completa. Cliente pediu verificação de identidade.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
  'extracao_ia',
  NOW() - INTERVAL '2 hours',
  NOW() - INTERVAL '30 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado bloqueios ↔ atendimentos ===
UPDATE barravips.bloqueios
  SET atendimento_id = '91000000-0000-0000-0000-000000000005'
  WHERE id = 'b1000000-0000-0000-0000-000000000001'
    AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
  SET bloqueio_id = 'b1000000-0000-0000-0000-000000000001'
  WHERE id = '91000000-0000-0000-0000-000000000005'
    AND bloqueio_id IS NULL;

-- === mensagens ===
-- CNV_EDUA_ALE — MSG-019 a MSG-026 (ATD_EDUA_1)
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  -- MSG-019: Eduardo abre conversa
  '0a200000-0000-0000-0000-000000000019',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'cliente', 'texto',
  'Boa tarde. Quero marcar para hoje à noite em hotel.',
  NULL, '3EB0EDUA00000001',
  NOW() - INTERVAL '2 hours'
),
(
  -- MSG-020: IA pede detalhes
  '0a200000-0000-0000-0000-000000000020',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'ia', 'texto',
  'Boa tarde! Adoro 😊 Qual horário e qual hotel? Me conta os detalhes.',
  NULL, '3EB0EDUA00000002',
  NOW() - INTERVAL '1 hour 58 minutes'
),
(
  -- MSG-021: Eduardo informa hotel e horário
  '0a200000-0000-0000-0000-000000000021',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'cliente', 'texto',
  'Hotel Windsor na Barra, 20h, umas 2 horas.',
  NULL, '3EB0EDUA00000003',
  NOW() - INTERVAL '1 hour 50 minutes'
),
(
  -- MSG-022: IA apresenta valor e solicita Pix
  '0a200000-0000-0000-0000-000000000022',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'ia', 'texto',
  'Perfeito! Para 2h em hotel na Barra, R$ 2.500 incluindo deslocamento. Para confirmar, preciso de um Pix de R$ 200. Combinado?',
  NULL, '3EB0EDUA00000004',
  NOW() - INTERVAL '1 hour 48 minutes'
),
(
  -- MSG-023: Eduardo levanta dúvida sobre autenticidade
  '0a200000-0000-0000-0000-000000000023',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'cliente', 'texto',
  'Antes de confirmar, quero saber se você é real de verdade. Já fui enganado antes.',
  NULL, '3EB0EDUA00000005',
  NOW() - INTERVAL '1 hour 40 minutes'
),
(
  -- MSG-024: IA oferece videochamada
  '0a200000-0000-0000-0000-000000000024',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'ia', 'texto',
  'Entendo sua preocupação! Minhas fotos são todas autênticas 😊 Posso fazer uma videochamada rápida antes de confirmarmos — fica mais fácil!',
  NULL, '3EB0EDUA00000006',
  NOW() - INTERVAL '1 hour 38 minutes'
),
(
  -- MSG-025: Eduardo exige foto ao vivo com data escrita
  '0a200000-0000-0000-0000-000000000025',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'cliente', 'texto',
  'Não quero chamada. Preciso de uma foto ao vivo com seu rosto e a data de hoje escrita num papel.',
  NULL, '3EB0EDUA00000007',
  NOW() - INTERVAL '35 minutes'
),
(
  -- MSG-026: IA aceita e pede um instante — dispara handoff_ia para Fernando
  '0a200000-0000-0000-0000-000000000026',
  'f1000000-0000-0000-0000-000000000002', '91000000-0000-0000-0000-000000000005',
  'ia', 'texto',
  'Claro! Me dá um instante que preparo aqui 😊',
  NULL, '3EB0EDUA00000008',
  NOW() - INTERVAL '30 minutes'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- === comprovantes_pix ===
-- Nenhum para Eduardo: Pix ainda não foi solicitado (ia_pausada=handoff_ia antes de chegar nessa etapa)

-- === escaladas ===

-- ESC_EDUA_1: aberta — handoff_ia, verificação de identidade (ATD_EDUA_1)
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-000000000005',
  'Fernando',
  'Cliente solicitou foto ao vivo com data. Comportamento incomum antes de confirmar.',
  'Eduardo Luz, novo, externo. Hotel Windsor Barra, hoje 20h, 2h, R$ 2.500. Qualificação completa. Cliente pediu verificação de identidade antes de confirmar.',
  'Avaliar o perfil e decidir: prosseguir (devolver para IA), recusar ou orientar IA. Se prosseguir, IA solicitará o Pix.',
  '3EB0CARD00000004',
  NOW() - INTERVAL '30 minutes',
  NULL, NULL, NULL
)
ON CONFLICT (id) DO NOTHING;

-- === eventos ===

-- E37-E40: ATD_EDUA_1 (Qualificado + handoff_ia)
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  -- E37: Novo → Triagem
  '0e200000-0000-0000-0000-000000000037',
  '91000000-0000-0000-0000-000000000005',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 58 minutes'
),
(
  -- E38: Triagem → Qualificado (sinais completos)
  '0e200000-0000-0000-0000-000000000038',
  '91000000-0000-0000-0000-000000000005',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 48 minutes'
),
(
  -- E39: bloqueio criado para horário solicitado (20h-22h)
  '0e200000-0000-0000-0000-000000000039',
  '91000000-0000-0000-0000-000000000005',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000001","inicio":"20:00","fim":"22:00"}',
  NOW() - INTERVAL '1 hour 47 minutes'
),
(
  -- E40: handoff_ia — cliente exige verificação incomum, IA escala para Fernando
  '0e200000-0000-0000-0000-000000000040',
  '91000000-0000-0000-0000-000000000005',
  'handoff_aberto', 'agente', 'IA',
  '{"motivo":"Cliente solicitou foto ao vivo com data. Comportamento incomum antes de confirmar.","responsavel":"Fernando","ia_pausada_motivo":"handoff_ia"}',
  NOW() - INTERVAL '30 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === envios_evolution ===

-- Card no grupo de coordenação: ESC_EDUA_1
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid, contexto, direcao, tipo,
  atendimento_id, conversa_id, payload, created_at
) VALUES
(
  'ee200000-0000-0000-0000-000000000001',
  '3EB0CARD00000004', 'evo_alessia', '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000005', NULL,
  '{"titulo":"Handoff IA — verificação de identidade","escalada_id":"81000000-0000-0000-0000-000000000004"}',
  NOW() - INTERVAL '30 minutes'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- Mensagem da IA na conversa do cliente: MSG-026 (último envio da IA antes do handoff)
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid, contexto, direcao, tipo,
  atendimento_id, conversa_id, payload, created_at
) VALUES
(
  'ee200000-0000-0000-0000-000000000002',
  '3EB0IA000000004', 'evo_alessia', '5521999990002@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000005', 'f1000000-0000-0000-0000-000000000002',
  '{"tipo_msg":"texto","len":44}',
  NOW() - INTERVAL '30 minutes'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- === atendimento_servicos ===
-- Nenhum para Eduardo: atendimento em estado Qualificado (não Fechado)

COMMIT;
