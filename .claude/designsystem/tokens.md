# Tokens

Todos os tokens vivem em `interface/src/app/globals.css` e são expostos ao Tailwind via `@theme inline`. Esta página é a referência humana — o CSS é a fonte da verdade.

## Cor

### Escala neutra (`ink-*`)

Base estrutural. Fundos, bordas, texto, divisores. **Nunca** usar `gray-*`, `zinc-*` ou outros utilitários Tailwind crus.

| Token | Hex | Uso típico |
|---|---|---|
| `ink-0` | `#000000` | Overlay de modal (`bg-ink-0/85`), texto inverso |
| `ink-50` | `#0A0A0A` | `--surface` — fundo principal da página |
| `ink-100` | `#141414` | `--surface-raised` — `Card`, `Popover`, `Dialog` |
| `ink-200` | `#1F1F1F` | `--surface-hover` — hover de card/menu item ativo de sidebar |
| `ink-300` | `#2A2A2A` | `--surface-pressed` — active/pressed; também fundo de `Badge` |
| `ink-400` | `#3D3D3D` | `--border-strong` — borda enfática, scrollbar |
| `ink-500` | `#5C5C5C` | `--text-disabled`, scrollbar hover |
| `ink-600` | `#8B8B8B` | `--text-muted` — placeholder, label secundário |
| `ink-700` | `#B4B4B4` | `--text-secondary` — corpo de texto não-primário |
| `ink-800` | `#DEDEDE` | Texto em superfície clara (raro) |
| `ink-900` | `#F5F5F5` | `--text-primary` — todo texto principal |

### Marca (`gold-*`)

Identidade Barra Vips. **Restrita a:** logotipo, primary action, item ativo de navegação, ênfase intencional, ponto de marca em ranking/chart. **Não decorar** — gold em excesso vira ruído.

| Token | Hex | Uso |
|---|---|---|
| `gold-300` | `#8C7848` | Ponto baixo de escala sequencial |
| `gold-500` | `#C4A961` | `--primary`, `--text-brand`, `--border-brand`, ativo de sidebar |
| `gold-700` | `#E6CB7A` | `--text-link`, `--focus-ring` (anel de foco no tema) |

### Estado semântico

Sempre por significado, nunca por estética. Trocar `danger-500` por `warn-500` muda a mensagem que o operador lê.

| Token | Hex | Significado | Onde aparece |
|---|---|---|---|
| `success-500` | `#1FB07A` | Concluído com sucesso, tendência positiva | `--state-closed`, fechamento, delta positivo |
| `warn-500` | `#F4B81C` | Atenção, ação humana esperada | `--state-handoff`, badge Handoff, urgência média (>30min) |
| `danger-500` | `#D62828` | Erro, perda, urgência crítica | `--state-lost`, Pix em revisão, urgência alta (>2h), delta negativo |
| `info-500` | `#4F8FE1` | Informativo, neutro acionável | `--state-info`, `modelo_em_atendimento` |

### Estado de atendimento (alias semânticos)

Camada acima do estado genérico — vincula direto ao vocabulário do CONTEXT.md.

| Token | Resolve | Termo de domínio |
|---|---|---|
| `state-active` | `gold-500` | Ativo / Em execução |
| `state-paused` | `ink-600` | IA pausada genérico |
| `state-handoff` | `warn-500` | Handoff aguardando humano |
| `state-closed` | `success-500` | Registro de resultado fechado |
| `state-lost` | `danger-500` | Registro de resultado perdido |
| `state-info` | `info-500` | Modelo em atendimento |

### Superfícies & texto (alias)

Use estes em vez de `ink-*` direto sempre que houver alias semântico — facilita repaint global.

| Token | Resolve | Uso |
|---|---|---|
| `surface` | `ink-50` | Fundo de página |
| `surface-raised` | `ink-100` | Card, popover, dialog, input |
| `surface-hover` | `ink-200` | Hover interativo |
| `surface-pressed` | `ink-300` | Pressed/active |
| `border-subtle` | `ink-300` | Borda padrão |
| `border-strong` | `ink-400` | Borda enfática |
| `border-brand` | `gold-500` | Borda de destaque (raro) |
| `text-primary` | `ink-900` | Texto principal |
| `text-secondary` | `ink-700` | Texto secundário |
| `text-muted` | `ink-600` | Label, placeholder, metadado |
| `text-disabled` | `ink-500` | Desabilitado |
| `text-brand` | `gold-500` | Marca |
| `text-link` | `gold-700` | Link |
| `focus-ring` | `gold-700` | Anel de foco |

### Charts & sequências

Para gráficos do dashboard.

- **Categóricas (`chart-1..7`)**: cores distintas e estáveis para séries discretas.
- **Sequenciais (`seq-1..5`)**: gradiente gold do escuro ao claro para "quanto mais, mais gold".
- **Divergentes (`div-low/low-2/mid/high-2/high`)**: vermelho ↔ neutro ↔ verde para perda/ganho.

Ver hexes em `globals.css` linhas 176-194. Cor de chart **não** se inventa em componente — sempre token.

## Tipografia

Três famílias carregadas via `next/font/google` em `app/layout.tsx`:

| Família | Variável | Uso |
|---|---|---|
| **Inter** | `--font-sans` / `--font-heading` | Texto, números, UI inteira |
| **Cormorant Garamond** | `--font-serif` | **Exclusivo do logotipo "Barra Vips"** na sidebar. Não usar em outro lugar. |
| **JetBrains Mono** | `--font-mono` | IDs, telefones, valores tabulares, timestamps relativos |

### Escala em uso

Estes são os tamanhos efetivamente aplicados — não improvise outros sem justificativa.

| Tamanho | Linha | Tracking | Aplicação |
|---|---|---|---|
| `text-[11px]` | `leading-tight` | — | Tendência (delta), metadado de rodapé |
| `text-xs` (12px) | — | `tracking-[0.08em]` quando `uppercase` | Label de tile, badge, metadado |
| `text-[13px]` | — | — | Conteúdo denso de card (motivo, próxima ação) |
| `text-sm` (14px) | — | — | Corpo padrão, item de lista, input |
| `text-base` (16px) | — | — | Título de card, item destacado |
| `text-lg` (18px) | — | — | Título de dialog |
| `text-[28px]` | — | — | Logotipo Barra Vips (Cormorant 500) |
| `text-[36px]` | `leading-[44px]` | `tracking-[-0.02em]` | KPI grande (`TileMetrica`) |
| `text-[40px]` | `leading-[48px]` | — | KPI dashboard (`TileKpi`), com `tabular-nums` |

### Peso

`font-medium` (500) e `font-semibold` (600) são os únicos pesos em uso. **Não usar `font-bold`** — quebra a hierarquia visual estabelecida.

### Tabular-nums

Sempre que houver número em tile, ranking, valor monetário ou contador, aplicar `tabular-nums`. Sem isso os dígitos pulam ao atualizar.

## Espaçamento

Tailwind defaults (4px scale). Padrões observados:

| Contexto | Padding | Gap |
|---|---|---|
| Página (`<main>`) | `p-8` | — |
| Card padrão | `p-4` a `p-6` | `gap-3` a `gap-4` |
| Card compacto (`data-size="sm"`) | `p-3` | `gap-3` |
| Card de tile | `p-5` a `p-6` | `gap-3` |
| Item de lista (sidebar) | `px-3 py-2` | `gap-3` |
| Botão `default` | `h-8 px-2.5 gap-1.5` | — |
| Botão `sm` | `h-7 px-2.5 gap-1` | — |
| Botão `xs` | `h-6 px-2 gap-1` | — |
| Input | `h-8 px-2.5 py-1` | — |

## Raio

Mapeados a `--radius: 0.5rem` via `@theme`:

| Classe | Cálculo | Uso |
|---|---|---|
| `rounded-sm` | `0.25rem` | Indicadores, dots |
| `rounded-md` | `0.5rem` | Botão padrão, item de nav, input |
| `rounded-lg` | `0.75rem` | Card pequeno, tile |
| `rounded-xl` | `1rem` | Card grande |
| `rounded-full` | — | Avatar, badge pílula |

## Foco

**Regra dura**: todo elemento interativo precisa de `focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none`. Quando dentro de superfície escura, adicionar `focus-visible:ring-offset-2`.

`--ring` resolve para `focus-ring` → `gold-700`. Não trocar por outro tom.

## Sombras

Não há tokens de `box-shadow`. Hierarquia vem de:
- `ring-1 ring-foreground/10` para card (`Card` aplica direto).
- `border` com `border-subtle` ou `border-strong` para divisores.
- `surface-hover` / `surface-pressed` para estados interativos.

**Não introduzir sombras sem decisão arquitetural** — quebra a estética flat-dark estabelecida.

## Animação

Curtas (100-300ms), ease-out, sem bounce.

- `transition-colors` — padrão para hover/active de cor.
- `transition-[width] duration-200 ease-in-out` — collapse de sidebar.
- `duration-100 data-open:animate-in data-open:fade-in-0 data-closed:animate-out` — overlay de dialog.
- `.tile-update-flash` — `tile-update-flash 0.7s ease-out` (keyframe em `globals.css:261`) para indicar atualização de KPI em tempo real.

## Scrollbar

Apenas via `.scroll-thin` (utility em `globals.css:241-258`): `width: 4px`, thumb `ink-400`, hover `ink-500`. Aplicar em listas internas de cards/dialogs. Página inteira mantém scrollbar nativa.
