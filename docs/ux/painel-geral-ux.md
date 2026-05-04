# Painel Geral — Guia UX para Iteração

> Doc operacional para agentes de IA iterarem o módulo. Foca em jornada, UX, propósito e dados — não em implementação técnica.

---

## Propósito no sistema

O Painel Geral é a **tela de trabalho diário de Fernando**. Enquanto as demais telas (Atendimentos, Pix, Agenda, Modelos) são contextuais — Fernando as abre com intenção específica —, o Painel é a tela que Fernando **abre ao acordar e mantém aberta** durante o dia.

Papel operacional: surfacar o que precisa de decisão humana agora. A IA cuida dos atendimentos automaticamente; o Painel expõe os pontos em que ela pausou e esperada Fernando agir.

---

## Usuário e contexto de uso

**Único usuário:** Fernando, dono/operador da agência. Não é usuário técnico — é operacional. Usa o painel entre outras atividades do dia, geralmente no desktop.

**Pergunta que Fernando traz ao abrir a tela:** "O que está esperando por mim agora?"

**Sessão típica:** Fernando abre o painel, resolve os cards pendentes (30–90 segundos cada), fecha a aba ou deixa em segundo plano. Quando uma nova pendência chega via Realtime, ele volta.

---

## Jornada do usuário

```
Abrir painel
    → Skeletons enquanto carrega (< 1s na prática)
    → Ver bloco "Aguardando você"
        → 0 cards: confirma que não há nada urgente, segue para métricas/agenda
        → N cards: decide por cada card
            → Pix em revisão      → clicar → vai para /atendimentos?id=...
            → Handoff da IA       → clicar → vai para /atendimentos?id=...
            → Modelo atendendo    → clicar → vai para /atendimentos?id=... OU clica "Devolver para IA" → confirma no dialog → card some
    → Ver métricas (leitura passiva — volume do dia)
    → Ver agenda (verificar bloqueios do dia)
    → Usar atalhos se necessário (casos rápidos)
```

**Critério de sucesso do Painel:** Fernando identifica e executa sua próxima ação em menos de 10 segundos.

---

## Blocos visuais

### 1. Header
**Arquivo:** `components/painel/HeaderPainel.tsx`

Exibe título "Painel" em serif grande (40px). À direita, dois campos lado a lado:
- **MODELO** — nome da modelo ativa ou seletor dropdown (quando múltiplas)
- **AGORA** — data + hora em fonte mono, atualizando a cada 60s

**Estado variável:**
- 0 modelos ativas → "Nenhuma modelo ativa" em muted
- 1 modelo → nome estático
- 2+ modelos → seletor com opção "Todas as modelos" + por modelo individual

O seletor é um dropdown customizado (não usa `<select>`) com fechamento ao clicar fora. Não usa shadcn Select.

---

### 2. Aguardando você (cards de destaque)
**Arquivo:** `components/painel/CardDestaque.tsx`

Bloco mais importante da tela. Cada card representa um atendimento em que a IA pausou e precisa de Fernando.

**Três tipos de card, com hierarquia fixa de exibição:**

| Tipo | Badge variant | Label | Ação disponível no card |
|---|---|---|---|
| Pix em revisão | `revisao` (amarelo) | "Pix em revisão" | Nenhuma inline — clicar navega para `/atendimentos?id=...` |
| Handoff da IA | `handoff` (azul) | "Aguardando você" | Nenhuma inline — clicar navega para `/atendimentos?id=...` |
| Modelo atendendo | `paused` (cinza) | "Modelo atendendo" | Botão "Devolver para IA" + AlertDialog |

> **Atenção:** todos os tipos de card navegam para `/atendimentos?id={atendimento_id}` ao ser clicados — não há navegação especial para `/pix`. O atalho "Ver N Pix em revisão" na seção de atalhos é que vai para `/pix`.

**Anatomia do card:**
```
[Badge tipo] [Ícone ClockAlert — apenas modelo_em_atendimento] [#N] [Nome do cliente]
MOTIVO  [texto do motivo da pausa]
PRÓXIMA AÇÃO  [o que fazer]       ← omitido se proxima_acao_esperada for null
[Botão "Devolver para IA" — apenas modelo_em_atendimento]
─────────────────────────────────────────────────────────
Pausada há X min · Com [Fernando | modelo | IA]   [nome da modelo se filtro "Todas"]
```

O ícone `ClockAlert` e o botão "Devolver para IA" aparecem para **todos** os cards de tipo `modelo_em_atendimento`, independente do campo `expirado`. O campo `expirado` existe no tipo mas não é usado na renderização.

**UX crítica:** o card inteiro é clicável (navega para o atendimento), exceto o botão "Devolver para IA" que usa `e.stopPropagation()`. Isso evita acionar navegação ao tentar devolver.

**Empty state:**
```
[CheckCircle2 verde] Nada precisa de você agora.
                     Atendimentos que precisarem da sua decisão aparecem aqui.
```

**Grid:** 2 colunas em `xl:` (>= 1280px), 1 coluna abaixo disso.

---

### 3. Métricas do dia
**Arquivo:** `components/painel/TileMetrica.tsx`

Seção com header "**Hoje**" e data atual (`{diaSemana} · {dataFormatada}`) alinhada à direita. Leitura passiva — Fernando não age a partir daqui.

Quatro tiles em grid 4 colunas:

- **ATENDIMENTOS ABERTOS** — todos os abertos, sem corte por data (cor padrão)
- **FECHAMENTOS HOJE** — em `text-success-500` (verde)
- **PERDAS HOJE** — em `text-danger-500` (vermelho)
- **VALOR BRUTO HOJE** — formatado em BRL pt-BR (cor padrão)

Tiles com valor zero renderizam normalmente — zero é informação válida ("não houve perdas hoje").

Cada tile usa `<dl>/<dt>/<dd>` semântico. O valor é exibido em fonte sans 40px com tracking negativo (mesma escala do título).

---

### 4. Agenda de hoje
**Arquivo:** `components/painel/LinhaAgenda.tsx`

Lista os bloqueios de agenda do dia corrente. Fernando usa para ter consciência de quando a modelo está ocupada/em atendimento.

**Anatomia de linha:**
```
[HH:MM–HH:MM]  [Badge estado]  [Nome cliente ou observação]  [nome modelo?]  [Ícone origem]  [>]
```

**Estados de badge e seus labels:**

| Estado | Variant | Label exibido |
|---|---|---|
| `bloqueado` | `paused` | **"Agendado"** |
| `em_atendimento` | `active` | "Em atendimento" |
| `concluido` | `closed` | "Concluído" |
| `cancelado` | `paused` | "Cancelado" |

> **Atenção:** o estado `bloqueado` exibe o label **"Agendado"** (não "Bloqueado").

**Exibição do nome:** se o bloqueio tem `atendimento_id`, exibe `cliente_nome ?? "Cliente"`; caso contrário exibe `observacao ?? "Bloqueio manual"`.

**Estado cancelado:** linha inteira fica com `line-through opacity-60`.

**Origens com ícone + tooltip:**

| Origem | Ícone | Tooltip |
|---|---|---|
| `ia` | `Bot` | "IA" |
| `painel_fernando` | `User` | "Fernando" |
| `manual` | `Hand` | "Manual" |

Click na linha navega para `/agenda?data={YYYY-MM-DD}&bloqueio={id}`.

**Empty state:** `CalendarOff` + "Nenhum horário reservado hoje." + botão ghost "Bloquear horário" que leva para `/agenda?action=bloquear`.

---

### 5. Atalhos contextuais
**Arquivo:** `components/painel/AtalhoContextual.tsx`

Botões de acesso rápido na base da tela. Separados do conteúdo acima por um divisor. Sem título de seção.

| Atalho | Aparece quando | Variant | Destino |
|---|---|---|---|
| Conectar WhatsApp da modelo | `evolution_instance_id` é null | `default` (primary) | `/modelos?modelo={id}&aba=perfil` |
| Ver N Pix em revisão | `pix_em_revisao_pendentes > 0` | `secondary` | `/pix?status=em_revisao` |
| Ver N atendimentos abertos | `abertos > 0` | `secondary` | `/atendimentos` |
| Bloquear horário | sempre | `secondary` | `/agenda?action=bloquear` |

"Conectar WhatsApp" é o único `variant="default"` (primary) e sempre vem primeiro quando visível. Todos os atalhos são renderizados como `<Link>` do Next.js via prop `render` do `Button`.

---

## Dados que alimentam a tela

Tudo vem de um único endpoint: `GET /api/v1/painel/resumo` (com `?modelo_id=` opcional).

**O que cada bloco consome:**

| Bloco | Campo da resposta |
|---|---|
| Header | `modelos_ativas[]` |
| Cards | `cards_destaque[]` filtrado por `modeloId` se selecionado |
| Métricas | `metricas_dia` |
| Agenda | `agenda_dia[]` filtrado por `modeloId` se selecionado |
| Atalhos | `metricas_dia` + primeiro item de `modelos_ativas` (quando `modeloId` é null) ou o item correspondente |

A tela assina Realtime em 4 tabelas (`atendimentos`, `comprovantes_pix`, `bloqueios`, `eventos`). Qualquer mudança dispara um refetch debounced de 250ms — sem patch local. Quando o filtro de modelo muda, o refetch é imediato (sem debounce).

---

## Comportamento do filtro por modelo

Quando há múltiplas modelos, Fernando pode filtrar o Painel por uma modelo específica usando o seletor no header. O estado é local (`modeloId: string | null`):

- `null` → "Todas as modelos" — exibe dados agregados
- `string` → filtra cards e agenda para aquela modelo

Este comportamento **diverge da spec original** (que previa apenas aviso de múltiplas). Foi uma evolução deliberada para quando a operação escala além de 1 modelo.

---

## Estados e variações importantes

| Situação | Comportamento |
|---|---|
| Carregando | Skeletons em todos os blocos (header, 2 cards, 4 tiles métricas, agenda) — atalhos não têm skeleton |
| Erro de rede | BannerErro com botão "Tentar novamente" (só na primeira carga; erros subsequentes são silenciosos) |
| 0 cards | Empty state com CheckCircle2 verde + duas linhas de texto |
| 0 itens na agenda | Empty state com CalendarOff + botão ghost bloquear |
| Devolvendo para IA | Botão e dialog desabilitados + texto "Devolvendo…" |
| Erro ao devolver | Dialog permanece aberto, toast com detalhe do erro |
| Sucesso ao devolver | Dialog fecha, toast de sucesso, card some via Realtime (refetch debounced) |

---

## Oportunidades de iteração identificadas

1. **Hierarquia visual do bloco de cards** — é o bloco mais crítico mas tem o mesmo peso visual que métricas e agenda. Pode merecer mais destaque quando há pendências urgentes.
2. **Cards sem nome de cliente** — quando `cliente_nome` é null, exibe telefone formatado. Pode ser confuso em cards de handoff onde o contexto importa mais.
3. **Ausência de contagem no header dos cards quando filtrado** — ao filtrar por modelo, o contador "N aguardando ação" some junto com os cards da outra modelo, sem feedback.
4. **Atalhos sempre na base** — quando há cards urgentes, os atalhos ficam enterrados. Podem ser escondidos ou colapsados quando há pendências críticas.
5. **Métricas sem contexto histórico** — tiles mostram só o dia atual sem comparativo, dificultando entender se o dia está bom ou ruim.
6. **Campo `expirado` não utilizado** — `CardDestaque` tem o campo `expirado: boolean` no tipo mas a UI não diferencia visual ou funcionalmente cards expirados dos não-expirados. Oportunidade de mostrar urgência adicional.
