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

-- === modelos — Alessia (ativa) + Bruna (pausada) ===
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
-- BLOCO B — CLIENTE: CAIO REIS
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000013',
  '+5521999990013',
  'Caio Reis',
  'a1000000-0000-0000-0000-000000000001'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000013',
  'c1000000-0000-0000-0000-000000000013',
  'a1000000-0000-0000-0000-000000000001',
  '5521999990013@s.whatsapp.net',
  false,
  NULL,
  NULL,
  NOW() - INTERVAL '15 minutes',
  'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios ===
-- BLQ_ALE_11: AMANHÃ 20h-22h, bloqueado (Caio Aguardando_confirmacao com Pix aguardando)
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao) VALUES
(
  'b1000000-0000-0000-0000-000000000014',
  'a1000000-0000-0000-0000-000000000001', NULL,
  ((NOW() + INTERVAL '1 day')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() + INTERVAL '1 day')::date + TIME '22:00') AT TIME ZONE 'America/Sao_Paulo',
  'bloqueado', 'ia', NULL
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos ===
-- ATD_CAIO_1: Aguardando_confirmacao para AMANHÃ 20h, externo Hotel Tijuca, 2h, R$ 2.500, Pix aguardando
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
  '91000000-0000-0000-0000-000000000015', 12,
  'c1000000-0000-0000-0000-000000000013',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000013',
  NULL,
  'Aguardando_confirmacao', 'externo', 'agendado',
  (NOW() + INTERVAL '1 day')::date, '20:00', 2.0,
  NULL, 'Tijuca', 'hotel', 'Hotel Tijuca Palace',
  'pix', 2500.00, NULL, 40.00,
  NULL, NULL, 'aguardando',
  NULL, NULL,
  false, NULL, 'IA',
  'Cliente enviar comprovante Pix de R$ 200 para confirmar.',
  NULL,
  'Caio Reis, novo, externo, Hotel Tijuca Palace, amanhã 20h, 2h, R$ 2.500. Aguardando comprovante Pix.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
  'extracao_ia',
  NOW() - INTERVAL '2 hours',
  NOW() - INTERVAL '15 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado ===
UPDATE barravips.bloqueios
  SET atendimento_id = '91000000-0000-0000-0000-000000000015'
  WHERE id = 'b1000000-0000-0000-0000-000000000014'
    AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
  SET bloqueio_id = 'b1000000-0000-0000-0000-000000000014'
  WHERE id = '91000000-0000-0000-0000-000000000015'
    AND bloqueio_id IS NULL;

-- === mensagens ===
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  '0ad00000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'cliente', 'texto',
  'Oi Alessia, tudo bem? Queria marcar para amanhã à noite num hotel na Tijuca.',
  NULL, '3EB0CAIO00000001',
  NOW() - INTERVAL '2 hours'
),
(
  '0ad00000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'ia', 'texto',
  'Oi! Tudo ótimo 😊 Qual hotel e qual horário?',
  NULL, '3EB0CAIO00000002',
  NOW() - INTERVAL '1 hour 58 minutes'
),
(
  '0ad00000-0000-0000-0000-000000000003',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'cliente', 'texto',
  'Hotel Tijuca Palace, amanhã às 20h, 2 horas.',
  NULL, '3EB0CAIO00000003',
  NOW() - INTERVAL '1 hour 50 minutes'
),
(
  '0ad00000-0000-0000-0000-000000000004',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'ia', 'texto',
  'Para 2h na Tijuca, R$ 2.500 incluindo deslocamento. Para confirmar, Pix de R$ 200 para 21999990100 (Alessia Viana). Combinado?',
  NULL, '3EB0CAIO00000004',
  NOW() - INTERVAL '1 hour 45 minutes'
),
(
  '0ad00000-0000-0000-0000-000000000005',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'cliente', 'texto',
  'Combinado. Mando o Pix daqui a pouco quando chegar em casa.',
  NULL, '3EB0CAIO00000005',
  NOW() - INTERVAL '1 hour 30 minutes'
),
(
  '0ad00000-0000-0000-0000-000000000006',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'ia', 'texto',
  'Combinado! Te aguardo o comprovante para fechar tudo 🌸',
  NULL, '3EB0CAIO00000006',
  NOW() - INTERVAL '1 hour 28 minutes'
),
(
  '0ad00000-0000-0000-0000-000000000007',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'cliente', 'texto',
  'Demorou um pouco mais que pensei. Mando hoje à noite, beleza?',
  NULL, '3EB0CAIO00000007',
  NOW() - INTERVAL '20 minutes'
),
(
  '0ad00000-0000-0000-0000-000000000008',
  'f1000000-0000-0000-0000-000000000013', '91000000-0000-0000-0000-000000000015',
  'ia', 'texto',
  'Sem problema! Quanto antes você fechar, mais tranquilo fica 😊 Te espero!',
  NULL, '3EB0CAIO00000008',
  NOW() - INTERVAL '15 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === comprovantes_pix ===
-- Nenhum: cliente ainda não enviou o comprovante.

-- === escaladas ===
-- Nenhuma: IA conduz, ainda aguarda Pix.

-- === eventos ===
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  '0ed00000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-000000000015',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 58 minutes'
),
(
  '0ed00000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-000000000015',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 45 minutes'
),
(
  '0ed00000-0000-0000-0000-000000000003',
  '91000000-0000-0000-0000-000000000015',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 30 minutes'
),
(
  '0ed00000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-000000000015',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000014","inicio":"20:00","fim":"22:00"}',
  NOW() - INTERVAL '1 hour 29 minutes'
),
(
  '0ed00000-0000-0000-0000-000000000005',
  '91000000-0000-0000-0000-000000000015',
  'pix_solicitado', 'agente', 'IA',
  '{"chave":"21999990100","valor":200}',
  NOW() - INTERVAL '1 hour 28 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === envios_evolution ===
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid,
  contexto, direcao, tipo,
  atendimento_id, conversa_id,
  payload, created_at
) VALUES
(
  'ef0d0000-0000-0000-0000-000000000001',
  '3EB0CAIOIA000001',
  'evo_alessia',
  '5521999990013@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000015', 'f1000000-0000-0000-0000-000000000013',
  '{"tipo_msg":"texto","len":45}',
  NOW() - INTERVAL '1 hour 58 minutes'
),
(
  'ef0d0000-0000-0000-0000-000000000002',
  '3EB0CAIOIA000002',
  'evo_alessia',
  '5521999990013@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000015', 'f1000000-0000-0000-0000-000000000013',
  '{"tipo_msg":"texto","len":121}',
  NOW() - INTERVAL '1 hour 45 minutes'
),
(
  'ef0d0000-0000-0000-0000-000000000003',
  '3EB0CAIOIA000003',
  'evo_alessia',
  '5521999990013@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000015', 'f1000000-0000-0000-0000-000000000013',
  '{"tipo_msg":"texto","len":56}',
  NOW() - INTERVAL '1 hour 28 minutes'
),
(
  'ef0d0000-0000-0000-0000-000000000004',
  '3EB0CAIOIA000004',
  'evo_alessia',
  '5521999990013@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000015', 'f1000000-0000-0000-0000-000000000013',
  '{"tipo_msg":"texto","len":71}',
  NOW() - INTERVAL '15 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimento_servicos ===
-- Nenhum: ATD_CAIO_1 não é Fechado.

COMMIT;
