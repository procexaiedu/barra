# Padrões de composição

Como montar tela, página e componente respeitando tokens e primitivas. Referência para revisar diff de UI.

## Estrutura de página

Toda rota em `app/(interface)/<contexto>/` segue:

```tsx
"use client" // quando precisar de estado/efeito

import { HeaderPagina } from "@/components/<contexto>/HeaderPagina"
import { ToolbarPagina } from "@/components/<contexto>/ToolbarPagina"
import { Conteudo } from "@/components/<contexto>/Conteudo"

export default function Page() {
  return (
    <div className="space-y-6">
      <HeaderPagina />
      <ToolbarPagina />
      <Conteudo />
    </div>
  )
}
```

- **`<main>` já tem `p-8` e `overflow-y-auto`** (vem de `(interface)/layout.tsx`). Não duplicar padding na página.
- **Header** sempre primeiro, com título e ações globais (criar/atualizar). Pattern: `HeaderAgenda`, `HeaderModelos`, `HeaderDashboard`.
- **Toolbar** abaixo, com filtros, busca, range de período.
- **Conteúdo** ocupa o resto. `space-y-6` separa as três faixas.

## Padrão data-slot

Toda primitiva ou componente reusável recebe `data-slot` no root. Subpartes nomeadas também. Isso permite:
- Selecionar via CSS `[data-slot="card-header"]` em estilos globais.
- Identificar slots em devtools.
- `has-data-[slot=card-footer]:pb-0` — composição condicional do pai (padrão real em `card.tsx:15`).

```tsx
function Componente({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="componente"
      className={cn("classes-base", className)}
      {...props}
    />
  )
}
```

**Anti-padrão**: criar componente novo em `components/ui/` sem `data-slot`. Reprovação automática em revisão.

## Variantes via `cva`, não props boolean

**Errado:**
```tsx
<Button isPrimary isLarge isDanger isOutline /> // prop boolean proliferation
```

**Certo:**
```tsx
<Button variant="primary" size="lg" />
```

Quando 2+ booleans se acumulam controlando aparência, refatore para `variant` único via `cva`. Booleans só sobrevivem quando representam estado independente do visual (`disabled`, `loading`).

## Composição compound

Para componente com partes nomeadas (`Card`, `Dialog`), siga o padrão exportação plana:

```tsx
export { Card, CardHeader, CardTitle, CardDescription, CardAction, CardContent, CardFooter }
```

**Não** exportar como namespace (`Card.Header`). O Tailwind v4 + data-slot funciona melhor com export plano.

## Layout interno de card

Padrão observado em `CardDestaque`, `TileMetrica`, `TileKpi`:

1. **Indicador de estado** (borda esquerda colorida ou badge no topo) — máx 1.
2. **Identidade** — nome, número, ícone.
3. **Conteúdo principal** — KPI grande, motivo, próxima ação.
4. **Rodapé com metadado** — timestamp relativo, autor, range comparativo.

Tudo separado por `border-t border-border pt-3` quando há rodapé.

## Estados de tela

Toda lista/conteúdo precisa de **4 estados**:

| Estado | Conteúdo |
|---|---|
| **Loading** | `Skeleton` no formato exato do conteúdo final. Sem spinner centralizado. |
| **Empty** | Texto curto explicando + CTA quando aplicável. Ex: "Nenhum Pix em revisão. Tudo certo por aqui." |
| **Error** | `BannerErro` (`components/layout/BannerErro.tsx`) no topo + lista vazia. Não toast — erro de carregamento merece banner persistente. |
| **Conteúdo** | O caminho feliz. |

**Não esquecer:** loading e empty têm aparência distinta. Empty é texto, loading é skeleton. Misturar ("Carregando…" no centro) é anti-padrão.

## Atualização em tempo real

Quando KPI/tile atualiza por websocket/poll, aplicar `tile-update-flash` (keyframe em `globals.css:261`):

```tsx
<Card className={cn("base", flashing && "tile-update-flash")} />
```

Flash dura 700ms, suficiente para o operador notar sem atrapalhar leitura. Padrão em `TileMetrica` e `CardDestaque`.

## Listas

| Tipo | Estrutura |
|---|---|
| Itens densos (Pix, Atendimentos) | `Card size="sm"` em `<div className="space-y-2">` |
| Cards horizontais (KPI dashboard) | Grid `grid grid-cols-N gap-4` |
| Tabela | Não há `Table` primitivo. Construir com `<dl>` / `<ul>` semântico + flex. Evitar `<table>` se não for dado verdadeiramente tabular. |

## Modal de confirmação

Padrão de `CardDestaque` para qualquer ação destrutiva/irreversível:

```tsx
<AlertDialog open={dialogOpen} onOpenChange={setDialogOpen}>
  <AlertDialogContent className="max-w-md bg-card">
    <AlertDialogHeader>
      <AlertDialogTitle>Devolver #12 para a IA?</AlertDialogTitle>
      <AlertDialogDescription>A IA volta a responder o cliente na próxima mensagem.</AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogCancel disabled={loading}>Cancelar</AlertDialogCancel>
      <AlertDialogAction onClick={handleAcao} disabled={loading}>
        {loading ? "Devolvendo…" : "Confirmar devolução"}
      </AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

Regras:
- `max-w-md` + `bg-card`.
- Título termina com `?` quando é confirmação.
- Descrição em 1 frase. Sem listas.
- Botão de ação tem estado de loading com texto trocado (`"Devolvendo…"`), não spinner ao lado.
- Disabilitar ambos botões durante loading.

## Filtros de toolbar

Todo filtro em barra de toolbar (`Toolbar*.tsx` ou inline na página) segue o mesmo padrão visual: rótulo curto **visível** acima do controle, empilhado.

```tsx
<label className="flex flex-col gap-1">
  <span className="text-xs font-medium text-text-muted">{rotulo}</span>
  <Select ... />
  // ou <Input ... />
</label>
```

Regras:
- Rótulo sempre **visível** — nunca `sr-only`, inclusive sobre o campo de busca (use `"Buscar"`).
- Classe canônica do rótulo: `text-xs font-medium text-text-muted`. **Não** usar `uppercase`, `tracking-[0.08em]`, `font-semibold`, `text-[11px]` nem `text-sm`.
- `flex flex-col gap-1` para empilhar rótulo + controle.
- `<label>` envolve o controle (semântica nativa) ou usa `<label htmlFor>`.
- `aria-label` no select pode ser dispensado quando o `<label>` já cobre.

Exceção — grupo de botões-preset (`role="group"`):

Quando o controle é um conjunto de botões (`FiltroPeriodo` do dashboard), o group em si carrega `role="group" aria-label="Período"`; quando posto numa toolbar com outros filtros rotulados, envolva em wrapper para alinhar visualmente:

```tsx
<div className="flex flex-col gap-1">
  <span className="text-xs font-medium text-text-muted">Período</span>
  <FiltroPeriodo ... />
</div>
```

Nomenclatura cross-módulo:
- Filtro por modelo da agência sempre se chama **"Modelo"**.
- Filtro de janela de tempo sempre se chama **"Período"**. Exceção semântica: em Atendimentos, o filtro de urgência se chama **"Quando"** (não é janela de tempo).

## Acessibilidade

**Mínimos:**
- Todo botão só-ícone: `aria-label`.
- Todo input: `<Label htmlFor>` (ou `aria-label` em busca/filtro inline).
- Card clicável: `role="link"` ou `role="button"`, `tabIndex={0}`, `onKeyDown` para `Enter`/` ` (espaço). Pattern em `CardDestaque:88-89` e `TileMetrica:66-68`.
- `aria-hidden` em ícone decorativo ao lado de texto.
- Toolist/Tooltip só dentro de `TooltipProvider`.
- `<nav aria-label="Navegação principal">` (pattern da `Sidebar`).
- Skip-link: ausente hoje, não introduzir sem decisão.

**Foco visível:** `focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none`. Em superfície com fundo próximo do ring, adicionar `focus-visible:ring-offset-2`.

## Formatação de dados

Use `interface/src/lib/formatters.ts` para tudo que é cross-componente:

| Função | Uso |
|---|---|
| `formatTempoRelativo(iso)` | "há 12 min", "há 2 h" — timestamp humano em rodapé |
| `formatTelefone(e164)` | "(11) 99999-9999" |
| `formatMoeda(centavos)` | "R$ 1.250,00" |
| `formatData(iso)` | "12/05/2026" |

**Não** chamar `Intl.NumberFormat` direto no componente. Centralizar evita inconsistência ("R$1.250,00" vs "R$ 1.250,00").

## Direção: ícone antes ou depois?

| Padrão | Quando |
|---|---|
| Ícone + texto | Affordance (`<Plus> Criar modelo`, `<LogOut> Sair`) |
| Texto + ícone | Indicador de continuação (`Ver mais <ArrowRight>`), trend (`+12% <TrendingUp>`) |

Gap: `gap-1` a `gap-2` dependendo do tamanho.

## Cores que **não** se inventam

Reprovação automática se aparecer no diff:
- `bg-red-*`, `text-red-*` → use `bg-danger-500`, `text-danger-500`.
- `bg-yellow-*` → `bg-warn-500`.
- `bg-green-*` → `bg-success-500`.
- `bg-blue-*` → `bg-info-500`.
- `bg-gray-*`, `text-gray-*`, `bg-zinc-*` → `text-text-muted`, `bg-ink-200`, etc.
- Hex inline (`#XXXXXX`) → adicione token primeiro em `globals.css`.

## Mobile

A `interface/` é **desktop-only**. `MobileBlocker` cobre telas < `lg` (1024 px). **Não** escrever `sm:` / `md:` adaptive — tudo é desktop. Use apenas `max-lg:hidden` para esconder elementos abaixo do breakpoint quando necessário.
