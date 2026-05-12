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
-- BLOCO B — CLIENTE: FELIPE RAMOS
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000007',
  '+5521999990007',
  'Felipe Ramos',
  'a1000000-0000-0000-0000-000000000001'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000007',
  'c1000000-0000-0000-0000-000000000007',
  'a1000000-0000-0000-0000-000000000001',
  '5521999990007@s.whatsapp.net',
  false,
  NULL,
  'sumiu',
  NOW() - INTERVAL '5 days' - INTERVAL '2 hours',
  'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios (atendimento_id=NULL; UPDATE cruzado abaixo) ===
-- BLQ_ALE_06: -5d 20h–22h, cancelado por auto_timeout_interno (Felipe sumiu)
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao) VALUES
(
  'b1000000-0000-0000-0000-000000000006',
  'a1000000-0000-0000-0000-000000000001', NULL,
  ((NOW() - INTERVAL '5 days')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '5 days')::date + TIME '22:00') AT TIME ZONE 'America/Sao_Paulo',
  'cancelado', 'ia', NULL
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos (bloqueio_id=NULL; UPDATE cruzado abaixo) ===

-- ATD_FELI_1: Perdido (sumiu) -5d, interno, 20h, 2h
-- Cliente avisou que estava saindo mas nunca enviou foto de portaria.
-- Cron auto_timeout_interno marcou como Perdido após 30min sem foto.
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
  '91000000-0000-0000-0000-000000000009', 8,
  'c1000000-0000-0000-0000-000000000007',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000007',
  NULL,
  'Perdido', 'interno', 'agendado',
  (NOW() - INTERVAL '5 days')::date, '20:00', 2.0,
  NULL, NULL, NULL, NULL,
  'dinheiro', 1500.00, NULL, NULL,
  'sumiu', NULL, 'nao_solicitado',
  ((NOW() - INTERVAL '5 days')::date + TIME '19:50') AT TIME ZONE 'America/Sao_Paulo',
  NULL,
  false, NULL, 'IA',
  NULL, NULL,
  'Felipe Ramos, novo, interno. Avisou saída às 19h50, não enviou foto de portaria. Marcado como Perdido (sumiu) por timeout automático.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
  'auto_timeout_interno',
  NOW() - INTERVAL '5 days' - INTERVAL '2 hours',
  NOW() - INTERVAL '5 days' + INTERVAL '20 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado bloqueios ↔ atendimentos ===
UPDATE barravips.bloqueios
  SET atendimento_id = '91000000-0000-0000-0000-000000000009'
  WHERE id = 'b1000000-0000-0000-0000-000000000006'
    AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
  SET bloqueio_id = 'b1000000-0000-0000-0000-000000000006'
  WHERE id = '91000000-0000-0000-0000-000000000009'
    AND bloqueio_id IS NULL;

-- === mensagens ===
-- CNV_FELI_ALE — MSG-052 a MSG-056 (ATD_FELI_1, Perdido sumiu, -5 dias)
-- Trigger atualiza_ultima_mensagem_em_conversa definirá ultima_mensagem_em/direcao
-- Resultado final: 'cliente', MSG-056 (aviso de saída às 19h50)
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  -- MSG-052: Felipe abre a conversa
  '0a700000-0000-0000-0000-000000000052',
  'f1000000-0000-0000-0000-000000000007', '91000000-0000-0000-0000-000000000009',
  'cliente', 'texto',
  'Oi Alessia, quero ir aí hoje à noite pelas 20h.',
  NULL, '3EB0FELI00000001',
  NOW() - INTERVAL '5 days' - INTERVAL '2 hours'
),
(
  -- MSG-053: IA Alessia confirma horário e valor
  '0a700000-0000-0000-0000-000000000053',
  'f1000000-0000-0000-0000-000000000007', '91000000-0000-0000-0000-000000000009',
  'ia', 'texto',
  'Oi! Pode vir sim, 20h está ótimo 😊 Para 2h aqui em casa, R$ 1.500 em dinheiro. Combinado?',
  NULL, '3EB0FELI00000002',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 58 minutes'
),
(
  -- MSG-054: Felipe aceita e pergunta o endereço
  '0a700000-0000-0000-0000-000000000054',
  'f1000000-0000-0000-0000-000000000007', '91000000-0000-0000-0000-000000000009',
  'cliente', 'texto',
  'Combinado! Qual o endereço?',
  NULL, '3EB0FELI00000003',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 50 minutes'
),
(
  -- MSG-055: IA combina passar o endereço no momento da saída
  '0a700000-0000-0000-0000-000000000055',
  'f1000000-0000-0000-0000-000000000007', '91000000-0000-0000-0000-000000000009',
  'ia', 'texto',
  'Passo o endereço quando você estiver saindo, pode ser? Me avisa!',
  NULL, '3EB0FELI00000004',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 48 minutes'
),
(
  -- MSG-056: Felipe avisa que está saindo (aviso_saida_em). Não envia foto de portaria → timeout
  '0a700000-0000-0000-0000-000000000056',
  'f1000000-0000-0000-0000-000000000007', '91000000-0000-0000-0000-000000000009',
  'cliente', 'texto',
  'Tô saindo agora.',
  NULL, '3EB0FELI00000005',
  ((NOW() - INTERVAL '5 days')::date + TIME '19:50') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === comprovantes_pix ===
-- Nenhum: atendimento interno, pix_status='nao_solicitado'.

-- === escaladas ===
-- Nenhuma: cron registrou perdido por timeout, sem handoff humano.

-- === eventos ===
-- ATD_FELI_1: Novo → Triagem → Qualificado → Aguardando_confirmacao → Perdido (cron auto_timeout_interno)
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  -- EN10: IA detecta abertura
  '0e700000-0000-0000-0000-000000000010',
  '91000000-0000-0000-0000-000000000009',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 58 minutes'
),
(
  -- EN11: IA qualifica
  '0e700000-0000-0000-0000-000000000011',
  '91000000-0000-0000-0000-000000000009',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 50 minutes'
),
(
  -- EN12: IA aguarda confirmação (interno, sem Pix obrigatório)
  '0e700000-0000-0000-0000-000000000012',
  '91000000-0000-0000-0000-000000000009',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 48 minutes'
),
(
  -- EN13: bloqueio criado para 20h–22h (BLQ_ALE_06)
  '0e700000-0000-0000-0000-000000000013',
  '91000000-0000-0000-0000-000000000009',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000006","inicio":"20:00","fim":"22:00"}',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 47 minutes'
),
(
  -- EN14: aviso_saida_em registrado (cliente sai mas nunca chega)
  '0e700000-0000-0000-0000-000000000014',
  '91000000-0000-0000-0000-000000000009',
  'extracao_registrada', 'agente', 'IA',
  '{"campo":"aviso_saida_em","valor":"agora"}',
  ((NOW() - INTERVAL '5 days')::date + TIME '19:50') AT TIME ZONE 'America/Sao_Paulo'
),
(
  -- EN15: cron auto_timeout_interno marca Perdido (sumiu) após 30min sem foto de portaria
  '0e700000-0000-0000-0000-000000000015',
  '91000000-0000-0000-0000-000000000009',
  'transicao_estado', 'cron', 'sistema',
  '{"de":"Aguardando_confirmacao","para":"Perdido","trigger":"auto_timeout_interno","motivo_perda":"sumiu","fonte_decisao":"auto_timeout_interno"}',
  ((NOW() - INTERVAL '5 days')::date + TIME '20:20') AT TIME ZONE 'America/Sao_Paulo'
),
(
  -- EN16: trigger sync_bloqueio_estado cancela o bloqueio
  '0e700000-0000-0000-0000-000000000016',
  '91000000-0000-0000-0000-000000000009',
  'bloqueio_estado_mudado', 'cron', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000006","de":"bloqueado","para":"cancelado"}',
  ((NOW() - INTERVAL '5 days')::date + TIME '20:20') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === envios_evolution ===
-- MSG-053: IA Alessia confirma horário e valor a Felipe
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid,
  contexto, direcao, tipo,
  atendimento_id, conversa_id,
  payload, created_at
) VALUES
(
  'ef070000-0000-0000-0000-000000000001',
  '3EB0IA000000010',
  'evo_alessia',
  '5521999990007@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000009', 'f1000000-0000-0000-0000-000000000007',
  '{"tipo_msg":"texto","len":72}',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 58 minutes'
),
(
  -- MSG-055: IA combina entregar endereço quando ele estiver saindo
  'ef070000-0000-0000-0000-000000000002',
  '3EB0FELIIA000001',
  'evo_alessia',
  '5521999990007@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000009', 'f1000000-0000-0000-0000-000000000007',
  '{"tipo_msg":"texto","len":61}',
  NOW() - INTERVAL '5 days' - INTERVAL '1 hour 48 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimento_servicos ===
-- Nenhum: ATD_FELI_1 está Perdido (não Fechado).

COMMIT;
