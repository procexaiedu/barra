# Agenda Operacional — Guia UX para Iteração

> Doc operacional para agentes de IA iterarem o módulo. Foca em jornada, UX, propósito e dados — não em implementação técnica.

---

## Propósito no sistema

A Agenda Operacional é onde Fernando **controla quando a modelo está disponível**. Ela não gerencia atendimentos — isso é responsabilidade da Central. A Agenda gerencia o tempo físico da modelo: quando ela pode receber clientes, quando está ocupada, quando um horário reservado foi cumprido ou cancelado.

O principal risco operacional que a Agenda evita é **conflito de horário**: dois atendimentos marcados no mesmo slot, ou Fernando devolver um cliente que a modelo já está atendendo.

Fernando abre essa tela quando quer: criar uma reserva manual, verificar o que tem no dia, ou checar se há espaço antes de confirmar algo com um cliente.

---

## Usuário e contexto de uso

**Único usuário:** Fernando. Usa a tela de forma planejada (revisar a semana, liberar horários) ou rápida (criar um bloqueio pontual antes de confirmar um atendimento).

**Pergunta que Fernando traz:** "Quando a modelo está livre?" ou "Preciso bloquear tal horário."

**Chegada típica:**
- Do Painel ou da Central via link de bloqueio → chega na tela normalmente (deep links `?data=` e `?bloqueio=` não são consumidos pela página atualmente)
- Diretamente pela sidebar → começa na visão Mês do dia atual

**Critério de sucesso:** Fernando cria, ajusta ou cancela um bloqueio em menos de 20 segundos.

---

## Jornada do usuário

```
Abrir /agenda
    → Skeleton do calendário e painel do dia
    → Mês atual carregado, hoje selecionado
    → Visualizar o calendário

Revisar o mês (visão padrão)
    → Dias com bloqueios mostram chips compactos (até 3 + contador)
    → Clicar em um dia → painel lateral atualiza para aquele dia
    → Ver slots livres e ocupados no painel

Criar bloqueio
    → Clicar em slot livre no painel → dialog abre com data/horário preenchido
    → OU duplo-clique em dia vazio no calendário → dialog abre com aquele dia preenchido
    → Preencher fim e observação (opcional) → Criar bloqueio
    → Toast "Bloqueio criado" + agenda atualiza

Ver/editar bloqueio existente
    → Clicar no card no painel ou no chip no calendário → dialog de edição abre
    → Editar horário ou observação → Salvar
    → OU Cancelar bloqueio → AlertDialog de confirmação → confirmar

Navegar períodos
    → ChevronLeft/Right navega o período ativo (dia / semana / mês)
    → "Hoje" volta para o período atual e seleciona hoje
    → Alternar Dia/Semana/Mês muda a granularidade mantendo o dia selecionado

Filtrar por modelo
    → FiltroModelo na toolbar → seleciona uma modelo → agenda recarrega
```

---

## Blocos visuais

### 1. Header
**Arquivo:** `components/agenda/HeaderAgenda.tsx`

Título "Agenda" em serif 40px. Abaixo, o nome da modelo no formato `"Modelo {nome}"` ou `"Nenhuma modelo ativa"`. À direita, três contadores calculados sobre todos os bloqueios do período visível:

| Contador | Lógica |
|---|---|
| Bloqueios ativos | `estado === "bloqueado"` ou `"em_atendimento"` |
| Em atendimento | `estado === "em_atendimento"` |
| Cancelados | `estado === "cancelado"` |

---

### 2. Toolbar
**Arquivo:** `components/agenda/ToolbarAgenda.tsx`

Barra em card com dois grupos:

**Esquerda:** segmented control com fundo `bg-muted` — `Dia · Semana · Mês`. Botão ativo recebe `bg-card text-text-brand`.

**Direita:** `FiltroModelo` (dropdown de seleção de modelo) + divisor + `ChevronLeft` · label do período · `ChevronRight` · botão ghost "Hoje".

> **Não há botão "Bloquear janela" na toolbar.** Criação de bloqueio acontece exclusivamente via clique num slot livre no PainelDia ou duplo-clique num dia vazio no calendário.

---

### 3. Calendário (visões Mês/Semana/Dia)
**Arquivo:** `components/agenda/CalendarioMes.tsx`

Um único componente que renderiza as três visões. Grid 7 colunas com header `Seg Ter Qua Qui Sex Sáb Dom`.

| Visão | Layout | Altura mínima das células |
|---|---|---|
| Mês | grid 7×6 (42 células) | `clamp(7rem, 12vw, 11rem)` |
| Semana | grid 7 colunas (7 células) | `clamp(7rem, 12vw, 11rem)` |
| Dia | grid 1 coluna (1 célula) | `420px` |

**Cada célula exibe:**
- número do dia (em `text-text-brand` quando selecionado)
- até 3 chips compactos dos bloqueios daquele dia
- contador `+N` no canto superior direito quando houver mais de 3

**Dia selecionado:** borda `border-ring`. Dias fora do mês corrente: opacidade 45%.

> **Hoje não tem destaque visual próprio.** O calendário não diferencia visualmente o dia de hoje do restante; apenas o dia selecionado recebe estilo especial. Como o estado inicial é hoje, na prática hoje começa selecionado.

**Interações:**
- Clique simples → seleciona o dia (atualiza o PainelDia)
- Duplo clique num dia **sem bloqueios** → abre dialog de criação com o próximo slot livre daquele dia
- Clicar num chip de bloqueio → abre dialog de edição

**Sem empty state dedicado:** quando não há bloqueios, as células simplesmente ficam sem chips — não há mensagem.

---

### 4. Painel do dia selecionado
**Arquivo:** `components/agenda/PainelDia.tsx`

Coluna com largura `minmax(360px, 420px)` à direita. Header mostra data formatada + contador `{N} bloqueio(s)`.

Exibe **24 slots de 1h** (`00:00` até `23:00`). Área dos slots tem `max-h-[calc(100vh-280px)] overflow-y-auto` — rola independentemente do restante da página.

**Slot livre:** botão `h-11` com horário em mono à esquerda e ícone `Plus` à direita. Clicar abre criação com início = aquele slot, fim = slot + 1h (ou `24:00` para o slot `23:00`).

**Slot ocupado:** renderiza o card `BloqueioAgenda` (modo não-compacto). Clicar abre edição.

**Empty state do dia** (quando `bloqueios.length === 0`): card `"Dia livre." · "Clique em um horário para bloqueá-lo."` aparece **acima** da lista de slots, que continua visível.

---

### 5. Card de bloqueio (`BloqueioAgenda`)
**Arquivo:** `components/agenda/BloqueioAgenda.tsx`

Renderiza em dois modos:

**Compacto** (nos chips do calendário):
```
[HH:MM-HH:MM]  [nome da modelo — só 1a palavra]
[Título: cliente, observação ou "Bloqueio manual"]
```
Sem badge, sem ícone de origem.

**Não-compacto** (no PainelDia):
```
[HH:MM-HH:MM]  [Badge estado]    [nome da modelo — só 1a palavra]
[Título: cliente, observação ou "Bloqueio manual"]
[Ícone origem] [label da origem em texto] [#N se vinculado]
```

**Estados visuais:**

| Estado | Badge label | Variant | Visual extra |
|---|---|---|---|
| `bloqueado` | "Bloqueado" | `paused` | — |
| `em_atendimento` | "Em atendimento" | `active` | — |
| `concluido` | "Concluído" | `closed` | — |
| `cancelado` | "Cancelado" | `paused` | opacidade 60% no card inteiro + `line-through` no título |

**Origens:** ícone + label em texto (Tooltip repete o label). `ia` → `Bot` "IA"; `painel_fernando` → `User` "Fernando"; `manual` → `Hand` "Manual".

Cancelado e concluído são clicáveis — abrem o dialog mas em modo read-only.

---

### 6. Dialog de bloqueio (criar / editar)
**Arquivo:** `components/agenda/DialogBloqueio.tsx`

**Não usa `AlertDialog`** — é um `div` com `role="dialog"` e `position: fixed` centralizado, com backdrop `bg-background/80` que fecha ao clicar. Fecha também com `Escape`.

**Campos:**

| Campo | Tipo | Observação |
|---|---|---|
| Modelo | `FiltroModelo` com `hideTodas` | Só aparece na criação quando não há `modeloId` na toolbar |
| Data | `<input type="date">` | Obrigatório |
| Início | `<select>` 00:00–23:00 | Obrigatório |
| Fim | `<select>` 00:00–24:00 | Deve ser > início; `24:00` representa meia-noite do dia seguinte |
| Observação | `<textarea>` | Opcional; limite visual de 160 caracteres (`{N}/160`); `maxLength` no elemento é 180 |

**Validações inline:**
- Fim ≤ Início → "Fim precisa ser maior que início." em `text-state-lost`
- Conflito com bloqueio ativo no mesmo período → "Este horário se sobrepõe a outro bloqueio ativo." em `text-state-handoff`
- Ambas ainda permitem tentar salvar — o backend é a autoridade final (409 se houver conflito real)

**Botões por situação:**

| Situação | Esquerda | Direita |
|---|---|---|
| Criando | — | Cancelar · **Criar bloqueio** |
| Editando (avulso) | — | Cancelar · Cancelar bloqueio · **Salvar** |
| Editando (vinculado a atendimento) | "Ver atendimento" (ghost, navega `/atendimentos?selecionado={id}`) | Cancelar · Cancelar bloqueio · **Salvar** |
| Read-only (concluído ou cancelado) | "Ver atendimento" se vinculado | Cancelar |

"Cancelar bloqueio" usa `variant="danger"` e abre um `AlertDialog` de confirmação:
- Estado `bloqueado`: "Cancelar bloqueio?" com aviso sobre atendimento vinculado → botões "Cancelar" / "Cancelar bloqueio"
- Estado `em_atendimento`: "Cancelar bloqueio em atendimento?" com aviso mais forte → botões "Voltar" / "Confirmar cancelamento"

---

## Dados que alimentam a tela

Um endpoint de leitura e três de escrita:

| Chamada | O que faz |
|---|---|
| `GET /v1/agenda/bloqueios?inicio=...&fim=...` | carrega todos os bloqueios da janela visível |
| `POST /v1/agenda/bloqueios` | cria bloqueio manual |
| `PATCH /v1/agenda/bloqueios/{id}` | edita horário e/ou observação |
| `POST /v1/agenda/bloqueios/{id}/cancelar` | cancela (com `{ confirmar: true }` para `em_atendimento`) |

Após criar, atualizar ou cancelar, o hook refaz o carregamento do período visível diretamente (não espera Realtime).

**Realtime:** assina `bloqueios` e `eventos`. Qualquer mudança dispara refetch debounced de 250ms da janela visível — sem patch local.

---

## Estados e variações importantes

| Situação | Comportamento |
|---|---|
| Carregando | skeleton: header (título + 3 cards) + toolbar + calendário 35 células + painel 8 slots |
| Erro de carga | `BannerErro` com botão "Tentar novamente"; header ainda renderiza com contadores zerados |
| Mês sem bloqueios | calendário renderiza normalmente — células ficam sem chips |
| Dia sem bloqueios | empty state "Dia livre." acima dos 24 slots |
| Dialog aberto com intervalo inválido | aviso inline; botão Salvar/Criar desabilitado |
| Dialog aberto com conflito | aviso inline em laranja; botão Salvar/Criar permanece ativo |
| Submissão em voo | botão de ação com `Loader2 animate-spin`, todos os botões desabilitados |
| Conflito 409 do backend | toast de erro, dialog permanece aberto |
| Sucesso em criar/editar/cancelar | toast + dialog fecha + agenda recarrega |
| Bloqueio cancelado | visível no calendário e painel — card com opacidade 60% e riscado |
| Bloqueio concluído | visível, read-only, botão "Cancelar bloqueio" ausente |
| Refetch por Realtime | sem skeleton — calendário e painel atualizam silenciosamente |

---

## Conexão com outras telas

A Agenda não vive isolada — bloqueios são criados automaticamente pela IA e pelos fluxos de atendimento:

- **IA cria bloqueio** quando um atendimento é confirmado (origem `ia`)
- **Converter atendimento** muda o bloqueio vinculado para `concluido`
- **Perda de atendimento** muda o bloqueio para `cancelado` (se não estiver `em_atendimento` ou `concluido`)
- **Painel Geral** linka para `/agenda?data={YYYY-MM-DD}&bloqueio={id}` na linha de agenda do dia — esses parâmetros **não são consumidos** pela página de agenda atualmente

Quando Fernando cancela um bloqueio vinculado a atendimento, o aviso no dialog instrui a ajustar o atendimento separadamente na Central — a Agenda não altera estado de atendimento diretamente.

---

## Oportunidades de iteração identificadas

1. **Hoje sem destaque visual** — o calendário não diferencia o dia atual dos demais; Fernando perde o senso de onde está na semana ao navegar para períodos futuros.
2. **Deep links não consumidos** — o Painel linka para `/agenda?data=...&bloqueio=...` mas a página ignora esses parâmetros; Fernando chega no mês atual sem nenhum dia/bloqueio pré-selecionado.
3. **Chips no calendário sem legenda de cores** — os chips usam cores de estado mas não há legenda; para entender o que cada cor significa é preciso clicar.
4. **Slot de 1h pode ser grosso** — passo de 30min no futuro pode ajudar na precisão para atendimentos mais curtos ou com deslocamento.
5. **Painel sempre começa em 00:00** — Fernando provavelmente opera das 10:00 às 23:00; o painel poderia ter scroll automático para o primeiro bloqueio do dia ou para a hora atual.
6. **Observação não aparece no chip compacto** — Fernando não consegue ler o contexto do bloqueio sem abrir o dialog; o chip mostra só horário + título.
7. **Visão Dia usa o mesmo `CalendarioMes`** — na visão dia, o componente renderiza uma única célula em grade de 1 coluna; o layout poderia ser mais útil (linha do tempo vertical, por exemplo).
