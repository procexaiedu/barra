-- 0038_seed_pix_deslocamento.sql
-- Popula a aba "Pix de deslocamento" do painel com comprovantes alinhados aos
-- atendimentos do seed 0037 (Hoje: 2026-05-13).
--
-- Cobertura:
--   - 2 pendentes (em_revisao, sem decisao_final) -> "Aguardando voce"
--   - 5 validados automaticamente (pipeline -> validado, sem decisao final)
--   - 1 validado manualmente por Fernando (em_revisao -> decisao_final=validado)
--   - 1 rejeitado por Fernando (em_revisao -> decisao_final=invalido)
--
-- Convencao de IDs:
--   mensagens (imagens do comprovante): 0a200000-...-000000XX
--   comprovantes_pix:                   72000000-...-000000XX
--   evolution_message_id:               3EB0PIXSEED00000XX
--
-- Idempotente: roda 2x sem efeito colateral.

BEGIN;

-- ========================================================================
-- AJUSTES DE PIX_STATUS NOS ATENDIMENTOS DO SEED 0037
-- Refletir o estado real do comprovante associado.
-- ========================================================================

-- a8 Felipe 17/05 -> Pix duvidoso (conta destino divergente) aguardando Fernando
UPDATE barravips.atendimentos
   SET pix_status = 'em_revisao',
       ia_pausada = true,
       ia_pausada_motivo = 'pix_em_revisao',
       responsavel_atual = 'Fernando',
       updated_at = '2026-05-13 14:02:00-03'::timestamptz
 WHERE id = '91000000-0000-0000-0000-0000000000a8'
   AND pix_status = 'aguardando';

-- b5 Renato 18/05 -> Pix duvidoso (valor abaixo) aguardando Fernando
UPDATE barravips.atendimentos
   SET pix_status = 'em_revisao',
       ia_pausada = true,
       ia_pausada_motivo = 'pix_em_revisao',
       responsavel_atual = 'Fernando',
       updated_at = '2026-05-13 10:32:00-03'::timestamptz
 WHERE id = '91000000-0000-0000-0000-0000000000b5'
   AND pix_status = 'aguardando';

-- a6 Ricardo 14/05 Pernoite -> OCR falhou, Fernando validou manualmente
UPDATE barravips.atendimentos
   SET pix_status = 'validado',
       estado = 'Confirmado',
       updated_at = '2026-05-13 11:45:00-03'::timestamptz
 WHERE id = '91000000-0000-0000-0000-0000000000a6';

-- b1 Renato 12/05 (perdido por preco) -> tinha enviado Pix R$ 80, foi rejeitado
UPDATE barravips.atendimentos
   SET pix_status = 'invalido'
 WHERE id = '91000000-0000-0000-0000-0000000000b1'
   AND pix_status = 'nao_solicitado';

-- ========================================================================
-- MENSAGENS (imagens dos comprovantes) — 1 por Pix
-- Cada mensagem vive na conversa do par (cliente, modelo).
-- ========================================================================

INSERT INTO barravips.mensagens (
  id, conversa_id, atendimento_id, direcao, tipo, conteudo,
  media_object_key, evolution_message_id, created_at
) VALUES
-- PIX 01: Felipe (Alessia) pendente — chave divergente
(
  '0a200000-0000-0000-0000-000000000001',
  'f1000000-0000-0000-0000-000000000007',
  '91000000-0000-0000-0000-0000000000a8',
  'cliente', 'imagem', '[comprovante Pix]',
  'mensagens/f1000000-0000-0000-0000-000000000007/3EB0PIXSEED0000001.jpg',
  '3EB0PIXSEED0000001',
  '2026-05-13 14:00:00-03'::timestamptz
),
-- PIX 02: Renato (Bruna) pendente — valor abaixo
(
  '0a200000-0000-0000-0000-000000000002',
  'f1000000-0000-0000-0000-000000000014',
  '91000000-0000-0000-0000-0000000000b5',
  'cliente', 'imagem', '[comprovante Pix R$ 100]',
  'mensagens/f1000000-0000-0000-0000-000000000014/3EB0PIXSEED0000002.jpg',
  '3EB0PIXSEED0000002',
  '2026-05-13 10:30:00-03'::timestamptz
),
-- PIX 03: Ricardo (Alessia) HOJE 09h — validado auto
(
  '0a200000-0000-0000-0000-000000000003',
  'f1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a2',
  'cliente', 'imagem', '[comprovante Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000001/3EB0PIXSEED0000003.jpg',
  '3EB0PIXSEED0000003',
  '2026-05-13 07:30:00-03'::timestamptz
),
-- PIX 04: Lucas (Bruna) HOJE 10h — validado auto
(
  '0a200000-0000-0000-0000-000000000004',
  'f1000000-0000-0000-0000-000000000010',
  '91000000-0000-0000-0000-0000000000b2',
  'cliente', 'imagem', '[comprovante Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000010/3EB0PIXSEED0000004.jpg',
  '3EB0PIXSEED0000004',
  '2026-05-13 08:00:00-03'::timestamptz
),
-- PIX 05: Thiago (Alessia) HOJE 19h — validado auto
(
  '0a200000-0000-0000-0000-000000000005',
  'f1000000-0000-0000-0000-000000000009',
  '91000000-0000-0000-0000-0000000000a5',
  'cliente', 'imagem', '[comprovante Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000009/3EB0PIXSEED0000005.jpg',
  '3EB0PIXSEED0000005',
  '2026-05-13 09:45:00-03'::timestamptz
),
-- PIX 06: Lucas (Bruna) 16/05 — validado auto
(
  '0a200000-0000-0000-0000-000000000006',
  'f1000000-0000-0000-0000-000000000010',
  '91000000-0000-0000-0000-0000000000b4',
  'cliente', 'imagem', '[comprovante Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000010/3EB0PIXSEED0000006.jpg',
  '3EB0PIXSEED0000006',
  '2026-05-13 09:30:00-03'::timestamptz
),
-- PIX 07: Adriano (Alessia) 19/05 — validado auto (recebido ontem 20h)
(
  '0a200000-0000-0000-0000-000000000007',
  'f1000000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-0000000000a9',
  'cliente', 'imagem', '[comprovante Pix R$ 200]',
  'mensagens/f1000000-0000-0000-0000-000000000004/3EB0PIXSEED0000007.jpg',
  '3EB0PIXSEED0000007',
  '2026-05-12 20:00:00-03'::timestamptz
),
-- PIX 08: Ricardo (Alessia) Pernoite 14/05 — OCR falhou, validado manual
(
  '0a200000-0000-0000-0000-000000000008',
  'f1000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a6',
  'cliente', 'imagem', '[comprovante Pix - imagem com baixa nitidez]',
  'mensagens/f1000000-0000-0000-0000-000000000001/3EB0PIXSEED0000008.jpg',
  '3EB0PIXSEED0000008',
  '2026-05-13 11:30:00-03'::timestamptz
),
-- PIX 09: Renato (Bruna) ontem 12/05 — rejeitado (valor errado)
(
  '0a200000-0000-0000-0000-000000000009',
  'f1000000-0000-0000-0000-000000000014',
  '91000000-0000-0000-0000-0000000000b1',
  'cliente', 'imagem', '[comprovante Pix R$ 80]',
  'mensagens/f1000000-0000-0000-0000-000000000014/3EB0PIXSEED0000009.jpg',
  '3EB0PIXSEED0000009',
  '2026-05-12 18:45:00-03'::timestamptz
)
ON CONFLICT (evolution_message_id) DO NOTHING;

-- ========================================================================
-- COMPROVANTES_PIX
-- ========================================================================

INSERT INTO barravips.comprovantes_pix (
  id, atendimento_id, mensagem_id,
  valor_extraido, chave_extraida, titular_extraido, timestamp_extraido,
  decisao_pipeline, motivo_em_revisao,
  decisao_final, decisao_final_por,
  created_at
) VALUES
-- PIX 01: Felipe a8 — em revisao (conta destino divergente)
-- Pix veio em chave de outra conta; valor e janela OK. Aguardando decisao.
(
  '72000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a8',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000001'),
  200.00, '21988887777', 'Marina Silva Santos',
  '2026-05-13 13:58:12-03'::timestamptz,
  'em_revisao', 'conta_destino_invalida',
  NULL, NULL,
  '2026-05-13 14:00:30-03'::timestamptz
),
-- PIX 02: Renato b5 — em revisao (valor divergente)
-- Cliente mandou apenas R$ 100, esperado R$ 200 (chave correta).
(
  '72000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-0000000000b5',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000002'),
  100.00, '21999990200', 'Renato Oliveira',
  '2026-05-13 10:28:45-03'::timestamptz,
  'em_revisao', 'valor_divergente',
  NULL, NULL,
  '2026-05-13 10:30:30-03'::timestamptz
),
-- PIX 03: Ricardo a2 — validado auto (recorrente, fechou hoje 09h)
(
  '72000000-0000-0000-0000-000000000003',
  '91000000-0000-0000-0000-0000000000a2',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000003'),
  200.00, '21999990100', 'Ricardo Alves',
  '2026-05-13 07:29:10-03'::timestamptz,
  'validado', NULL,
  NULL, NULL,
  '2026-05-13 07:30:15-03'::timestamptz
),
-- PIX 04: Lucas b2 — validado auto (fechou hoje 10h com Bruna)
(
  '72000000-0000-0000-0000-000000000004',
  '91000000-0000-0000-0000-0000000000b2',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000004'),
  200.00, '21999990200', 'Lucas Borges',
  '2026-05-13 07:58:40-03'::timestamptz,
  'validado', NULL,
  NULL, NULL,
  '2026-05-13 08:00:20-03'::timestamptz
),
-- PIX 05: Thiago a5 — validado auto (Confirmado hoje 19h)
(
  '72000000-0000-0000-0000-000000000005',
  '91000000-0000-0000-0000-0000000000a5',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000005'),
  200.00, '21999990100', 'Thiago Mendes',
  '2026-05-13 09:43:55-03'::timestamptz,
  'validado', NULL,
  NULL, NULL,
  '2026-05-13 09:45:18-03'::timestamptz
),
-- PIX 06: Lucas b4 — validado auto (Confirmado 16/05)
(
  '72000000-0000-0000-0000-000000000006',
  '91000000-0000-0000-0000-0000000000b4',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000006'),
  200.00, '21999990200', 'Lucas Borges',
  '2026-05-13 09:28:11-03'::timestamptz,
  'validado', NULL,
  NULL, NULL,
  '2026-05-13 09:30:25-03'::timestamptz
),
-- PIX 07: Adriano a9 — validado auto (Confirmado 19/05, enviou ontem)
(
  '72000000-0000-0000-0000-000000000007',
  '91000000-0000-0000-0000-0000000000a9',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000007'),
  200.00, '21999990100', 'Adriano Santana',
  '2026-05-12 19:58:33-03'::timestamptz,
  'validado', NULL,
  NULL, NULL,
  '2026-05-12 20:00:14-03'::timestamptz
),
-- PIX 08: Ricardo a6 Pernoite — OCR falhou, Fernando validou manualmente
(
  '72000000-0000-0000-0000-000000000008',
  '91000000-0000-0000-0000-0000000000a6',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000008'),
  NULL, '21999990100', 'Ricardo Alves',
  NULL,
  'em_revisao', 'ocr_falhou',
  'validado', '00000000-0000-0000-0000-000000000001',
  '2026-05-13 11:30:42-03'::timestamptz
),
-- PIX 09: Renato b1 — rejeitado por Fernando (valor errado)
(
  '72000000-0000-0000-0000-000000000009',
  '91000000-0000-0000-0000-0000000000b1',
  (SELECT id FROM barravips.mensagens WHERE evolution_message_id = '3EB0PIXSEED0000009'),
  80.00, '21999990200', 'Renato Oliveira',
  '2026-05-12 18:43:21-03'::timestamptz,
  'em_revisao', 'valor_divergente',
  'invalido', '00000000-0000-0000-0000-000000000001',
  '2026-05-12 18:45:09-03'::timestamptz
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- EVENTOS — timeline do detalhe Pix (pix_solicitado + pix_status_mudado)
-- ========================================================================

INSERT INTO barravips.eventos (id, atendimento_id, tipo, origem, autor, payload, created_at) VALUES

-- PIX 01: Felipe pendente
(
  '7e000000-0000-0000-0000-00000000010a',
  '91000000-0000-0000-0000-0000000000a8',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-13 10:00:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000010b',
  '91000000-0000-0000-0000-0000000000a8',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000001", "decisao": "em_revisao", "motivo": "conta_destino_invalida"}'::jsonb,
  '2026-05-13 14:00:35-03'::timestamptz
),

-- PIX 02: Renato pendente
(
  '7e000000-0000-0000-0000-00000000020a',
  '91000000-0000-0000-0000-0000000000b5',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-13 10:25:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000020b',
  '91000000-0000-0000-0000-0000000000b5',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000002", "decisao": "em_revisao", "motivo": "valor_divergente"}'::jsonb,
  '2026-05-13 10:30:35-03'::timestamptz
),

-- PIX 03: Ricardo validado auto
(
  '7e000000-0000-0000-0000-00000000030a',
  '91000000-0000-0000-0000-0000000000a2',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-13 07:20:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000030b',
  '91000000-0000-0000-0000-0000000000a2',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000003", "decisao": "validado"}'::jsonb,
  '2026-05-13 07:30:20-03'::timestamptz
),

-- PIX 04: Lucas validado auto
(
  '7e000000-0000-0000-0000-00000000040a',
  '91000000-0000-0000-0000-0000000000b2',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-13 07:50:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000040b',
  '91000000-0000-0000-0000-0000000000b2',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000004", "decisao": "validado"}'::jsonb,
  '2026-05-13 08:00:25-03'::timestamptz
),

-- PIX 05: Thiago validado auto
(
  '7e000000-0000-0000-0000-00000000050a',
  '91000000-0000-0000-0000-0000000000a5',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-13 09:40:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000050b',
  '91000000-0000-0000-0000-0000000000a5',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000005", "decisao": "validado"}'::jsonb,
  '2026-05-13 09:45:22-03'::timestamptz
),

-- PIX 06: Lucas 16/05 validado auto
(
  '7e000000-0000-0000-0000-00000000060a',
  '91000000-0000-0000-0000-0000000000b4',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-13 09:20:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000060b',
  '91000000-0000-0000-0000-0000000000b4',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000006", "decisao": "validado"}'::jsonb,
  '2026-05-13 09:30:30-03'::timestamptz
),

-- PIX 07: Adriano 19/05 validado auto (ontem 20h)
(
  '7e000000-0000-0000-0000-00000000070a',
  '91000000-0000-0000-0000-0000000000a9',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-12 19:50:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000070b',
  '91000000-0000-0000-0000-0000000000a9',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000007", "decisao": "validado"}'::jsonb,
  '2026-05-12 20:00:20-03'::timestamptz
),

-- PIX 08: Ricardo Pernoite — OCR falhou, Fernando validou manualmente
(
  '7e000000-0000-0000-0000-00000000080a',
  '91000000-0000-0000-0000-0000000000a6',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-13 11:20:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000080b',
  '91000000-0000-0000-0000-0000000000a6',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000008", "decisao": "em_revisao", "motivo": "ocr_falhou"}'::jsonb,
  '2026-05-13 11:30:50-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000080c',
  '91000000-0000-0000-0000-0000000000a6',
  'pix_status_mudado', 'painel', 'Fernando',
  '{"pix_id": "72000000-0000-0000-0000-000000000008", "decisao": "validado", "usuario_id": "00000000-0000-0000-0000-000000000001"}'::jsonb,
  '2026-05-13 11:45:00-03'::timestamptz
),

-- PIX 09: Renato ontem — rejeitado por Fernando
(
  '7e000000-0000-0000-0000-00000000090a',
  '91000000-0000-0000-0000-0000000000b1',
  'pix_solicitado', 'agente', 'IA',
  '{"valor_esperado": 200.00}'::jsonb,
  '2026-05-12 18:35:00-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000090b',
  '91000000-0000-0000-0000-0000000000b1',
  'pix_status_mudado', 'pipeline_pix', 'sistema',
  '{"pix_id": "72000000-0000-0000-0000-000000000009", "decisao": "em_revisao", "motivo": "valor_divergente"}'::jsonb,
  '2026-05-12 18:45:15-03'::timestamptz
),
(
  '7e000000-0000-0000-0000-00000000090c',
  '91000000-0000-0000-0000-0000000000b1',
  'pix_status_mudado', 'painel', 'Fernando',
  '{"pix_id": "72000000-0000-0000-0000-000000000009", "decisao": "invalido", "motivo": "valor_incorreto", "usuario_id": "00000000-0000-0000-0000-000000000001"}'::jsonb,
  '2026-05-12 19:10:00-03'::timestamptz
)
ON CONFLICT (id) DO NOTHING;

-- ========================================================================
-- ESCALADAS — cards "saida confirmada" no grupo de Coordenacao por modelo
-- para Pix validados (auto e manual). Pix em revisao gera card de Fernando
-- mas como esses ja entram na fila do painel, basta marcar o card aberto
-- para os 2 pendentes.
-- ========================================================================

INSERT INTO barravips.escaladas (
  id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
  card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal
) VALUES
-- Felipe a8 pendente — card aberto para Fernando decidir
(
  '83000000-0000-0000-0000-000000000001',
  '91000000-0000-0000-0000-0000000000a8',
  'Fernando',
  'Pix duvidoso aguardando decisao',
  'Felipe Ramos #21 17/05 21h Barra. Pix R$ 200 mas chave/titular nao bate (Marina Silva Santos / 21988887777).',
  'Aprovar ou rejeitar no painel.',
  '3EB0CARDPIX0000001',
  '2026-05-13 14:00:35-03'::timestamptz,
  NULL, NULL, NULL
),
-- Renato b5 pendente — card aberto
(
  '83000000-0000-0000-0000-000000000002',
  '91000000-0000-0000-0000-0000000000b5',
  'Fernando',
  'Pix duvidoso aguardando decisao',
  'Renato Oliveira #9 18/05 21h Leblon. Pix de R$ 100 (esperado R$ 200).',
  'Aprovar ou rejeitar no painel.',
  '3EB0CARDPIX0000002',
  '2026-05-13 10:30:35-03'::timestamptz,
  NULL, NULL, NULL
)
ON CONFLICT (id) DO NOTHING;

COMMIT;
