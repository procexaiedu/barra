---
version: alpha
name: Barra Vips Painel
description: >-
  Identidade visual do painel operacional Barra Vips. Herda a assinatura
  preto + dourado do canal orgânico (BarraVips.com) e a adapta para uma
  ferramenta de trabalho usada por horas: densidade alta, contraste forte,
  ornamento contido. NÃO replica o tom adulto, as fotos sensíveis nem a
  serifa decorativa do site público — esses elementos pertencem ao canal
  de aquisição e não ao produto interno.

colors:
  ink-0:        "#000000"
  ink-50:       "#0A0A0A"
  ink-100:      "#141414"
  ink-200:      "#1F1F1F"
  ink-300:      "#2A2A2A"
  ink-400:      "#3D3D3D"
  ink-500:      "#5C5C5C"
  ink-600:      "#8B8B8B"
  ink-700:      "#B4B4B4"
  ink-800:      "#DEDEDE"
  ink-900:      "#F5F5F5"

  gold-300:     "#8C7848"
  gold-500:     "#C4A961"
  gold-700:     "#E6CB7A"

  warn-500:     "#F4B81C"
  danger-500:   "#D62828"
  success-500:  "#1FB07A"
  info-500:     "#4F8FE1"

  surface:           "{colors.ink-50}"
  surface-raised:    "{colors.ink-100}"
  surface-hover:     "{colors.ink-200}"
  surface-pressed:   "{colors.ink-300}"
  border-subtle:     "{colors.ink-300}"
  border-strong:     "{colors.ink-400}"
  border-brand:      "{colors.gold-500}"

  text-primary:      "{colors.ink-900}"
  text-secondary:    "{colors.ink-700}"
  text-muted:        "{colors.ink-600}"
  text-disabled:     "{colors.ink-500}"
  text-inverse:      "{colors.ink-0}"
  text-brand:        "{colors.gold-500}"
  text-link:         "{colors.gold-700}"

  state-handoff:     "{colors.warn-500}"
  state-lost:        "{colors.danger-500}"
  state-closed:      "{colors.success-500}"
  state-active:      "{colors.gold-500}"
  state-paused:      "{colors.ink-600}"
  state-info:        "{colors.info-500}"

  on-surface:        "{colors.ink-900}"
  on-surface-muted:  "{colors.ink-700}"
  on-brand:          "{colors.ink-0}"
  on-warn:           "{colors.ink-0}"
  on-danger:         "{colors.ink-900}"
  on-success:        "{colors.ink-0}"
  on-info:           "{colors.ink-0}"

  focus-ring:        "{colors.gold-700}"

  chart-1:  "{colors.gold-500}"
  chart-2:  "{colors.info-500}"
  chart-3:  "{colors.success-500}"
  chart-4:  "#B66CD9"
  chart-5:  "#E07A5F"
  chart-6:  "#6FCFC9"
  chart-7:  "#D4A574"

  seq-1:    "#1A1606"
  seq-2:    "#4A3F25"
  seq-3:    "#8C7848"
  seq-4:    "#C4A961"
  seq-5:    "#E6CB7A"

  div-low:    "{colors.danger-500}"
  div-low-2:  "#E0857A"
  div-mid:    "{colors.ink-500}"
  div-high-2: "#7DCFA8"
  div-high:   "{colors.success-500}"

typography:
  display-xl:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: 56px
    fontWeight: 500
    lineHeight: 60px
    letterSpacing: -0.02em
  display-lg:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: 40px
    fontWeight: 500
    lineHeight: 48px
    letterSpacing: -0.02em
  heading-lg:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 22px
    fontWeight: 600
    lineHeight: 30px
    letterSpacing: -0.01em
  heading-md:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 600
    lineHeight: 24px
    letterSpacing: -0.005em
  heading-sm:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 12px
    fontWeight: 600
    lineHeight: 16px
    letterSpacing: 0.08em
  body-md:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 22px
    letterSpacing: 0em
  body-sm:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 20px
    letterSpacing: 0em
  caption:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 16px
    letterSpacing: 0.01em
  mono-sm:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, monospace"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 16px
    letterSpacing: 0em

spacing:
  "0":  0px
  "1":  4px
  "2":  8px
  "3":  12px
  "4":  16px
  "5":  24px
  "6":  32px
  "7":  48px
  "8":  64px

rounded:
  none: 0px
  sm:   4px
  md:   8px
  lg:   12px
  xl:   16px
  pill: 9999px

components:
  button-primary:
    backgroundColor: "{colors.gold-500}"
    textColor: "{colors.ink-0}"
    typography: "{typography.heading-md}"
    rounded: "{rounded.md}"
    padding: "{spacing.3} {spacing.5}"
  button-primary-hover:
    backgroundColor: "{colors.gold-700}"
    textColor: "{colors.ink-0}"
  button-primary-disabled:
    backgroundColor: "{colors.ink-300}"
    textColor: "{colors.ink-500}"

  button-secondary:
    backgroundColor: "{colors.ink-200}"
    textColor: "{colors.ink-900}"
    typography: "{typography.heading-md}"
    rounded: "{rounded.md}"
    padding: "{spacing.3} {spacing.5}"
  button-secondary-hover:
    backgroundColor: "{colors.ink-300}"
    textColor: "{colors.ink-900}"

  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-700}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "{spacing.2} {spacing.4}"
  button-ghost-hover:
    backgroundColor: "{colors.ink-200}"
    textColor: "{colors.ink-900}"

  button-danger:
    backgroundColor: "{colors.ink-200}"
    textColor: "{colors.danger-500}"
    typography: "{typography.heading-md}"
    rounded: "{rounded.md}"
    padding: "{spacing.3} {spacing.5}"

  input:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-900}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "{spacing.3} {spacing.4}"
    height: 40px
  input-focus:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-900}"

  card:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.lg}"
    padding: "{spacing.5}"

  card-handoff:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.lg}"
    padding: "{spacing.5}"

  badge-active:
    backgroundColor: "{colors.ink-300}"
    textColor: "{colors.gold-500}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "{spacing.1} {spacing.3}"
  badge-paused:
    backgroundColor: "{colors.ink-300}"
    textColor: "{colors.warn-500}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "{spacing.1} {spacing.3}"
  badge-closed:
    backgroundColor: "{colors.ink-300}"
    textColor: "{colors.success-500}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "{spacing.1} {spacing.3}"
  badge-lost:
    backgroundColor: "{colors.ink-300}"
    textColor: "{colors.danger-500}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "{spacing.1} {spacing.3}"

  table-row:
    backgroundColor: "transparent"
    textColor: "{colors.ink-800}"
    typography: "{typography.body-sm}"
    padding: "{spacing.3} {spacing.4}"
  table-row-hover:
    backgroundColor: "{colors.ink-200}"
    textColor: "{colors.ink-900}"

  sidebar:
    backgroundColor: "{colors.ink-50}"
    textColor: "{colors.ink-700}"
    typography: "{typography.body-md}"
    padding: "{spacing.4}"
  sidebar-item-active:
    backgroundColor: "{colors.ink-200}"
    textColor: "{colors.gold-500}"

  app-shell:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body-md}"
---

## Overview

A **Barra Vips** opera no segmento adulto premium do Rio de Janeiro e São Paulo. Os clientes descobrem as modelos pelo canal orgânico **BarraVips.com**: portal preto, ornamentado em dourado, com perfis discretos e contato direto pelo WhatsApp da modelo. Esse painel **não é** o canal orgânico. Ele é a ferramenta interna que Fernando usa para supervisionar a IA que atende esses clientes em nome de cada modelo.

A linguagem visual deste painel cumpre dois mandatos simultâneos:

- **Continuidade de marca**. Quem opera a Barra Vips reconhece a assinatura preto + dourado em qualquer superfície da agência. O painel respeita essa assinatura para que o operador sinta que está dentro do mesmo ecossistema.
- **Sobriedade operacional**. O painel é uma ferramenta de trabalho de longa duração — listar atendimentos, decidir handoff, validar Pix, registrar resultado. Densidade vence beleza, legibilidade vence ornamento, decisão vence atmosfera.

### Princípios

1. **Decisão acima de tudo.** A interface existe para acelerar o próximo movimento de Fernando ou da modelo: devolver para IA, registrar `fechado valor`, escalar Pix em revisão, abrir o card no grupo de Coordenação. O elemento mais brilhante de qualquer tela é a próxima ação.
2. **Estado é a unidade visual.** Cada atendimento, cada Pix, cada conversa carrega um estado finito (ativa, pausada, em handoff, em revisão, fechado, perdido). O design **mostra o estado antes de mostrar o conteúdo**: badge de estado vem antes do nome, cor de borda esquerda comunica antes do texto.
3. **Dourado é assinatura, não ruído.** Dourado marca presença de marca (logo, foco de CTA primário, item ativo da nav). Nunca preenche grandes áreas. Nunca substitui texto de corpo.
4. **Vermelho e amarelo são vocabulário escasso.** Amarelo (`warn-500`) só aparece quando há handoff ou pendência de decisão humana. Vermelho (`danger-500`) só aparece em perda, erro de comando ou risco confirmado. Se tudo é alerta, nada é alerta.
5. **Conteúdo sensível fica fora do painel.** Fotos de modelos, fotos de portaria enviadas por cliente e comprovantes Pix existem no fluxo, mas a interface os mostra reduzidos, com expansão sob clique deliberado. Nunca em listas, nunca em hovers, nunca em previews automáticos.
6. **Tipografia operacional, ornamento contido.** Serifa (Cormorant Garamond) é cerimonial: aparece no logo do app, no título de página principal e na tela de login. Todo o resto é Inter. Mono (JetBrains Mono) só para JID, ID de evento e o que precisa ser copiado literal.
7. **Modo escuro é o único modo.** A operação acontece de noite e o canal orgânico é preto absoluto. Não existe modo claro neste painel — não é uma simplificação, é a identidade.

## Colors

A paleta tem três planos: **tinta** (escala neutra que constrói superfície e tipografia), **dourado** (assinatura de marca, três tons), e **estados** (vocabulário operacional curto e sempre semântico). Cada token tem um *papel funcional* — o componente consome o papel, não o tom. Tons brutos (`ink-500`, `gold-500`) servem para definir os papéis; nunca devem aparecer hard-coded em código de componente.

### Canvas — preto operacional, não preto absoluto

O canvas do app é `ink-50` (`#0A0A0A`), não `#000000`. Preto puro contra texto claro causa **halation** — sangramento percebido na borda do glifo — em sessões longas, justamente o cenário deste painel. Pelo mesmo motivo, o texto principal é `ink-900` (`#F5F5F5`), off-white deliberado, e não `#FFFFFF`. A literatura de dark mode é uniforme aqui: pares branco-puro × preto-puro fadigam o operador. `ink-0` (`#000000`) permanece na paleta para superfícies *cerimoniais* (fundo de modal de mídia sensível, divisória entre painéis, borda externa da janela) — nunca como background de tela operacional.

### Tinta — escala funcional Radix-style

A escala `ink-0..900` está calibrada para uma correspondência **papel × step** inspirada no modelo de 12 steps do [Radix Colors](https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale). Quando precisar escolher um cinza, escolha pelo papel:

| Token | Hex | Papel funcional |
|---|---|---|
| `ink-0` | `#000000` | Cerimonial: divisória, borda externa, fundo de modal de mídia. |
| `ink-50` | `#0A0A0A` | App background (canvas). |
| `ink-100` | `#141414` | Superfície subtil: card em repouso, sidebar, header. |
| `ink-200` | `#1F1F1F` | Componente UI base: input, botão secondary, hover de tabela. |
| `ink-300` | `#2A2A2A` | Componente pressionado, fundo de badge, hover de input. |
| `ink-400` | `#3D3D3D` | Borda subtil: card, separador, divisor de seção. |
| `ink-500` | `#5C5C5C` | Borda forte, ícone neutro, texto desabilitado. |
| `ink-600` | `#8B8B8B` | Texto silenciado: caption, metadado, placeholder. |
| `ink-700` | `#B4B4B4` | Texto secundário: descrição, body de tabela. |
| `ink-800` | `#DEDEDE` | Texto de destaque: rótulo importante. |
| `ink-900` | `#F5F5F5` | Texto principal: body, headings, ícone primário. |

Steps 1–5 carregam **superfície e estado de interação**; steps 6–7 carregam **borda**; steps 8–10 carregam **ícone, ação, contorno forte**; steps 11–12 carregam **texto**. Componentes não pulam de papel — input não usa cor de texto como fundo, badge não usa cor de superfície como rótulo.

### Dourado — `gold-300`, `gold-500`, `gold-700`

`gold-500` (`#C4A961`) é o dourado canônico — extraído do logo do BarraVips.com e dos labels da ficha de perfil. É a cor do CTA primário, do item ativo da sidebar, da borda esquerda de cards de handoff e do nome do logo. `gold-700` (`#E6CB7A`) é a versão clara, usada em hover de CTA, em links inline e como cor do **focus ring** (sempre 2px, offset 2px). `gold-300` (`#8C7848`) é o dourado fosco para microdetalhes decorativos (separadores cerimoniais, ícone do logo) — não use em texto.

### Estados — `warn-500`, `danger-500`, `success-500`, `info-500`

`warn-500` (`#F4B81C`) é o amarelo do triângulo de aviso da splash 18+ do site público. Reservado para **handoff e pendência humana**: card em handoff, Pix em revisão, comando ambíguo aguardando complemento. `danger-500` (`#D62828`) é o vermelho dos cabeçalhos de seção da nav do site público; aqui se desloca para **perda, erro, risco**: badge de atendimento perdido, erro de comando no grupo, risco confirmado pela IA. `success-500` (`#1FB07A`) e `info-500` (`#4F8FE1`) são introduções deste painel — não existem no canal orgânico — e existem para **fechamento confirmado** e **neutro operacional**.

Estes são os **únicos quatro hues semânticos** do painel. Não invente um quinto. Necessidades como "atenção branda", "informação importante mas neutra" ou "lembrete" se resolvem com tipografia e ênfase, não com cor nova.

### Pares — *background ↔ on-background* (Material 3-style)

Inspirado nos *color roles* do [Material 3](https://m3.material.io/styles/color/roles): toda superfície colorida tem um par `on-` que define a cor do conteúdo (texto, ícone) sobre ela. O componente nunca decide essa combinação — ela vem do par.

| Background | On (texto/ícone) | Uso |
|---|---|---|
| `surface` (`ink-50`) | `on-surface` (`ink-900`) | App background. |
| `surface-raised` (`ink-100`) | `on-surface` (`ink-900`) | Card. |
| `surface-hover` (`ink-200`) | `on-surface` (`ink-900`) | Hover de linha, hover de menu. |
| `surface-pressed` (`ink-300`) | `on-surface` (`ink-900`) | Estado pressionado, fundo de badge. |
| `gold-500` (brand) | `on-brand` (`ink-0`) | CTA primário. |
| `warn-500` | `on-warn` (`ink-0`) | Pílula sólida em destaque (uso raríssimo). |
| `danger-500` | `on-danger` (`ink-900`) | Pílula sólida em destaque (uso raríssimo). |
| `success-500` | `on-success` (`ink-0`) | Pílula sólida em destaque (uso raríssimo). |

Regra prática: **prefira badge em texto colorido sobre `ink-300` em vez de pílula sólida colorida**. Pílula sólida `warn-500`/`danger-500`/`success-500` brilha demais e quebra o monocromático. A pílula sólida é última instância — quando precisa furar a vista por motivo crítico (alerta global, banner de incidente).

### Distribuição visual — 60 / 30 / 10

A regra clássica do [60-30-10](https://uxplanet.org/the-60-30-10-rule-a-foolproof-way-to-choose-colors-for-your-ui-design-d15625e56d25) está aplicada deste modo no painel:

- **60% — superfície neutra escura** (`ink-50`, `ink-100`). É a maior parte de qualquer tela: canvas, sidebar, fundo de tabela, fundo de cards de conteúdo.
- **30% — texto e estrutura** (`ink-700`, `ink-800`, `ink-900` em tipografia; `ink-300`, `ink-400` em bordas e divisores). Tipografia, ícones em repouso, separadores. É o que o operador *lê*.
- **10% — assinatura e estado** (`gold-500` para marca/ação canônica; vocabulário curto: `warn-500`, `danger-500`, `success-500`, `info-500`). Aparece pontualmente em CTAs canônicos, item ativo da nav, badges, bordas laterais de cards de decisão.

Se o **10% começar a parecer 30%**, há ruído visual — alguma cor está sendo usada fora do papel. A proporção é referência de calibragem, não medição em pixels: em telas de operação corrente (lista de atendimentos, timeline) a tinta domina e a marca quase desaparece, e está certo. Em telas cerimoniais (login) o dourado pode crescer.

### Roles semânticos — única superfície de consumo

Os tokens semânticos (`text-primary`, `surface`, `border-brand`, `state-handoff`, `on-brand`, `focus-ring`, etc.) são a **única superfície que componentes devem consumir**. Tokens cromáticos brutos (`ink-500`, `gold-500`) são para definir os semânticos no `globals.css` / `theme`, não para uso direto em componente.

### Acessibilidade

- Texto principal (`text-primary` sobre `surface`): **17:1** — WCAG AAA.
- Texto secundário (`text-secondary` sobre `surface`): **8.6:1** — WCAG AAA.
- Texto silenciado (`text-muted` sobre `surface`): **5.3:1** — WCAG AA para texto pequeno.
- CTA primário (`on-brand` sobre `gold-500`): **11.2:1** — WCAG AAA.
- Bordas e ícones (`ink-500`+ sobre `surface`): **3:1** mínimo — atende [WCAG 1.4.11 — non-text contrast](https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast).
- Focus ring (`gold-700`, 2px, offset 2px): **8.2:1** sobre `surface`. Sempre visível, **nunca removido** em override do shadcn.

A calibragem complementar segue o modelo perceptual [APCA](https://www.myndex.com/APCA/) — texto principal atinge `Lc 90`+, secundário `Lc 75`+, alinhado aos passos 11–12 do Radix.

## Typography

Três famílias, escala curta, uso disciplinado.

### Famílias

- **Cormorant Garamond** — serifa cerimonial. Logo do painel, título da tela de login, título de página principal (`Painel`, `Atendimentos`). Empresta a serif do logo `BarraVips`. **Nunca em texto operacional.**
- **Inter** — sans-serif operacional. Toda a UI (cabeçalhos de seção, body, labels, badges, botões, tabelas).
- **JetBrains Mono** — mono. JID (`5521...@s.whatsapp.net`), IDs de evento, valor literal de comando recebido no grupo, hash de Pix.

### Escala

| Token | Uso |
|---|---|
| `display-xl` | Splash de login. Único lugar onde a serifa aparece em tamanho monumental. |
| `display-lg` | Título da página atual (uma vez por tela). |
| `heading-lg` | H1 dentro de uma tela já titulada. Cabeçalho de modal. |
| `heading-md` | H2 de seção. Título de card. Texto de botão. |
| `heading-sm` | Labels de coluna em tabela. Cabeçalhos de grupo na sidebar. Sempre maiúsculo, com `letter-spacing 0.08em`. |
| `body-md` | Texto principal. Descrições. Mensagens dentro do timeline da conversa. |
| `body-sm` | Linhas de tabela. Metadados em cards densos. |
| `caption` | Timestamp, contador, badges. |
| `mono-sm` | JIDs, IDs, comandos literais. |

### Regras

- Nunca centralize parágrafos. Centralize só o título da splash de login.
- Nunca use `display-xl` ou `display-lg` na operação corrente — só em superfícies cerimoniais.
- Quando uma frase mistura PT-BR de domínio com identificador técnico (ex.: "JID `5521...@s.whatsapp.net`"), o identificador vai em `mono-sm` inline com cor `text-muted`.
- Não use itálico para ênfase em texto operacional. Use peso (`font-weight: 600`) ou cor (`text-brand`).

## Layout

### Grade do app

O app tem **shell de duas colunas**: sidebar fixa de 240px à esquerda + área de conteúdo. Em telas operacionais com timeline (atendimento aberto), surge uma **terceira coluna** à direita de 360px com card de contexto (cliente, modelo, último resultado conhecido). A área central nunca passa de 1280px de largura útil; passou disso, ganha respiro lateral.

### Escala de espaçamento

Base 4px. Escala curta (`spacing.0`–`spacing.8`). A maioria das densidades operacionais cabe em `spacing.2`–`spacing.4`. Cards de decisão (handoff, registro de resultado) recebem `spacing.5` para dar respiro à decisão. Áreas cerimoniais (login) usam `spacing.6`–`spacing.7`.

### Densidade

Lista de atendimentos é **densa por padrão**: 44px de altura de linha, sem ilustração, badge de estado à esquerda, nome no meio, timestamp e ação à direita. Mostre 12+ atendimentos sem rolar em tela 1080p. A versão respirada (linha de 64px com snippet da última mensagem) é opcional, comutável por toggle de densidade — nunca o padrão.

### Breakpoints

| Breakpoint | Mínimo | Estratégia |
|---|---|---|
| `sm` | 640px | Apenas tela de login. Nenhuma tela operacional é desenhada para mobile. |
| `md` | 768px | Tablet — sidebar colapsa em rail de 64px. |
| `lg` | 1024px | Mínimo desejado para operação real. |
| `xl` | 1280px | Layout canônico. Timeline + card de contexto lado a lado. |
| `2xl` | 1536px | Acima disto, ganha respiro lateral, sem alargar conteúdo. |

O painel **não tem versão mobile operacional**. Em mobile, exibe-se um aviso curto direcionando ao desktop ou ao grupo de Coordenação por modelo (que já é o canal mobile da operação).

## Elevation & Depth

Em modo escuro, profundidade não vem de sombra projetada; vem de **escalonamento de superfícies** sobre o canvas preto. Quanto mais alto o elemento, mais claro o `ink`.

| Camada | Token | Uso |
|---|---|---|
| Canvas | `ink-0` | Fundo absoluto entre módulos do shell. Borda de janela. |
| Superfície | `ink-50` | Background de área de conteúdo. |
| Superfície elevada | `ink-100` | Card, sidebar, header. |
| Hover | `ink-200` | Linha de tabela em hover, input, item de menu em hover. |
| Pressed | `ink-300` | Estado pressionado. Background de badge. |

Sombras são reservadas para **modais e popovers** que precisam destacar-se de cards subjacentes, e mesmo nesse caso a sombra é estreita e próxima:

- `shadow-popover`: `0 8px 24px rgba(0,0,0,0.6)`
- `shadow-modal`: `0 16px 48px rgba(0,0,0,0.7)`

Nenhum outro componente carrega sombra. Card não tem sombra — sua elevação é a cor da superfície.

## Shapes

A geometria do painel é **levemente arredondada e funcional**. Nunca pill em botão (pill é só badge/chip). Nunca quadrado absoluto fora de divisórias e tabelas.

| Token | Uso |
|---|---|
| `rounded.none` | Tabelas, divisórias, cabeçalhos full-width. |
| `rounded.sm` | Inputs, badges retangulares, tags pequenas. |
| `rounded.md` | Botões, cards densos, dropdowns. |
| `rounded.lg` | Cards de decisão (handoff, registro de resultado), modais. |
| `rounded.xl` | Splash de login, hero da home (se houver). |
| `rounded.pill` | Badges de estado, chips de filtro. |

### Bordas de marca

Cards que comunicam **estado operacional** ganham uma **borda esquerda de 3px** colorida pelo estado:

- `border-left: 3px solid gold-500` — atendimento ativo conduzido pela IA.
- `border-left: 3px solid warn-500` — atendimento em handoff, Pix em revisão.
- `border-left: 3px solid success-500` — atendimento fechado.
- `border-left: 3px solid danger-500` — atendimento perdido, erro de comando.

A borda lateral é a **única assinatura cromática** do card. O resto do card permanece monocromático.

## Components

### Botões

Três variantes principais e uma de exceção.

- **Primary** (`button-primary`) — dourado sólido, texto preto. Reservado para a **ação canônica** da tela: `Devolver para IA`, `Registrar resultado`, `Aprovar Pix`. Uma única instância visível por tela. Hover clareia para `gold-700`.
- **Secondary** (`button-secondary`) — superfície `ink-200`, texto `ink-900`. Para ações secundárias: `Cancelar`, `Ver detalhes`, `Abrir conversa`.
- **Ghost** (`button-ghost`) — sem fundo, texto `ink-700`. Para ações terciárias e itens de menu inline.
- **Danger** (`button-danger`) — `ink-200` com texto `danger-500`. Apenas para `Marcar como perdido`, `Reverter Pix`, ações destrutivas que precisam confirmar.

Botões nunca são pill. Não há `button-tertiary` separado — `ghost` cumpre o papel.

### Cards de decisão

Componente central do painel. Estrutura fixa:

```
[borda lateral colorida pelo estado] [conteúdo]
  cabeçalho:  badge-estado · nome do cliente · #atendimento (mono-sm)
  corpo:      resumo de 1-2 linhas (body-sm) + metadados (caption, text-muted)
  ação:       button-primary (canônica) + button-ghost (secundárias)
  footnote:   timestamp da última transição (caption, text-muted)
```

Card de handoff e card de registro de resultado seguem essa estrutura. Não use cards diferentes para fluxos diferentes — varie pela borda lateral, pelo badge e pelo botão canônico.

### Badges de estado

Pill arredondado, `caption`, fundo `ink-300`, texto colorido pelo estado. Vocabulário fechado:

| Badge | Cor de texto | Quando |
|---|---|---|
| `Ativa` | `gold-500` | IA conduzindo a conversa cliente. |
| `Pausada` | `ink-600` | IA pausada por motivo neutro (timeout, fim de expediente da modelo). |
| `Em handoff` | `warn-500` | IA pausada aguardando decisão humana. |
| `Em revisão` | `warn-500` | Pix de deslocamento aguardando Fernando. |
| `Fechado` | `success-500` | Atendimento com `Registro de resultado` fechado. |
| `Perdido` | `danger-500` | Atendimento com `Registro de resultado` perdido. |

Badges não comunicam ação — comunicam estado. Nunca clicáveis.

### Inputs e formulários

Inputs ocupam altura `40px`, fundo `ink-100`, borda `border-strong`. No foco, ganham ring `gold-700` de 2px. Placeholders em `text-muted`. Erros descem como linha de `body-sm` em `danger-500` abaixo do input — nunca tooltip, nunca borda vermelha sem texto.

Formulários do painel são curtos por construção. Se um formulário precisa de mais de 6 campos, há um problema de fluxo, não de design.

### Tabelas

Linha de 44px de altura, `body-sm`, sem zebra (zebra empobrece o monocromático). Hover `ink-200`. Borda inferior `1px ink-300`. Cabeçalho `heading-sm` em maiúsculas com `letter-spacing 0.08em`, fixo no scroll (`position: sticky`).

Nunca incluir foto na tabela de modelos ou de atendimentos. Modelo é representada por nome + bairro + status; cliente é representado por nome (ou apelido) + último contato + estado da conversa.

### Sidebar

Largura `240px`, fundo `ink-50`. Logo no topo (Cormorant Garamond, `gold-500`). Itens: `body-md`, `text-secondary` em repouso, `text-primary` em hover, `gold-500` quando ativos com fundo `ink-200`. Cabeçalhos de grupo (`OPERAÇÃO`, `CADASTROS`) em `heading-sm` maiúsculo `text-muted`.

Em rail (768–1024px), só ícones — labels viram tooltip.

### Timeline da conversa

Mensagens em coluna, balão à esquerda do cliente, balão à direita da modelo (que pode ser IA ou modelo manual — distinguir por etiqueta `IA` em `gold-500` ou `MODELO` em `ink-700`, posicionada acima do balão). Balão do cliente: fundo `ink-100`. Balão da modelo: fundo `ink-200`. Borda lateral esquerda de 2px `gold-500` no balão da IA — esse é o único momento em que essa borda aparece em mensagem.

Mensagens recebidas durante handoff continuam na timeline (CONTEXT.md: "a Conversa cliente continua sendo gravada mesmo quando a IA está pausada"), com um divisor horizontal sutil `border-subtle` marcando início e fim do bloco de handoff.

### Anexos sensíveis

Foto de portaria, comprovante Pix, mídia enviada pelo cliente: aparecem como **chip mono** com ícone + nome do arquivo + tamanho. Expansão visual exige clique deliberado — nunca preview automático em hover, nunca thumbnail em lista. Quando expandido, surge em modal com fundo `ink-0`, sem border-radius, sem decoração.

## Data Visualization

O painel tem áreas analíticas (dashboard de atendimentos por hora, distribuição de motivos de perda, conversão de Pix, ranking de modelos no mês). Charts seguem **três paletas finitas**, escolhidas pela natureza do dado:

- **Categórica** — categorias sem ordem implícita.
- **Sequencial** — magnitude/intensidade ordenada.
- **Divergente** — desvio em torno de um ponto neutro.

Limite máximo: **7 séries simultâneas**. Acima disso, agrupe em "outros" ou troque o chart por uma tabela.

### Categórica — `chart-1` a `chart-7`

Para categorias sem ordem (ex.: motivos de perda, modelos mais ativas no mês). Use **a ordem fixa** dos tokens — não permute, não associe cor a categoria por significado ("vermelho para o pior"), porque isso quebra quando outra tela usa "vermelho para perdido". O agente de design escolhe pela ordem decrescente de magnitude da série.

| Token | Hex | Hue | Origem |
|---|---|---|---|
| `chart-1` | `#C4A961` | dourado | brand |
| `chart-2` | `#4F8FE1` | azul | info |
| `chart-3` | `#1FB07A` | verde | success |
| `chart-4` | `#B66CD9` | púrpura | introdução |
| `chart-5` | `#E07A5F` | terracota | introdução |
| `chart-6` | `#6FCFC9` | teal claro | introdução |
| `chart-7` | `#D4A574` | caramelo | introdução |

A paleta foi escolhida para sobreviver a **deuteranopia** (red-green colorblindness, ~8% dos homens): nenhuma combinação adjacente depende exclusivamente do eixo vermelho-verde. `danger-500` **não entra** nessa paleta — é semântico, não categórico. Usar vermelho brilhante para "fluxo X" leva o leitor a concluir que algo está errado quando não está.

### Sequencial — single-hue dourado

Para magnitude ordenada (ex.: heatmap de horários com mais conversa, intensidade de uso por modelo). Single-hue garante que a leitura sobreviva a qualquer tipo de daltonismo — só a luminosidade carrega informação.

| Token | Hex | Posição |
|---|---|---|
| `seq-1` | `#1A1606` | mais baixo |
| `seq-2` | `#4A3F25` | |
| `seq-3` | `#8C7848` | mediano |
| `seq-4` | `#C4A961` | |
| `seq-5` | `#E6CB7A` | mais alto |

### Divergente — vermelho ↔ neutro ↔ verde

Para desvio em torno de um meio significativo (ex.: variação versus meta de fechamentos, repasse acima/abaixo do esperado). A paleta **reusa o vocabulário já estabelecido** do painel: vermelho do `danger-500` no extremo negativo, verde do `success-500` no extremo positivo, neutro `ink-500` no meio. O operador não precisa aprender uma segunda gramática cromática — vermelho continua sendo "ruim/abaixo" em qualquer superfície (badge, card, gráfico), verde continua sendo "bom/acima".

| Token | Hex | Posição |
|---|---|---|
| `div-low` | `#D62828` (`danger-500`) | extremo negativo |
| `div-low-2` | `#E0857A` | negativo fosco |
| `div-mid` | `#5C5C5C` (`ink-500`) | meio neutro |
| `div-high-2` | `#7DCFA8` | positivo fosco |
| `div-high` | `#1FB07A` (`success-500`) | extremo positivo |

**Esta escolha pressupõe operadores sem deuteranopia (red-green colorblindness).** Se a operação contratar alguém daltônico, troque para a paleta colorblind-safe azul ↔ laranja: `#4F8FE1` → `#5C5C5C` → `#E07A5F`. Os tokens (`div-low`, `div-mid`, `div-high`) continuam os mesmos — só os valores mudam.

**Convivência com badges**: vermelho num KPI "fechamentos abaixo da meta" não conflita com o vermelho do badge "Perdido" porque a leitura é convergente — em ambos os casos significa "atenção, está ruim". A regra que continua valendo: `danger-500` **não entra** na paleta categórica (`chart-1..7`), porque ali a cor não tem direção semântica e o vermelho seria interpretado como erro fora de contexto.

### Eixos, grid e fundo de chart

- Fundo do chart: **`surface`** (`ink-50`) — chart funde no app, não em moldura.
- Linhas de grid: **`ink-300`**, 1px sólido, opacidade 0.6. Tracejado opcional para eixos de referência (meta, baseline).
- Eixos: **`ink-500`**, 1px sólido.
- Labels de eixo: `caption` em `text-muted`.
- Tooltip: `surface-raised` com `border-subtle`, `body-sm`, sombra `shadow-popover`.
- Legenda: `caption` em `text-secondary`, alinhada ao topo direito do chart, máximo 2 linhas.

### KPIs e charts não substituem estados

Um KPI "atendimentos perdidos" em destaque pode usar `danger-500` no número grande e a paleta categórica `chart-1`/`chart-2` no detalhamento abaixo. O número é semântico (estado); a barra é categoria. Os dois sistemas convivem por separação clara de papéis.

### Quando trocar chart por tabela

- Mais de 7 categorias.
- Comparações exatas (operador precisa do número, não da impressão).
- Dados onde a ordem importa mais que a magnitude.
- Listagens com identificador (modelo, cliente, atendimento).

Tabela vence chart sempre que a decisão depende de leitura literal — e o painel é um produto de decisões.

## Do's and Don'ts

### Faça

- **Faça** começar cada tela operacional pelo estado do que está aberto agora (handoff pendente, Pix em revisão, atendimento aguardando confirmação) — antes de qualquer dashboard ou métrica.
- **Faça** usar a borda esquerda colorida como assinatura de estado em qualquer card de decisão.
- **Faça** preservar `gold-500` como cor exclusiva da ação canônica da tela e do item ativo da navegação.
- **Faça** mostrar JIDs, IDs e comandos literais em `mono-sm` com `text-muted` — nunca em sans-serif e nunca em cor de destaque.
- **Faça** confirmar destrutivos (registrar perdido, reverter Pix, deletar bloqueio em `em_atendimento`) com modal explícito que repete o estado atual e o estado proposto.
- **Faça** manter modo escuro como o único modo do painel.
- **Faça** ler o `CONTEXT.md` antes de inventar nomenclatura na UI — o domínio é fechado: `Conversa cliente`, `Coordenação por modelo`, `Handoff`, `Devolução para IA`, `Registro de resultado`, `Pix de deslocamento`, `Aviso de saída`, `Foto de portaria`. Use esses termos exatos.
- **Faça** usar `ink-50` (`#0A0A0A`) como canvas e `ink-100` (`#141414`) como superfície de card. `ink-0` (`#000000`) é cerimonial — divisórias e modais de mídia.
- **Faça** consumir cores pelo papel semântico (`surface`, `on-surface`, `border-brand`, `state-handoff`, `focus-ring`) — nunca pelo nome do tom (`ink-500`, `gold-500`) em código de componente.
- **Faça** parear background com seu `on-` correspondente quando a superfície for colorida — sempre que escolher um background, o token de texto vem do par definido em `## Colors`.
- **Faça** seguir a ordem fixa `chart-1..7` em séries categóricas; agrupe em "outros" antes de chegar na 8ª série.
- **Faça** preferir tabela a chart quando há mais de 7 categorias, quando a comparação precisa ser exata, ou quando há identificador por linha (modelo, cliente, atendimento).
- **Faça** calibrar a tela contra a regra **60-30-10**: se a marca ou os estados começarem a ocupar mais de ~10% da composição, alguma cor saiu do papel.

### Não faça

- **Não** replique a estética sensual/adulta do BarraVips.com no painel. O canal orgânico vende perfis; o painel coordena operação. São públicos diferentes.
- **Não** mostre fotos de modelos em lista, em sidebar, em hover ou em qualquer superfície que não seja a tela explícita de cadastro da modelo.
- **Não** mostre a foto de portaria nem o comprovante de Pix em preview automático — sempre por clique deliberado, sempre com fundo neutro.
- **Não** use serifa (Cormorant Garamond) em texto operacional. Serifa é cerimonial, não funcional.
- **Não** use vermelho ou amarelo fora do vocabulário de estado definido. Não pinte um botão de ação corrente de `warn-500` "para chamar atenção" — chamar atenção é o trabalho do `gold-500`.
- **Não** introduza um quarto tom de dourado, um quinto cinza ou uma cor "de marca alternativa". A paleta é fechada.
- **Não** use elevação por sombra em cards. A profundidade vem da cor da superfície.
- **Não** use ilustração, ícone decorativo, gradient, glow, glass-morphism ou qualquer efeito atmosférico. O painel é severo por escolha.
- **Não** desenhe ações destrutivas como botões primários — `Marcar como perdido` é `button-danger`, nunca `button-primary`.
- **Não** invente uma versão mobile operacional. Mobile é tela de login + redirecionamento. Operação real é desktop.
- **Não** pluralize emojis ou misture iconografias (Heroicons + Lucide + emoji). Use **Lucide** uniformemente, em `1.5px stroke`, tamanho 16px ou 20px.
- **Não** confunda `Pausada` (neutro, IA descansando) com `Em handoff` (amarelo, decisão humana pendente). São estados diferentes com cores diferentes.
- **Não** carregue avatar de cliente do WhatsApp na timeline. Cliente é texto + JID em mono. Privacidade é estética aqui.
- **Não** use `#000000` ou `#FFFFFF` puros em superfícies grandes — o par causa **halation** (sangramento percebido na borda do glifo) em sessões longas. Use `ink-50` no canvas e `ink-900` no texto.
- **Não** use `danger-500` em chart categórico. Vermelho semântico em chart faz o leitor ler "erro" onde não há.
- **Não** introduza um vermelho ou verde fora de `danger-500`/`success-500` para uso em diverging chart — a paleta divergente reusa exatamente esses dois tokens. Se a operação contratar alguém daltônico, **troque a paleta** (azul → neutro → laranja), não invente um terceiro vermelho.
- **Não** introduza uma 8ª cor categórica. Mais de 7 séries é sinal de que o chart errado foi escolhido.
- **Não** misture paleta categórica com sequencial no mesmo chart. Uma cor por papel.
- **Não** use pílula sólida em `warn-500`/`danger-500`/`success-500` por padrão — prefira badge com texto colorido sobre `ink-300`. Pílula sólida é última instância.
- **Não** dependa só de cor para comunicar estado (red-green colorblind, contexto monocromático em screenshots impressos). Acompanhe sempre com **rótulo textual ou ícone**: badge `Em handoff` em amarelo carrega a palavra "Em handoff", não só a cor.
