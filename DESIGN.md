---
name: Elite Baby Painel
description: Painel operacional interno da agência Elite Baby. Densidade, decisão e a assinatura preto + dourado.
colors:
  ink-0: "#000000"
  ink-50: "#0A0A0A"
  ink-100: "#141414"
  ink-200: "#1F1F1F"
  ink-300: "#2A2A2A"
  ink-400: "#3D3D3D"
  ink-500: "#5C5C5C"
  ink-600: "#8B8B8B"
  ink-700: "#B4B4B4"
  ink-800: "#DEDEDE"
  ink-900: "#F5F5F5"
  gold-300: "#8C7848"
  gold-500: "#C4A961"
  gold-700: "#E6CB7A"
  warn-500: "#F4B81C"
  danger-500: "#D62828"
  success-500: "#1FB07A"
  info-500: "#4F8FE1"
  surface: "#0A0A0A"
  surface-raised: "#141414"
  surface-hover: "#1F1F1F"
  surface-pressed: "#2A2A2A"
  border-subtle: "#2A2A2A"
  border-strong: "#3D3D3D"
  border-brand: "#C4A961"
  text-primary: "#F5F5F5"
  text-secondary: "#B4B4B4"
  text-muted: "#8B8B8B"
  text-disabled: "#5C5C5C"
  text-brand: "#C4A961"
  text-link: "#E6CB7A"
  focus-ring: "#E6CB7A"
  on-brand: "#000000"
  on-danger: "#F5F5F5"
  on-success: "#000000"
  on-info: "#000000"
  state-active: "#C4A961"
  state-paused: "#8B8B8B"
  state-handoff: "#F4B81C"
  state-lost: "#D62828"
  state-closed: "#1FB07A"
  state-info: "#4F8FE1"
typography:
  display:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: "28px"
    fontWeight: 500
    lineHeight: "1.1"
    letterSpacing: "normal"
  headline:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 600
    lineHeight: "48px"
    letterSpacing: "-0.01em"
  metric:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "36px"
    fontWeight: 600
    lineHeight: "44px"
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 500
    lineHeight: "1.375"
    letterSpacing: "normal"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: "1.5"
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: "16px"
    letterSpacing: "0.08em"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, monospace"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: "16px"
    letterSpacing: "normal"
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  full: "9999px"
spacing:
  "1": "4px"
  "2": "8px"
  "2.5": "10px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
components:
  button-primary:
    backgroundColor: "{colors.gold-500}"
    textColor: "{colors.on-brand}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.gold-700}"
    textColor: "{colors.on-brand}"
  button-secondary:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-outline:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-danger:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.danger-500}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  input:
    backgroundColor: "transparent"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "4px 10px"
    height: "32px"
  card:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    padding: "16px"
  badge-handoff:
    backgroundColor: "{colors.surface-pressed}"
    textColor: "{colors.state-handoff}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: "4px 12px"
  sidebar-item-active:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.gold-500}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
---

# Design System: Elite Baby Painel

## 1. Overview

**Creative North Star: "A Sala de Comando Noturna"**

Este painel não é a vitrine. O canal orgânico Elite Baby (preto absoluto, serifa ornamentada, perfis sensuais) existe para captar clientes; este produto existe para Fernando supervisionar, por horas seguidas, a IA que atende esses clientes em nome de cada modelo. A linguagem visual é a de uma sala de comando: superfície escura que descansa a vista na operação noturna, dourado como assinatura discreta da marca, e um vocabulário cromático curto e severo onde cada cor carrega significado operacional. Densidade vence beleza, legibilidade vence ornamento, decisão vence atmosfera.

O painel tem dois temas (escuro e claro, alternáveis via `next-themes` com `defaultTheme="system"`), mas o **escuro é o tema canônico**: é a identidade Elite Baby, é onde a operação noturna acontece e é a referência para qualquer decisão de design. O tema claro (superfícies creme `#FAFAF7` e branco) é a alternativa funcional para quem opera sob luz forte; ele herda a mesma estrutura de tokens, apenas invertendo a escala de tinta. Quando uma escolha visual conflitar entre os dois temas, resolva pelo escuro.

O sistema rejeita explicitamente: painéis SaaS genéricos com gradientes coloridos, dashboards com hero-metrics e grids de cards idênticos, interfaces "consumer" com muito espaço em branco, e qualquer coisa que pareça template de admin. Também rejeita reproduzir a estética sensual/adulta do canal orgânico: público diferente, mandato diferente.

**Key Characteristics:**
- Densidade alta: 12+ atendimentos visíveis sem rolar em 1080p; cada tela cabe no viewport.
- Estado antes de conteúdo: badge e faixa de borda comunicam o estado de negócio antes do texto.
- Dourado escasso: marca e ação canônica, nunca preenchimento de área.
- Vocabulário de cor fechado: quatro hues semânticos, sem um quinto.
- Desktop-only: abaixo de 1024px o operador vê um blocker, não uma versão mobile.

## 2. Colors

Três planos: tinta (escala neutra que constrói superfície e tipografia), dourado (assinatura de marca, três tons) e estados (vocabulário operacional curto e sempre semântico). Componentes consomem o **papel** (`surface`, `text-primary`, `state-handoff`), nunca o tom bruto (`ink-500`, `gold-500`). Os valores no frontmatter estão resolvidos no tema canônico (escuro); o tema claro inverte a escala de tinta mantendo os mesmos papéis.

### Primary
- **Dourado Elite Baby** (`gold-500`, #C4A961): a assinatura. CTA primário, item ativo da navegação, faixa de borda de atendimento ativo conduzido pela IA, logotipo. Extraído do logo e dos labels da ficha de perfil. No tema claro o papel de marca migra para `gold-300` (#8C7848) por contraste.
- **Dourado claro** (`gold-700`, #E6CB7A): hover do CTA, links inline e cor do focus ring.
- **Dourado fosco** (`gold-300`, #8C7848): microdetalhe decorativo (separador cerimonial, ícone do logo). Nunca em texto sobre fundo escuro.

### Tertiary (estados semânticos)
Os únicos quatro hues semânticos do painel. Não existe um quinto. Necessidades como "atenção branda" ou "lembrete" resolvem-se com tipografia e ênfase, não com cor nova.
- **Âmbar** (`warn-500`, #F4B81C): handoff e pendência humana. Card aguardando você, comando ambíguo aguardando complemento.
- **Vermelho** (`danger-500`, #D62828): perda, erro, risco. Badge de atendimento perdido, faixa de Pix em revisão, erro de comando no grupo.
- **Verde** (`success-500`, #1FB07A): fechamento confirmado, tendência positiva.
- **Azul** (`info-500`, #4F8FE1): neutro acionável, modelo em atendimento.

### Neutral (escala de tinta `ink-0` a `ink-900`)
Escala funcional inspirada nos 12 steps do Radix: escolha o cinza pelo papel, não pelo tom. Steps 1 a 5 carregam superfície e interação; 6 a 7 carregam borda; 8 a 10 carregam ícone e contorno forte; 11 a 12 carregam texto.
- **Canvas** (`surface`, #0A0A0A no escuro / #FAFAF7 no claro): fundo da área de conteúdo. No escuro é `ink-50`, não `#000000`: preto puro contra texto claro causa halation em sessões longas.
- **Superfície elevada** (`surface-raised`, #141414 / #FFFFFF): card, popover, dialog, sidebar.
- **Hover / Pressed** (`surface-hover` #1F1F1F, `surface-pressed` #2A2A2A): estados interativos e fundo de badge.
- **Bordas** (`border-subtle` #2A2A2A, `border-strong` #3D3D3D): divisores e bordas enfáticas.
- **Texto** (`text-primary` #F5F5F5, `text-secondary` #B4B4B4, `text-muted` #8B8B8B): principal off-white deliberado (não `#FFFFFF`), secundário e silenciado. No tema claro o texto principal é `ink-100` (#141414).

### Named Rules
**A Regra dos Quatro Hues.** O painel tem exatamente quatro cores semânticas (`warn`, `danger`, `success`, `info`) mais o dourado de marca. Nunca introduza uma quinta. Se algo precisa de destaque e não é estado nem marca, use peso ou tamanho de tipografia.

**A Regra 60-30-10.** 60% superfície neutra, 30% texto e estrutura, 10% assinatura e estado. Se o dourado ou os estados começarem a parecer 30% da tela, alguma cor saiu do papel. Em telas de operação corrente a tinta domina e a marca quase desaparece, e está certo.

**A Regra do Par.** Toda superfície colorida tem um par `on-` que define a cor do conteúdo sobre ela (`gold-500` carrega `on-brand`; `danger-500` carrega `on-danger`). O componente nunca decide essa combinação: ela vem do par.

## 3. Typography

**Display Font:** Cormorant Garamond, peso 500 (com fallback Georgia, serif)
**Body Font:** Inter (com fallback ui-sans-serif, system-ui)
**Label/Mono Font:** JetBrains Mono (com fallback ui-monospace)

**Character:** A serifa é cerimonial e rara; a sans é operacional e onipresente; a mono carrega o que precisa ser lido ou copiado literalmente. O contraste entre a Cormorant do logo e a Inter densa da operação é a própria tensão do produto: marca de luxo, ferramenta de trabalho.

### Hierarchy
- **Display** (Cormorant 500, 28px): exclusivo do logotipo "Elite Baby" na sidebar e do título da tela de login. Nunca em texto operacional.
- **Headline** (Inter 600, 40px / 48px, tabular-nums): KPI grande do dashboard.
- **Metric** (Inter 600, 36px / 44px, tracking -0.02em): número de tile de métrica.
- **Title** (Inter 500, 16px): título de card e de dialog.
- **Body** (Inter 400, 14px): corpo padrão, item de lista, input. Conteúdo denso de card desce a 13px. Limite de linha de leitura em 65 a 75ch.
- **Label** (Inter 500, 12px, tracking 0.08em, maiúsculo): label de tile, cabeçalho de coluna, badge.
- **Mono** (JetBrains Mono 500, 12px): JID, ID de evento, telefone, valor literal de comando, hash de Pix.

### Named Rules
**A Regra da Serifa Cerimonial.** Cormorant Garamond aparece em exatamente dois lugares: o logotipo e o título do login. Em qualquer outro texto é regressão. Para ênfase em texto operacional, use peso 600 ou `text-brand`, nunca itálico nem serifa.

**A Regra do tabular-nums.** Todo número que atualiza (tile, ranking, valor monetário, contador) usa `tabular-nums`. Sem isso os dígitos pulam ao atualizar. Pesos em uso: 500 e 600 apenas; `font-bold` quebra a hierarquia.

## 4. Elevation

O painel é flat por escolha. Profundidade não vem de sombra projetada; vem de escalonamento de superfícies sobre o canvas: quanto mais alto o elemento, mais clara a tinta no escuro (canvas `ink-50` < card `ink-100` < hover `ink-200` < pressed `ink-300`), e o inverso no claro. Cards não carregam `box-shadow`: a separação vem de `ring-1 ring-foreground/10` mais a cor da superfície. Sombra é reservada exclusivamente para overlays que precisam destacar-se de conteúdo subjacente (modal, popover), e mesmo nesse caso é estreita e próxima.

### Shadow Vocabulary (uso restrito)
- **popover** (`box-shadow: 0 8px 24px rgba(0,0,0,0.6)`): dropdown e popover sobre card.
- **modal** (`box-shadow: 0 16px 48px rgba(0,0,0,0.7)`): dialog e modal de mídia sensível.

### Named Rules
**A Regra Flat-Por-Padrão.** Nenhum componente além de modal e popover carrega sombra. Se você sentiu vontade de adicionar `shadow` num card para "destacar", a resposta é trocar a superfície (`surface-raised`) ou o `ring`, nunca projetar sombra.

## 5. Components

Primitivas vêm do shadcn/ui sobre Base UI, com `data-slot` obrigatório no root e nas partes nomeadas. Domínio em PT-BR construído por cima (`CardDestaque`, `BadgeEstadoAtendimento`); primitivas permanecem em EN.

### Buttons
- **Shape:** cantos suaves (`rounded-lg`, 12px). Botão nunca é pílula; pílula é só badge e chip.
- **Tamanho:** altura padrão 32px (`h-8`), padding lateral 10px (`px-2.5`), `text-sm font-medium`. Variantes `sm` (28px) e `xs` (24px) para barras densas; `lg` (36px) para CTA cerimonial.
- **Primary** (`gold-500` sobre `on-brand`): a ação canônica da tela ("Devolver para IA", "Registrar resultado"). Uma instância visível por tela. Hover escurece para `bg-primary/80`.
- **Secondary** (`surface-hover` sobre `text-primary`): "Cancelar", "Ver detalhes". **Ghost** (transparente, `text-secondary`): ações terciárias e itens de menu. **Outline** (fundo `surface`, borda `border`): alternativa de baixo peso.
- **Danger** (`surface-hover` com texto `danger-500`): ações destrutivas que confirmam ("Marcar como perdido"). Nunca um botão destrutivo desenhado como primary.
- **Focus / Active:** foco é `ring-3 ring-ring/50` mais `border-ring` (sem outline removido); active afunda 1px (`translate-y-px`).

### Badges (estado)
- **Style:** pílula (`rounded-full`), `text-xs font-medium`, padding `px-3 py-1`. Fundo tingido `bg-state/15`, borda `border-state/30`, texto `text-state`.
- **Vocabulário fechado:** `Ativa` (gold), `Pausada` (ink-600), `Aguardando você` / handoff (warn), `Modelo atendendo` / info (info), `Pix em revisão` / revisao (danger), `Fechado` (success), `Perdido` (danger). Badges comunicam estado, nunca ação; nunca são clicáveis.

### Cards / Containers
- **Corner Style:** `rounded-xl` (16px); card compacto `data-size="sm"`.
- **Background:** `surface-raised`. **Border:** `ring-1 ring-foreground/10`, sem sombra. **Footer:** `border-t bg-muted/50`.
- **Internal Padding:** `p-4` padrão (`py-4 px-4`), `p-3` compacto, `p-5` a `p-6` em cards de tile e decisão.

### Inputs / Fields
- **Style:** altura 32px (`h-8`), `rounded-lg`, borda `border-input`, fundo transparente (no escuro `bg-input/30`), padding `px-2.5 py-1`.
- **Focus:** `border-ring` mais `ring-3 ring-ring/50`. **Erro:** linha `body` em `danger-500` abaixo do campo, mais `aria-invalid` que pinta borda e ring. Nunca tooltip, nunca borda vermelha sem texto.
- Formulários do painel são curtos por construção: mais de 6 campos é sinal de problema de fluxo.

### Navigation (sidebar)
- Largura 240px, fundo `surface-raised`. Logo no topo em Cormorant `gold-500`. Itens em `body`, `text-secondary` em repouso, `gold-500` quando ativos com fundo `surface-hover`. Cabeçalhos de grupo em `label` maiúsculo. Em rail (768 a 1024px) só ícones, labels viram tooltip.

### CardDestaque (componente-assinatura)
O card de decisão do painel. Estrutura fixa: faixa de borda esquerda colorida pelo estado (`border-l-4`, compacto `border-l-3`), cabeçalho com badge de estado mais nome do cliente mais `#atendimento` em mono, corpo de resumo curto mais metadados, ação canônica (button-primary) mais secundárias (ghost), e timestamp da última transição. Hover clareia para `surface-hover` com `ring-border-brand/40`. A faixa lateral mapeia direto ao motivo da pausa: `border-l-warn-500` (handoff), `border-l-danger-500` (Pix em revisão), `border-l-info-500` (modelo atendendo). O mapa completo termo de domínio para token vive em `docs/design/dominio-visual.md`.

## 6. Do's and Don'ts

### Do:
- **Do** começar cada tela operacional pelo estado do que está aberto agora (handoff pendente, Pix em revisão), antes de qualquer dashboard ou métrica.
- **Do** consumir cor pelo papel semântico (`surface`, `text-primary`, `border-brand`, `state-handoff`, `focus-ring`), nunca pelo tom bruto (`ink-500`, `gold-500`) em código de componente.
- **Do** parear todo background colorido com seu `on-` correspondente.
- **Do** preservar `gold-500` como cor exclusiva da ação canônica da tela e do item ativo da navegação.
- **Do** mostrar JID, ID e comando literal em `mono` com `text-muted`, nunca em sans nem em cor de destaque.
- **Do** confirmar destrutivos (registrar perdido, reverter Pix) com modal explícito que repete o estado atual e o proposto.
- **Do** tratar o escuro como canônico: ao decidir entre temas, resolva pelo escuro.
- **Do** usar a faixa de borda esquerda colorida apenas em **item de lista ou card vinculado a estado de negócio** (atendimento, Pix, agenda, handoff), sempre mapeada a um token semântico (`border-l-state-*`) — o `CardDestaque` é o caso-modelo. Essa é a única exceção sancionada à proibição geral de side-stripe; **nunca** use a faixa como acento decorativo em alerta, callout ou para marcar autoria (alerta de erro usa borda completa + tinte `bg-destructive/5`).
- **Do** ler o `CONTEXT.md` e o `docs/design/dominio-visual.md` antes de inventar nomenclatura ou cor para estado de negócio.

### Don't:
- **Don't** replicar a estética sensual/adulta do canal orgânico Elite Baby: o canal vende perfis, o painel coordena operação.
- **Don't** usar painel SaaS genérico com gradientes coloridos, hero-metrics, ou grid de cards idênticos (icon mais heading mais texto repetido).
- **Don't** mostrar foto de modelo em lista, sidebar ou hover; nem foto de portaria ou comprovante de Pix em preview automático. Sempre por clique deliberado, sempre com fundo neutro.
- **Don't** usar serifa (Cormorant) em texto operacional; é cerimonial.
- **Don't** usar vermelho ou âmbar fora do vocabulário de estado. Chamar atenção é trabalho do `gold-500`, não do `warn-500`.
- **Don't** introduzir um quarto dourado, um quinto cinza, um quinto hue semântico ou uma "cor de marca alternativa". A paleta é fechada.
- **Don't** usar elevação por sombra em card; a profundidade vem da superfície e do `ring`.
- **Don't** usar gradiente, glow, glass-morphism, ilustração ou ícone decorativo. Ícones só Lucide, stroke 1.5px, 16 ou 20px.
- **Don't** desenhar ação destrutiva como button-primary; "Marcar como perdido" é button-danger.
- **Don't** inventar versão mobile operacional; abaixo de 1024px é login mais blocker.
- **Don't** usar `#000000` ou `#FFFFFF` puros em superfície grande (halation): canvas é `ink-50`, texto é `ink-900`.
- **Don't** usar `danger-500` em chart categórico; vermelho semântico em chart faz ler "erro" onde não há.
- **Don't** depender só de cor para estado: badge sempre carrega o rótulo textual, não só a cor.
