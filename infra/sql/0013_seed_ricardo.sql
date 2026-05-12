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
-- BLOCO B — CLIENTE: RICARDO ALVES
-- ============================================================

-- === clientes ===
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id)
VALUES (
  'c1000000-0000-0000-0000-000000000001',
  '+5521999990001',
  'Ricardo Alves',
  'a1000000-0000-0000-0000-000000000001'
)
ON CONFLICT (id) DO NOTHING;

-- === conversas ===
INSERT INTO barravips.conversas (
  id, cliente_id, modelo_id, evolution_chat_id,
  recorrente, observacoes_internas, ultimo_motivo_perda,
  ultima_mensagem_em, ultima_mensagem_direcao
) VALUES (
  'f1000000-0000-0000-0000-000000000001',
  'c1000000-0000-0000-0000-000000000001',
  'a1000000-0000-0000-0000-000000000001',
  '5521999990001@s.whatsapp.net',
  true,
  'Cliente VIP. 3 atendimentos em 7 dias. Sempre pontual. Prefere interno.',
  NULL,
  NOW() - INTERVAL '4 hours',
  'modelo_manual'
)
ON CONFLICT (id) DO NOTHING;

-- === bloqueios (atendimento_id=NULL; UPDATE cruzado abaixo) ===
INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem) VALUES
(
  'b1000000-0000-0000-0000-000000000004',
  'a1000000-0000-0000-0000-000000000001', NULL,
  ((NOW() - INTERVAL '7 days')::date + TIME '18:00') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '7 days')::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo',
  'concluido', 'ia'
),
(
  'b1000000-0000-0000-0000-000000000003',
  'a1000000-0000-0000-0000-000000000001', NULL,
  ((NOW() - INTERVAL '1 day')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '1 day')::date + TIME '22:30') AT TIME ZONE 'America/Sao_Paulo',
  'concluido', 'ia'
),
(
  'b1000000-0000-0000-0000-000000000002',
  'a1000000-0000-0000-0000-000000000001', NULL,
  (NOW()::date + TIME '15:00') AT TIME ZONE 'America/Sao_Paulo',
  (NOW()::date + TIME '17:00') AT TIME ZONE 'America/Sao_Paulo',
  'em_atendimento', 'ia'
)
ON CONFLICT (id) DO NOTHING;

-- === atendimentos (bloqueio_id=NULL; UPDATE cruzado abaixo) ===

-- ATD_RICO_1: Fechado −7d, interno, 3h
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
  '91000000-0000-0000-0000-000000000001', 1,
  'c1000000-0000-0000-0000-000000000001',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000001',
  NULL,
  'Fechado', 'interno', 'agendado',
  (NOW() - INTERVAL '7 days')::date, '18:00', 3.0,
  NULL, NULL, NULL, NULL,
  'dinheiro', 1500.00, 1800.00, 40.00,
  NULL, NULL, 'nao_solicitado',
  ((NOW() - INTERVAL '7 days')::date + TIME '17:45') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo',
  false, NULL, 'IA',
  NULL, NULL,
  'Ricardo Alves, interno, 3h. Chegou às 18h08 (foto de portaria). Alessia encerrou com R$ 1.800.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
  'comando_grupo',
  NOW() - INTERVAL '7 days' - INTERVAL '2 hours',
  NOW() - INTERVAL '7 days' + INTERVAL '3 hours'
)
ON CONFLICT (id) DO NOTHING;

-- ATD_RICO_2: Fechado −1d, externo, 2h30, Pix validado
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
  '91000000-0000-0000-0000-000000000002', 2,
  'c1000000-0000-0000-0000-000000000001',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000001',
  NULL,
  'Fechado', 'externo', 'agendado',
  (NOW() - INTERVAL '1 day')::date, '20:00', 2.5,
  'Av. Atlântica, 1702, Quarto 1404', 'Copacabana', 'hotel', 'JW Marriott — Posto 4',
  'pix', 2200.00, 2500.00, 40.00,
  NULL, NULL, 'validado',
  NULL, NULL,
  false, NULL, 'IA',
  NULL, NULL,
  'Ricardo Alves, externo, JW Marriott Copacabana. Pix de R$ 200 validado automaticamente. Encerrou com R$ 2.500.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
  'comando_grupo',
  NOW() - INTERVAL '1 day' - INTERVAL '3 hours',
  NOW() - INTERVAL '1 day' + INTERVAL '2 hours 30 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- ATD_RICO_3: Em_execucao hoje, interno, 2h (IA pausada — Alessia em atendimento)
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
  '91000000-0000-0000-0000-000000000005', NULL,
  'c1000000-0000-0000-0000-000000000001',
  'a1000000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000001',
  NULL,
  'Em_execucao', 'interno', 'imediato',
  NOW()::date, '15:00', 2.0,
  NULL, NULL, NULL, NULL,
  'dinheiro', 1500.00, NULL, 40.00,
  NULL, NULL, 'nao_solicitado',
  (NOW()::date + TIME '14:40') AT TIME ZONE 'America/Sao_Paulo',
  (NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo',
  true, 'modelo_em_atendimento', 'modelo',
  'Alessia encerrar com "finalizado [valor]" ao término.',
  'Cliente chegou (foto de portaria). Alessia em atendimento.',
  'Ricardo Alves, recorrente, interno, 2h. Chegou às 15h05. Alessia conduzindo o atendimento.',
  '{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
  'webhook_imagem',
  NOW() - INTERVAL '5 hours',
  NOW() - INTERVAL '4 hours'
)
ON CONFLICT (id) DO NOTHING;

-- === UPDATE cruzado bloqueios <-> atendimentos ===
UPDATE barravips.bloqueios
   SET atendimento_id = '91000000-0000-0000-0000-000000000001'
 WHERE id = 'b1000000-0000-0000-0000-000000000004'
   AND atendimento_id IS NULL;

UPDATE barravips.bloqueios
   SET atendimento_id = '91000000-0000-0000-0000-000000000002'
 WHERE id = 'b1000000-0000-0000-0000-000000000003'
   AND atendimento_id IS NULL;

UPDATE barravips.bloqueios
   SET atendimento_id = '91000000-0000-0000-0000-000000000005'
 WHERE id = 'b1000000-0000-0000-0000-000000000002'
   AND atendimento_id IS NULL;

UPDATE barravips.atendimentos
   SET bloqueio_id = 'b1000000-0000-0000-0000-000000000004'
 WHERE id = '91000000-0000-0000-0000-000000000001'
   AND bloqueio_id IS NULL;

UPDATE barravips.atendimentos
   SET bloqueio_id = 'b1000000-0000-0000-0000-000000000003'
 WHERE id = '91000000-0000-0000-0000-000000000002'
   AND bloqueio_id IS NULL;

UPDATE barravips.atendimentos
   SET bloqueio_id = 'b1000000-0000-0000-0000-000000000002'
 WHERE id = '91000000-0000-0000-0000-000000000005'
   AND bloqueio_id IS NULL;

-- === mensagens ===
-- IDs estáveis: 0a100000-0000-0000-0000-0000000000{NN}
-- Trigger atualiza_ultima_mensagem_em_conversa atualiza conversas automaticamente.

-- ATD_RICO_1 (−7 dias, interno)
INSERT INTO barravips.mensagens (id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at) VALUES
(
  '0a100000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000001',
  'cliente', 'texto',
  'Oi Alessia, posso ir aí hoje à noite tipo umas 18h?',
  NULL, '3EB0RICO00000001',
  NOW() - INTERVAL '7 days' - INTERVAL '2 hours'
),
(
  '0a100000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000001',
  'ia', 'texto',
  'Oi Ricardo! Pode sim, 18h está ótimo 😊 Me avisa quando estiver saindo.',
  NULL, '3EB0RICO00000002',
  NOW() - INTERVAL '7 days' - INTERVAL '1 hour 59 minutes'
),
(
  '0a100000-0000-0000-0000-000000000003',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000001',
  'cliente', 'texto',
  'Saindo agora, em 20 minutinhos estou aí.',
  NULL, '3EB0RICO00000003',
  ((NOW() - INTERVAL '7 days')::date + TIME '17:45') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0a100000-0000-0000-0000-000000000004',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000001',
  'cliente', 'imagem',
  '[foto da portaria]',
  'mensagens/f1000000-0000-0000-0000-000000000001/3EB0RICO00000004.jpg',
  '3EB0RICO00000004',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0a100000-0000-0000-0000-000000000005',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000001',
  'modelo_manual', 'texto',
  'Oi Ricardo 🌹 Pode subir, apê 301!',
  NULL, '3EB0RICO00000005',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:10') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0a100000-0000-0000-0000-000000000006',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000001',
  'modelo_manual', 'texto',
  'finalizado 1800',
  NULL, '3EB0RICO00000006',
  ((NOW() - INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- ATD_RICO_2 (−1 dia, externo, Pix)
INSERT INTO barravips.mensagens (id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at) VALUES
(
  '0a100000-0000-0000-0000-000000000007',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000002',
  'cliente', 'texto',
  'Oi Alessia, estou no JW Marriott em Copacabana. Posso te chamar para hoje à noite, umas 20h?',
  NULL, '3EB0RICO00000007',
  NOW() - INTERVAL '1 day' - INTERVAL '3 hours'
),
(
  '0a100000-0000-0000-0000-000000000008',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000002',
  'ia', 'texto',
  'Que ótima escolha, Ricardo 😍 Pode ser! Para 2h em hotel, R$ 2.500. Para confirmar, preciso do Pix de deslocamento de R$ 200 para a chave 21999990100 (Alessia Viana). Pode mandar?',
  NULL, '3EB0RICO00000008',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 58 minutes'
),
(
  '0a100000-0000-0000-0000-000000000009',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000002',
  'cliente', 'texto',
  'Mando agora.',
  NULL, '3EB0RICO00000009',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 40 minutes'
),
(
  -- MSG-010: referenciada por PIX_RICO_1
  '0a100000-0000-0000-0000-000000000010',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000002',
  'cliente', 'imagem',
  '[comprovante de Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000001/3EB0RICO00000010.jpg',
  '3EB0RICO00000010',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes'
),
(
  '0a100000-0000-0000-0000-000000000011',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000002',
  'ia', 'texto',
  'Pix confirmado ✅ Estarei aí às 20h pontualmente! Me manda o número do quarto quando eu chegar 🌸',
  NULL, '3EB0RICO00000011',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours'
),
(
  '0a100000-0000-0000-0000-000000000012',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000002',
  'cliente', 'texto',
  'Quarto 1404, pode vir.',
  NULL, '3EB0RICO00000012',
  NOW() - INTERVAL '1 day' - INTERVAL '1 hour'
),
(
  '0a100000-0000-0000-0000-000000000013',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000002',
  'modelo_manual', 'texto',
  'finalizado 2500',
  NULL, '3EB0RICO00000013',
  ((NOW() - INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- ATD_RICO_3 (hoje, interno, Em_execucao)
INSERT INTO barravips.mensagens (id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id, created_at) VALUES
(
  '0a100000-0000-0000-0000-000000000014',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000005',
  'cliente', 'texto',
  'Oi Alessia! É o Ricardo. Consigo ir aí hoje à tarde, tipo 15h. Tá bom?',
  NULL, '3EB0RICO00000014',
  NOW() - INTERVAL '5 hours'
),
(
  '0a100000-0000-0000-0000-000000000015',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000005',
  'ia', 'texto',
  'Ricardo!! Que saudade 🥰 Pode vir sim, 15h ótimo! Me avisa quando estiver saindo.',
  NULL, '3EB0RICO00000015',
  NOW() - INTERVAL '4 hours 58 minutes'
),
(
  '0a100000-0000-0000-0000-000000000016',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000005',
  'cliente', 'texto',
  'Saindo agora, em uns 20 minutos chego.',
  NULL, '3EB0RICO00000016',
  (NOW()::date + TIME '14:40') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0a100000-0000-0000-0000-000000000017',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000005',
  'cliente', 'imagem',
  '[foto da portaria]',
  'mensagens/f1000000-0000-0000-0000-000000000001/3EB0RICO00000017.jpg',
  '3EB0RICO00000017',
  (NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0a100000-0000-0000-0000-000000000018',
  'f1000000-0000-0000-0000-000000000001', '91000000-0000-0000-0000-000000000005',
  'modelo_manual', 'texto',
  'Oi amor, pode subir! Apê 301 🌸',
  NULL, '3EB0RICO00000018',
  (NOW()::date + TIME '15:07') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- === comprovantes_pix ===
-- PIX_RICO_1: Pix de R$200, validado automaticamente (ATD_RICO_2, MSG-010)
INSERT INTO barravips.comprovantes_pix (
  id, atendimento_id, mensagem_id,
  valor_extraido, chave_extraida, titular_extraido, timestamp_extraido,
  decisao_pipeline, motivo_em_revisao,
  decisao_final, decisao_final_por,
  created_at
) VALUES (
  '71000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-000000000002',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0RICO00000010'),
  200.00, '21999990100', 'Alessia Viana',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 30 minutes',
  'validado', NULL,
  NULL, NULL,
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 29 minutes'
)
ON CONFLICT (id) DO NOTHING;

-- === escaladas ===

-- ESC_RICO_1: fechada — "cliente chegou" ATD_RICO_1 (−7 dias)
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-000000000001',
  'modelo',
  'Cliente chegou (foto de portaria). Alessia em atendimento.',
  'Ricardo Alves, interno, 3h. Foto de portaria às 18h08. Alessia conduzindo.',
  'Encerrar com "finalizado [valor]" ao término.',
  '3EB0CARD00000001',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo',
  ((NOW() - INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo',
  NULL, 'grupo_coordenacao'
)
ON CONFLICT (id) DO NOTHING;

-- ESC_RICO_2: fechada — "saída confirmada" Pix validado ATD_RICO_2 (−1 dia)
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-000000000002',
  'modelo',
  'Pix de deslocamento validado automaticamente. Alessia a caminho.',
  'Ricardo Alves, externo, JW Marriott Copacabana, 20h. Pix de R$ 200 validado.',
  'Encerrar com "finalizado [valor]" ao término.',
  '3EB0CARD00000002',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours',
  ((NOW() - INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo',
  NULL, 'grupo_coordenacao'
)
ON CONFLICT (id) DO NOTHING;

-- ESC_RICO_3: aberta — "cliente chegou" ATD_RICO_3 (hoje, Em_execucao)
INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES (
  '81000000-0000-0000-0000-000000000003',
  '91000000-0000-0000-0000-000000000005',
  'modelo',
  'Cliente chegou (foto de portaria). Alessia em atendimento.',
  'Ricardo Alves, recorrente, interno. Foto de portaria às 15h05. IA pausada, Alessia conduzindo.',
  'Encerrar com "finalizado [valor]" ao término do atendimento.',
  '3EB0CARD00000003',
  (NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo',
  NULL, NULL, NULL
)
ON CONFLICT (id) DO NOTHING;

-- === eventos ===

-- E01-E11: ATD_RICO_1 (ciclo completo interno, −7 dias)
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  '0e100000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-000000000001',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '7 days' - INTERVAL '1 hour 59 minutes'
),
(
  '0e100000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-000000000001',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '7 days' - INTERVAL '1 hour 50 minutes'
),
(
  '0e100000-0000-0000-0000-000000000003',
  '91000000-0000-0000-0000-000000000001',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '7 days' - INTERVAL '1 hour 48 minutes'
),
(
  '0e100000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-000000000001',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000004","inicio":"18:00","fim":"21:00"}',
  NOW() - INTERVAL '7 days' - INTERVAL '1 hour 47 minutes'
),
(
  '0e100000-0000-0000-0000-000000000005',
  '91000000-0000-0000-0000-000000000001',
  'extracao_registrada', 'agente', 'IA',
  '{"campo":"aviso_saida_em","valor":"agora"}',
  ((NOW() - INTERVAL '7 days')::date + TIME '17:45') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000006',
  '91000000-0000-0000-0000-000000000001',
  'handoff_aberto', 'agente', 'IA',
  '{"motivo":"Cliente chegou (foto de portaria)","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"}',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000007',
  '91000000-0000-0000-0000-000000000001',
  'transicao_estado', 'agente', 'sistema',
  '{"de":"Aguardando_confirmacao","para":"Em_execucao","trigger":"foto_portaria","fonte_decisao":"webhook_imagem"}',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000008',
  '91000000-0000-0000-0000-000000000001',
  'bloqueio_estado_mudado', 'agente', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000004","de":"bloqueado","para":"em_atendimento"}',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000009',
  '91000000-0000-0000-0000-000000000001',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"comando":"finalizado 1800","valor_final":1800}',
  ((NOW() - INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000010',
  '91000000-0000-0000-0000-000000000001',
  'transicao_estado', 'grupo_coordenacao', 'modelo',
  '{"de":"Em_execucao","para":"Fechado","fonte_decisao":"comando_grupo"}',
  ((NOW() - INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000011',
  '91000000-0000-0000-0000-000000000001',
  'bloqueio_estado_mudado', 'agente', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000004","de":"em_atendimento","para":"concluido"}',
  ((NOW() - INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- E12-E24: ATD_RICO_2 (ciclo completo externo com Pix, −1 dia)
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  '0e100000-0000-0000-0000-000000000012',
  '91000000-0000-0000-0000-000000000002',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 58 minutes'
),
(
  '0e100000-0000-0000-0000-000000000013',
  '91000000-0000-0000-0000-000000000002',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 48 minutes'
),
(
  '0e100000-0000-0000-0000-000000000014',
  '91000000-0000-0000-0000-000000000002',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 45 minutes'
),
(
  '0e100000-0000-0000-0000-000000000015',
  '91000000-0000-0000-0000-000000000002',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000003","inicio":"20:00","fim":"22:30"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 44 minutes'
),
(
  '0e100000-0000-0000-0000-000000000016',
  '91000000-0000-0000-0000-000000000002',
  'pix_solicitado', 'agente', 'IA',
  '{"chave":"21999990100","valor":200}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours 43 minutes'
),
(
  '0e100000-0000-0000-0000-000000000017',
  '91000000-0000-0000-0000-000000000002',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id":"71000000-0000-0000-0000-000000000001","decisao":"validado"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours'
),
(
  '0e100000-0000-0000-0000-000000000018',
  '91000000-0000-0000-0000-000000000002',
  'handoff_aberto', 'pipeline_pix', 'sistema',
  '{"motivo":"Pix de deslocamento validado automaticamente","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours'
),
(
  '0e100000-0000-0000-0000-000000000019',
  '91000000-0000-0000-0000-000000000002',
  'transicao_estado', 'pipeline_pix', 'sistema',
  '{"de":"Aguardando_confirmacao","para":"Confirmado","fonte_decisao":"pipeline_pix"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours'
),
(
  '0e100000-0000-0000-0000-000000000020',
  '91000000-0000-0000-0000-000000000002',
  'bloqueio_estado_mudado', 'cron', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000003","de":"bloqueado","para":"em_atendimento"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000021',
  '91000000-0000-0000-0000-000000000002',
  'transicao_estado', 'cron', 'sistema',
  '{"de":"Confirmado","para":"Em_execucao","fonte_decisao":"cron_em_execucao"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000022',
  '91000000-0000-0000-0000-000000000002',
  'fechado_registrado', 'grupo_coordenacao', 'modelo',
  '{"comando":"finalizado 2500","valor_final":2500}',
  ((NOW() - INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000023',
  '91000000-0000-0000-0000-000000000002',
  'transicao_estado', 'grupo_coordenacao', 'modelo',
  '{"de":"Em_execucao","para":"Fechado","fonte_decisao":"comando_grupo"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000024',
  '91000000-0000-0000-0000-000000000002',
  'bloqueio_estado_mudado', 'agente', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000003","de":"em_atendimento","para":"concluido"}',
  ((NOW() - INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- E29-E36: ATD_RICO_3 (Em_execucao hoje, interno)
INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES
(
  '0e100000-0000-0000-0000-000000000029',
  '91000000-0000-0000-0000-000000000005',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '4 hours 58 minutes'
),
(
  '0e100000-0000-0000-0000-000000000030',
  '91000000-0000-0000-0000-000000000005',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '4 hours 50 minutes'
),
(
  '0e100000-0000-0000-0000-000000000031',
  '91000000-0000-0000-0000-000000000005',
  'transicao_estado', 'agente', 'IA',
  '{"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"}',
  NOW() - INTERVAL '4 hours 45 minutes'
),
(
  '0e100000-0000-0000-0000-000000000032',
  '91000000-0000-0000-0000-000000000005',
  'bloqueio_criado', 'agente', 'IA',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000002","inicio":"15:00","fim":"17:00"}',
  NOW() - INTERVAL '4 hours 44 minutes'
),
(
  '0e100000-0000-0000-0000-000000000033',
  '91000000-0000-0000-0000-000000000005',
  'extracao_registrada', 'agente', 'IA',
  '{"campo":"aviso_saida_em","valor":"agora"}',
  (NOW()::date + TIME '14:40') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000034',
  '91000000-0000-0000-0000-000000000005',
  'handoff_aberto', 'agente', 'IA',
  '{"motivo":"Cliente chegou (foto de portaria)","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"}',
  (NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000035',
  '91000000-0000-0000-0000-000000000005',
  'transicao_estado', 'agente', 'sistema',
  '{"de":"Aguardando_confirmacao","para":"Em_execucao","trigger":"foto_portaria","fonte_decisao":"webhook_imagem"}',
  (NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'
),
(
  '0e100000-0000-0000-0000-000000000036',
  '91000000-0000-0000-0000-000000000005',
  'bloqueio_estado_mudado', 'agente', 'sistema',
  '{"bloqueio_id":"b1000000-0000-0000-0000-000000000002","de":"bloqueado","para":"em_atendimento"}',
  (NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (id) DO NOTHING;

-- === envios_evolution ===

-- Cards no grupo de coordenação
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid, contexto, direcao, tipo,
  atendimento_id, conversa_id, payload, created_at
) VALUES
(
  'ee100000-0000-0000-0000-000000000001',
  '3EB0CARD00000001', 'evo_alessia', '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000001', NULL,
  '{"titulo":"Cliente chegou","escalada_id":"81000000-0000-0000-0000-000000000001"}',
  ((NOW() - INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  'ee100000-0000-0000-0000-000000000002',
  '3EB0CARD00000002', 'evo_alessia', '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000002', NULL,
  '{"titulo":"Saída confirmada","escalada_id":"81000000-0000-0000-0000-000000000002"}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours'
),
(
  'ee100000-0000-0000-0000-000000000003',
  '3EB0CARD00000003', 'evo_alessia', '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'card',
  '91000000-0000-0000-0000-000000000005', NULL,
  '{"titulo":"Cliente chegou","escalada_id":"81000000-0000-0000-0000-000000000003"}',
  (NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- Confirmações no grupo de coordenação
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid, contexto, direcao, tipo,
  atendimento_id, conversa_id, payload, created_at
) VALUES
(
  'ee100000-0000-0000-0000-000000000004',
  '3EB0CONF00000001', 'evo_alessia', '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'confirmacao',
  '91000000-0000-0000-0000-000000000001', NULL,
  '{"comando":"finalizado 1800","valor_final":1800}',
  ((NOW() - INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'
),
(
  'ee100000-0000-0000-0000-000000000005',
  '3EB0CONF00000002', 'evo_alessia', '120363111111111001@g.us',
  'grupo_coordenacao', 'outbound_backend', 'confirmacao',
  '91000000-0000-0000-0000-000000000002', NULL,
  '{"comando":"finalizado 2500","valor_final":2500}',
  ((NOW() - INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- Mensagens da IA na conversa do cliente (seleção representativa)
INSERT INTO barravips.envios_evolution (
  id, evolution_message_id, instance_id, remote_jid, contexto, direcao, tipo,
  atendimento_id, conversa_id, payload, created_at
) VALUES
(
  -- MSG-002: IA confirma 18h (ATD_RICO_1)
  'ee100000-0000-0000-0000-000000000006',
  '3EB0IA000000001', 'evo_alessia', '5521999990001@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001',
  '{"tipo_msg":"texto","len":61}',
  NOW() - INTERVAL '7 days' - INTERVAL '1 hour 59 minutes'
),
(
  -- MSG-011: IA confirma Pix validado (ATD_RICO_2)
  'ee100000-0000-0000-0000-000000000007',
  '3EB0IA000000002', 'evo_alessia', '5521999990001@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000002', 'f1000000-0000-0000-0000-000000000001',
  '{"tipo_msg":"texto","len":82}',
  NOW() - INTERVAL '1 day' - INTERVAL '2 hours'
),
(
  -- MSG-015: IA recebe Ricardo hoje (ATD_RICO_3)
  'ee100000-0000-0000-0000-000000000008',
  '3EB0IA000000003', 'evo_alessia', '5521999990001@s.whatsapp.net',
  'conversa_cliente', 'outbound_backend', 'ia',
  '91000000-0000-0000-0000-000000000005', 'f1000000-0000-0000-0000-000000000001',
  '{"tipo_msg":"texto","len":68}',
  NOW() - INTERVAL '4 hours 58 minutes'
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- === atendimento_servicos ===
-- Apenas atendimentos Fechado com serviço identificado
INSERT INTO barravips.atendimento_servicos (
  id, atendimento_id, programa_id, duracao_id, preco_snapshot
) VALUES
(
  '0c100000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-000000000001',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000003',
  3500.00
),
(
  '0c100000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-000000000002',
  'e0000000-0000-0000-0000-000000000003',
  'd0000000-0000-0000-0000-000000000002',
  2500.00
)
ON CONFLICT (id) DO NOTHING;

COMMIT;
