# CRM — Guia UX para Iteração

> Doc operacional para agentes de IA iterarem o módulo. Foca em jornada, UX, propósito e dados — não em implementação técnica.

---

## Propósito no sistema

O CRM é a tela de **contexto histórico**. Enquanto a Central de Atendimentos mostra o que está acontecendo agora, o CRM mostra quem é o cliente, quantas vezes voltou, por que perdeu da última vez e qual o valor acumulado gerado.

A unidade da tela é a **conversa** — o par (cliente, modelo), não o cliente isolado. Isso reflete uma decisão do domínio: histórico, recorrência e estatísticas são por par. Um mesmo cliente que conversa com duas modelos diferentes aparece como duas conversas distintas, cada uma com seu histórico independente.

Fernando abre o CRM quando quer entender o contexto de um cliente antes de agir, ou quando quer filtrar por comportamento (recorrentes, perdas por preço, etc).

---

## Usuário e contexto de uso

**Único usuário:** Fernando. Usa o CRM de forma investigativa — chega com uma pergunta sobre um cliente específico, ou para filtrar por comportamento.

**Pergunta que Fernando traz:** "Quem é esse cliente?" ou "Quantos recorrentes tive esse mês?" ou "Quanto esse cliente já gerou?"

**Chegada típica:**
- Diretamente pela sidebar durante uma análise
- Via link "Abrir conversa" na tela de Pix (navega para `/crm`)

**Critério de sucesso:** Fernando encontra o histórico de um cliente e lê o contexto relevante em menos de 30 segundos.

---

## Jornada do usuário

```
Abrir /crm
    → Skeleton da lista + detalhe
    → Lista carrega com todas as conversas, mais recente selecionada

Encontrar o cliente
    → Busca por nome ou telefone (debounce 300ms no hook)
    → OU filtrar por recorrência / motivo de perda / período / modelo
    → Lista atualiza, primeira conversa selecionada automaticamente
    → Clicar em conversa diferente para selecionar

Ler o contexto
    → Header: quem é o cliente e com qual modelo
    → Dados do cliente: telefone, nome, primeiro contato, cliente desde + estatísticas
    → Dados da conversa: recorrência, último motivo de perda, última mensagem, conversa desde
    → Atendimento aberto: se tiver algo em andamento, card com borda esquerda laranja
    → Histórico: lista de fechamentos e perdas anteriores com valores
```

---

## Blocos visuais

### 1. Header da página
**Localização:** inline em `app/(interface)/crm/page.tsx`

Título "CRM" em serif 40px. Abaixo, subtitle fixo: `"Histórico, recorrência e observações de cada cliente, por modelo."` em 13px muted.

---

### 2. Toolbar de filtros
**Localização:** função local `Toolbar` em `app/(interface)/crm/page.tsx`

Grid `grid-cols-[minmax(260px,1fr)_140px_180px_140px_180px]` com 5 controles:

| Controle | Tipo | Opções visíveis |
|---|---|---|
| Busca | Input com ícone Search | placeholder "Buscar nome ou telefone" |
| Recorrência | `<select>` nativo | Todas · Novas · Recorrentes |
| Motivo da última perda | `<select>` nativo | Todos · Preço · Sumiu · Risco · Indisponibilidade · Fora de área · Outro |
| Período do último atendimento | `<select>` nativo | Todos · 7 dias · 30 dias · 90 dias |
| Modelo | `<select>` nativo | Todas · [lista de modelos do `/v1/modelos`] |

**Loading:** quando `listaStatus === "loading"`, toolbar vira 5 skeletons `h-9`.

**UX:** busca dispara `onBuscaChange` a cada keystroke; o debounce de 300ms fica no hook.

---

### 3. Lista de conversas
**Arquivos:** `components/crm/ListaConversas.tsx` + `ItemConversa.tsx`

Coluna esquerda de **360px** (`grid-cols-[360px_minmax(0,1fr)]`). Container `rounded-lg border border-border bg-card` com scroll interno `overflow-y-auto scroll-thin`.

**Anatomia do item:**
```
[Nome do cliente ou telefone formatado]          [tempo relativo]
[Badge Recorrente?] [modelo · #N · perda: motivo]    [estado]
```

- Linha 1: nome (flex-1 truncate semibold) + tempo relativo à direita (ml-auto)
- Linha 2: `Badge variant="paused" "Recorrente"` (só se `recorrente = true`) + linha de texto muted com `{modelo.nome} · #{numero_curto} · perda: {motivo}` (só campos não-nulos) + estado do último atendimento à direita (ml-auto, só se `ultimo_atendimento` não é null)

**Sinais visuais da borda esquerda (3px):**

| Situação | Token |
|---|---|
| Item selecionado | `border-l-state-active` |
| `tem_atendimento_aberto` + não selecionado | `border-l-state-handoff` |
| Default | `border-l-transparent` |

Item selecionado também recebe `bg-ink-200`.

**Paginação:** quando `nextCursor` existe, botão "Carregar mais" aparece ao final.

**Loading:** 12 skeletons `h-[60px]`.

**Empty states:**
- Sem filtros: "Nenhuma conversa registrada ainda." + "Conversas aparecem aqui assim que clientes chamarem no WhatsApp da modelo."
- Com filtros: "Nenhuma conversa encontrada para estes filtros." + "Ajuste os filtros para ampliar a busca."

---

### 4. Header da conversa selecionada
**Arquivo:** `components/crm/DetalheConversa.tsx`

Header `flex flex-wrap items-baseline gap-x-3 gap-y-1` no topo do painel direito:

```
[Nome ou telefone]  [Badge Recorrente?]                 [tempo da última mensagem]
Conversa com [nome da modelo]
```

- h1: nome do cliente ou telefone formatado (`text-lg font-semibold`)
- `Badge variant="paused" "Recorrente"` quando `conversa.recorrente = true`
- Span ml-auto: `"Última mensagem {tempo relativo}"` ou `"Sem mensagens ainda"`
- Linha abaixo (w-full): `"Conversa com "` + nome da modelo (`font-medium text-text-primary`)

**Empty state** quando nenhuma conversa selecionada: card `"Nenhuma conversa selecionada."` + `"Selecione um item da lista para ver o histórico do cliente com a modelo."`

---

### 5. Dados do cliente
**Arquivo:** `components/crm/DadosCliente.tsx`

Card read-only. Recebe `cliente` e `historico` como props. Toda informação é somente leitura — sem edição inline.

**Campos principais:**

| Campo | Comportamento |
|---|---|
| Telefone | Mono muted. Nunca editável. |
| Nome | Exibe nome ou `"Não informado"` quando null. Read-only. |
| Primeiro contato | Nome da modelo pelo qual o cliente chegou primeiro. `"Não informado"` quando null. |
| Cliente desde | Data formatada de `created_at`. |

**Seção "Estatísticas do Cliente"** (abaixo de `border-t`):

| Stat | Lógica |
|---|---|
| Atendimentos Fechados | `historico.filter(h => h.estado === "Fechado").length` |
| Atendimentos Perdidos | `historico.filter(h => h.estado === "Perdido").length` |
| Receita Total | Soma de `valor_final` dos fechados — em `text-state-won`. Só renderiza quando `fechados.length > 0`. |
| Ticket Médio | `receita / fechados.length`. Só renderiza quando `fechados.length > 0`. |

---

### 6. Dados da conversa
**Arquivo:** `components/crm/DadosConversa.tsx`

Card read-only com informações do par (cliente, modelo):

| Campo | O que mostra |
|---|---|
| Recorrência | "Recorrente" (com ícone `RefreshCw`) ou "Nova" |
| Último motivo de perda | Label do motivo ou `"Nenhum"` quando null |
| Última mensagem | Data+hora formatada + chip mono em `bg-ink-300` com direção (cliente / IA / modelo); `"Sem mensagens ainda"` quando null |
| Conversa desde | Data de `created_at` da conversa |

---

### 7. Atendimento aberto
**Arquivo:** `components/crm/AtendimentoAberto.tsx`

**Sempre renderiza** o `<section>` com título "Atendimento aberto". Quando `atendimento === null`, exibe apenas `"Sem atendimento aberto nesta conversa."` (texto simples sem CTA).

Quando há atendimento ativo, o card recebe borda esquerda `border-l-state-handoff`:

```
[Badge estado]  [#N em mono]
[tipo · urgência · valor acordado]     ← só quando pelo menos um não for null
Próxima ação esperada: [texto]         ← só quando não-null
[Abrir na Central]
```

O botão "Abrir na Central" usa `variant="secondary"`, `size="sm"` e navega para `/atendimentos` (sem deep link para o atendimento específico).

---

### 8. Histórico de atendimentos
**Arquivo:** `components/crm/HistoricoAtendimentosConversa.tsx`

Card com título "Histórico" (`text-base font-semibold`). Lista os atendimentos **terminais** (`Fechado` ou `Perdido`) da conversa em ordem retornada pelo backend.

**Cada linha** (`h-14 flex items-center`):
```
[#N mono]  [Badge estado]  [data formatada]  ·  [detalhe final]
```

`detalhe final`:
- Fechado + `valor_final` não-null → valor em BRL
- Perdido + `motivo_perda` → label do motivo; se `outro` e há `motivo_perda_obs`, trunca em 40 chars
- Demais casos → sem detalhe

Linhas não são clicáveis.

**Empty state:** `"Nenhum atendimento registrado ainda nesta conversa."`

---

## Dados que alimentam a tela

Dois endpoints de leitura (sem escrita):

| Chamada | O que faz |
|---|---|
| `GET /v1/crm/conversas` | lista paginada por cursor com filtros |
| `GET /v1/crm/conversas/{id}` | conversa, cliente, modelo, atendimento_aberto, historico_atendimentos |

Parâmetros de lista: `q`, `recorrente`, `motivo_perda`, `periodo`, `modelo_id`, `cursor`, `limit=50`.

Não há endpoints de escrita — o CRM é somente leitura no estado atual.

**Realtime:** assina `conversas`, `clientes` e `atendimentos`. Qualquer mudança dispara refetch debounced de 250ms preservando a conversa selecionada.

---

## Estados e variações importantes

| Situação | Comportamento |
|---|---|
| Carregando lista | 12 skeletons `h-[60px]` |
| Carregando detalhe | 6 skeletons (h-16 + h-44 × 4 + h-24) |
| Lista vazia sem filtros | empty state "Nenhuma conversa registrada ainda." + contexto |
| Lista vazia com filtros | empty state "Nenhuma conversa encontrada para estes filtros." |
| Nenhuma conversa selecionada | card "Nenhuma conversa selecionada." + instrução |
| Sem atendimento aberto | seção sempre visível com texto "Sem atendimento aberto nesta conversa." |
| Sem histórico | seção sempre visível com "Nenhum atendimento registrado ainda nesta conversa." |
| Erro de lista | `BannerErro` com botão "Tentar novamente" dentro do card |
| Erro de detalhe | `BannerErro` com botão "Tentar novamente" no painel direito |
| Refetch Realtime | lista e detalhe atualizam silenciosamente, sem skeleton |

---

## Oportunidades de iteração identificadas

1. **CRM é leitura pura, mas `observacoes_internas` existe no tipo** — o campo `ConversaResumo.observacoes_internas` existe no backend mas não há UI para editar ou exibir essa observação. Implementar o bloco de observações seria de alto valor para Fernando anotar contexto.
2. **Badge Recorrente sem contador de frequência** — o badge diz que o cliente voltou, mas o número de fechamentos fica enterrado nas Estatísticas do Cliente no detalhe. Um "Nª vez" visível no item da lista daria mais contexto ao navegar.
3. **"Abrir na Central" sem ancoragem** — navega para `/atendimentos` e o primeiro item da lista é selecionado. Se houver múltiplos atendimentos abertos da mesma conversa em algum cenário futuro, o comportamento ficaria ambíguo. Um deep link `?id=` seria mais preciso.
4. **Histórico sem valor acumulado visível** — Fernando não vê o total histórico sem olhar para as Estatísticas. Um subtotal ao fim da seção de histórico evitaria o scroll.
5. **Sem indicação de que o nome do cliente é global** — mudar o nome via API afetaria todas as conversas do mesmo número; como a edição não está implementada, isso não é um problema agora, mas vale considerar ao implementar.
6. **Filtros sem indicador de "filtros ativos"** — quando Fernando usa filtros, não há nenhum sinal visual na toolbar de que a lista está filtrada além do resultado vazio ou reduzido.
