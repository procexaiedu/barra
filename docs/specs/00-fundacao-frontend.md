# 00 — Fundação Frontend Barra Vips

> **Constituição do painel.** Decisões transversais que valem para **todas as telas** do `interface/`. Não repetir essas decisões em specs de tela individuais — apenas referenciar este documento.
>
> **Status:** alpha (P0). Mudanças aqui afetam todas as telas; tratar como ADR — substituir entrada com `superseded` em vez de apagar.
>
> **Última atualização:** 2026-04-30.

---

## Como usar este documento

### Ao especificar uma nova tela

1. Cabeçalho da spec da tela referencia: *"Herda decisões de `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto explícito."*
2. A spec da tela cobre **apenas o que é específico**: rota, blocos próprios, ações de escrita, regras de negócio da tela, contratos de API próprios, critérios de aceite que extrapolam o que está aqui.
3. Quando a spec precisar quebrar uma decisão da fundação, **declarar explicitamente em "Vetos locais"** com justificativa.

### Ao codificar uma tela

1. Ler esta fundação primeiro.
2. Ler a spec da tela.
3. Implementar apenas o que está na spec da tela; o ferramental compartilhado (cliente Supabase, fontes, sidebar, middleware, formatadores, etc.) é responsabilidade desta fundação e existe só uma vez.

### Ordem de leitura para o agente codificador (sempre)

1. `CLAUDE.md` (raiz) — princípios.
2. `CONTEXT.md` (raiz) — vocabulário de domínio.
3. `DESIGN.md` (raiz) — identidade visual.
4. **Este arquivo** (`docs/specs/00-fundacao-frontend.md`).
5. A spec específica da tela.
6. `docs/mvp/06-dados-interfaces.md` — se a tela referenciar entidades.
7. `interface/AGENTS.md` — aviso sobre Next.js 16 ter quebras vs. treinamento.

---

## 1. Identidade e princípios

- **Produto:** painel operacional Barra Vips (interno, ferramenta de trabalho de Fernando).
- **Não é** o canal orgânico (BarraVips.com). Sem replicar estética sensual/adulta no painel.
- **Princípios** (DESIGN.md §Princípios — resumo):
  1. Decisão acima de tudo. Próxima ação é o elemento mais brilhante da tela.
  2. Estado é a unidade visual — badge antes de conteúdo, borda esquerda comunica antes do texto.
  3. Dourado é assinatura, não ruído.
  4. Vermelho e amarelo são vocabulário escasso (só estado).
  5. Conteúdo sensível fora do painel.
  6. Tipografia operacional, ornamento contido.
  7. **Modo escuro é o único modo.**
- **Vocabulário de domínio:** usar **exatamente** os termos do `CONTEXT.md` (Conversa cliente, Coordenação por modelo, Handoff, Devolução para IA, Pix de deslocamento, Aviso de saída, Foto de portaria, Registro de resultado, Valor final, Motivo de perda). Proibido inventar nomenclatura.

---

## 2. Stack canônica

| Camada | Escolha pinada |
|---|---|
| Framework | Next.js 16.2 (App Router, Turbopack default) |
| UI | React 19.2 + TypeScript 5 |
| CSS | Tailwind v4.2 (`@theme inline`) |
| Componentes | shadcn/ui (style `base-nova`, baseColor `neutral`, data-slot pattern) |
| Ícones | Lucide (1.5px stroke, 16px ou 20px) |
| Fontes | `next/font/google` — Cormorant Garamond, Inter, JetBrains Mono |
| Auth | Supabase Auth + `@supabase/ssr` (cookies) |
| Realtime | Supabase Realtime (Postgres Changes via `@supabase/supabase-js`) |
| API REST | FastAPI no `api/` (consumida via `fetch` no client) |
| Toasts | `sonner` (shadcn) |
| Gerenciador | pnpm |

> **Nunca** trocar shadcn por outro headless lib; nunca trocar Lucide por outro icon set; nunca usar Pages Router.

### Arquivo de checagem rápida

`interface/package.json` deve listar:
- `next@16.2.x`
- `react@19.2.x` / `react-dom@19.2.x`
- `@supabase/supabase-js`, `@supabase/ssr`
- `tailwindcss@4`, `@tailwindcss/postcss@4`
- `shadcn` (CLI), `class-variance-authority`, `clsx`, `tailwind-merge`, `tw-animate-css`
- `lucide-react`
- `sonner`

---

## 3. Estrutura de arquivos canônica

```
interface/
├── src/
│   ├── app/
│   │   ├── layout.tsx              # root: html dark + fontes + Toaster
│   │   ├── globals.css             # tokens DESIGN.md
│   │   ├── (auth)/
│   │   │   └── login/page.tsx      # form de login
│   │   └── (interface)/            # área autenticada
│   │       ├── layout.tsx          # shell de 2 colunas com <Sidebar/>
│   │       ├── page.tsx            # / = Painel Geral
│   │       ├── atendimentos/
│   │       ├── agenda/
│   │       ├── crm/
│   │       ├── modelos/
│   │       ├── pix/
│   │       └── dashboard/
│   ├── components/
│   │   ├── ui/                     # primitives shadcn
│   │   ├── layout/                 # Sidebar, MobileBlocker, BannerErro
│   │   └── <feature>/              # componentes específicos por tela
│   ├── lib/
│   │   ├── supabase.ts             # cliente Supabase singleton
│   │   ├── api.ts                  # fetcher tipado
│   │   ├── realtime.ts             # helper para subscriptions + debouncedRefetch
│   │   ├── formatters.ts           # telefone, data, moeda, tempo relativo
│   │   └── utils.ts                # cn (shadcn)
│   ├── hooks/
│   │   └── use<Feature>.ts         # 1 hook por tela quando a tela tem fetch+realtime
│   ├── tipos/                      # tipos compartilhados; futuro = gerados do OpenAPI
│   │   └── <feature>.ts
│   └── middleware.ts               # auth guard
├── components.json                 # shadcn config (já existe)
├── package.json
└── .env.example
```

### Convenções de nomenclatura

- **Domínio em PT-BR:** `tipos/painel.ts`, `components/painel/CardDestaque.tsx`, `hooks/usePainelResumo.ts`, `Conversa`, `DirecaoMensagem`, `MotivoPerda`.
- **Infra/utilitários em EN:** `lib/api.ts`, `lib/supabase.ts`, `lib/utils.ts`, `app/layout.tsx`, `middleware.ts`.
- **Componentes em PascalCase**, hooks `useCamelCase`, módulos em camelCase.
- **Sem `index.ts` re-exports** dentro de subpastas (regra `CLAUDE.md` — sem abstração especulativa).

---

## 4. Tema e tokens (DESIGN.md aplicado)

### 4.1 Forçar dark-mode único

Em `app/layout.tsx`:

```tsx
<html lang="pt-BR" className={`dark ${cormorant.variable} ${inter.variable} ${jetbrains.variable}`}>
```

Sem toggle, sem `prefers-color-scheme`, sem variante light. **Painel é dark-only por escolha** (DESIGN.md princípio 7).

### 4.2 Fontes — `next/font/google` no root layout

```tsx
import { Cormorant_Garamond, Inter, JetBrains_Mono } from 'next/font/google';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });
const cormorant = Cormorant_Garamond({
  subsets: ['latin'], weight: ['500'], variable: '--font-cormorant', display: 'swap'
});
const jetbrains = JetBrains_Mono({
  subsets: ['latin'], weight: ['500'], variable: '--font-mono', display: 'swap'
});
```

`globals.css` mapeia:

```css
@theme inline {
  --font-sans: var(--font-inter);
  --font-heading: var(--font-cormorant);
  --font-mono: var(--font-mono);
}
```

**Uso:** Cormorant **só** no logo da sidebar e em títulos de página principal (`display-lg`/`display-xl`). Tudo o mais é Inter. Mono apenas em JIDs, IDs, comandos literais.

### 4.3 Paleta `globals.css` (substitui o default neutro do shadcn)

```css
:root {
  /* tinta */
  --ink-0: #000000;
  --ink-50: #0A0A0A;
  --ink-100: #141414;
  --ink-200: #1F1F1F;
  --ink-300: #2A2A2A;
  --ink-400: #3D3D3D;
  --ink-500: #5C5C5C;
  --ink-600: #8B8B8B;
  --ink-700: #B4B4B4;
  --ink-800: #DEDEDE;
  --ink-900: #F5F5F5;

  /* dourado */
  --gold-300: #8C7848;
  --gold-500: #C4A961;
  --gold-700: #E6CB7A;

  /* estados */
  --warn-500: #F4B81C;
  --danger-500: #D62828;
  --success-500: #1FB07A;
  --info-500: #4F8FE1;

  /* roles semânticos — únicos consumidos por componentes */
  --background: var(--ink-50);
  --foreground: var(--ink-900);
  --card: var(--ink-100);
  --card-foreground: var(--ink-900);
  --popover: var(--ink-100);
  --popover-foreground: var(--ink-900);
  --primary: var(--gold-500);
  --primary-foreground: var(--ink-0);
  --secondary: var(--ink-200);
  --secondary-foreground: var(--ink-900);
  --muted: var(--ink-200);
  --muted-foreground: var(--ink-600);
  --accent: var(--ink-200);
  --accent-foreground: var(--ink-900);
  --destructive: var(--danger-500);
  --destructive-foreground: var(--ink-900);
  --border: var(--ink-300);
  --input: var(--ink-100);
  --ring: var(--gold-700);

  --text-primary: var(--ink-900);
  --text-secondary: var(--ink-700);
  --text-muted: var(--ink-600);
  --text-brand: var(--gold-500);
  --focus-ring: var(--gold-700);

  --state-handoff: var(--warn-500);
  --state-lost: var(--danger-500);
  --state-closed: var(--success-500);
  --state-active: var(--gold-500);
  --state-paused: var(--ink-600);
}
```

**Componentes consomem apenas roles semânticos** (`--background`, `--card`, `--state-handoff`, etc.). Nunca `--ink-500` direto em código de componente.

### 4.4 Espaçamento, raio e densidade

- Base 4px. Escala `0..8` (`0,1,2,3,4,5,6,7,8` = `0,4,8,12,16,24,32,48,64`).
- Raio: `none|sm(4)|md(8)|lg(12)|xl(16)|pill(9999)`. Botões nunca pill; pill só em badge/chip.
- Densidade: linhas de tabela 44px; cards de decisão `padding: spacing.5`; áreas cerimoniais `spacing.6–7`.

### 4.5 Variantes shadcn obrigatórias

#### `button` (sobrescrever `interface/src/components/ui/button.tsx`)

| Variante | bg | fg | typography | uso |
|---|---|---|---|---|
| `primary` | `--gold-500` (hover `--gold-700`) | `--ink-0` | heading-md | ação canônica única |
| `secondary` | `--ink-200` (hover `--ink-300`) | `--ink-900` | heading-md | secundárias |
| `ghost` | transparente (hover `--ink-200`) | `--ink-700` (hover `--ink-900`) | body-md | terciárias / menu inline |
| `danger` | `--ink-200` | `--danger-500` | heading-md | destrutiva (Marcar perdido, Reverter Pix) |

Foco sempre `--ring` 2px offset 2px. **Nunca remover focus ring em override.**

#### `badge` (variantes)

| Variante | fg | bg | label | uso |
|---|---|---|---|---|
| `active` | `--gold-500` | `--ink-300` | "Ativa" | IA conduzindo |
| `paused` | `--ink-600` | `--ink-300` | "Pausada" | IA pausa neutra |
| `handoff` | `--warn-500` | `--ink-300` | "Em handoff" | aguarda decisão humana |
| `revisao` | `--warn-500` | `--ink-300` | "Em revisão" | Pix em revisão |
| `closed` | `--success-500` | `--ink-300` | "Fechado" | atendimento fechado |
| `lost` | `--danger-500` | `--ink-300` | "Perdido" | atendimento perdido |

Todas pill (`rounded-full`), `caption` (12px peso 500), `padding: spacing.1 spacing.3`. **Vocabulário fechado; não inventar variante nova.**

### 4.6 Cards de decisão — borda esquerda colorida

```css
border-left: 3px solid <token>;
```

| Token | Significado |
|---|---|
| `--gold-500` | atendimento ativo conduzido pela IA |
| `--warn-500` | em handoff, Pix em revisão, modelo expirado |
| `--success-500` | fechado |
| `--danger-500` | perdido, erro de comando |

Resto do card permanece monocromático (`--card` = `--ink-100`).

---

## 5. Layout shell e responsividade

### 5.1 Shell de 2 colunas

`app/(interface)/layout.tsx`:

```
+-----------------+--------------------------------------------------+
| <Sidebar/> 240px|  <main> max-width 1280px com respiro lateral     |
| --background    |  --background                                     |
+-----------------+--------------------------------------------------+
```

- Sidebar fixa esquerda, fundo `--background` (ink-50), borda direita `1px var(--border)`.
- Conteúdo `padding: spacing.6` (32px) topo/laterais.
- Largura útil cap em 1280px; passou disso, ganha respiro lateral.

### 5.2 Breakpoints

| Breakpoint | Mín | Comportamento |
|---|---|---|
| `sm` | 640px | apenas tela de login |
| `md` | 768px | tablet — sidebar colapsa em rail 64px (só ícones, label vira tooltip) |
| `lg` | 1024px | mínimo desejado para operação |
| `xl` | 1280px | layout canônico |
| `2xl` | 1536px | respiro lateral, sem alargar conteúdo |

### 5.3 Mobile blocker (<lg, exceto `/login`)

Quando `viewport < 1024px` em qualquer rota de `(interface)/*`:

- Esconde sidebar e conteúdo.
- Mostra `<MobileBlocker/>`: container fullscreen `--background`, conteúdo centralizado vertical+horizontal:
  - Logo "Barra Vips" em Cormorant Garamond `--gold-500` (`display-lg`).
  - Texto em Inter body-md `--text-primary`: *"Painel operacional disponível apenas em desktop. Use o grupo de Coordenação por modelo no celular."*
  - Sem botão, sem CTA. Só a mensagem.
- `/login` é **exceção**: funciona normalmente em mobile.

### 5.4 Sidebar (compartilhada)

Componente: `interface/src/components/layout/Sidebar.tsx`. Largura 240px (rail 64px em md).

- **Topo:** logo "Barra Vips" em Cormorant Garamond peso 500, `--gold-500`, ~32px. Padding `spacing.5` em todos lados.
- **Grupos** (header `heading-sm` maiúsculo `letter-spacing 0.08em` `--text-muted`):

| Grupo | Itens | Rota |
|---|---|---|
| OPERAÇÃO | Painel | `/` |
|  | Atendimentos | `/atendimentos` |
|  | Agenda | `/agenda` |
|  | Pix | `/pix` |
| CADASTROS | CRM | `/crm` |
|  | Modelos | `/modelos` |
| ANÁLISE | Dashboard | `/dashboard` |

- **Ícones Lucide:** `LayoutDashboard`, `MessagesSquare`, `Calendar`, `Receipt`, `Users`, `IdCard`, `ChartLine`. Stroke 1.5px, 20px.
- **Item:** altura 40px, padding `spacing.2 spacing.3`, gap `spacing.3`.
  - Repouso: `--text-secondary` ícone+label.
  - Hover: bg `--ink-200`, `--text-primary`.
  - **Ativo (rota corrente, via `usePathname()`):** bg `--ink-200`, label e ícone em `--gold-500`, `rounded.md`.
  - Foco: ring `--ring` 2px offset 2px.
- **Rodapé** (fixo bottom, separado por `1px var(--border)`):
  - Email do usuário em `caption --text-muted`, truncado.
  - Item "Sair" (`LogOut` 16px + label `body-md`) — mesmo estilo de item de nav. Click → `await supabase.auth.signOut()` → `router.push('/login')`.
- **Em md (rail 64px):** mostra apenas ícones; label aparece em `<Tooltip side="right">`.

> Sidebar é renderizada uma vez no `(interface)/layout.tsx` e compartilhada por todas as telas autenticadas. **Nunca duplicar Sidebar dentro de uma tela.**

---

## 6. Auth e sessão

### 6.1 Middleware (auth guard)

Arquivo: `interface/src/middleware.ts`.

```ts
import { type NextRequest, NextResponse } from 'next/server';
import { createServerClient } from '@supabase/ssr';

export async function middleware(req: NextRequest) {
  const res = NextResponse.next();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => req.cookies.getAll(),
        setAll: (toSet) => toSet.forEach(({ name, value, options }) =>
          res.cookies.set({ name, value, ...options })
        ),
      },
    }
  );
  const { data: { user } } = await supabase.auth.getUser();
  const url = req.nextUrl;
  const isLogin = url.pathname.startsWith('/login');

  if (!user && !isLogin) return NextResponse.redirect(new URL('/login', req.url));
  if (user && isLogin) return NextResponse.redirect(new URL('/', req.url));
  return res;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|svg)$).*)'],
};
```

### 6.2 Cliente Supabase (`src/lib/supabase.ts`)

```ts
import { createClient } from '@supabase/supabase-js';

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  { realtime: { params: { eventsPerSecond: 10 } } }
);
```

> Substituir o stub atual `export const supabase = null` na primeira tela que precisar.

### 6.3 Refresh JWT sem derrubar Realtime

Em qualquer tela que mantenha subscriptions Realtime, registrar **uma única vez** no mount:

```ts
const { data: sub } = supabase.auth.onAuthStateChange((evt, session) => {
  if ((evt === 'TOKEN_REFRESHED' || evt === 'SIGNED_IN') && session) {
    supabase.realtime.setAuth(session.access_token);
  }
  if (evt === 'SIGNED_OUT') router.replace('/login');
});
return () => sub.subscription.unsubscribe();
```

- **Não** fechar/reabrir channels em `TOKEN_REFRESHED`. `setAuth` substitui o token na conexão WS existente.
- O middleware (§6.1) cobre redirecionamento ao próximo navigate.

### 6.4 Erro 401 em chamadas REST

Padrão único: `supabase.auth.signOut()` + toast `error` "Sessão expirada. Faça login novamente." + `router.push('/login')`. Implementado uma vez em `lib/api.ts` (§7).

### 6.5 Autorização (papel)

P0 só tem Fernando (`usuarios.papel='fernando'`). **Sem checagem de papel no front no P0.** Backend valida via RLS + check explícito; front confia. Quando entrar `vendedor_read_only` (P1), reabrir esta seção.

---

## 7. API REST padrão

### 7.1 Fetcher tipado (`src/lib/api.ts`)

```ts
import { supabase } from './supabase';

const baseURL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession();
  const r = await fetch(`${baseURL}${path}`, {
    ...init,
    headers: {
      'content-type': 'application/json',
      ...(session ? { authorization: `Bearer ${session.access_token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (r.status === 401) {
    await supabase.auth.signOut();
    if (typeof window !== 'undefined') window.location.assign('/login');
    throw new ApiError(401, 'Sessão expirada');
  }

  if (!r.ok) {
    let detail = `Erro ${r.status}`;
    try { const body = await r.json(); detail = body.detail ?? detail; } catch {}
    throw new ApiError(r.status, detail);
  }

  return r.json() as Promise<T>;
}
```

### 7.2 Convenções de endpoint

- Backend FastAPI em `api/`, prefixo `/api/v1` (ou `/api/` no MVP — confirmar com `api/src/barra/api/v1.py`).
- Cada tela documenta seus endpoints na própria spec.
- Endpoint **agregado por tela** quando a tela é dashboard-like (ex.: `GET /api/painel/resumo`); **CRUD por entidade** quando a tela é mestre-detalhe (ex.: `GET /api/atendimentos/:id`).
- Erros: 4xx retorna `{ detail: string }` em pt-BR (mensagem usável em toast); 5xx retorna `{ detail: string }` genérico.
- Toda chamada de escrita é idempotente quando possível (ID na rota; dedupe no backend).

### 7.3 Tipos (`src/tipos/`)

- 1 arquivo por feature. Ex.: `tipos/painel.ts`, `tipos/atendimentos.ts`.
- **No futuro:** gerador OpenAPI (`scripts/gera_tipos_openapi.sh`) substitui a manutenção manual. Enquanto não existe, manter sincronia manual com o backend declarando: *"Tipos refletem o contrato de `api/src/barra/dominio/<contexto>/schemas.py` em <data>."*

---

## 8. Realtime padrão

### 8.1 Subscriptions

- Cada tela com Realtime declara explicitamente quais tabelas observa em sua spec (ex.: `atendimentos`, `comprovantes_pix`).
- **Backend/infra deve garantir** que essas tabelas estão na publicação `supabase_realtime`. RLS aplica.

### 8.2 Helper compartilhado (`src/lib/realtime.ts`)

```ts
import { supabase } from './supabase';

export type RealtimeTabela = 'atendimentos' | 'comprovantes_pix' | 'bloqueios' | 'eventos' | 'mensagens';

export function subscribeTabelas(canalNome: string, tabelas: RealtimeTabela[], onEvent: () => void) {
  const channels = tabelas.map((t) =>
    supabase.channel(`${canalNome}:${t}`)
      .on('postgres_changes', { event: '*', schema: 'barravips', table: t }, onEvent)
      .subscribe()
  );
  return () => channels.forEach((c) => supabase.removeChannel(c));
}
```

### 8.3 Anti-rajada

- Refetch debounced 250ms. Implementação simples com `useRef` + `clearTimeout`/`setTimeout` (sem lodash).
- Em dev, log: `console.debug('[<tela>] refetch coalescido por N eventos')`. Em produção, silencioso.
- **Critério de revisão:** se >30 refetches/min sustentados em produção, abrir issue para investigar trigger excessivo.

### 8.4 Reconciliação

Após qualquer evento, **refetch completo** do endpoint agregado da tela (sem patch local). Mantém consistência simples ao custo de uma request por janela debounced.

---

## 9. Padrões de UI (loading, erro, vazio, ações)

### 9.1 Loading

- **Skeleton** shadcn por bloco. Layout permanece estável (mesmas dimensões do conteúdo final).
- `aria-busy="true"` no container.
- **Não usar spinner full-screen** em qualquer tela autenticada.
- Após primeiro `success`, refetches **não** mostram skeleton — manter dados antigos visíveis.

### 9.2 Erro de carregamento

- **`<BannerErro />`** inline em cada bloco impactado. Layout permanece estável.
- Componente: `interface/src/components/layout/BannerErro.tsx`. Props: `{ mensagem?: string; onRetry: () => void }`.
- Visual:
  ```
  [card --card --rounded.lg --padding spacing.5, border-left 3px var(--danger-500)]
  [body-md --text-primary] Não foi possível carregar.
  [button-ghost] Tentar novamente
  ```
- Quando o erro é no agregado, todos os blocos exibem banner; click em "Tentar novamente" em qualquer um refaz o fetch global.

### 9.3 Empty state

- **Empty state próprio por bloco**, nunca esconder o bloco.
- Layout: card com ícone + 1 linha principal `body-md --text-primary` + 1 linha auxiliar `body-sm --text-muted` (opcional). Sem CTA salvo quando ele acelera ação útil (ex.: "Bloquear janela manualmente").
- Sem ilustração, sem mensagens hero. Tom operacional, não cerimonial.

### 9.4 Toasts (sonner)

Configurar uma vez em `app/layout.tsx`:

```tsx
import { Toaster } from 'sonner';
<Toaster position="bottom-right" theme="dark" richColors closeButton />
```

Convenções:

| Caso | Tipo | Texto |
|---|---|---|
| Ação OK | `success` | "{Ação} realizada" — específico por ação |
| Erro 4xx | `error` | mostrar `detail` retornado |
| Erro 5xx | `error` | "Erro do servidor. Tente novamente." |
| Sessão expirada | `error` | "Sessão expirada. Faça login novamente." |

### 9.5 AlertDialog para destrutivos

Toda ação que altera estado de **negócio relevante** (devolver para IA, registrar perdido, recusar Pix, cancelar bloqueio em `em_atendimento`) abre `<AlertDialog>` shadcn antes de chamar a API.

Estrutura mínima:

```
heading-lg --text-primary  | Título objetivo: "Devolver #142 para a IA?"
body-md --text-secondary   | Consequência clara em 1–2 frases
[button-ghost] Cancelar  [button-primary | button-danger] Confirmar
```

- `Esc`/click fora/Cancelar fecha sem ação.
- Confirmar desabilita ambos botões + spinner inline.
- Sucesso → fecha + toast.
- Erro → mantém aberto + toast.

### 9.6 Botões — uma única primary por tela

Regra do DESIGN.md: **uma única instância visível** de `button-primary` por tela (a ação canônica). Outras ações = `button-secondary` ou `button-ghost`. Destrutivas = `button-danger`. Quebrar essa regra exige veto local na spec da tela.

### 9.7 Foco e acessibilidade

- Todos elementos focáveis exibem ring `--ring` 2px offset 2px. **Nunca** override com `outline-none` sem substituto.
- Textos: contraste mínimo AA; texto principal AAA; cor sozinha **nunca** carrega informação (acompanhada de label/ícone/badge).
- Tabela ARIA roles esperados:
  - `<nav aria-label="Navegação principal">` na sidebar.
  - `<section aria-label="...">` em blocos da tela.
  - `<dl><dt><dd>` para KPIs.
  - Cards navegáveis: `<article role="link" tabIndex={0}>` + key Enter/Space ativando.

### 9.8 Conteúdo sensível

- Foto de portaria, comprovante Pix, mídia do cliente: chip mono com nome do arquivo + tamanho. **Nunca** preview automático.
- Expansão sob clique deliberado, em modal `--ink-0` sem decoração.

---

## 10. Formatadores (`src/lib/formatters.ts`)

Implementar **uma vez** e reusar em todas as telas.

### 10.1 Telefone (`formatTelefone`)

Input: JID Evolution (`5521987654321@s.whatsapp.net`, `552134567890@c.us`) ou E.164 (`+5521987654321`) ou puro (`21987654321`).

Algoritmo:

1. Strip de qualquer sufixo após `@`.
2. Strip do prefixo `+55` ou `55` no início.
3. Strip de qualquer caractere não-dígito.
4. Sobre os dígitos restantes:
   - 11 dígitos → `(DD) NNNNN-NNNN`. Ex.: `21987654321` → `(21) 98765-4321`.
   - 10 dígitos → `(DD) NNNN-NNNN`. Ex.: `2134567890` → `(21) 3456-7890`.
   - Outro tamanho (estrangeiro, malformado) → retornar a string sem prefixo `+55`/`55`, sem formatar.

> **Decisão consciente:** sem mascaramento. Fernando é único usuário do P0; RLS protege. Quando vendedor read-only (P1) entrar, mascaramento é decisão dessa fase.

### 10.2 Moeda BRL (`formatBRL`)

```ts
export const formatBRL = (n: number) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(n);
```

Sempre 2 casas decimais. Zero renderiza como `R$ 0,00`.

### 10.3 Data e hora (`formatData`, `formatDataHora`, `formatHorario`)

Fuso fixo: `America/Sao_Paulo`.

```ts
export const formatDataHora = (iso: string) =>
  new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso));
// "30 de abr. de 2026, 14:32"

export const formatData = (iso: string) =>
  new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit', month: 'short', year: 'numeric', timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso));
// "30 abr 2026"

export const formatHorario = (iso: string) =>
  new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso));
// "14:32"
```

### 10.4 Tempo relativo (`formatTempoRelativo`)

```ts
export function formatTempoRelativo(iso: string, agora = new Date()): string {
  const diffMs = agora.getTime() - new Date(iso).getTime();
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return 'agora';
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  const d = Math.floor(h / 24);
  return `há ${d} d`;
}
```

### 10.5 `previsao_termino` (cálculo backend, referência aqui)

Quando uma tela usar `previsao_termino` ou `expirado` num atendimento, o backend deriva (sem coluna nova):

| Caso | Fórmula |
|---|---|
| `tipo_atendimento='interno'` E `foto_portaria_em IS NOT NULL` E `duracao_horas IS NOT NULL` | `foto_portaria_em + (duracao_horas * INTERVAL '1 hour')` |
| `tipo_atendimento='externo'` E `data_desejada IS NOT NULL` E `horario_desejado IS NOT NULL` E `duracao_horas IS NOT NULL` | `(data_desejada + horario_desejado) AT TIME ZONE 'America/Sao_Paulo' + (duracao_horas * INTERVAL '1 hour')` |
| Qualquer outro | `null`, `expirado=false` |

`expirado = (previsao_termino IS NOT NULL) AND (now() > previsao_termino)`.

---

## 11. Convenções de código

- TypeScript estrito (`tsconfig.json` com `strict: true`).
- Componentes em arquivos individuais; sem `index.ts` re-exports.
- **Zero comentários** salvo onde o porquê é não óbvio (regra `CLAUDE.md`).
- Nada de itálico para ênfase em texto operacional — usar `font-weight: 600` ou `--text-brand`.
- Sem `console.log` em produção. `console.debug` permitido apenas em dev guards (`if (process.env.NODE_ENV !== 'production')`).
- Sem `any`. Erros de tipo resolvidos no tipo, não com `as`.
- **Sem testes nesta fase.** Verificação é manual conforme `CLAUDE.md` §5 (subir dev server, validar fluxo, rodar Lighthouse quando relevante).

---

## 12. Vetos globais (DESIGN.md aplicado)

❌ **Não** trocar dark por light, mid ou system.
❌ **Não** usar `#000000`/`#FFFFFF` em superfícies grandes — halation.
❌ **Não** mostrar foto de modelo em sidebar, lista, hover ou qualquer superfície que não a tela explícita de cadastro.
❌ **Não** preview automático de foto de portaria/comprovante Pix.
❌ **Não** usar serifa fora do logo da sidebar e do título de página principal.
❌ **Não** usar vermelho/amarelo fora do vocabulário de estado.
❌ **Não** introduzir 4º dourado, 5º cinza ou cor "alternativa".
❌ **Não** usar sombra em card. Profundidade vem da cor da superfície.
❌ **Não** usar gradient, glow, glass-morphism, ilustração ou ícone decorativo.
❌ **Não** usar ações destrutivas como botão primary.
❌ **Não** versão mobile operacional (mobile = blocker, exceto `/login`).
❌ **Não** misturar bibliotecas de ícones — Lucide uniforme.
❌ **Não** confundir `Pausada` (neutro) com `Em handoff` (decisão pendente).
❌ **Não** carregar avatar de cliente do WhatsApp.
❌ **Não** usar `localStorage` para token — `@supabase/ssr` cuida via cookie.
❌ **Não** fazer SSR/RSC para telas com Realtime — client component com skeleton.
❌ **Não** cachear respostas da API REST no client.
❌ **Não** introduzir paginação ou virtualização sem necessidade comprovada.
❌ **Não** depender só de cor para informação (acompanhar com label/ícone).

---

## 13. Pré-requisitos compartilhados (uma vez no projeto)

> Estes itens são executados **uma única vez** no setup do projeto. As specs de tela individuais não os repetem; apenas verificam que estão prontos.

### 13.1 Variáveis de ambiente (`interface/.env.example`)

```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
```

### 13.2 Dependências a adicionar uma vez

```sh
pnpm add @supabase/supabase-js @supabase/ssr sonner
```

### 13.3 Componentes shadcn a instalar uma vez

```sh
pnpm dlx shadcn@latest add card badge alert-dialog tooltip skeleton sonner separator
```

(Adicionar outros conforme cada tela exigir.)

### 13.4 Schema/RLS no Supabase

- Schema `barravips` aplicado conforme `infra/sql/0001_schema_inicial.sql`.
- RLS `FORCE` em todas as tabelas; policy `fernando_full_access` ativa para usuários com papel `fernando`.
- Tabelas listadas em §8.1 estão na publicação `supabase_realtime`.

---

## 14. Critérios de aceite estruturais (para todas as telas)

Toda tela, ao ser considerada pronta, **também** passa nestes critérios além dos específicos:

- [ ] EST-1 — `pnpm lint` em `interface/` passa sem erro.
- [ ] EST-2 — `pnpm build` em `interface/` passa sem erro.
- [ ] EST-3 — `pnpm dev` sobe e a rota da tela carrega sem erro de console.
- [ ] EST-4 — Acesso não autenticado → redirect `/login` (middleware §6.1).
- [ ] EST-5 — Acesso em viewport <1024px (exceto `/login`) → `<MobileBlocker/>`.
- [ ] EST-6 — Foco visível com ring `--ring` 2px offset 2px em todos os interativos.
- [ ] EST-7 — `dark` aplicado em `<html>`; tokens DESIGN.md em uso; sem `--ink-*`/`--gold-*` hard-coded em componentes (apenas em `globals.css`).
- [ ] EST-8 — Apenas 1 `button-primary` visível na tela (ou veto local declarado na spec).
- [ ] EST-9 — Vocabulário do `CONTEXT.md` respeitado em qualquer label visível.
- [ ] EST-10 — Skeletons no loading inicial; banner inline + retry no erro; empty-state próprio quando dados vazios.
- [ ] EST-11 — Erro 401 da API → `signOut` + redirect `/login` (via `lib/api.ts`).
- [ ] EST-12 — Refresh JWT (`TOKEN_REFRESHED`) chama `supabase.realtime.setAuth` se a tela tiver Realtime.
- [ ] EST-13 — Lighthouse acessibilidade ≥ 95 (quando a tela for visualmente estabilizada).

---

## 15. Vetos locais — quando uma tela precisa quebrar a fundação

Se uma tela específica precisar contradizer algo aqui, sua spec inclui uma seção **"Vetos locais"** com:

- Item da fundação que está sendo quebrado (ex.: "§9.6 — apenas 1 primary por tela").
- Justificativa em 1–3 frases.
- Aprovação do usuário (referência da conversa onde foi decidido).

Sem esses 3 itens, o agente codificador segue a fundação literalmente.

---

## 16. Histórico

| Data | Mudança | Origem |
|---|---|---|
| 2026-04-30 | Versão alpha extraída da spec da Tela 01 (Painel Geral). | Conversa de QA Tela 01. |

— FIM —
