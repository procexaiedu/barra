# Schema `barravips` — Documentação Estrutural

> Gerado em 2026-05-06. Contém apenas estrutura (sem dados).

---

## Sumário

- [Extensões Instaladas](#extensões-instaladas)
- [Tipos Enumerados (ENUMs)](#tipos-enumerados-enums)
- [Tabelas](#tabelas)
- [Índices](#índices)
- [Check Constraints de Negócio](#check-constraints-de-negócio)
- [Políticas RLS](#políticas-rls)
- [Triggers](#triggers)
- [Funções](#funções)
- [Grants e Privilégios](#grants-e-privilégios)
- [Realtime (Supabase)](#realtime-supabase)
- [Diagrama de Relacionamentos](#diagrama-de-relacionamentos)

---

## Extensões Instaladas

| Extensão | Versão | Uso |
|---|---|---|
| `btree_gist` | 1.7 | Suporte a índices GiST em colunas btree — usado em `bloqueios_sem_sobreposicao` |
| `http` | 1.6 | Requisições HTTP dentro do Postgres |
| `pg_cron` | 1.6.4 | Agendamento de jobs cron nativos no Postgres |
| `pg_net` | 0.19.5 | Requisições HTTP/HTTPS assíncronas (webhook, Edge Functions) |
| `pg_stat_statements` | 1.11 | Rastreamento de estatísticas de queries |
| `pgcrypto` | 1.3 | Funções criptográficas (`gen_random_bytes`, `gen_random_uuid`) |
| `plpgsql` | 1.0 | Linguagem procedural padrão |
| `supabase_vault` | 0.3.1 | Armazenamento seguro de secrets |
| `unaccent` | 1.1 | Remoção de acentos para buscas |
| `uuid-ossp` | 1.1 | Geração de UUIDs (`uuid_generate_v4` etc.) |
| `vector` | 0.8.0 | Suporte a embeddings vetoriais (pgvector) |

---

## Tipos Enumerados (ENUMs)

| Enum | Valores |
|---|---|
| `autor_evento_enum` | `IA`, `Fernando`, `modelo`, `sistema` |
| `decisao_final_pix_enum` | `validado`, `invalido` |
| `decisao_pipeline_pix_enum` | `validado`, `em_revisao` |
| `direcao_mensagem_enum` | `cliente`, `ia`, `modelo_manual` |
| `escalada_canal_enum` | `grupo_coordenacao`, `painel`, `pipeline_pix` |
| `escalada_responsavel_enum` | `Fernando`, `modelo` |
| `estado_atendimento_enum` | `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`, `Confirmado`, `Em_execucao`, `Fechado`, `Perdido` |
| `estado_bloqueio_enum` | `bloqueado`, `em_atendimento`, `concluido`, `cancelado` |
| `fonte_decisao_enum` | `extracao_ia`, `webhook_imagem`, `pipeline_pix`, `comando_grupo`, `painel_fernando`, `auto_timeout`, `auto_timeout_interno`, `cron_em_execucao` |
| `forma_pagamento_enum` | `pix`, `dinheiro`, `outro` |
| `ia_pausada_motivo_enum` | `pix_em_revisao`, `modelo_em_atendimento`, `handoff_ia` |
| `midia_tipo_enum` | `foto`, `video` |
| `modelo_status_enum` | `ativa`, `pausada`, `inativa` |
| `motivo_perda_enum` | `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro` |
| `origem_bloqueio_enum` | `ia`, `painel_fernando`, `manual` |
| `origem_evento_enum` | `agente`, `grupo_coordenacao`, `painel`, `pipeline_pix`, `cron` |
| `papel_usuario_enum` | `fernando`, `vendedor_read_only` |
| `pix_status_enum` | `nao_solicitado`, `aguardando`, `enviado`, `em_revisao`, `validado`, `invalido` |
| `responsavel_atual_enum` | `IA`, `Fernando`, `modelo` |
| `tipo_atendimento_enum` | `interno`, `externo` |
| `tipo_evento_enum` | `transicao_estado`, `extracao_registrada`, `pix_solicitado`, `pix_status_mudado`, `handoff_aberto`, `devolucao_para_ia`, `fechado_registrado`, `perdido_registrado`, `correcao_registro`, `bloqueio_criado`, `bloqueio_estado_mudado`, `comando_invalido`, `modelo_pausada`, `modelo_reativada` |
| `tipo_local_enum` | `hotel`, `casa`, `apartamento`, `outro` |
| `tipo_mensagem_enum` | `texto`, `audio`, `imagem` |
| `urgencia_enum` | `imediato`, `agendado`, `indefinido`, `estimado` |

---

## Tabelas

### `usuarios`

> Operadores do painel. P0: somente Fernando.
> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Restrições |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | — | PK; FK → `auth.users.id` ON DELETE CASCADE |
| `nome` | `text` | NOT NULL | — | |
| `email` | `text` | NOT NULL | — | UNIQUE |
| `papel` | `papel_usuario_enum` | NOT NULL | `'fernando'` | |
| `ativo` | `boolean` | NOT NULL | `true` | |
| `created_at` | `timestamptz` | NOT NULL | `now()` | |

---

### `modelos`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Restrições / Notas |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` | PK |
| `nome` | `text` | NOT NULL | — | |
| `numero_whatsapp` | `text` | NOT NULL | — | UNIQUE |
| `evolution_instance_id` | `text` | NULL | — | |
| `status` | `modelo_status_enum` | NOT NULL | `'ativa'` | |
| `valor_padrao` | `numeric` | NOT NULL | — | CHECK `>= 0` |
| `percentual_repasse` | `numeric` | NULL | — | CHECK `NULL OR (>= 0 AND <= 100)` |
| `chave_pix` | `text` | NULL | — | |
| `titular_chave` | `text` | NULL | — | |
| `idade` | `integer` | NOT NULL | — | CHECK `> 0`; interpolado no system prompt da IA |
| `idiomas` | `text[]` | NOT NULL | `ARRAY['pt-BR']` | BCP-47; interpolado no system prompt da IA |
| `localizacao_operacional` | `text` | NULL | — | |
| `tipo_atendimento_aceito` | `tipo_atendimento_enum[]` | NOT NULL | — | CHECK `length >= 1`; usado pela IA no qualificador |
| `foto_perfil_object_key` | `text` | NULL | — | Object key MinIO; não cria registro em `modelo_midia` |
| `coordenacao_chat_id` | `text` | NULL | — | JID Evolution do grupo de Coordenação por modelo |
| `coordenacao_verificada_em` | `timestamptz` | NULL | — | Última verificação do grupo via Evolution |
| `created_at` | `timestamptz` | NOT NULL | `now()` | |
| `updated_at` | `timestamptz` | NOT NULL | `now()` | atualizado por trigger |

---

### `modelo_faq`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `modelo_id` | `uuid` | NULL | FK → `modelos.id` ON DELETE CASCADE |
| `pergunta` | `text` | NOT NULL | — |
| `resposta` | `text` | NOT NULL | — |
| `tags` | `text[]` | NOT NULL | `ARRAY[]::text[]` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |
| `updated_at` | `timestamptz` | NOT NULL | `now()` |

---

### `modelo_midia`

> Mídia pré-aprovada armazenada em MinIO (bucket `barra-media`). Mínimo 10 por modelo antes do piloto.
> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `modelo_id` | `uuid` | NOT NULL | FK → `modelos.id` ON DELETE CASCADE |
| `tipo` | `midia_tipo_enum` | NOT NULL | — |
| `tag` | `text` | NOT NULL | — |
| `bucket` | `text` | NOT NULL | `'barra-media'` |
| `object_key` | `text` | NOT NULL | — |
| `aprovada` | `boolean` | NOT NULL | `true` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

---

### `clientes`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Notas |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK | |
| `telefone` | `text` | NOT NULL | — | UNIQUE |
| `nome` | `text` | NULL | — | |
| `primeiro_contato_modelo_id` | `uuid` | NULL | — | FK → `modelos.id` ON DELETE SET NULL; atributo identitário, não viola isolamento entre IAs |
| `created_at` | `timestamptz` | NOT NULL | `now()` | |
| `updated_at` | `timestamptz` | NOT NULL | `now()` | atualizado por trigger |

---

### `conversas`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `cliente_id` | `uuid` | NOT NULL | FK → `clientes.id` ON DELETE RESTRICT |
| `modelo_id` | `uuid` | NOT NULL | FK → `modelos.id` ON DELETE RESTRICT |
| `evolution_chat_id` | `text` | NOT NULL | — |
| `recorrente` | `boolean` | NOT NULL | `false` |
| `observacoes_internas` | `text` | NULL | — |
| `ultimo_motivo_perda` | `motivo_perda_enum` | NULL | — |
| `ultima_mensagem_em` | `timestamptz` | NULL | — |
| `ultima_mensagem_direcao` | `direcao_mensagem_enum` | NULL | — |
| `created_at` | `timestamptz` | NOT NULL | `now()` |
| `updated_at` | `timestamptz` | NOT NULL | `now()` |

**Constraint única:** `conversas_par_unico` — `(cliente_id, modelo_id)`

---

### `atendimentos`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Restrições |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` | PK |
| `numero_curto` | `integer` | NOT NULL | gerado por trigger | CHECK `> 0`; UNIQUE `(modelo_id, numero_curto)` |
| `cliente_id` | `uuid` | NOT NULL | — | FK → `clientes.id` ON DELETE RESTRICT |
| `modelo_id` | `uuid` | NOT NULL | — | FK → `modelos.id` ON DELETE RESTRICT |
| `conversa_id` | `uuid` | NOT NULL | — | FK → `conversas.id` ON DELETE RESTRICT |
| `bloqueio_id` | `uuid` | NULL | — | FK → `bloqueios.id` ON DELETE SET NULL |
| `estado` | `estado_atendimento_enum` | NOT NULL | `'Novo'` | |
| `tipo_atendimento` | `tipo_atendimento_enum` | NULL | — | |
| `urgencia` | `urgencia_enum` | NULL | — | |
| `data_desejada` | `date` | NULL | — | |
| `horario_desejado` | `time` | NULL | — | |
| `duracao_horas` | `numeric` | NULL | — | CHECK `> 0` |
| `endereco` | `text` | NULL | — | |
| `bairro` | `text` | NULL | — | |
| `tipo_local` | `tipo_local_enum` | NULL | — | |
| `referencia_local` | `text` | NULL | — | |
| `forma_pagamento` | `forma_pagamento_enum` | NULL | — | |
| `valor_acordado` | `numeric` | NULL | — | CHECK `>= 0` |
| `valor_final` | `numeric` | NULL | — | CHECK `>= 0` |
| `percentual_repasse_snapshot` | `numeric` | NULL | — | CHECK `NULL OR (>= 0 AND <= 100)` |
| `motivo_perda` | `motivo_perda_enum` | NULL | — | |
| `motivo_perda_obs` | `text` | NULL | — | |
| `pix_status` | `pix_status_enum` | NOT NULL | `'nao_solicitado'` | |
| `aviso_saida_em` | `timestamptz` | NULL | — | |
| `foto_portaria_em` | `timestamptz` | NULL | — | |
| `ia_pausada` | `boolean` | NOT NULL | `false` | |
| `ia_pausada_motivo` | `ia_pausada_motivo_enum` | NULL | — | |
| `responsavel_atual` | `responsavel_atual_enum` | NOT NULL | `'IA'` | |
| `proxima_acao_esperada` | `text` | NULL | — | |
| `motivo_escalada` | `text` | NULL | — | |
| `resumo_operacional` | `text` | NULL | — | |
| `sinais_qualificacao` | `jsonb` | NOT NULL | `'{}'` | |
| `fonte_decisao_ultima_transicao` | `fonte_decisao_enum` | NULL | — | |
| `created_at` | `timestamptz` | NOT NULL | `now()` | |
| `updated_at` | `timestamptz` | NOT NULL | `now()` | atualizado por trigger |

**Constraint única:** `atendimentos_um_aberto_por_par` — `(cliente_id, modelo_id)` WHERE estado NOT IN (`Fechado`, `Perdido`)

---

### `bloqueios`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `modelo_id` | `uuid` | NOT NULL | FK → `modelos.id` ON DELETE RESTRICT |
| `atendimento_id` | `uuid` | NULL | FK → `atendimentos.id` ON DELETE SET NULL |
| `inicio` | `timestamptz` | NOT NULL | — |
| `fim` | `timestamptz` | NOT NULL | — |
| `estado` | `estado_bloqueio_enum` | NOT NULL | `'bloqueado'` |
| `origem` | `origem_bloqueio_enum` | NOT NULL | — |
| `observacao` | `text` | NULL | — |
| `created_at` | `timestamptz` | NOT NULL | `now()` |
| `updated_at` | `timestamptz` | NOT NULL | `now()` |

---

### `mensagens`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `conversa_id` | `uuid` | NOT NULL | FK → `conversas.id` ON DELETE CASCADE |
| `atendimento_id` | `uuid` | NULL | FK → `atendimentos.id` ON DELETE SET NULL |
| `direcao` | `direcao_mensagem_enum` | NOT NULL | — |
| `tipo` | `tipo_mensagem_enum` | NOT NULL | — |
| `conteudo` | `text` | NOT NULL | `''` |
| `media_object_key` | `text` | NULL | — |
| `evolution_message_id` | `text` | NOT NULL | — — UNIQUE |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

---

### `comprovantes_pix`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `atendimento_id` | `uuid` | NOT NULL | FK → `atendimentos.id` ON DELETE CASCADE |
| `mensagem_id` | `uuid` | NOT NULL | FK → `mensagens.id` ON DELETE CASCADE |
| `valor_extraido` | `numeric` | NULL | — |
| `chave_extraida` | `text` | NULL | — |
| `titular_extraido` | `text` | NULL | — |
| `timestamp_extraido` | `timestamptz` | NULL | — |
| `decisao_pipeline` | `decisao_pipeline_pix_enum` | NOT NULL | — |
| `motivo_em_revisao` | `text` | NULL | — |
| `decisao_final` | `decisao_final_pix_enum` | NULL | — |
| `decisao_final_por` | `uuid` | NULL | FK → `usuarios.id` ON DELETE SET NULL |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

---

### `escaladas`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `atendimento_id` | `uuid` | NOT NULL | FK → `atendimentos.id` ON DELETE CASCADE |
| `responsavel` | `escalada_responsavel_enum` | NOT NULL | — |
| `motivo` | `text` | NOT NULL | — |
| `resumo_operacional` | `text` | NOT NULL | — |
| `acao_esperada` | `text` | NOT NULL | — |
| `card_message_id` | `text` | NULL | — |
| `aberta_em` | `timestamptz` | NOT NULL | `now()` |
| `fechada_em` | `timestamptz` | NULL | — |
| `fechada_por` | `uuid` | NULL | FK → `usuarios.id` ON DELETE SET NULL |
| `fechada_canal` | `escalada_canal_enum` | NULL | — |

---

### `eventos`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK |
| `atendimento_id` | `uuid` | NULL | FK → `atendimentos.id` ON DELETE SET NULL |
| `tipo` | `tipo_evento_enum` | NOT NULL | — |
| `origem` | `origem_evento_enum` | NOT NULL | — |
| `autor` | `autor_evento_enum` | NOT NULL | — |
| `payload` | `jsonb` | NOT NULL | `'{}'` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

---

### `envios_evolution`

> Outbound enviado pelo backend via Evolution. Usado para distinguir backend/IA/sistema de ação manual no número operado.
> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Restrições |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK | |
| `evolution_message_id` | `text` | NOT NULL | — | UNIQUE |
| `instance_id` | `text` | NOT NULL | — | |
| `remote_jid` | `text` | NOT NULL | — | |
| `contexto` | `text` | NOT NULL | — | CHECK IN (`conversa_cliente`, `grupo_coordenacao`) |
| `direcao` | `text` | NOT NULL | `'outbound_backend'` | CHECK = `outbound_backend` |
| `tipo` | `text` | NOT NULL | — | CHECK IN (`ia`, `card`, `confirmacao`, `erro_comando`, `midia`) |
| `atendimento_id` | `uuid` | NULL | — | FK → `atendimentos.id` ON DELETE SET NULL |
| `conversa_id` | `uuid` | NULL | — | FK → `conversas.id` ON DELETE SET NULL |
| `payload` | `jsonb` | NOT NULL | `'{}'` | |
| `created_at` | `timestamptz` | NOT NULL | `now()` | |

---

### `modelo_servicos`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Restrições |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuidv7()` — PK | |
| `modelo_id` | `uuid` | NOT NULL | — | FK → `modelos.id` ON DELETE CASCADE |
| `nome` | `text` | NOT NULL | — | CHECK `TRIM(nome) length > 0` |
| `duracao_horas` | `numeric` | NOT NULL | — | CHECK `> 0` |
| `preco` | `numeric` | NOT NULL | — | CHECK `>= 0` |
| `ativo` | `boolean` | NOT NULL | `true` | |
| `ordem` | `smallint` | NOT NULL | `0` | |
| `created_at` | `timestamptz` | NOT NULL | `now()` | |
| `updated_at` | `timestamptz` | NOT NULL | `now()` | |

**Constraint única:** `modelo_servicos_nome_duracao_unique` — `(modelo_id, nome, duracao_horas)`

---

### `programas`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Restrições |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` — PK | |
| `nome` | `text` | NOT NULL | — | CHECK `TRIM(nome) length > 0` |
| `categoria` | `text` | NULL | — | |
| `created_at` | `timestamptz` | NOT NULL | `now()` | |
| `updated_at` | `timestamptz` | NOT NULL | `now()` | |

---

### `duracoes`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default | Restrições |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` — PK | |
| `nome` | `text` | NOT NULL | — | CHECK `TRIM(nome) length > 0` |
| `ordem` | `integer` | NOT NULL | `0` | |
| `created_at` | `timestamptz` | NULL | `now()` | |

---

### `modelo_programas`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `modelo_id` | `uuid` | NOT NULL | FK → `modelos.id` ON DELETE CASCADE |
| `programa_id` | `uuid` | NOT NULL | FK → `programas.id` ON DELETE RESTRICT |
| `duracao_id` | `uuid` | NOT NULL | FK → `duracoes.id` ON DELETE RESTRICT |
| `preco` | `numeric` | NOT NULL | — CHECK `>= 0` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |
| `updated_at` | `timestamptz` | NOT NULL | `now()` |

**PK composta:** `(modelo_id, programa_id, duracao_id)`

---

### `atendimento_servicos`

> RLS: habilitado

| Coluna | Tipo | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` — PK |
| `atendimento_id` | `uuid` | NOT NULL | FK → `atendimentos.id` ON DELETE CASCADE |
| `programa_id` | `uuid` | NOT NULL | FK → `programas.id` ON DELETE RESTRICT |
| `duracao_id` | `uuid` | NOT NULL | FK → `duracoes.id` ON DELETE RESTRICT |
| `preco_snapshot` | `numeric` | NOT NULL | — CHECK `>= 0` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

---

## Índices

### `atendimento_servicos`

| Nome | Definição |
|---|---|
| `atendimento_servicos_pkey` | UNIQUE BTREE `(id)` |
| `ats_atendimento_idx` | BTREE `(atendimento_id)` |

### `atendimentos`

| Nome | Definição |
|---|---|
| `atendimentos_pkey` | UNIQUE BTREE `(id)` |
| `atendimentos_numero_curto_modelo_unique` | UNIQUE BTREE `(modelo_id, numero_curto)` |
| `atendimentos_um_aberto_por_par` | UNIQUE BTREE `(cliente_id, modelo_id)` WHERE `estado NOT IN ('Fechado', 'Perdido')` |
| `atendimentos_cliente_idx` | BTREE `(cliente_id)` |
| `atendimentos_conversa_idx` | BTREE `(conversa_id)` |
| `atendimentos_modelo_estado_idx` | BTREE `(modelo_id, estado)` |
| `atendimentos_em_aberto_idx` | BTREE `(modelo_id, updated_at DESC)` WHERE `estado NOT IN ('Fechado', 'Perdido')` |
| `atendimentos_pausada_idx` | BTREE `(modelo_id, ia_pausada_motivo)` WHERE `ia_pausada = true` |
| `atendimentos_bloqueio_idx` | BTREE `(bloqueio_id)` WHERE `bloqueio_id IS NOT NULL` |

### `bloqueios`

| Nome | Definição |
|---|---|
| `bloqueios_pkey` | UNIQUE BTREE `(id)` |
| `bloqueios_modelo_inicio_idx` | BTREE `(modelo_id, inicio)` |
| `bloqueios_atendimento_idx` | BTREE `(atendimento_id)` WHERE `atendimento_id IS NOT NULL` |
| `bloqueios_sem_sobreposicao` | GIST `(modelo_id, tstzrange(inicio, fim, '[)'))` WHERE `estado IN ('bloqueado', 'em_atendimento')` |

### `clientes`

| Nome | Definição |
|---|---|
| `clientes_pkey` | UNIQUE BTREE `(id)` |
| `clientes_telefone_key` | UNIQUE BTREE `(telefone)` |
| `clientes_primeiro_contato_modelo_idx` | BTREE `(primeiro_contato_modelo_id)` WHERE `primeiro_contato_modelo_id IS NOT NULL` |

### `comprovantes_pix`

| Nome | Definição |
|---|---|
| `comprovantes_pix_pkey` | UNIQUE BTREE `(id)` |
| `comprovantes_pix_atendimento_idx` | BTREE `(atendimento_id)` |
| `comprovantes_pix_mensagem_idx` | BTREE `(mensagem_id)` |
| `comprovantes_pix_decisao_por_idx` | BTREE `(decisao_final_por)` WHERE `decisao_final_por IS NOT NULL` |
| `comprovantes_pix_em_revisao_idx` | BTREE `(created_at DESC)` WHERE `decisao_pipeline = 'em_revisao' AND decisao_final IS NULL` |

### `conversas`

| Nome | Definição |
|---|---|
| `conversas_pkey` | UNIQUE BTREE `(id)` |
| `conversas_par_unico` | UNIQUE BTREE `(cliente_id, modelo_id)` |
| `conversas_modelo_idx` | BTREE `(modelo_id)` |
| `conversas_cliente_idx` | BTREE `(cliente_id)` |
| `conversas_evolution_chat_idx` | BTREE `(modelo_id, evolution_chat_id)` |
| `conversas_atualizada_idx` | BTREE `(modelo_id, updated_at DESC)` |
| `conversas_modelo_ultima_msg_idx` | BTREE `(modelo_id, ultima_mensagem_em DESC NULLS LAST)` |

### `duracoes`

| Nome | Definição |
|---|---|
| `duracoes_pkey` | UNIQUE BTREE `(id)` |

### `envios_evolution`

| Nome | Definição |
|---|---|
| `envios_evolution_pkey` | UNIQUE BTREE `(id)` |
| `envios_evolution_evolution_message_id_key` | UNIQUE BTREE `(evolution_message_id)` |
| `envios_evolution_remote_jid_created_idx` | BTREE `(remote_jid, created_at DESC)` |
| `envios_evolution_atendimento_created_idx` | BTREE `(atendimento_id, created_at DESC)` WHERE `atendimento_id IS NOT NULL` |
| `envios_evolution_conversa_created_idx` | BTREE `(conversa_id, created_at DESC)` WHERE `conversa_id IS NOT NULL` |

### `escaladas`

| Nome | Definição |
|---|---|
| `escaladas_pkey` | UNIQUE BTREE `(id)` |
| `escaladas_atendimento_idx` | BTREE `(atendimento_id)` |
| `escaladas_abertas_idx` | BTREE `(aberta_em DESC)` WHERE `fechada_em IS NULL` |
| `escaladas_fechada_por_idx` | BTREE `(fechada_por)` WHERE `fechada_por IS NOT NULL` |

### `eventos`

| Nome | Definição |
|---|---|
| `eventos_pkey` | UNIQUE BTREE `(id)` |
| `eventos_atendimento_idx` | BTREE `(atendimento_id)` |
| `eventos_tipo_idx` | BTREE `(tipo)` |
| `eventos_created_idx` | BTREE `(created_at DESC)` |
| `eventos_payload_gin_idx` | GIN `(payload)` |

### `mensagens`

| Nome | Definição |
|---|---|
| `mensagens_pkey` | UNIQUE BTREE `(id)` |
| `mensagens_evolution_message_id_key` | UNIQUE BTREE `(evolution_message_id)` |
| `mensagens_conversa_created_idx` | BTREE `(conversa_id, created_at DESC)` |
| `mensagens_atendimento_idx` | BTREE `(atendimento_id)` WHERE `atendimento_id IS NOT NULL` |

### `modelo_faq`

| Nome | Definição |
|---|---|
| `modelo_faq_pkey` | UNIQUE BTREE `(id)` |
| `modelo_faq_modelo_idx` | BTREE `(modelo_id)` |
| `modelo_faq_tags_gin_idx` | GIN `(tags)` |

### `modelo_midia`

| Nome | Definição |
|---|---|
| `modelo_midia_pkey` | UNIQUE BTREE `(id)` |
| `modelo_midia_modelo_idx` | BTREE `(modelo_id)` |
| `modelo_midia_modelo_tag_idx` | BTREE `(modelo_id, tag)` WHERE `aprovada = true` |

### `modelo_programas`

| Nome | Definição |
|---|---|
| `modelo_programas_pkey` | UNIQUE BTREE `(modelo_id, programa_id, duracao_id)` |
| `modelo_programas_modelo_idx` | BTREE `(modelo_id)` |

### `modelo_servicos`

| Nome | Definição |
|---|---|
| `modelo_servicos_pkey` | UNIQUE BTREE `(id)` |
| `modelo_servicos_nome_duracao_unique` | UNIQUE BTREE `(modelo_id, nome, duracao_horas)` |
| `modelo_servicos_modelo_idx` | BTREE `(modelo_id, ordem, duracao_horas)` |

### `modelos`

| Nome | Definição |
|---|---|
| `modelos_pkey` | UNIQUE BTREE `(id)` |
| `modelos_numero_whatsapp_key` | UNIQUE BTREE `(numero_whatsapp)` |
| `modelos_status_created_idx` | BTREE `(status, created_at)` |
| `modelos_coordenacao_chat_idx` | BTREE `(coordenacao_chat_id)` WHERE `coordenacao_chat_id IS NOT NULL` |

### `programas`

| Nome | Definição |
|---|---|
| `programas_pkey` | UNIQUE BTREE `(id)` |

### `usuarios`

| Nome | Definição |
|---|---|
| `usuarios_pkey` | UNIQUE BTREE `(id)` |
| `usuarios_email_key` | UNIQUE BTREE `(email)` |

---

## Check Constraints de Negócio

> Omitidas as constraints `NOT NULL` geradas automaticamente pelo sistema. Listadas apenas as regras de negócio explícitas.

### `atendimentos`

| Constraint | Regra |
|---|---|
| `atendimentos_numero_curto_check` | `numero_curto > 0` |
| `atendimentos_duracao_horas_check` | `duracao_horas IS NULL OR duracao_horas > 0` |
| `atendimentos_valor_acordado_check` | `valor_acordado IS NULL OR valor_acordado >= 0` |
| `atendimentos_valor_final_check` | `valor_final IS NULL OR valor_final >= 0` |
| `atendimentos_percentual_repasse_snapshot_check` | `percentual_repasse_snapshot IS NULL OR (>= 0 AND <= 100)` |
| `atendimentos_fechado_exige_valor_final` | `estado <> 'Fechado' OR valor_final IS NOT NULL` |
| `atendimentos_perdido_exige_motivo` | `estado <> 'Perdido' OR motivo_perda IS NOT NULL` |
| `atendimentos_ia_pausada_exige_motivo` | `ia_pausada = false OR ia_pausada_motivo IS NOT NULL` |
| `atendimentos_motivo_outro_exige_obs` | `motivo_perda IS DISTINCT FROM 'outro' OR motivo_perda_obs IS NOT NULL` |

### `bloqueios`

| Constraint | Regra |
|---|---|
| `bloqueios_intervalo_valido` | `inicio < fim` |

### `mensagens`

| Constraint | Regra |
|---|---|
| `mensagens_midia_exige_object_key` | `tipo = 'texto' OR media_object_key IS NOT NULL` |

### `modelos`

| Constraint | Regra |
|---|---|
| `modelos_valor_padrao_check` | `valor_padrao >= 0` |
| `modelos_percentual_repasse_check` | `percentual_repasse IS NULL OR (>= 0 AND <= 100)` |
| `modelos_idade_check` | `idade > 0` |
| `modelos_tipo_atendimento_nao_vazio` | `array_length(tipo_atendimento_aceito, 1) >= 1` |

### `modelo_servicos`

| Constraint | Regra |
|---|---|
| `modelo_servicos_nome_check` | `length(TRIM(nome)) > 0` |
| `modelo_servicos_duracao_horas_check` | `duracao_horas > 0` |
| `modelo_servicos_preco_check` | `preco >= 0` |

### `modelo_programas`

| Constraint | Regra |
|---|---|
| `modelo_programas_preco_check` | `preco >= 0` |

### `programas`

| Constraint | Regra |
|---|---|
| `programas_nome_check` | `length(TRIM(nome)) > 0` |

### `duracoes`

| Constraint | Regra |
|---|---|
| `duracoes_nome_check` | `length(TRIM(nome)) > 0` |

### `atendimento_servicos`

| Constraint | Regra |
|---|---|
| `atendimento_servicos_preco_snapshot_check` | `preco_snapshot >= 0` |

### `envios_evolution`

| Constraint | Regra |
|---|---|
| `envios_evolution_contexto_check` | `contexto IN ('conversa_cliente', 'grupo_coordenacao')` |
| `envios_evolution_direcao_check` | `direcao = 'outbound_backend'` |
| `envios_evolution_tipo_check` | `tipo IN ('ia', 'card', 'confirmacao', 'erro_comando', 'midia')` |

---

## Políticas RLS

> Todas as tabelas têm RLS habilitado. A função helper `is_fernando()` verifica se o usuário autenticado tem `papel = 'fernando'` e `ativo = true`.

| Tabela | Policy | Papel | Comando | USING / WITH CHECK |
|---|---|---|---|---|
| `usuarios` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `modelos` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `modelo_faq` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `modelo_midia` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `modelo_servicos` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `modelo_programas` | `fernando_full_access` | authenticated | ALL | `true` (qualquer autenticado) |
| `clientes` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `conversas` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `atendimentos` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `bloqueios` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `mensagens` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `comprovantes_pix` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `escaladas` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `eventos` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `envios_evolution` | `fernando_full_access` | authenticated | ALL | `is_fernando()` |
| `programas` | `fernando_full_access` | authenticated | ALL | `true` (qualquer autenticado) |
| `atendimento_servicos` | `fernando_full_access` | authenticated | ALL | `true` (qualquer autenticado) |

> **Nota:** `modelo_programas`, `programas` e `atendimento_servicos` têm policy `true` — qualquer usuário autenticado tem acesso total. Provável que o backend (service role) acesse via `service_role` key que bypassa RLS por completo.

---

## Triggers

**Triggers em `barravips`:**

| Tabela | Trigger | Evento | Timing | Função |
|---|---|---|---|---|
| `atendimentos` | `gen_numero_curto_atendimentos` | INSERT | BEFORE | `gen_numero_curto()` |
| `atendimentos` | `set_updated_at_atendimentos` | UPDATE | BEFORE | `set_updated_at()` |
| `atendimentos` | `sync_bloqueio_estado_atendimentos` | UPDATE | AFTER | `sync_bloqueio_estado()` |
| `bloqueios` | `set_updated_at_bloqueios` | UPDATE | BEFORE | `set_updated_at()` |
| `clientes` | `set_updated_at_clientes` | UPDATE | BEFORE | `set_updated_at()` |
| `conversas` | `set_updated_at_conversas` | UPDATE | BEFORE | `set_updated_at()` |
| `mensagens` | `atualiza_ultima_mensagem_conversa` | INSERT | AFTER | `atualiza_ultima_mensagem_em_conversa()` |
| `modelo_faq` | `set_updated_at_modelo_faq` | UPDATE | BEFORE | `set_updated_at()` |
| `modelo_programas` | `set_updated_at_modelo_programas` | UPDATE | BEFORE | `set_updated_at_modelo_programas()` |
| `modelo_servicos` | `set_updated_at_modelo_servicos` | UPDATE | BEFORE | `set_updated_at()` |
| `modelos` | `set_updated_at_modelos` | UPDATE | BEFORE | `set_updated_at()` |
| `programas` | `set_updated_at_programas` | UPDATE | BEFORE | `set_updated_at_programas()` |

**Triggers cross-schema em `auth.users`:**

| Trigger | Evento | Timing | Função chamada | Efeito |
|---|---|---|---|---|
| `on_auth_user_created` | INSERT | AFTER | `public.handle_new_user()` | Insere em `public.profiles` (artefato de outro projeto no mesmo Supabase) |
| `on_auth_user_created_barravips` | INSERT | AFTER | `barravips.handle_new_user()` | Insere em `barravips.usuarios` com papel `fernando` |

> **Atenção:** O projeto Supabase é compartilhado. Ambos os triggers disparam no mesmo INSERT em `auth.users`. O trigger `on_auth_user_created` é artefato de outro schema (`public`) e não interfere no `barravips`.

---

## Funções

> **Volatilidade:** `v` = VOLATILE (padrão), `s` = STABLE. `SECURITY DEFINER` executa com os privilégios do dono da função, não do chamador — relevante para RLS.

| Função | Retorno | Security | Volatilidade |
|---|---|---|---|
| `uuidv7` | `uuid` | INVOKER | VOLATILE |
| `set_updated_at` | `trigger` | INVOKER | VOLATILE |
| `set_updated_at_modelo_programas` | `trigger` | INVOKER | VOLATILE |
| `set_updated_at_programas` | `trigger` | INVOKER | VOLATILE |
| `gen_numero_curto` | `trigger` | INVOKER | VOLATILE |
| `atualiza_ultima_mensagem_em_conversa` | `trigger` | INVOKER | VOLATILE |
| `sync_bloqueio_estado` | `trigger` | INVOKER | VOLATILE |
| `handle_new_user` | `trigger` | **DEFINER** | VOLATILE |
| `is_fernando` | `boolean` | **DEFINER** | STABLE |

---

### `uuidv7() → uuid`

Gera UUID v7 (timestamp-prefixed). Usado como default de PK em todas as tabelas de domínio.

```sql
DECLARE
  ts_ms      bigint;
  uuid_bytes bytea;
BEGIN
  ts_ms := floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  uuid_bytes := substring(int8send(ts_ms) from 3) || gen_random_bytes(10);
  uuid_bytes := set_byte(uuid_bytes, 6, (get_byte(uuid_bytes, 6) & 15) | 112);
  uuid_bytes := set_byte(uuid_bytes, 8, (get_byte(uuid_bytes, 8) & 63) | 128);
  RETURN encode(uuid_bytes, 'hex')::uuid;
END;
```

### `set_updated_at() → trigger`

Atualiza `updated_at = now()` antes de UPDATE. Usado em: `atendimentos`, `bloqueios`, `clientes`, `conversas`, `modelo_faq`, `modelo_servicos`, `modelos`.

```sql
BEGIN NEW.updated_at := now(); RETURN NEW; END;
```

### `set_updated_at_modelo_programas() → trigger` / `set_updated_at_programas() → trigger`

Variantes idênticas de `set_updated_at` para as tabelas `modelo_programas` e `programas`.

### `gen_numero_curto() → trigger`

Gera `numero_curto` sequencial por modelo usando advisory lock para evitar duplicatas concorrentes.

```sql
DECLARE proximo integer;
BEGIN
  IF NEW.numero_curto IS NOT NULL THEN RETURN NEW; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.modelo_id::text, 0));
  SELECT COALESCE(MAX(numero_curto), 0) + 1 INTO proximo
    FROM barravips.atendimentos WHERE modelo_id = NEW.modelo_id;
  NEW.numero_curto := proximo;
  RETURN NEW;
END;
```

### `atualiza_ultima_mensagem_em_conversa() → trigger`

Após INSERT em `mensagens`, sincroniza `conversas.ultima_mensagem_em` e `conversas.ultima_mensagem_direcao`.

```sql
BEGIN
  UPDATE barravips.conversas
     SET ultima_mensagem_em      = NEW.created_at,
         ultima_mensagem_direcao = NEW.direcao
   WHERE id = NEW.conversa_id;
  RETURN NEW;
END;
```

### `sync_bloqueio_estado() → trigger`

Após UPDATE em `atendimentos`, sincroniza o estado do bloqueio vinculado:
- `Fechado` → bloqueio vira `concluido`
- `Perdido` → bloqueio vira `cancelado` (salvo se já `em_atendimento` ou `concluido`)

```sql
BEGIN
  IF NEW.bloqueio_id IS NULL THEN RETURN NEW; END IF;
  IF NEW.estado = 'Fechado' AND (OLD.estado IS DISTINCT FROM 'Fechado') THEN
    UPDATE barravips.bloqueios SET estado = 'concluido', updated_at = now()
     WHERE id = NEW.bloqueio_id AND estado <> 'concluido';
  ELSIF NEW.estado = 'Perdido' AND (OLD.estado IS DISTINCT FROM 'Perdido') THEN
    UPDATE barravips.bloqueios SET estado = 'cancelado', updated_at = now()
     WHERE id = NEW.bloqueio_id AND estado NOT IN ('em_atendimento', 'concluido');
  END IF;
  RETURN NEW;
END;
```

### `handle_new_user() → trigger`

Registrado em `auth.users` (schema Supabase). Cria automaticamente um registro em `barravips.usuarios` quando um novo usuário é criado no Auth.

```sql
BEGIN
  INSERT INTO barravips.usuarios (id, email, nome, papel, ativo)
  VALUES (NEW.id, NEW.email,
    COALESCE(NEW.raw_user_meta_data ->> 'nome', NEW.email),
    'fernando', true)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
```

### `is_fernando() → boolean`

Função helper para RLS. Retorna `true` se o usuário autenticado tem papel `fernando` e está ativo.

```sql
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM barravips.usuarios u
     WHERE u.id = (SELECT auth.uid())
       AND u.ativo AND u.papel = 'fernando'
  );
END;
```

---

## Grants e Privilégios

### Acesso ao schema `barravips`

| Role | USAGE | CREATE |
|---|---|---|
| `anon` | ✗ | ✗ |
| `authenticated` | ✓ | ✗ |
| `service_role` | ✓ | ✗ |
| `postgres` | ✓ | ✓ |

> `anon` não tem acesso ao schema — nenhuma tabela é acessível sem autenticação.

### Privilégios por role nas tabelas

Padrão uniforme em todas as 18 tabelas:

| Role | SELECT | INSERT | UPDATE | DELETE | TRUNCATE | REFERENCES | TRIGGER |
|---|---|---|---|---|---|---|---|
| `authenticated` | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| `service_role` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `postgres` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

> O acesso efetivo de `authenticated` é filtrado pelas **políticas RLS** (`is_fernando()`). O `service_role` bypassa RLS por completo — é o papel usado pelo backend FastAPI.

---

## Realtime (Supabase)

Publicação `supabase_realtime` (INSERT, UPDATE, DELETE, TRUNCATE habilitados).

**Tabelas COM Realtime habilitado (14):**

| Tabela |
|---|
| `atendimentos` |
| `bloqueios` |
| `clientes` |
| `comprovantes_pix` |
| `conversas` |
| `duracoes` |
| `eventos` |
| `mensagens` |
| `modelo_faq` |
| `modelo_midia` |
| `modelo_programas` |
| `modelo_servicos` |
| `modelos` |
| `programas` |

**Tabelas SEM Realtime (4):**

| Tabela | Motivo provável |
|---|---|
| `usuarios` | Dados sensíveis de operadores; não exige push |
| `escaladas` | Consultadas por polling/API, não por subscription |
| `envios_evolution` | Log de auditoria; frontend não precisa de push |
| `atendimento_servicos` | Dado de detalhe; carregado junto ao atendimento |

---

## pg_cron Jobs

**Nenhum job** agendado para o schema `barravips`.

> O banco possui um job ativo para outro schema (`iprado.contacts`, diário às 03:00 UTC) — artefato de projeto diferente no mesmo Supabase, sem relação com barravips.

---

## Edge Functions

**Nenhuma** Edge Function deployada neste projeto.

---

## Contexto: Schemas Coexistentes

Este banco Supabase é compartilhado. Além de `barravips`, existem outros schemas ativos de projetos distintos:

| Schema | Uso |
|---|---|
| `public` | Projeto anterior — contém `profiles`, `handle_new_user`, trigger em `auth.users` |
| `devcontext` | Outro projeto — tem `handle_new_user` e `profiles` próprios |
| `wgr6` | Outro projeto — tem `handle_new_user` e `profiles` próprios |
| `iprado` | Outro projeto — tem job `pg_cron` ativo (reset diário de `contacts`) |

> Esses schemas são isolados e não interferem no `barravips`, mas é importante saber que **múltiplos triggers em `auth.users`** disparam simultaneamente ao criar um usuário.

---

## Guia para Seeds

> Tudo que um agente precisa para gerar seeds completas, realistas e contextualizadas — sem precisar de outros arquivos.

---

### Formatos Canônicos

| Campo | Formato | Exemplo real |
|---|---|---|
| `clientes.telefone` | E.164 com `+` | `+5511988887771` |
| `conversas.evolution_chat_id` | `{numero_sem_plus}@s.whatsapp.net` | `5511988887772@s.whatsapp.net` |
| `modelos.coordenacao_chat_id` | JID de grupo `@g.us` | `120363000000000001@g.us` |
| `envios_evolution.remote_jid` (cliente) | igual `evolution_chat_id` | `5511988887771@s.whatsapp.net` |
| `envios_evolution.remote_jid` (grupo) | `{id_grupo}@g.us` | `grupo_coord_alessia@g.us` |
| `envios_evolution.instance_id` | `evo_{nome_modelo_lowercase}` | `evo_alessia` |
| `modelos.evolution_instance_id` | igual `instance_id` | `evo_alessia` |
| `mensagens.evolution_message_id` | string única por mensagem | `3EB0ABC123DEF456` |
| `escaladas.card_message_id` | ID Evolution do card no grupo | `3EB0CARD00000001` |
| `modelo_midia.object_key` | `modelos/{modelo_id}/{tipo}/{arquivo}` | `modelos/018f...001/foto/rosto-01.jpg` |
| `modelo_midia.bucket` | sempre `barra-media` | `barra-media` |
| `modelos.foto_perfil_object_key` | `modelos/{modelo_id}/perfil/{arquivo}` | `modelos/018f...001/perfil/perfil.jpg` |
| `atendimentos.numero_curto` | inteiro sequencial por modelo; gerado por trigger | `1`, `2`, `3` … |
| `modelos.percentual_repasse` | 30, 40 ou 50 | `30.00` |
| `modelos.valor_padrao` | ~1000–2000 (R$/hora, premium) | `1200.00` |
| `modelos.idiomas` | array BCP-47 | `{pt-BR}`, `{pt-BR,en-US}` |

---

### Estrutura dos Campos JSONB

#### `atendimentos.sinais_qualificacao`

Cinco chaves booleanas, todas obrigatórias. Default `{}` na criação; preenchido quando a IA registra extração.

```json
{
  "informa_horario": true,
  "informa_local": true,
  "aceita_valor": true,
  "envia_pix": false,
  "responde_objetivamente": true
}
```

| Chave | Significado |
|---|---|
| `informa_horario` | Cliente informou data/hora desejada |
| `informa_local` | Cliente informou endereço ou tipo de local |
| `aceita_valor` | Cliente não questionou o valor cobrado |
| `envia_pix` | Cliente efetivamente enviou Pix de deslocamento |
| `responde_objetivamente` | Cliente responde perguntas sem desvio |

**Exemplos reais do banco:**
```json
// atendimento recém-criado
{}

// triagem inicial — cliente vago
{"envia_pix": false, "aceita_valor": false, "informa_local": false, "informa_horario": false, "responde_objetivamente": false}

// cliente qualificado (externo sem pix ainda)
{"envia_pix": false, "aceita_valor": true, "informa_local": true, "informa_horario": true, "responde_objetivamente": true}

// atendimento externo confirmado
{"envia_pix": true, "aceita_valor": true, "informa_local": true, "informa_horario": true, "responde_objetivamente": true}
```

---

#### `eventos.payload` — por tipo

Exemplos reais extraídos do banco:

```json
// transicao_estado — IA via extracao
{ "de": "Novo", "para": "Triagem", "fonte_decisao": "extracao_ia" }

// transicao_estado — com sinais capturados
{ "de": "Triagem", "para": "Qualificado",
  "sinais": { "aceita_valor": true, "informa_local": true, "informa_horario": true },
  "fonte_decisao": "extracao_ia" }

// transicao_estado — webhook de imagem (foto de portaria)
{ "de": "Aguardando_confirmacao", "para": "Em_execucao",
  "trigger": "foto_portaria", "fonte_decisao": "webhook_imagem" }

// transicao_estado — pipeline Pix validou
{ "de": "Qualificado", "para": "Confirmado", "fonte_decisao": "pipeline_pix" }

// transicao_estado — cron timeout interno 30min
{ "de": "Aguardando_confirmacao", "para": "Perdido",
  "trigger": "30min_sem_foto_portaria", "fonte_decisao": "auto_timeout_interno" }

// transicao_estado — cron timeout longo 24h
{ "de": "Qualificado", "para": "Perdido", "fonte_decisao": "auto_timeout" }

// transicao_estado — painel Fernando (kanban)
{ "via": "kanban", "estado_anterior": "Triagem", "estado_novo": "Aguardando_confirmacao" }

// transicao_estado — modelo fecha via grupo
{ "de": "Em_execucao", "para": "Fechado", "fonte_decisao": "comando_grupo" }

// transicao_estado — Fernando fecha via painel
{ "de": "Qualificado", "para": "Perdido", "fonte_decisao": "painel_fernando" }

// extracao_registrada
{ "campo": "aviso_saida_em", "valor": "agora" }

// pix_solicitado
{ "chave": "21999990001", "valor": 200 }

// pix_status_mudado
{ "pix_id": "018f...0002", "decisao": "validado" }

// handoff_aberto
{ "motivo": "Cliente chegou (foto de portaria)",
  "responsavel": "modelo",
  "ia_pausada_motivo": "modelo_em_atendimento" }

// devolucao_para_ia
{ "observacao": null, "usuario_id": "3d08...e98" }

// fechado_registrado
{ "comando": "finalizado 1800", "valor_final": 1800 }

// perdido_registrado
{ "motivo": "risco", "obs": "Perfil de risco confirmado após análise manual" }

// correcao_registro
{ "campo": "valor_final", "de": 2400, "para": 2500,
  "motivo": "Cliente acrescentou gorjeta - valor confirmado pela modelo via áudio." }

// bloqueio_criado
{ "bloqueio_id": "b10c...0002", "inicio": "20:00", "fim": "22:00" }

// bloqueio_estado_mudado
{ "bloqueio_id": "b10c...0001", "de": "bloqueado", "para": "em_atendimento" }

// comando_invalido
{ "comando": "fechado", "erro": "valor_obrigatorio", "mensagem_grupo_id": "3EB0ERR0001" }
```

---

#### `envios_evolution.payload` — por tipo e contexto

```json
// tipo "ia", contexto "conversa_cliente"
{ "tipo_msg": "texto", "len": 64 }

// tipo "midia", contexto "conversa_cliente"
{ "midia_id": "018f...0004", "tipo": "foto", "tag": "apresentacao" }

// tipo "card", contexto "grupo_coordenacao" — cliente chegou (interno)
{ "titulo": "Cliente chegou", "escalada_id": "018f...0004" }

// tipo "card", contexto "grupo_coordenacao" — Pix validado (externo)
{ "titulo": "Saída confirmada", "escalada_id": "018f...0003" }

// tipo "card", contexto "grupo_coordenacao" — Pix em revisão
{ "titulo": "Pix em revisão", "escalada_id": "018f...0001" }

// tipo "card", contexto "grupo_coordenacao" — handoff IA
{ "titulo": "Handoff IA - cliente ambíguo", "escalada_id": "018f...0005" }

// tipo "confirmacao", contexto "grupo_coordenacao" — resposta a comando
{ "comando": "finalizado 2500", "valor_final": 2500 }

// tipo "erro_comando", contexto "grupo_coordenacao"
{ "erro": "valor_obrigatorio", "comando_recebido": "fechado" }
```

---

### Máquina de Estados — Transições Válidas

```
(criação) ──────────────────────────────────► Novo
Novo ──► Triagem ──► Qualificado ──► Aguardando_confirmacao
                                            │
                              ┌─────────────┴──────────────┐
                         interno                        externo
                    foto de portaria              Pix validado
                              │                            │
                         Em_execucao                 Confirmado
                                                          │
                                                   cron horário
                                                          │
                                                     Em_execucao
                              └──────────┬─────────────────┘
                                    Fechado (valor_final obrigatório)
                                    Perdido (motivo obrigatório; 'outro' exige obs)
                                    ↑ pode vir de qualquer estado
```

**`ia_pausada` é flag ortogonal — coexiste com qualquer estado:**

| Motivo | Disparado por | Liberado por |
|---|---|---|
| `pix_em_revisao` | Pipeline OCR falha | Fernando valida/recusa via painel |
| `modelo_em_atendimento` | Foto de portaria (interno) ou Pix validado (externo) | `finalizado [valor]` da modelo ou devolução manual |
| `handoff_ia` | `escalar()` da IA | `IA assume` no grupo ou botão painel |

**`fonte_decisao` por origem da transição:**

| Valor | Quando usar |
|---|---|
| `extracao_ia` | IA chamou `registrar_extracao` |
| `webhook_imagem` | Imagem recebida em `Aguardando_confirmacao` interno |
| `pipeline_pix` | OCR validou Pix automaticamente |
| `comando_grupo` | Comando da modelo/Fernando no grupo de coordenação |
| `painel_fernando` | Ação de Fernando no painel (incluindo kanban) |
| `auto_timeout` | Cron — 24h sem confirmação |
| `auto_timeout_interno` | Cron — 30min após aviso de saída sem foto |
| `cron_em_execucao` | Cron — horário previsto chegou, bloqueio → `em_atendimento` |

---

### Regras de Negócio para Seeds Realistas

**Modelos:**
- `valor_padrao`: entre R$ 800 e R$ 2.500 (premium)
- `percentual_repasse`: apenas 30, 40 ou 50
- `tipo_atendimento_aceito`: array com pelo menos um valor; `{interno,externo}` = aceita ambos
- `idiomas`: sempre inclui `pt-BR`; estrangeiras têm `{pt-BR,en-US}` ou `{pt-BR,es-ES}`
- Mínimo 10 `modelo_midia` por modelo antes do piloto (tags: `apresentacao`, `corpo`, `lifestyle`, `evento`)

**Clientes:**
- `telefone`: formato E.164 com `+` (ex: `+5521999990001`)
- `nome`: pode ser NULL (cliente que nunca se identificou)
- `primeiro_contato_modelo_id`: ID da primeira modelo que o cliente contactou

**Conversas:**
- Uma por par `(cliente_id, modelo_id)` — constraint única
- `evolution_chat_id`: `{telefone_sem_plus}@s.whatsapp.net`
- `recorrente = true` somente se o cliente tem atendimento fechado anterior no mesmo par
- `ultima_mensagem_em` e `ultima_mensagem_direcao`: preenchidos por trigger ao inserir mensagem

**Atendimentos:**
- `numero_curto`: gerado pelo trigger — **não inserir manualmente em seeds reais**; pode setar explicitamente em seeds de teste se o trigger não for chamado
- Um único atendimento aberto por par `(cliente_id, modelo_id)` (constraint parcial)
- `valor_final`: obrigatório quando `estado = 'Fechado'`
- `motivo_perda`: obrigatório quando `estado = 'Perdido'`
- `motivo_perda_obs`: obrigatório quando `motivo_perda = 'outro'`
- `ia_pausada_motivo`: obrigatório quando `ia_pausada = true`
- `pix_status = 'nao_solicitado'` em atendimentos internos (Pix não se aplica ao fluxo interno)
- `bloqueio_id`: NULL até a IA criar o bloqueio de agenda

**Bloqueios:**
- `inicio < fim` (check constraint)
- Sem sobreposição para o mesmo `modelo_id` em estados `bloqueado` ou `em_atendimento` (índice GiST exclusivo)
- `origem = 'ia'` quando criado pela IA no fluxo normal; `'painel_fernando'` quando Fernando cria manualmente
- `atendimento_id = NULL` para bloqueios manuais avulsos (ex: folga)

**Mensagens:**
- `evolution_message_id`: único globalmente — use padrões distintos nas seeds (ex: `3EB0MSG{n}`)
- `conteudo`: texto decodificado ou transcrição; nunca NULL (default `''`)
- `media_object_key`: obrigatório quando `tipo ∈ {audio, imagem}` (check constraint)
- `atendimento_id`: NULL para mensagens antes de haver atendimento vinculado

**Comprovantes Pix:**
- Sempre ligados a uma `mensagem` de `tipo = 'imagem'`
- `decisao_pipeline = 'validado'` → `atendimentos.pix_status = 'validado'`
- `decisao_pipeline = 'em_revisao'` → `atendimentos.pix_status = 'em_revisao'`, `ia_pausada = true`, motivo `pix_em_revisao`

**Escaladas:**
- `card_message_id`: ID Evolution da mensagem do card no grupo; NULL se a escalada foi pelo painel
- `fechada_por`: ID do `usuario` que fechou (sempre Fernando no P0)
- `fechada_canal`: `grupo_coordenacao` (comando), `painel` (botão), `pipeline_pix` (Pix validado automático)

**Eventos:**
- Append-only — nunca deletar
- Toda transição de estado gera um evento `transicao_estado`
- Toda abertura de handoff gera `handoff_aberto`
- `autor = 'sistema'` para cron/pipeline; `'IA'` para agente; `'Fernando'`/`'modelo'` para humanos

**Tags de mídia válidas:** `apresentacao`, `corpo`, `lifestyle`, `evento`
*(A seed pode incluir a tag `lingerie` — está presente no banco real)*

---

### Ordem de Inserção para Seeds (dependências FK)

```
1.  auth.users          — Supabase Auth (Fernando)
2.  usuarios            — criado por trigger ou manual
3.  duracoes            — sem FK de barravips
4.  programas           — sem FK de barravips
5.  modelos             — sem FK de barravips
6.  modelo_faq          — FK → modelos
7.  modelo_midia        — FK → modelos
8.  modelo_servicos     — FK → modelos
9.  modelo_programas    — FK → modelos, programas, duracoes
10. clientes            — FK → modelos (primeiro_contato)
11. conversas           — FK → clientes, modelos
12. bloqueios           — FK → modelos (sem atendimento_id ainda)
13. atendimentos        — FK → clientes, modelos, conversas (bloqueio_id NULL até criar)
14. [UPDATE bloqueios.atendimento_id após criar atendimentos]
15. [UPDATE atendimentos.bloqueio_id após criar bloqueios]
16. mensagens           — FK → conversas, atendimentos
17. comprovantes_pix    — FK → atendimentos, mensagens
18. escaladas           — FK → atendimentos, usuarios
19. eventos             — FK → atendimentos
20. envios_evolution    — FK → atendimentos, conversas
21. atendimento_servicos — FK → atendimentos, programas, duracoes
```

> **Atenção à referência circular:** `atendimentos.bloqueio_id → bloqueios.id` e `bloqueios.atendimento_id → atendimentos.id`. Inserir com NULL em ambos, depois fazer UPDATE em um dos dois.

---

### Exemplo de Seed Narrativa — Ciclo Completo

**Cenário:** Modelo "Alessia", cliente "Ricardo", atendimento **interno fechado**.

```
1. usuarios: Fernando (id vinculado ao auth.users)
2. modelos: Alessia (interno+externo, R$ 1.500/h, 40% repasse, instance_id = evo_alessia)
3. modelo_midia: 10 fotos/vídeos (tags: apresentacao x3, corpo x3, lifestyle x2, evento x2)
4. clientes: Ricardo (+5521999990001, primeiro_contato_modelo_id = Alessia)
5. conversas: Ricardo↔Alessia (evolution_chat_id = 5521999990001@s.whatsapp.net)
6. bloqueios: 20h–22h, estado = bloqueado, origem = ia (criado durante qualificação)
7. atendimentos: estado = Fechado, tipo = interno, valor_final = 1800
   sinais_qualificacao = {informa_horario:true, informa_local:true, aceita_valor:true, envia_pix:false, responde_objetivamente:true}
   ia_pausada = false, pix_status = nao_solicitado
   aviso_saida_em = 2026-05-01 19:45:00-03
   foto_portaria_em = 2026-05-01 20:03:00-03
   fonte_decisao_ultima_transicao = comando_grupo
8. [UPDATE bloqueios: estado = concluido, atendimento_id = id_atendimento]
9. [UPDATE atendimentos: bloqueio_id = id_bloqueio]
10. mensagens (na ordem cronológica):
    - "Oi, estava pensando em ir aí hoje à noite" (cliente, texto)
    - [resposta da IA perguntando horário] (ia, texto)
    - "Tipo umas 20h" (cliente, texto)
    - [IA confirma e pede endereço] (ia, texto)
    - [imagem da portaria] (cliente, imagem, foto_portaria_em = atendimentos.foto_portaria_em)
    - "finalizado 1800" (modelo_manual, texto)
11. escaladas: handoff implícito da foto de portaria (responsavel = modelo, fechada via grupo)
12. eventos (em ordem):
    - transicao_estado: Novo → Triagem (extracao_ia)
    - transicao_estado: Triagem → Qualificado (extracao_ia, com sinais)
    - transicao_estado: Qualificado → Aguardando_confirmacao (extracao_ia)
    - bloqueio_criado
    - extracao_registrada (aviso_saida_em)
    - handoff_aberto (foto de portaria, responsavel = modelo)
    - transicao_estado: Aguardando_confirmacao → Em_execucao (webhook_imagem, trigger = foto_portaria)
    - bloqueio_estado_mudado (bloqueado → em_atendimento)
    - fechado_registrado (comando = "finalizado 1800", valor_final = 1800)
    - transicao_estado: Em_execucao → Fechado (comando_grupo)
    - bloqueio_estado_mudado (em_atendimento → concluido) [via trigger sync_bloqueio_estado]
13. envios_evolution:
    - tipo = card, contexto = grupo_coordenacao, payload = {titulo: "Cliente chegou", escalada_id: ...}
    - tipo = confirmacao, contexto = grupo_coordenacao, payload = {comando: "finalizado 1800", valor_final: 1800}
```

---

### Exemplos de Textos Realistas para Seeds

**Campos de texto livres:**

```
escaladas.resumo_operacional:
  "Ricardo avisou que saiu de casa às 19h45. Foto da portaria recebida às 20h03. IA pausada."
  "Pix de R$ 200 recebido mas titular diverge do cadastro. Pipeline sinalizou revisão."
  "Cliente Igor fez perguntas ambíguas sobre identidade da modelo. IA solicitou avaliação."

escaladas.acao_esperada:
  "Atender normalmente. Encerrar com finalizado [valor] ao término."
  "Validar ou recusar o comprovante pelo painel."
  "Decidir se segue, recusa ou ajusta o roteiro pelo painel."

atendimentos.resumo_operacional:
  "Cliente recorrente, agendado para 20h, interno. Confirmou endereço em Ipanema."
  "Novo cliente, externo, Barra da Tijuca, horário a combinar. Pix pendente."

atendimentos.proxima_acao_esperada:
  "Aguardar foto da portaria do cliente."
  "Aguardar Pix de deslocamento (R$ 200)."
  "Registrar finalizado [valor] após encerramento."

modelo_faq.pergunta / resposta:
  "Você atende em qual região?" / "Atendo em toda a Zona Sul e Barra. Regiões mais distantes têm taxa de deslocamento."
  "Qual o valor do programa?" / "O valor varia de acordo com o programa escolhido. Posso te informar os detalhes!"
  "Você é real?" / "Claro que sim! 😊 Minhas fotos são recentes e autênticas."
```

---

```
auth.users
    └─ usuarios (id FK CASCADE)

usuarios
    ←── comprovantes_pix.decisao_final_por (SET NULL)
    ←── escaladas.fechada_por (SET NULL)

modelos
    ←── conversas.modelo_id (RESTRICT)
    ←── atendimentos.modelo_id (RESTRICT)
    ←── bloqueios.modelo_id (RESTRICT)
    ←── clientes.primeiro_contato_modelo_id (SET NULL)
    ←── modelo_faq.modelo_id (CASCADE)
    ←── modelo_midia.modelo_id (CASCADE)
    ←── modelo_servicos.modelo_id (CASCADE)
    ←── modelo_programas.modelo_id (CASCADE)

clientes
    ←── conversas.cliente_id (RESTRICT)
    ←── atendimentos.cliente_id (RESTRICT)

conversas (UNIQUE: cliente_id + modelo_id)
    ←── atendimentos.conversa_id (RESTRICT)
    ←── mensagens.conversa_id (CASCADE)
    ←── envios_evolution.conversa_id (SET NULL)

atendimentos (UNIQUE aberto: cliente_id + modelo_id)
    ←── bloqueios.atendimento_id (SET NULL)
    ←── mensagens.atendimento_id (SET NULL)
    ←── comprovantes_pix.atendimento_id (CASCADE)
    ←── escaladas.atendimento_id (CASCADE)
    ←── eventos.atendimento_id (SET NULL)
    ←── envios_evolution.atendimento_id (SET NULL)
    ←── atendimento_servicos.atendimento_id (CASCADE)
    └─► bloqueios.id (SET NULL via bloqueio_id)

bloqueios
    └─► atendimentos.bloqueio_id (referência circular controlada)

mensagens
    ←── comprovantes_pix.mensagem_id (CASCADE)

programas
    ←── modelo_programas.programa_id (RESTRICT)
    ←── atendimento_servicos.programa_id (RESTRICT)

duracoes
    ←── modelo_programas.duracao_id (RESTRICT)
    ←── atendimento_servicos.duracao_id (RESTRICT)
```
