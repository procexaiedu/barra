# 06 — Dados e Interfaces

Este documento concentra a modelagem das entidades operacionais e o desenho das telas do painel. Não substitui a stack (`07-stack-tecnica.md`), os fluxos (`04-fluxos-operacionais.md`) nem a definição de módulos (`03-modulos-sistema.md`); descreve **o que é persistido** e **o que Fernando vê**. O DDL canônico do MVP está em `infra/sql/0001_schema_inicial.sql` (schema `barravips`); este arquivo e o SQL devem permanecer alinhados.

## 1. Princípios de modelagem

- **Postgres é a fonte de verdade** (`03 §7.4`); todas as decisões, estados, agenda, Pix, escaladas e registros comerciais são persistidos antes de qualquer ação operacional.
- **Schema único `barravips`** no Postgres do Supabase managed (definido em `infra/sql/0001_schema_inicial.sql`); conexão da app via Supavisor 6543 (`07 §7.8`).
- **RLS habilitada (FORCE) em todas as tabelas**; no P0 a policy `fernando_full_access` libera operações para usuários autenticados com papel `fernando` em `usuarios` — isolamento granular por `modelo_id` fica para P1 junto com vendedor read-only (`07 §7.8`).
- **`id` em UUID v7** — no schema inicial, default `barravips.uuidv7()` no banco (PL/pgSQL até PG18); o app pode gerar v7 antes do insert se necessário.
- **`created_at`/`updated_at`** com `timestamptz` onde aplicável; default `now()`; triggers mantêm `updated_at` nas tabelas que possuem a coluna.
- **Soft-delete não é usado no MVP**; remoções são raras e ficam em Fernando pelo painel.
- **Convenção de nome**: snake_case para tabelas e colunas; enums em `barravips.<nome>_enum`.
- **Auditoria via tabela `eventos`** — checkpointer LangGraph não é audit log (`07 §2.2`).

---

## 2. Entidades de domínio

### 2.1 `modelos`

Profissional cadastrada que opera no sistema.

A **persona e o tom** da IA vêm de um **template versionado no repositório** (ex.: `persona.md` no agente), não de colunas free-text no banco. Só entram em `modelos` os **campos estruturados** interpolados nesse template (nome, idade, idiomas, localização, tipos de atendimento aceitos, etc.). Política comercial, restrições finas e regras longas continuam endereçadas por **FAQ** (`modelo_faq`) e pelo desenho dos fluxos — não há tabela `modelo_perfil` no schema inicial.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | UUID v7 (default no banco) |
| `nome` | text | Nome operacional usado pela IA |
| `idade` | integer | Variável estruturada no system prompt; `CHECK (idade > 0)` |
| `numero_whatsapp` | text | Número da modelo, vinculado ao Evolution |
| `evolution_instance_id` | text nullable | Identificador da instância Evolution |
| `status` | enum (`ativa`, `pausada`, `inativa`) | Controle operacional |
| `valor_padrao` | numeric(10,2) | Hora padrão (ex: 1000.00); `>= 0` |
| `percentual_repasse` | numeric(5,2) nullable | 30, 40 ou 50; opcional (`01 §1`); 0–100 quando preenchido |
| `chave_pix` | text nullable | Chave Pix para deslocamento |
| `titular_chave` | text nullable | Titular da chave |
| `idiomas` | text[] | BCP-47 (ex.: `pt-BR`, `en-US`); default `{pt-BR}`; interpolados no prompt |
| `localizacao_operacional` | text nullable | Bairro/região onde a modelo atende |
| `tipo_atendimento_aceito` | `tipo_atendimento[]` | Tipos que a modelo realiza (`interno`, `externo`); array não vazio — a IA usa no qualificador para não negociar tipo inaceitável |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Restrições:
- `numero_whatsapp` único.
- No P0, esperado **1 modelo piloto** ativa por vez (`02 §3.1`).

### 2.2 `modelo_faq`

FAQ operacional consultada pela IA via `consultar_faq`.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `modelo_id` | uuid nullable (FK→modelos) | NULL = FAQ global; preenchido = especialização (`03 §4.5`) |
| `pergunta` | text | |
| `resposta` | text | |
| `tags` | text[] | Para busca |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Mínimo 20–30 FAQs globais revisadas por Fernando antes do piloto (`03 §4.5`).

### 2.3 `modelo_midia`

Mídia pré-aprovada armazenada em MinIO.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `modelo_id` | uuid (FK→modelos) | |
| `tipo` | enum (`foto`, `video`) | |
| `tag` | text | Ex: `apresentacao`, `corpo`, `lifestyle`, `evento` |
| `bucket` | text | `media` |
| `object_key` | text | Caminho no MinIO |
| `aprovada` | boolean default true | Apenas mídia aprovada é enviável |
| `created_at` | timestamptz | |

Mínimo 10 mídias aprovadas por modelo antes do piloto (`02 §3.1`, `03 §4.5`).

### 2.4 `clientes`

Cliente identificado por número de WhatsApp. Entidade global, mas **histórico operacional vive em `conversas`** (par cliente, modelo) — IA por modelo é isolada (`04 §4.1`).

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `telefone` | text | Formato E.164 |
| `nome` | text nullable | Quando informado pelo cliente em qualquer conversa |
| `primeiro_contato_modelo_id` | uuid nullable (FK→modelos) | Modelo que originou o cliente na operação; preenchido na criação do primeiro registro; atributo identitário (isolamento operacional continua por conversa) |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Restrições:
- `telefone` único.

### 2.5 `conversas`

Hilo de WhatsApp entre cliente e modelo. **Uma conversa por par (cliente, modelo)** — unidade que carrega histórico, recorrência e observações do CRM (`04 §4.1`). A IA da modelo X enxerga apenas a conversa em que está atuando.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | Usado como `thread_id` no LangGraph (`07 §7.1`) |
| `cliente_id` | uuid (FK→clientes) | |
| `modelo_id` | uuid (FK→modelos) | |
| `evolution_chat_id` | text | JID Evolution |
| `recorrente` | boolean default false | True após o primeiro atendimento `Fechado` ou `Perdido` desta conversa |
| `observacoes_internas` | text nullable | Texto livre da modelo/Fernando; escopo restrito a esta conversa |
| `ultimo_motivo_perda` | enum nullable | Snapshot do último `Perdido` desta conversa para uso da IA |
| `ultima_mensagem_em` | timestamptz nullable | Preenchido por trigger a cada insert em `mensagens`; desnormalização para ordenar lista de conversas por atividade |
| `ultima_mensagem_direcao` | enum nullable | Última direção da mensagem (`cliente` / `ia` / `modelo_manual`); sincronizado com o insert |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | Atualizado em mudanças na própria conversa (não substitui `ultima_mensagem_em`) |

Restrições:
- Único `(cliente_id, modelo_id)`.

### 2.6 `mensagens`

Histórico bruto. Persistido por 5.1 antes de qualquer decisão (`03 §5.1`).

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `conversa_id` | uuid (FK→conversas) | |
| `atendimento_id` | uuid nullable (FK→atendimentos) | Atribuído pelo coordenador após resolver/criar |
| `direcao` | enum (`cliente`, `ia`, `modelo_manual`) | Somente tráfego da conversa cliente↔modelo/IA |
| `tipo` | enum (`texto`, `audio`, `imagem`) | |
| `conteudo` | text | Texto ou transcrição |
| `media_object_key` | text nullable | Quando `tipo` ∈ {audio, imagem}; obrigatório se não for `texto` |
| `evolution_message_id` | text | Idempotência no webhook; único |
| `created_at` | timestamptz | |

**Grupo de Coordenação:** mensagens de card, confirmações e correlatos **não** são persistidas em `mensagens`. O handoff fica em `escaladas` (ex.: `card_message_id`) e o rastro auditável em `eventos` / payload. Se no futuro for necessário histórico bruto do grupo, prevê-se uma tabela dedicada (ex. `mensagens_grupo`).

Índices:
- `(conversa_id, created_at desc)` para histórico.
- Único `evolution_message_id`.

### 2.7 `atendimentos`

Ciclo comercial. **Um atendimento aberto por (cliente, modelo)**.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `numero_curto` | int | Para uso como `#N` em comandos do grupo (`05 §3`); sequencial por modelo; gerado por trigger no insert se omitido |
| `cliente_id` | uuid (FK→clientes) | |
| `modelo_id` | uuid (FK→modelos) | |
| `conversa_id` | uuid (FK→conversas) | |
| `bloqueio_id` | uuid nullable (FK→bloqueios) | Quando há agenda vinculada |
| `estado` | enum estado_atendimento | Ver `03 §4.2` |
| `tipo_atendimento` | enum (`interno`, `externo`) nullable | NULL até a IA decidir |
| `urgencia` | enum (`imediato`, `agendado`, `indefinido`, `estimado`) nullable | |
| `data_desejada` | date nullable | |
| `horario_desejado` | time nullable | |
| `duracao_horas` | numeric(4,2) nullable | |
| `endereco` | text nullable | Obrigatório para `externo` |
| `bairro` | text nullable | |
| `tipo_local` | enum (`hotel`, `casa`, `apartamento`, `outro`) nullable | |
| `referencia_local` | text nullable | |
| `forma_pagamento` | enum (`pix`, `dinheiro`, `outro`) nullable | |
| `valor_acordado` | numeric(10,2) nullable | |
| `valor_final` | numeric(10,2) nullable | Bruto pago pelo cliente; obrigatório em `Fechado` |
| `percentual_repasse_snapshot` | numeric(5,2) nullable | Snapshot opcional do acordo (`01 §1`) |
| `motivo_perda` | enum (`preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`) nullable | Obrigatório em `Perdido` |
| `motivo_perda_obs` | text nullable | Obrigatório quando `motivo_perda='outro'` |
| `pix_status` | enum (`nao_solicitado`, `aguardando`, `enviado`, `em_revisao`, `validado`, `invalido`) | Default `nao_solicitado` |
| `aviso_saida_em` | timestamptz nullable | Cliente avisou que saiu (interno) |
| `foto_portaria_em` | timestamptz nullable | Webhook recebeu foto (interno) |
| `ia_pausada` | boolean default false | Flag ortogonal ao estado (`04 §8.5`) |
| `ia_pausada_motivo` | enum (`pix_em_revisao`, `modelo_em_atendimento`, `handoff_ia`) nullable | |
| `responsavel_atual` | enum (`IA`, `Fernando`, `modelo`) | Default `IA` |
| `proxima_acao_esperada` | text nullable | Preenchido pela IA na escalada (`05 §2.1`) |
| `motivo_escalada` | text nullable | |
| `resumo_operacional` | text nullable | Gerado pela IA na escalada |
| `sinais_qualificacao` | jsonb | `{informa_horario, informa_local, aceita_valor, envia_pix, responde_objetivamente}`; default `{}` no schema |
| `fonte_decisao_ultima_transicao` | enum | Ver `04 §9.1` |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Restrições:
- Único `(modelo_id, numero_curto)`.
- **Único parcial** `(cliente_id, modelo_id)` quando `estado` ∉ {`Fechado`, `Perdido`}, garantindo um atendimento aberto por par.
- Check: `valor_final IS NOT NULL` quando `estado='Fechado'`.
- Check: `motivo_perda IS NOT NULL` quando `estado='Perdido'`.
- Check: `motivo_perda_obs IS NOT NULL` quando `motivo_perda='outro'`.
- Check: se `ia_pausada=true`, então `ia_pausada_motivo IS NOT NULL`.

### 2.8 `bloqueios`

Reserva de agenda da modelo.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `modelo_id` | uuid (FK→modelos) | |
| `atendimento_id` | uuid nullable (FK→atendimentos) | NULL = bloqueio manual avulso |
| `inicio` | timestamptz | |
| `fim` | timestamptz | |
| `estado` | enum (`bloqueado`, `em_atendimento`, `concluido`, `cancelado`) | Ver `03 §4.3` |
| `origem` | enum (`ia`, `painel_fernando`, `manual`) | |
| `observacao` | text nullable | |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Restrições:
- Constraint de exclusão (Postgres `EXCLUDE USING gist`) impedindo sobreposição em estados ativos (`bloqueado`, `em_atendimento`) por `modelo_id`.

### 2.9 `comprovantes_pix`

Comprovantes recebidos pelo pipeline OCR/vision (4.6/5.6).

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `atendimento_id` | uuid (FK→atendimentos) | |
| `mensagem_id` | uuid (FK→mensagens) | Imagem original |
| `valor_extraido` | numeric(10,2) nullable | OCR |
| `chave_extraida` | text nullable | |
| `titular_extraido` | text nullable | |
| `timestamp_extraido` | timestamptz nullable | |
| `decisao_pipeline` | enum (`validado`, `em_revisao`) | |
| `motivo_em_revisao` | text nullable | Qual checagem falhou |
| `decisao_final` | enum (`validado`, `invalido`) nullable | Após Fernando atuar quando `em_revisao` |
| `decisao_final_por` | uuid nullable (FK→usuarios) | |
| `created_at` | timestamptz | |

### 2.10 `escaladas`

Cards de handoff abertos no grupo de Coordenação por modelo (`03 §5.4`).

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `atendimento_id` | uuid (FK→atendimentos) | |
| `responsavel` | enum (`Fernando`, `modelo`) | |
| `motivo` | text | Campo livre, dashboard agrega por contagem (`03 §5.4`); NOT NULL no schema |
| `resumo_operacional` | text | NOT NULL no schema |
| `acao_esperada` | text | NOT NULL no schema |
| `card_message_id` | text nullable | ID Evolution do card no grupo |
| `aberta_em` | timestamptz | |
| `fechada_em` | timestamptz nullable | Quando devolvida ou registrada |
| `fechada_por` | uuid nullable (FK→usuarios) | |
| `fechada_canal` | enum (`grupo_coordenacao`, `painel`, `pipeline_pix`) nullable | |

### 2.11 `eventos`

Audit log humano-legível. Recebe insert em **toda** ação operacional persistida (`03 §7.4`, `07 §2.2`).

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | |
| `atendimento_id` | uuid nullable (FK→atendimentos) | NULL para eventos não vinculados |
| `tipo` | enum | Ver §2.11.1 |
| `origem` | enum (`agente`, `grupo_coordenacao`, `painel`, `pipeline_pix`, `cron`) | |
| `autor` | enum (`IA`, `Fernando`, `modelo`, `sistema`) | |
| `payload` | jsonb | Dados da ação (estado anterior, novo estado, valor, motivo) |
| `created_at` | timestamptz | |

#### 2.11.1 Tipos de evento P0

- `transicao_estado`
- `extracao_registrada`
- `pix_solicitado`
- `pix_status_mudado`
- `handoff_aberto`
- `devolucao_para_ia`
- `fechado_registrado`
- `perdido_registrado`
- `correcao_registro`
- `bloqueio_criado`
- `bloqueio_estado_mudado`
- `comando_invalido`

### 2.12 `usuarios`

Operadores do painel. No P0, apenas Fernando.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | uuid (PK) | Vinculado a `auth.users` do Supabase |
| `nome` | text | |
| `email` | text | Único |
| `papel` | enum (`fernando`, `vendedor_read_only`) | `vendedor_read_only` é P1 |
| `ativo` | boolean default true | |
| `created_at` | timestamptz | |

### 2.13 Diagrama relacional resumido

```text
modelos ─┬─ modelo_faq (1:N)
         ├─ modelo_midia (1:N)
         ├─ conversas ── mensagens (1:N) → trigger atualiza ultima_mensagem_* na conversa
         │       └── atendimentos (1:N) ─┬─ bloqueios (1:1 quando vinculado)
         │                               ├─ comprovantes_pix (1:N)
         │                               ├─ escaladas (1:N)  ← cards / handoff grupo
         │                               └─ eventos (1:N)
         └─ bloqueios (1:N, atendimento_id NULL para bloqueio avulso)
clientes (opcional primeiro_contato_modelo_id → modelos) ── conversas (1:N) ── ...
usuarios (Fernando, vendedor read-only P1; sync auth.users → barravips.usuarios)
```

---

## 3. Enumerações canônicas

| Enum | Valores |
|------|---------|
| `estado_atendimento` | `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`, `Confirmado`, `Em_execucao`, `Fechado`, `Perdido` |
| `tipo_atendimento` | `interno`, `externo` |
| `urgencia` | `imediato`, `agendado`, `indefinido`, `estimado` |
| `tipo_local` | `hotel`, `casa`, `apartamento`, `outro` |
| `forma_pagamento` | `pix`, `dinheiro`, `outro` |
| `motivo_perda` | `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro` |
| `pix_status` | `nao_solicitado`, `aguardando`, `enviado`, `em_revisao`, `validado`, `invalido` |
| `ia_pausada_motivo` | `pix_em_revisao`, `modelo_em_atendimento`, `handoff_ia` |
| `responsavel_atual` | `IA`, `Fernando`, `modelo` |
| `direcao_mensagem` | `cliente`, `ia`, `modelo_manual` (conteúdo do grupo de coordenação não entra em `mensagens`; ver §2.6) |
| `tipo_mensagem` | `texto`, `audio`, `imagem` |
| `estado_bloqueio` | `bloqueado`, `em_atendimento`, `concluido`, `cancelado` |
| `origem_bloqueio` | `ia`, `painel_fernando`, `manual` |
| `decisao_pipeline_pix` | `validado`, `em_revisao` |
| `decisao_final_pix` | `validado`, `invalido` |
| `papel_usuario` | `fernando`, `vendedor_read_only` |
| `fonte_decisao` | `extracao_ia`, `webhook_imagem`, `pipeline_pix`, `comando_grupo`, `painel_fernando`, `auto_timeout`, `auto_timeout_interno`, `cron_em_execucao` |
| `tipo_evento` | Ver §2.11.1 |
| `origem_evento` | `agente`, `grupo_coordenacao`, `painel`, `pipeline_pix`, `cron` |
| `autor_evento` | `IA`, `Fernando`, `modelo`, `sistema` |
| `modelo_status` | `ativa`, `pausada`, `inativa` |
| `midia_tipo` | `foto`, `video` |
| `escalada_responsavel` | `Fernando`, `modelo` |
| `escalada_canal` | `grupo_coordenacao`, `painel`, `pipeline_pix` |

No Postgres, os tipos são `barravips.<nome>_enum` (ex.: `direcao_mensagem_enum`).

## 4. Telas do painel

Painel é Next.js 16.2 + React 19 + shadcn/ui + Supabase Auth + Realtime (`07 §7.11`). Único usuário no P0 é Fernando.

### 4.1 Painel Geral

Tela inicial. Visão operacional rápida do dia (`03 §4.1`).

**Componentes:**
- **Cabeçalho** com data/hora e modelo ativa.
- **Cards de destaque** ordenados por urgência:
  - `pix_em_revisao` (vermelho) — Fernando valida ou recusa.
  - `handoff_ia` (vermelho) — IA escalou para Fernando: risco, política, conflito de agenda, etc.
  - `modelo_em_atendimento` com tempo previsto expirado (amarelo) — botão `Devolver para IA`.
- Cada card mostra: `#N`, cliente, motivo do destaque, responsável atual, próxima ação esperada.
- **Métricas do dia**: atendimentos abertos, fechamentos, perdas, valor bruto.
- **Agenda do dia** resumida (lista cronológica).
- **Acessos rápidos** para Central de Atendimentos, Agenda, Pix, Modelo, Dashboard.

**Eventos Realtime:** subscribe em `atendimentos` filtrado por `ia_pausada=true` ou estado mudou hoje.

### 4.2 Central de Atendimentos

Lista e detalhe dos atendimentos abertos (`03 §4.2`).

**Lista (esquerda):**
- Filtros: estado, tipo, urgência, `ia_pausada`.
- Busca por cliente/telefone.
- Linha: `#N`, cliente, modelo, estado, tipo, urgência, indicador `ia_pausada`, última atualização.

**Detalhe (direita):**
- **Resumo do atendimento**: estado, tipo, horário, endereço/bairro, valor acordado, sinais de qualificação, motivo de escalada, próxima ação esperada.
- **Histórico de mensagens** (read-only no P0; sem edição manual). Indica direção (`cliente` / `ia` / `modelo_manual`) e tipo (texto/áudio com transcrição/imagem). **Conteúdo trocado no grupo de Coordenação (cards/confirmações)** não aparece aqui; use `escaladas` e a linha do tempo de `eventos`.
- **Mídia recebida** vinculada (comprovantes, foto de portaria).
- **Linha do tempo de eventos** (do `eventos`): transições, escaladas, devolução, registros.

**Ações (botões):**
- `Devolver para IA` — quando `ia_pausada=true` e for caso permitido.
- `Fechar` (com input de valor).
- `Perder` (com seletor de motivo + observação se `outro`).
- `Corrigir registro` — abre formulário com confirmação se bloqueio em `em_atendimento`/`concluido` (`05 §3.4`).

**Eventos Realtime:** subscribe em `mensagens`, `atendimentos`, `eventos` filtrado pelo atendimento aberto.

### 4.3 Agenda Operacional

Calendário da modelo piloto (`03 §4.3`).

**Visões:**
- Dia / Semana / Mês.
- Cores por estado de bloqueio (`bloqueado`, `em_atendimento`, `concluido`, `cancelado`).
- Origem (`ia` / `painel_fernando` / `manual`) indicada por ícone.

**Ações:**
- Clicar slot livre → criar bloqueio manual (data, hora, duração, observação).
- Clicar bloqueio → editar/cancelar (com aviso se vinculado a atendimento).
- Botão `Bloquear janela` para bloqueio avulso (sem atendimento).

**Conflitos:**
- Tentativa de criar bloqueio sobreposto → aviso visual e bloqueio impedido (constraint do Postgres).

**Eventos Realtime:** subscribe em `bloqueios`.

### 4.4 CRM

Histórico de **conversas** (par cliente, modelo) — não de clientes globais — porque histórico, recorrência e observações são por par (`04 §4.1`).

**Lista:**
- Filtros: novo/recorrente nesta conversa, último motivo de perda da conversa, data do último atendimento, modelo.
- Busca por telefone/nome (resolve para `clientes`, lista todas as conversas do cliente; no P0 com 1 modelo piloto, em geral haverá só uma conversa por cliente).
- Linha: nome (ou telefone), modelo, recorrente, último atendimento, último estado; opcionalmente **última atividade** (`conversas.ultima_mensagem_em` / direção).

**Detalhe:**
- Dados do cliente (telefone, nome, `primeiro_contato_modelo_id` quando existir — campos de `clientes`).
- Dados da conversa selecionada (recorrente, observações, último motivo de perda, última mensagem — campos de `conversas`).
- Edição inline de observações internas da conversa.
- Histórico de atendimentos da conversa: lista cronológica com estado, valor, motivo de perda.

**Importação da base antiga:** fora do MVP (`02 §3.2`).

### 4.5 Modelo — perfil + base de conhecimento

Cadastro e dados operacionais da modelo piloto (`03 §4.5`).

**Abas:**
- **Perfil**: nome, número WhatsApp (com botão `Conectar via QR code` que dispara o flow do Evolution — decisão grilling 29/04), valor padrão, percentual de repasse, chave Pix, titular.
- **Dados para o prompt**: idade, idiomas (BCP-47), localização operacional, tipos de atendimento aceitos (`interno`/`externo`) — persistidos em `modelos` e interpolados no template de persona versionado no repositório (não há `modelo_perfil` no banco).
- **FAQ**: política e dúvidas em texto; lista de FAQs globais e específicas; CRUD com campos `pergunta`, `resposta`, `tags`.
- **Mídia**: grid com mídias do MinIO; upload, marcar aprovada, definir tipo e tag, remover.

**Restrições:**
- IA Admin não edita perfil/FAQ/mídia no P0 (`03 §4.5`); operação pelo painel.
- Conexão WhatsApp restrita ao ambiente correspondente (Fase 1.5 = grupo de teste; Fase 2 = número da modelo) — decisão grilling 29/04.

### 4.6 Pix e Comprovantes

Lista e detalhe dos Pix em revisão (`03 §4.6`).

**Lista:**
- Filtros: `pix_status`, atendimento aberto/fechado.
- Linha: `#N`, cliente, modelo, valor extraído, motivo de em revisão, recebido em.

**Detalhe:**
- Dados extraídos pelo pipeline (valor, chave, titular, timestamp).
- Imagem do comprovante.
- Comparação com cadastro da modelo (chave esperada, titular esperado, valor esperado).
- Botões `Validar` e `Recusar` (com motivo opcional).

**Eventos Realtime:** subscribe em `comprovantes_pix` filtrado por `decisao_pipeline='em_revisao'` e `decisao_final IS NULL`.

### 4.7 Dashboard

Métricas P0 (`03 §4.7`).

**Visões:**
- Filtros: período (hoje, 7 dias, 30 dias).
- **Volume de atendimentos** por estado (Novo, Triagem, Qualificado, Aguardando_confirmacao, Confirmado, Em_execucao, Fechado, Perdido).
- **Taxa de conversão**: Fechados / (Fechados + Perdidos).
- **Fechamentos** com valor bruto agregado.
- **Perdas** com agregação por `motivo_perda`.
- **Profissionais mais procuradas** (no MVP, sempre a piloto, mas estrutura pronta para P1).
- **Pix em revisão pendentes**.
- **Atendimentos escalados** por motivo (texto livre agregado por contagem).

**Não inclui no P0:**
- Filtro por `fonte_decisao` (P1).
- Métricas por vendedor (vendedor é read-only no P0).
- Auditoria detalhada de classificador (P1).
- Toggle `is_test` — `is_test` foi removido do spec (decisão grilling 29/04).

---

## 5. APIs internas (esboço)

Não substituem contrato OpenAPI; descrevem o que existe para o painel consumir.

### 5.1 REST do painel

- `GET /api/atendimentos?estado=&tipo=&ia_pausada=` — lista paginada.
- `GET /api/atendimentos/:id` — detalhe + histórico de mensagens + eventos.
- `POST /api/atendimentos/:id/devolver` — chama 5.4 com origem `painel`.
- `POST /api/atendimentos/:id/fechar` — body `{valor}`.
- `POST /api/atendimentos/:id/perder` — body `{motivo, observacao?}`.
- `POST /api/atendimentos/:id/corrigir` — body `{novo_resultado, valor?, motivo?, observacao?}`.
- `GET /api/agenda?inicio=&fim=` — bloqueios da modelo.
- `POST /api/agenda/bloqueios` — cria bloqueio manual.
- `PATCH /api/agenda/bloqueios/:id` — edita/cancela.
- `GET /api/clientes` / `GET /api/clientes/:id` / `PATCH /api/clientes/:id`.
- `GET /api/conversas` / `GET /api/conversas/:id` / `PATCH /api/conversas/:id` — recorrente, observações, último motivo de perda da conversa.
- `GET /api/modelos/:id` (perfil completo).
- `PATCH /api/modelos/:id` (dados de `modelos`, incluindo campos estruturados do prompt; persona continua no repositório).
- `POST /api/modelos/:id/conectar-whatsapp` — dispara QR code Evolution.
- CRUD em `/api/modelos/:id/faq` e `/api/modelos/:id/midia`.
- `GET /api/pix/em-revisao` / `POST /api/pix/:id/validar` / `POST /api/pix/:id/recusar`.
- `GET /api/dashboard?periodo=`.

### 5.2 Webhook

- `POST /webhook/evolution` — payload do Evolution. Validado pelo Coordenador de Turno (`03 §5.2`); idempotência por `evolution_message_id`.

### 5.3 Realtime (Supabase)

Subscrições do painel respeitam RLS (`07 §7.8`). Tabelas expostas via Realtime no P0:
- `atendimentos`
- `mensagens`
- `bloqueios`
- `comprovantes_pix`
- `eventos`

---

## 6. Pontos abertos

- **Numeração curta `#N`**: sequencial por modelo é simples mas pode confundir quando houver múltiplas modelos em P1; revisar quando entrar a segunda.
- **Política de retenção de mídia do cliente**: fora do escopo MVP (`03 §5.1`); definir quando legal/LGPD virar prioridade.
- **Snapshot de percentual de repasse**: opcional no P0; revisar se relatórios financeiros virarem prioridade.
- **Backup do schema `barravips`**: coberto pelo daily backup do Supabase Pro + dump diário para MinIO (`07 §6`).
- **Migrações**: SQL puro sequencial em `infra/sql/NNNN_nome.sql`, sem migration framework. Aplicação manual via `psql` ou Supabase Studio na ordem numérica.
- **RLS para vendedor read-only (P1)**: política a definir quando a tela de vendedor entrar — provavelmente `select` em `mensagens` e `atendimentos` da modelo associada, sem `update`.
