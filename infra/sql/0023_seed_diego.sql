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
-- BLOCO B — CLIENTE: DIEGO CASTRO
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000011',
  '+5521999990011',
  'Diego Castro',
  'a1000000-0000-0000-0000-000000000001'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000011',
  'c1000000-0000-0000-0000-000000000011',
  'a1000000-0000-0000-0000-000000000001',
  '5521999990011@s.whatsapp.net',
  false,
  'Hospede frequente do Caesar Park. Pediu para guardar referência.',
  NULL,
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo',
  'modelo_manual'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios ===
-- BLQ_ALE_09: -3d 19h-22h, concluido (Diego externo)
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao) VALUES
(
  'b1000000-0000-0000-0000-000000000012',
  'a1000000-0000-0000-0000-000000000001', NULL,
  ((NOW() - INTERVAL '3 days')::date + TIME '19:00') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:00') AT TIME ZONE 'America/Sao_Paulo',
  'concluido', 'ia', NULL
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos ===
-- ATD_DIEG_1: Fechado -3d, externo Ipanema, 3h, R$ 4.000
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
  '91000000-0000-0000-0000-000000000013', 10,
  'c1000000-0000-0000-0000-000000000011',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000011',
  NULL,
  'Fechado', 'externo', 'agendado',
  (NOW() - INTERVAL '3 days')::date, '19:00', 3.0,
  'Av. Vieira Souto, 460, Suíte 1102', 'Ipanema',
  'hotel', 'Caesar Park Ipanema',
  'pix', 3800.00, 4000.00, 40.00,
  NULL, NULL, 'validado',
  NULL, NULL,
  false, NULL, 'IA',
  NULL, NULL,
  'Diego Castro, novo, externo, Caesar Park Ipanema, 3h. Pix de R$ 200 validado. Encerrou com R$ 4.000.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
  'comando_grupo',
  NOW() - INTERVAL '3 days' - INTERVAL '3 hours',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado ===
UPDATE barravips.bloqueios
  SET atendimento_id = '91000000-0000-0000-0000-000000000013'
  WHERE id = 'b1000000-0000-0000-0000-000000000012'
    AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
  SET bloqueio_id = 'b1000000-0000-0000-0000-000000000012'
  WHERE id = '91000000-0000-0000-0000-000000000013'
    AND bloqueio_id IS NULL;

-- === mensagens ===
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  '0ab00000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000011', '91000000-0000-0000-0000-000000000013',
  'cliente', 'texto',
  'Boa tarde Alessia, sou Diego. Estou hospedado no Caesar Park, quero te chamar para hoje 19h, umas 3 horas.',
  NULL, '3EB0DIEG00000001',
  NOW() - INTERVAL '3 days' - INTERVAL '3 hours'
),
(
  '0ab00000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000011', '91000000-0000-0000-0000-000000000013',
  'ia', 'texto',
  'Olá Diego! Caesar Park é uma delícia 😊 Para 3h em hotel, R$ 3.800. Para confirmar, preciso do Pix de R$ 200 para 21999990100 (Alessia Viana). Topa?',
  NULL, '3EB0DIEG00000002',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 58 minutes'
),
(
  '0ab00000-0000-0000-0000-000000000003',
  'f1000000-0000-0000-0000-000000000011', '91000000-0000-0000-0000-000000000013',
  'cliente', 'audio',
  '[áudio: aceita o valor e diz que envia o Pix]',
  'mensagens/f1000000-0000-0000-0000-000000000011/3EB0DIEG00000003.ogg',
  '3EB0DIEG00000003',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 50 minutes'
),
(
  '0ab00000-0000-0000-0000-000000000004',
  'f1000000-0000-0000-0000-000000000011', '91000000-0000-0000-0000-000000000013',
  'cliente', 'imagem',
  '[comprovante de Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000011/3EB0DIEG00000004.jpg',
  '3EB0DIEG00000004',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 40 minutes'
),
(
  '0ab00000-0000-0000-0000-000000000005',
  'f1000000-0000-0000-0000-000000000011', '91000000-0000-0000-0000-000000000013',
  'ia', 'texto',
  'Pix confirmado ✅ Estarei aí às 19h. Me passa o número da suíte 🌸',
  NULL, '3EB0DIEG00000005',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 30 minutes'
),
(
  '0ab00000-0000-0000-0000-000000000006',
  'f1000000-0000-0000-0000-000000000011', '91000000-0000-0000-0000-000000000013',
  'cliente', 'texto',
  'Suíte 1102. Avisei na recepção.',
  NULL, '3EB0DIEG00000006',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours'
),
(
  '0ab00000-0000-0000-0000-000000000007',
  'f1000000-0000-0000-0000-000000000011', '91000000-0000-0000-0000-000000000013',
  'modelo_manual', 'texto',
  'finalizado 4000',
  NULL, '3EB0DIEG00000007',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === comprovantes_pix ===
INSERT INTO barravips.comprovantes_pix (
  id, atendimento_id, mensagem_id,
  valor_extraido, chave_extraida, titular_extraido, timestamp_extraido,
  decisao_pipeline, motivo_em_revisao, decisao_final, decisao_final_por,
  created_at
) VALUES (
  '71000000-0000-0000-0000-000000000006',
  '91000000-0000-0000-0000-000000000013',
  '0ab00000-0000-0000-0000-000000000004',
  200.00, '21999990100', 'Diego Castro',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 40 minutes',
  'validado', NULL, NULL, NULL,
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 38 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === escaladas ===
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000010',
  '91000000-0000-0000-0000-000000000013',
  'modelo',
  'Pix de deslocamento validado automaticamente. Alessia a caminho.',
  'Diego Castro, externo, Caesar Park Ipanema, 19h, 3h. Pix de R$ 200 validado.',
  'Encerrar com "finalizado [valor]" ao término.',
  '3EB0CARD00000010',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 30 minutes',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo',
  NULL, 'grupo_coordenacao'
)
ON CONFLICT (id) DO NOTHING;

-- === eventos ===
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  '0eb00000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-000000000013',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 58 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-000000000013',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 50 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000003',
  '91000000-0000-0000-0000-000000000013',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 48 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-000000000013',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000012","inicio":"19:00","fim":"22:00"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 47 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000005',
  '91000000-0000-0000-0000-000000000013',
  'pix_solicitado', 'agente', 'IA',
  '{"chave":"21999990100","valor":200}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 46 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000006',
  '91000000-0000-0000-0000-000000000013',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id":"71000000-0000-0000-0000-000000000006","decisao":"validado"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 30 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000007',
  '91000000-0000-0000-0000-000000000013',
  'handoff_aberto', 'pipeline_pix', 'sistema',
  '{"motivo":"Pix de deslocamento validado automaticamente","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 30 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000008',
  '91000000-0000-0000-0000-000000000013',
  'transicao_estado', 'pipeline_pix', 'sistema',
  '{"de":"Aguardando_confirmacao","para":"Confirmado","fonte_decisao":"pipeline_pix"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 30 minutes'
),
(
  '0eb00000-0000-0000-0000-000000000009',
  '91000000-0000-0000-0000-000000000013',
  'bloqueio_estado_mudado', 'cron', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000012","de":"bloqueado","para":"em_atendimento"}',
  ((NOW() - INTERVAL '3 days')::date + TIME '19:00') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0eb00000-0000-0000-0000-000000000010',
  '91000000-0000-0000-0000-000000000013',
  'transicao_estado', 'cron', 'sistema',
  '{"de":"Confirmado","para":"Em_execucao","fonte_decisao":"cron_em_execucao"}',
  ((NOW() - INTERVAL '3 days')::date + TIME '19:00') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0eb00000-0000-0000-0000-000000000011',
  '91000000-0000-0000-0000-000000000013',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"comando":"finalizado 4000","valor_final":4000}',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0eb00000-0000-0000-0000-000000000012',
  '91000000-0000-0000-0000-000000000013',
  'transicao_estado', 'grupo_coordenacao', 'modelo',
  '{"de":"Em_execucao","para":"Fechado","fonte_decisao":"comando_grupo"}',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0eb00000-0000-0000-0000-000000000013',
  '91000000-0000-0000-0000-000000000013',
  'bloqueio_estado_mudado', 'agente', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000012","de":"em_atendimento","para":"concluido"}',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo'
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
  'ef0b0000-0000-0000-0000-000000000001',
  '3EB0DIEGIA000001',
  'evo_alessia',
  '5521999990011@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000013', 'f1000000-0000-0000-0000-000000000011',
  '{"tipo_msg":"texto","len":141}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 58 minutes'
),
(
  'ef0b0000-0000-0000-0000-000000000002',
  '3EB0DIEGIA000002',
  'evo_alessia',
  '5521999990011@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000013', 'f1000000-0000-0000-0000-000000000011',
  '{"tipo_msg":"texto","len":68}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 30 minutes'
),
(
  'ef0b0000-0000-0000-0000-000000000003',
  '3EB0CARD00000010',
  'evo_alessia',
  '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000013', NULL,
  '{"titulo":"Saída confirmada","escalada_id":"81000000-0000-0000-0000-000000000010"}',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours 30 minutes'
),
(
  'ef0b0000-0000-0000-0000-000000000004',
  '3EB0DIEGCONF0001',
  'evo_alessia',
  '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'confirmacao',
  '91000000-0000-0000-0000-000000000013', NULL,
  '{"comando":"finalizado 4000","valor_final":4000}',
  ((NOW() - INTERVAL '3 days')::date + TIME '22:10') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimento_servicos ===
-- Programa Completo 3h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000013',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000003',
  3500.00
)
ON CONFLICT DO NOTHING;

COMMIT;
