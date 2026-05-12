BEGIN;

-- ============================================================
-- BLOCO A — INFRAESTRUTURA COMPARTILHADA (idempotente)
-- ============================================================

-- === usuarios ===
INSERT INTO barravips.usuarios (id, nome, email, papel, ativo, created_at)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Fernando',
  'contato@procexai.te',
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
-- BLOCO B — CLIENTE: GUSTAVO MORAES
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000003',
  '+5521999990003',
  'Gustavo Moraes',
  'a1000000-0000-0000-0000-000000000001'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000003',
  'c1000000-0000-0000-0000-000000000003',
  'a1000000-0000-0000-0000-000000000001',
  '5521999990003@s.whatsapp.net',
  false,
  NULL,
  NULL,
  NOW() - INTERVAL '40 minutes',
  'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios (atendimento_id=NULL; UPDATE cruzado abaixo) ===
-- BLQ_ALE_05: hoje 22h–00h, bloqueado (Gustavo aguardando validação do Pix)
-- 22h evita sobreposição com BLQ_ALE_01/Eduardo (20h–22h) — EXCLUSION CONSTRAINT
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem) VALUES
(
  'b1000000-0000-0000-0000-000000000005',
  'a1000000-0000-0000-0000-000000000001', NULL,
  (NOW()::date + TIME '22:00') AT TIME ZONE 'America/Sao_Paulo',
  (NOW()::date + TIME '22:00' + INTERVAL '2 hours') AT TIME ZONE 'America/Sao_Paulo',
  'bloqueado', 'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos (bloqueio_id=NULL; UPDATE cruzado abaixo) ===

-- ATD_GUST_1: Aguardando_confirmacao, externo, pix_em_revisao (Fernando decide)
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
  '91000000-0000-0000-0000-000000000006', 6,
  'c1000000-0000-0000-0000-000000000003',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000003',
  NULL,
  'Aguardando_confirmacao', 'externo', 'agendado',
  NOW()::date, '22:00', 2.0,
  NULL, 'Ipanema', 'hotel', 'Hotel Ipanema Inn — Rua Vinícius de Moraes',
  'pix', 1500.00, NULL, 40.00,
  NULL, NULL, 'em_revisao',
  NULL, NULL,
  true, 'pix_em_revisao', 'Fernando',
  'Fernando validar ou recusar o comprovante Pix pelo painel.',
  'Pix de R$ 200 recebido. Titular "G. M. Silva" não confere com o nome cadastrado "Gustavo Moraes".',
  'Gustavo Moraes, novo, externo. Hotel Ipanema Inn, hoje 22h, 2h, R$ 1.500. Pix em revisão.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
  'pipeline_pix',
  NOW() - INTERVAL '2 hours',
  NOW() - INTERVAL '40 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado bloqueios ↔ atendimentos ===
UPDATE barravips.bloqueios
  SET atendimento_id = '91000000-0000-0000-0000-000000000006'
  WHERE id = 'b1000000-0000-0000-0000-000000000005'
    AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
  SET bloqueio_id = 'b1000000-0000-0000-0000-000000000005'
  WHERE id = '91000000-0000-0000-0000-000000000006'
    AND bloqueio_id IS NULL;

-- === mensagens ===
-- CNV_GUST_ALE — MSG-027 a MSG-033 (ATD_GUST_1)
-- Trigger atualiza_ultima_mensagem_em_conversa atualizará conversas.ultima_mensagem_em
-- e ultima_mensagem_direcao automaticamente (resultado final: 'ia', NOW()-40min)
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  -- MSG-027: Gustavo abre conversa, pergunta sobre externo
  '0a300000-0000-0000-0000-000000000027',
  'f1000000-0000-0000-0000-000000000003', '91000000-0000-0000-0000-000000000006',
  'cliente', 'texto',
  'Oi Alessia, tô querendo ir num hotel hoje à noite tipo 22h. Você atende externo?',
  NULL, '3EB0GUST00000001',
  NOW() - INTERVAL '2 hours'
),
(
  -- MSG-028: IA confirma e pede detalhes do hotel
  '0a300000-0000-0000-0000-000000000028',
  'f1000000-0000-0000-0000-000000000003', '91000000-0000-0000-0000-000000000006',
  'ia', 'texto',
  'Oi! Atendo sim 😊 Qual hotel e em qual bairro?',
  NULL, '3EB0GUST00000002',
  NOW() - INTERVAL '1 hour 58 minutes'
),
(
  -- MSG-029: Gustavo informa hotel Ipanema Inn e duração
  '0a300000-0000-0000-0000-000000000029',
  'f1000000-0000-0000-0000-000000000003', '91000000-0000-0000-0000-000000000006',
  'cliente', 'texto',
  'Hotel Ipanema Inn, na Rua Vinícius de Moraes. Quero 2 horas.',
  NULL, '3EB0GUST00000003',
  NOW() - INTERVAL '1 hour 50 minutes'
),
(
  -- MSG-030: IA informa valor e solicita Pix de deslocamento
  '0a300000-0000-0000-0000-000000000030',
  'f1000000-0000-0000-0000-000000000003', '91000000-0000-0000-0000-000000000006',
  'ia', 'texto',
  'Ótima região! Para 2h em hotel, R$ 1.500. Para confirmar, Pix de deslocamento de R$ 200 para a chave 21999990100 (Alessia Viana). Topo?',
  NULL, '3EB0GUST00000004',
  NOW() - INTERVAL '1 hour 45 minutes'
),
(
  -- MSG-031: Gustavo aceita e avisa que vai mandar o Pix
  '0a300000-0000-0000-0000-000000000031',
  'f1000000-0000-0000-0000-000000000003', '91000000-0000-0000-0000-000000000006',
  'cliente', 'texto',
  'Topo. Mandando agora.',
  NULL, '3EB0GUST00000005',
  NOW() - INTERVAL '1 hour 20 minutes'
),
(
  -- MSG-032: Gustavo envia comprovante Pix (imagem) — referenciado em PIX_GUST_1
  '0a300000-0000-0000-0000-000000000032',
  'f1000000-0000-0000-0000-000000000003', '91000000-0000-0000-0000-000000000006',
  'cliente', 'imagem',
  '[comprovante de Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000003/3EB0GUST00000006.jpg',
  '3EB0GUST00000006',
  NOW() - INTERVAL '1 hour 15 minutes'
),
(
  -- MSG-033: IA confirma recebimento e informa que está verificando
  -- Após este envio: pipeline sinalizou em_revisao, ia_pausada=true
  '0a300000-0000-0000-0000-000000000033',
  'f1000000-0000-0000-0000-000000000003', '91000000-0000-0000-0000-000000000006',
  'ia', 'texto',
  'Recebi! Só verificando aqui e já confirmo 🌸',
  NULL, '3EB0GUST00000007',
  NOW() - INTERVAL '40 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === comprovantes_pix ===
-- PIX_GUST_1: em_revisao — titular "G. M. Silva" diverge do cadastro "Gustavo Moraes"
INSERT INTO barravips.comprovantes_pix (
  id, atendimento_id, mensagem_id,
  valor_extraido, chave_extraida, titular_extraido, timestamp_extraido,
  decisao_pipeline, motivo_em_revisao,
  decisao_final, decisao_final_por,
  created_at
) VALUES (
  '71000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-000000000006',
  '0a300000-0000-0000-0000-000000000032',
  200.00,
  '21999990100',
  'G. M. Silva',
  NOW() - INTERVAL '1 hour 15 minutes',
  'em_revisao',
  'Titular "G. M. Silva" não confere com o nome cadastrado do cliente "Gustavo Moraes".',
  NULL, NULL,
  NOW() - INTERVAL '1 hour 10 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === escaladas ===
-- ESC_GUST_1: aberta — pix_em_revisao, Fernando precisa validar ou recusar
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel,
  motivo, resumo_operacional, acao_esperada,
  card_message_id,
  aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000005',
  '91000000-0000-0000-0000-000000000006',
  'Fernando',
  'Pix de R$ 200 recebido. Titular "G. M. Silva" não confere com "Gustavo Moraes".',
  'Gustavo Moraes, novo, externo. Hotel Ipanema Inn, hoje 22h, 2h, R$ 1.500. Pix em revisão.',
  'Validar ou recusar o comprovante pelo painel. Se validado, IA confirma o atendimento.',
  '3EB0CARD00000005',
  NOW() - INTERVAL '1 hour 10 minutes',
  NULL, NULL, NULL
)
ON CONFLICT (id) DO NOTHING;

-- === eventos ===
-- ATD_GUST_1: ciclo Novo → Triagem → Qualificado → Aguardando_confirmacao + Pix em revisão
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  -- E41: IA detecta abertura de atendimento
  'e0000000-0000-0000-0000-000000000041',
  '91000000-0000-0000-0000-000000000006',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 58 minutes'
),
(
  -- E42: IA qualifica (horário, local e valor confirmados)
  'e0000000-0000-0000-0000-000000000042',
  '91000000-0000-0000-0000-000000000006',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 50 minutes'
),
(
  -- E43: IA avança para aguardando confirmação (Pix solicitado)
  'e0000000-0000-0000-0000-000000000043',
  '91000000-0000-0000-0000-000000000006',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 hour 45 minutes'
),
(
  -- E44: IA cria bloqueio BLQ_ALE_05 (21h–23h hoje)
  'e0000000-0000-0000-0000-000000000044',
  '91000000-0000-0000-0000-000000000006',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000005","inicio":"22:00","fim":"00:00"}',
  NOW() - INTERVAL '1 hour 44 minutes'
),
(
  -- E45: IA solicita Pix de deslocamento R$ 200
  'e0000000-0000-0000-0000-000000000045',
  '91000000-0000-0000-0000-000000000006',
  'pix_solicitado', 'agente', 'IA',
  '{"chave":"21999990100","valor":200}',
  NOW() - INTERVAL '1 hour 43 minutes'
),
(
  -- E46: pipeline processa Pix e retorna em_revisao (titular divergente)
  'e0000000-0000-0000-0000-000000000046',
  '91000000-0000-0000-0000-000000000006',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id":"71000000-0000-0000-0000-000000000002","decisao":"em_revisao"}',
  NOW() - INTERVAL '1 hour 10 minutes'
),
(
  -- E47: sistema abre handoff para Fernando decidir sobre o Pix
  'e0000000-0000-0000-0000-000000000047',
  '91000000-0000-0000-0000-000000000006',
  'handoff_aberto', 'pipeline_pix', 'sistema',
  '{"motivo":"Pix em revisão — titular divergente do cadastro","responsavel":"Fernando","ia_pausada_motivo":"pix_em_revisao"}',
  NOW() - INTERVAL '1 hour 10 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === envios_evolution ===
-- Card ESC_GUST_1 no grupo de coordenação (IA Admin P0: grupo_coordenacao)
-- Mensagem IA MSG-033 na conversa do cliente
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid,
  contexto, direcao, tipo,
  atendimento_id, conversa_id,
  payload, created_at
) VALUES
(
  'ef030000-0000-0000-0000-000000000001',
  '3EB0CARD00000005',
  'evo_alessia',
  '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000006', NULL,
  '{"titulo":"Pix em revisão","escalada_id":"81000000-0000-0000-0000-000000000005"}',
  NOW() - INTERVAL '1 hour 10 minutes'
),
(
  'ef030000-0000-0000-0000-000000000002',
  '3EB0IA000000005',
  'evo_alessia',
  '5521999990003@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000006', 'f1000000-0000-0000-0000-000000000003',
  '{"tipo_msg":"texto","len":46}',
  NOW() - INTERVAL '40 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimento_servicos ===
-- Nenhum: ATD_GUST_1 está em Aguardando_confirmacao (não Fechado).

COMMIT;
