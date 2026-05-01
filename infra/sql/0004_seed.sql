-- =============================================================================
-- 0004_seed.sql
-- Seed completo e coerente para o MVP da operação Barra Vips.
--
-- Fontes:
--   - infra/sql/0001_schema_inicial.sql, 0002_envios_evolution.sql, 0003_realtime_crm.sql
--   - CONTEXT.md (vocabulário de domínio canônico)
--   - ata.txt (perfil de cliente, fluxos, valores, sazonalidade)
--   - docs/mvp/04-fluxos-operacionais.md, 05-escalada-regras-ia.md, 06-dados-interfaces.md
--
-- Objetivos do seed:
--   1. Popular o painel com dados realistas para que cada tela tenha algo significativo.
--   2. Cobrir TODOS os 8 estados de atendimento e os DOIS fluxos (interno/externo).
--   3. Cobrir Pix em todos os status relevantes (nao_solicitado, aguardando, validado, em_revisao).
--   4. Validar regras de domínio: handoff implícito por foto_portaria; saída confirmada por Pix;
--      sinalização de recorrência por par (cliente, modelo); isolamento entre IAs por par.
--   5. Permitir reaplicação segura: idempotente via ON CONFLICT em chaves naturais
--      (telefone, numero_whatsapp, evolution_message_id, evolution_chat_id+modelo, etc).
--
-- Decisões importantes:
--   - UUIDs determinísticos com prefixos semânticos (modelos=0e7e..., clientes=c11e...,
--     atendimentos=a7e0d..., conversas=c01f..., mensagens=0e55..., bloqueios=b10c...,
--     comprovantes_pix=c0517..., escaladas=e5ca..., eventos=e1e1..., envios=e09f...,
--     midia=e1d10..., faq=faff...). Assim re-runs preservam relacionamentos e o operador
--     reconhece a entidade pelo prefixo na inspeção.
--   - barravips.usuarios depende de auth.users (FK direta). O seed NÃO insere Fernando
--     em auth.users — isso é responsabilidade do Supabase Auth. Por isso campos
--     decisao_final_por / fechada_por ficam NULL aqui (já é semântica válida: pix
--     decidido pelo pipeline; escalada fechada por comando do grupo sem login).
--   - numero_curto é setado explicitamente para garantir determinismo. A trigger
--     gen_numero_curto() respeita NEW.numero_curto IS NOT NULL e não sobrescreve.
--   - ultima_mensagem_em / ultima_mensagem_direcao em conversas é populado pela
--     trigger atualiza_ultima_mensagem_em_conversa() AFTER INSERT em mensagens.
--   - Para atendimentos terminais (Fechado/Perdido) o bloqueio vinculado já é inserido
--     com estado coerente (concluido/cancelado), pois a trigger sync_bloqueio_estado
--     só roda em UPDATE.
--   - bloqueios_sem_sobreposicao (EXCLUDE) é satisfeito porque os intervalos ativos
--     por modelo não se sobrepõem (ver §6).
--
-- Aplicação:
--   psql "$DATABASE_URL" -f 0004_seed.sql
-- =============================================================================

SET search_path TO barravips, public;

BEGIN;


-- -----------------------------------------------------------------------------
-- 1. Modelos (3 — 2 ativas no piloto + 1 pausada por rotatividade)
-- -----------------------------------------------------------------------------
-- Stephanie: aceita interno e externo (cobre os dois fluxos da ata §2.7).
-- Alessia: só interno — usada para validar o filtro de tipo_atendimento_aceito
--          no qualificador (a IA não pode oferecer saída para essa modelo).
-- Larissa: pausada — modela rotatividade (ata §2.12).
INSERT INTO barravips.modelos
  (id, nome, idade, numero_whatsapp, evolution_instance_id, status,
   valor_padrao, percentual_repasse, chave_pix, titular_chave,
   idiomas, localizacao_operacional, tipo_atendimento_aceito)
VALUES
  ('0e7e1000-0001-7000-8000-000000000001', 'Stephanie Lima', 28,
   '+5521999990001', 'evo_stephanie',  'ativa',
   1000.00, 40.00, '21999990001', 'Stephanie Lima de Souza',
   ARRAY['pt-BR','en-US','es-ES'], 'Barra da Tijuca, Rio de Janeiro - RJ',
   ARRAY['interno','externo']::barravips.tipo_atendimento_enum[]),
  ('0e7e1000-0001-7000-8000-000000000002', 'Alessia Conti', 25,
   '+5521999990002', 'evo_alessia', 'ativa',
   1200.00, 30.00, 'alessia.conti@barravips.tld', 'Alessia Conti Pereira',
   ARRAY['pt-BR','en-US'], 'Leblon, Rio de Janeiro - RJ',
   ARRAY['interno']::barravips.tipo_atendimento_enum[]),
  ('0e7e1000-0001-7000-8000-000000000003', 'Larissa Mello', 23,
   '+5521999990003', NULL, 'pausada',
   800.00, 50.00, NULL, NULL,
   ARRAY['pt-BR'], 'Recreio dos Bandeirantes, Rio de Janeiro - RJ',
   ARRAY['interno','externo']::barravips.tipo_atendimento_enum[])
ON CONFLICT (numero_whatsapp) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 2. modelo_faq — global (modelo_id NULL) + por modelo
-- -----------------------------------------------------------------------------
-- FAQ global: respostas que valem para qualquer modelo (forma de pagamento,
-- política de pix de deslocamento, abrangência). FAQ por modelo: idiomas,
-- localização, restrições próprias.
INSERT INTO barravips.modelo_faq (id, modelo_id, pergunta, resposta, tags) VALUES
  ('faff0000-0001-7000-8000-000000000001', NULL,
   'Quais formas de pagamento são aceitas?',
   'Pix ou dinheiro presencialmente. Cartão e transferência não.',
   ARRAY['pagamento','pix','dinheiro']),
  ('faff0000-0001-7000-8000-000000000002', NULL,
   'Tem custo para a modelo se deslocar até mim?',
   'Para encontros fora, há um valor antecipado de deslocamento via Pix. Combinamos pelo chat.',
   ARRAY['saida','externo','pix','deslocamento']),
  ('faff0000-0001-7000-8000-000000000003', NULL,
   'Em quais regiões vocês atendem?',
   'Zona Sul, Barra, Recreio e regiões próximas. Posso confirmar pelo endereço exato.',
   ARRAY['area','rio','geografia']),
  ('faff0000-0001-7000-8000-000000000004',
   '0e7e1000-0001-7000-8000-000000000001',
   'Quais idiomas você fala?',
   'Português, inglês e espanhol. Conversamos no idioma que for melhor para você.',
   ARRAY['idioma','persona']),
  ('faff0000-0001-7000-8000-000000000005',
   '0e7e1000-0001-7000-8000-000000000001',
   'Você atende em hotel?',
   'Sim, atendo em hotel, flat e apartamento próprio. Me passa a região para combinarmos.',
   ARRAY['local','interno','externo']),
  ('faff0000-0001-7000-8000-000000000006',
   '0e7e1000-0001-7000-8000-000000000002',
   'Você se desloca?',
   'No momento atendo apenas em meu apartamento, em local discreto. Posso te passar a região para você confirmar.',
   ARRAY['local','interno']),
  ('faff0000-0001-7000-8000-000000000007',
   '0e7e1000-0001-7000-8000-000000000002',
   'Quais idiomas você fala?',
   'Português e inglês fluentes.',
   ARRAY['idioma','persona'])
ON CONFLICT (id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 3. modelo_midia — fotos e vídeos pré-aprovados (mín. 10 por modelo no piloto)
-- -----------------------------------------------------------------------------
-- object_key segue o padrão "modelos/<modelo_id>/<categoria>/<nome>" (bucket "media").
INSERT INTO barravips.modelo_midia (id, modelo_id, tipo, tag, bucket, object_key, aprovada) VALUES
  -- Stephanie (10 mídias: 7 fotos + 3 vídeos)
  ('e1d10000-0001-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001', 'foto',  'rosto',          'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/foto/rosto-01.jpg',     true),
  ('e1d10000-0001-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001', 'foto',  'corpo',          'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/foto/corpo-01.jpg',     true),
  ('e1d10000-0001-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000001', 'foto',  'corpo',          'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/foto/corpo-02.jpg',     true),
  ('e1d10000-0001-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000001', 'foto',  'lingerie',       'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/foto/lingerie-01.jpg',  true),
  ('e1d10000-0001-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000001', 'foto',  'lingerie',       'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/foto/lingerie-02.jpg',  true),
  ('e1d10000-0001-7000-8000-000000000006', '0e7e1000-0001-7000-8000-000000000001', 'foto',  'praia',          'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/foto/praia-01.jpg',     true),
  ('e1d10000-0001-7000-8000-000000000007', '0e7e1000-0001-7000-8000-000000000001', 'foto',  'evento',         'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/foto/evento-01.jpg',    true),
  ('e1d10000-0001-7000-8000-000000000008', '0e7e1000-0001-7000-8000-000000000001', 'video', 'visualizacao_unica', 'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/video/vu-01.mp4',   true),
  ('e1d10000-0001-7000-8000-000000000009', '0e7e1000-0001-7000-8000-000000000001', 'video', 'visualizacao_unica', 'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/video/vu-02.mp4',   true),
  ('e1d10000-0001-7000-8000-00000000000a', '0e7e1000-0001-7000-8000-000000000001', 'video', 'apresentacao',       'media', 'modelos/0e7e1000-0001-7000-8000-000000000001/video/apres-01.mp4', true),
  -- Alessia (10 mídias)
  ('e1d10000-0001-7000-8000-000000000101', '0e7e1000-0001-7000-8000-000000000002', 'foto',  'rosto',          'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/foto/rosto-01.jpg',     true),
  ('e1d10000-0001-7000-8000-000000000102', '0e7e1000-0001-7000-8000-000000000002', 'foto',  'corpo',          'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/foto/corpo-01.jpg',     true),
  ('e1d10000-0001-7000-8000-000000000103', '0e7e1000-0001-7000-8000-000000000002', 'foto',  'corpo',          'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/foto/corpo-02.jpg',     true),
  ('e1d10000-0001-7000-8000-000000000104', '0e7e1000-0001-7000-8000-000000000002', 'foto',  'lingerie',       'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/foto/lingerie-01.jpg',  true),
  ('e1d10000-0001-7000-8000-000000000105', '0e7e1000-0001-7000-8000-000000000002', 'foto',  'lingerie',       'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/foto/lingerie-02.jpg',  true),
  ('e1d10000-0001-7000-8000-000000000106', '0e7e1000-0001-7000-8000-000000000002', 'foto',  'casual',         'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/foto/casual-01.jpg',    true),
  ('e1d10000-0001-7000-8000-000000000107', '0e7e1000-0001-7000-8000-000000000002', 'foto',  'evento',         'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/foto/evento-01.jpg',    true),
  ('e1d10000-0001-7000-8000-000000000108', '0e7e1000-0001-7000-8000-000000000002', 'video', 'visualizacao_unica', 'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/video/vu-01.mp4',   true),
  ('e1d10000-0001-7000-8000-000000000109', '0e7e1000-0001-7000-8000-000000000002', 'video', 'visualizacao_unica', 'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/video/vu-02.mp4',   true),
  ('e1d10000-0001-7000-8000-00000000010a', '0e7e1000-0001-7000-8000-000000000002', 'video', 'apresentacao',       'media', 'modelos/0e7e1000-0001-7000-8000-000000000002/video/apres-01.mp4', true)
ON CONFLICT (id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 4. clientes — 8 perfis cobrindo os 4 tipos por urgência (ata §2.8)
-- -----------------------------------------------------------------------------
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id) VALUES
  -- Roberto: executivo SP em viagem ao RJ. Tipo 1 (imediato), interno → Em_execucao
  ('c11e0000-0001-7000-8000-000000000001', '+5511988887771', 'Roberto Almeida',
   '0e7e1000-0001-7000-8000-000000000001'),
  -- André: empresário, agendou para a noite. Tipo 2 (agendado), externo → Confirmado pix
  ('c11e0000-0001-7000-8000-000000000002', '+5511988887772', 'André Vasconcelos',
   '0e7e1000-0001-7000-8000-000000000001'),
  -- Marcos: cliente carioca, externo, Pix em revisão. Tipo 4 (estimado)
  ('c11e0000-0001-7000-8000-000000000003', '+5521988887773', 'Marcos Tavares',
   '0e7e1000-0001-7000-8000-000000000001'),
  -- Diego: corporativo, vai ao apartamento da Alessia. Tipo 3 (indefinido, "te aviso quando sair")
  ('c11e0000-0001-7000-8000-000000000004', '+5511988887774', 'Diego Barros',
   '0e7e1000-0001-7000-8000-000000000002'),
  -- Henrique: cliente recorrente da Alessia. Vai fechado e tem histórico fechado.
  ('c11e0000-0001-7000-8000-000000000005', '+5511988887775', 'Henrique Sampaio',
   '0e7e1000-0001-7000-8000-000000000002'),
  -- João: pediu desconto agressivo, perdido por preço (com Stephanie)
  ('c11e0000-0001-7000-8000-000000000006', '+5521988887776', 'João Marinho',
   '0e7e1000-0001-7000-8000-000000000001'),
  -- Felipe: chegou agora, conversa em Triagem com Alessia
  ('c11e0000-0001-7000-8000-000000000007', '+5511988887777', 'Felipe Cordeiro',
   '0e7e1000-0001-7000-8000-000000000002'),
  -- Pedro: chegou agora, atendimento Novo com Stephanie
  ('c11e0000-0001-7000-8000-000000000008', '+5511988887778', 'Pedro Linhares',
   '0e7e1000-0001-7000-8000-000000000001')
ON CONFLICT (telefone) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 5. conversas — uma por par (cliente, modelo). Isolamento entre IAs (CONTEXT.md).
-- -----------------------------------------------------------------------------
-- evolution_chat_id = "<telefone>@s.whatsapp.net" (formato Evolution).
-- recorrente=true só para Henrique x Alessia (par já fechou antes).
-- ultima_mensagem_em / ultima_mensagem_direcao são populados pela trigger
-- atualiza_ultima_mensagem_em_conversa em §8 conforme as mensagens entram.
INSERT INTO barravips.conversas
  (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas, ultimo_motivo_perda)
VALUES
  ('c01f0000-0001-7000-8000-000000000001', 'c11e0000-0001-7000-8000-000000000001',
   '0e7e1000-0001-7000-8000-000000000001',
   '5511988887771@s.whatsapp.net', false,
   'Cliente SP em viagem ao RJ. Hospedado no Copacabana Palace.', NULL),
  ('c01f0000-0001-7000-8000-000000000002', 'c11e0000-0001-7000-8000-000000000002',
   '0e7e1000-0001-7000-8000-000000000001',
   '5511988887772@s.whatsapp.net', false,
   'Empresário, agendou com antecedência para evento em Ipanema.', NULL),
  ('c01f0000-0001-7000-8000-000000000003', 'c11e0000-0001-7000-8000-000000000003',
   '0e7e1000-0001-7000-8000-000000000001',
   '5521988887773@s.whatsapp.net', false,
   'Carioca, pediu saída para hotel na Barra. Pix em revisão (valor abaixo do combinado).', NULL),
  ('c01f0000-0001-7000-8000-000000000004', 'c11e0000-0001-7000-8000-000000000004',
   '0e7e1000-0001-7000-8000-000000000002',
   '5511988887774@s.whatsapp.net', false,
   'Cliente novo, atendimento interno. Avisou que já vai sair de casa.', NULL),
  ('c01f0000-0001-7000-8000-000000000005', 'c11e0000-0001-7000-8000-000000000005',
   '0e7e1000-0001-7000-8000-000000000002',
   '5511988887775@s.whatsapp.net', true,
   'Cliente recorrente. 2º atendimento, gosta de horários noturnos.', NULL),
  ('c01f0000-0001-7000-8000-000000000006', 'c11e0000-0001-7000-8000-000000000006',
   '0e7e1000-0001-7000-8000-000000000001',
   '5521988887776@s.whatsapp.net', false,
   'Negociou agressivamente preço, recusou valor padrão.',
   'preco'),
  ('c01f0000-0001-7000-8000-000000000007', 'c11e0000-0001-7000-8000-000000000007',
   '0e7e1000-0001-7000-8000-000000000002',
   '5511988887777@s.whatsapp.net', false,
   'Acabou de iniciar conversa, ainda em triagem.', NULL),
  ('c01f0000-0001-7000-8000-000000000008', 'c11e0000-0001-7000-8000-000000000008',
   '0e7e1000-0001-7000-8000-000000000001',
   '5511988887778@s.whatsapp.net', false,
   'Primeira mensagem. Em Novo, IA ainda não respondeu.', NULL)
ON CONFLICT (cliente_id, modelo_id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 6. atendimentos — cobre os 8 estados + 1 histórico Fechado (recorrência)
-- -----------------------------------------------------------------------------
-- Numeração por modelo (numero_curto): Stephanie #1..#5, Alessia #1..#4.
-- A unique parcial atendimentos_um_aberto_por_par garante que não há 2 abertos
-- no mesmo par; pares com Fechado/Perdido podem ter outros atendimentos depois.
--
-- Decisões por linha:
--   #S1 Roberto: Em_execucao (interno). foto_portaria_em preenchido → handoff
--                implícito → ia_pausada=true (motivo modelo_em_atendimento).
--                bloqueio em_atendimento (b10c..001).
--   #S2 André:   Confirmado (externo). pix_status=validado → handoff implícito
--                → ia_pausada=true. bloqueio bloqueado (b10c..002, agenda futura).
--   #S3 Marcos:  Qualificado (externo). pix_status=em_revisao → ia_pausada=true
--                (motivo pix_em_revisao). escalada aberta para Fernando.
--   #S4 João:    Perdido com motivo preco. bloqueio cancelado (b10c..004).
--   #S5 Pedro:   Novo. IA ainda não respondeu. Sem bloqueio.
--   #A1 Diego:   Aguardando_confirmacao (interno). aviso_saida_em registrado,
--                mas foto_portaria_em ainda NULL → IA segue ATIVA respondendo
--                o cliente (CONTEXT.md: "Aviso de saída prepara a modelo, mas
--                a IA continua respondendo o cliente normalmente"). Sem bloqueio
--                ainda — bloqueio só nasce no Confirmado/Em_execucao.
--   #A2 Henrique (atual): Fechado, valor_final 2500, percentual snapshot 30%.
--                bloqueio concluido (b10c..006).
--   #A3 Henrique (histórico):  Fechado, valor_final 1800. bloqueio concluido
--                (b10c..007). Mostra recorrência por par.
--   #A4 Felipe:  Triagem. IA respondeu cumprimento, ainda sem qualificação.
INSERT INTO barravips.atendimentos
  (id, numero_curto, cliente_id, modelo_id, conversa_id, bloqueio_id,
   estado, tipo_atendimento, urgencia,
   data_desejada, horario_desejado, duracao_horas,
   endereco, bairro, tipo_local, referencia_local,
   forma_pagamento, valor_acordado, valor_final, percentual_repasse_snapshot,
   motivo_perda, motivo_perda_obs,
   pix_status, aviso_saida_em, foto_portaria_em,
   ia_pausada, ia_pausada_motivo,
   responsavel_atual, proxima_acao_esperada, motivo_escalada, resumo_operacional,
   sinais_qualificacao, fonte_decisao_ultima_transicao,
   created_at, updated_at)
VALUES
  -- #S1 Stephanie / Roberto — Em_execucao (interno)
  ('a7e0d000-0001-7000-8000-000000000001', 1,
   'c11e0000-0001-7000-8000-000000000001', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-000000000001', NULL,  -- FK populada após bloqueio existir (§7)
   'Em_execucao', 'interno', 'imediato',
   CURRENT_DATE, '14:00', 2,
   'Avenida Atlântica, 1702 - Copacabana', 'Copacabana', 'hotel', 'Hotel Copacabana Palace - portaria principal',
   'dinheiro', 2000.00, NULL, NULL,
   NULL, NULL,
   'nao_solicitado', NULL, now() - interval '15 minutes',
   true, 'modelo_em_atendimento',
   'modelo', 'Encerrar atendimento e registrar fechado/perdido no grupo',
   'cliente_chegou', 'Cliente Roberto chegou no Copacabana Palace às 14h, foto da portaria recebida. 2 horas combinadas.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'webhook_imagem',
   now() - interval '2 hours', now() - interval '15 minutes'),

  -- #S2 Stephanie / André — Confirmado (externo, pix validado)
  ('a7e0d000-0001-7000-8000-000000000002', 2,
   'c11e0000-0001-7000-8000-000000000002', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-000000000002', NULL,
   'Confirmado', 'externo', 'agendado',
   CURRENT_DATE, '20:00', 2,
   'Rua Vinícius de Moraes, 142 - Ipanema', 'Ipanema', 'apartamento', 'Edifício Atlas, cobertura',
   'pix', 2200.00, NULL, NULL,
   NULL, NULL,
   'validado', NULL, NULL,
   true, 'modelo_em_atendimento',
   'modelo', 'Aguardar horário combinado (20h) e seguir para o endereço',
   'pix_validado', 'Cliente André confirmado às 20h em Ipanema. Pix de deslocamento (R$ 200) validado pelo pipeline.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'pipeline_pix',
   now() - interval '4 hours', now() - interval '40 minutes'),

  -- #S3 Stephanie / Marcos — Qualificado (externo, pix em revisão)
  ('a7e0d000-0001-7000-8000-000000000003', 3,
   'c11e0000-0001-7000-8000-000000000003', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-000000000003', NULL,
   'Qualificado', 'externo', 'estimado',
   CURRENT_DATE, '22:00', 1,
   'Avenida das Américas, 4666 - Barra da Tijuca', 'Barra da Tijuca', 'hotel', 'Hotel Windsor Barra',
   'pix', 1200.00, NULL, NULL,
   NULL, NULL,
   'em_revisao', NULL, NULL,
   true, 'pix_em_revisao',
   'Fernando', 'Validar Pix recebido - valor abaixo do combinado',
   'pix_em_revisao', 'Cliente Marcos enviou Pix de R$ 150 (combinado: R$ 200 deslocamento). Pipeline rejeitou - aguarda decisão de Fernando.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'pipeline_pix',
   now() - interval '90 minutes', now() - interval '20 minutes'),

  -- #S4 Stephanie / João — Perdido (motivo preco)
  ('a7e0d000-0001-7000-8000-000000000004', 4,
   'c11e0000-0001-7000-8000-000000000006', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-000000000006', NULL,
   'Perdido', 'externo', 'imediato',
   NULL, NULL, NULL,
   NULL, 'Tijuca', NULL, NULL,
   NULL, 1000.00, NULL, NULL,
   'preco', NULL,
   'nao_solicitado', NULL, NULL,
   false, NULL,
   'IA', NULL, NULL,
   'Cliente recusou valor padrão de R$ 1000/h e pediu R$ 500. Encerrado pela IA após 3 trocas sem avanço.',
   '{"informa_horario": false, "informa_local": false, "aceita_valor": false, "envia_pix": false, "responde_objetivamente": false}'::jsonb,
   'comando_grupo',
   now() - interval '1 day' - interval '3 hours', now() - interval '1 day'),

  -- #S5 Stephanie / Pedro — Novo
  ('a7e0d000-0001-7000-8000-000000000005', 5,
   'c11e0000-0001-7000-8000-000000000008', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-000000000008', NULL,
   'Novo', NULL, NULL,
   NULL, NULL, NULL,
   NULL, NULL, NULL, NULL,
   NULL, NULL, NULL, NULL,
   NULL, NULL,
   'nao_solicitado', NULL, NULL,
   false, NULL,
   'IA', 'Responder cumprimento inicial e iniciar triagem',
   NULL, NULL,
   '{}'::jsonb,
   NULL,
   now() - interval '5 minutes', now() - interval '5 minutes'),

  -- #A1 Alessia / Diego — Aguardando_confirmacao (interno)
  -- Aviso de saída registrado, foto da portaria ainda NÃO chegou → IA segue ativa.
  ('a7e0d000-0001-7000-8000-000000000011', 1,
   'c11e0000-0001-7000-8000-000000000004', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0001-7000-8000-000000000004', NULL,
   'Aguardando_confirmacao', 'interno', 'imediato',
   CURRENT_DATE, '11:00', 1,
   'Rua Dias Ferreira, 200 - Leblon', 'Leblon', 'apartamento', 'Edifício Vista Mar, apto 1402',
   'dinheiro', 1200.00, NULL, NULL,
   NULL, NULL,
   'nao_solicitado', now() - interval '8 minutes', NULL,
   false, NULL,
   'IA', 'Aguardar foto da portaria do cliente para confirmar chegada',
   NULL,
   'Cliente Diego avisou que está saindo do trabalho. Tempo estimado de chegada: 30 min.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'extracao_ia',
   now() - interval '70 minutes', now() - interval '8 minutes'),

  -- #A2 Alessia / Henrique — Fechado (atendimento atual)
  ('a7e0d000-0001-7000-8000-000000000012', 2,
   'c11e0000-0001-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0001-7000-8000-000000000005', NULL,
   'Fechado', 'interno', 'agendado',
   CURRENT_DATE - 1, '22:00', 2,
   'Rua Dias Ferreira, 200 - Leblon', 'Leblon', 'apartamento', 'Edifício Vista Mar, apto 1402',
   'dinheiro', 2400.00, 2500.00, 30.00,
   NULL, NULL,
   'nao_solicitado', now() - interval '1 day' - interval '3 hours', now() - interval '1 day' - interval '2 hours' - interval '30 minutes',
   false, NULL,
   'Fernando', NULL, NULL,
   'Cliente recorrente Henrique. 2 horas, fechou em R$ 2500 (R$ 100 acima do combinado, gorjeta). Encerrado pela modelo via comando "finalizado 2500".',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'comando_grupo',
   now() - interval '1 day' - interval '6 hours', now() - interval '1 day'),

  -- #A3 Alessia / Henrique — Fechado (histórico, mostra recorrência por par)
  ('a7e0d000-0001-7000-8000-000000000013', 3,
   'c11e0000-0001-7000-8000-000000000005', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0001-7000-8000-000000000005', NULL,
   'Fechado', 'interno', 'agendado',
   CURRENT_DATE - 30, '21:00', 1,
   'Rua Dias Ferreira, 200 - Leblon', 'Leblon', 'apartamento', 'Edifício Vista Mar, apto 1402',
   'dinheiro', 1800.00, 1800.00, 30.00,
   NULL, NULL,
   'nao_solicitado', NULL, NULL,
   false, NULL,
   'Fernando', NULL, NULL,
   'Primeiro atendimento do par. Fechado dentro do combinado, 1 hora.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'comando_grupo',
   now() - interval '30 days', now() - interval '30 days' + interval '2 hours'),

  -- #A4 Alessia / Felipe — Triagem
  ('a7e0d000-0001-7000-8000-000000000014', 4,
   'c11e0000-0001-7000-8000-000000000007', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0001-7000-8000-000000000007', NULL,
   'Triagem', NULL, NULL,
   NULL, NULL, NULL,
   NULL, NULL, NULL, NULL,
   NULL, NULL, NULL, NULL,
   NULL, NULL,
   'nao_solicitado', NULL, NULL,
   false, NULL,
   'IA', 'Coletar tipo de atendimento (interno) e horário',
   NULL,
   NULL,
   '{}'::jsonb,
   'extracao_ia',
   now() - interval '2 minutes', now() - interval '1 minutes')
ON CONFLICT (id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 7. bloqueios — agendados/em_atendimento/concluido/cancelado SEM sobreposição ativa
-- -----------------------------------------------------------------------------
-- Constraint EXCLUDE bloqueios_sem_sobreposicao só valida estados ativos
-- ('bloqueado','em_atendimento'). Por modelo:
--   Stephanie ATIVOS: hoje 14-16 (em_atendimento) + hoje 20-22 (bloqueado) → não sobrepõem.
--   Alessia ATIVOS: nenhum (Diego ainda Aguardando_confirmacao, sem bloqueio criado).
-- Bloqueios concluido/cancelado podem ter qualquer intervalo sem violar a EXCLUDE.
INSERT INTO barravips.bloqueios
  (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao,
   created_at, updated_at)
VALUES
  -- B1: Stephanie em_atendimento (Roberto, hoje 14h-16h)
  ('b10c0000-0001-7000-8000-000000000001',
   '0e7e1000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001',
   (CURRENT_DATE + time '14:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE + time '16:00') AT TIME ZONE 'America/Sao_Paulo',
   'em_atendimento', 'ia',
   'Atendimento interno Roberto - Copacabana Palace.',
   now() - interval '2 hours', now() - interval '15 minutes'),
  -- B2: Stephanie bloqueado (André, hoje 20h-22h, agenda futura)
  ('b10c0000-0001-7000-8000-000000000002',
   '0e7e1000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000002',
   (CURRENT_DATE + time '20:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE + time '22:00') AT TIME ZONE 'America/Sao_Paulo',
   'bloqueado', 'ia',
   'Saída externa André - Ipanema. Pix validado.',
   now() - interval '4 hours', now() - interval '40 minutes'),
  -- B4: Stephanie cancelado (João perdido)
  ('b10c0000-0001-7000-8000-000000000004',
   '0e7e1000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000004',
   (CURRENT_DATE - 1 + time '21:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE - 1 + time '22:00') AT TIME ZONE 'America/Sao_Paulo',
   'cancelado', 'ia',
   'Cancelado: cliente João recusou valor.',
   now() - interval '1 day' - interval '3 hours', now() - interval '1 day'),
  -- B6: Alessia concluido (Henrique atual)
  ('b10c0000-0001-7000-8000-000000000006',
   '0e7e1000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000012',
   (CURRENT_DATE - 1 + time '22:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE - 1 + time '24:00') AT TIME ZONE 'America/Sao_Paulo',
   'concluido', 'painel_fernando',
   'Atendimento Henrique fechado (R$ 2500).',
   now() - interval '1 day' - interval '6 hours', now() - interval '1 day'),
  -- B7: Alessia concluido (Henrique histórico)
  ('b10c0000-0001-7000-8000-000000000007',
   '0e7e1000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000013',
   (CURRENT_DATE - 30 + time '21:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE - 30 + time '22:00') AT TIME ZONE 'America/Sao_Paulo',
   'concluido', 'painel_fernando',
   'Histórico - primeiro atendimento Henrique.',
   now() - interval '30 days', now() - interval '30 days' + interval '2 hours'),
  -- B8: Stephanie bloqueado manual amanhã 18h-19h (saída de salão programada pela modelo)
  ('b10c0000-0001-7000-8000-000000000008',
   '0e7e1000-0001-7000-8000-000000000001',
   NULL,
   (CURRENT_DATE + 1 + time '18:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE + 1 + time '19:00') AT TIME ZONE 'America/Sao_Paulo',
   'bloqueado', 'manual',
   'Bloqueio avulso - sessão de salão.',
   now() - interval '6 hours', now() - interval '6 hours')
ON CONFLICT (id) DO NOTHING;

-- Vincula atendimentos aos bloqueios (FK circular criada em §6 do schema).
UPDATE barravips.atendimentos
   SET bloqueio_id = 'b10c0000-0001-7000-8000-000000000001'
 WHERE id = 'a7e0d000-0001-7000-8000-000000000001'
   AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos
   SET bloqueio_id = 'b10c0000-0001-7000-8000-000000000002'
 WHERE id = 'a7e0d000-0001-7000-8000-000000000002'
   AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos
   SET bloqueio_id = 'b10c0000-0001-7000-8000-000000000004'
 WHERE id = 'a7e0d000-0001-7000-8000-000000000004'
   AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos
   SET bloqueio_id = 'b10c0000-0001-7000-8000-000000000006'
 WHERE id = 'a7e0d000-0001-7000-8000-000000000012'
   AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos
   SET bloqueio_id = 'b10c0000-0001-7000-8000-000000000007'
 WHERE id = 'a7e0d000-0001-7000-8000-000000000013'
   AND bloqueio_id IS NULL;


-- -----------------------------------------------------------------------------
-- 8. mensagens — histórico curto e realista por conversa ATIVA
-- -----------------------------------------------------------------------------
-- Conteúdo extremamente velado (CONTEXT.md / ata §2.4): nenhuma menção explícita.
-- O conteúdo do grupo de Coordenação NÃO entra aqui — vive em escaladas/eventos.
-- A trigger atualiza_ultima_mensagem_em_conversa() popula automaticamente
-- conversas.ultima_mensagem_em e ultima_mensagem_direcao.
-- evolution_message_id é UNIQUE → ON CONFLICT DO NOTHING garante idempotência.
INSERT INTO barravips.mensagens
  (id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key,
   evolution_message_id, created_at)
VALUES
  -- C1 Roberto x Stephanie (interno → Em_execucao). Sequência: cumprimento, valor,
  -- combinado, aviso de saída, foto da portaria.
  ('0e550000-0001-7000-8000-000000000001', 'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001', 'cliente', 'texto',
   'Oi, tudo bem? Vi seu perfil no anúncio.',
   NULL, 'evo_msg_S1_001', now() - interval '2 hours'),
  ('0e550000-0001-7000-8000-000000000002', 'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001', 'ia', 'texto',
   'Oi amor, tudo ótimo! E você? Me conta, é para hoje?',
   NULL, 'evo_msg_S1_002', now() - interval '2 hours' + interval '30 seconds'),
  ('0e550000-0001-7000-8000-000000000003', 'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001', 'cliente', 'texto',
   'Sim, hoje. Estou em Copacabana, posso ir até você. Quanto fica 2 horas?',
   NULL, 'evo_msg_S1_003', now() - interval '2 hours' + interval '2 minutes'),
  ('0e550000-0001-7000-8000-000000000004', 'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001', 'ia', 'texto',
   '2 horas fica R$ 2000, amor. Atendo em apartamento próprio na Barra. Posso te passar a referência.',
   NULL, 'evo_msg_S1_004', now() - interval '2 hours' + interval '3 minutes'),
  ('0e550000-0001-7000-8000-000000000005', 'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001', 'cliente', 'texto',
   'Fechado. Saio do hotel daqui 20 min.',
   NULL, 'evo_msg_S1_005', now() - interval '90 minutes'),
  ('0e550000-0001-7000-8000-000000000006', 'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001', 'ia', 'texto',
   'Perfeito, vou me preparar. Me avisa quando estiver chegando.',
   NULL, 'evo_msg_S1_006', now() - interval '90 minutes' + interval '20 seconds'),
  ('0e550000-0001-7000-8000-000000000007', 'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001', 'cliente', 'imagem',
   '',
   'mensagens/c01f0000-0001-7000-8000-000000000001/portaria-roberto.jpg',
   'evo_msg_S1_007', now() - interval '15 minutes'),

  -- C2 André x Stephanie (externo → Confirmado, pix validado)
  ('0e550000-0001-7000-8000-000000000011', 'c01f0000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000002', 'cliente', 'texto',
   'Olá, gostaria de combinar para hoje à noite, 20h. Posso ir até você?',
   NULL, 'evo_msg_S2_001', now() - interval '4 hours'),
  ('0e550000-0001-7000-8000-000000000012', 'c01f0000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000002', 'ia', 'texto',
   'Posso ir até você sim, amor. 20h em Ipanema fica perfeito. Para encontros fora há um Pix de deslocamento (R$ 200) antecipado. Topa?',
   NULL, 'evo_msg_S2_002', now() - interval '4 hours' + interval '1 minute'),
  ('0e550000-0001-7000-8000-000000000013', 'c01f0000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000002', 'cliente', 'texto',
   'Topo. Me passa a chave.',
   NULL, 'evo_msg_S2_003', now() - interval '3 hours' - interval '50 minutes'),
  ('0e550000-0001-7000-8000-000000000014', 'c01f0000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000002', 'ia', 'texto',
   'Chave Pix: 21999990001 (Stephanie Lima de Souza). Quando enviar me manda o comprovante.',
   NULL, 'evo_msg_S2_004', now() - interval '3 hours' - interval '49 minutes'),
  ('0e550000-0001-7000-8000-000000000015', 'c01f0000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000002', 'cliente', 'imagem',
   '',
   'mensagens/c01f0000-0001-7000-8000-000000000002/comprovante-andre.jpg',
   'evo_msg_S2_005', now() - interval '40 minutes'),
  ('0e550000-0001-7000-8000-000000000016', 'c01f0000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000002', 'ia', 'texto',
   'Recebido, amor! Confirmado às 20h em Ipanema.',
   NULL, 'evo_msg_S2_006', now() - interval '38 minutes'),

  -- C3 Marcos x Stephanie (externo → Qualificado, pix em revisão)
  ('0e550000-0001-7000-8000-000000000021', 'c01f0000-0001-7000-8000-000000000003',
   'a7e0d000-0001-7000-8000-000000000003', 'cliente', 'texto',
   'Oi, tudo bem? Você pode vir aqui na Barra hoje à noite?',
   NULL, 'evo_msg_S3_001', now() - interval '90 minutes'),
  ('0e550000-0001-7000-8000-000000000022', 'c01f0000-0001-7000-8000-000000000003',
   'a7e0d000-0001-7000-8000-000000000003', 'ia', 'texto',
   'Posso sim! Me passa a referência exata. Para saída tenho um Pix de deslocamento (R$ 200). Topa?',
   NULL, 'evo_msg_S3_002', now() - interval '88 minutes'),
  ('0e550000-0001-7000-8000-000000000023', 'c01f0000-0001-7000-8000-000000000003',
   'a7e0d000-0001-7000-8000-000000000003', 'cliente', 'texto',
   'Hotel Windsor Barra. Topo, me manda a chave.',
   NULL, 'evo_msg_S3_003', now() - interval '60 minutes'),
  ('0e550000-0001-7000-8000-000000000024', 'c01f0000-0001-7000-8000-000000000003',
   'a7e0d000-0001-7000-8000-000000000003', 'ia', 'texto',
   'Chave Pix: 21999990001 (Stephanie Lima de Souza).',
   NULL, 'evo_msg_S3_004', now() - interval '59 minutes'),
  ('0e550000-0001-7000-8000-000000000025', 'c01f0000-0001-7000-8000-000000000003',
   'a7e0d000-0001-7000-8000-000000000003', 'cliente', 'imagem',
   '',
   'mensagens/c01f0000-0001-7000-8000-000000000003/comprovante-marcos.jpg',
   'evo_msg_S3_005', now() - interval '20 minutes'),

  -- C4 Diego x Alessia (interno → Aguardando_confirmacao, aviso de saída registrado)
  ('0e550000-0001-7000-8000-000000000031', 'c01f0000-0001-7000-8000-000000000004',
   'a7e0d000-0001-7000-8000-000000000011', 'cliente', 'texto',
   'Boa tarde. Posso ir te ver hoje?',
   NULL, 'evo_msg_A1_001', now() - interval '70 minutes'),
  ('0e550000-0001-7000-8000-000000000032', 'c01f0000-0001-7000-8000-000000000004',
   'a7e0d000-0001-7000-8000-000000000011', 'ia', 'texto',
   'Boa tarde, amor! Pode sim. Atendo em apartamento próprio no Leblon. 1 hora R$ 1200.',
   NULL, 'evo_msg_A1_002', now() - interval '69 minutes'),
  ('0e550000-0001-7000-8000-000000000033', 'c01f0000-0001-7000-8000-000000000004',
   'a7e0d000-0001-7000-8000-000000000011', 'cliente', 'texto',
   'Fechado. Que horas posso ir?',
   NULL, 'evo_msg_A1_003', now() - interval '50 minutes'),
  ('0e550000-0001-7000-8000-000000000034', 'c01f0000-0001-7000-8000-000000000004',
   'a7e0d000-0001-7000-8000-000000000011', 'ia', 'texto',
   'Me avisa quando estiver saindo de casa que eu te mando a referência.',
   NULL, 'evo_msg_A1_004', now() - interval '49 minutes'),
  ('0e550000-0001-7000-8000-000000000035', 'c01f0000-0001-7000-8000-000000000004',
   'a7e0d000-0001-7000-8000-000000000011', 'cliente', 'texto',
   'Estou saindo agora. Devo chegar em 30 min.',
   NULL, 'evo_msg_A1_005', now() - interval '8 minutes'),
  ('0e550000-0001-7000-8000-000000000036', 'c01f0000-0001-7000-8000-000000000004',
   'a7e0d000-0001-7000-8000-000000000011', 'ia', 'texto',
   'Perfeito, vou me arrumar. Endereço: Rua Dias Ferreira, 200 - Edifício Vista Mar, apto 1402. Me manda foto da portaria quando chegar.',
   NULL, 'evo_msg_A1_006', now() - interval '7 minutes'),

  -- C5 Henrique x Alessia (Fechado atual). Conversa curta, recorrente.
  ('0e550000-0001-7000-8000-000000000041', 'c01f0000-0001-7000-8000-000000000005',
   'a7e0d000-0001-7000-8000-000000000012', 'cliente', 'texto',
   'Oi, posso aparecer hoje 22h?',
   NULL, 'evo_msg_A2_001', now() - interval '1 day' - interval '6 hours'),
  ('0e550000-0001-7000-8000-000000000042', 'c01f0000-0001-7000-8000-000000000005',
   'a7e0d000-0001-7000-8000-000000000012', 'ia', 'texto',
   'Oi amor! Pode sim. Mesmo lugar. 2 horas R$ 2400?',
   NULL, 'evo_msg_A2_002', now() - interval '1 day' - interval '6 hours' + interval '1 minute'),
  ('0e550000-0001-7000-8000-000000000043', 'c01f0000-0001-7000-8000-000000000005',
   'a7e0d000-0001-7000-8000-000000000012', 'cliente', 'texto',
   'Combinado.',
   NULL, 'evo_msg_A2_003', now() - interval '1 day' - interval '5 hours'),
  ('0e550000-0001-7000-8000-000000000044', 'c01f0000-0001-7000-8000-000000000005',
   'a7e0d000-0001-7000-8000-000000000012', 'cliente', 'imagem',
   '',
   'mensagens/c01f0000-0001-7000-8000-000000000005/portaria-henrique.jpg',
   'evo_msg_A2_004', now() - interval '1 day' - interval '2 hours' - interval '30 minutes'),

  -- C6 João x Stephanie (Perdido por preço)
  ('0e550000-0001-7000-8000-000000000051', 'c01f0000-0001-7000-8000-000000000006',
   'a7e0d000-0001-7000-8000-000000000004', 'cliente', 'texto',
   'Quanto?',
   NULL, 'evo_msg_S4_001', now() - interval '1 day' - interval '3 hours'),
  ('0e550000-0001-7000-8000-000000000052', 'c01f0000-0001-7000-8000-000000000006',
   'a7e0d000-0001-7000-8000-000000000004', 'ia', 'texto',
   '1 hora R$ 1000, amor.',
   NULL, 'evo_msg_S4_002', now() - interval '1 day' - interval '3 hours' + interval '30 seconds'),
  ('0e550000-0001-7000-8000-000000000053', 'c01f0000-0001-7000-8000-000000000006',
   'a7e0d000-0001-7000-8000-000000000004', 'cliente', 'texto',
   'Faz 500?',
   NULL, 'evo_msg_S4_003', now() - interval '1 day' - interval '3 hours' + interval '1 minute'),
  ('0e550000-0001-7000-8000-000000000054', 'c01f0000-0001-7000-8000-000000000006',
   'a7e0d000-0001-7000-8000-000000000004', 'ia', 'texto',
   'Não trabalho com esse valor, amor. R$ 1000 é o mínimo.',
   NULL, 'evo_msg_S4_004', now() - interval '1 day' - interval '3 hours' + interval '2 minutes'),

  -- C7 Felipe x Alessia (Triagem)
  ('0e550000-0001-7000-8000-000000000061', 'c01f0000-0001-7000-8000-000000000007',
   'a7e0d000-0001-7000-8000-000000000014', 'cliente', 'texto',
   'Oi.',
   NULL, 'evo_msg_A4_001', now() - interval '2 minutes'),
  ('0e550000-0001-7000-8000-000000000062', 'c01f0000-0001-7000-8000-000000000007',
   'a7e0d000-0001-7000-8000-000000000014', 'ia', 'texto',
   'Oi amor, tudo bem? Me conta, é para hoje?',
   NULL, 'evo_msg_A4_002', now() - interval '1 minute'),

  -- C8 Pedro x Stephanie (Novo - IA ainda não respondeu)
  ('0e550000-0001-7000-8000-000000000071', 'c01f0000-0001-7000-8000-000000000008',
   'a7e0d000-0001-7000-8000-000000000005', 'cliente', 'texto',
   'Boa tarde.',
   NULL, 'evo_msg_S5_001', now() - interval '5 minutes')
ON CONFLICT (evolution_message_id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 9. comprovantes_pix — pipeline OCR/vision (doc 04 §4.6/§5.6)
-- -----------------------------------------------------------------------------
-- decisao_final_por fica NULL: no seed não há usuário Fernando real em
-- auth.users. Em produção isso é preenchido via painel quando Fernando decide.
INSERT INTO barravips.comprovantes_pix
  (id, atendimento_id, mensagem_id, valor_extraido, chave_extraida,
   titular_extraido, timestamp_extraido,
   decisao_pipeline, motivo_em_revisao,
   decisao_final, decisao_final_por, created_at)
VALUES
  -- CP1: André — pipeline validou (R$ 200 = combinado, chave bate, titular bate)
  ('c0517000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000002',
   '0e550000-0001-7000-8000-000000000015',
   200.00, '21999990001', 'Stephanie Lima de Souza',
   now() - interval '40 minutes' - interval '2 minutes',
   'validado', NULL,
   'validado', NULL, now() - interval '40 minutes'),
  -- CP2: Marcos — pipeline marcou em_revisao (valor R$ 150 abaixo do combinado R$ 200)
  ('c0517000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000003',
   '0e550000-0001-7000-8000-000000000025',
   150.00, '21999990001', 'Stephanie Lima de Souza',
   now() - interval '20 minutes' - interval '1 minute',
   'em_revisao', 'Valor extraído (R$ 150) abaixo do combinado (R$ 200).',
   NULL, NULL, now() - interval '20 minutes')
ON CONFLICT (id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 10. escaladas — cards de handoff no grupo de Coordenação
-- -----------------------------------------------------------------------------
-- E1: aberta para Fernando (pix em revisão, atendimento Marcos)
-- E2: fechada (modelo confirmou via comando "finalizado 2500" no grupo)
-- E3: fechada (saída confirmada — André pix validado)
-- E4: aberta para modelo (chegada do Roberto, foto de portaria)
INSERT INTO barravips.escaladas
  (id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
   card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal)
VALUES
  ('e5ca0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000003', 'Fernando',
   'Pix em revisão',
   'Marcos enviou Pix de R$ 150 (combinado: R$ 200 deslocamento). Pipeline rejeitou. Decida validar ou invalidar.',
   'Validar ou invalidar Pix no painel ou pelo grupo (#3 valido / #3 invalido).',
   'evo_card_S3_pix_001',
   now() - interval '20 minutes', NULL, NULL, NULL),
  ('e5ca0000-0001-7000-8000-000000000002',
   'a7e0d000-0001-7000-8000-000000000012', 'modelo',
   'Atendimento concluído pela modelo via comando',
   'Henrique encerrou às 24h. Modelo confirmou "finalizado 2500" no grupo.',
   'Nenhuma — atendimento já fechado.',
   'evo_card_A2_close_001',
   now() - interval '1 day' - interval '2 hours',
   now() - interval '1 day', NULL, 'grupo_coordenacao'),
  ('e5ca0000-0001-7000-8000-000000000003',
   'a7e0d000-0001-7000-8000-000000000002', 'modelo',
   'Saída confirmada (Pix validado)',
   'Pix de R$ 200 validado pelo pipeline. Cliente André em Ipanema às 20h. IA pausada.',
   'Sair para o endereço no horário combinado. Encerrar com finalizado [valor] após o atendimento.',
   'evo_card_S2_saida_001',
   now() - interval '40 minutes', NULL, NULL, NULL),
  ('e5ca0000-0001-7000-8000-000000000004',
   'a7e0d000-0001-7000-8000-000000000001', 'modelo',
   'Cliente chegou (foto de portaria)',
   'Roberto chegou no Copacabana Palace. Foto da portaria recebida. IA pausada.',
   'Receber o cliente. Encerrar com finalizado [valor] ou perdido [motivo] após o atendimento.',
   'evo_card_S1_chegou_001',
   now() - interval '15 minutes', NULL, NULL, NULL)
ON CONFLICT (id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 11. eventos — audit log humano-legível por atendimento
-- -----------------------------------------------------------------------------
-- Cobrindo: transicao_estado, pix_solicitado, pix_status_mudado, handoff_aberto,
-- bloqueio_criado, bloqueio_estado_mudado, fechado_registrado, perdido_registrado,
-- comando_invalido (para mostrar erro no grupo).
INSERT INTO barravips.eventos
  (id, atendimento_id, tipo, origem, autor, payload, created_at)
VALUES
  -- Roberto (interno → Em_execucao)
  ('e1e10000-0001-7000-8000-000000000001', 'a7e0d000-0001-7000-8000-000000000001',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Novo", "para": "Triagem", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '2 hours' + interval '30 seconds'),
  ('e1e10000-0001-7000-8000-000000000002', 'a7e0d000-0001-7000-8000-000000000001',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Triagem", "para": "Qualificado", "fonte_decisao": "extracao_ia", "sinais": {"informa_horario": true, "informa_local": true, "aceita_valor": true}}'::jsonb,
   now() - interval '2 hours' + interval '3 minutes'),
  ('e1e10000-0001-7000-8000-000000000003', 'a7e0d000-0001-7000-8000-000000000001',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Qualificado", "para": "Aguardando_confirmacao", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '90 minutes'),
  ('e1e10000-0001-7000-8000-000000000004', 'a7e0d000-0001-7000-8000-000000000001',
   'bloqueio_criado', 'agente', 'IA',
   '{"bloqueio_id": "b10c0000-0001-7000-8000-000000000001", "inicio": "14:00", "fim": "16:00"}'::jsonb,
   now() - interval '90 minutes'),
  ('e1e10000-0001-7000-8000-000000000005', 'a7e0d000-0001-7000-8000-000000000001',
   'transicao_estado', 'agente', 'sistema',
   '{"de": "Aguardando_confirmacao", "para": "Em_execucao", "fonte_decisao": "webhook_imagem", "trigger": "foto_portaria"}'::jsonb,
   now() - interval '15 minutes'),
  ('e1e10000-0001-7000-8000-000000000006', 'a7e0d000-0001-7000-8000-000000000001',
   'handoff_aberto', 'pipeline_pix', 'sistema',
   '{"responsavel": "modelo", "motivo": "Cliente chegou (foto de portaria)", "ia_pausada_motivo": "modelo_em_atendimento"}'::jsonb,
   now() - interval '15 minutes'),
  ('e1e10000-0001-7000-8000-000000000007', 'a7e0d000-0001-7000-8000-000000000001',
   'bloqueio_estado_mudado', 'pipeline_pix', 'sistema',
   '{"bloqueio_id": "b10c0000-0001-7000-8000-000000000001", "de": "bloqueado", "para": "em_atendimento"}'::jsonb,
   now() - interval '15 minutes'),

  -- André (externo → Confirmado, pix validado)
  ('e1e10000-0001-7000-8000-000000000011', 'a7e0d000-0001-7000-8000-000000000002',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Novo", "para": "Triagem", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '4 hours' + interval '30 seconds'),
  ('e1e10000-0001-7000-8000-000000000012', 'a7e0d000-0001-7000-8000-000000000002',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Triagem", "para": "Qualificado", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '4 hours' + interval '2 minutes'),
  ('e1e10000-0001-7000-8000-000000000013', 'a7e0d000-0001-7000-8000-000000000002',
   'pix_solicitado', 'agente', 'IA',
   '{"valor": 200.00, "chave": "21999990001"}'::jsonb,
   now() - interval '4 hours' + interval '1 minute'),
  ('e1e10000-0001-7000-8000-000000000014', 'a7e0d000-0001-7000-8000-000000000002',
   'pix_status_mudado', 'pipeline_pix', 'sistema',
   '{"de": "aguardando", "para": "validado", "comprovante_id": "c0517000-0001-7000-8000-000000000001"}'::jsonb,
   now() - interval '40 minutes'),
  ('e1e10000-0001-7000-8000-000000000015', 'a7e0d000-0001-7000-8000-000000000002',
   'transicao_estado', 'pipeline_pix', 'sistema',
   '{"de": "Qualificado", "para": "Confirmado", "fonte_decisao": "pipeline_pix"}'::jsonb,
   now() - interval '40 minutes'),
  ('e1e10000-0001-7000-8000-000000000016', 'a7e0d000-0001-7000-8000-000000000002',
   'handoff_aberto', 'pipeline_pix', 'sistema',
   '{"responsavel": "modelo", "motivo": "Saída confirmada (Pix validado)", "ia_pausada_motivo": "modelo_em_atendimento"}'::jsonb,
   now() - interval '40 minutes'),
  ('e1e10000-0001-7000-8000-000000000017', 'a7e0d000-0001-7000-8000-000000000002',
   'bloqueio_criado', 'pipeline_pix', 'sistema',
   '{"bloqueio_id": "b10c0000-0001-7000-8000-000000000002", "inicio": "20:00", "fim": "22:00"}'::jsonb,
   now() - interval '40 minutes'),

  -- Marcos (externo → Qualificado, pix em revisão)
  ('e1e10000-0001-7000-8000-000000000021', 'a7e0d000-0001-7000-8000-000000000003',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Novo", "para": "Qualificado", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '88 minutes'),
  ('e1e10000-0001-7000-8000-000000000022', 'a7e0d000-0001-7000-8000-000000000003',
   'pix_solicitado', 'agente', 'IA',
   '{"valor": 200.00, "chave": "21999990001"}'::jsonb,
   now() - interval '88 minutes'),
  ('e1e10000-0001-7000-8000-000000000023', 'a7e0d000-0001-7000-8000-000000000003',
   'pix_status_mudado', 'pipeline_pix', 'sistema',
   '{"de": "aguardando", "para": "em_revisao", "comprovante_id": "c0517000-0001-7000-8000-000000000002", "motivo": "valor_abaixo_do_combinado"}'::jsonb,
   now() - interval '20 minutes'),
  ('e1e10000-0001-7000-8000-000000000024', 'a7e0d000-0001-7000-8000-000000000003',
   'handoff_aberto', 'pipeline_pix', 'sistema',
   '{"responsavel": "Fernando", "motivo": "Pix em revisão", "ia_pausada_motivo": "pix_em_revisao"}'::jsonb,
   now() - interval '20 minutes'),

  -- João (Perdido)
  ('e1e10000-0001-7000-8000-000000000031', 'a7e0d000-0001-7000-8000-000000000004',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Novo", "para": "Qualificado", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '1 day' - interval '3 hours' + interval '30 seconds'),
  ('e1e10000-0001-7000-8000-000000000032', 'a7e0d000-0001-7000-8000-000000000004',
   'perdido_registrado', 'agente', 'IA',
   '{"motivo": "preco", "valor_proposto_cliente": 500, "valor_minimo": 1000}'::jsonb,
   now() - interval '1 day'),
  ('e1e10000-0001-7000-8000-000000000033', 'a7e0d000-0001-7000-8000-000000000004',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Qualificado", "para": "Perdido", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '1 day'),
  ('e1e10000-0001-7000-8000-000000000034', 'a7e0d000-0001-7000-8000-000000000004',
   'bloqueio_estado_mudado', 'agente', 'sistema',
   '{"bloqueio_id": "b10c0000-0001-7000-8000-000000000004", "de": "bloqueado", "para": "cancelado"}'::jsonb,
   now() - interval '1 day'),

  -- Pedro (Novo) — sem eventos ainda além do nascimento
  -- Diego (interno → Aguardando_confirmacao)
  ('e1e10000-0001-7000-8000-000000000041', 'a7e0d000-0001-7000-8000-000000000011',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Novo", "para": "Triagem", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '70 minutes' + interval '30 seconds'),
  ('e1e10000-0001-7000-8000-000000000042', 'a7e0d000-0001-7000-8000-000000000011',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Triagem", "para": "Qualificado", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '69 minutes'),
  ('e1e10000-0001-7000-8000-000000000043', 'a7e0d000-0001-7000-8000-000000000011',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Qualificado", "para": "Aguardando_confirmacao", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '49 minutes'),
  ('e1e10000-0001-7000-8000-000000000044', 'a7e0d000-0001-7000-8000-000000000011',
   'extracao_registrada', 'agente', 'IA',
   '{"campo": "aviso_saida_em", "valor": "agora"}'::jsonb,
   now() - interval '8 minutes'),

  -- Henrique atual (Fechado)
  ('e1e10000-0001-7000-8000-000000000051', 'a7e0d000-0001-7000-8000-000000000012',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Novo", "para": "Aguardando_confirmacao", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '1 day' - interval '6 hours' + interval '1 minute'),
  ('e1e10000-0001-7000-8000-000000000052', 'a7e0d000-0001-7000-8000-000000000012',
   'transicao_estado', 'agente', 'sistema',
   '{"de": "Aguardando_confirmacao", "para": "Em_execucao", "fonte_decisao": "webhook_imagem", "trigger": "foto_portaria"}'::jsonb,
   now() - interval '1 day' - interval '2 hours' - interval '30 minutes'),
  ('e1e10000-0001-7000-8000-000000000053', 'a7e0d000-0001-7000-8000-000000000012',
   'fechado_registrado', 'grupo_coordenacao', 'modelo',
   '{"valor_final": 2500.00, "comando": "finalizado 2500", "fonte_decisao": "comando_grupo"}'::jsonb,
   now() - interval '1 day'),
  ('e1e10000-0001-7000-8000-000000000054', 'a7e0d000-0001-7000-8000-000000000012',
   'transicao_estado', 'grupo_coordenacao', 'modelo',
   '{"de": "Em_execucao", "para": "Fechado", "fonte_decisao": "comando_grupo"}'::jsonb,
   now() - interval '1 day'),
  ('e1e10000-0001-7000-8000-000000000055', 'a7e0d000-0001-7000-8000-000000000012',
   'bloqueio_estado_mudado', 'grupo_coordenacao', 'sistema',
   '{"bloqueio_id": "b10c0000-0001-7000-8000-000000000006", "de": "em_atendimento", "para": "concluido"}'::jsonb,
   now() - interval '1 day'),

  -- Felipe (Triagem)
  ('e1e10000-0001-7000-8000-000000000061', 'a7e0d000-0001-7000-8000-000000000014',
   'transicao_estado', 'agente', 'IA',
   '{"de": "Novo", "para": "Triagem", "fonte_decisao": "extracao_ia"}'::jsonb,
   now() - interval '1 minute'),

  -- Comando inválido no grupo (exemplo de auditoria de erro de operador)
  ('e1e10000-0001-7000-8000-000000000099', NULL,
   'comando_invalido', 'grupo_coordenacao', 'modelo',
   '{"comando": "fechado", "erro": "valor_obrigatorio", "mensagem_grupo_id": "evo_grp_err_001"}'::jsonb,
   now() - interval '1 day' - interval '5 minutes')
ON CONFLICT (id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 12. envios_evolution — outbound rastreável do backend (0002)
-- -----------------------------------------------------------------------------
-- Cobre os 5 valores de "tipo": ia, card, confirmacao, erro_comando, midia.
INSERT INTO barravips.envios_evolution
  (id, evolution_message_id, instance_id, remote_jid, contexto, direcao, tipo,
   atendimento_id, conversa_id, payload, created_at)
VALUES
  -- IA respondeu Roberto
  ('e09f0000-0001-7000-8000-000000000001', 'evo_msg_S1_006', 'evo_stephanie',
   '5511988887771@s.whatsapp.net', 'conversa_cliente', 'outbound_backend', 'ia',
   'a7e0d000-0001-7000-8000-000000000001', 'c01f0000-0001-7000-8000-000000000001',
   '{"tipo_msg": "texto", "len": 64}'::jsonb,
   now() - interval '90 minutes' + interval '20 seconds'),
  -- IA enviou mídia (foto da Stephanie) para André após pix
  ('e09f0000-0001-7000-8000-000000000002', 'evo_msg_S2_media_001', 'evo_stephanie',
   '5511988887772@s.whatsapp.net', 'conversa_cliente', 'outbound_backend', 'midia',
   'a7e0d000-0001-7000-8000-000000000002', 'c01f0000-0001-7000-8000-000000000002',
   '{"midia_id": "e1d10000-0001-7000-8000-000000000004", "tag": "lingerie", "tipo": "foto"}'::jsonb,
   now() - interval '38 minutes'),
  -- Card no grupo de Coordenação: chegada do Roberto
  ('e09f0000-0001-7000-8000-000000000003', 'evo_card_S1_chegou_001', 'evo_stephanie',
   'grupo_coord_stephanie@g.us', 'grupo_coordenacao', 'outbound_backend', 'card',
   'a7e0d000-0001-7000-8000-000000000001', NULL,
   '{"escalada_id": "e5ca0000-0001-7000-8000-000000000004", "titulo": "Cliente chegou"}'::jsonb,
   now() - interval '15 minutes'),
  -- Card no grupo: saída confirmada (André)
  ('e09f0000-0001-7000-8000-000000000004', 'evo_card_S2_saida_001', 'evo_stephanie',
   'grupo_coord_stephanie@g.us', 'grupo_coordenacao', 'outbound_backend', 'card',
   'a7e0d000-0001-7000-8000-000000000002', NULL,
   '{"escalada_id": "e5ca0000-0001-7000-8000-000000000003", "titulo": "Saída confirmada"}'::jsonb,
   now() - interval '40 minutes'),
  -- Card no grupo: pix em revisao (Marcos) — para Fernando
  ('e09f0000-0001-7000-8000-000000000005', 'evo_card_S3_pix_001', 'evo_stephanie',
   'grupo_coord_stephanie@g.us', 'grupo_coordenacao', 'outbound_backend', 'card',
   'a7e0d000-0001-7000-8000-000000000003', NULL,
   '{"escalada_id": "e5ca0000-0001-7000-8000-000000000001", "titulo": "Pix em revisão"}'::jsonb,
   now() - interval '20 minutes'),
  -- Confirmação no grupo: "fechado 2500" (Henrique)
  ('e09f0000-0001-7000-8000-000000000006', 'evo_grp_conf_001', 'evo_alessia',
   'grupo_coord_alessia@g.us', 'grupo_coordenacao', 'outbound_backend', 'confirmacao',
   'a7e0d000-0001-7000-8000-000000000012', NULL,
   '{"comando": "finalizado 2500", "valor_final": 2500.00}'::jsonb,
   now() - interval '1 day'),
  -- Erro de comando: "fechado" sem valor (exemplo de auditoria)
  ('e09f0000-0001-7000-8000-000000000007', 'evo_grp_err_001', 'evo_alessia',
   'grupo_coord_alessia@g.us', 'grupo_coordenacao', 'outbound_backend', 'erro_comando',
   NULL, NULL,
   '{"comando_recebido": "fechado", "erro": "valor_obrigatorio"}'::jsonb,
   now() - interval '1 day' - interval '5 minutes')
ON CONFLICT (evolution_message_id) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 13. Cobertura dos enums e cenários remanescentes
-- -----------------------------------------------------------------------------
-- Esta seção complementa §1..§12 cobrindo valores de enum e estados não
-- exercitados acima. Cada bloco está marcado com o(s) enum(s) que cobre.
-- Justificativa por cenário em CONTEXT.md / docs/mvp/04 e 05.
-- -----------------------------------------------------------------------------

-- 13.1 modelos — modelo_status_enum.inativa
-- Camila Marques saiu da operação (rotatividade definitiva — ata §2.12).
INSERT INTO barravips.modelos
  (id, nome, idade, numero_whatsapp, evolution_instance_id, status,
   valor_padrao, percentual_repasse, chave_pix, titular_chave,
   idiomas, localizacao_operacional, tipo_atendimento_aceito)
VALUES
  ('0e7e1000-0001-7000-8000-000000000004', 'Camila Marques', 26,
   '+5521999990004', NULL, 'inativa',
   900.00, 50.00, NULL, NULL,
   ARRAY['pt-BR'], 'São Conrado, Rio de Janeiro - RJ',
   ARRAY['interno']::barravips.tipo_atendimento_enum[])
ON CONFLICT (numero_whatsapp) DO NOTHING;


-- 13.2 clientes (8 novos para os cenários abaixo)
INSERT INTO barravips.clientes (id, telefone, nome, primeiro_contato_modelo_id) VALUES
  ('c11e0000-0001-7000-8000-000000000009', '+5511988887781', 'Bruno Mendes',     '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0001-7000-8000-00000000000a', '+5511988887782', 'Caio Brandão',     '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0001-7000-8000-00000000000b', '+5511988887783', 'Davi Carvalho',    '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0001-7000-8000-00000000000c', '+5511988887784', 'Eduardo Pires',    '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0001-7000-8000-00000000000d', '+5511988887785', 'Fabio Nogueira',   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0001-7000-8000-00000000000e', '+5511988887786', 'Gustavo Ramos',    '0e7e1000-0001-7000-8000-000000000002'),
  ('c11e0000-0001-7000-8000-00000000000f', '+5511988887787', 'Heitor Salgado',   '0e7e1000-0001-7000-8000-000000000001'),
  ('c11e0000-0001-7000-8000-000000000010', '+5511988887788', 'Igor Bittencourt', '0e7e1000-0001-7000-8000-000000000001')
ON CONFLICT (telefone) DO NOTHING;


-- 13.3 conversas (uma por par)
INSERT INTO barravips.conversas
  (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas, ultimo_motivo_perda)
VALUES
  ('c01f0000-0001-7000-8000-000000000009', 'c11e0000-0001-7000-8000-000000000009',
   '0e7e1000-0001-7000-8000-000000000001', '5511988887781@s.whatsapp.net', false,
   'Pediu saída para casa em Itanhangá. Pix solicitado mas ainda não enviado.', NULL),
  ('c01f0000-0001-7000-8000-00000000000a', 'c11e0000-0001-7000-8000-00000000000a',
   '0e7e1000-0001-7000-8000-000000000001', '5511988887782@s.whatsapp.net', false,
   'Pediu encontro em motel (tipo_local=outro). Pagamento alternativo (forma=outro).', NULL),
  ('c01f0000-0001-7000-8000-00000000000b', 'c11e0000-0001-7000-8000-00000000000b',
   '0e7e1000-0001-7000-8000-000000000001', '5511988887783@s.whatsapp.net', false,
   'Pix enviado mas pipeline e Fernando classificaram como inválido (chave divergente).',
   'outro'),
  ('c01f0000-0001-7000-8000-00000000000c', 'c11e0000-0001-7000-8000-00000000000c',
   '0e7e1000-0001-7000-8000-000000000001', '5511988887784@s.whatsapp.net', false,
   'Avisou que ia sair mas nunca enviou foto da portaria. Timeout interno após 30min.',
   'sumiu'),
  ('c01f0000-0001-7000-8000-00000000000d', 'c11e0000-0001-7000-8000-00000000000d',
   '0e7e1000-0001-7000-8000-000000000001', '5511988887785@s.whatsapp.net', false,
   'Endereço identificado em comunidade pela triagem - escalado e perdido por risco.',
   'risco'),
  ('c01f0000-0001-7000-8000-00000000000e', 'c11e0000-0001-7000-8000-00000000000e',
   '0e7e1000-0001-7000-8000-000000000002', '5511988887786@s.whatsapp.net', false,
   'Cliente tentou marcar mas todas as faixas estavam bloqueadas - perdido por indisponibilidade.',
   'indisponibilidade'),
  ('c01f0000-0001-7000-8000-00000000000f', 'c11e0000-0001-7000-8000-00000000000f',
   '0e7e1000-0001-7000-8000-000000000001', '5511988887787@s.whatsapp.net', false,
   'Pediu saída para Niterói - fora da área de operação.',
   'fora_de_area'),
  ('c01f0000-0001-7000-8000-000000000010', 'c11e0000-0001-7000-8000-000000000010',
   '0e7e1000-0001-7000-8000-000000000001', '5511988887788@s.whatsapp.net', false,
   'Comportamento ambíguo - IA pediu handoff para Fernando decidir antes de seguir.', NULL)
ON CONFLICT (cliente_id, modelo_id) DO NOTHING;


-- 13.4 atendimentos — cobre urgencia.indefinido, tipo_local.casa/outro,
-- forma_pagamento.outro, pix_status.aguardando/enviado/invalido,
-- motivo_perda.sumiu/risco/indisponibilidade/fora_de_area/outro,
-- ia_pausada_motivo.handoff_ia, fonte_decisao.painel_fernando/auto_timeout/auto_timeout_interno
INSERT INTO barravips.atendimentos
  (id, numero_curto, cliente_id, modelo_id, conversa_id, bloqueio_id,
   estado, tipo_atendimento, urgencia,
   data_desejada, horario_desejado, duracao_horas,
   endereco, bairro, tipo_local, referencia_local,
   forma_pagamento, valor_acordado, valor_final, percentual_repasse_snapshot,
   motivo_perda, motivo_perda_obs,
   pix_status, aviso_saida_em, foto_portaria_em,
   ia_pausada, ia_pausada_motivo,
   responsavel_atual, proxima_acao_esperada, motivo_escalada, resumo_operacional,
   sinais_qualificacao, fonte_decisao_ultima_transicao,
   created_at, updated_at)
VALUES
  -- #S6 Bruno — Qualificado externo. Cobre: urgencia.indefinido, tipo_local.casa,
  -- pix_status.aguardando (IA pediu Pix, cliente ainda não enviou).
  ('a7e0d000-0001-7000-8000-000000000020', 6,
   'c11e0000-0001-7000-8000-000000000009', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-000000000009', NULL,
   'Qualificado', 'externo', 'indefinido',
   NULL, NULL, 1,
   'Estrada do Itanhangá, 800 - Itanhangá', 'Itanhangá', 'casa', 'Casa branca, portão preto',
   'pix', 1200.00, NULL, NULL,
   NULL, NULL,
   'aguardando', NULL, NULL,
   false, NULL,
   'IA', 'Aguardar comprovante de Pix do cliente',
   NULL,
   'Cliente Bruno topou a saída mas não definiu horário ("te aviso quando estiver livre"). Pix de R$ 200 solicitado, sem comprovante até o momento.',
   '{"informa_horario": false, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'extracao_ia',
   now() - interval '50 minutes', now() - interval '30 minutes'),

  -- #S7 Caio — Qualificado externo. Cobre: pix_status.enviado, tipo_local.outro,
  -- forma_pagamento.outro (combinou pagamento misto).
  ('a7e0d000-0001-7000-8000-000000000021', 7,
   'c11e0000-0001-7000-8000-00000000000a', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-00000000000a', NULL,
   'Qualificado', 'externo', 'imediato',
   CURRENT_DATE, '23:00', 2,
   'Av. Niemeyer, 769 - Vidigal', 'São Conrado', 'outro', 'Motel Sky - suíte presidencial',
   'outro', 2200.00, NULL, NULL,
   NULL, NULL,
   'enviado', NULL, NULL,
   false, NULL,
   'IA', 'Aguardar pipeline OCR processar comprovante',
   NULL,
   'Cliente Caio enviou comprovante R$ 200, OCR em processamento. Pagamento do atendimento combinado em parte cartão / parte dinheiro (forma=outro).',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'extracao_ia',
   now() - interval '25 minutes', now() - interval '3 minutes'),

  -- #S8 Davi — Perdido externo. Cobre: pix_status.invalido, motivo_perda.outro
  -- + motivo_perda_obs (constraint atendimentos_motivo_outro_exige_obs).
  ('a7e0d000-0001-7000-8000-000000000022', 8,
   'c11e0000-0001-7000-8000-00000000000b', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-00000000000b', NULL,
   'Perdido', 'externo', 'agendado',
   NULL, NULL, NULL,
   NULL, 'Botafogo', 'apartamento', NULL,
   'pix', 1000.00, NULL, NULL,
   'outro', 'Pix declarado inválido pelo Fernando (chave de terceiro, suspeita de golpe).',
   'invalido', NULL, NULL,
   false, NULL,
   'Fernando', NULL, 'pix_invalido',
   'Pipeline classificou em revisão; Fernando rejeitou no painel (chave PIX divergia do titular declarado pelo cliente).',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}'::jsonb,
   'painel_fernando',
   now() - interval '4 hours', now() - interval '3 hours'),

  -- #S9 Eduardo — Perdido interno. Cobre: motivo_perda.sumiu,
  -- fonte_decisao.auto_timeout_interno (CONTEXT.md: aviso_saida sem foto_portaria
  -- em 30 min → timeout determinístico → Perdido sem mensagem ao cliente).
  ('a7e0d000-0001-7000-8000-000000000023', 9,
   'c11e0000-0001-7000-8000-00000000000c', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-00000000000c', NULL,
   'Perdido', 'interno', 'imediato',
   CURRENT_DATE - 1, '15:00', 1,
   'Rua Visconde de Pirajá, 100 - Ipanema', 'Ipanema', 'apartamento', 'Stephanie - apto piloto',
   'dinheiro', 1000.00, NULL, NULL,
   'sumiu', NULL,
   'nao_solicitado',
   now() - interval '1 day' - interval '4 hours',
   NULL,
   false, NULL,
   'IA', NULL, NULL,
   'Eduardo avisou saída mas nunca enviou foto da portaria. Timeout determinístico de 30min disparado pelo cron. Sem mensagem ao cliente.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'auto_timeout_interno',
   now() - interval '1 day' - interval '5 hours', now() - interval '1 day' - interval '4 hours' + interval '30 minutes'),

  -- #S10 Fabio — Perdido externo. Cobre: motivo_perda.risco,
  -- fonte_decisao.painel_fernando (Fernando decidiu via painel após escalada).
  ('a7e0d000-0001-7000-8000-000000000024', 10,
   'c11e0000-0001-7000-8000-00000000000d', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-00000000000d', NULL,
   'Perdido', 'externo', 'imediato',
   NULL, NULL, NULL,
   'Rua Cerqueira Lima - Complexo do Alemão', 'Complexo do Alemão', 'casa', NULL,
   NULL, NULL, NULL, NULL,
   'risco', NULL,
   'nao_solicitado', NULL, NULL,
   false, NULL,
   'Fernando', NULL, 'endereco_em_comunidade',
   'Triagem identificou comunidade. Escalado para Fernando, que rejeitou o atendimento e fechou como risco no painel.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'painel_fernando',
   now() - interval '6 hours', now() - interval '5 hours'),

  -- #A5 Gustavo — Perdido interno (com Alessia). Cobre: motivo_perda.indisponibilidade.
  ('a7e0d000-0001-7000-8000-000000000025', 5,
   'c11e0000-0001-7000-8000-00000000000e', '0e7e1000-0001-7000-8000-000000000002',
   'c01f0000-0001-7000-8000-00000000000e', NULL,
   'Perdido', 'interno', 'agendado',
   CURRENT_DATE - 1, '22:00', 2,
   NULL, 'Leblon', 'apartamento', NULL,
   'dinheiro', 2400.00, NULL, NULL,
   'indisponibilidade', NULL,
   'nao_solicitado', NULL, NULL,
   false, NULL,
   'IA', NULL, NULL,
   'Gustavo tentou marcar 22h-24h mas a faixa já estava bloqueada para Henrique. IA ofereceu outras opções, cliente declinou.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'extracao_ia',
   now() - interval '1 day' - interval '8 hours', now() - interval '1 day' - interval '7 hours'),

  -- #S11 Heitor — Perdido externo. Cobre: motivo_perda.fora_de_area, fonte_decisao.auto_timeout.
  ('a7e0d000-0001-7000-8000-000000000026', 11,
   'c11e0000-0001-7000-8000-00000000000f', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-00000000000f', NULL,
   'Perdido', 'externo', 'estimado',
   NULL, NULL, NULL,
   'Rua Tavares de Macedo, 50 - Icaraí', 'Icaraí - Niterói', 'apartamento', NULL,
   NULL, NULL, NULL, NULL,
   'fora_de_area', NULL,
   'nao_solicitado', NULL, NULL,
   false, NULL,
   'IA', NULL, NULL,
   'Heitor pediu saída para Niterói. Filtro de área rejeitou; IA encerrou educadamente. Cron de timeout fechou após cliente não responder em 2h.',
   '{"informa_horario": false, "informa_local": true, "aceita_valor": false, "envia_pix": false, "responde_objetivamente": true}'::jsonb,
   'auto_timeout',
   now() - interval '12 hours', now() - interval '10 hours'),

  -- #S12 Igor — Qualificado externo. Cobre: ia_pausada_motivo.handoff_ia
  -- (IA decidiu pausar para Fernando antes de prosseguir).
  ('a7e0d000-0001-7000-8000-000000000027', 12,
   'c11e0000-0001-7000-8000-000000000010', '0e7e1000-0001-7000-8000-000000000001',
   'c01f0000-0001-7000-8000-000000000010', NULL,
   'Qualificado', 'externo', 'imediato',
   CURRENT_DATE, '21:00', 1,
   'Rua Aristides Espínola, 88 - Leblon', 'Leblon', 'hotel', 'Ritz Plaza',
   'pix', 1200.00, NULL, NULL,
   NULL, NULL,
   'nao_solicitado', NULL, NULL,
   true, 'handoff_ia',
   'Fernando', 'Decidir se prossegue ou recusa - cliente fez perguntas ambíguas sobre acompanhantes',
   'comportamento_ambiguo',
   'IA detectou perguntas que extrapolam o roteiro (validação cruzada de identidade da modelo, insistência em informações pessoais). Pausada para Fernando avaliar antes de prosseguir.',
   '{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": false}'::jsonb,
   'extracao_ia',
   now() - interval '40 minutes', now() - interval '15 minutes')
ON CONFLICT (id) DO NOTHING;


-- 13.5 bloqueios — cobre origem_bloqueio_enum.painel_fernando + estado.cancelado
-- de Perdido (Gustavo). Indisponibilidade não gera bloqueio próprio, mas o
-- bloqueio do Henrique (b10c..006) é o que conflitou — já existe.
-- Aqui criamos 1 cancelado para Davi (Pix invalidado pelo painel) e
-- 1 cancelado pra Eduardo (timeout interno fechou bloqueio que existia).
INSERT INTO barravips.bloqueios
  (id, modelo_id, atendimento_id, inicio, fim, estado, origem, observacao,
   created_at, updated_at)
VALUES
  ('b10c0000-0001-7000-8000-000000000022',
   '0e7e1000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000022',
   (CURRENT_DATE + 1 + time '21:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE + 1 + time '22:00') AT TIME ZONE 'America/Sao_Paulo',
   'cancelado', 'painel_fernando',
   'Cancelado: Pix de Davi rejeitado pelo Fernando como inválido.',
   now() - interval '4 hours', now() - interval '3 hours'),
  ('b10c0000-0001-7000-8000-000000000023',
   '0e7e1000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000023',
   (CURRENT_DATE - 1 + time '15:00') AT TIME ZONE 'America/Sao_Paulo',
   (CURRENT_DATE - 1 + time '16:00') AT TIME ZONE 'America/Sao_Paulo',
   'cancelado', 'ia',
   'Cancelado: timeout interno (aviso de saída sem foto da portaria em 30min).',
   now() - interval '1 day' - interval '5 hours', now() - interval '1 day' - interval '4 hours' + interval '30 minutes')
ON CONFLICT (id) DO NOTHING;

UPDATE barravips.atendimentos
   SET bloqueio_id = 'b10c0000-0001-7000-8000-000000000022'
 WHERE id = 'a7e0d000-0001-7000-8000-000000000022'
   AND bloqueio_id IS NULL;
UPDATE barravips.atendimentos
   SET bloqueio_id = 'b10c0000-0001-7000-8000-000000000023'
 WHERE id = 'a7e0d000-0001-7000-8000-000000000023'
   AND bloqueio_id IS NULL;


-- 13.6 mensagens — cobre direcao_mensagem_enum.modelo_manual e tipo_mensagem_enum.audio
-- modelo_manual: na conversa de Roberto (IA pausada, modelo respondeu pelo painel).
-- audio: cliente Bruno enviou áudio descrevendo o que quer (entra como tipo audio
-- com object_key obrigatório pelo CHECK mensagens_midia_exige_object_key).
INSERT INTO barravips.mensagens
  (id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key,
   evolution_message_id, created_at)
VALUES
  ('0e550000-0001-7000-8000-000000000080',
   'c01f0000-0001-7000-8000-000000000001',
   'a7e0d000-0001-7000-8000-000000000001',
   'modelo_manual', 'texto',
   'Pode subir, amor. Apto 1502.', NULL,
   'evo_msg_S1_modelo_001', now() - interval '14 minutes'),
  ('0e550000-0001-7000-8000-000000000090',
   'c01f0000-0001-7000-8000-000000000009',
   'a7e0d000-0001-7000-8000-000000000020',
   'cliente', 'audio',
   '', 'mensagens/c01f0000-0001-7000-8000-000000000009/audio-bruno-001.ogg',
   'evo_msg_S6_001', now() - interval '50 minutes')
ON CONFLICT (evolution_message_id) DO NOTHING;


-- 13.7 comprovantes_pix — cobre decisao_final_pix_enum.invalido
-- Atendimento Davi: pipeline em_revisao + Fernando rejeitou (decisao_final=invalido).
-- mensagem_id aponta para uma mensagem nova (comprovante enviado pelo cliente Davi).
INSERT INTO barravips.mensagens
  (id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key,
   evolution_message_id, created_at)
VALUES
  ('0e550000-0001-7000-8000-0000000000a0',
   'c01f0000-0001-7000-8000-00000000000b',
   'a7e0d000-0001-7000-8000-000000000022',
   'cliente', 'imagem',
   '', 'mensagens/c01f0000-0001-7000-8000-00000000000b/comprovante-davi.jpg',
   'evo_msg_S8_001', now() - interval '4 hours' + interval '10 minutes')
ON CONFLICT (evolution_message_id) DO NOTHING;

INSERT INTO barravips.comprovantes_pix
  (id, atendimento_id, mensagem_id, valor_extraido, chave_extraida,
   titular_extraido, timestamp_extraido,
   decisao_pipeline, motivo_em_revisao,
   decisao_final, decisao_final_por, created_at)
VALUES
  ('c0517000-0001-7000-8000-000000000003',
   'a7e0d000-0001-7000-8000-000000000022',
   '0e550000-0001-7000-8000-0000000000a0',
   200.00, 'chave-divergente@example.com', 'Outro Titular Divergente',
   now() - interval '4 hours' + interval '5 minutes',
   'em_revisao', 'Titular do comprovante diverge do titular declarado pelo cliente.',
   'invalido', NULL, now() - interval '4 hours' + interval '12 minutes')
ON CONFLICT (id) DO NOTHING;


-- 13.8 escaladas — cobre escalada_canal_enum.painel e .pipeline_pix
INSERT INTO barravips.escaladas
  (id, atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada,
   card_message_id, aberta_em, fechada_em, fechada_por, fechada_canal)
VALUES
  -- ESC5: handoff_ia em Igor → aberta para Fernando
  ('e5ca0000-0001-7000-8000-000000000005',
   'a7e0d000-0001-7000-8000-000000000027', 'Fernando',
   'Handoff por decisão da IA',
   'Cliente Igor fez perguntas ambíguas sobre identidade da modelo. IA solicitou avaliação de Fernando antes de prosseguir.',
   'Decidir se segue, recusa ou ajusta o roteiro pelo painel.',
   'evo_card_S12_handoff_001',
   now() - interval '15 minutes', NULL, NULL, NULL),
  -- ESC6: risco em Fabio → fechada via PAINEL (canal=painel)
  ('e5ca0000-0001-7000-8000-000000000006',
   'a7e0d000-0001-7000-8000-000000000024', 'Fernando',
   'Endereço em comunidade (risco)',
   'Triagem identificou comunidade. Endereço incompatível com mapa de áreas seguras de Fernando.',
   'Avaliar e encerrar como risco.',
   'evo_card_S10_risco_001',
   now() - interval '6 hours' + interval '15 minutes',
   now() - interval '5 hours', NULL, 'painel'),
  -- ESC7: pix invalido em Davi → fechada via PIPELINE_PIX (canal=pipeline_pix)
  ('e5ca0000-0001-7000-8000-000000000007',
   'a7e0d000-0001-7000-8000-000000000022', 'Fernando',
   'Pix em revisão (titular divergente)',
   'Comprovante enviado em nome de outro titular. Suspeita de golpe.',
   'Validar/invalidar no fluxo do pipeline.',
   'evo_card_S8_pix_001',
   now() - interval '4 hours' + interval '15 minutes',
   now() - interval '3 hours', NULL, 'pipeline_pix')
ON CONFLICT (id) DO NOTHING;


-- 13.9 eventos — cobre tipo_evento_enum.devolucao_para_ia, .correcao_registro,
-- e fonte_decisao.cron_em_execucao.
INSERT INTO barravips.eventos
  (id, atendimento_id, tipo, origem, autor, payload, created_at)
VALUES
  -- Bruno (pix aguardando)
  ('e1e10000-0001-7000-8000-000000000071', 'a7e0d000-0001-7000-8000-000000000020',
   'pix_solicitado', 'agente', 'IA',
   '{"valor": 200.00, "chave": "21999990001"}'::jsonb,
   now() - interval '30 minutes'),

  -- Caio (pix enviado)
  ('e1e10000-0001-7000-8000-000000000072', 'a7e0d000-0001-7000-8000-000000000021',
   'pix_status_mudado', 'pipeline_pix', 'sistema',
   '{"de": "aguardando", "para": "enviado"}'::jsonb,
   now() - interval '3 minutes'),

  -- Davi (pix invalido) — decisão via painel + transição pra Perdido
  ('e1e10000-0001-7000-8000-000000000073', 'a7e0d000-0001-7000-8000-000000000022',
   'pix_status_mudado', 'painel', 'Fernando',
   '{"de": "em_revisao", "para": "invalido", "comprovante_id": "c0517000-0001-7000-8000-000000000003"}'::jsonb,
   now() - interval '3 hours'),
  ('e1e10000-0001-7000-8000-000000000074', 'a7e0d000-0001-7000-8000-000000000022',
   'transicao_estado', 'painel', 'Fernando',
   '{"de": "Qualificado", "para": "Perdido", "fonte_decisao": "painel_fernando"}'::jsonb,
   now() - interval '3 hours'),
  ('e1e10000-0001-7000-8000-000000000075', 'a7e0d000-0001-7000-8000-000000000022',
   'perdido_registrado', 'painel', 'Fernando',
   '{"motivo": "outro", "obs": "Pix declarado inválido pelo Fernando"}'::jsonb,
   now() - interval '3 hours'),
  ('e1e10000-0001-7000-8000-000000000076', 'a7e0d000-0001-7000-8000-000000000022',
   'bloqueio_estado_mudado', 'painel', 'sistema',
   '{"bloqueio_id": "b10c0000-0001-7000-8000-000000000022", "de": "bloqueado", "para": "cancelado"}'::jsonb,
   now() - interval '3 hours'),

  -- Eduardo (timeout interno) — fonte_decisao auto_timeout_interno
  ('e1e10000-0001-7000-8000-000000000077', 'a7e0d000-0001-7000-8000-000000000023',
   'extracao_registrada', 'agente', 'IA',
   '{"campo": "aviso_saida_em", "valor": "agora"}'::jsonb,
   now() - interval '1 day' - interval '4 hours'),
  ('e1e10000-0001-7000-8000-000000000078', 'a7e0d000-0001-7000-8000-000000000023',
   'transicao_estado', 'cron', 'sistema',
   '{"de": "Aguardando_confirmacao", "para": "Perdido", "fonte_decisao": "auto_timeout_interno", "trigger": "30min_sem_foto_portaria"}'::jsonb,
   now() - interval '1 day' - interval '4 hours' + interval '30 minutes'),
  ('e1e10000-0001-7000-8000-000000000079', 'a7e0d000-0001-7000-8000-000000000023',
   'perdido_registrado', 'cron', 'sistema',
   '{"motivo": "sumiu", "fonte_decisao": "auto_timeout_interno"}'::jsonb,
   now() - interval '1 day' - interval '4 hours' + interval '30 minutes'),
  ('e1e10000-0001-7000-8000-00000000007a', 'a7e0d000-0001-7000-8000-000000000023',
   'bloqueio_estado_mudado', 'cron', 'sistema',
   '{"bloqueio_id": "b10c0000-0001-7000-8000-000000000023", "de": "bloqueado", "para": "cancelado"}'::jsonb,
   now() - interval '1 day' - interval '4 hours' + interval '30 minutes'),

  -- Fabio (risco) — fonte_decisao painel_fernando
  ('e1e10000-0001-7000-8000-00000000007b', 'a7e0d000-0001-7000-8000-000000000024',
   'handoff_aberto', 'agente', 'IA',
   '{"responsavel": "Fernando", "motivo": "endereço em comunidade", "ia_pausada_motivo": "handoff_ia"}'::jsonb,
   now() - interval '6 hours' + interval '15 minutes'),
  ('e1e10000-0001-7000-8000-00000000007c', 'a7e0d000-0001-7000-8000-000000000024',
   'transicao_estado', 'painel', 'Fernando',
   '{"de": "Qualificado", "para": "Perdido", "fonte_decisao": "painel_fernando"}'::jsonb,
   now() - interval '5 hours'),
  ('e1e10000-0001-7000-8000-00000000007d', 'a7e0d000-0001-7000-8000-000000000024',
   'perdido_registrado', 'painel', 'Fernando',
   '{"motivo": "risco"}'::jsonb,
   now() - interval '5 hours'),

  -- Gustavo (indisponibilidade)
  ('e1e10000-0001-7000-8000-00000000007e', 'a7e0d000-0001-7000-8000-000000000025',
   'perdido_registrado', 'agente', 'IA',
   '{"motivo": "indisponibilidade", "horario_solicitado": "22:00", "conflito_bloqueio_id": "b10c0000-0001-7000-8000-000000000006"}'::jsonb,
   now() - interval '1 day' - interval '7 hours'),

  -- Heitor (fora_de_area + auto_timeout)
  ('e1e10000-0001-7000-8000-00000000007f', 'a7e0d000-0001-7000-8000-000000000026',
   'transicao_estado', 'cron', 'sistema',
   '{"de": "Qualificado", "para": "Perdido", "fonte_decisao": "auto_timeout"}'::jsonb,
   now() - interval '10 hours'),
  ('e1e10000-0001-7000-8000-000000000080', 'a7e0d000-0001-7000-8000-000000000026',
   'perdido_registrado', 'cron', 'sistema',
   '{"motivo": "fora_de_area", "fonte_decisao": "auto_timeout"}'::jsonb,
   now() - interval '10 hours'),

  -- Igor (handoff_ia)
  ('e1e10000-0001-7000-8000-000000000081', 'a7e0d000-0001-7000-8000-000000000027',
   'handoff_aberto', 'agente', 'IA',
   '{"responsavel": "Fernando", "motivo": "comportamento_ambiguo", "ia_pausada_motivo": "handoff_ia"}'::jsonb,
   now() - interval '15 minutes'),

  -- DEVOLUCAO_PARA_IA: Fernando devolveu o atendimento de Igor para a IA seguir
  -- (cenário hipotético registrado para auditoria, mas mantemos o estado atual
  -- como Qualificado/handoff_ia para fins de demo).
  ('e1e10000-0001-7000-8000-000000000082', 'a7e0d000-0001-7000-8000-000000000027',
   'devolucao_para_ia', 'painel', 'Fernando',
   '{"motivo": "Fernando avaliou e autorizou IA a seguir", "canal": "painel"}'::jsonb,
   now() - interval '5 minutes'),

  -- CORRECAO_REGISTRO: Fernando corrigiu valor_final do atendimento Henrique
  -- (cenário previsto em CONTEXT.md: "Correção de Registro de resultado por Fernando
  -- recalcula financeiro"). Apenas registro de auditoria; valor real mantido em A2.
  ('e1e10000-0001-7000-8000-000000000083', 'a7e0d000-0001-7000-8000-000000000012',
   'correcao_registro', 'painel', 'Fernando',
   '{"campo": "valor_final", "de": 2400.00, "para": 2500.00, "motivo": "Cliente acrescentou gorjeta - valor confirmado pela modelo via áudio."}'::jsonb,
   now() - interval '20 hours'),

  -- CRON_EM_EXECUCAO: cron periódico verificou atendimentos Em_execucao
  -- (não muda estado, só registra que o cron rodou — útil para SLO/observabilidade).
  ('e1e10000-0001-7000-8000-000000000084', 'a7e0d000-0001-7000-8000-000000000001',
   'extracao_registrada', 'cron', 'sistema',
   '{"check": "duracao_em_execucao_dentro_do_combinado", "fonte_decisao": "cron_em_execucao", "decorrido_minutos": 105, "limite_minutos": 120}'::jsonb,
   now() - interval '15 minutes')
ON CONFLICT (id) DO NOTHING;


-- 13.10 envios_evolution — cards adicionais para os cenários novos
INSERT INTO barravips.envios_evolution
  (id, evolution_message_id, instance_id, remote_jid, contexto, direcao, tipo,
   atendimento_id, conversa_id, payload, created_at)
VALUES
  -- Card no grupo: handoff_ia (Igor)
  ('e09f0000-0001-7000-8000-000000000020', 'evo_card_S12_handoff_001', 'evo_stephanie',
   'grupo_coord_stephanie@g.us', 'grupo_coordenacao', 'outbound_backend', 'card',
   'a7e0d000-0001-7000-8000-000000000027', NULL,
   '{"escalada_id": "e5ca0000-0001-7000-8000-000000000005", "titulo": "Handoff IA - cliente ambíguo"}'::jsonb,
   now() - interval '15 minutes'),
  -- Card: risco (Fabio)
  ('e09f0000-0001-7000-8000-000000000021', 'evo_card_S10_risco_001', 'evo_stephanie',
   'grupo_coord_stephanie@g.us', 'grupo_coordenacao', 'outbound_backend', 'card',
   'a7e0d000-0001-7000-8000-000000000024', NULL,
   '{"escalada_id": "e5ca0000-0001-7000-8000-000000000006", "titulo": "Risco - endereço em comunidade"}'::jsonb,
   now() - interval '6 hours' + interval '15 minutes'),
  -- Card: pix invalido (Davi)
  ('e09f0000-0001-7000-8000-000000000022', 'evo_card_S8_pix_001', 'evo_stephanie',
   'grupo_coord_stephanie@g.us', 'grupo_coordenacao', 'outbound_backend', 'card',
   'a7e0d000-0001-7000-8000-000000000022', NULL,
   '{"escalada_id": "e5ca0000-0001-7000-8000-000000000007", "titulo": "Pix em revisão"}'::jsonb,
   now() - interval '4 hours' + interval '15 minutes'),
  -- Mensagem manual da modelo (rastreabilidade do envio pelo painel)
  ('e09f0000-0001-7000-8000-000000000023', 'evo_msg_S1_modelo_001', 'evo_stephanie',
   '5511988887771@s.whatsapp.net', 'conversa_cliente', 'outbound_backend', 'ia',
   'a7e0d000-0001-7000-8000-000000000001', 'c01f0000-0001-7000-8000-000000000001',
   '{"origem_painel": true, "obs": "Envio manual da modelo via painel - rastreado para distinguir IA vs modelo"}'::jsonb,
   now() - interval '14 minutes'),
  -- Confirmação no grupo: devolução para IA (Igor)
  ('e09f0000-0001-7000-8000-000000000024', 'evo_grp_devolucao_001', 'evo_stephanie',
   'grupo_coord_stephanie@g.us', 'grupo_coordenacao', 'outbound_backend', 'confirmacao',
   'a7e0d000-0001-7000-8000-000000000027', NULL,
   '{"comando": "ia assume #12", "resultado": "ok", "evento_id": "e1e10000-0001-7000-8000-000000000082"}'::jsonb,
   now() - interval '5 minutes')
ON CONFLICT (evolution_message_id) DO NOTHING;


COMMIT;


-- =============================================================================
-- Resumo do seed:
--   3 modelos (2 ativas + 1 pausada), 7 entradas de FAQ, 20 mídias.
--   8 clientes, 8 conversas (1 recorrente).
--   9 atendimentos cobrindo os 8 estados:
--     Novo (Pedro), Triagem (Felipe), Qualificado (Marcos),
--     Aguardando_confirmacao (Diego), Confirmado (André),
--     Em_execucao (Roberto), Fechado (Henrique x2), Perdido (João).
--   6 bloqueios (2 ativos sem sobreposição, 2 concluido, 1 cancelado, 1 manual).
--   ~30 mensagens com idempotência via evolution_message_id.
--   2 comprovantes Pix (1 validado, 1 em_revisao).
--   4 escaladas (2 abertas, 2 fechadas).
--   25 eventos auditando transições, pix, handoffs, fechamentos e comandos inválidos.
--   7 envios_evolution cobrindo todos os 5 tipos.
-- =============================================================================
