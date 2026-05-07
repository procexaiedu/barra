# Especificação de Seeds — Barra Vips

> Arquivo consumido por agente para gerar SQL de seeds completo.
> Usar junto com `docs/schema_barravips.md` (estrutura das tabelas, constraints, ENUMs).
> Schema Postgres: `barravips`. Todas as tabelas devem ser prefixadas com `barravips.`.

---

## 1. Objetivo

Gerar seeds que cubram **100% dos componentes visuais** de todas as telas da interface:
- Painel operacional (cards de destaque, métricas do dia, agenda)
- Atendimentos (todos os 8 estados, kanban, detalhe completo)
- Clientes/CRM (conversas, histórico, gráfico de receita)
- Agenda (visão dia/semana/mês, todos os estados de bloqueio)
- Modelos (lista, perfil, FAQ, mídia, programas)
- PIX (todos os estados: em_revisao, validado_auto, invalido)
- Dashboard analítico (KPIs, funil, perdas por motivo, ranking)

---

## 2. UUIDs Pré-definidos

Use EXATAMENTE estes UUIDs para garantir consistência nas FKs.

```
-- USUARIO
USR_FERNANDO    = '00000000-0000-0000-0000-000000000001'

-- MODELOS
MOD_ALESSIA     = 'a1000000-0000-0000-0000-000000000001'
MOD_BRUNA       = 'a1000000-0000-0000-0000-000000000002'
MOD_CAMILA      = 'a1000000-0000-0000-0000-000000000003'

-- DURACOES
DUR_1H          = 'd0000000-0000-0000-0000-000000000001'
DUR_2H          = 'd0000000-0000-0000-0000-000000000002'
DUR_3H          = 'd0000000-0000-0000-0000-000000000003'
DUR_4H          = 'd0000000-0000-0000-0000-000000000004'
DUR_PERNOITE    = 'd0000000-0000-0000-0000-000000000005'

-- PROGRAMAS
PRG_MASSAGEM    = 'e0000000-0000-0000-0000-000000000001'
PRG_JANTAR      = 'e0000000-0000-0000-0000-000000000002'
PRG_COMPLETO    = 'e0000000-0000-0000-0000-000000000003'
PRG_PERNOITE    = 'e0000000-0000-0000-0000-000000000004'
PRG_TANTRICA    = 'e0000000-0000-0000-0000-000000000005'

-- CLIENTES
CLI_RICARDO     = 'c1000000-0000-0000-0000-000000000001'
CLI_MARCOS      = 'c1000000-0000-0000-0000-000000000002'
CLI_BRUNO       = 'c1000000-0000-0000-0000-000000000003'
CLI_FELIPE      = 'c1000000-0000-0000-0000-000000000004'
CLI_ADRIANO     = 'c1000000-0000-0000-0000-000000000005'
CLI_LUCAS       = 'c1000000-0000-0000-0000-000000000006'
CLI_RODRIGO     = 'c1000000-0000-0000-0000-000000000007'
CLI_DANIEL      = 'c1000000-0000-0000-0000-000000000008'
CLI_EDUARDO     = 'c1000000-0000-0000-0000-000000000009'
CLI_GUSTAVO     = 'c1000000-0000-0000-0000-000000000010'
CLI_PAULO       = 'c1000000-0000-0000-0000-000000000011'
CLI_ANDRE       = 'c1000000-0000-0000-0000-000000000012'

-- CONVERSAS (par único cliente+modelo)
CNV_RICO_ALE    = 'f1000000-0000-0000-0000-000000000001'
CNV_MARC_ALE    = 'f1000000-0000-0000-0000-000000000002'
CNV_ADRI_ALE    = 'f1000000-0000-0000-0000-000000000003'
CNV_LUCA_ALE    = 'f1000000-0000-0000-0000-000000000004'
CNV_DANI_ALE    = 'f1000000-0000-0000-0000-000000000005'
CNV_EDUA_ALE    = 'f1000000-0000-0000-0000-000000000006'
CNV_BRUN_BRU    = 'f1000000-0000-0000-0000-000000000007'
CNV_FELI_BRU    = 'f1000000-0000-0000-0000-000000000008'
CNV_RODR_BRU    = 'f1000000-0000-0000-0000-000000000009'
CNV_GUST_BRU    = 'f1000000-0000-0000-0000-000000000010'
CNV_PAUL_CAM    = 'f1000000-0000-0000-0000-000000000011'
CNV_ANDR_CAM    = 'f1000000-0000-0000-0000-000000000012'

-- BLOQUEIOS
BLQ_ALE_01      = 'b1000000-0000-0000-0000-000000000001'  -- hoje 20h-22h bloqueado (Eduardo)
BLQ_ALE_02      = 'b1000000-0000-0000-0000-000000000002'  -- hoje 15h-17h em_atendimento (Ricardo atual)
BLQ_ALE_03      = 'b1000000-0000-0000-0000-000000000003'  -- ontem 20h-22h concluido (Ricardo anterior)
BLQ_ALE_04      = 'b1000000-0000-0000-0000-000000000004'  -- -7d 18h-21h concluido (Ricardo antigo)
BLQ_ALE_05      = 'b1000000-0000-0000-0000-000000000005'  -- amanhã 19h-21h bloqueado (Marcos)
BLQ_BRU_01      = 'b1000000-0000-0000-0000-000000000006'  -- hoje 13h-18h em_atendimento (Bruno)
BLQ_BRU_02      = 'b1000000-0000-0000-0000-000000000007'  -- hoje 21h-23h bloqueado (Gustavo)
BLQ_BRU_03      = 'b1000000-0000-0000-0000-000000000008'  -- amanhã 14h-16h bloqueado manual
BLQ_CAM_01      = 'b1000000-0000-0000-0000-000000000009'  -- -3d 19h-21h concluido (Paulo)

-- ATENDIMENTOS
ATD_RICO_1      = '91000000-0000-0000-0000-000000000001'  -- Fechado -7d interno R$1800
ATD_RICO_2      = '91000000-0000-0000-0000-000000000002'  -- Fechado -1d externo R$2500
ATD_RICO_3      = '91000000-0000-0000-0000-000000000003'  -- Fechado hoje interno R$1500 (atual)
ATD_MARC_1      = '91000000-0000-0000-0000-000000000004'  -- Triagem hoje interno
ATD_ADRI_1      = '91000000-0000-0000-0000-000000000005'  -- Perdido preco -3d
ATD_LUCA_1      = '91000000-0000-0000-0000-000000000006'  -- Perdido fora_de_area -2d
ATD_DANI_1      = '91000000-0000-0000-0000-000000000007'  -- Novo agora
ATD_EDUA_1      = '91000000-0000-0000-0000-000000000008'  -- Qualificado hoje (handoff_ia)
ATD_BRUN_1      = '91000000-0000-0000-0000-000000000009'  -- Fechado -14d interno R$2400
ATD_BRUN_2      = '91000000-0000-0000-0000-000000000010'  -- Em_execucao hoje interno
ATD_FELI_1      = '91000000-0000-0000-0000-000000000011'  -- Perdido sumiu -5d
ATD_RODR_1      = '91000000-0000-0000-0000-000000000012'  -- Perdido risco -1d
ATD_GUST_1      = '91000000-0000-0000-0000-000000000013'  -- Aguardando_confirmacao externo pix_em_revisao
ATD_PAUL_1      = '91000000-0000-0000-0000-000000000014'  -- Fechado -3d com Camila R$3000
ATD_ANDR_1      = '91000000-0000-0000-0000-000000000015'  -- Perdido indisponibilidade com Camila

-- MENSAGENS (selection — adicionar mais se necessário)
MSG_001 thru MSG_060  (gerar sequencialmente com evolution_message_id = '3EB0SEED' + zero-padded index)

-- COMPROVANTES PIX
PIX_GUST_1      = '71000000-0000-0000-0000-000000000001'  -- em_revisao (Gustavo)
PIX_RICO_1      = '71000000-0000-0000-0000-000000000002'  -- validado_auto (Ricardo antigo)
PIX_RICO_2      = '71000000-0000-0000-0000-000000000003'  -- validado_auto (Ricardo recente)
PIX_RODR_1      = '71000000-0000-0000-0000-000000000004'  -- invalido/rejeitado (Rodrigo)

-- ESCALADAS
ESC_GUST_1      = '81000000-0000-0000-0000-000000000001'  -- aberta: pix em revisão Gustavo
ESC_EDUA_1      = '81000000-0000-0000-0000-000000000002'  -- aberta: handoff_ia Eduardo
ESC_BRUN_1      = '81000000-0000-0000-0000-000000000003'  -- fechada: chegou Bruno
ESC_RICO_1      = '81000000-0000-0000-0000-000000000004'  -- fechada: chegou Ricardo
```

---

## 3. Dados por Tabela (ordem de inserção)

### 3.1 `barravips.usuarios`

> Inserir manualmente. O trigger `handle_new_user` normalmente cria este registro ao inserir em `auth.users`. Para seeds, insira direto.
> **Atenção:** O campo `id` deve referenciar um UUID real de `auth.users` em produção. Em ambiente de testes, use o UUID gerado no Supabase para o usuário Fernando (contato@procexai.tech). Se não souber o UUID, use o placeholder abaixo e faça UPDATE depois.

```sql
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
```

---

### 3.2 `barravips.duracoes`

```
id=DUR_1H,       nome='1 hora',    ordem=1
id=DUR_2H,       nome='2 horas',   ordem=2
id=DUR_3H,       nome='3 horas',   ordem=3
id=DUR_4H,       nome='4 horas',   ordem=4
id=DUR_PERNOITE, nome='Pernoite',  ordem=5
```

---

### 3.3 `barravips.programas`

```
id=PRG_MASSAGEM, nome='Massagem Relaxante',   categoria='relaxamento'
id=PRG_JANTAR,   nome='Acompanhante Jantar',  categoria='social'
id=PRG_COMPLETO, nome='Programa Completo',    categoria='completo'
id=PRG_PERNOITE, nome='Pernoite',             categoria='pernoite'
id=PRG_TANTRICA, nome='Massagem Tântrica',    categoria='tântrica'
```

---

### 3.4 `barravips.modelos`

#### Alessia Viana (ativa)
```
id                      = MOD_ALESSIA
nome                    = 'Alessia Viana'
numero_whatsapp         = '+5521999990100'
evolution_instance_id   = 'evo_alessia'
status                  = 'ativa'
valor_padrao            = 1500.00
percentual_repasse      = 40.00
chave_pix               = '21999990100'
titular_chave           = 'Alessia Viana'
idade                   = 24
idiomas                 = ARRAY['pt-BR', 'en-US']
localizacao_operacional = 'Zona Sul e Barra da Tijuca, Rio de Janeiro'
tipo_atendimento_aceito = ARRAY['interno', 'externo']
foto_perfil_object_key  = 'modelos/a1000000-0000-0000-0000-000000000001/perfil/perfil.jpg'
coordenacao_chat_id     = '120363111111111001@g.us'
coordenacao_verificada_em = NOW() - INTERVAL '1 hour'
```

#### Bruna Martins (ativa)
```
id                      = MOD_BRUNA
nome                    = 'Bruna Martins'
numero_whatsapp         = '+5511988880200'
evolution_instance_id   = 'evo_bruna'
status                  = 'ativa'
valor_padrao            = 1200.00
percentual_repasse      = 30.00
chave_pix               = '11988880200'
titular_chave           = 'Bruna Martins'
idade                   = 27
idiomas                 = ARRAY['pt-BR']
localizacao_operacional = 'São Paulo — Jardins, Moema, Itaim Bibi'
tipo_atendimento_aceito = ARRAY['interno', 'externo']
foto_perfil_object_key  = 'modelos/a1000000-0000-0000-0000-000000000002/perfil/perfil.jpg'
coordenacao_chat_id     = '120363222222222002@g.us'
coordenacao_verificada_em = NOW() - INTERVAL '30 minutes'
```

#### Camila Santos (pausada)
```
id                      = MOD_CAMILA
nome                    = 'Camila Santos'
numero_whatsapp         = '+5521977770300'
evolution_instance_id   = 'evo_camila'
status                  = 'pausada'
valor_padrao            = 2000.00
percentual_repasse      = 50.00
chave_pix               = '21977770300'
titular_chave           = 'Camila Santos'
idade                   = 22
idiomas                 = ARRAY['pt-BR', 'es-ES']
localizacao_operacional = 'Barra da Tijuca e Recreio, Rio de Janeiro'
tipo_atendimento_aceito = ARRAY['externo']
foto_perfil_object_key  = 'modelos/a1000000-0000-0000-0000-000000000003/perfil/perfil.jpg'
coordenacao_chat_id     = '120363333333333003@g.us'
coordenacao_verificada_em = NOW() - INTERVAL '2 days'
```

---

### 3.5 `barravips.modelo_faq`

**Alessia (5 itens):**
```
1. pergunta='Você atende em qual região?'
   resposta='Atendo em toda Zona Sul e Barra da Tijuca. Para outras regiões consulte disponibilidade e taxa de deslocamento.'
   tags=ARRAY['localização', 'região', 'bairro']

2. pergunta='Qual o valor do programa?'
   resposta='Meus valores variam por duração e programa. O básico começa em R$ 800 por hora. Posso te passar os detalhes do que você tem em mente!'
   tags=ARRAY['valor', 'preço', 'programa']

3. pergunta='Você é real? As fotos são suas?'
   resposta='Claro que sim! 😊 Minhas fotos são recentes e autênticas. Posso fazer uma chamada de vídeo rápida para você se certificar.'
   tags=ARRAY['verificação', 'autenticidade', 'fotos']

4. pergunta='Aceita Pix?'
   resposta='Sim! Aceito Pix. Para atendimentos externos, cobro um Pix de deslocamento antecipado. Presencialmente aceito dinheiro ou Pix.'
   tags=ARRAY['pagamento', 'pix', 'dinheiro']

5. pergunta='Qual a duração mínima?'
   resposta='A duração mínima é 1 hora. Para programas completos ou pernoite, temos opções especiais — basta perguntar!'
   tags=ARRAY['duração', 'tempo', 'programa']
```

**Bruna (4 itens):**
```
1. pergunta='Onde você fica localizada?'
   resposta='Estou em São Paulo, atendo nos Jardins, Moema e Itaim Bibi. Para outras regiões verifico disponibilidade.'
   tags=ARRAY['localização', 'sp', 'bairro']

2. pergunta='Como funciona o agendamento?'
   resposta='É simples! Me conta o dia, horário e o que você tem em mente. Confirmo a disponibilidade e te mando os detalhes para fecharmos.'
   tags=ARRAY['agendamento', 'reserva', 'como funciona']

3. pergunta='Tem fotos verificadas?'
   resposta='Sim! Todas as fotos são minhas e recentes. Se quiser mais certeza, posso mostrar uma selfie com data antes de fecharmos.'
   tags=ARRAY['verificação', 'fotos', 'autenticidade']

4. pergunta='Atende à domicílio?'
   resposta='Sim, atendo no seu local (hotel, apartamento ou casa) na minha área de cobertura. Preciso de endereço e confirmação antes de sair.'
   tags=ARRAY['domicílio', 'externo', 'hotel', 'apartamento']
```

**Camila (3 itens):**
```
1. pergunta='Você fala espanhol?'
   resposta='Sí, hablo español y también português. Puedo atenderte en los dos idiomas sin problema! 😊'
   tags=ARRAY['idioma', 'espanhol', 'espanol']

2. pergunta='Atende só externo ou também interno?'
   resposta='Atendo apenas em locais dos clientes — hotel, apartamento ou casa. Não realizo atendimentos no meu endereço.'
   tags=ARRAY['externo', 'tipo', 'local']

3. pergunta='Qual o valor para pernoite?'
   resposta='Pernoite tem um valor especial. Me conta melhor o que você tem em mente e te passo os detalhes com calma.'
   tags=ARRAY['pernoite', 'valor', 'noite']
```

---

### 3.6 `barravips.modelo_midia`

Gerar 10 registros para Alessia, 10 para Bruna, 5 para Camila.
Usar padrão de object_key: `modelos/{modelo_id}/{tipo}/{nome_arquivo}`
bucket sempre `barra-media`, aprovada=true.

**Alessia (10 mídias):**
```
tipo=foto, tag=apresentacao, object_key=modelos/MOD_ALESSIA/foto/apresentacao-01.jpg
tipo=foto, tag=apresentacao, object_key=modelos/MOD_ALESSIA/foto/apresentacao-02.jpg
tipo=foto, tag=apresentacao, object_key=modelos/MOD_ALESSIA/foto/apresentacao-03.jpg
tipo=foto, tag=corpo,        object_key=modelos/MOD_ALESSIA/foto/corpo-01.jpg
tipo=foto, tag=corpo,        object_key=modelos/MOD_ALESSIA/foto/corpo-02.jpg
tipo=foto, tag=corpo,        object_key=modelos/MOD_ALESSIA/foto/corpo-03.jpg
tipo=foto, tag=lifestyle,    object_key=modelos/MOD_ALESSIA/foto/lifestyle-01.jpg
tipo=foto, tag=lifestyle,    object_key=modelos/MOD_ALESSIA/foto/lifestyle-02.jpg
tipo=video, tag=evento,      object_key=modelos/MOD_ALESSIA/video/evento-01.mp4
tipo=video, tag=evento,      object_key=modelos/MOD_ALESSIA/video/evento-02.mp4
```

**Bruna (10 mídias — mesma estrutura de tags, paths com MOD_BRUNA):**
```
tipo=foto, tag=apresentacao (x3)
tipo=foto, tag=corpo (x3)
tipo=foto, tag=lifestyle (x2)
tipo=video, tag=evento (x2)
```

**Camila (5 mídias):**
```
tipo=foto, tag=apresentacao (x2)
tipo=foto, tag=corpo (x1)
tipo=foto, tag=lifestyle (x1)
tipo=video, tag=evento (x1)
```

---

### 3.7 `barravips.modelo_servicos`

**Alessia:**
```
nome='Programa 1h',  duracao_horas=1.0, preco=1500.00, ativo=true, ordem=1
nome='Programa 2h',  duracao_horas=2.0, preco=2800.00, ativo=true, ordem=2
nome='Programa 3h',  duracao_horas=3.0, preco=3800.00, ativo=true, ordem=3
nome='Pernoite',     duracao_horas=12.0, preco=6000.00, ativo=true, ordem=4
```

**Bruna:**
```
nome='Programa 1h',  duracao_horas=1.0, preco=1200.00, ativo=true, ordem=1
nome='Programa 2h',  duracao_horas=2.0, preco=2200.00, ativo=true, ordem=2
nome='Massagem 1h',  duracao_horas=1.0, preco=900.00,  ativo=true, ordem=3
```

**Camila:**
```
nome='Programa 1h',  duracao_horas=1.0, preco=2000.00, ativo=true, ordem=1
nome='Programa 2h',  duracao_horas=2.0, preco=3500.00, ativo=true, ordem=2
nome='Pernoite',     duracao_horas=12.0, preco=7000.00, ativo=false, ordem=3
```

---

### 3.8 `barravips.modelo_programas`

**Alessia:**
```
(MOD_ALESSIA, PRG_MASSAGEM, DUR_1H,       preco=800.00)
(MOD_ALESSIA, PRG_MASSAGEM, DUR_2H,       preco=1500.00)
(MOD_ALESSIA, PRG_COMPLETO, DUR_2H,       preco=2500.00)
(MOD_ALESSIA, PRG_COMPLETO, DUR_3H,       preco=3500.00)
(MOD_ALESSIA, PRG_PERNOITE, DUR_PERNOITE, preco=5500.00)
(MOD_ALESSIA, PRG_TANTRICA, DUR_1H,       preco=1800.00)
(MOD_ALESSIA, PRG_TANTRICA, DUR_2H,       preco=3000.00)
```

**Bruna:**
```
(MOD_BRUNA, PRG_MASSAGEM, DUR_1H,       preco=600.00)
(MOD_BRUNA, PRG_MASSAGEM, DUR_2H,       preco=1100.00)
(MOD_BRUNA, PRG_JANTAR,   DUR_2H,       preco=1400.00)
(MOD_BRUNA, PRG_JANTAR,   DUR_3H,       preco=2000.00)
(MOD_BRUNA, PRG_COMPLETO, DUR_2H,       preco=1800.00)
(MOD_BRUNA, PRG_COMPLETO, DUR_3H,       preco=2600.00)
```

**Camila:**
```
(MOD_CAMILA, PRG_COMPLETO, DUR_1H,       preco=1500.00)
(MOD_CAMILA, PRG_COMPLETO, DUR_2H,       preco=2500.00)
(MOD_CAMILA, PRG_PERNOITE, DUR_PERNOITE, preco=6000.00)
```

---

### 3.9 `barravips.clientes`

```
id=CLI_RICARDO, telefone='+5521999990001', nome='Ricardo Alves',    primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_MARCOS,  telefone='+5521999990002', nome='Marcos Lima',      primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_BRUNO,   telefone='+5511988880001', nome='Bruno Costa',      primeiro_contato_modelo_id=MOD_BRUNA
id=CLI_FELIPE,  telefone='+5511988880002', nome='Felipe Ramos',     primeiro_contato_modelo_id=MOD_BRUNA
id=CLI_ADRIANO, telefone='+5521988880001', nome='Adriano Santana',  primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_LUCAS,   telefone='+5521988880002', nome='Lucas Fernandes',  primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_RODRIGO, telefone='+5511977770001', nome='Rodrigo Pinto',    primeiro_contato_modelo_id=MOD_BRUNA
id=CLI_DANIEL,  telefone='+5511977770002', nome=NULL,               primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_EDUARDO, telefone='+5521977770001', nome='Eduardo Luz',      primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_GUSTAVO, telefone='+5521977770002', nome='Gustavo Moraes',   primeiro_contato_modelo_id=MOD_BRUNA
id=CLI_PAULO,   telefone='+5511966660001', nome='Paulo Vieira',     primeiro_contato_modelo_id=MOD_CAMILA
id=CLI_ANDRE,   telefone='+5511966660002', nome='André Saraiva',    primeiro_contato_modelo_id=MOD_CAMILA
```

---

### 3.10 `barravips.conversas`

```
id=CNV_RICO_ALE, cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990001@s.whatsapp.net',
  recorrente=true, ultimo_motivo_perda=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '2 hours',
  ultima_mensagem_direcao='ia'

id=CNV_MARC_ALE, cliente_id=CLI_MARCOS, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990002@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '45 minutes',
  ultima_mensagem_direcao='cliente'

id=CNV_ADRI_ALE, cliente_id=CLI_ADRIANO, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521988880001@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='preco',
  ultima_mensagem_em=NOW()-INTERVAL '3 days',
  ultima_mensagem_direcao='ia'

id=CNV_LUCA_ALE, cliente_id=CLI_LUCAS, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521988880002@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='fora_de_area',
  ultima_mensagem_em=NOW()-INTERVAL '2 days',
  ultima_mensagem_direcao='ia'

id=CNV_DANI_ALE, cliente_id=CLI_DANIEL, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5511977770002@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '10 minutes',
  ultima_mensagem_direcao='cliente'

id=CNV_EDUA_ALE, cliente_id=CLI_EDUARDO, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521977770001@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '30 minutes',
  ultima_mensagem_direcao='ia',
  observacoes_internas='Cliente parece hesitante, faz perguntas sobre identidade da modelo. IA solicitou handoff para avaliação.'

id=CNV_BRUN_BRU, cliente_id=CLI_BRUNO, modelo_id=MOD_BRUNA,
  evolution_chat_id='5511988880001@s.whatsapp.net',
  recorrente=true, ultimo_motivo_perda=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '4 hours',
  ultima_mensagem_direcao='modelo_manual'

id=CNV_FELI_BRU, cliente_id=CLI_FELIPE, modelo_id=MOD_BRUNA,
  evolution_chat_id='5511988880002@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='sumiu',
  ultima_mensagem_em=NOW()-INTERVAL '5 days',
  ultima_mensagem_direcao='ia'

id=CNV_RODR_BRU, cliente_id=CLI_RODRIGO, modelo_id=MOD_BRUNA,
  evolution_chat_id='5511977770001@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='risco',
  ultima_mensagem_em=NOW()-INTERVAL '1 day',
  ultima_mensagem_direcao='ia'

id=CNV_GUST_BRU, cliente_id=CLI_GUSTAVO, modelo_id=MOD_BRUNA,
  evolution_chat_id='5521977770002@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '1 hour',
  ultima_mensagem_direcao='cliente'

id=CNV_PAUL_CAM, cliente_id=CLI_PAULO, modelo_id=MOD_CAMILA,
  evolution_chat_id='5511966660001@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '3 days',
  ultima_mensagem_direcao='ia'

id=CNV_ANDR_CAM, cliente_id=CLI_ANDRE, modelo_id=MOD_CAMILA,
  evolution_chat_id='5511966660002@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='indisponibilidade',
  ultima_mensagem_em=NOW()-INTERVAL '4 days',
  ultima_mensagem_direcao='ia'
```

---

### 3.11 `barravips.bloqueios`

> Inserir ANTES dos atendimentos pois ATD referencia bloqueio_id. Inserir com atendimento_id=NULL; depois fazer UPDATE após criar ATDs.
> As datas devem ser calculadas relativamente a NOW() na hora de gerar o SQL.
> Todos os horários em UTC-3 (BRT = UTC-3, logo um bloqueio às 20h BRT = 23h UTC).

```
id=BLQ_ALE_01, modelo_id=MOD_ALESSIA,
  inicio=NOW()::date + TIME '20:00:00' + INTERVAL '0',   -- hoje 20h BRT
  fim=NOW()::date + TIME '22:00:00' + INTERVAL '0',
  estado='bloqueado', origem='ia', atendimento_id=NULL,
  observacao=NULL

id=BLQ_ALE_02, modelo_id=MOD_ALESSIA,
  inicio=NOW()::date + TIME '15:00:00' - INTERVAL '0',   -- hoje 15h BRT
  fim=NOW()::date + TIME '17:00:00' - INTERVAL '0',
  estado='em_atendimento', origem='ia', atendimento_id=NULL,
  observacao=NULL

id=BLQ_ALE_03, modelo_id=MOD_ALESSIA,
  inicio=(NOW()-INTERVAL '1 day')::date + TIME '20:00:00',
  fim=(NOW()-INTERVAL '1 day')::date + TIME '22:30:00',
  estado='concluido', origem='ia', atendimento_id=NULL,
  observacao=NULL

id=BLQ_ALE_04, modelo_id=MOD_ALESSIA,
  inicio=(NOW()-INTERVAL '7 days')::date + TIME '18:00:00',
  fim=(NOW()-INTERVAL '7 days')::date + TIME '21:00:00',
  estado='concluido', origem='ia', atendimento_id=NULL,
  observacao=NULL

id=BLQ_ALE_05, modelo_id=MOD_ALESSIA,
  inicio=(NOW()+INTERVAL '1 day')::date + TIME '19:00:00',
  fim=(NOW()+INTERVAL '1 day')::date + TIME '21:00:00',
  estado='bloqueado', origem='ia', atendimento_id=NULL,
  observacao=NULL

id=BLQ_BRU_01, modelo_id=MOD_BRUNA,
  inicio=NOW()::date + TIME '13:00:00',
  fim=NOW()::date + TIME '18:00:00',
  estado='em_atendimento', origem='ia', atendimento_id=NULL,
  observacao=NULL

id=BLQ_BRU_02, modelo_id=MOD_BRUNA,
  inicio=NOW()::date + TIME '21:00:00',
  fim=NOW()::date + TIME '23:00:00',
  estado='bloqueado', origem='ia', atendimento_id=NULL,
  observacao=NULL

id=BLQ_BRU_03, modelo_id=MOD_BRUNA,
  inicio=(NOW()+INTERVAL '1 day')::date + TIME '14:00:00',
  fim=(NOW()+INTERVAL '1 day')::date + TIME '16:00:00',
  estado='bloqueado', origem='painel_fernando', atendimento_id=NULL,
  observacao='Folga — compromisso pessoal'

id=BLQ_CAM_01, modelo_id=MOD_CAMILA,
  inicio=(NOW()-INTERVAL '3 days')::date + TIME '19:00:00',
  fim=(NOW()-INTERVAL '3 days')::date + TIME '21:00:00',
  estado='concluido', origem='ia', atendimento_id=NULL,
  observacao=NULL
```

---

### 3.12 `barravips.atendimentos`

> `numero_curto` é gerado por trigger (não inserir). Se o trigger não estiver ativo no ambiente de seeds, inserir explicitamente sequencial por modelo (Alessia: 1,2,3,4,5,6,7,8 / Bruna: 1,2,3,4,5 / Camila: 1,2).
> Após inserir todos os ATDs, fazer UPDATE dos bloqueios com atendimento_id e UPDATE dos ATDs com bloqueio_id.

#### ATD_RICO_1 — Ricardo + Alessia — FECHADO há 7 dias (interno)
```
id=ATD_RICO_1, cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA,
conversa_id=CNV_RICO_ALE, bloqueio_id=BLQ_ALE_04,
estado='Fechado', tipo_atendimento='interno', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '7 days')::date,
horario_desejado='18:00:00',
duracao_horas=3.0,
endereco=NULL, bairro=NULL, tipo_local=NULL,
forma_pagamento='dinheiro',
valor_acordado=1500.00, valor_final=1800.00,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=(NOW()-INTERVAL '7 days')::date + TIME '17:45:00',
foto_portaria_em=(NOW()-INTERVAL '7 days')::date + TIME '18:07:00',
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Cliente recorrente, atendimento interno concluído com gorjeta. Duração 3h, pagou R$1.800.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='comando_grupo',
created_at=NOW()-INTERVAL '7 days' - INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '7 days'
```

#### ATD_RICO_2 — Ricardo + Alessia — FECHADO ontem (externo)
```
id=ATD_RICO_2, cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA,
conversa_id=CNV_RICO_ALE, bloqueio_id=BLQ_ALE_03,
estado='Fechado', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '1 day')::date,
horario_desejado='20:00:00',
duracao_horas=2.5,
endereco='Av. Atlântica, 1702, apto 1202', bairro='Copacabana',
tipo_local='apartamento', referencia_local='Próximo ao Posto 4',
forma_pagamento='pix',
valor_acordado=2200.00, valor_final=2500.00,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='validado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Atendimento externo em Copacabana. Pix de deslocamento R$250 validado automaticamente. Encerrou com R$2.500.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='comando_grupo',
created_at=NOW()-INTERVAL '1 day' - INTERVAL '3 hours',
updated_at=NOW()-INTERVAL '1 day'
```

#### ATD_RICO_3 — Ricardo + Alessia — FECHADO hoje (interno) — atendimento mais recente
```
id=ATD_RICO_3, cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA,
conversa_id=CNV_RICO_ALE, bloqueio_id=BLQ_ALE_02,
estado='Fechado', tipo_atendimento='interno', urgencia='imediato',
data_desejada=NOW()::date,
horario_desejado='15:00:00',
duracao_horas=2.0,
endereco=NULL, bairro=NULL, tipo_local=NULL,
forma_pagamento='dinheiro',
valor_acordado=1500.00, valor_final=1500.00,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NOW()::date + TIME '14:45:00',
foto_portaria_em=NOW()::date + TIME '15:05:00',
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Cliente recorrente, veio hoje à tarde. Confirmou com foto de portaria, duração 2h, pagou R$1.500.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='comando_grupo',
created_at=NOW() - INTERVAL '4 hours',
updated_at=NOW() - INTERVAL '2 hours'
```

#### ATD_MARC_1 — Marcos + Alessia — TRIAGEM (hoje)
```
id=ATD_MARC_1, cliente_id=CLI_MARCOS, modelo_id=MOD_ALESSIA,
conversa_id=CNV_MARC_ALE, bloqueio_id=NULL,
estado='Triagem', tipo_atendimento='interno', urgencia='indefinido',
data_desejada=NULL, horario_desejado=NULL, duracao_horas=NULL,
endereco=NULL, bairro=NULL, tipo_local=NULL,
forma_pagamento=NULL, valor_acordado=NULL, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada='Qualificar horário e tipo de atendimento desejado.',
motivo_escalada=NULL,
resumo_operacional='Novo cliente, entrou em contato perguntando sobre disponibilidade. IA coletando informações iniciais.',
sinais_qualificacao='{"informa_horario": false, "informa_local": false, "aceita_valor": false, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='extracao_ia',
created_at=NOW() - INTERVAL '50 minutes',
updated_at=NOW() - INTERVAL '45 minutes'
```

#### ATD_ADRI_1 — Adriano + Alessia — PERDIDO (preco, -3 dias)
```
id=ATD_ADRI_1, cliente_id=CLI_ADRIANO, modelo_id=MOD_ALESSIA,
conversa_id=CNV_ADRI_ALE, bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '2 days')::date,
horario_desejado='19:00:00', duracao_horas=1.0,
endereco=NULL, bairro='Ipanema', tipo_local='hotel',
forma_pagamento='pix', valor_acordado=1500.00, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='preco', motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Cliente questionou o valor e não aceitou após negociação. Encerrado como perda por preço.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": false, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='painel_fernando',
created_at=NOW()-INTERVAL '3 days' - INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '3 days'
```

#### ATD_LUCA_1 — Lucas + Alessia — PERDIDO (fora_de_area, -2 dias)
```
id=ATD_LUCA_1, cliente_id=CLI_LUCAS, modelo_id=MOD_ALESSIA,
conversa_id=CNV_LUCA_ALE, bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='externo', urgencia='imediato',
data_desejada=NULL, horario_desejado=NULL, duracao_horas=NULL,
endereco=NULL, bairro='Centro', tipo_local='apartamento',
forma_pagamento=NULL, valor_acordado=NULL, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='fora_de_area', motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Cliente no Centro do Rio. Fora da área de cobertura da modelo.',
sinais_qualificacao='{"informa_horario": false, "informa_local": true, "aceita_valor": false, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='extracao_ia',
created_at=NOW()-INTERVAL '2 days' - INTERVAL '1 hour',
updated_at=NOW()-INTERVAL '2 days'
```

#### ATD_DANI_1 — Daniel + Alessia — NOVO (agora)
```
id=ATD_DANI_1, cliente_id=CLI_DANIEL, modelo_id=MOD_ALESSIA,
conversa_id=CNV_DANI_ALE, bloqueio_id=NULL,
estado='Novo', tipo_atendimento=NULL, urgencia=NULL,
data_desejada=NULL, horario_desejado=NULL, duracao_horas=NULL,
endereco=NULL, bairro=NULL, tipo_local=NULL,
forma_pagamento=NULL, valor_acordado=NULL, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada='Entender a intenção e qualificador básico.',
motivo_escalada=NULL,
resumo_operacional=NULL,
sinais_qualificacao='{}',
fonte_decisao_ultima_transicao=NULL,
created_at=NOW() - INTERVAL '12 minutes',
updated_at=NOW() - INTERVAL '10 minutes'
```

#### ATD_EDUA_1 — Eduardo + Alessia — QUALIFICADO com IA pausada (handoff_ia)
```
id=ATD_EDUA_1, cliente_id=CLI_EDUARDO, modelo_id=MOD_ALESSIA,
conversa_id=CNV_EDUA_ALE, bloqueio_id=BLQ_ALE_01,
estado='Qualificado', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()+INTERVAL '0 days')::date,
horario_desejado='20:00:00', duracao_horas=2.0,
endereco=NULL, bairro='Barra da Tijuca', tipo_local='hotel',
referencia_local='Hotel Windsor Barra',
forma_pagamento='pix', valor_acordado=2500.00, valor_final=NULL,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=true, ia_pausada_motivo='handoff_ia',
responsavel_atual='Fernando',
proxima_acao_esperada='Fernando decidir se segue com o atendimento. Cliente fez perguntas ambíguas.',
motivo_escalada='Cliente fez perguntas que sugerem intenção de verificar se é real antes de confirmar. Requer avaliação.',
resumo_operacional='Eduardo, externo, Hotel Windsor Barra, hoje às 20h, 2h, R$2.500. Qualificação completa, mas IA escalou por comportamento ambíguo.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='extracao_ia',
created_at=NOW() - INTERVAL '2 hours',
updated_at=NOW() - INTERVAL '30 minutes'
```

#### ATD_BRUN_1 — Bruno + Bruna — FECHADO -14 dias (interno)
```
id=ATD_BRUN_1, cliente_id=CLI_BRUNO, modelo_id=MOD_BRUNA,
conversa_id=CNV_BRUN_BRU, bloqueio_id=NULL,
estado='Fechado', tipo_atendimento='interno', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '14 days')::date,
horario_desejado='19:00:00', duracao_horas=2.0,
endereco=NULL, bairro=NULL, tipo_local=NULL,
forma_pagamento='dinheiro',
valor_acordado=1200.00, valor_final=2400.00,
percentual_repasse_snapshot=30.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=(NOW()-INTERVAL '14 days')::date + TIME '18:45:00',
foto_portaria_em=(NOW()-INTERVAL '14 days')::date + TIME '19:08:00',
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Primeiro atendimento do Bruno com Bruna. Interno, 2h, pagou R$2.400 (acima do acordado).',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='comando_grupo',
created_at=NOW()-INTERVAL '14 days' - INTERVAL '3 hours',
updated_at=NOW()-INTERVAL '14 days'
```

#### ATD_BRUN_2 — Bruno + Bruna — EM EXECUÇÃO hoje (interno, ia_pausada=modelo_em_atendimento)
```
id=ATD_BRUN_2, cliente_id=CLI_BRUNO, modelo_id=MOD_BRUNA,
conversa_id=CNV_BRUN_BRU, bloqueio_id=BLQ_BRU_01,
estado='Em_execucao', tipo_atendimento='interno', urgencia='agendado',
data_desejada=NOW()::date,
horario_desejado='13:00:00', duracao_horas=5.0,
endereco=NULL, bairro=NULL, tipo_local=NULL,
forma_pagamento='dinheiro',
valor_acordado=1200.00, valor_final=NULL,
percentual_repasse_snapshot=30.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NOW()::date + TIME '12:45:00',
foto_portaria_em=NOW()::date + TIME '13:10:00',
ia_pausada=true, ia_pausada_motivo='modelo_em_atendimento',
responsavel_atual='modelo',
proxima_acao_esperada='Bruna encerrar com "finalizado [valor]" ao término.',
motivo_escalada='Cliente chegou (foto de portaria). Bruna em atendimento.',
resumo_operacional='Bruno, recorrente, atendimento interno hoje. Foto de portaria às 13h10. IA pausada, Bruna conduzindo.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='webhook_imagem',
created_at=NOW() - INTERVAL '5 hours',
updated_at=NOW() - INTERVAL '4 hours'
```

#### ATD_FELI_1 — Felipe + Bruna — PERDIDO (sumiu, -5 dias)
```
id=ATD_FELI_1, cliente_id=CLI_FELIPE, modelo_id=MOD_BRUNA,
conversa_id=CNV_FELI_BRU, bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='interno', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '5 days')::date,
horario_desejado='20:00:00', duracao_horas=NULL,
endereco=NULL, bairro=NULL, tipo_local=NULL,
forma_pagamento=NULL, valor_acordado=1200.00, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='sumiu', motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Cliente combinado para 20h, avisou que saiu mas não apareceu. Timeout de 30 min, encerrado como sumiu.',
sinais_qualificacao='{"informa_horario": true, "informa_local": false, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": false}',
fonte_decisao_ultima_transicao='auto_timeout_interno',
created_at=NOW()-INTERVAL '5 days' - INTERVAL '4 hours',
updated_at=NOW()-INTERVAL '5 days'
```

#### ATD_RODR_1 — Rodrigo + Bruna — PERDIDO (risco, -1 dia)
```
id=ATD_RODR_1, cliente_id=CLI_RODRIGO, modelo_id=MOD_BRUNA,
conversa_id=CNV_RODR_BRU, bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='externo', urgencia='imediato',
data_desejada=NOW()::date-INTERVAL '1 day', horario_desejado=NULL, duracao_horas=1.0,
endereco=NULL, bairro='Santo André', tipo_local='apartamento',
forma_pagamento='pix', valor_acordado=NULL, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='risco', motivo_perda_obs=NULL,
pix_status='invalido',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='Fernando',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Cliente enviou comprovante Pix inválido (conta destino errada). Fernando recusou e encerrou como risco.',
sinais_qualificacao='{"informa_horario": false, "informa_local": true, "aceita_valor": false, "envia_pix": true, "responde_objetivamente": false}',
fonte_decisao_ultima_transicao='painel_fernando',
created_at=NOW()-INTERVAL '1 day' - INTERVAL '5 hours',
updated_at=NOW()-INTERVAL '1 day'
```

#### ATD_GUST_1 — Gustavo + Bruna — AGUARDANDO CONFIRMAÇÃO (externo, pix_em_revisao)
```
id=ATD_GUST_1, cliente_id=CLI_GUSTAVO, modelo_id=MOD_BRUNA,
conversa_id=CNV_GUST_BRU, bloqueio_id=BLQ_BRU_02,
estado='Aguardando_confirmacao', tipo_atendimento='externo', urgencia='agendado',
data_desejada=NOW()::date,
horario_desejado='21:00:00', duracao_horas=2.0,
endereco=NULL, bairro='Moema', tipo_local='apartamento',
referencia_local='Próximo ao metrô Eucaliptos',
forma_pagamento='pix', valor_acordado=1200.00, valor_final=NULL,
percentual_repasse_snapshot=30.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='em_revisao',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=true, ia_pausada_motivo='pix_em_revisao',
responsavel_atual='Fernando',
proxima_acao_esperada='Fernando validar ou recusar o comprovante Pix pelo painel.',
motivo_escalada='Pix de deslocamento (R$150) com titular divergente do cadastro. Pipeline sinalizou revisão.',
resumo_operacional='Gustavo, externo, Moema, hoje 21h, 2h, R$1.200. Aguardando validação do Pix de deslocamento.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='pipeline_pix',
created_at=NOW() - INTERVAL '1 hour',
updated_at=NOW() - INTERVAL '40 minutes'
```

#### ATD_PAUL_1 — Paulo + Camila — FECHADO -3 dias
```
id=ATD_PAUL_1, cliente_id=CLI_PAULO, modelo_id=MOD_CAMILA,
conversa_id=CNV_PAUL_CAM, bloqueio_id=BLQ_CAM_01,
estado='Fechado', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '3 days')::date,
horario_desejado='19:00:00', duracao_horas=2.0,
endereco='Rua Haddock Lobo, 595, apto 71', bairro='Jardins',
tipo_local='apartamento', referencia_local=NULL,
forma_pagamento='pix',
valor_acordado=2000.00, valor_final=3000.00,
percentual_repasse_snapshot=50.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='validado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Atendimento externo em São Paulo, 2h. Pix validado automaticamente. Encerrou com R$3.000.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": true, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='comando_grupo',
created_at=NOW()-INTERVAL '3 days' - INTERVAL '3 hours',
updated_at=NOW()-INTERVAL '3 days'
```

#### ATD_ANDR_1 — André + Camila — PERDIDO (indisponibilidade)
```
id=ATD_ANDR_1, cliente_id=CLI_ANDRE, modelo_id=MOD_CAMILA,
conversa_id=CNV_ANDR_CAM, bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '4 days')::date,
horario_desejado='20:00:00', duracao_horas=1.0,
endereco=NULL, bairro='Itaim Bibi', tipo_local='hotel',
forma_pagamento='pix', valor_acordado=2000.00, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='indisponibilidade', motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL,
motivo_escalada=NULL,
resumo_operacional='Camila sem disponibilidade na data solicitada. Atendimento encerrado como indisponibilidade.',
sinais_qualificacao='{"informa_horario": true, "informa_local": true, "aceita_valor": true, "envia_pix": false, "responde_objetivamente": true}',
fonte_decisao_ultima_transicao='painel_fernando',
created_at=NOW()-INTERVAL '4 days' - INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '4 days'
```

---

### 3.13 UPDATE pós-inserção (referências circulares)

```sql
-- Associar bloqueios aos atendimentos (atendimento_id nos bloqueios)
UPDATE barravips.bloqueios SET atendimento_id = ATD_RICO_1 WHERE id = BLQ_ALE_04;
UPDATE barravips.bloqueios SET atendimento_id = ATD_RICO_2 WHERE id = BLQ_ALE_03;
UPDATE barravips.bloqueios SET atendimento_id = ATD_RICO_3 WHERE id = BLQ_ALE_02;
UPDATE barravips.bloqueios SET atendimento_id = ATD_EDUA_1 WHERE id = BLQ_ALE_01;
UPDATE barravips.bloqueios SET atendimento_id = ATD_MARC_1 WHERE id = BLQ_ALE_05;
UPDATE barravips.bloqueios SET atendimento_id = ATD_BRUN_2 WHERE id = BLQ_BRU_01;
UPDATE barravips.bloqueios SET atendimento_id = ATD_GUST_1 WHERE id = BLQ_BRU_02;
UPDATE barravips.bloqueios SET atendimento_id = ATD_PAUL_1 WHERE id = BLQ_CAM_01;
-- BLQ_BRU_03 = bloqueio manual, sem atendimento
```

---

### 3.14 `barravips.mensagens`

Inserir mensagens para cada conversa. O trigger `atualiza_ultima_mensagem_em_conversa` atualizará `conversas.ultima_mensagem_em` e `ultima_mensagem_direcao` automaticamente.

Usar padrão para `evolution_message_id`: `'3EB0SEED' + LPAD(n::text, 8, '0')` — ex: `3EB0SEED00000001`.
Para mensagens de imagem: `media_object_key = 'mensagens/{conversa_id}/{evolution_message_id}.jpg'`.
Para mensagens de áudio: `media_object_key = 'mensagens/{conversa_id}/{evolution_message_id}.ogg'`.

#### Conversa Ricardo↔Alessia (CNV_RICO_ALE) — msgs 001-010

> Contexto: Ricardo chegou para o atendimento de hoje (ATD_RICO_3). Conversa mostra ciclo completo.

```
MSG-001: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='cliente', tipo='texto',
  conteudo='Oi Alessia, é o Ricardo. Tô vindo aí mais tarde, por volta das 15h. Tudo certo?',
  created_at=NOW()-INTERVAL '5 hours'

MSG-002: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='ia', tipo='texto',
  conteudo='Oi, Ricardo! Que ótimo te ver de volta 😊 Sim, pode vir às 15h! Você já sabe o endereço né? Qualquer coisa me avisa quando estiver saindo.',
  created_at=NOW()-INTERVAL '5 hours'+INTERVAL '1 minute'

MSG-003: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='cliente', tipo='texto',
  conteudo='Perfeito! Saindo de casa agora.',
  created_at=NOW()-INTERVAL '4 hours 15 minutes'

MSG-004: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='imagem', tipo='imagem',
  conteudo='[foto da portaria]',
  media_object_key='mensagens/CNV_RICO_ALE/3EB0SEED00000004.jpg',
  created_at=NOW()-INTERVAL '4 hours'

MSG-005: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='modelo_manual', tipo='texto',
  conteudo='finalizado 1500',
  created_at=NOW()-INTERVAL '2 hours'

MSG-006: conversa=CNV_RICO_ALE, atendimento=NULL,
  direcao='ia', tipo='texto',
  conteudo='Perfeito! Ótima tarde, Ricardo 😊 Já encerramos por hoje. Quando quiser, pode entrar em contato!',
  created_at=NOW()-INTERVAL '2 hours'+INTERVAL '2 minutes'
```

#### Conversa Marcos↔Alessia (CNV_MARC_ALE) — msgs 007-012

> Contexto: Marcos em triagem (ATD_MARC_1).

```
MSG-007: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='cliente', tipo='texto',
  conteudo='Olá, vi o número por indicação. Você atende hoje?',
  created_at=NOW()-INTERVAL '50 minutes'

MSG-008: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='ia', tipo='texto',
  conteudo='Olá, que bom! Sim, tenho disponibilidade hoje. Me conta o que você tem em mente — prefere algo à tarde ou à noite?',
  created_at=NOW()-INTERVAL '49 minutes'

MSG-009: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='cliente', tipo='texto',
  conteudo='Prefiro à noite, umas 20h. É lá na sua casa mesmo?',
  created_at=NOW()-INTERVAL '46 minutes'

MSG-010: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='ia', tipo='texto',
  conteudo='Exatamente! Você viria até mim. Qual seu bairro? Assim confirmo se a distância é tranquila.',
  created_at=NOW()-INTERVAL '45 minutes'
```

#### Conversa Eduardo↔Alessia (CNV_EDUA_ALE) — msgs 013-020

> Contexto: Eduardo qualificado, IA pausada (handoff_ia).

```
MSG-013: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto',
  conteudo='Oi. Quero marcar para hoje à noite.',
  created_at=NOW()-INTERVAL '2 hours'

MSG-014: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='ia', tipo='texto',
  conteudo='Oi! Que ótimo 😊 Me conta o que você está buscando, horário e local que prefere?',
  created_at=NOW()-INTERVAL '1 hour 58 minutes'

MSG-015: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto',
  conteudo='Hotel Windsor na Barra, 20h, umas 2 horas. Mas primeiro quero ver se você é real mesmo. Como posso confirmar?',
  created_at=NOW()-INTERVAL '1 hour 50 minutes'

MSG-016: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='ia', tipo='texto',
  conteudo='Entendo a preocupação! Posso fazer uma chamada de vídeo rápida antes de confirmarmos. Me avisa quando estiver pronto.',
  created_at=NOW()-INTERVAL '1 hour 48 minutes'

MSG-017: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto',
  conteudo='Ok, e o valor fica em quanto pra isso?',
  created_at=NOW()-INTERVAL '1 hour 40 minutes'

MSG-018: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='ia', tipo='texto',
  conteudo='Para 2h no hotel, R$ 2.500. Inclui deslocamento. O Pix de deslocamento é R$ 200 antecipado para confirmar.',
  created_at=NOW()-INTERVAL '1 hour 38 minutes'

MSG-019: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto',
  conteudo='Tá. Me manda um selfie pra eu ver mesmo.',
  created_at=NOW()-INTERVAL '30 minutes'
```

#### Conversa Bruno↔Bruna (CNV_BRUN_BRU) — msgs 021-030

> Contexto: Bruno em execução (ATD_BRUN_2). Conversa histórica + atual.

```
MSG-021: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_2,
  direcao='cliente', tipo='texto',
  conteudo='Bruna, bom dia! Quero repetir, posso ir hoje à tarde?',
  created_at=NOW()-INTERVAL '5 hours'

MSG-022: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_2,
  direcao='ia', tipo='texto',
  conteudo='Bruno! Que bom 😊 Pode sim! Chegando a partir de que horas?',
  created_at=NOW()-INTERVAL '4 hours 59 minutes'

MSG-023: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_2,
  direcao='cliente', tipo='texto',
  conteudo='Umas 13h. Vou ficar 5 horas se der.',
  created_at=NOW()-INTERVAL '4 hours 55 minutes'

MSG-024: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_2,
  direcao='ia', tipo='texto',
  conteudo='Perfeito! 13h até 18h. Te espero aqui 🌸',
  created_at=NOW()-INTERVAL '4 hours 50 minutes'

MSG-025: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_2,
  direcao='cliente', tipo='texto',
  conteudo='Saindo de casa agora!',
  created_at=NOW()-INTERVAL '4 hours 20 minutes'

MSG-026: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_2,
  direcao='imagem', tipo='imagem',
  conteudo='[foto da portaria]',
  media_object_key='mensagens/CNV_BRUN_BRU/3EB0SEED00000026.jpg',
  created_at=NOW()-INTERVAL '4 hours'

MSG-027: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_2,
  direcao='modelo_manual', tipo='texto',
  conteudo='Oi amor, pode subir! Apartamento 304.',
  created_at=NOW()-INTERVAL '3 hours 58 minutes'
```

#### Conversa Gustavo↔Bruna (CNV_GUST_BRU) — msgs 031-040

> Contexto: Gustavo aguardando confirmação com Pix em revisão.

```
MSG-031: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='texto',
  conteudo='Oi Bruna, quero marcar pra hoje à noite. Posso?',
  created_at=NOW()-INTERVAL '2 hours'

MSG-032: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='ia', tipo='texto',
  conteudo='Oi! Posso sim 😊 Me conta o horário e local que você prefere.',
  created_at=NOW()-INTERVAL '1 hour 58 minutes'

MSG-033: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='texto',
  conteudo='21h, meu apartamento em Moema. Fico a 5 min do metrô Eucaliptos.',
  created_at=NOW()-INTERVAL '1 hour 50 minutes'

MSG-034: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='ia', tipo='texto',
  conteudo='Perfeito! Para confirmar, vou precisar de um Pix de deslocamento de R$ 150. Pode mandar para a chave 11988880200.',
  created_at=NOW()-INTERVAL '1 hour 45 minutes'

MSG-035: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='texto',
  conteudo='Mandei!',
  created_at=NOW()-INTERVAL '1 hour 20 minutes'

MSG-036: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='imagem', tipo='imagem',
  conteudo='[comprovante de pix]',
  media_object_key='mensagens/CNV_GUST_BRU/3EB0SEED00000036.jpg',
  created_at=NOW()-INTERVAL '1 hour 15 minutes'

MSG-037: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='ia', tipo='texto',
  conteudo='Recebi o comprovante! Vou verificar aqui e já confirmo 🌸',
  created_at=NOW()-INTERVAL '1 hour 10 minutes'

MSG-038: conversa=CNV_GUST_BRU, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='texto',
  conteudo='Ok, aguardo!',
  created_at=NOW()-INTERVAL '1 hour'
```

Adicionar mensagens representativas (2-4 cada) para as conversas:
- CNV_ADRI_ALE (Adriano perdido por preço)
- CNV_LUCA_ALE (Lucas perdido fora_de_area)
- CNV_DANI_ALE (Daniel novo)
- CNV_FELI_BRU (Felipe sumiu)
- CNV_RODR_BRU (Rodrigo risco — inclui mensagem de imagem do Pix)
- CNV_PAUL_CAM (Paulo fechado)
- CNV_ANDR_CAM (André indisponibilidade)

Para CNV_RODR_BRU, incluir uma mensagem de tipo=imagem que será vinculada ao comprovante_pix PIX_RODR_1.

---

### 3.15 `barravips.comprovantes_pix`

```
id=PIX_GUST_1, atendimento_id=ATD_GUST_1, mensagem_id=MSG-036,
  valor_extraido=150.00, chave_extraida='11988880200',
  titular_extraido='G. M. Silva',      -- diverge do esperado "Gustavo Moraes"
  timestamp_extraido=NOW()-INTERVAL '1 hour 15 minutes',
  decisao_pipeline='em_revisao',
  motivo_em_revisao='Titular do Pix diverge do nome cadastrado do cliente.',
  decisao_final=NULL, decisao_final_por=NULL

id=PIX_RICO_1, atendimento_id=ATD_RICO_2, mensagem_id=(mensagem de imagem do Pix de Ricardo, -1 dia),
  valor_extraido=200.00, chave_extraida='21999990100',
  titular_extraido='Alessia Viana',
  timestamp_extraido=(NOW()-INTERVAL '1 day')::date + TIME '19:30:00',
  decisao_pipeline='validado', motivo_em_revisao=NULL,
  decisao_final=NULL, decisao_final_por=NULL

id=PIX_RICO_2, atendimento_id=ATD_PAUL_1, mensagem_id=(mensagem de imagem do Pix de Paulo),
  valor_extraido=300.00, chave_extraida='21977770300',
  titular_extraido='Camila Santos',
  timestamp_extraido=(NOW()-INTERVAL '3 days')::date + TIME '18:30:00',
  decisao_pipeline='validado', motivo_em_revisao=NULL,
  decisao_final=NULL, decisao_final_por=NULL

id=PIX_RODR_1, atendimento_id=ATD_RODR_1, mensagem_id=(mensagem de imagem do Pix de Rodrigo),
  valor_extraido=200.00, chave_extraida='99999999999',  -- chave inválida/aleatória
  titular_extraido='Empresa XYZ Ltda',
  timestamp_extraido=(NOW()-INTERVAL '1 day')::date + TIME '17:00:00',
  decisao_pipeline='em_revisao',
  motivo_em_revisao='Conta destino inválida e titular incoerente.',
  decisao_final='invalido', decisao_final_por=USR_FERNANDO
```

> **Atenção:** Os `mensagem_id` dos comprovantes precisam referenciar mensagens de `tipo='imagem'` existentes. Criar as mensagens de imagem de Pix para Rico-2, Paulo e Rodrigo antes de inserir os comprovantes.

---

### 3.16 `barravips.escaladas`

```
id=ESC_GUST_1, atendimento_id=ATD_GUST_1, responsavel='Fernando',
  motivo='Pix de deslocamento com titular divergente. Pipeline sinalizou revisão manual.',
  resumo_operacional='Gustavo Moraes, externo, Moema, hoje 21h, 2h, R$1.200. Enviou Pix de R$150 mas o titular "G. M. Silva" não confere com o cadastro.',
  acao_esperada='Validar ou recusar o comprovante pelo painel. Se validado, IA retoma e confirma o atendimento.',
  card_message_id='3EB0CARD00000001',
  aberta_em=NOW()-INTERVAL '1 hour 10 minutes',
  fechada_em=NULL, fechada_por=NULL, fechada_canal=NULL

id=ESC_EDUA_1, atendimento_id=ATD_EDUA_1, responsavel='Fernando',
  motivo='Cliente com comportamento ambíguo — questionou autenticidade e pediu selfie. IA escalou para avaliação.',
  resumo_operacional='Eduardo Luz, externo, Hotel Windsor Barra, hoje 20h, 2h, R$2.500. Qualificação completa. Cliente solicitou verificação visual antes de confirmar.',
  acao_esperada='Avaliar o perfil e decidir se segue, recusa ou pede mais informações. Se prosseguir, devolver para IA e aguardar Pix.',
  card_message_id='3EB0CARD00000002',
  aberta_em=NOW()-INTERVAL '30 minutes',
  fechada_em=NULL, fechada_por=NULL, fechada_canal=NULL

id=ESC_BRUN_1, atendimento_id=ATD_BRUN_2, responsavel='modelo',
  motivo='Cliente chegou (foto de portaria). Bruna em atendimento.',
  resumo_operacional='Bruno Costa, interno, foto de portaria às 13h10. IA pausada, Bruna conduzindo o atendimento.',
  acao_esperada='Encerrar com "finalizado [valor]" ao término do atendimento.',
  card_message_id='3EB0CARD00000003',
  aberta_em=NOW()-INTERVAL '4 hours',
  fechada_em=NULL, fechada_por=NULL, fechada_canal=NULL

id=ESC_RICO_1, atendimento_id=ATD_RICO_3, responsavel='modelo',
  motivo='Ricardo chegou (foto de portaria). Alessia em atendimento.',
  resumo_operacional='Ricardo Alves, interno, foto de portaria às 15h05. IA pausada, Alessia conduzindo.',
  acao_esperada='Encerrar com "finalizado [valor]".',
  card_message_id='3EB0CARD00000004',
  aberta_em=NOW()-INTERVAL '4 hours',
  fechada_em=NOW()-INTERVAL '2 hours',
  fechada_por=USR_FERNANDO, fechada_canal='grupo_coordenacao'
```

---

### 3.17 `barravips.eventos`

Gerar sequência de eventos para os atendimentos principais. Cada transição de estado gera um evento `transicao_estado`. Append-only.

#### Eventos ATD_RICO_3 (ciclo completo de hoje):
```
1. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '5 hours'

2. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '4 hours 50 minutes'

3. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '4 hours 45 minutes'

4. tipo='bloqueio_criado', origem='agente', autor='IA',
   payload={"bloqueio_id":"BLQ_ALE_02","inicio":"15:00","fim":"17:00"},
   created_at=NOW()-INTERVAL '4 hours 44 minutes'

5. tipo='extracao_registrada', origem='agente', autor='IA',
   payload={"campo":"aviso_saida_em","valor":"agora"},
   created_at=NOW()-INTERVAL '4 hours 15 minutes'

6. tipo='handoff_aberto', origem='agente', autor='IA',
   payload={"motivo":"Cliente chegou (foto de portaria)","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"},
   created_at=NOW()-INTERVAL '4 hours'

7. tipo='transicao_estado', origem='webhook_imagem', autor='sistema',
   payload={"de":"Aguardando_confirmacao","para":"Em_execucao","trigger":"foto_portaria","fonte_decisao":"webhook_imagem"},
   created_at=NOW()-INTERVAL '4 hours'

8. tipo='bloqueio_estado_mudado', origem='agente', autor='sistema',
   payload={"bloqueio_id":"BLQ_ALE_02","de":"bloqueado","para":"em_atendimento"},
   created_at=NOW()-INTERVAL '4 hours'

9. tipo='fechado_registrado', origem='grupo_coordenacao', autor='modelo',
   payload={"comando":"finalizado 1500","valor_final":1500},
   created_at=NOW()-INTERVAL '2 hours'

10. tipo='transicao_estado', origem='grupo_coordenacao', autor='modelo',
    payload={"de":"Em_execucao","para":"Fechado","fonte_decisao":"comando_grupo"},
    created_at=NOW()-INTERVAL '2 hours'

11. tipo='bloqueio_estado_mudado', origem='agente', autor='sistema',
    payload={"bloqueio_id":"BLQ_ALE_02","de":"em_atendimento","para":"concluido"},
    created_at=NOW()-INTERVAL '2 hours'
```

#### Eventos ATD_EDUA_1 (qualificado + handoff_ia):
```
1. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '2 hours'

2. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '1 hour 40 minutes'

3. tipo='bloqueio_criado', origem='agente', autor='IA',
   payload={"bloqueio_id":"BLQ_ALE_01","inicio":"20:00","fim":"22:00"},
   created_at=NOW()-INTERVAL '1 hour 39 minutes'

4. tipo='handoff_aberto', origem='agente', autor='IA',
   payload={"motivo":"Cliente com comportamento ambíguo, solicitou verificação visual","responsavel":"Fernando","ia_pausada_motivo":"handoff_ia"},
   created_at=NOW()-INTERVAL '30 minutes'
```

#### Eventos ATD_GUST_1 (pix em revisão):
```
1. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '2 hours'

2. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Triagem","para":"Qualificado","fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '1 hour 50 minutes'

3. tipo='transicao_estado', origem='agente', autor='IA',
   payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
   created_at=NOW()-INTERVAL '1 hour 45 minutes'

4. tipo='bloqueio_criado', origem='agente', autor='IA',
   payload={"bloqueio_id":"BLQ_BRU_02","inicio":"21:00","fim":"23:00"},
   created_at=NOW()-INTERVAL '1 hour 44 minutes'

5. tipo='pix_solicitado', origem='agente', autor='IA',
   payload={"chave":"11988880200","valor":150},
   created_at=NOW()-INTERVAL '1 hour 45 minutes'

6. tipo='pix_status_mudado', origem='pipeline_pix', autor='sistema',
   payload={"pix_id":"PIX_GUST_1","decisao":"em_revisao"},
   created_at=NOW()-INTERVAL '1 hour 10 minutes'

7. tipo='handoff_aberto', origem='pipeline_pix', autor='sistema',
   payload={"motivo":"Pix em revisão — titular divergente","responsavel":"Fernando","ia_pausada_motivo":"pix_em_revisao"},
   created_at=NOW()-INTERVAL '1 hour 10 minutes'
```

#### Eventos ATD_BRUN_2 (em execução):
```
1-3: transicoes Novo → Triagem → Qualificado → Aguardando_confirmacao (similar aos anteriores)
4. bloqueio_criado para BLQ_BRU_01
5. extracao_registrada: aviso_saida_em
6. handoff_aberto: foto de portaria, responsavel=modelo
7. transicao_estado: Aguardando_confirmacao → Em_execucao (webhook_imagem)
8. bloqueio_estado_mudado: bloqueado → em_atendimento
```

#### Eventos para ATDs fechados/perdidos históricos:
Gerar pelo menos `transicao_estado` (Novo→...→estado_final) e `fechado_registrado` ou `perdido_registrado` para:
- ATD_RICO_1, ATD_RICO_2 (fechados históricos)
- ATD_BRUN_1 (fechado histórico)
- ATD_PAUL_1 (fechado Camila)
- ATD_ADRI_1 (perdido preco)
- ATD_LUCA_1 (perdido fora_de_area)
- ATD_FELI_1 (perdido sumiu — incluir `auto_timeout_interno`)
- ATD_RODR_1 (perdido risco)
- ATD_MARC_1 (evento inicial Novo→Triagem)
- ATD_DANI_1 (evento inicial Novo)
- ATD_ANDR_1 (perdido indisponibilidade com Camila)

---

### 3.18 `barravips.envios_evolution`

Gerar registros para as principais ações do sistema. `evolution_message_id` único globalmente.

```
-- Card "Pix em revisão" para Bruna (ESC_GUST_1)
contexto='grupo_coordenacao', instance_id='evo_bruna',
remote_jid='120363222222222002@g.us', tipo='card',
atendimento_id=ATD_GUST_1, conversa_id=NULL,
payload={"titulo":"Pix em revisão","escalada_id":"ESC_GUST_1"},
evolution_message_id='3EB0CARD00000001'

-- Card "Handoff IA" para Alessia (ESC_EDUA_1)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='card',
atendimento_id=ATD_EDUA_1, conversa_id=NULL,
payload={"titulo":"Handoff IA — cliente ambíguo","escalada_id":"ESC_EDUA_1"},
evolution_message_id='3EB0CARD00000002'

-- Card "Cliente chegou" para Bruna (ESC_BRUN_1)
contexto='grupo_coordenacao', instance_id='evo_bruna',
remote_jid='120363222222222002@g.us', tipo='card',
atendimento_id=ATD_BRUN_2, conversa_id=NULL,
payload={"titulo":"Cliente chegou","escalada_id":"ESC_BRUN_1"},
evolution_message_id='3EB0CARD00000003'

-- Card "Cliente chegou" para Alessia (ESC_RICO_1)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='card',
atendimento_id=ATD_RICO_3, conversa_id=NULL,
payload={"titulo":"Cliente chegou","escalada_id":"ESC_RICO_1"},
evolution_message_id='3EB0CARD00000004'

-- Confirmação finalizado para Alessia (ATD_RICO_3)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='confirmacao',
atendimento_id=ATD_RICO_3, conversa_id=NULL,
payload={"comando":"finalizado 1500","valor_final":1500},
evolution_message_id='3EB0CONF00000001'

-- Mensagem IA para cliente Ricardo (MSG-002)
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990001@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_RICO_3, conversa_id=CNV_RICO_ALE,
payload={"tipo_msg":"texto","len":78},
evolution_message_id='3EB0IA000000001'
```

---

### 3.19 `barravips.atendimento_servicos`

Para atendimentos fechados com serviços vinculados:

**ATD_RICO_1 (Fechado, interno, 3h):**
```
programa_id=PRG_COMPLETO, duracao_id=DUR_3H, preco_snapshot=3500.00
```

**ATD_RICO_2 (Fechado, externo, ~2.5h):**
```
programa_id=PRG_COMPLETO, duracao_id=DUR_2H, preco_snapshot=2500.00
```

**ATD_RICO_3 (Fechado, interno, 2h):**
```
programa_id=PRG_MASSAGEM, duracao_id=DUR_2H, preco_snapshot=1500.00
```

**ATD_BRUN_1 (Fechado Bruna, 2h):**
```
programa_id=PRG_COMPLETO, duracao_id=DUR_2H, preco_snapshot=1800.00
programa_id=PRG_MASSAGEM, duracao_id=DUR_1H, preco_snapshot=600.00
```

**ATD_PAUL_1 (Fechado Camila, 2h):**
```
programa_id=PRG_COMPLETO, duracao_id=DUR_2H, preco_snapshot=2500.00
```

---

## 4. Cobertura de UI por Tela

### 4.1 Painel Operacional
Após seed, o painel deve exibir:
- **cards_destaque (3):**
  - `#ATD_GUST_1` (Bruna) — motivo `pix_em_revisao` — Gustavo
  - `#ATD_EDUA_1` (Alessia) — motivo `handoff_ia` — Eduardo  
  - `#ATD_BRUN_2` (Bruna) — motivo `modelo_em_atendimento` — Bruno
- **metricas_dia:**
  - abertos: 4 (ATD_MARC_1, ATD_DANI_1, ATD_EDUA_1, ATD_GUST_1)
  - fechamentos_hoje: 1 (ATD_RICO_3 = R$1.500)
  - perdas_hoje: 0 (nenhuma perda hoje)
  - pix_em_revisao_pendentes: 1 (PIX_GUST_1)
- **agenda_dia (hoje):** BLQ_ALE_02 em_atendimento, BLQ_ALE_01 bloqueado, BLQ_BRU_01 em_atendimento, BLQ_BRU_02 bloqueado

### 4.2 Atendimentos
- Kanban: 1 card em Novo, 1 em Triagem, 1 em Qualificado, 1 em Aguardando, 1 em Execução
- Lista com filtros funcionando (tipo interno/externo, IA pausada, urgência)
- Detalhe completo de ATD_BRUN_2 com mensagens, eventos, timeline

### 4.3 Clientes (CRM)
- 12 conversas listadas
- Recorrentes: Ricardo (3 fechados), Bruno (2 atendimentos)
- Filtros por motivo de perda: preco (Adriano), sumiu (Felipe), risco (Rodrigo), fora_de_area (Lucas), indisponibilidade (André)
- Gráfico de receita de Ricardo: 3 pontos (R$1.800, R$2.500, R$1.500)
- Dados calculados para DadosCliente: modelo_preferida, tipo preferido, programa preferido

### 4.4 Agenda
- Visão semana mostra BLQ_ALE_01..05 + BLQ_BRU_01..03 + BLQ_CAM_01
- Todos os 4 estados de bloqueio visíveis (bloqueado, em_atendimento, concluido, cancelado)
- Bloqueios manuais (BLQ_BRU_03) vs vinculados a atendimentos
- Dialog de edição/criação com atendimentos para busca

### 4.5 Modelos
- Lista 3 modelos (2 ativas, 1 pausada)
- Detalhe Alessia: perfil completo, 5 FAQs, 10 mídias, 7 combinações de programa+duração
- Detalhe Bruna: completo
- Detalhe Camila: pausada, menos dados
- PainelProgramas com todos os programas e durações vinculados

### 4.6 PIX
- Filtro "pendentes": PIX_GUST_1 (em_revisao, Gustavo↔Bruna)
- Filtro "rejeitado": PIX_RODR_1 (invalido, Rodrigo↔Bruna)
- Filtro "validado_auto": PIX_RICO_1, PIX_RICO_2
- Detalhe com checagens, eventos, valor e titular extraídos

### 4.7 Dashboard Analítico
- KPIs período 7d: taxa_conversao, fechamentos (4+), perdas (5+)
- Funil: Novo(1), Triagem(1), Qualificado(1), Aguardando(1), Em_execucao(1), Fechado(5+), Perdido(5+)
- Perdas por motivo: todos os 5 motivos representados (preco, sumiu, risco, fora_de_area, indisponibilidade)
- Ranking: Alessia no topo (3 fechados, ~R$5.800), Bruna (1+, R$2.400+), Camila (1, R$3.000)

---

## 5. Instruções de Geração SQL

1. **Schema:** Prefixar todas as tabelas com `barravips.` — ex: `INSERT INTO barravips.clientes (...)`
2. **UUIDs:** Usar os UUIDs literais da seção 2. Não usar `gen_random_uuid()` exceto quando explicitamente indicado.
3. **Timestamps:** Calcular relativos a `NOW()` para manter seeds sempre "atuais". Usar `NOW() - INTERVAL 'X'` em vez de timestamps absolutos.
4. **numero_curto:** Se o trigger `gen_numero_curto` estiver ativo, NÃO inserir `numero_curto` — ele é gerado automaticamente. Se não estiver, inserir explicitamente (Alessia: 1,2,3,4,5,6,7,8 / Bruna: 1,2,3,4,5 / Camila: 1,2).
5. **Constraint única em conversas:** `(cliente_id, modelo_id)` — apenas uma conversa por par. Os dados desta spec já respeitam isso.
6. **Constraint em atendimentos:** Um único atendimento ABERTO por par `(cliente_id, modelo_id)`. Atenção: Ricardo tem 3 atendimentos com Alessia, mas apenas ATD_RICO_3 é recente — os anteriores já estão Fechados, então não viola a constraint.
7. **Referência circular:** Inserir bloqueios com `atendimento_id=NULL`, inserir atendimentos com `bloqueio_id=NULL`, depois fazer os UPDATE conforme seção 3.13.
8. **trigger `atualiza_ultima_mensagem_em_conversa`:** O trigger atualiza `conversas.ultima_mensagem_em` e `ultima_mensagem_direcao` automaticamente ao INSERT em mensagens. Não fazer UPDATE manual nessas colunas depois.
9. **trigger `sync_bloqueio_estado`:** Ao UPDATE do estado do atendimento para Fechado/Perdido, o trigger atualiza automaticamente o bloqueio vinculado. Não fazer UPDATE manual no estado do bloqueio quando mudar o atendimento.
10. **`envios_evolution.evolution_message_id`:** UNIQUE globalmente. Usar padrões distintos por tipo: `3EB0SEED` (mensagens), `3EB0CARD` (cards), `3EB0CONF` (confirmações), `3EB0IA` (IA outbound).
11. **`mensagens.evolution_message_id`:** UNIQUE globalmente. Usar `3EB0SEED` + índice sequencial zero-padded 8 dígitos.
12. **`modelo_programas` PK composta:** `(modelo_id, programa_id, duracao_id)` — não pode repetir.
13. **`modelo_servicos` UNIQUE:** `(modelo_id, nome, duracao_horas)` — não repetir combinação.
14. **Wrap em transação:** Envolver todo o SQL em `BEGIN; ... COMMIT;` para rollback fácil em caso de erro.
15. **ON CONFLICT:** Usar `ON CONFLICT DO NOTHING` nos INSERTs para idempotência (permite rodar o seed múltiplas vezes).
16. **Ordem de inserção obrigatória:** usuarios → duracoes → programas → modelos → modelo_faq → modelo_midia → modelo_servicos → modelo_programas → clientes → conversas → bloqueios (sem atendimento_id) → atendimentos (sem bloqueio_id) → UPDATE bloqueios.atendimento_id → mensagens → comprovantes_pix → escaladas → eventos → envios_evolution → atendimento_servicos.

---

## 6. Verificação Pós-Seed

Executar estas queries para confirmar cobertura completa:

```sql
-- Contagem por tabela
SELECT 'usuarios' as t, count(*) FROM barravips.usuarios UNION ALL
SELECT 'modelos', count(*) FROM barravips.modelos UNION ALL
SELECT 'modelo_faq', count(*) FROM barravips.modelo_faq UNION ALL
SELECT 'modelo_midia', count(*) FROM barravips.modelo_midia UNION ALL
SELECT 'modelo_servicos', count(*) FROM barravips.modelo_servicos UNION ALL
SELECT 'modelo_programas', count(*) FROM barravips.modelo_programas UNION ALL
SELECT 'duracoes', count(*) FROM barravips.duracoes UNION ALL
SELECT 'programas', count(*) FROM barravips.programas UNION ALL
SELECT 'clientes', count(*) FROM barravips.clientes UNION ALL
SELECT 'conversas', count(*) FROM barravips.conversas UNION ALL
SELECT 'bloqueios', count(*) FROM barravips.bloqueios UNION ALL
SELECT 'atendimentos', count(*) FROM barravips.atendimentos UNION ALL
SELECT 'mensagens', count(*) FROM barravips.mensagens UNION ALL
SELECT 'comprovantes_pix', count(*) FROM barravips.comprovantes_pix UNION ALL
SELECT 'escaladas', count(*) FROM barravips.escaladas UNION ALL
SELECT 'eventos', count(*) FROM barravips.eventos UNION ALL
SELECT 'envios_evolution', count(*) FROM barravips.envios_evolution UNION ALL
SELECT 'atendimento_servicos', count(*) FROM barravips.atendimento_servicos;

-- Verificar todos os estados de atendimento estão representados
SELECT estado, count(*) FROM barravips.atendimentos GROUP BY estado ORDER BY estado;

-- Verificar todos os motivos de perda estão representados
SELECT motivo_perda, count(*) FROM barravips.atendimentos WHERE estado='Perdido' GROUP BY motivo_perda;

-- Verificar todos os estados de bloqueio estão representados
SELECT estado, count(*) FROM barravips.bloqueios GROUP BY estado;

-- Verificar comprovantes por status
SELECT decisao_pipeline, decisao_final, count(*) FROM barravips.comprovantes_pix GROUP BY 1,2;

-- Verificar escaladas abertas
SELECT count(*) FROM barravips.escaladas WHERE fechada_em IS NULL;
```

**Resultados esperados mínimos:**
- atendimentos: 15 registros, todos os 8 estados presentes
- bloqueios: 9 registros, todos os 4 estados presentes (bloqueado, em_atendimento, concluido, cancelado)
- comprovantes_pix: 4 registros (1 em_revisao, 2 validado_auto, 1 invalido)
- escaladas: 4 registros (2 abertas, 2 fechadas)
- mensagens: mínimo 40 registros
- eventos: mínimo 40 registros
- modelo_midia: 25 registros (10+10+5)
- modelo_programas: 16 registros (7+6+3)
