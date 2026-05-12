# Especificação de Seeds — Barra Vips

> Arquivo consumido por agente para gerar SQL de seeds completo.
> Usar junto com `docs/schema_barravips.md` (estrutura das tabelas, constraints, ENUMs).
> Schema Postgres: `barravips`. Todas as tabelas devem ser prefixadas com `barravips.`.

---

## 1. Objetivo

Gerar seeds de **4 cenários completos** com 1 modelo (Alessia). Cada cenário cobre a jornada real do cliente do início ao fim — com mensagens reais, todos os eventos de transição de estado, escaladas, envios_evolution, comprovantes_pix e bloqueios linkados.

### Cenários

| # | Cliente | Estado Atual | Tipo | Narrativa |
|---|---------|-------------|------|-----------|
| 1 | Ricardo Alves | `Em_execucao` (#3 de 3 atendimentos) | interno | Cliente recorrente. Chegou às 15h com foto de portaria. Alessia em atendimento agora. 2 atendimentos fechados históricos (#1 e #2). |
| 2 | Eduardo Luz | `Qualificado` + `ia_pausada=handoff_ia` | externo | Para esta noite no Windsor Barra, qualificação completa, mas pediu verificação de identidade. IA escalou; Fernando ainda não decidiu. |
| 3 | Gustavo Moraes | `Aguardando_confirmacao` + `ia_pausada=pix_em_revisao` | externo | Pix de R$ 200 recebido, titular "G. M. Silva" diverge do cadastro. Aguardando validação de Fernando. |
| 4 | Adriano Santana | `Perdido` (motivo `preco`) | externo | Recusou o valor depois de qualificar. Perdido há 3 dias. |

**Histórico do Ricardo:**
- ATD #1: Fechado −7d (interno, 3h, R$ 1.800)
- ATD #2: Fechado −1d (externo, 2h30, Pix validado, R$ 2.500)
- ATD #3: Em_execucao agora (interno, 2h, foto de portaria há ~1h)

---

## 2. UUIDs Pré-definidos

Use EXATAMENTE estes UUIDs para garantir consistência nas FKs.

```
-- USUARIO
USR_FERNANDO    = '00000000-0000-0000-0000-000000000001'

-- MODELO
MOD_ALESSIA     = 'a1000000-0000-0000-0000-000000000001'

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
CLI_EDUARDO     = 'c1000000-0000-0000-0000-000000000002'
CLI_GUSTAVO     = 'c1000000-0000-0000-0000-000000000003'
CLI_ADRIANO     = 'c1000000-0000-0000-0000-000000000004'

-- CONVERSAS
CNV_RICO_ALE    = 'f1000000-0000-0000-0000-000000000001'
CNV_EDUA_ALE    = 'f1000000-0000-0000-0000-000000000002'
CNV_GUST_ALE    = 'f1000000-0000-0000-0000-000000000003'
CNV_ADRI_ALE    = 'f1000000-0000-0000-0000-000000000004'

-- BLOQUEIOS
BLQ_ALE_01      = 'b1000000-0000-0000-0000-000000000001'
  -- hoje 20h–22h, estado=bloqueado   (Eduardo, criado ao qualificar)
BLQ_ALE_02      = 'b1000000-0000-0000-0000-000000000002'
  -- hoje 15h–17h, estado=em_atendimento (Ricardo #3, atual)
BLQ_ALE_03      = 'b1000000-0000-0000-0000-000000000003'
  -- ontem 20h–22h30, estado=concluido (Ricardo #2, externo)
BLQ_ALE_04      = 'b1000000-0000-0000-0000-000000000004'
  -- −7d 18h–21h, estado=concluido    (Ricardo #1, interno)
BLQ_ALE_05      = 'b1000000-0000-0000-0000-000000000005'
  -- hoje 21h–23h, estado=bloqueado   (Gustavo, aguardando Pix)

-- ATENDIMENTOS
ATD_RICO_1      = '91000000-0000-0000-0000-000000000001'
  -- Fechado −7d, interno, numero_curto=1
ATD_RICO_2      = '91000000-0000-0000-0000-000000000002'
  -- Fechado −1d, externo (Pix), numero_curto=2
ATD_ADRI_1      = '91000000-0000-0000-0000-000000000003'
  -- Perdido −3d, preco, numero_curto=3
ATD_RICO_3      = '91000000-0000-0000-0000-000000000004'
  -- Em_execucao hoje, interno, numero_curto=4
ATD_EDUA_1      = '91000000-0000-0000-0000-000000000005'
  -- Qualificado hoje, handoff_ia, numero_curto=5
ATD_GUST_1      = '91000000-0000-0000-0000-000000000006'
  -- Aguardando_confirmacao, pix_em_revisao, numero_curto=6

-- COMPROVANTES PIX
PIX_RICO_1      = '71000000-0000-0000-0000-000000000001'
  -- validado automaticamente (ATD_RICO_2, MSG-010)
PIX_GUST_1      = '71000000-0000-0000-0000-000000000002'
  -- em_revisao (ATD_GUST_1, MSG-032)

-- ESCALADAS
ESC_RICO_1      = '81000000-0000-0000-0000-000000000001'
  -- fechada: "cliente chegou" (ATD_RICO_1, −7d)
ESC_RICO_2      = '81000000-0000-0000-0000-000000000002'
  -- fechada: "saída confirmada" Pix validado (ATD_RICO_2, −1d)
ESC_RICO_3      = '81000000-0000-0000-0000-000000000003'
  -- aberta: "cliente chegou" (ATD_RICO_3, agora, modelo em atendimento)
ESC_EDUA_1      = '81000000-0000-0000-0000-000000000004'
  -- aberta: handoff_ia, verificação de identidade (ATD_EDUA_1)
ESC_GUST_1      = '81000000-0000-0000-0000-000000000005'
  -- aberta: pix em revisão (ATD_GUST_1)

-- ─────────────────────────────────────────────────────────────────────────────
-- REGISTROS COMPLEMENTARES — cobertura de UI (estados, filtros e modais extras)
-- ─────────────────────────────────────────────────────────────────────────────

-- MODELO COMPLEMENTAR
MOD_BRUNA       = 'a1000000-0000-0000-0000-000000000002'
  -- pausada, evolution_instance_id=NULL → cobre filtros "pausada" e "não pareada"

-- CLIENTES COMPLEMENTARES
CLI_MARCOS      = 'c1000000-0000-0000-0000-000000000005'  -- Triagem hoje (Alessia)
CLI_BRUNO       = 'c1000000-0000-0000-0000-000000000006'  -- Confirmado externo hoje (Bruna)
CLI_FELIPE      = 'c1000000-0000-0000-0000-000000000007'  -- Perdido sumiu −5d (Alessia)
CLI_RODRIGO     = 'c1000000-0000-0000-0000-000000000008'  -- Perdido risco −2d (Bruna, Pix rejeitado)

-- CONVERSAS COMPLEMENTARES
CNV_MARC_ALE    = 'f1000000-0000-0000-0000-000000000005'
CNV_BRUN_BRU    = 'f1000000-0000-0000-0000-000000000006'
CNV_FELI_ALE    = 'f1000000-0000-0000-0000-000000000007'
CNV_RODR_BRU    = 'f1000000-0000-0000-0000-000000000008'

-- BLOQUEIOS COMPLEMENTARES
BLQ_ALE_06      = 'b1000000-0000-0000-0000-000000000006'
  -- −5d 20h–22h, cancelado (auto_timeout_interno Felipe → trigger sync_bloqueio_estado)
BLQ_ALE_07      = 'b1000000-0000-0000-0000-000000000007'
  -- amanhã 10h–13h, manual, sem atendimento_id (folga — cobre origem=manual)
BLQ_BRU_01      = 'b1000000-0000-0000-0000-000000000008'
  -- hoje 21h–22h30, bloqueado (Bruno Confirmado — Bruna vai ao hotel)
BLQ_BRU_02      = 'b1000000-0000-0000-0000-000000000009'
  -- −2d 20h–21h, cancelado (Rodrigo pix rejeitado → perdido → trigger cancela)

-- ATENDIMENTOS COMPLEMENTARES
ATD_MARC_1      = '91000000-0000-0000-0000-000000000007'  -- Triagem, Alessia, numero_curto=7
ATD_BRUN_1      = '91000000-0000-0000-0000-000000000008'  -- Confirmado, Bruna, numero_curto=1
ATD_FELI_1      = '91000000-0000-0000-0000-000000000009'  -- Perdido sumiu, Alessia, numero_curto=8
ATD_RODR_1      = '91000000-0000-0000-0000-000000000010'  -- Perdido risco, Bruna, numero_curto=2

-- COMPROVANTES PIX COMPLEMENTARES
PIX_BRUN_1      = '71000000-0000-0000-0000-000000000003'
  -- validado_auto (ATD_BRUN_1, MSG-055)
PIX_RODR_1      = '71000000-0000-0000-0000-000000000004'
  -- invalido, conta_destino_invalida (ATD_RODR_1, MSG-073)

-- ESCALADAS COMPLEMENTARES
ESC_BRUN_1      = '81000000-0000-0000-0000-000000000006'
  -- aberta: "saída confirmada" (ATD_BRUN_1, Bruna vai ao Bruno às 21h)
ESC_RODR_1      = '81000000-0000-0000-0000-000000000007'
  -- fechada: pix rejeitado pelo painel (ATD_RODR_1)
```

---

## 3. Dados por Tabela (ordem de inserção)

### 3.1 `barravips.usuarios`

> O trigger `handle_new_user` normalmente cria este registro ao inserir em `auth.users`.
> Para seeds, inserir direto. O `id` deve referenciar o UUID real do Fernando no Supabase Auth.
> Use o UUID abaixo como placeholder e faça UPDATE depois se necessário.

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
id=PRG_TANTRICA, nome='Massagem Tântrica',    categoria='tantrica'
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

---

### 3.5 `barravips.modelo_faq`

```
1. pergunta='Você atende em qual região?'
   resposta='Atendo em toda Zona Sul e Barra da Tijuca. Para outras regiões consulte disponibilidade e taxa de deslocamento.'
   tags=ARRAY['localização','região','bairro']

2. pergunta='Qual o valor do programa?'
   resposta='Meus valores variam por duração e programa. O básico começa em R$ 800 por hora. Me conta o que você tem em mente!'
   tags=ARRAY['valor','preço','programa']

3. pergunta='Você é real? As fotos são suas?'
   resposta='Claro que sim! 😊 Minhas fotos são recentes e autênticas. Posso fazer uma chamada de vídeo rápida para você se certificar.'
   tags=ARRAY['verificação','autenticidade','fotos']

4. pergunta='Aceita Pix?'
   resposta='Sim! Para atendimentos externos, cobro um Pix de deslocamento antecipado. Presencialmente aceito dinheiro ou Pix.'
   tags=ARRAY['pagamento','pix','dinheiro']

5. pergunta='Qual a duração mínima?'
   resposta='A duração mínima é 1 hora. Para programas completos ou pernoite, temos opções especiais — basta perguntar!'
   tags=ARRAY['duração','tempo','programa']
```

---

### 3.6 `barravips.modelo_midia`

> 10 registros. bucket sempre `barra-media`, aprovada=true.
> object_key: `modelos/{modelo_id}/{tipo}/{arquivo}`

```
tipo=foto,  tag=apresentacao, object_key=modelos/MOD_ALESSIA/foto/apresentacao-01.jpg
tipo=foto,  tag=apresentacao, object_key=modelos/MOD_ALESSIA/foto/apresentacao-02.jpg
tipo=foto,  tag=apresentacao, object_key=modelos/MOD_ALESSIA/foto/apresentacao-03.jpg
tipo=foto,  tag=corpo,        object_key=modelos/MOD_ALESSIA/foto/corpo-01.jpg
tipo=foto,  tag=corpo,        object_key=modelos/MOD_ALESSIA/foto/corpo-02.jpg
tipo=foto,  tag=corpo,        object_key=modelos/MOD_ALESSIA/foto/corpo-03.jpg
tipo=foto,  tag=lifestyle,    object_key=modelos/MOD_ALESSIA/foto/lifestyle-01.jpg
tipo=foto,  tag=lifestyle,    object_key=modelos/MOD_ALESSIA/foto/lifestyle-02.jpg
tipo=video, tag=evento,       object_key=modelos/MOD_ALESSIA/video/evento-01.mp4
tipo=video, tag=evento,       object_key=modelos/MOD_ALESSIA/video/evento-02.mp4
```

---

### 3.7 `barravips.modelo_servicos`

```
nome='Programa 1h',  duracao_horas=1.0,  preco=1500.00, ativo=true,  ordem=1
nome='Programa 2h',  duracao_horas=2.0,  preco=2800.00, ativo=true,  ordem=2
nome='Programa 3h',  duracao_horas=3.0,  preco=3800.00, ativo=true,  ordem=3
nome='Massagem 1h',  duracao_horas=1.0,  preco=800.00,  ativo=true,  ordem=4
nome='Pernoite',     duracao_horas=12.0, preco=6000.00, ativo=true,  ordem=5
```

---

### 3.8 `barravips.modelo_programas`

```
(MOD_ALESSIA, PRG_MASSAGEM, DUR_1H,       preco=800.00)
(MOD_ALESSIA, PRG_MASSAGEM, DUR_2H,       preco=1500.00)
(MOD_ALESSIA, PRG_COMPLETO, DUR_2H,       preco=2500.00)
(MOD_ALESSIA, PRG_COMPLETO, DUR_3H,       preco=3500.00)
(MOD_ALESSIA, PRG_PERNOITE, DUR_PERNOITE, preco=5500.00)
(MOD_ALESSIA, PRG_TANTRICA, DUR_1H,       preco=1800.00)
(MOD_ALESSIA, PRG_TANTRICA, DUR_2H,       preco=3000.00)
```

---

### 3.9 `barravips.clientes`

```
id=CLI_RICARDO, telefone='+5521999990001', nome='Ricardo Alves',   primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_EDUARDO, telefone='+5521999990002', nome='Eduardo Luz',     primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_GUSTAVO, telefone='+5521999990003', nome='Gustavo Moraes',  primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_ADRIANO, telefone='+5521999990004', nome='Adriano Santana', primeiro_contato_modelo_id=MOD_ALESSIA
```

---

### 3.10 `barravips.conversas`

> `ultima_mensagem_em` e `ultima_mensagem_direcao` são atualizados pelo trigger ao inserir mensagens — definir os valores abaixo no INSERT; o trigger substituirá pelo valor da última mensagem inserida.

```
id=CNV_RICO_ALE, cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990001@s.whatsapp.net',
  recorrente=true, ultimo_motivo_perda=NULL,
  observacoes_internas='Cliente VIP. 3 atendimentos em 7 dias. Sempre pontual. Prefere interno.',
  ultima_mensagem_em=NOW()-INTERVAL '4 hours',
  ultima_mensagem_direcao='modelo_manual'

id=CNV_EDUA_ALE, cliente_id=CLI_EDUARDO, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990002@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  observacoes_internas='Cliente novo. Fez perguntas sobre autenticidade. IA escalou por comportamento ambíguo.',
  ultima_mensagem_em=NOW()-INTERVAL '30 minutes',
  ultima_mensagem_direcao='ia'

id=CNV_GUST_ALE, cliente_id=CLI_GUSTAVO, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990003@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  observacoes_internas=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '40 minutes',
  ultima_mensagem_direcao='ia'

id=CNV_ADRI_ALE, cliente_id=CLI_ADRIANO, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990004@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='preco',
  observacoes_internas=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '3 days',
  ultima_mensagem_direcao='ia'
```

---

### 3.11 `barravips.bloqueios`

> Inserir com `atendimento_id=NULL`. Após inserir atendimentos, fazer UPDATE (seção 3.13).
> Horários em BRT (UTC-3). Usar `AT TIME ZONE 'America/Sao_Paulo'` ou calcular offset manualmente.

```
id=BLQ_ALE_01, modelo_id=MOD_ALESSIA,
  inicio=(NOW()::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=(NOW()::date + TIME '22:00') AT TIME ZONE 'America/Sao_Paulo',
  estado='bloqueado', origem='ia', atendimento_id=NULL, observacao=NULL

id=BLQ_ALE_02, modelo_id=MOD_ALESSIA,
  inicio=(NOW()::date + TIME '15:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=(NOW()::date + TIME '17:00') AT TIME ZONE 'America/Sao_Paulo',
  estado='em_atendimento', origem='ia', atendimento_id=NULL, observacao=NULL

id=BLQ_ALE_03, modelo_id=MOD_ALESSIA,
  inicio=((NOW()-INTERVAL '1 day')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=((NOW()-INTERVAL '1 day')::date + TIME '22:30') AT TIME ZONE 'America/Sao_Paulo',
  estado='concluido', origem='ia', atendimento_id=NULL, observacao=NULL

id=BLQ_ALE_04, modelo_id=MOD_ALESSIA,
  inicio=((NOW()-INTERVAL '7 days')::date + TIME '18:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=((NOW()-INTERVAL '7 days')::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo',
  estado='concluido', origem='ia', atendimento_id=NULL, observacao=NULL

id=BLQ_ALE_05, modelo_id=MOD_ALESSIA,
  inicio=(NOW()::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=(NOW()::date + TIME '23:00') AT TIME ZONE 'America/Sao_Paulo',
  estado='bloqueado', origem='ia', atendimento_id=NULL, observacao=NULL
```

---

### 3.12 `barravips.atendimentos`

> `numero_curto` é gerado por trigger. Se o trigger não estiver ativo, inserir explicitamente (sequencial por modelo).
> Inserir `bloqueio_id=NULL`; atualizar via UPDATE na seção 3.13.

#### ATD_RICO_1 — Ricardo + Alessia — FECHADO −7d (interno, 3h)

```
id=ATD_RICO_1, numero_curto=1,
cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA, conversa_id=CNV_RICO_ALE,
bloqueio_id=NULL,
estado='Fechado', tipo_atendimento='interno', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '7 days')::date,
horario_desejado='18:00', duracao_horas=3.0,
endereco=NULL, bairro=NULL, tipo_local=NULL, referencia_local=NULL,
forma_pagamento='dinheiro',
valor_acordado=1500.00, valor_final=1800.00,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=((NOW()-INTERVAL '7 days')::date + TIME '17:45') AT TIME ZONE 'America/Sao_Paulo',
foto_portaria_em=((NOW()-INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo',
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL, motivo_escalada=NULL,
resumo_operacional='Ricardo Alves, interno, 3h. Chegou às 18h08 (foto de portaria). Alessia encerrou com R$ 1.800.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='comando_grupo',
created_at=NOW()-INTERVAL '7 days'-INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '7 days'+INTERVAL '3 hours'
```

#### ATD_RICO_2 — Ricardo + Alessia — FECHADO −1d (externo, 2h30, Pix validado)

```
id=ATD_RICO_2, numero_curto=2,
cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA, conversa_id=CNV_RICO_ALE,
bloqueio_id=NULL,
estado='Fechado', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '1 day')::date,
horario_desejado='20:00', duracao_horas=2.5,
endereco='Av. Atlântica, 1702, Quarto 1404', bairro='Copacabana',
tipo_local='hotel', referencia_local='JW Marriott — Posto 4',
forma_pagamento='pix',
valor_acordado=2200.00, valor_final=2500.00,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='validado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL, motivo_escalada=NULL,
resumo_operacional='Ricardo Alves, externo, JW Marriott Copacabana. Pix de R$ 200 validado automaticamente. Encerrou com R$ 2.500.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='comando_grupo',
created_at=NOW()-INTERVAL '1 day'-INTERVAL '3 hours',
updated_at=NOW()-INTERVAL '1 day'+INTERVAL '2 hours 30 minutes'
```

#### ATD_ADRI_1 — Adriano + Alessia — PERDIDO −3d (preco)

```
id=ATD_ADRI_1, numero_curto=3,
cliente_id=CLI_ADRIANO, modelo_id=MOD_ALESSIA, conversa_id=CNV_ADRI_ALE,
bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '2 days')::date,
horario_desejado='20:00', duracao_horas=1.0,
endereco=NULL, bairro='Ipanema', tipo_local='apartamento', referencia_local=NULL,
forma_pagamento='pix',
valor_acordado=1500.00, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='preco', motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL, motivo_escalada=NULL,
resumo_operacional='Adriano Santana, externo, Ipanema, 1h. Recusou R$ 1.500. Perdido por preço.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":false,"envia_pix":false,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='painel_fernando',
created_at=NOW()-INTERVAL '3 days'-INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '3 days'
```

#### ATD_RICO_3 — Ricardo + Alessia — EM EXECUÇÃO (interno, hoje, Alessia em atendimento agora)

```
id=ATD_RICO_3, numero_curto=4,
cliente_id=CLI_RICARDO, modelo_id=MOD_ALESSIA, conversa_id=CNV_RICO_ALE,
bloqueio_id=NULL,
estado='Em_execucao', tipo_atendimento='interno', urgencia='imediato',
data_desejada=NOW()::date,
horario_desejado='15:00', duracao_horas=2.0,
endereco=NULL, bairro=NULL, tipo_local=NULL, referencia_local=NULL,
forma_pagamento='dinheiro',
valor_acordado=1500.00, valor_final=NULL,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=(NOW()::date + TIME '14:40') AT TIME ZONE 'America/Sao_Paulo',
foto_portaria_em=(NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo',
ia_pausada=true, ia_pausada_motivo='modelo_em_atendimento',
responsavel_atual='modelo',
proxima_acao_esperada='Alessia encerrar com "finalizado [valor]" ao término.',
motivo_escalada='Cliente chegou (foto de portaria). Alessia em atendimento.',
resumo_operacional='Ricardo Alves, recorrente, interno, 2h. Chegou às 15h05. Alessia conduzindo o atendimento.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='webhook_imagem',
created_at=NOW()-INTERVAL '5 hours',
updated_at=NOW()-INTERVAL '4 hours'
```

#### ATD_EDUA_1 — Eduardo + Alessia — QUALIFICADO (handoff_ia, para esta noite)

```
id=ATD_EDUA_1, numero_curto=5,
cliente_id=CLI_EDUARDO, modelo_id=MOD_ALESSIA, conversa_id=CNV_EDUA_ALE,
bloqueio_id=NULL,
estado='Qualificado', tipo_atendimento='externo', urgencia='agendado',
data_desejada=NOW()::date,
horario_desejado='20:00', duracao_horas=2.0,
endereco=NULL, bairro='Barra da Tijuca', tipo_local='hotel',
referencia_local='Hotel Windsor Barra',
forma_pagamento='pix',
valor_acordado=2500.00, valor_final=NULL,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=true, ia_pausada_motivo='handoff_ia',
responsavel_atual='Fernando',
proxima_acao_esperada='Fernando avaliar o cliente e decidir se prossegue, recusa ou orienta a IA.',
motivo_escalada='Cliente solicitou foto ao vivo com data de hoje para verificar autenticidade. Comportamento incomum antes de confirmar.',
resumo_operacional='Eduardo Luz, novo, externo. Hotel Windsor Barra, hoje 20h, 2h, R$ 2.500. Qualificação completa. Cliente pediu verificação de identidade.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='extracao_ia',
created_at=NOW()-INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '30 minutes'
```

#### ATD_GUST_1 — Gustavo + Alessia — AGUARDANDO CONFIRMAÇÃO (pix_em_revisao)

```
id=ATD_GUST_1, numero_curto=6,
cliente_id=CLI_GUSTAVO, modelo_id=MOD_ALESSIA, conversa_id=CNV_GUST_ALE,
bloqueio_id=NULL,
estado='Aguardando_confirmacao', tipo_atendimento='externo', urgencia='agendado',
data_desejada=NOW()::date,
horario_desejado='21:00', duracao_horas=2.0,
endereco=NULL, bairro='Ipanema', tipo_local='hotel',
referencia_local='Hotel Ipanema Inn — Rua Vinícius de Moraes',
forma_pagamento='pix',
valor_acordado=1500.00, valor_final=NULL,
percentual_repasse_snapshot=40.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='em_revisao',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=true, ia_pausada_motivo='pix_em_revisao',
responsavel_atual='Fernando',
proxima_acao_esperada='Fernando validar ou recusar o comprovante Pix pelo painel.',
motivo_escalada='Pix de R$ 200 recebido. Titular "G. M. Silva" não confere com o nome cadastrado "Gustavo Moraes".',
resumo_operacional='Gustavo Moraes, novo, externo. Hotel Ipanema Inn, hoje 21h, 2h, R$ 1.500. Pix em revisão.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='pipeline_pix',
created_at=NOW()-INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '40 minutes'
```

---

### 3.13 UPDATE pós-inserção (referências circulares)

```sql
-- Associar bloqueios aos atendimentos
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000004' WHERE id = 'b1000000-0000-0000-0000-000000000002'; -- BLQ_ALE_02 → ATD_RICO_3
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000002' WHERE id = 'b1000000-0000-0000-0000-000000000003'; -- BLQ_ALE_03 → ATD_RICO_2
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000001' WHERE id = 'b1000000-0000-0000-0000-000000000004'; -- BLQ_ALE_04 → ATD_RICO_1
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000005' WHERE id = 'b1000000-0000-0000-0000-000000000001'; -- BLQ_ALE_01 → ATD_EDUA_1
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000006' WHERE id = 'b1000000-0000-0000-0000-000000000005'; -- BLQ_ALE_05 → ATD_GUST_1

-- Associar bloqueios nos atendimentos
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000004' WHERE id = '91000000-0000-0000-0000-000000000001'; -- ATD_RICO_1 → BLQ_ALE_04
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000003' WHERE id = '91000000-0000-0000-0000-000000000002'; -- ATD_RICO_2 → BLQ_ALE_03
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000002' WHERE id = '91000000-0000-0000-0000-000000000004'; -- ATD_RICO_3 → BLQ_ALE_02
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000001' WHERE id = '91000000-0000-0000-0000-000000000005'; -- ATD_EDUA_1 → BLQ_ALE_01
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000005' WHERE id = '91000000-0000-0000-0000-000000000006'; -- ATD_GUST_1 → BLQ_ALE_05
-- ATD_ADRI_1 não tem bloqueio (perdido antes de confirmar)
```

---

### 3.14 `barravips.mensagens`

> Trigger `atualiza_ultima_mensagem_em_conversa` atualiza `conversas.ultima_mensagem_em` e `ultima_mensagem_direcao` automaticamente ao inserir.
> `evolution_message_id` único: `'3EB0SEED' + LPAD(n::text, 8, '0')` — ex: `3EB0SEED00000001`.
> `media_object_key` para imagens: `'mensagens/{conversa_id}/{evolution_message_id}.jpg'`

---

#### CNV_RICO_ALE — Mensagens do Ricardo (ATDs 1, 2 e 3)

> Conversa única (par único), mensagens de 3 atendimentos diferentes.

**ATD_RICO_1 (−7 dias, interno):**

```
MSG-001: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '7 days'-INTERVAL '2 hours',
  conteudo='Oi Alessia, posso ir aí hoje à noite tipo umas 18h?'

MSG-002: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '7 days'-INTERVAL '1 hour 59 minutes',
  conteudo='Oi Ricardo! Pode sim, 18h está ótimo 😊 Me avisa quando estiver saindo.'

MSG-003: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_1,
  direcao='cliente', tipo='texto',
  created_at=((NOW()-INTERVAL '7 days')::date + TIME '17:45') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='Saindo agora, em 20 minutinhos estou aí.'

MSG-004: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_1,
  direcao='cliente', tipo='imagem',
  media_object_key='mensagens/f1000000-0000-0000-0000-000000000001/3EB0SEED00000004.jpg',
  created_at=((NOW()-INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='[foto da portaria]'

MSG-005: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_1,
  direcao='modelo_manual', tipo='texto',
  created_at=((NOW()-INTERVAL '7 days')::date + TIME '18:10') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='Oi Ricardo 🌹 Pode subir, apê 301!'

MSG-006: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_1,
  direcao='modelo_manual', tipo='texto',
  created_at=((NOW()-INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='finalizado 1800'
```

**ATD_RICO_2 (−1 dia, externo com Pix):**

```
MSG-007: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_2,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 day'-INTERVAL '3 hours',
  conteudo='Oi Alessia, estou no JW Marriott em Copacabana. Posso te chamar para hoje à noite, umas 20h?'

MSG-008: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_2,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 58 minutes',
  conteudo='Que ótima escolha, Ricardo 😍 Pode ser! Para 2h em hotel, R$ 2.500. Para confirmar, preciso do Pix de deslocamento de R$ 200 para a chave 21999990100 (Alessia Viana). Pode mandar?'

MSG-009: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_2,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 40 minutes',
  conteudo='Mando agora.'

MSG-010: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_2,
  direcao='cliente', tipo='imagem',
  media_object_key='mensagens/f1000000-0000-0000-0000-000000000001/3EB0SEED00000010.jpg',
  created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 30 minutes',
  conteudo='[comprovante de Pix R$ 200]'
  -- ATENÇÃO: este é o mensagem_id referenciado por PIX_RICO_1

MSG-011: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_2,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours',
  conteudo='Pix confirmado ✅ Estarei aí às 20h pontualmente! Me manda o número do quarto quando eu chegar 🌸'

MSG-012: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_2,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 day'-INTERVAL '1 hour',
  conteudo='Quarto 1404, pode vir.'

MSG-013: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_2,
  direcao='modelo_manual', tipo='texto',
  created_at=((NOW()-INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='finalizado 2500'
```

**ATD_RICO_3 (hoje, interno, Em_execucao):**

```
MSG-014: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '5 hours',
  conteudo='Oi Alessia! É o Ricardo. Consigo ir aí hoje à tarde, tipo 15h. Tá bom?'

MSG-015: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '4 hours 58 minutes',
  conteudo='Ricardo!! Que saudade 🥰 Pode vir sim, 15h ótimo! Me avisa quando estiver saindo.'

MSG-016: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='cliente', tipo='texto',
  created_at=(NOW()::date + TIME '14:40') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='Saindo agora, em uns 20 minutos chego.'

MSG-017: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='cliente', tipo='imagem',
  media_object_key='mensagens/f1000000-0000-0000-0000-000000000001/3EB0SEED00000017.jpg',
  created_at=(NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='[foto da portaria]'
  -- ATENÇÃO: dispara handoff implícito → ESC_RICO_3, IA pausada, bloqueio → em_atendimento

MSG-018: conversa=CNV_RICO_ALE, atendimento=ATD_RICO_3,
  direcao='modelo_manual', tipo='texto',
  created_at=(NOW()::date + TIME '15:07') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='Oi amor, pode subir! Apê 301 🌸'
```

---

#### CNV_EDUA_ALE — Mensagens do Eduardo (ATD_EDUA_1)

```
MSG-019: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '2 hours',
  conteudo='Boa tarde. Quero marcar para hoje à noite em hotel.'

MSG-020: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '1 hour 58 minutes',
  conteudo='Boa tarde! Adoro 😊 Qual horário e qual hotel? Me conta os detalhes.'

MSG-021: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 hour 50 minutes',
  conteudo='Hotel Windsor na Barra, 20h, umas 2 horas.'

MSG-022: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '1 hour 48 minutes',
  conteudo='Perfeito! Para 2h em hotel na Barra, R$ 2.500 incluindo deslocamento. Para confirmar, preciso de um Pix de R$ 200. Combinado?'

MSG-023: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 hour 40 minutes',
  conteudo='Antes de confirmar, quero saber se você é real de verdade. Já fui enganado antes.'

MSG-024: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '1 hour 38 minutes',
  conteudo='Entendo sua preocupação! Minhas fotos são todas autênticas 😊 Posso fazer uma videochamada rápida antes de confirmarmos — fica mais fácil!'

MSG-025: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '35 minutes',
  conteudo='Não quero chamada. Preciso de uma foto ao vivo com seu rosto e a data de hoje escrita num papel.'

MSG-026: conversa=CNV_EDUA_ALE, atendimento=ATD_EDUA_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '30 minutes',
  conteudo='Claro! Me dá um instante que preparo aqui 😊'
  -- Após esta mensagem: IA escalou para Fernando (handoff_ia), ia_pausada=true
```

---

#### CNV_GUST_ALE — Mensagens do Gustavo (ATD_GUST_1)

```
MSG-027: conversa=CNV_GUST_ALE, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '2 hours',
  conteudo='Oi Alessia, tô querendo ir num hotel hoje à noite tipo 21h. Você atende externo?'

MSG-028: conversa=CNV_GUST_ALE, atendimento=ATD_GUST_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '1 hour 58 minutes',
  conteudo='Oi! Atendo sim 😊 Qual hotel e em qual bairro?'

MSG-029: conversa=CNV_GUST_ALE, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 hour 50 minutes',
  conteudo='Hotel Ipanema Inn, na Rua Vinícius de Moraes. Quero 2 horas.'

MSG-030: conversa=CNV_GUST_ALE, atendimento=ATD_GUST_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '1 hour 45 minutes',
  conteudo='Ótima região! Para 2h em hotel, R$ 1.500. Para confirmar, Pix de deslocamento de R$ 200 para a chave 21999990100 (Alessia Viana). Topo?'

MSG-031: conversa=CNV_GUST_ALE, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 hour 20 minutes',
  conteudo='Topo. Mandando agora.'

MSG-032: conversa=CNV_GUST_ALE, atendimento=ATD_GUST_1,
  direcao='cliente', tipo='imagem',
  media_object_key='mensagens/f1000000-0000-0000-0000-000000000003/3EB0SEED00000032.jpg',
  created_at=NOW()-INTERVAL '1 hour 15 minutes',
  conteudo='[comprovante de Pix R$ 200]'
  -- ATENÇÃO: este é o mensagem_id referenciado por PIX_GUST_1

MSG-033: conversa=CNV_GUST_ALE, atendimento=ATD_GUST_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '40 minutes',
  conteudo='Recebi! Só verificando aqui e já confirmo 🌸'
  -- Após esta mensagem: pipeline sinalizou em_revisao, ia_pausada=true
```

---

#### CNV_ADRI_ALE — Mensagens do Adriano (ATD_ADRI_1, −3 dias)

```
MSG-034: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '2 hours',
  conteudo='Olá, vi o número no site. Você tem disponibilidade essa semana?'

MSG-035: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 58 minutes',
  conteudo='Oi! Tenho sim 😊 O que você tem em mente? Me conta horário e onde você prefere.'

MSG-036: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 50 minutes',
  conteudo='Pensava no meu apartamento em Ipanema, amanhã à noite, 1 hora.'

MSG-037: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 45 minutes',
  conteudo='Ipanema ótimo! Para 1h em apartamento, R$ 1.500. Pix de deslocamento de R$ 150. Combinado?'

MSG-038: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 30 minutes',
  conteudo='R$ 1.500 por 1h tá caro demais. Não tem como baixar?'

MSG-039: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 28 minutes',
  conteudo='Entendo! Esse é o valor padrão por hora 😊 Posso oferecer 2h por R$ 2.800, que fica mais em conta por hora. O que acha?'

MSG-040: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 15 minutes',
  conteudo='Não, não compensa. Deixa pra lá.'

MSG-041: conversa=CNV_ADRI_ALE, atendimento=ATD_ADRI_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 13 minutes',
  conteudo='Entendido! Se mudar de ideia, é só me chamar. Até mais! 😊'
  -- Fernando registra perdido preco no painel após esta mensagem
```

---

### 3.15 `barravips.comprovantes_pix`

> Inserir APÓS as mensagens (FK → mensagens.id).

```
id=PIX_RICO_1, atendimento_id=ATD_RICO_2, mensagem_id=(id de MSG-010),
  valor_extraido=200.00,
  chave_extraida='21999990100',
  titular_extraido='Alessia Viana',
  timestamp_extraido=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 30 minutes',
  decisao_pipeline='validado',
  motivo_em_revisao=NULL,
  decisao_final=NULL, decisao_final_por=NULL,
  created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 29 minutes'

id=PIX_GUST_1, atendimento_id=ATD_GUST_1, mensagem_id=(id de MSG-032),
  valor_extraido=200.00,
  chave_extraida='21999990100',
  titular_extraido='G. M. Silva',
  timestamp_extraido=NOW()-INTERVAL '1 hour 15 minutes',
  decisao_pipeline='em_revisao',
  motivo_em_revisao='Titular "G. M. Silva" não confere com o nome cadastrado do cliente "Gustavo Moraes".',
  decisao_final=NULL, decisao_final_por=NULL,
  created_at=NOW()-INTERVAL '1 hour 10 minutes'
```

---

### 3.16 `barravips.escaladas`

> Inserir APÓS os atendimentos (FK → atendimentos.id).

```
-- FECHADA: "cliente chegou" − Ricardo #1 (−7 dias)
id=ESC_RICO_1, atendimento_id=ATD_RICO_1, responsavel='modelo',
  motivo='Cliente chegou (foto de portaria). Alessia em atendimento.',
  resumo_operacional='Ricardo Alves, interno, 3h. Foto de portaria às 18h08. Alessia conduzindo.',
  acao_esperada='Encerrar com "finalizado [valor]" ao término.',
  card_message_id='3EB0CARD00000001',
  aberta_em=((NOW()-INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo',
  fechada_em=((NOW()-INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo',
  fechada_por=NULL, fechada_canal='grupo_coordenacao'

-- FECHADA: "saída confirmada" − Ricardo #2 (−1 dia, externo, Pix validado)
id=ESC_RICO_2, atendimento_id=ATD_RICO_2, responsavel='modelo',
  motivo='Pix de deslocamento validado automaticamente. Alessia a caminho.',
  resumo_operacional='Ricardo Alves, externo, JW Marriott Copacabana, 20h. Pix de R$ 200 validado.',
  acao_esperada='Encerrar com "finalizado [valor]" ao término.',
  card_message_id='3EB0CARD00000002',
  aberta_em=NOW()-INTERVAL '1 day'-INTERVAL '2 hours',
  fechada_em=((NOW()-INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo',
  fechada_por=NULL, fechada_canal='grupo_coordenacao'

-- ABERTA: "cliente chegou" − Ricardo #3 (hoje, Em_execucao)
id=ESC_RICO_3, atendimento_id=ATD_RICO_3, responsavel='modelo',
  motivo='Cliente chegou (foto de portaria). Alessia em atendimento.',
  resumo_operacional='Ricardo Alves, recorrente, interno. Foto de portaria às 15h05. IA pausada, Alessia conduzindo.',
  acao_esperada='Encerrar com "finalizado [valor]" ao término do atendimento.',
  card_message_id='3EB0CARD00000003',
  aberta_em=(NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo',
  fechada_em=NULL, fechada_por=NULL, fechada_canal=NULL

-- ABERTA: handoff_ia − Eduardo (Qualificado)
id=ESC_EDUA_1, atendimento_id=ATD_EDUA_1, responsavel='Fernando',
  motivo='Cliente solicitou foto ao vivo com data para verificar autenticidade. Comportamento incomum.',
  resumo_operacional='Eduardo Luz, novo, externo. Hotel Windsor Barra, hoje 20h, 2h, R$ 2.500. Qualificação completa. Cliente pediu verificação de identidade antes de confirmar.',
  acao_esperada='Avaliar o perfil e decidir: prosseguir (devolver para IA), recusar ou orientar IA. Se prosseguir, IA solicitará o Pix.',
  card_message_id='3EB0CARD00000004',
  aberta_em=NOW()-INTERVAL '30 minutes',
  fechada_em=NULL, fechada_por=NULL, fechada_canal=NULL

-- ABERTA: pix_em_revisao − Gustavo (Aguardando_confirmacao)
id=ESC_GUST_1, atendimento_id=ATD_GUST_1, responsavel='Fernando',
  motivo='Pix de R$ 200 recebido. Titular "G. M. Silva" não confere com "Gustavo Moraes".',
  resumo_operacional='Gustavo Moraes, novo, externo. Hotel Ipanema Inn, hoje 21h, 2h, R$ 1.500. Pix em revisão.',
  acao_esperada='Validar ou recusar o comprovante pelo painel. Se validado, IA confirma o atendimento.',
  card_message_id='3EB0CARD00000005',
  aberta_em=NOW()-INTERVAL '1 hour 10 minutes',
  fechada_em=NULL, fechada_por=NULL, fechada_canal=NULL
```

---

### 3.17 `barravips.eventos`

> Append-only. Toda transição gera `transicao_estado`. Toda abertura de handoff gera `handoff_aberto`.
> `autor='sistema'` para cron/pipeline; `'IA'` para agente; `'Fernando'`/`'modelo'` para humanos.

---

#### Eventos — ATD_RICO_1 (ciclo completo interno, −7 dias)

```
E01: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_1,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '7 days'-INTERVAL '1 hour 59 minutes'

E02: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_1,
     payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '7 days'-INTERVAL '1 hour 50 minutes'

E03: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_1,
     payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '7 days'-INTERVAL '1 hour 48 minutes'

E04: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_RICO_1,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000004","inicio":"18:00","fim":"21:00"},
     created_at=NOW()-INTERVAL '7 days'-INTERVAL '1 hour 47 minutes'

E05: tipo='extracao_registrada', origem='agente', autor='IA', atendimento_id=ATD_RICO_1,
     payload={"campo":"aviso_saida_em","valor":"agora"},
     created_at=((NOW()-INTERVAL '7 days')::date + TIME '17:45') AT TIME ZONE 'America/Sao_Paulo'

E06: tipo='handoff_aberto', origem='agente', autor='IA', atendimento_id=ATD_RICO_1,
     payload={"motivo":"Cliente chegou (foto de portaria)","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"},
     created_at=((NOW()-INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'

E07: tipo='transicao_estado', origem='agente', autor='sistema', atendimento_id=ATD_RICO_1,
     payload={"de":"Aguardando_confirmacao","para":"Em_execucao","trigger":"foto_portaria","fonte_decisao":"webhook_imagem"},
     created_at=((NOW()-INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'

E08: tipo='bloqueio_estado_mudado', origem='agente', autor='sistema', atendimento_id=ATD_RICO_1,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000004","de":"bloqueado","para":"em_atendimento"},
     created_at=((NOW()-INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'

E09: tipo='fechado_registrado', origem='grupo_coordenacao', autor='modelo', atendimento_id=ATD_RICO_1,
     payload={"comando":"finalizado 1800","valor_final":1800},
     created_at=((NOW()-INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'

E10: tipo='transicao_estado', origem='grupo_coordenacao', autor='modelo', atendimento_id=ATD_RICO_1,
     payload={"de":"Em_execucao","para":"Fechado","fonte_decisao":"comando_grupo"},
     created_at=((NOW()-INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'

E11: tipo='bloqueio_estado_mudado', origem='agente', autor='sistema', atendimento_id=ATD_RICO_1,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000004","de":"em_atendimento","para":"concluido"},
     created_at=((NOW()-INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'
```

---

#### Eventos — ATD_RICO_2 (ciclo completo externo com Pix, −1 dia)

```
E12: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_2,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 58 minutes'

E13: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_2,
     payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 48 minutes'

E14: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_2,
     payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 45 minutes'

E15: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_RICO_2,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000003","inicio":"20:00","fim":"22:30"},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 44 minutes'

E16: tipo='pix_solicitado', origem='agente', autor='IA', atendimento_id=ATD_RICO_2,
     payload={"chave":"21999990100","valor":200},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours 43 minutes'

E17: tipo='pix_status_mudado', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_RICO_2,
     payload={"pix_id":"71000000-0000-0000-0000-000000000001","decisao":"validado"},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours'

E18: tipo='handoff_aberto', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_RICO_2,
     payload={"motivo":"Pix de deslocamento validado automaticamente","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours'

E19: tipo='transicao_estado', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_RICO_2,
     payload={"de":"Aguardando_confirmacao","para":"Confirmado","fonte_decisao":"pipeline_pix"},
     created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours'

E20: tipo='bloqueio_estado_mudado', origem='cron', autor='sistema', atendimento_id=ATD_RICO_2,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000003","de":"bloqueado","para":"em_atendimento"},
     created_at=((NOW()-INTERVAL '1 day')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo'

E21: tipo='transicao_estado', origem='cron', autor='sistema', atendimento_id=ATD_RICO_2,
     payload={"de":"Confirmado","para":"Em_execucao","fonte_decisao":"cron_em_execucao"},
     created_at=((NOW()-INTERVAL '1 day')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo'

E22: tipo='fechado_registrado', origem='grupo_coordenacao', autor='modelo', atendimento_id=ATD_RICO_2,
     payload={"comando":"finalizado 2500","valor_final":2500},
     created_at=((NOW()-INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'

E23: tipo='transicao_estado', origem='grupo_coordenacao', autor='modelo', atendimento_id=ATD_RICO_2,
     payload={"de":"Em_execucao","para":"Fechado","fonte_decisao":"comando_grupo"},
     created_at=((NOW()-INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'

E24: tipo='bloqueio_estado_mudado', origem='agente', autor='sistema', atendimento_id=ATD_RICO_2,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000003","de":"em_atendimento","para":"concluido"},
     created_at=((NOW()-INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'
```

---

#### Eventos — ATD_ADRI_1 (Perdido preco, −3 dias)

```
E25: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_ADRI_1,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 58 minutes'

E26: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_ADRI_1,
     payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":false},"fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 45 minutes'

E27: tipo='perdido_registrado', origem='painel', autor='Fernando', atendimento_id=ATD_ADRI_1,
     payload={"motivo":"preco","obs":null},
     created_at=NOW()-INTERVAL '3 days'-INTERVAL '30 minutes'

E28: tipo='transicao_estado', origem='painel', autor='Fernando', atendimento_id=ATD_ADRI_1,
     payload={"de":"Qualificado","para":"Perdido","fonte_decisao":"painel_fernando"},
     created_at=NOW()-INTERVAL '3 days'-INTERVAL '30 minutes'
```

---

#### Eventos — ATD_RICO_3 (Em_execucao agora, interno)

```
E29: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_3,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '4 hours 58 minutes'

E30: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_3,
     payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '4 hours 50 minutes'

E31: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RICO_3,
     payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '4 hours 45 minutes'

E32: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_RICO_3,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000002","inicio":"15:00","fim":"17:00"},
     created_at=NOW()-INTERVAL '4 hours 44 minutes'

E33: tipo='extracao_registrada', origem='agente', autor='IA', atendimento_id=ATD_RICO_3,
     payload={"campo":"aviso_saida_em","valor":"agora"},
     created_at=(NOW()::date + TIME '14:40') AT TIME ZONE 'America/Sao_Paulo'

E34: tipo='handoff_aberto', origem='agente', autor='IA', atendimento_id=ATD_RICO_3,
     payload={"motivo":"Cliente chegou (foto de portaria)","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"},
     created_at=(NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'

E35: tipo='transicao_estado', origem='agente', autor='sistema', atendimento_id=ATD_RICO_3,
     payload={"de":"Aguardando_confirmacao","para":"Em_execucao","trigger":"foto_portaria","fonte_decisao":"webhook_imagem"},
     created_at=(NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'

E36: tipo='bloqueio_estado_mudado', origem='agente', autor='sistema', atendimento_id=ATD_RICO_3,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000002","de":"bloqueado","para":"em_atendimento"},
     created_at=(NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'
```

---

#### Eventos — ATD_EDUA_1 (Qualificado + handoff_ia)

```
E37: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_EDUA_1,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 hour 58 minutes'

E38: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_EDUA_1,
     payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 hour 48 minutes'

E39: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_EDUA_1,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000001","inicio":"20:00","fim":"22:00"},
     created_at=NOW()-INTERVAL '1 hour 47 minutes'

E40: tipo='handoff_aberto', origem='agente', autor='IA', atendimento_id=ATD_EDUA_1,
     payload={"motivo":"Cliente solicitou foto ao vivo com data. Comportamento incomum antes de confirmar.","responsavel":"Fernando","ia_pausada_motivo":"handoff_ia"},
     created_at=NOW()-INTERVAL '30 minutes'
```

---

#### Eventos — ATD_GUST_1 (Aguardando_confirmacao + pix_em_revisao)

```
E41: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_GUST_1,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 hour 58 minutes'

E42: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_GUST_1,
     payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 hour 50 minutes'

E43: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_GUST_1,
     payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '1 hour 45 minutes'

E44: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_GUST_1,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000005","inicio":"21:00","fim":"23:00"},
     created_at=NOW()-INTERVAL '1 hour 44 minutes'

E45: tipo='pix_solicitado', origem='agente', autor='IA', atendimento_id=ATD_GUST_1,
     payload={"chave":"21999990100","valor":200},
     created_at=NOW()-INTERVAL '1 hour 43 minutes'

E46: tipo='pix_status_mudado', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_GUST_1,
     payload={"pix_id":"71000000-0000-0000-0000-000000000002","decisao":"em_revisao"},
     created_at=NOW()-INTERVAL '1 hour 10 minutes'

E47: tipo='handoff_aberto', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_GUST_1,
     payload={"motivo":"Pix em revisão — titular divergente do cadastro","responsavel":"Fernando","ia_pausada_motivo":"pix_em_revisao"},
     created_at=NOW()-INTERVAL '1 hour 10 minutes'
```

---

### 3.18 `barravips.envios_evolution`

> Registra apenas o que o backend enviou (IA + cards + confirmações).
> Mensagens `modelo_manual` NÃO têm entrada aqui — vêm do WhatsApp da Alessia.
> `evolution_message_id` único globalmente.

#### Cards no grupo de coordenação

```
-- ESC_RICO_1: "Cliente chegou" (ATD_RICO_1, −7d)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='card',
atendimento_id=ATD_RICO_1, conversa_id=NULL,
payload={"titulo":"Cliente chegou","escalada_id":"81000000-0000-0000-0000-000000000001"},
evolution_message_id='3EB0CARD00000001',
created_at=((NOW()-INTERVAL '7 days')::date + TIME '18:08') AT TIME ZONE 'America/Sao_Paulo'

-- ESC_RICO_2: "Saída confirmada" (ATD_RICO_2, −1d, Pix validado)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='card',
atendimento_id=ATD_RICO_2, conversa_id=NULL,
payload={"titulo":"Saída confirmada","escalada_id":"81000000-0000-0000-0000-000000000002"},
evolution_message_id='3EB0CARD00000002',
created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours'

-- ESC_RICO_3: "Cliente chegou" (ATD_RICO_3, hoje)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='card',
atendimento_id=ATD_RICO_3, conversa_id=NULL,
payload={"titulo":"Cliente chegou","escalada_id":"81000000-0000-0000-0000-000000000003"},
evolution_message_id='3EB0CARD00000003',
created_at=(NOW()::date + TIME '15:05') AT TIME ZONE 'America/Sao_Paulo'

-- ESC_EDUA_1: "Handoff IA" (ATD_EDUA_1)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='card',
atendimento_id=ATD_EDUA_1, conversa_id=NULL,
payload={"titulo":"Handoff IA — verificação de identidade","escalada_id":"81000000-0000-0000-0000-000000000004"},
evolution_message_id='3EB0CARD00000004',
created_at=NOW()-INTERVAL '30 minutes'

-- ESC_GUST_1: "Pix em revisão" (ATD_GUST_1)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='card',
atendimento_id=ATD_GUST_1, conversa_id=NULL,
payload={"titulo":"Pix em revisão","escalada_id":"81000000-0000-0000-0000-000000000005"},
evolution_message_id='3EB0CARD00000005',
created_at=NOW()-INTERVAL '1 hour 10 minutes'
```

#### Confirmações no grupo de coordenação

```
-- Confirmação "finalizado 1800" (ATD_RICO_1)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='confirmacao',
atendimento_id=ATD_RICO_1, conversa_id=NULL,
payload={"comando":"finalizado 1800","valor_final":1800},
evolution_message_id='3EB0CONF00000001',
created_at=((NOW()-INTERVAL '7 days')::date + TIME '21:08') AT TIME ZONE 'America/Sao_Paulo'

-- Confirmação "finalizado 2500" (ATD_RICO_2)
contexto='grupo_coordenacao', instance_id='evo_alessia',
remote_jid='120363111111111001@g.us', tipo='confirmacao',
atendimento_id=ATD_RICO_2, conversa_id=NULL,
payload={"comando":"finalizado 2500","valor_final":2500},
evolution_message_id='3EB0CONF00000002',
created_at=((NOW()-INTERVAL '1 day')::date + TIME '22:35') AT TIME ZONE 'America/Sao_Paulo'
```

#### Mensagens da IA na conversa do cliente (seleção representativa)

> Incluir ao menos uma por atendimento para que o `envios_evolution` não fique vazio.

```
-- MSG-002 (ATD_RICO_1): IA confirma 18h
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990001@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_RICO_1, conversa_id=CNV_RICO_ALE,
payload={"tipo_msg":"texto","len":61},
evolution_message_id='3EB0IA000000001',
created_at=NOW()-INTERVAL '7 days'-INTERVAL '1 hour 59 minutes'

-- MSG-011 (ATD_RICO_2): IA confirma Pix validado
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990001@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_RICO_2, conversa_id=CNV_RICO_ALE,
payload={"tipo_msg":"texto","len":82},
evolution_message_id='3EB0IA000000002',
created_at=NOW()-INTERVAL '1 day'-INTERVAL '2 hours'

-- MSG-015 (ATD_RICO_3): IA recebe Ricardo
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990001@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_RICO_3, conversa_id=CNV_RICO_ALE,
payload={"tipo_msg":"texto","len":68},
evolution_message_id='3EB0IA000000003',
created_at=NOW()-INTERVAL '4 hours 58 minutes'

-- MSG-026 (ATD_EDUA_1): IA diz "um instante" antes de escalar
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990002@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_EDUA_1, conversa_id=CNV_EDUA_ALE,
payload={"tipo_msg":"texto","len":44},
evolution_message_id='3EB0IA000000004',
created_at=NOW()-INTERVAL '30 minutes'

-- MSG-033 (ATD_GUST_1): IA confirma recebimento do Pix
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990003@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_GUST_1, conversa_id=CNV_GUST_ALE,
payload={"tipo_msg":"texto","len":46},
evolution_message_id='3EB0IA000000005',
created_at=NOW()-INTERVAL '40 minutes'

-- MSG-041 (ATD_ADRI_1): IA despede Adriano
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990004@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_ADRI_1, conversa_id=CNV_ADRI_ALE,
payload={"tipo_msg":"texto","len":57},
evolution_message_id='3EB0IA000000006',
created_at=NOW()-INTERVAL '3 days'-INTERVAL '1 hour 13 minutes'
```

---

### 3.19 `barravips.atendimento_servicos`

> Apenas para atendimentos `Fechado` com serviço identificado.

```
-- ATD_RICO_1 (Fechado −7d, interno, 3h — Programa Completo 3h)
atendimento_id=ATD_RICO_1, programa_id=PRG_COMPLETO, duracao_id=DUR_3H,
preco_snapshot=3500.00

-- ATD_RICO_2 (Fechado −1d, externo, 2h — Programa Completo 2h)
atendimento_id=ATD_RICO_2, programa_id=PRG_COMPLETO, duracao_id=DUR_2H,
preco_snapshot=2500.00
```

---

## 3.20 Registros Complementares (cobertura de UI extra)

> Objetivo: cobrir estados e filtros ausentes nas seeds principais — segundo modelo (`pausada`), estados `Triagem` e `Confirmado` no kanban, `Perdido-sumiu` e `Perdido-risco`, bloqueio `manual`, bloqueio `cancelado` por auto-timeout, Pix `invalido` rejeitado por Fernando.

---

### 3.20.1 `barravips.modelos` — Bruna Martins (pausada)

```
id                      = MOD_BRUNA
nome                    = 'Bruna Martins'
numero_whatsapp         = '+5521999990200'
evolution_instance_id   = NULL
status                  = 'pausada'
valor_padrao            = 1200.00
percentual_repasse      = 35.00
chave_pix               = '21999990200'
titular_chave           = 'Bruna Martins'
idade                   = 26
idiomas                 = ARRAY['pt-BR']
localizacao_operacional = 'Barra da Tijuca e Recreio, Rio de Janeiro'
tipo_atendimento_aceito = ARRAY['externo']
foto_perfil_object_key  = 'modelos/a1000000-0000-0000-0000-000000000002/perfil/perfil.jpg'
coordenacao_chat_id     = NULL
coordenacao_verificada_em = NULL
```

---

### 3.20.2 `barravips.modelo_faq` — Bruna (2 FAQs)

```
1. modelo_id=MOD_BRUNA,
   pergunta='Você faz externo?'
   resposta='Faço sim, em hotéis e flats na Barra e Recreio. Cobro Pix de deslocamento antecipado.'
   tags=ARRAY['externo','hotel','deslocamento']

2. modelo_id=MOD_BRUNA,
   pergunta='Qual o valor?'
   resposta='A partir de R$ 1.200 por hora. Depende do programa e duração. Me fala o que você quer!'
   tags=ARRAY['valor','preço']
```

---

### 3.20.3 `barravips.modelo_midia` — Bruna (5 fotos)

```
tipo=foto, tag=apresentacao, object_key=modelos/a1000000-0000-0000-0000-000000000002/foto/apresentacao-01.jpg
tipo=foto, tag=apresentacao, object_key=modelos/a1000000-0000-0000-0000-000000000002/foto/apresentacao-02.jpg
tipo=foto, tag=corpo,        object_key=modelos/a1000000-0000-0000-0000-000000000002/foto/corpo-01.jpg
tipo=foto, tag=corpo,        object_key=modelos/a1000000-0000-0000-0000-000000000002/foto/corpo-02.jpg
tipo=foto, tag=lifestyle,    object_key=modelos/a1000000-0000-0000-0000-000000000002/foto/lifestyle-01.jpg
```

---

### 3.20.4 `barravips.modelo_servicos` — Bruna

```
nome='Programa 1h', duracao_horas=1.0,  preco=1200.00, ativo=true, ordem=1
nome='Programa 2h', duracao_horas=2.0,  preco=2200.00, ativo=true, ordem=2
```

---

### 3.20.5 `barravips.modelo_programas` — Bruna

```
(MOD_BRUNA, PRG_COMPLETO, DUR_1H, preco=1200.00)
(MOD_BRUNA, PRG_COMPLETO, DUR_2H, preco=2200.00)
```

---

### 3.20.6 `barravips.clientes` — complementares

```
id=CLI_MARCOS,  telefone='+5521999990005', nome='Marcos Lima',      primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_BRUNO,   telefone='+5521999990006', nome='Bruno Carvalho',   primeiro_contato_modelo_id=MOD_BRUNA
id=CLI_FELIPE,  telefone='+5521999990007', nome='Felipe Ramos',     primeiro_contato_modelo_id=MOD_ALESSIA
id=CLI_RODRIGO, telefone='+5521999990008', nome='Rodrigo Teixeira', primeiro_contato_modelo_id=MOD_BRUNA
```

---

### 3.20.7 `barravips.conversas` — complementares

```
id=CNV_MARC_ALE, cliente_id=CLI_MARCOS, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990005@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  observacoes_internas=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '1 hour',
  ultima_mensagem_direcao='ia'

id=CNV_BRUN_BRU, cliente_id=CLI_BRUNO, modelo_id=MOD_BRUNA,
  evolution_chat_id='5521999990006@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda=NULL,
  observacoes_internas=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '3 hours',
  ultima_mensagem_direcao='ia'

id=CNV_FELI_ALE, cliente_id=CLI_FELIPE, modelo_id=MOD_ALESSIA,
  evolution_chat_id='5521999990007@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='sumiu',
  observacoes_internas=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '5 days'-INTERVAL '2 hours',
  ultima_mensagem_direcao='ia'

id=CNV_RODR_BRU, cliente_id=CLI_RODRIGO, modelo_id=MOD_BRUNA,
  evolution_chat_id='5521999990008@s.whatsapp.net',
  recorrente=false, ultimo_motivo_perda='risco',
  observacoes_internas=NULL,
  ultima_mensagem_em=NOW()-INTERVAL '2 days'-INTERVAL '1 hour',
  ultima_mensagem_direcao='ia'
```

---

### 3.20.8 `barravips.bloqueios` — complementares

> Inserir com `atendimento_id=NULL`. UPDATE após atendimentos (seção 3.20.10).

```
id=BLQ_ALE_06, modelo_id=MOD_ALESSIA,
  inicio=((NOW()-INTERVAL '5 days')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=((NOW()-INTERVAL '5 days')::date + TIME '22:00') AT TIME ZONE 'America/Sao_Paulo',
  estado='cancelado', origem='ia', atendimento_id=NULL, observacao=NULL
  -- cancelado por auto_timeout: Felipe enviou aviso de saída mas não enviou foto de portaria

id=BLQ_ALE_07, modelo_id=MOD_ALESSIA,
  inicio=((NOW()+INTERVAL '1 day')::date + TIME '10:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=((NOW()+INTERVAL '1 day')::date + TIME '13:00') AT TIME ZONE 'America/Sao_Paulo',
  estado='bloqueado', origem='manual', atendimento_id=NULL, observacao='Folga — consulta médica'
  -- bloqueio manual sem atendimento_id (cobre filtro origem=manual)

id=BLQ_BRU_01, modelo_id=MOD_BRUNA,
  inicio=(NOW()::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=(NOW()::date + TIME '22:30') AT TIME ZONE 'America/Sao_Paulo',
  estado='bloqueado', origem='ia', atendimento_id=NULL, observacao=NULL
  -- Bruno Confirmado para 21h; Bruna a caminho

id=BLQ_BRU_02, modelo_id=MOD_BRUNA,
  inicio=((NOW()-INTERVAL '2 days')::date + TIME '20:00') AT TIME ZONE 'America/Sao_Paulo',
  fim=((NOW()-INTERVAL '2 days')::date + TIME '21:00') AT TIME ZONE 'America/Sao_Paulo',
  estado='cancelado', origem='ia', atendimento_id=NULL, observacao=NULL
  -- cancelado: Rodrigo com Pix rejeitado → Perdido → trigger sync_bloqueio_estado cancela
```

---

### 3.20.9 `barravips.atendimentos` — complementares

#### ATD_MARC_1 — Marcos + Alessia — TRIAGEM (hoje, interno, imediato)

```
id=ATD_MARC_1, numero_curto=7,
cliente_id=CLI_MARCOS, modelo_id=MOD_ALESSIA, conversa_id=CNV_MARC_ALE,
bloqueio_id=NULL,
estado='Triagem', tipo_atendimento='interno', urgencia='imediato',
data_desejada=NOW()::date,
horario_desejado=NULL, duracao_horas=NULL,
endereco=NULL, bairro=NULL, tipo_local=NULL, referencia_local=NULL,
forma_pagamento=NULL,
valor_acordado=NULL, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada='IA coletar horário, local e programa desejados.',
motivo_escalada=NULL,
resumo_operacional='Marcos Lima, novo. Demonstrou interesse; IA em triagem.',
sinais_qualificacao='{"informa_horario":false,"informa_local":false,"aceita_valor":false,"envia_pix":false,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='extracao_ia',
created_at=NOW()-INTERVAL '1 hour',
updated_at=NOW()-INTERVAL '55 minutes'
```

#### ATD_BRUN_1 — Bruno + Bruna — CONFIRMADO (hoje, externo, 21h)

```
id=ATD_BRUN_1, numero_curto=1,
cliente_id=CLI_BRUNO, modelo_id=MOD_BRUNA, conversa_id=CNV_BRUN_BRU,
bloqueio_id=NULL,
estado='Confirmado', tipo_atendimento='externo', urgencia='agendado',
data_desejada=NOW()::date,
horario_desejado='21:00', duracao_horas=1.5,
endereco=NULL, bairro='Barra da Tijuca', tipo_local='hotel',
referencia_local='Hotel Praia Ipanema — Av. Vieira Souto',
forma_pagamento='pix',
valor_acordado=1200.00, valor_final=NULL,
percentual_repasse_snapshot=35.00,
motivo_perda=NULL, motivo_perda_obs=NULL,
pix_status='validado',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=true, ia_pausada_motivo='modelo_em_atendimento',
responsavel_atual='modelo',
proxima_acao_esperada='Bruna sair ao hotel às 21h. Encerrar com "finalizado [valor]" ao término.',
motivo_escalada='Pix de deslocamento validado automaticamente. Bruna a caminho.',
resumo_operacional='Bruno Carvalho, externo, Hotel Praia Ipanema Barra, hoje 21h, 1h30. Pix confirmado.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='pipeline_pix',
created_at=NOW()-INTERVAL '4 hours',
updated_at=NOW()-INTERVAL '3 hours'
```

#### ATD_FELI_1 — Felipe + Alessia — PERDIDO (sumiu, −5 dias, interno)

```
id=ATD_FELI_1, numero_curto=8,
cliente_id=CLI_FELIPE, modelo_id=MOD_ALESSIA, conversa_id=CNV_FELI_ALE,
bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='interno', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '5 days')::date,
horario_desejado='20:00', duracao_horas=2.0,
endereco=NULL, bairro=NULL, tipo_local=NULL, referencia_local=NULL,
forma_pagamento='dinheiro',
valor_acordado=1500.00, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='sumiu', motivo_perda_obs=NULL,
pix_status='nao_solicitado',
aviso_saida_em=((NOW()-INTERVAL '5 days')::date + TIME '19:50') AT TIME ZONE 'America/Sao_Paulo',
foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL, motivo_escalada=NULL,
resumo_operacional='Felipe Ramos, novo, interno. Avisou saída às 19h50, não enviou foto de portaria. Marcado como Perdido (sumiu) por timeout automático.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":false,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='cron_timeout',
created_at=NOW()-INTERVAL '5 days'-INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '5 days'+INTERVAL '20 minutes'
```

#### ATD_RODR_1 — Rodrigo + Bruna — PERDIDO (risco, −2 dias, externo)

```
id=ATD_RODR_1, numero_curto=2,
cliente_id=CLI_RODRIGO, modelo_id=MOD_BRUNA, conversa_id=CNV_RODR_BRU,
bloqueio_id=NULL,
estado='Perdido', tipo_atendimento='externo', urgencia='agendado',
data_desejada=(NOW()-INTERVAL '2 days')::date,
horario_desejado='20:00', duracao_horas=1.0,
endereco=NULL, bairro='Recreio', tipo_local='apartamento', referencia_local=NULL,
forma_pagamento='pix',
valor_acordado=1200.00, valor_final=NULL,
percentual_repasse_snapshot=NULL,
motivo_perda='risco', motivo_perda_obs='Pix com conta de destino inválida.',
pix_status='invalido',
aviso_saida_em=NULL, foto_portaria_em=NULL,
ia_pausada=false, ia_pausada_motivo=NULL,
responsavel_atual='IA',
proxima_acao_esperada=NULL, motivo_escalada=NULL,
resumo_operacional='Rodrigo Teixeira, externo, Recreio. Pix rejeitado (conta_destino_invalida). Fernando marcou como Perdido por risco.',
sinais_qualificacao='{"informa_horario":true,"informa_local":true,"aceita_valor":true,"envia_pix":true,"responde_objetivamente":true}',
fonte_decisao_ultima_transicao='painel_fernando',
created_at=NOW()-INTERVAL '2 days'-INTERVAL '2 hours',
updated_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour'
```

---

### 3.20.10 UPDATE pós-inserção (bloqueios complementares)

```sql
-- Associar bloqueios aos atendimentos complementares
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000009' WHERE id = 'b1000000-0000-0000-0000-000000000006'; -- BLQ_ALE_06 → ATD_FELI_1
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000008' WHERE id = 'b1000000-0000-0000-0000-000000000008'; -- BLQ_BRU_01 → ATD_BRUN_1
UPDATE barravips.bloqueios SET atendimento_id = '91000000-0000-0000-0000-000000000010' WHERE id = 'b1000000-0000-0000-0000-000000000009'; -- BLQ_BRU_02 → ATD_RODR_1
-- BLQ_ALE_07: sem atendimento_id (manual/folga)
-- ATD_MARC_1: sem bloqueio (Triagem, horário não confirmado ainda)

-- Associar atendimentos aos bloqueios
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000006' WHERE id = '91000000-0000-0000-0000-000000000009'; -- ATD_FELI_1 → BLQ_ALE_06
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000008' WHERE id = '91000000-0000-0000-0000-000000000008'; -- ATD_BRUN_1 → BLQ_BRU_01
UPDATE barravips.atendimentos SET bloqueio_id = 'b1000000-0000-0000-0000-000000000009' WHERE id = '91000000-0000-0000-0000-000000000010'; -- ATD_RODR_1 → BLQ_BRU_02
```

---

### 3.20.11 `barravips.mensagens` — complementares

> evolution_message_id dos clientes: `'3EB0SEED' + LPAD(n::text, 8, '0')` continuando de MSG-042.

#### CNV_MARC_ALE — Marcos + Alessia (ATD_MARC_1, Triagem)

```
MSG-042: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '1 hour',
  conteudo='Oi, você está disponível hoje?'

MSG-043: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '58 minutes',
  conteudo='Oi! Estou sim 😊 O que você tem em mente? Me conta mais!'

MSG-044: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '55 minutes',
  conteudo='Queria ir aí visitar... é no apartamento de vocês mesmo?'

MSG-045: conversa=CNV_MARC_ALE, atendimento=ATD_MARC_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '53 minutes',
  conteudo='É sim, aqui mesmo, bem tranquilo 😊 Em qual horário você pensou?'
```

---

#### CNV_BRUN_BRU — Bruno + Bruna (ATD_BRUN_1, Confirmado externo)

```
MSG-046: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '4 hours',
  conteudo='Oi, você faz externo? Estou num hotel na Barra.'

MSG-047: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '3 hours 58 minutes',
  conteudo='Faço sim! 😊 Qual hotel e para quando?'

MSG-048: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '3 hours 50 minutes',
  conteudo='Hotel Praia Ipanema, Av. Vieira Souto. Hoje à noite, umas 21h, 1 hora e meia.'

MSG-049: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '3 hours 48 minutes',
  conteudo='Boa localização! Para 1h30 em hotel, R$ 1.200. Para confirmar, preciso do Pix de deslocamento de R$ 150 para a chave 21999990200 (Bruna Martins). Combina?'

MSG-050: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_1,
  direcao='cliente', tipo='imagem',
  media_object_key='mensagens/f1000000-0000-0000-0000-000000000006/3EB0SEED00000050.jpg',
  created_at=NOW()-INTERVAL '3 hours 30 minutes',
  conteudo='[comprovante de Pix R$ 150]'
  -- ATENÇÃO: este é o mensagem_id referenciado por PIX_BRUN_1

MSG-051: conversa=CNV_BRUN_BRU, atendimento=ATD_BRUN_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '3 hours',
  conteudo='Pix confirmado ✅ Estarei no hotel às 21h pontualmente! Me manda o número do quarto quando eu chegar 🌸'
```

---

#### CNV_FELI_ALE — Felipe + Alessia (ATD_FELI_1, Perdido sumiu, −5 dias)

```
MSG-052: conversa=CNV_FELI_ALE, atendimento=ATD_FELI_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '5 days'-INTERVAL '2 hours',
  conteudo='Oi Alessia, quero ir aí hoje à noite pelas 20h.'

MSG-053: conversa=CNV_FELI_ALE, atendimento=ATD_FELI_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 58 minutes',
  conteudo='Oi! Pode vir sim, 20h está ótimo 😊 Para 2h aqui em casa, R$ 1.500 em dinheiro. Combinado?'

MSG-054: conversa=CNV_FELI_ALE, atendimento=ATD_FELI_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 50 minutes',
  conteudo='Combinado! Qual o endereço?'

MSG-055: conversa=CNV_FELI_ALE, atendimento=ATD_FELI_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 48 minutes',
  conteudo='Passo o endereço quando você estiver saindo, pode ser? Me avisa!'

MSG-056: conversa=CNV_FELI_ALE, atendimento=ATD_FELI_1,
  direcao='cliente', tipo='texto',
  created_at=((NOW()-INTERVAL '5 days')::date + TIME '19:50') AT TIME ZONE 'America/Sao_Paulo',
  conteudo='Tô saindo agora.'
  -- aviso_saida_em registrado. Nenhuma foto de portaria enviada em 30min → auto_timeout → Perdido sumiu
```

---

#### CNV_RODR_BRU — Rodrigo + Bruna (ATD_RODR_1, Perdido risco, −2 dias)

```
MSG-057: conversa=CNV_RODR_BRU, atendimento=ATD_RODR_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '2 days'-INTERVAL '2 hours',
  conteudo='Oi, você faz externo no Recreio?'

MSG-058: conversa=CNV_RODR_BRU, atendimento=ATD_RODR_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 58 minutes',
  conteudo='Faço sim! 😊 Para onde exatamente e qual horário?'

MSG-059: conversa=CNV_RODR_BRU, atendimento=ATD_RODR_1,
  direcao='cliente', tipo='texto', created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 50 minutes',
  conteudo='Meu apartamento no Recreio, amanhã às 20h, 1 hora.'

MSG-060: conversa=CNV_RODR_BRU, atendimento=ATD_RODR_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 45 minutes',
  conteudo='Pode ser! Para 1h em apartamento, R$ 1.200. Pix de deslocamento de R$ 120 para a chave 21999990200 (Bruna Martins). Me manda?'

MSG-061: conversa=CNV_RODR_BRU, atendimento=ATD_RODR_1,
  direcao='cliente', tipo='imagem',
  media_object_key='mensagens/f1000000-0000-0000-0000-000000000008/3EB0SEED00000061.jpg',
  created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 30 minutes',
  conteudo='[comprovante de Pix R$ 120]'
  -- ATENÇÃO: este é o mensagem_id referenciado por PIX_RODR_1

MSG-062: conversa=CNV_RODR_BRU, atendimento=ATD_RODR_1,
  direcao='ia', tipo='texto', created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 25 minutes',
  conteudo='Recebi! Verificando aqui e já confirmo 🌸'
  -- Pipeline detecta conta_destino_invalida → em_revisao → escalada para Fernando
  -- Fernando rejeita via painel → Perdido risco
```

---

### 3.20.12 `barravips.comprovantes_pix` — complementares

```
id=PIX_BRUN_1, atendimento_id=ATD_BRUN_1, mensagem_id=(id de MSG-050),
  valor_extraido=150.00,
  chave_extraida='21999990200',
  titular_extraido='Bruno Carvalho',
  timestamp_extraido=NOW()-INTERVAL '3 hours 30 minutes',
  decisao_pipeline='validado',
  motivo_em_revisao=NULL,
  decisao_final=NULL, decisao_final_por=NULL,
  created_at=NOW()-INTERVAL '3 hours 25 minutes'

id=PIX_RODR_1, atendimento_id=ATD_RODR_1, mensagem_id=(id de MSG-061),
  valor_extraido=120.00,
  chave_extraida='21999990200',
  titular_extraido='R. Teixeira',
  timestamp_extraido=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 30 minutes',
  decisao_pipeline='em_revisao',
  motivo_em_revisao='Conta de destino da chave Pix não confere com a chave cadastrada da modelo (conta_destino_invalida).',
  decisao_final='invalido', decisao_final_por=USR_FERNANDO,
  created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 25 minutes'
```

---

### 3.20.13 `barravips.escaladas` — complementares

```
-- ABERTA: "saída confirmada" − Bruno/Bruna (ATD_BRUN_1, Confirmado)
id=ESC_BRUN_1, atendimento_id=ATD_BRUN_1, responsavel='modelo',
  motivo='Pix de deslocamento validado automaticamente. Bruna a caminho.',
  resumo_operacional='Bruno Carvalho, externo, Hotel Praia Ipanema Barra, hoje 21h, 1h30. Pix de R$ 150 validado.',
  acao_esperada='Encerrar com "finalizado [valor]" ao término.',
  card_message_id='3EB0CARD00000006',
  aberta_em=NOW()-INTERVAL '3 hours',
  fechada_em=NULL, fechada_por=NULL, fechada_canal=NULL

-- FECHADA: pix rejeitado − Rodrigo/Bruna (ATD_RODR_1)
id=ESC_RODR_1, atendimento_id=ATD_RODR_1, responsavel='Fernando',
  motivo='Pix com conta de destino inválida. Fernando rejeitou e marcou como Perdido.',
  resumo_operacional='Rodrigo Teixeira, externo, Recreio. Pix de R$ 120 rejeitado — conta_destino_invalida.',
  acao_esperada='Fernando avaliar e decidir sobre o Pix inválido.',
  card_message_id='3EB0CARD00000007',
  aberta_em=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 25 minutes',
  fechada_em=NOW()-INTERVAL '2 days'-INTERVAL '1 hour',
  fechada_por=USR_FERNANDO, fechada_canal='painel'
```

---

### 3.20.14 `barravips.eventos` — complementares

#### Eventos — ATD_MARC_1 (Triagem)

```
EN1: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_MARC_1,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '58 minutes'
```

#### Eventos — ATD_BRUN_1 (ciclo externo Confirmado)

```
EN2: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_BRUN_1,
     payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '3 hours 58 minutes'

EN3: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_BRUN_1,
     payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '3 hours 50 minutes'

EN4: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_BRUN_1,
     payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
     created_at=NOW()-INTERVAL '3 hours 48 minutes'

EN5: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_BRUN_1,
     payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000008","inicio":"21:00","fim":"22:30"},
     created_at=NOW()-INTERVAL '3 hours 47 minutes'

EN6: tipo='pix_solicitado', origem='agente', autor='IA', atendimento_id=ATD_BRUN_1,
     payload={"chave":"21999990200","valor":150},
     created_at=NOW()-INTERVAL '3 hours 46 minutes'

EN7: tipo='pix_status_mudado', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_BRUN_1,
     payload={"pix_id":"71000000-0000-0000-0000-000000000003","decisao":"validado"},
     created_at=NOW()-INTERVAL '3 hours'

EN8: tipo='handoff_aberto', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_BRUN_1,
     payload={"motivo":"Pix de deslocamento validado automaticamente","responsavel":"modelo","ia_pausada_motivo":"modelo_em_atendimento"},
     created_at=NOW()-INTERVAL '3 hours'

EN9: tipo='transicao_estado', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_BRUN_1,
     payload={"de":"Aguardando_confirmacao","para":"Confirmado","fonte_decisao":"pipeline_pix"},
     created_at=NOW()-INTERVAL '3 hours'
```

#### Eventos — ATD_FELI_1 (Perdido sumiu, auto_timeout)

```
EN10: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_FELI_1,
      payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
      created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 58 minutes'

EN11: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_FELI_1,
      payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
      created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 50 minutes'

EN12: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_FELI_1,
      payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
      created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 48 minutes'

EN13: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_FELI_1,
      payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000006","inicio":"20:00","fim":"22:00"},
      created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 47 minutes'

EN14: tipo='extracao_registrada', origem='agente', autor='IA', atendimento_id=ATD_FELI_1,
      payload={"campo":"aviso_saida_em","valor":"agora"},
      created_at=((NOW()-INTERVAL '5 days')::date + TIME '19:50') AT TIME ZONE 'America/Sao_Paulo'

EN15: tipo='transicao_estado', origem='cron', autor='sistema', atendimento_id=ATD_FELI_1,
      payload={"de":"Aguardando_confirmacao","para":"Perdido","trigger":"auto_timeout_interno","motivo_perda":"sumiu","fonte_decisao":"cron_timeout"},
      created_at=((NOW()-INTERVAL '5 days')::date + TIME '20:20') AT TIME ZONE 'America/Sao_Paulo'

EN16: tipo='bloqueio_estado_mudado', origem='cron', autor='sistema', atendimento_id=ATD_FELI_1,
      payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000006","de":"bloqueado","para":"cancelado"},
      created_at=((NOW()-INTERVAL '5 days')::date + TIME '20:20') AT TIME ZONE 'America/Sao_Paulo'
```

#### Eventos — ATD_RODR_1 (Perdido risco, Pix invalido)

```
EN17: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RODR_1,
      payload={"de":"Novo","para":"Triagem","fonte_decisao":"extracao_ia"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 58 minutes'

EN18: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RODR_1,
      payload={"de":"Triagem","para":"Qualificado","sinais":{"informa_horario":true,"informa_local":true,"aceita_valor":true},"fonte_decisao":"extracao_ia"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 50 minutes'

EN19: tipo='transicao_estado', origem='agente', autor='IA', atendimento_id=ATD_RODR_1,
      payload={"de":"Qualificado","para":"Aguardando_confirmacao","fonte_decisao":"extracao_ia"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 48 minutes'

EN20: tipo='bloqueio_criado', origem='agente', autor='IA', atendimento_id=ATD_RODR_1,
      payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000009","inicio":"20:00","fim":"21:00"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 47 minutes'

EN21: tipo='pix_solicitado', origem='agente', autor='IA', atendimento_id=ATD_RODR_1,
      payload={"chave":"21999990200","valor":120},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 46 minutes'

EN22: tipo='pix_status_mudado', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_RODR_1,
      payload={"pix_id":"71000000-0000-0000-0000-000000000004","decisao":"em_revisao","motivo":"conta_destino_invalida"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 25 minutes'

EN23: tipo='handoff_aberto', origem='pipeline_pix', autor='sistema', atendimento_id=ATD_RODR_1,
      payload={"motivo":"Pix inválido — conta de destino não confere com chave da modelo","responsavel":"Fernando","ia_pausada_motivo":"pix_em_revisao"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 25 minutes'

EN24: tipo='pix_status_mudado', origem='painel', autor='Fernando', atendimento_id=ATD_RODR_1,
      payload={"pix_id":"71000000-0000-0000-0000-000000000004","decisao":"invalido"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour'

EN25: tipo='perdido_registrado', origem='painel', autor='Fernando', atendimento_id=ATD_RODR_1,
      payload={"motivo":"risco","obs":"Pix com conta de destino inválida."},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour'

EN26: tipo='transicao_estado', origem='painel', autor='Fernando', atendimento_id=ATD_RODR_1,
      payload={"de":"Aguardando_confirmacao","para":"Perdido","fonte_decisao":"painel_fernando"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour'

EN27: tipo='bloqueio_estado_mudado', origem='agente', autor='sistema', atendimento_id=ATD_RODR_1,
      payload={"bloqueio_id":"b1000000-0000-0000-0000-000000000009","de":"bloqueado","para":"cancelado"},
      created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour'
```

---

### 3.20.15 `barravips.envios_evolution` — complementares (Bruna)

> Bruna tem `evolution_instance_id=NULL` (pausada). Registrar os envios da fase antes da pausa.
> `instance_id='evo_bruna'` — valor histórico capturado no momento do envio.

#### Cards no grupo de coordenação de Bruna

```
-- ESC_BRUN_1: "Saída confirmada" (ATD_BRUN_1, Pix validado)
contexto='grupo_coordenacao', instance_id='evo_bruna',
remote_jid='120363222222222001@g.us', tipo='card',
atendimento_id=ATD_BRUN_1, conversa_id=NULL,
payload={"titulo":"Saída confirmada","escalada_id":"81000000-0000-0000-0000-000000000006"},
evolution_message_id='3EB0CARD00000006',
created_at=NOW()-INTERVAL '3 hours'

-- ESC_RODR_1: "Pix inválido" (ATD_RODR_1)
contexto='grupo_coordenacao', instance_id='evo_bruna',
remote_jid='120363222222222001@g.us', tipo='card',
atendimento_id=ATD_RODR_1, conversa_id=NULL,
payload={"titulo":"Pix em revisão — conta_destino_invalida","escalada_id":"81000000-0000-0000-0000-000000000007"},
evolution_message_id='3EB0CARD00000007',
created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 25 minutes'
```

#### Mensagens da IA de Bruna nas conversas

```
-- MSG-043 (ATD_MARC_1): IA Alessia responde Marcos (Triagem)
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990005@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_MARC_1, conversa_id=CNV_MARC_ALE,
payload={"tipo_msg":"texto","len":47},
evolution_message_id='3EB0IA000000007',
created_at=NOW()-INTERVAL '58 minutes'

-- MSG-047 (ATD_BRUN_1): IA Bruna responde Bruno
contexto='conversa_cliente', instance_id='evo_bruna',
remote_jid='5521999990006@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_BRUN_1, conversa_id=CNV_BRUN_BRU,
payload={"tipo_msg":"texto","len":33},
evolution_message_id='3EB0IA000000008',
created_at=NOW()-INTERVAL '3 hours 58 minutes'

-- MSG-051 (ATD_BRUN_1): IA Bruna confirma Pix validado
contexto='conversa_cliente', instance_id='evo_bruna',
remote_jid='5521999990006@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_BRUN_1, conversa_id=CNV_BRUN_BRU,
payload={"tipo_msg":"texto","len":79},
evolution_message_id='3EB0IA000000009',
created_at=NOW()-INTERVAL '3 hours'

-- MSG-053 (ATD_FELI_1): IA Alessia confirma horário Felipe
contexto='conversa_cliente', instance_id='evo_alessia',
remote_jid='5521999990007@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_FELI_1, conversa_id=CNV_FELI_ALE,
payload={"tipo_msg":"texto","len":72},
evolution_message_id='3EB0IA000000010',
created_at=NOW()-INTERVAL '5 days'-INTERVAL '1 hour 58 minutes'

-- MSG-062 (ATD_RODR_1): IA Bruna recebe comprovante Rodrigo
contexto='conversa_cliente', instance_id='evo_bruna',
remote_jid='5521999990008@s.whatsapp.net', tipo='ia',
atendimento_id=ATD_RODR_1, conversa_id=CNV_RODR_BRU,
payload={"tipo_msg":"texto","len":42},
evolution_message_id='3EB0IA000000011',
created_at=NOW()-INTERVAL '2 days'-INTERVAL '1 hour 25 minutes'
```

---

## 4. Cobertura de UI por Tela

### 4.1 Painel Operacional

Após seed, o painel exibe:

**Cards de destaque (ia_pausada=true):**
- `#4` ATD_RICO_3 — `modelo_em_atendimento` — Ricardo (Alessia, interno, desde 15h05)
- `#5` ATD_EDUA_1 — `handoff_ia` — Eduardo (Alessia, externo, Windsor 20h)
- `#6` ATD_GUST_1 — `pix_em_revisao` — Gustavo (Alessia, externo, Ipanema Inn 21h)
- `#8` ATD_BRUN_1 — `modelo_em_atendimento` — Bruno (Bruna, externo, Confirmado 21h)

**Métricas do dia:**
- Abertos hoje: 4 (ATD_RICO_3, ATD_EDUA_1, ATD_GUST_1, ATD_BRUN_1)
- Fechamentos hoje: 0
- Perdas hoje: 0
- Pix pendentes: 1 (PIX_GUST_1 em_revisao)

**Agenda hoje:** BLQ_ALE_02 em_atendimento (15h–17h), BLQ_ALE_01 bloqueado (20h–22h), BLQ_ALE_05 bloqueado (21h–23h), BLQ_BRU_01 bloqueado (21h–22h30)

---

### 4.2 Atendimentos

**Kanban — todos os estados cobertos:**

| Estado | Atendimento | Modelo | Cliente |
|--------|-------------|--------|---------|
| Triagem | ATD_MARC_1 | Alessia | Marcos |
| Qualificado | ATD_EDUA_1 | Alessia | Eduardo |
| Aguardando_confirmacao | ATD_GUST_1 | Alessia | Gustavo |
| Confirmado | ATD_BRUN_1 | Bruna | Bruno |
| Em_execucao | ATD_RICO_3 | Alessia | Ricardo |

**Histórico — todos os motivos de perda cobertos:**

| Estado | Motivo | Atendimento | Modelo |
|--------|--------|-------------|--------|
| Fechado | — | ATD_RICO_1, ATD_RICO_2 | Alessia |
| Perdido | preco | ATD_ADRI_1 | Alessia |
| Perdido | sumiu | ATD_FELI_1 | Alessia |
| Perdido | risco | ATD_RODR_1 | Bruna |

**Detalhes testáveis:**
- ATD_RICO_3: mensagens reais, 8 eventos, escalada aberta, bloqueio linkado
- ATD_RICO_2: ciclo externo completo com Pix, 13 eventos
- ATD_FELI_1: auto_timeout com `cron_timeout`, bloqueio cancelado, nenhuma escalada aberta
- ATD_RODR_1: Pix rejeitado por Fernando, escalada fechada, bloqueio cancelado por trigger

**Filtros testáveis:** por modelo (Alessia vs. Bruna), por estado, por tipo (interno vs. externo), por urgência

---

### 4.3 Clientes (CRM)

- 8 conversas na lista total (6 Alessia, 2 Bruna)
- Filtro por modelo funciona com 2 modelos distintas
- Ricardo: recorrente=true, 3 atendimentos, receita histórica R$ 4.300
- Adriano: ultimo_motivo_perda='preco'
- Felipe: ultimo_motivo_perda='sumiu'
- Rodrigo: ultimo_motivo_perda='risco'
- Gráfico de receita do Ricardo: 2 pontos (R$ 1.800 + R$ 2.500)
- Modal de cliente: observações preenchidas (Ricardo), sem observações (demais)

---

### 4.4 Agenda

**Alessia — todos os estados e origens de bloqueio:**

| Bloqueio | Estado | Origem | Quando |
|----------|--------|--------|--------|
| BLQ_ALE_01 | bloqueado | ia | hoje 20h–22h |
| BLQ_ALE_02 | em_atendimento | ia | hoje 15h–17h |
| BLQ_ALE_03 | concluido | ia | ontem 20h–22h30 |
| BLQ_ALE_04 | concluido | ia | −7d 18h–21h |
| BLQ_ALE_05 | bloqueado | ia | hoje 21h–23h |
| BLQ_ALE_06 | cancelado | ia | −5d 20h–22h |
| BLQ_ALE_07 | bloqueado | **manual** | amanhã 10h–13h |

**Bruna — bloqueado e cancelado:**

| Bloqueio | Estado | Origem | Quando |
|----------|--------|--------|--------|
| BLQ_BRU_01 | bloqueado | ia | hoje 21h–22h30 |
| BLQ_BRU_02 | cancelado | ia | −2d 20h–21h |

**Filtros testáveis:** por modelo, por estado (bloqueado/em_atendimento/concluido/cancelado), por origem (ia/manual)

---

### 4.5 Modelos

- **Alessia** (ativa): perfil completo, 5 FAQs, 10 mídias, 7 programas, 5 serviços, `evolution_instance_id` preenchido, `coordenacao_chat_id` preenchido
- **Bruna** (pausada): perfil parcial, 2 FAQs, 5 mídias, 2 programas, 2 serviços, `evolution_instance_id=NULL`, `coordenacao_chat_id=NULL`

**Filtros testáveis:** status (ativa vs. pausada), "não pareada" (evolution_instance_id=NULL)

**Modal de edição testável:** percentual_repasse, valor_padrao, idiomas, tipo_atendimento_aceito

---

### 4.6 PIX

| Comprovante | Decisão | Modelo | Cliente | Valor |
|-------------|---------|--------|---------|-------|
| PIX_RICO_1 | validado (auto) | Alessia | Ricardo | R$ 200 |
| PIX_GUST_1 | em_revisao | Alessia | Gustavo | R$ 200 |
| PIX_BRUN_1 | validado (auto) | Bruna | Bruno | R$ 150 |
| PIX_RODR_1 | invalido (Fernando) | Bruna | Rodrigo | R$ 120 |

**Filtros testáveis:** por status (validado/em_revisao/invalido), por modelo
**Modais testáveis:**
- PIX_GUST_1: botão "Validar" e "Rejeitar" ativos (pendente)
- PIX_RODR_1: motivo de rejeição, quem rejeitou, quando — tela de detalhe
- PIX_RICO_1 e PIX_BRUN_1: validado automaticamente, sem ação disponível

---

### 4.7 Dashboard Analítico

- **2 modelos** com dados (Alessia e Bruna)
- **Funil completo** (todos os estados presentes):
  `Triagem(1) → Qualificado(1) → Aguardando_confirmacao(1) → Confirmado(1) → Em_execucao(1) → Fechado(2) → Perdido(3)`
- **Perdas por motivo:** 1 × preco, 1 × sumiu, 1 × risco
- **Receita período 7d:** R$ 4.300 (ATD_RICO_1 + ATD_RICO_2, Alessia)
- **Receita por modelo:** Alessia R$ 4.300 | Bruna R$ 0 (sem fechamentos)
- **Filtro por modelo** no dashboard: cobre gráficos de Alessia isolada vs. consolidado

---

## 5. Ordem de Inserção

> Cada tabela recebe todos os registros de todas as modelos antes de avançar para a próxima.
> Bruna e Alessia seguem a mesma sequência; não há etapas separadas por modelo.

```
1.  barravips.usuarios
2.  barravips.duracoes
3.  barravips.programas
4.  barravips.modelos               (Alessia + Bruna)
5.  barravips.modelo_faq            (Alessia 5 FAQs + Bruna 2 FAQs)
6.  barravips.modelo_midia          (Alessia 10 + Bruna 5)
7.  barravips.modelo_servicos       (Alessia 5 + Bruna 2)
8.  barravips.modelo_programas      (Alessia 7 + Bruna 2)
9.  barravips.clientes              (8 clientes)
10. barravips.conversas             (8 conversas)
11. barravips.bloqueios             (atendimento_id=NULL — todos os 9 bloqueios)
12. barravips.atendimentos          (bloqueio_id=NULL — todos os 10 atendimentos)
13. UPDATE bloqueios.atendimento_id (seções 3.13 + 3.20.10)
14. UPDATE atendimentos.bloqueio_id (seções 3.13 + 3.20.10)
15. barravips.mensagens             (MSG-001 a MSG-062)
16. barravips.comprovantes_pix      (após mensagens — 4 comprovantes)
17. barravips.escaladas             (após atendimentos — 7 escaladas)
18. barravips.eventos               (após atendimentos — E01–E47 + EN1–EN27)
19. barravips.envios_evolution      (após atendimentos, conversas e escaladas)
20. barravips.atendimento_servicos  (apenas ATD_RICO_1 e ATD_RICO_2)
```
