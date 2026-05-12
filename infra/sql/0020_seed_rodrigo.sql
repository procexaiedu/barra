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
-- BLOCO B — CLIENTE: RODRIGO TEIXEIRA
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000008',
  '+5521999990008',
  'Rodrigo Teixeira',
  'a1000000-0000-0000-0000-000000000002'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000008',
  'c1000000-0000-0000-0000-000000000008',
  'a1000000-0000-0000-0000-000000000002',
  '5521999990008@s.whatsapp.net',
  false,
  NULL,
  'risco',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour',
  'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios (atendimento_id=NULL; UPDATE cruzado abaixo) ===
-- BLQ_BRU_02: -2d 20h–21h, cancelado (Pix rejeitado → Perdido → trigger cancela)
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao) VALUES
(
  'b1000000-0000-0000-0000-000000000009',
  'a1000000-0000-0000-0000-000000000002', NULL,
  ((NOW() - INTERVAL '2 days')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '2 days')::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo',
  'cancelado', 'ia', NULL
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos (bloqueio_id=NULL; UPDATE cruzado abaixo) ===

-- ATD_RODR_1: Perdido (risco) -2d, externo Recreio, 20h, 1h
-- Pix rejeitado pelo Fernando — conta_destino_invalida. Marcado como Perdido por risco.
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
  '91000000-0000-0000-0000-000000000010', 2,
  'c1000000-0000-0000-0000-000000000008',
  'a1000000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000008',
  NULL,
  'Perdido', 'externo', 'agendado',
  (NOW() - INTERVAL '2 days')::date, '20:00', 1.0,
  NULL, 'Recreio', 'apartamento', NULL,
  'pix', 1200.00, NULL, NULL,
  'risco', 'Pix com conta de destino inválida.', 'invalido',
  NULL, NULL,
  false, NULL, 'IA',
  NULL, NULL,
  'Rodrigo Teixeira, externo, Recreio. Pix rejeitado (conta_destino_invalida). Fernando marcou como Perdido por risco.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
  'painel_fernando',
  NOW() - INTERVAL '2 days' - INTERVAL '2 hours',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado bloqueios ↔ atendimentos ===
UPDATE barravips.bloqueios
  SET atendimento_id = '91000000-0000-0000-0000-000000000010'
  WHERE id = 'b1000000-0000-0000-0000-000000000009'
    AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
  SET bloqueio_id = 'b1000000-0000-0000-0000-000000000009'
  WHERE id = '91000000-0000-0000-0000-000000000010'
    AND bloqueio_id IS NULL;

-- === mensagens ===
-- CNV_RODR_BRU — MSG-057 a MSG-062 (ATD_RODR_1, Perdido risco, -2 dias)
-- Trigger atualiza_ultima_mensagem_em_conversa definirá ultima_mensagem_em/direcao
-- Resultado final: 'ia', MSG-062 (-2d -1h 25min)
INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at
) VALUES
(
  -- MSG-057: Rodrigo abre conversa perguntando externo no Recreio
  '0a800000-0000-0000-0000-000000000057',
  'f1000000-0000-0000-0000-000000000008', '91000000-0000-0000-0000-000000000010',
  'cliente', 'texto',
  'Oi, você faz externo no Recreio?',
  NULL, '3EB0RODR00000001',
  NOW() - INTERVAL '2 days' - INTERVAL '2 hours'
),
(
  -- MSG-058: IA Bruna confirma externo e pede detalhes
  '0a800000-0000-0000-0000-000000000058',
  'f1000000-0000-0000-0000-000000000008', '91000000-0000-0000-0000-000000000010',
  'ia', 'texto',
  'Faço sim! 😊 Para onde exatamente e qual horário?',
  NULL, '3EB0RODR00000002',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 58 minutes'
),
(
  -- MSG-059: Rodrigo informa local, horário e duração
  '0a800000-0000-0000-0000-000000000059',
  'f1000000-0000-0000-0000-000000000008', '91000000-0000-0000-0000-000000000010',
  'cliente', 'texto',
  'Meu apartamento no Recreio, amanhã às 20h, 1 hora.',
  NULL, '3EB0RODR00000003',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 50 minutes'
),
(
  -- MSG-060: IA apresenta valor e solicita Pix de deslocamento
  '0a800000-0000-0000-0000-000000000060',
  'f1000000-0000-0000-0000-000000000008', '91000000-0000-0000-0000-000000000010',
  'ia', 'texto',
  'Pode ser! Para 1h em apartamento, R$ 1.200. Pix de deslocamento de R$ 120 para a chave 21999990200 (Bruna Martins). Me manda?',
  NULL, '3EB0RODR00000004',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 45 minutes'
),
(
  -- MSG-061: Rodrigo envia comprovante Pix — referenciado por PIX_RODR_1
  '0a800000-0000-0000-0000-000000000061',
  'f1000000-0000-0000-0000-000000000008', '91000000-0000-0000-0000-000000000010',
  'cliente', 'imagem',
  '[comprovante de Pix R$ 120]',
  'mensagens/f1000000-0000-0000-0000-000000000008/3EB0RODR00000005.jpg',
  '3EB0RODR00000005',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 30 minutes'
),
(
  -- MSG-062: IA recebeu comprovante; pipeline detecta conta_destino_invalida → em_revisao
  '0a800000-0000-0000-0000-000000000062',
  'f1000000-0000-0000-0000-000000000008', '91000000-0000-0000-0000-000000000010',
  'ia', 'texto',
  'Recebi! Verificando aqui e já confirmo 🌸',
  NULL, '3EB0RODR00000006',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 25 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === comprovantes_pix ===
-- PIX_RODR_1: em_revisao pelo pipeline (conta_destino_invalida), Fernando rejeita (invalido)
INSERT INTO barravips.comprovantes_pix (
  id, atendimento_id, mensagem_id,
  valor_extraido, chave_extraida, titular_extraido, timestamp_extraido,
  decisao_pipeline, motivo_em_revisao, decisao_final, decisao_final_por,
  created_at
) VALUES (
  '71000000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-000000000010',
  '0a800000-0000-0000-0000-000000000061',
  120.00,
  '21999990200',
  'R. Teixeira',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 30 minutes',
  'em_revisao',
  'Conta de destino da chave Pix não confere com a chave cadastrada da modelo (conta_destino_invalida).',
  'invalido',
  '00000000-0000-0000-0000-000000000001',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 25 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === escaladas ===
-- ESC_RODR_1: fechada — Pix rejeitado pelo painel pelo Fernando
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000007',
  '91000000-0000-0000-0000-000000000010',
  'Fernando',
  'Pix com conta de destino inválida. Fernando rejeitou e marcou como Perdido.',
  'Rodrigo Teixeira, externo, Recreio. Pix de R$ 120 rejeitado — conta_destino_invalida.',
  'Fernando avaliar e decidir sobre o Pix inválido.',
  '3EB0CARD00000007',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 25 minutes',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour',
  '00000000-0000-0000-0000-000000000001',
  'painel'
)
ON CONFLICT (id) DO NOTHING;

-- === eventos ===
-- ATD_RODR_1: Novo → Triagem → Qualificado → Aguardando_confirmacao → Perdido (painel Fernando)
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  -- EN17: Novo → Triagem
  '0e800000-0000-0000-0000-000000000017',
  '91000000-0000-0000-0000-000000000010',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 58 minutes'
),
(
  -- EN18: Triagem → Qualificado
  '0e800000-0000-0000-0000-000000000018',
  '91000000-0000-0000-0000-000000000010',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 50 minutes'
),
(
  -- EN19: Qualificado → Aguardando_confirmacao
  '0e800000-0000-0000-0000-000000000019',
  '91000000-0000-0000-0000-000000000010',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 48 minutes'
),
(
  -- EN20: bloqueio criado para 20h–21h (BLQ_BRU_02)
  '0e800000-0000-0000-0000-000000000020',
  '91000000-0000-0000-0000-000000000010',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000009","inicio":"20:00","fim":"21:00"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 47 minutes'
),
(
  -- EN21: Pix solicitado (R$ 120 para chave da Bruna)
  '0e800000-0000-0000-0000-000000000021',
  '91000000-0000-0000-0000-000000000010',
  'pix_solicitado', 'agente', 'IA',
  '{"chave":"21999990200","valor":120}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 46 minutes'
),
(
  -- EN22: pipeline detecta conta_destino_invalida → em_revisao
  '0e800000-0000-0000-0000-000000000022',
  '91000000-0000-0000-0000-000000000010',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id":"71000000-0000-0000-0000-000000000004","decisao":"em_revisao","motivo":"conta_destino_invalida"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 25 minutes'
),
(
  -- EN23: handoff_aberto para Fernando — Pix em revisão
  '0e800000-0000-0000-0000-000000000023',
  '91000000-0000-0000-0000-000000000010',
  'handoff_aberto', 'pipeline_pix', 'sistema',
  '{"motivo":"Pix inválido — conta de destino não confere com chave da modelo","responsavel":"Fernando","ia_pausada_motivo":"pix_em_revisao"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 25 minutes'
),
(
  -- EN24: Fernando rejeita o Pix no painel (decisao_final='invalido')
  '0e800000-0000-0000-0000-000000000024',
  '91000000-0000-0000-0000-000000000010',
  'pix_status_mudado', 'painel', 'Fernando',
  '{"pix_id":"71000000-0000-0000-0000-000000000004","decisao":"invalido"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour'
),
(
  -- EN25: Fernando registra perda por risco
  '0e800000-0000-0000-0000-000000000025',
  '91000000-0000-0000-0000-000000000010',
  'perdido_registrado', 'painel', 'Fernando',
  '{"motivo":"risco","obs":"Pix com conta de destino inválida."}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour'
),
(
  -- EN26: transição final Aguardando_confirmacao → Perdido
  '0e800000-0000-0000-0000-000000000026',
  '91000000-0000-0000-0000-000000000010',
  'transicao_estado', 'painel', 'Fernando',
  '{"de":"Aguardando_confirmacao","para":"Perdido","fonte_decisao":"painel_fernando"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour'
),
(
  -- EN27: trigger sync_bloqueio_estado cancela o bloqueio
  '0e800000-0000-0000-0000-000000000027',
  '91000000-0000-0000-0000-000000000010',
  'bloqueio_estado_mudado', 'agente', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000009","de":"bloqueado","para":"cancelado"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour'
)
ON CONFLICT (id) DO NOTHING;

-- === envios_evolution ===

-- ESC_RODR_1 card: "Pix em revisão" no grupo de coordenação da Bruna
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid,
  contexto, direcao, tipo,
  atendimento_id, conversa_id,
  payload, created_at
) VALUES
(
  'ef080000-0000-0000-0000-000000000001',
  '3EB0CARD00000007',
  'evo_bruna',
  '120363222222222001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000010', NULL,
  '{"titulo":"Pix em revisão — conta_destino_invalida","escalada_id":"81000000-0000-0000-0000-000000000007"}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 25 minutes'
),
(
  -- MSG-062: IA Bruna confirma recebimento do comprovante a Rodrigo
  'ef080000-0000-0000-0000-000000000002',
  '3EB0IA000000011',
  'evo_bruna',
  '5521999990008@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000010', 'f1000000-0000-0000-0000-000000000008',
  '{"tipo_msg":"texto","len":42}',
  NOW() - INTERVAL '2 days' - INTERVAL '1 hour 25 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimento_servicos ===
-- Nenhum: ATD_RODR_1 está Perdido (não Fechado).

COMMIT;
