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
-- BLOCO B — CLIENTE: LUCAS BORGES
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000010',
  '+5521999990010',
  'Lucas Borges',
  'a1000000-0000-0000-0000-000000000002'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000010',
  'c1000000-0000-0000-0000-000000000010',
  'a1000000-0000-0000-0000-000000000002',
  '5521999990010@s.whatsapp.net',
  false,
  NULL,
  NULL,
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo',
  'modelo_manual'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios (atendimento_id=NULL; UPDATE cruzado abaixo) ===
-- BLQ_BRU_03: ONTEM 21h-23h, concluido
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao) VALUES
(
  'b1000000-0000-0000-0000-000000000011',
  'a1000000-0000-0000-0000-000000000002', NULL,
  ((NOW() - INTERVAL '1 day')::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:00') AT TIME ZONE 'America/Sao_Paulo',
  'concluido', 'ia', NULL
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos (bloqueio_id=NULL; UPDATE cruzado abaixo) ===

-- ATD_LUCA_1: Fechado ONTEM, externo Recreio, 2h, R$ 2.400 (Pix R$ 200 + R$ 2.200)
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
  '91000000-0000-0000-0000-000000000012', 3,
  'c1000000-0000-0000-0000-000000000010',
  'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000010',
  NULL,
  'Fechado', 'externo', 'agendado',
  (NOW() - INTERVAL '1 day')::date, '21:00', 2.0,
  'Av. Lúcio Costa, 5210, Apto 802', 'Recreio',
  'apartamento', 'Condomínio Vista Mar',
  'pix', 2200.00, 2400.00, 35.00,
  NULL, NULL, 'validado',
  NULL, NULL,
  false, NULL, 'IA',
  NULL, NULL,
  'Lucas Borges, novo, externo, Recreio. Pix de R$ 200 validado. Encerrou com R$ 2.400.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
  'comando_grupo',
  NOW() - INTERVAL '1 day' - INTERVAL '3 hours',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado bloqueios ↔ atendimentos ===
UPDATE barravips.bloqueios
  SET atendimento_id = '91000000-0000-0000-0000-000000000012'
  WHERE id = 'b1000000-0000-0000-0000-000000000011'
    AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
  SET bloqueio_id = 'b1000000-0000-0000-0000-000000000011'
  WHERE id = '91000000-0000-0000-0000-000000000012'
    AND bloqueio_id IS NULL;

-- === mensagens ===
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  -- Lucas abre conversa
  '0aa00000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000010', '91000000-0000-0000-0000-000000000012',
  'cliente', 'texto',
  'Oi Bruna! Estou no Recreio, queria te chamar para hoje à noite, 21h, umas 2h. É no meu apê.',
  NULL, '3EB0LUCA00000001',
  NOW() - INTERVAL '1 day' - INTERVAL '3 hours'
),
(
  -- IA Bruna confirma valor e pede Pix
  '0aa00000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000010', '91000000-0000-0000-0000-000000000012',
  'ia', 'texto',
  'Oi Lucas! Adoro Recreio 😊 Para 2h em apartamento, R$ 2.200. Para confirmar, preciso do Pix de deslocamento de R$ 200 para 21999990200 (Bruna Martins). Combina?',
  NULL, '3EB0LUCA00000002',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 58 minutes'
),
(
  -- Cliente concorda
  '0aa00000-0000-0000-0000-000000000003',
  'f1000000-0000-0000-0000-000000000010', '91000000-0000-0000-0000-000000000012',
  'cliente', 'texto',
  'Combinado. Mando o Pix agora.',
  NULL, '3EB0LUCA00000003',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 50 minutes'
),
(
  -- Lucas envia comprovante (referenciado por PIX_LUCA_1)
  '0aa00000-0000-0000-0000-000000000004',
  'f1000000-0000-0000-0000-000000000010', '91000000-0000-0000-0000-000000000012',
  'cliente', 'imagem',
  '[comprovante de Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000010/3EB0LUCA00000004.jpg',
  '3EB0LUCA00000004',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 40 minutes'
),
(
  -- IA confirma Pix validado
  '0aa00000-0000-0000-0000-000000000005',
  'f1000000-0000-0000-0000-000000000010', '91000000-0000-0000-0000-000000000012',
  'ia', 'texto',
  'Pix confirmado ✅ Estarei aí às 21h pontualmente! Me manda o endereço completo 🌸',
  NULL, '3EB0LUCA00000005',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes'
),
(
  -- Lucas envia endereço
  '0aa00000-0000-0000-0000-000000000006',
  'f1000000-0000-0000-0000-000000000010', '91000000-0000-0000-0000-000000000012',
  'cliente', 'texto',
  'Av. Lúcio Costa 5210, Vista Mar, apê 802. Portaria já está avisada.',
  NULL, '3EB0LUCA00000006',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 20 minutes'
),
(
  -- Modelo encerra com finalizado
  '0aa00000-0000-0000-0000-000000000007',
  'f1000000-0000-0000-0000-000000000010', '91000000-0000-0000-0000-000000000012',
  'modelo_manual', 'texto',
  'finalizado 2400',
  NULL, '3EB0LUCA00000007',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === comprovantes_pix ===
-- PIX_LUCA_1: validado automaticamente
INSERT INTO barravips.comprovantes_pix (
  id, atendimento_id, mensagem_id,
  valor_extraido, chave_extraida, titular_extraido, timestamp_extraido,
  decisao_pipeline, motivo_em_revisao, decisao_final, decisao_final_por,
  created_at
) VALUES (
  '71000000-0000-0000-0000-000000000005',
  '91000000-0000-0000-0000-000000000012',
  '0aa00000-0000-0000-0000-000000000004',
  200.00, '21999990200', 'Lucas Borges',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 40 minutes',
  'validado', NULL, NULL, NULL,
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 38 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === escaladas ===
-- ESC_LUCA_1: fechada "saída confirmada"
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000009',
  '91000000-0000-0000-0000-000000000012',
  'modelo',
  'Pix de deslocamento validado automaticamente. Bruna a caminho.',
  'Lucas Borges, externo, Vista Mar Recreio, ontem 21h, 2h. Pix de R$ 200 validado.',
  'Encerrar com "finalizado [valor]" ao término.',
  '3EB0CARD00000009',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo',
  NULL, 'grupo_coordenacao'
)
ON CONFLICT (id) DO NOTHING;

-- === eventos ===
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  '0ea00000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-000000000012',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 58 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-000000000012',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 50 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000003',
  '91000000-0000-0000-0000-000000000012',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 48 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-000000000012',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000011","inicio":"21:00","fim":"23:00"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 47 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000005',
  '91000000-0000-0000-0000-000000000012',
  'pix_solicitado', 'agente', 'IA',
  '{"chave":"21999990200","valor":200}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 46 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000006',
  '91000000-0000-0000-0000-000000000012',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id":"71000000-0000-0000-0000-000000000005","decisao":"validado"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000007',
  '91000000-0000-0000-0000-000000000012',
  'handoff_aberto', 'pipeline_pix', 'sistema',
  '{"motivo":"Pix de deslocamento validado automaticamente","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000008',
  '91000000-0000-0000-0000-000000000012',
  'transicao_estado', 'pipeline_pix', 'sistema',
  '{"de":"Aguardando_confirmacao","para":"Confirmado","fonte_decisao":"pipeline_pix"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes'
),
(
  '0ea00000-0000-0000-0000-000000000009',
  '91000000-0000-0000-0000-000000000012',
  'bloqueio_estado_mudado', 'cron', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000011","de":"bloqueado","para":"em_atendimento"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0ea00000-0000-0000-0000-000000000010',
  '91000000-0000-0000-0000-000000000012',
  'transicao_estado', 'cron', 'sistema',
  '{"de":"Confirmado","para":"Em_execucao","fonte_decisao":"cron_em_execucao"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0ea00000-0000-0000-0000-000000000011',
  '91000000-0000-0000-0000-000000000012',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"comando":"finalizado 2400","valor_final":2400}',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0ea00000-0000-0000-0000-000000000012',
  '91000000-0000-0000-0000-000000000012',
  'transicao_estado', 'grupo_coordenacao', 'modelo',
  '{"de":"Em_execucao","para":"Fechado","fonte_decisao":"comando_grupo"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0ea00000-0000-0000-0000-000000000013',
  '91000000-0000-0000-0000-000000000012',
  'bloqueio_estado_mudado', 'agente', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000011","de":"em_atendimento","para":"concluido"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo'
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
  'ef0a0000-0000-0000-0000-000000000001',
  '3EB0LUCAIA000001',
  'evo_bruna',
  '5521999990010@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000012', 'f1000000-0000-0000-0000-000000000010',
  '{"tipo_msg":"texto","len":145}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 58 minutes'
),
(
  'ef0a0000-0000-0000-0000-000000000002',
  '3EB0LUCAIA000002',
  'evo_bruna',
  '5521999990010@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000012', 'f1000000-0000-0000-0000-000000000010',
  '{"tipo_msg":"texto","len":80}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes'
),
(
  -- Card "saída confirmada"
  'ef0a0000-0000-0000-0000-000000000003',
  '3EB0CARD00000009',
  'evo_bruna',
  '120363222222222001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000012', NULL,
  '{"titulo":"Saída confirmada","escalada_id":"81000000-0000-0000-0000-000000000009"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes'
),
(
  -- Confirmação finalizado
  'ef0a0000-0000-0000-0000-000000000004',
  '3EB0LUCACONF0001',
  'evo_bruna',
  '120363222222222001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'confirmacao',
  '91000000-0000-0000-0000-000000000012', NULL,
  '{"comando":"finalizado 2400","valor_final":2400}',
  ((NOW() - INTERVAL '1 day')::date + TIME '23:10') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimento_servicos ===
-- Programa Completo 2h
INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot) VALUES
(
  '91000000-0000-0000-0000-000000000012',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000002',
  2200.00
)
ON CONFLICT DO NOTHING;

COMMIT;
