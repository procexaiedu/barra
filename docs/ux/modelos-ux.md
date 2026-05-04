# Modelos — Guia UX para Iteração

> Doc operacional para agentes de IA iterarem o módulo. Foca em jornada, UX, propósito e dados — não em implementação técnica.

---

## Propósito no sistema

Modelos é a **tela de configuração central da operação**. Tudo que a IA sabe sobre uma modelo — como ela se apresenta, o que aceita, o que responde — vive aqui. Qualquer outra tela (Atendimentos, Agenda, CRM, Pix) apenas consome o que foi configurado aqui.

É também a única tela do painel autorizada a exibir fotos e mídias das modelos. Em todas as outras telas, a identidade visual da modelo é invisível — só o nome aparece.

Fernando usa essa tela de dois modos distintos:
- **Configuração** (menos frequente): cadastrar uma modelo nova, atualizar dados, conectar WhatsApp, ajustar FAQ e mídia antes do piloto
- **Operação** (eventual): pausar a modelo quando ela saiu para atendimento, reativar quando voltou, verificar se a IA está conectada

---

## Usuário e contexto de uso

**Único usuário:** Fernando. Modelos não acessam o painel.

**Pergunta na configuração:** "Preciso adicionar a Camila ao sistema" ou "A Júlia mudou de número, preciso atualizar."

**Pergunta na operação:** "A Júlia foi para o atendimento, preciso pausar a IA dela" ou "Quantas conversas ainda estão com a IA pausada?"

**Critério de sucesso (configuração):** Fernando completa o cadastro ou atualização de um bloco sem precisar navegar para outras telas.

**Critério de sucesso (operação):** Fernando pausa ou reativa a modelo em menos de 15 segundos.

---

## Jornada do usuário

```
Abrir /modelos
    → Lista carrega; primeira modelo ativa selecionada
    → Aba Perfil aberta por default
    → URL reflete ?modelo={id}&aba=perfil

Configuração inicial de nova modelo
    → Clicar "Adicionar modelo" → Dialog com campos mínimos → criar
    → Modelo criada selecionada automaticamente, aba Perfil aberta
    → Completar cards: Identidade, Contato, Serviços e preços, Repasse e Pix, Atendimento
    → Ir para aba Dúvidas → adicionar orientações específicas da modelo
    → Ir para aba Fotos e vídeos → fazer upload das fotos aprovadas

Conectar WhatsApp (parte do setup ou após troca de número)
    → Header mostra "Conectar WhatsApp" como primary quando não pareada
    → Clicar → Dialog abre com QR code
    → Modelo escaneia no WhatsApp dela
    → Modal fecha automaticamente via Realtime quando pareamento confirma

Pausar modelo para atendimento físico
    → Clicar "Pausar atendimentos" no header da modelo
    → AlertDialog mostra quantas conversas vão ser pausadas + quantos em andamento
    → Confirmar → IA pausa em todas as conversas ativas da modelo

Reativar modelo após retorno
    → Clicar "Reativar atendimentos" → AlertDialog explica que devolução é por conversa
    → Confirmar → modelo volta para ativa
    → Toast com action "Ver conversas" quando há conversas pausadas pendentes
    → Clicar action → vai para /atendimentos?ia_pausada=true&modelo_id={id}

Gerenciar catálogo (Programas e Durações)
    → Clicar na tab "Programas" no header
    → Duas colunas: catálogo de programas + opções de duração
    → Criar/editar/excluir programas e durações compartilhados
    → Vincular preços por modelo em AbaPerfil → Serviços e preços
```

---

## Blocos visuais

### 1. Header da página
**Localização:** inline em `app/(interface)/modelos/page.tsx`

Título "Modelos" em serif 28px. À direita no mesmo flex: tab navigation com duas views:

| Tab | Label | Ativa quando |
|---|---|---|
| `lista` | Modelos | padrão |
| `programas` | Programas | ao clicar |

Tab ativa recebe underline `after:bg-gold-500` (mesma convenção das abas de detalhe). Protegida por `protegerDirty` — trocar de view com edição pendente abre AlertDialog.

Botão "Adicionar modelo" (primary, `size="sm"`) aparece à direita, mas **fica oculto** quando:
- View = "programas", **ou**
- A modelo selecionada não tem `evolution_instance_id`, **ou**
- A modelo selecionada está `pausada`, **ou**
- A aba ativa é "midia"

---

### 2. Toolbar de filtros
**Arquivo:** `components/modelos/ToolbarModelos.tsx`

Busca + três selects nativos. Visível apenas na view `lista`.

| Controle | Tipo | Opções |
|---|---|---|
| Busca | Input com ícone Search | placeholder "Buscar nome, número ou bairro" |
| Situação | `<select>` | Todas situações · Ativas · Pausadas · Inativas |
| WhatsApp | `<select>` | Todos WhatsApp · WhatsApp pronto · WhatsApp pendente |
| Atende em | `<select>` | Atende em qualquer · Atende no local dela · Atende no local do cliente |

---

### 3. Lista de modelos
**Arquivos:** `components/modelos/ListaModelos.tsx` + `ItemModelo.tsx`

Grid `xl:grid-cols-[340px_1fr]` — coluna de 340px na esquerda. Visível apenas na view `lista`.

**Anatomia do item:**
```
[Nome da modelo]                           [Badge status]
[Telefone em mono]            [WhatsApp pendente — só quando sem evolution]
[N abertos · M pausados · ajuda há X]
```

- Linha 1: nome (truncate semibold) + Badge status à direita
- Linha 2: telefone mono + "WhatsApp pendente" em `text-state-handoff` (só quando `!evolution_instance_id`)
- Linha 3 (11px muted): indicadores — "N abertos" (text-secondary), "M pausados" (text-state-handoff), "ajuda {tempo}" ou "sem ajuda recente"

**Sinais visuais:**
- Selecionado: `bg-ink-100` + `border-l-gold-500`
- Inativa: `opacity-60`
- Default: `border-l-transparent`

> Não há borda colorida específica para "pausada não selecionada" — apenas para item selecionado.

**Skeleton:** 4 items `h-24`.

**Empty states:**
- Sem filtros: "Nenhuma modelo cadastrada." + "Adicione a primeira modelo para começar a operar." + botão primary "Adicionar modelo"
- Com filtros: "Nenhuma modelo encontrada para estes filtros." + "Ajuste situação, WhatsApp ou local de atendimento."

---

### 4. Header da modelo
**Arquivo:** `components/modelos/DetalheModelo.tsx`

Card `rounded-lg border bg-card px-4 py-3` no topo do painel direito.

```
[FotoPerfil size="sm"]  [Nome]  [Badge status]
                        [N anos · idiomas · bairro]  [WhatsApp pendente?]
                                                         [Ação contextual]
```

- Linha 1 (esquerda): FotoPerfil circular + nome (semibold) + Badge status
- Linha abaixo: `{idade} anos · {idiomas} · {localizacao_operacional ?? "sem região"}` — em 12px muted
- Quando sem evolution: `"WhatsApp pendente"` em `text-state-handoff` na mesma linha
- Direita: botões de ação contextual (ver tabela)

**Ação contextual:**

| Condição | Botão | Variante |
|---|---|---|
| `!evolution_instance_id` | Conectar WhatsApp | `primary` |
| `status === "ativa"` + `evolution_instance_id` | Pausar atendimentos | `secondary` |
| `status === "pausada"` | Reativar atendimentos | `primary` |
| `status === "inativa"` | (nenhum botão) | — |

**Skeleton:** `h-24` + `h-10` + `h-56` × 3.

**Empty state (sem seleção):** "Nenhuma modelo selecionada." + "Selecione uma modelo na lista ou adicione a primeira."

---

### 5. Abas do detalhe
**Arquivo:** `components/modelos/AbasModelo.tsx`

Três abas com URL sync (`?aba=perfil|faq|midia`). Underline `after:bg-gold-500` na aba ativa.

| Slug | Label visível |
|---|---|
| `perfil` | Perfil |
| `faq` | Dúvidas |
| `midia` | Fotos e vídeos |

Trocar aba com edição pendente passa pelo `protegerDirty` da page — abre AlertDialog antes de descartar.

---

### 6. Aba Perfil
**Arquivo:** `components/modelos/AbaPerfil.tsx`

Cinco blocos independentes em `space-y-5`. Cada bloco tem seu próprio botão "Salvar {bloco}" (`variant="secondary"`) que aparece **apenas quando há edição** (dirty). Salvar um bloco não afeta os outros.

**Bloco "Identidade":**
- Upload/remoção de foto de perfil
- Campos: Nome, Idade
- Campo Situação: `<select>` **desabilitado** (read-only) — muda via botões do header

**Bloco "Contato":**
- Campo: Número de WhatsApp
- Linha de status evolution: "WhatsApp pronto" (muted) ou "WhatsApp pendente" (state-handoff)
- Quando pareado: botões "Trocar conexão" (secondary) + "Remover conexão" (danger)
- Quando não pareado: botão "Conectar WhatsApp" (primary)
- Salvar número quando já pareado → aciona confirmação de troca de número antes de salvar

**Bloco "Serviços e preços"** (`components/modelos/ProgramasModelo.tsx`):
- Mostra o catálogo global de programas agrupado por categoria
- Para cada programa × duração: se vinculado mostra preço + editar/remover; se não mostra "Definir preço"
- Edição inline com Input + confirm/cancel (Enter/Escape funciona)
- Quando catálogo vazio: "Nenhum programa cadastrado... Acesse a aba Programas para adicionar."

**Bloco "Repasse e Pix":**
- Campos: Comissão da agência (%), Pix (chave), Nome no Pix (titular)
- Hint: mudança afeta apenas fechamentos futuros

**Bloco "Atendimento":**
- Campos: Bairro ou região, Idiomas (texto livre separado por vírgula)
- Checkboxes "Atende em": interno / externo
- Estes campos são interpolados no prompt da IA — editar aqui muda o comportamento da IA

---

### 7. Aba Dúvidas (FAQ)
**Arquivo:** `components/modelos/AbaFaq.tsx`

Lista de orientações que a IA usa para responder o cliente.

**Toolbar interna:**
- Busca: "Buscar pergunta, resposta ou tag"
- Select escopo: **Desta modelo** (default) · Gerais · Todas
- Botão "Adicionar resposta" (primary)

**Anatomia do card de FAQ:**
```
[Pergunta]             [chip "geral" — se global]
Resposta truncada em 2 linhas
[tags como chips bg-ink-200]
                       [ícone Editar]  [ícone Remover]  ← só no hover
```

FAQs globais (`modelo_id === null`) mostram chip `"geral"` (arredondado, `bg-ink-300`). Editar e excluir globais ficam **bloqueados** quando escopo é "Desta modelo" ou "Todas" — só desbloqueiam quando escopo é "Gerais".

**Empty state:** ícone `FileQuestion` + "Nenhuma resposta cadastrada para esta modelo." + "Adicione orientações para perguntas frequentes dos clientes."

---

### 8. Aba Fotos e vídeos (Mídia)
**Arquivo:** `components/modelos/AbaMidia.tsx` + `GridMidia.tsx` + `ItemMidia.tsx`

Grade de fotos e vídeos aprovados. **Única superfície do painel autorizada a exibir mídia das modelos.**

**Toolbar interna:**
- Select Tipo: Todos os tipos · Fotos · Vídeos
- Select Tag: Todas as tags · [tags únicas das mídias, ordenadas]
- Select Uso: **Prontas no atendimento** (default) · Ocultas · Todas
- Botão "Adicionar mídia" (primary, ml-auto)

**UX de upload** (`DialogMidiaUpload`): 4 passos — select arquivo → request URL assinada → PUT no MinIO → confirmar no backend. Suporta modo "midia" e "perfil".

---

### 9. View Programas
**Arquivo:** `components/modelos/PainelProgramas.tsx`

Acessível pela tab "Programas" no header. Gerencia o **catálogo global** da agência — programas e durações compartilhados por todas as modelos. Os preços por modelo são definidos em cada AbaPerfil → Serviços e preços.

Grid `xl:grid-cols-2` com dois cards lado a lado:

**Card "Programas":**
- Título + subtítulo "Serviços oferecidos pela agência. Preços por modelo." + contador
- Lista agrupada por categoria (seções com label uppercase muted)
- Itens sem categoria vão no topo sem agrupamento
- Edição inline: clique no Pencil → Input nome + Input categoria (com `<datalist>` de autocompletar) → confirm/cancel
- Remover com Trash2 (hover:text-state-lost)
- Footer de criação: Input nome + Input categoria + botão "Adicionar" (primary)

**Card "Durações":**
- Título + subtítulo "Opções disponíveis para todos os programas." + contador
- Lista linear de durações (ex.: "4 horas", "Final de semana")
- Edição inline: Input + confirm/cancel (Escape reverte)
- Footer de criação: Input + botão "Adicionar" (primary)

**Loading:** texto "Carregando programas...". **Erro:** `BannerErro`.

---

## Dados que alimentam a tela

Endpoints de leitura e ação:

| Chamada | O que faz |
|---|---|
| `GET /v1/modelos` | lista com indicadores agregados, filtros e cursor |
| `GET /v1/modelos/{id}` | detalhe: modelo, FAQ, mídia, programas vinculados |
| `POST /v1/modelos` | cria modelo |
| `PATCH /v1/modelos/{id}` | edita campos do perfil |
| `POST /v1/modelos/{id}/pausar` | pausa a modelo e todas as conversas ativas |
| `POST /v1/modelos/{id}/ativar` | reativa (sem retomar IA nas conversas) |
| `POST /v1/modelos/{id}/conectar-whatsapp` | retorna QR code para pareamento |
| `POST /v1/modelos/{id}/desparear-whatsapp` | remove pareamento Evolution |
| CRUD de FAQ | `GET/POST /v1/modelos/{id}/faq` · `PATCH/DELETE /v1/modelos/{id}/faq/{faqId}` |
| Upload de mídia | `POST /v1/modelos/{id}/midia/upload-url` → PUT MinIO → `POST /v1/modelos/{id}/midia` |
| Atualizar/excluir mídia | `PATCH/DELETE /v1/modelos/{id}/midia/{midiaId}` |
| Foto de perfil | `POST /v1/modelos/{id}/foto-perfil/upload-url` → PUT → `PATCH/DELETE /v1/modelos/{id}/foto-perfil` |
| Vincular programa | `POST /v1/modelos/{id}/programas` |
| Atualizar/remover preço | `PATCH/DELETE /v1/modelos/{id}/programas/{progId}/duracoes/{durId}` |
| CRUD de programas (catálogo) | via `useProgramas` hook |
| CRUD de durações | via `useProgramas` hook |

**Realtime:** assina `modelos`, `modelo_faq`, `modelo_midia`, `programas`, `modelo_programas`. Qualquer mudança dispara refetch debounced de 250ms, preservando edições dirty.

---

## Efeitos colaterais que Fernando precisa entender

**Pausar modelo:**
- IA pausa em **todas** as conversas abertas com `ia_pausada=false`
- Atendimentos `Em_execucao` não são interrompidos (modelo já está com o cliente)
- O AlertDialog mostra a contagem real de conversas afetadas antes de confirmar
- Título: "Pausar {nome}?" — `emExecucao` está hardcoded em 0 no AlertDialog atual

**Reativar modelo:**
- Modelo volta para ativa, mas **a IA não retoma automaticamente** nas conversas que ficaram pausadas
- Cada conversa precisa de devolução manual na Central de Atendimentos
- O toast pós-reativação oferece action "Ver conversas" → `/atendimentos?ia_pausada=true&modelo_id={id}`

**Trocar número de WhatsApp:**
- Pareamento Evolution é resetado imediatamente
- IA não consegue enviar mensagens até o novo número ser pareado
- Dialog de QR abre automaticamente após confirmação

**Editar campos de Atendimento:**
- Muda o comportamento da IA no **próximo turno** de qualquer conversa ativa
- Não reescreve histórico nem reabre conversas pausadas

---

## Regra de visibilidade do botão "Adicionar modelo"

O botão some em 4 situações:
1. View ativa é "Programas"
2. Modelo selecionada não tem `evolution_instance_id` (→ "Conectar WhatsApp" é o primary contextual)
3. Modelo selecionada está `pausada` (→ "Reativar atendimentos" é o primary contextual)
4. Aba ativa é "Fotos e vídeos" (→ "Adicionar mídia" é o primary da aba)

---

## Estados e variações importantes

| Situação | Comportamento |
|---|---|
| Carregando lista | 4 skeletons `h-24` |
| Carregando detalhe | skeletons: h-24 + h-10 + h-56 × 3 |
| Lista vazia sem filtros | empty state com "Adicionar modelo" primary |
| Lista vazia com filtros | empty state com instruções para ajustar filtros |
| Nenhuma modelo selecionada | "Nenhuma modelo selecionada." + instrução |
| Evolution não pareada | "WhatsApp pendente" no item e no header; primary "Conectar WhatsApp" |
| Bloco dirty | botão "Salvar {bloco}" secondary aparece |
| Salvando bloco | `Loader2 animate-spin` no botão; campo desabilitado |
| QR aguardando pareamento | Dialog aberto; fecha automaticamente via `useEffect` quando `evolution_instance_id` aparece |
| Catálogo vazio (sem programas) | ProgramasModelo mostra aviso com link para view Programas |
| Trocar aba/view com dirty | AlertDialog "Descartar alterações não salvas?" |
| Refetch Realtime com dirty | blocos read-only atualizam, dirty preservado |
| Reativação com conversas pausadas | toast com action "Ver conversas →" |
| AlertDialog de excluir FAQ/mídia | título "Remover esta resposta?" / "Remover esta mídia?" + variant danger |

---

## Oportunidades de iteração identificadas

1. **View "Programas" sem pré-seleção de modelo** — ao acessar a view Programas, Fernando perde o contexto da modelo que estava vendo. Não há indicação de "você estava em Fulana, agora está no catálogo global".
2. **Catálogo sem preço padrão global** — cada modelo define seus preços individualmente. Se a agência tiver 5 modelos, Fernando precisa definir preços 5 vezes por programa. Um preço sugerido no catálogo reduziria esse trabalho.
3. **Aba Dúvidas sem indicação de quantas FAQs a IA tem disponível** — quando o escopo filtra para "Desta modelo", Fernando não vê as globais sendo contadas. O total real que a IA consulta seria útil.
4. **Pausar/reativar sem contexto de handoff recente** — o AlertDialog mostra quantas conversas serão afetadas, mas não quando o último handoff aconteceu. "IA pausada há 45 min" ajudaria Fernando a priorizar.
5. **Mídia sem indicador de uso pela IA** — o filtro padrão "Prontas no atendimento" mostra aprovadas, mas não se alguma foi usada recentemente. Um contador de uso daria visibilidade.
6. **Deep link `?modelo=&aba=` não sincroniza a view** — se Fernando compartilhar o link de uma modelo, quem abrir vai sempre cair na view "Modelos" (correto), mas não há deep link para a view "Programas".
7. **`emExecucao` hardcoded em 0** — o AlertDialog de pausar mostra "0 atendimento(s) em andamento continuam preservados" sem consultar o dado real. Isso pode confundir Fernando quando há atendimentos `Em_execucao` ativos.
