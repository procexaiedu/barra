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
-- BLOCO B — CLIENTE: ADRIANO SANTANA
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000004',
  '+5521999990004',
  'Adriano Santana',
  'a1000000-0000-0000-0000-000000000001'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000004',
  'c1000000-0000-0000-0000-000000000004',
  'a1000000-0000-0000-0000-000000000001',
  '5521999990004@s.whatsapp.net',
  false,
  NULL,
  'preco',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 13 minutes',
  'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios ===
-- ATD_ADRI_1 não tem bloqueio: perdido antes de confirmar (sem pix, sem horário reservado)

-- === atendimentos (sem bloqueio_id) ===

-- ATD_ADRI_1: Perdido −3d, externo, Ipanema, 1h, motivo=preco
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
  '91000000-0000-0000-0000-000000000003', 3,
  'c1000000-0000-0000-0000-000000000004',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000004',
  NULL,
  'Perdido', 'externo', 'agendado',
  (NOW() - INTERVAL '2 days')::date, '20:00', 1.0,
  NULL, 'Ipanema', 'apartamento', NULL,
  'pix', 1500.00, NULL, NULL,
  'preco', NULL, 'nao_solicitado',
  NULL, NULL,
  false, NULL, 'IA',
  NULL, NULL,
  'Adriano Santana, externo, Ipanema, 1h. Recusou R$ 1.500. Perdido por preço.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":false,"envia_pix":false,"responde_objetivamente":true}',
  'painel_fernando',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours',
  NOW() - INTERVAL '3 days'
)
ON CONFLICT (id) DO NOTHING;

-- === mensagens ===
-- CNV_ADRI_ALE — MSG-034 a MSG-041 (ATD_ADRI_1, −3 dias)
-- Trigger atualiza_ultima_mensagem_em_conversa definirá ultima_mensagem_em/direcao
-- Resultado final: 'ia', NOW()-3days-1h13min (MSG-041)
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  -- MSG-034: Adriano abre conversa perguntando disponibilidade
  '0a400000-0000-0000-0000-000000000034',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'cliente', 'texto',
  'Olá, vi o número no site. Você tem disponibilidade essa semana?',
  NULL, '3EB0ADRI00000001',
  NOW() - INTERVAL '3 days' - INTERVAL '2 hours'
),
(
  -- MSG-035: IA responde e qualifica
  '0a400000-0000-0000-0000-000000000035',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'ia', 'texto',
  'Oi! Tenho sim 😊 O que você tem em mente? Me conta horário e onde você prefere.',
  NULL, '3EB0ADRI00000002',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 58 minutes'
),
(
  -- MSG-036: Adriano informa local, horário e duração
  '0a400000-0000-0000-0000-000000000036',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'cliente', 'texto',
  'Pensava no meu apartamento em Ipanema, amanhã à noite, 1 hora.',
  NULL, '3EB0ADRI00000003',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 50 minutes'
),
(
  -- MSG-037: IA apresenta valor e condições
  '0a400000-0000-0000-0000-000000000037',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'ia', 'texto',
  'Ipanema ótimo! Para 1h em apartamento, R$ 1.500. Pix de deslocamento de R$ 150. Combinado?',
  NULL, '3EB0ADRI00000004',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 45 minutes'
),
(
  -- MSG-038: Adriano recusa o preço
  '0a400000-0000-0000-0000-000000000038',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'cliente', 'texto',
  'R$ 1.500 por 1h tá caro demais. Não tem como baixar?',
  NULL, '3EB0ADRI00000005',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 30 minutes'
),
(
  -- MSG-039: IA oferece alternativa de 2h
  '0a400000-0000-0000-0000-000000000039',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'ia', 'texto',
  'Entendo! Esse é o valor padrão por hora 😊 Posso oferecer 2h por R$ 2.800, que fica mais em conta por hora. O que acha?',
  NULL, '3EB0ADRI00000006',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 28 minutes'
),
(
  -- MSG-040: Adriano desiste
  '0a400000-0000-0000-0000-000000000040',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'cliente', 'texto',
  'Não, não compensa. Deixa pra lá.',
  NULL, '3EB0ADRI00000007',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 15 minutes'
),
(
  -- MSG-041: IA se despede — Fernando registra perdido/preco no painel após esta mensagem
  '0a400000-0000-0000-0000-000000000041',
  'f1000000-0000-0000-0000-000000000004', '91000000-0000-0000-0000-000000000003',
  'ia', 'texto',
  'Entendido! Se mudar de ideia, é só me chamar. Até mais! 😊',
  NULL, '3EB0ADRI00000008',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 13 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === comprovantes_pix ===
-- Nenhum: Adriano nunca enviou Pix (pix_status='nao_solicitado').

-- === escaladas ===
-- Nenhuma: Fernando registrou o resultado direto pelo painel, sem handoff da IA.

-- === eventos ===
-- ATD_ADRI_1: Novo → Triagem → Qualificado → Perdido (Fernando via painel)
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  -- E25: IA detecta abertura do atendimento
  'e0000000-0000-0000-0000-000000000025',
  '91000000-0000-0000-0000-000000000003',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 58 minutes'
),
(
  -- E26: IA identifica qualificação parcial (aceita_valor=false)
  'e0000000-0000-0000-0000-000000000026',
  '91000000-0000-0000-0000-000000000003',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":false},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 45 minutes'
),
(
  -- E27: Fernando registra perda por preço pelo painel
  'e0000000-0000-0000-0000-000000000027',
  '91000000-0000-0000-0000-000000000003',
  'perdido_registrado', 'painel', 'Fernando',
  '{"motivo":"preco","obs":null}',
  NOW() - INTERVAL '3 days' - INTERVAL '30 minutes'
),
(
  -- E28: transição final para Perdido
  'e0000000-0000-0000-0000-000000000028',
  '91000000-0000-0000-0000-000000000003',
  'transicao_estado', 'painel', 'Fernando',
  '{"de":"Qualificado","para":"Perdido","fonte_decisao":"painel_fernando"}',
  NOW() - INTERVAL '3 days' - INTERVAL '30 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === envios_evolution ===
-- MSG-041: IA se despede de Adriano (único envio backend nesta conversa)
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid,
  contexto, direcao, tipo,
  atendimento_id, conversa_id,
  payload, created_at
) VALUES
(
  'ef040000-0000-0000-0000-000000000001',
  '3EB0IA000000006',
  'evo_alessia',
  '5521999990004@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000003', 'f1000000-0000-0000-0000-000000000004',
  '{"tipo_msg":"texto","len":57}',
  NOW() - INTERVAL '3 days' - INTERVAL '1 hour 13 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimento_servicos ===
-- Nenhum: ATD_ADRI_1 está Perdido (não Fechado).

COMMIT;
