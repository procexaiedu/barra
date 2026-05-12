# Componentes

Inventário das primitivas em `interface/src/components/ui/`. Tudo aqui usa o padrão **shadcn/ui data-slot** (atributo `data-slot` no root e nas partes nomeadas) e roda sobre `@base-ui/react` quando precisa de comportamento.

Componentes de domínio (`atendimentos/`, `pix/`, `agenda/`, etc.) **não** estão aqui — eles compõem estas primitivas. Se você se pegar reinventando uma primitiva dentro de pasta de domínio, pare: ou estenda a primitiva, ou crie uma nova em `components/ui/`.

## Inventário (`components/ui/`)

| Componente | Subpartes | Variantes | `data-slot` raiz |
|---|---|---|---|
| `Button` | — | `default`, `primary`, `outline`, `secondary`, `ghost`, `danger`, `destructive`, `link` | `button` |
| `Card` | `CardHeader`, `CardTitle`, `CardDescription`, `CardAction`, `CardContent`, `CardFooter` | `size`: `default`, `sm` | `card` |
| `Badge` | — | `active`, `paused`, `handoff`, `revisao`, `closed`, `lost` | `badge` |
| `Input` | — | — | `input` |
| `Textarea` | — | — | `textarea` |
| `Label` | — | — | `label` |
| `Dialog` | `DialogTrigger`, `DialogContent`, `DialogTitle`, `DialogDescription`, `DialogClose` | — | `dialog` |
| `AlertDialog` | `AlertDialogTrigger`, `AlertDialogContent`, `AlertDialogTitle`, `AlertDialogDescription`, `AlertDialogAction`, `AlertDialogCancel` | — | `alert-dialog` |
| `Sheet` | header/content/footer | side: `top`/`right`/`bottom`/`left` | `sheet` |
| `Tooltip` | `TooltipTrigger`, `TooltipContent`, `TooltipProvider` | — | `tooltip` |
| `Separator` | — | `horizontal`/`vertical` | `separator` |
| `Skeleton` | — | — | `skeleton` |
| `Sonner` (toaster) | — | — | (renderiza global em `app/layout.tsx`) |
| `ImageLightbox` | — | — | `image-lightbox` |

## Button

Tamanhos: `default` (h-8), `xs` (h-6), `sm` (h-7), `lg` (h-9), `icon` (size-8), `icon-xs/sm/lg`.

**Quando usar cada variante:**

| Variante | Quando |
|---|---|
| `default` / `primary` | **Uma por contexto.** Ação principal: "Confirmar devolução", "Salvar", "Criar modelo" |
| `outline` | Ações secundárias adjacentes à primária |
| `secondary` | Ação neutra dentro de toolbar/filtro |
| `ghost` | Ações de baixa ênfase, ícones em headers |
| `danger` | Ação destrutiva contextual (não-final) |
| `destructive` | Confirmação final de exclusão dentro de `AlertDialog` |
| `link` | Inline em texto — preferir `<Link>` do Next quando for navegação |

**Anti-padrões:**
- Dois botões `primary` lado a lado. Se houver "Salvar" e "Cancelar", o segundo é `outline`.
- Botão só-ícone sem `aria-label`. Use `size="icon-sm"` + `aria-label`.
- Botão dentro de `<a>` ou vice-versa. Use a prop `render` do `@base-ui/react` ou aplique `buttonVariants()` num `<Link>` direto.

## Card

Toda informação contida em superfície destacada usa `Card`. **Não inventar** `<div className="bg-card rounded-lg p-6">` — é o que `Card` já faz.

```tsx
<Card>
  <CardHeader>
    <CardTitle>Pix em revisão</CardTitle>
    <CardDescription>Validado em 23s</CardDescription>
    <CardAction>
      <Button variant="ghost" size="icon-sm" aria-label="Mais">…</Button>
    </CardAction>
  </CardHeader>
  <CardContent>…</CardContent>
  <CardFooter>…</CardFooter>
</Card>
```

`size="sm"` reduz padding (`py-3 px-3`) e título (`text-sm`). Use em listas densas; padrão para tile de dashboard.

`CardFooter` automaticamente recebe `bg-muted/50` + `border-t` + `rounded-b-xl`. Não tentar customizar — se precisa de footer diferente, é outro componente.

## Badge

**Pílula, não tag.** `rounded-full`, `text-xs`, `px-3 py-1`. Cor de fundo é sempre `ink-300`; **a cor muda só no texto**. Isso é proposital: badge não compete com KPI por atenção, só categoriza.

Variantes mapeiam direto a estados de domínio — ver [dominio.md](dominio.md) para o mapa completo.

## Dialog vs AlertDialog vs Sheet

| Use | Quando |
|---|---|
| `Dialog` | Formulário, visualização, edição. Tem `Close`. Não bloqueia ação destrutiva. |
| `AlertDialog` | Confirmação destrutiva ou irreversível ("Devolver para IA?", "Excluir bloqueio?"). Sem `X` de fechar — exige decisão. |
| `Sheet` | Painel lateral persistente para edição contextual (futuro — ainda não em uso massivo). |

**`max-w-md` é o tamanho padrão** observado para `AlertDialog` de confirmação. Para dialog de edição, `max-w-2xl` ou `max-w-3xl`. Não usar `max-w-full` — quebra a hierarquia.

## Tooltip

Sempre dentro de `TooltipProvider` (já no `app/layout.tsx`). Use para:
- Botão só-ícone (mesmo com `aria-label` — tooltip é affordance visual).
- Métrica abreviada cuja sigla não é óbvia (KPI do dashboard).
- `Info` icon (lucide) ao lado de label que precisa de explicação curta.

**Delay padrão**: `delay={400}` para nav (sidebar), default para resto. Não atrasar mais — operador vai sentir lag.

## Input / Textarea / Label

Sempre par `Label` + `Input`. Nunca placeholder como label.

```tsx
<div className="space-y-1.5">
  <Label htmlFor="valor">Valor final</Label>
  <Input id="valor" type="text" inputMode="decimal" placeholder="R$ 0,00" />
</div>
```

`Input` aceita `aria-invalid` para mostrar erro (anel vermelho automático). Use junto com mensagem `text-danger-500 text-xs` abaixo.

## Sonner (toast)

Importado em `app/layout.tsx` como `<Toaster position="bottom-right" theme="dark" richColors closeButton />`. Não recriar `<Toaster>` por página.

```tsx
import { toast } from "sonner"

toast.success("Atendimento #12 devolvido para a IA")
toast.error("Erro ao validar Pix")
```

**Toast é para confirmação de ação assíncrona, não para erro de validação de form** (esse é `aria-invalid` no campo).

## Skeleton

Use durante loading inicial de página/lista. Forma o esqueleto exato do conteúdo final (mesma altura, mesmas linhas). **Não usar spinner genérico em tela inteira** — quebra a sensação de velocidade.

## ImageLightbox

Visualização de Foto de portaria e Comprovante de Pix em tamanho grande. Não confundir com `Dialog` — é específico para imagem com zoom/pan.

## Quando criar componente novo em `components/ui/`

Critérios cumulativos (todos):

1. **Reuso real**: usado em ≥2 contextos de domínio diferentes (não "vai ser reusado um dia").
2. **Sem regra de domínio**: zero conhecimento de Pix, Atendimento, Modelo etc. Se o componente sabe o que é "ia_pausada_motivo", ele vai em `components/painel/` ou `components/atendimentos/`.
3. **data-slot aplicado**: root e cada subparte têm `data-slot="<nome>"`.
4. **Variantes via `cva`**: se houver >1 visual, usar `class-variance-authority`. Sem ternários espalhados pelo JSX.

Se algum critério falha, o componente nasce em pasta de domínio.

## Lucide icons

Tamanho padrão: `size={20} strokeWidth={1.5}` na sidebar e ícones de header. Em botões: `size={14}` a `size={16}` (o cva do botão já aplica `[&_svg:not([class*='size-'])]:size-4` por defeito). Em badges: `size={11}` a `size={14}`.

`strokeWidth={1.5}` é o padrão para ícone decorativo/informativo; `strokeWidth={2}` para indicadores fortes (tendência, alerta urgente).

**Sempre** `aria-hidden` quando o ícone é decoração ao lado de texto. **Nunca** `aria-hidden` quando o ícone é o único conteúdo do botão — aí precisa de `aria-label` no botão.
