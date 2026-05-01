# Tela 07 — Dashboard

> **Herda decisões de** `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto local declarado em §17. Não repetir aqui o que está na fundação.

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome | Dashboard |
| Slug | `dashboard` |
| Rota | `/dashboard` (filtros em query string: `?periodo=7d&modelo_id=...&de=...&ate=...`) |
| Arquivo Next.js | `interface/src/app/(interface)/dashboard/page.tsx` |
| Tipo | Client Component (`"use client"`) — Realtime exige client |
| Hook próprio | `interface/src/hooks/useDashboard.ts` |
| Tipos | `interface/src/tipos/dashboard.ts` |
| Componentes próprios | `interface/src/components/dashboard/{HeaderDashboard,ToolbarDashboard,FiltroPeriodo,FiltroModelo,DialogRangeCustom,TilePixRevisao,TileKpi,FunilEstados,BarraEstado,BlocoPerdasPorMotivo,BlocoMotivosEscalada,DialogTodasEscaladas,ProfissionaisRanking,IndicadorTendencia}.tsx` |

---

## 2. Objetivo

Dar a Fernando uma visão analítica agregada da operação no período selecionado: **taxa de conversão**, volume de **fechamentos** e **perdas** com valores, distribuição de atendimentos por estado, breakdown de **Motivo de perda**, ranking dos motivos de escalada e desempenho por modelo. Tela é **leitura pura** — toda ação é navegação contextual para as telas operacionais (`/atendimentos`, `/pix`, `/agenda`, `/modelos`).

Citação literal de `docs/mvp/06-dados-interfaces.md` §4.7: *"Métricas P0."*

---

## 3. Contexto funcional

- **Único usuário no P0:** Fernando.
- **Unidade da tela:** atendimentos do par (modelo, intervalo de tempo). No P0 só existe a piloto, mas a tela é estruturada para múltiplas modelos em P1.
- **Origem dos dados:** endpoint agregado único `GET /api/dashboard` (§12).
- **Realtime:** assinatura em `atendimentos`, `comprovantes_pix` e `escaladas` (§13). **Não** assinar `eventos` — alta cardinalidade; o backend desnormaliza o que importa nas três tabelas observadas (consistente com Tela 05 §13.1).
- **Escrita:** **nenhuma**. Toda interação é navegação ou troca de filtro.
- **Janela de comparação:** sempre o período imediatamente anterior de mesmo tamanho (hoje vs ontem; 7d vs 7d anteriores; 30d vs 30d anteriores; custom de N dias vs N dias anteriores). Backend retorna ambos os snapshots; front exibe delta % e seta.
- **Métrica de "Pix em revisão pendentes":** **snapshot atual** (não filtrado pelo período). Justificativa: é fila operacional ativa, não série temporal.
- **Filtro de modelo:** select "Todas" + lista de modelos. No P0 com 1 piloto, o select renderiza mas é informativo (espelhando Tela 05 §5.2).
- **Fora do escopo desta tela:** export (PDF/CSV), drill-down por dia/hora, séries temporais com gráfico de linha, filtros por `fonte_decisao`, métricas por vendedor, auditoria de classificador (todos P1, conforme `docs/mvp/06-dados-interfaces.md` §4.7).

---

## 4. Fluxo do usuário

### 4.1 Caminho feliz

1. Fernando acessa `/dashboard`. Middleware (fundação §6.1) garante autenticação.
2. Tela lê filtros da query string (default `periodo=7d`, `modelo_id=todas`).
3. Tela monta com skeletons em todos os blocos.
4. `useDashboard` chama `GET /api/dashboard?periodo=7d` via `lib/api.ts`; em paralelo, abre 3 subscriptions Realtime (§13.1) e registra listener `onAuthStateChange` (fundação §6.3).
5. Snapshot chega → skeletons substituídos pelo conteúdo:
   - tile destacado de **Pix em revisão pendentes** (snapshot atual);
   - 4 KPIs do período com indicador de tendência;
   - funil de estados em barras horizontais;
   - blocos de perdas por motivo e motivos de escalada lado a lado;
   - ranking de profissionais.
6. Fernando troca filtro → URL atualiza via `router.replace`; refetch sem skeleton (fundação §9.1); blocos mantêm dados antigos visíveis até o novo `success`.
7. Fernando clica em barra do funil → navega para `/atendimentos?estado=Perdido` (sem propagar período — §9.6).
8. Métricas atualizam ao vivo conforme novos atendimentos fecham/perdem ou Pix entram em revisão (refetch debounced 250ms).

### 4.2 Caminhos alternativos específicos da tela

| Cenário | Comportamento |
|---|---|
| 0 atendimentos no período | Cada bloco renderiza seu empty state próprio (§8). KPIs renderizam `0` / `R$ 0,00` / `—%` (taxa de conversão sem denominador). Funil mostra 8 barras com 0. Ranking mostra a piloto com tudo zero. |
| Período de comparação anterior também 0 | Indicador de tendência mostra `—` em vez de seta + delta. |
| Período de comparação 0 e atual > 0 | Indicador de tendência mostra chip `caption` "novo" em `--gold-500`, sem percentual. |
| Range custom inválido (`de` > `ate`, ou janela > 90 dias, ou `ate` no futuro) | Front bloqueia o "Aplicar" do `DialogRangeCustom` com mensagem inline; URL não é atualizada. Backend valida em paralelo (422). |
| Filtro por modelo inexistente (deep link com `modelo_id` inválido) | Backend retorna 404; front exibe `<BannerErro/>` com retry; filtro de modelo reverte para "Todas". |

> Cenários de auth, 401, mobile, erro de rede, refresh JWT são tratados pela fundação (§§6, 7, 5.3, 9.2).

---

## 5. Layout detalhado dos blocos próprios

> Sidebar e shell de 2 colunas vêm da fundação §5. Esta seção descreve apenas o conteúdo do `<main>` da rota `/dashboard`.

Sequência vertical dentro do `<main>`:

```
[Cabeçalho da página]
[Toolbar de filtros]
[Tile destacado — Pix em revisão pendentes (snapshot)]
[KPIs do período — 4 tiles]
[Funil de estados]
[Grid 2 colunas: Perdas por motivo | Motivos de escalada]
[Profissionais mais procuradas]
```

### 5.1 Cabeçalho da página

- Container: `padding: spacing.6 spacing.6 spacing.4`; flex row, `justify-content: space-between; align-items: baseline`.
- **Esquerda:** título "Dashboard" em **Cormorant Garamond `display-lg`** (40px, peso 500, `--text-primary`).
- **Direita:** rótulo do período aplicado em `caption --text-muted` maiúsculo + intervalo absoluto em `body-sm --text-primary` mono. Ex.: `PERÍODO  ·  24 abr – 30 abr 2026`.
- Re-render do bloco direito quando o filtro muda; sem `setInterval` (snapshot ancora o período).

### 5.2 Toolbar de filtros

- Linha horizontal abaixo do cabeçalho. Padding `spacing.0 spacing.6 spacing.5`. Gap `spacing.3`.
- Sem botão "Atualizar" — Realtime cobre (§13).

| Controle | Tipo | Opções |
|---|---|---|
| Período | segmented control (3 chips lado a lado) + chip "Personalizado" | `Hoje`, `7 dias` (default), `30 dias`, `Personalizado…` |
| Modelo | select | `Todas` (default) + lista de modelos. No P0 com 1 piloto, o controle aparece mas é informativo. |

#### 5.2.1 Chip "Personalizado…"

- Click abre `DialogRangeCustom` (§6.1).
- Quando ativo (range custom aplicado), o chip exibe a janela aplicada em mono-sm: `01 abr – 15 abr 2026`.
- Click novamente reabre o dialog com os valores vigentes.

#### 5.2.2 Sincronização com URL

- Mudança de qualquer filtro: `router.replace(...)` com nova query string.
- Recarregar a página com query string preserva o estado (deep link).
- Query string canônica:
  - `?periodo=hoje|7d|30d` para presets;
  - `?periodo=custom&de=YYYY-MM-DD&ate=YYYY-MM-DD` para range custom;
  - `&modelo_id={uuid}` opcional. Ausente = `todas`.

### 5.3 Tile destacado — Pix em revisão pendentes (snapshot)

- Container: `<Card>` shadcn `--card --rounded.lg --padding spacing.5`, `border-left: 3px solid var(--warn-500)` quando `> 0`; sem borda quando `= 0`.
- Layout flex row, `justify-content: space-between; align-items: center`.
- **Esquerda:**
  - label `caption --text-muted` maiúsculo "PIX EM REVISÃO PENDENTES (AGORA)".
  - valor em `display-lg --text-primary` (40px, Inter, peso 500).
  - linha `body-sm --text-muted`: "Não filtrado por período — fila operacional ativa."
- **Direita:** botão `button-secondary` "Ir para fila →" (ícone `Receipt` 16px à esquerda, `ArrowRight` 16px à direita).
  - Quando `= 0`, botão fica `button-ghost` desabilitado (`aria-disabled="true"`) com tooltip "Sem Pix aguardando decisão.".
  - Click navega para `/pix?status=em_revisao`.

### 5.4 KPIs do período — 4 tiles

- Título da seção: `heading-md --text-primary` "No período" + à direita, em `caption --text-muted`, "vs período anterior" (sempre presente quando há comparação válida).
- Padding seção: `spacing.5 spacing.6 spacing.3`.
- **Grid:** 4 colunas desde `lg`. Gap `spacing.4`.

#### 5.4.1 Estrutura de cada tile

```
[Card --card --rounded.lg --padding spacing.5]
  <dl>
    <dt> LABEL (caption --text-muted maiúsculo) </dt>
    <dd> VALOR (display-lg --text-primary) </dd>
  </dl>
  [linha auxiliar opcional, body-sm --text-muted]
  [IndicadorTendencia: seta + delta % + cor]
```

#### 5.4.2 Conteúdo dos tiles

| # | Label | Valor principal | Linha auxiliar | Tendência (delta vs período anterior) |
|---|---|---|---|---|
| 1 | TAXA DE CONVERSÃO | `formatPercent(kpis.taxa_conversao_pct)` (ex.: `73%`). Se denominador 0: `—` em `--text-muted`, sem indicador. | `{fechamentos} fech. / {fechamentos+perdas} decididos` em `body-sm --text-muted` | seta + delta em pontos percentuais (pp). Cor: ↑ em `--success-500`, ↓ em `--danger-500`, `=` em `--text-muted`. |
| 2 | FECHAMENTOS | `kpis.fechamentos.contagem` (inteiro) em `--success-500` | `formatBRL(kpis.fechamentos.valor_bruto_brl)` bruto · ticket médio `formatBRL(kpis.fechamentos.valor_medio_brl)` em `body-sm --text-muted` | seta + delta % na contagem |
| 3 | PERDAS | `kpis.perdas.contagem` em `--danger-500` | sem linha auxiliar | seta + delta % na contagem (delta menor é positivo — cor `--success-500` se ↓; ver §5.4.3) |
| 4 | ATENDIMENTOS ESCALADOS | `kpis.escaladas.contagem` em `--text-primary` | sem linha auxiliar | seta + delta % na contagem |

#### 5.4.3 IndicadorTendencia

Componente reutilizável.

| Caso | Render |
|---|---|
| `base = 0 AND atual = 0` | `—` em `--text-muted`, sem chip |
| `base = 0 AND atual > 0` | chip `caption` "novo" em `--gold-500` |
| `base > 0` | seta (`ArrowUp`/`ArrowDown`/`Minus` 12px) + `+12,5%` ou `−4,2%` em `caption` |

- **Polaridade da cor:** taxa de conversão e fechamentos seguem polaridade direta (alta = bom). **Perdas e atendimentos escalados** seguem polaridade invertida (baixa = bom): ↓ pinta `--success-500`; ↑ pinta `--danger-500`. `=` sempre `--text-muted`.
- `Math.abs(delta) < 0.05%` exibe `Minus` + `0%` em `--text-muted` (zero efetivo).

### 5.5 Funil de estados

- Título: `heading-md --text-primary` "Volume por estado" + à direita, em `caption --text-muted`, "{total} atendimentos no período".
- Padding seção: `spacing.5 spacing.6 spacing.3`.
- Container: `<Card --card --rounded.lg --padding spacing.5>`.

#### 5.5.1 Layout das barras

Lista vertical fixa de 8 linhas (1 por estado), na ordem canônica de `EstadoAtendimento`: `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`, `Confirmado`, `Em_execucao`, `Fechado`, `Perdido`.

Cada linha (altura 32px, padding `spacing.2 0`):

```
[label fixo 200px] [barra flex 1] [contagem mono-sm 60px right] [percentual caption 56px right]
```

- **Label:** `body-sm --text-primary` capitalizado conforme vocabulário (`Aguardando_confirmacao` exibe como `Aguardando confirmação`). Truncate com tooltip se overflow.
- **Barra:** `<div role="progressbar" aria-valuenow=… aria-valuemax=… aria-valuemin=0>` com altura 16px, `rounded.sm`, fundo `--ink-300`. Preenchimento interno largura proporcional ao **maior valor da lista** (não ao total): `width: (contagem / max) * 100%`. Cor do preenchimento por estado:

| Estado | Cor do preenchimento |
|---|---|
| `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`, `Confirmado`, `Em_execucao` | `--ink-500` |
| `Fechado` | `--success-500` |
| `Perdido` | `--danger-500` |

- **Contagem:** `mono-sm --text-primary`, alinhada à direita.
- **Percentual:** `(contagem / total) * 100` com 0 casas decimais, em `caption --text-muted`. Quando `total = 0`, esconde a coluna de percentual (mantém contagem `0`).

#### 5.5.2 Linha clicável

- Cada linha inteira é `<button type="button">` com hover `--ink-200` e foco `--ring`.
- Click navega para `/atendimentos?estado={Estado}` **sem** propagar `periodo` ou `modelo_id` (§9.6).
- Linha com contagem 0 permanece clicável (Fernando pode querer ver a fila vazia em outra tela).

#### 5.5.3 Empty state

Quando `total = 0`:

```
[card auxiliar dentro do mesmo Card, sem borda]
Nenhum atendimento no período selecionado.
```

`body-md --text-primary` na linha 1; `body-sm --text-muted` na linha 2 ("Ajuste o período no topo da página."). Funil **continua renderizando** (8 barras com 0) abaixo do empty inline — auditoria.

### 5.6 Grid 2 colunas: Perdas por motivo | Motivos de escalada

- Padding seção: `spacing.5 spacing.6 spacing.3`.
- **Grid:** 1 coluna até `xl`; 2 colunas a partir de `xl`. Gap `spacing.4`.

#### 5.6.1 Bloco "Perdas por motivo"

- Card `<Card --card --rounded.lg --padding spacing.5>`.
- Título: `heading-md --text-primary` "Perdas por motivo".
- Conteúdo: lista vertical de até 6 linhas, uma por **Motivo de perda** canônico (`preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`).
- Linhas com contagem 0 **não** são exibidas (diferente do funil — aqui motivos sem ocorrência poluem).
- Cada linha (altura 28px):

```
[Label legível 180px] [barra flex 1, fundo --ink-300, fill --danger-500] [contagem mono-sm 40px] [percentual caption 56px]
```

- **Map de labels:** `preco` → "Preço"; `sumiu` → "Sumiu"; `risco` → "Risco"; `indisponibilidade` → "Indisponibilidade"; `fora_de_area` → "Fora da área"; `outro` → "Outro".
- **Percentual:** sobre o total de perdas do período (não sobre o total de atendimentos).
- Linha clicável → navega para `/atendimentos?estado=Perdido&motivo_perda={motivo}` (sem propagar período).
- **Empty state:** quando `kpis.perdas.contagem = 0`, substitui a lista por:

```
✓ Sem perdas no período.
```

`body-md --text-primary` + ícone `CheckCircle2 --success-500` 20px.

#### 5.6.2 Bloco "Motivos de escalada"

- Card `<Card --card --rounded.lg --padding spacing.5>`.
- Título: `heading-md --text-primary` "Motivos de escalada" + à direita, `caption --text-muted` "{total} no período".
- Conteúdo: top 5 motivos com texto livre agregado por contagem **exata** (sem clustering), seguidos da linha "Outros (N)" quando `outros_total > 0`.
- Cada linha (altura 28px):

```
[Texto do motivo flex 1, body-sm --text-primary, 1 linha truncate com tooltip] [contagem mono-sm 40px right]
```

- A linha "Outros (N)" usa `body-sm --text-muted` no label. Click abre `DialogTodasEscaladas` (§6.2).
- Linhas do top 5 são clicáveis → navegam para `/atendimentos?ia_pausada=true&motivo_escalada={texto-encoded}`. (A Tela 02 não expõe esse filtro hoje; ver §14 para o ajuste necessário.)
- **Empty state:** quando `motivos_escalada.total = 0`, substitui a lista por:

```
Sem atendimentos escalados no período.
```

`body-md --text-muted`.

### 5.7 Profissionais mais procuradas

- Título: `heading-md --text-primary` "Profissionais mais procuradas".
- Padding seção: `spacing.5 spacing.6 spacing.3`.
- Container: `<Card --card --rounded.lg --padding spacing.0>` com tabela.
- **Tabela** (`<table>` semântica; linhas 56px conforme densidade da fundação §4.4):

| Coluna | Largura | Conteúdo |
|---|---|---|
| Modelo | flex 1 | nome em `heading-sm --text-primary`. Posto (`#1`, `#2`…) em mono-sm `--text-muted` à esquerda. |
| Volume | 96px | atendimentos do período em `mono-sm --text-primary` |
| Fechamentos | 120px | contagem em `--success-500` mono-sm |
| Valor bruto | 160px | `formatBRL(...)` em mono-sm `--text-primary` |
| Conversão | 96px | `formatPercent(...)` em mono-sm; `—` quando denominador 0 |
| | 24px | `ChevronRight` 16px `--text-muted` |

- Ordenação: `volume DESC`. Empate: `valor_bruto_brl DESC`.
- Linha inteira clicável: navega para `/modelos?modelo={id}&aba=perfil` (sem propagar período — §9.6).
- **Empty state** (nenhuma modelo cadastrada): `body-md --text-muted` "Nenhuma modelo cadastrada." + botão `button-secondary` "Cadastrar modelo →" navegando para `/modelos`.
- **No P0 com 1 piloto:** a tabela mostra exatamente 1 linha. Estrutura ainda assim é tabela (preparada para P1).

---

## 6. Dialogs

### 6.1 `DialogRangeCustom`

Modal sem AlertDialog (não é destrutivo).

```
[Dialog --card --rounded.lg --padding spacing.5, max-w-md]

heading-lg --text-primary  | Período personalizado

[ Início:  date input ]   [ Fim: date input ]

[mensagem inline de erro, body-sm --danger-500 — quando inválido]

[button-ghost] Cancelar  [button-primary] Aplicar
```

- Inputs `<input type="date">`. Limite máximo de cada um: `today` em `America/Sao_Paulo` (sem futuro).
- Validação front antes de habilitar "Aplicar":
  - ambos preenchidos;
  - `de <= ate`;
  - `ate <= today` (em BRT);
  - `(ate - de) <= 90 dias`.
- Falha de validação exibe mensagem inline `body-sm --danger-500`. Botão "Aplicar" fica `disabled`.
- "Aplicar" → atualiza URL via `router.replace('?periodo=custom&de=...&ate=...')`. Backend valida em paralelo (422 cai no toast de erro genérico via `<BannerErro/>`).
- Esc/click fora/Cancelar fecha sem efeito.

### 6.2 `DialogTodasEscaladas`

Modal de leitura sem AlertDialog.

```
[Dialog --card --rounded.lg --padding spacing.5, max-w-lg, max-height 80vh]

heading-lg --text-primary  | Motivos de escalada — período completo

[lista virtual dispensada; rolagem nativa]
[ texto motivo (body-sm --text-primary) ]   [ contagem mono-sm right ]
... (todos os motivos do período, ordenados por contagem DESC, exatos sem clustering)

[button-ghost] Fechar
```

- Endpoint: `GET /api/dashboard/escaladas?periodo=...&modelo_id=...` (§12.2). Lazy-load — só fetch ao abrir o dialog.
- Fonte: `escaladas.motivo` (texto livre, `NOT NULL` no schema; ver `docs/mvp/06-dados-interfaces.md` §3.6).
- Cada linha clicável navega para `/atendimentos?ia_pausada=true&motivo_escalada={texto-encoded}` e fecha o dialog.

---

## 7. Comportamentos esperados

### 7.1 Inicialização

`useEffect` no mount:

1. Lê `periodo`, `de`, `ate`, `modelo_id` da query string. Sem query: `periodo=7d`, `modelo_id` ausente.
2. `fetch` via `api('/dashboard?...')` (fundação §7.1).
3. `subscribeTabelas('dashboard', ['atendimentos','comprovantes_pix','escaladas'], debouncedRefetch)` (helper fundação §8.2).
4. Listener `onAuthStateChange` (fundação §6.3).

Cleanup no unmount: cancela subscriptions e listener.

### 7.2 Mudança de filtro

- Atualiza URL via `router.replace`.
- Refetch sem skeleton (mantém dados antigos visíveis até novo `success`).
- Realtime continua ativo durante a transição.

### 7.3 Reconciliação Realtime

Conforme fundação §8.3 e §8.4: refetch debounced 250ms; sem patch local; sem skeleton em refetches subsequentes.

### 7.4 Click em barra do funil / linha de motivo / linha de modelo

- Navegação via `router.push(...)`.
- **Filtro de período NÃO é propagado** (§9.6).
- Barras/linhas com contagem 0 permanecem navegáveis (decisão consciente; deixa o usuário inspecionar a fila vazia).

### 7.5 Teclado / a11y

Ordem do Tab: itens da sidebar (fundação) → cabeçalho (sem foco no h1) → controles da toolbar (chips de período, modelo) → "Ir para fila" do tile de Pix → barras do funil → linhas de perdas por motivo → linhas de motivos de escalada → "Ver todos" das escaladas → linhas do ranking de profissionais. Tiles de KPI **não são focáveis** (`<dl>`).

Roles ARIA:
- `<section aria-label="Filtros do dashboard">` na toolbar.
- `<section aria-label="Pix em revisão pendentes">` no tile destacado.
- `<section aria-label="KPIs do período">` no bloco de tiles (com `<dl>` interno).
- `<section aria-label="Volume por estado">` no funil. Cada barra usa `role="progressbar"` com `aria-valuenow/min/max` e `aria-label="{Estado}: {N} atendimentos"`.
- `<section aria-label="Perdas por motivo">`.
- `<section aria-label="Motivos de escalada">`.
- `<section aria-label="Profissionais mais procuradas">` com `<table>` semântica + `<caption>` visível.

---

## 8. Estados específicos da tela

> Padrões gerais de loading/erro/empty na fundação §9.

| Estado | Quando | Aparência |
|---|---|---|
| `loading-inicial` | primeiro fetch | skeletons em todos os blocos (§8.1) |
| `success-vazio (período)` | `total_periodo = 0` | KPIs, funil, ranking renderizam com 0; perdas/escaladas substituem lista por empty inline |
| `success-sem-comparacao` | `kpis_periodo_anterior` é `null` (caso o backend declare janela anterior fora do range disponível) | tiles renderizam sem `IndicadorTendencia` |
| `success-zerado (KPIs)` | algum KPI específico = 0 | tile renderiza com `0` / `R$ 0,00` / `—`; sem esconder |
| `success-sem-modelo` | `profissionais.length === 0` | ranking exibe empty `Nenhuma modelo cadastrada` |
| `dialog-range-loading` | "Aplicar" do `DialogRangeCustom` em vôo | botões desabilitados + spinner inline; URL ainda não muda até 200 chegar |
| `dialog-escaladas-loading` | abertura do `DialogTodasEscaladas` antes do fetch | skeleton de 8 linhas dentro do modal |

### 8.1 Skeletons específicos

- **Tile de Pix em revisão:** card 88px com 2 `Skeleton` (label 16px, valor 36px) + skeleton de botão 32px à direita.
- **KPIs do período:** 4 tiles 116px, cada com 3 `Skeleton` (label 16px, valor 36px, linha auxiliar 14px).
- **Funil:** 8 linhas-fantasma de 32px (label-skeleton + barra-skeleton + contagem-skeleton).
- **Perdas por motivo:** 4 linhas-fantasma de 28px.
- **Motivos de escalada:** 5 linhas-fantasma de 28px.
- **Profissionais:** 1 linha-fantasma de 56px (no P0; em P1 escala com `expected_modelos`).

---

## 9. Regras de negócio

### 9.1 Janela do período

- **Fuso fixo:** `America/Sao_Paulo`. Backend resolve com `AT TIME ZONE 'America/Sao_Paulo'`.
- **Presets:**
  - `hoje` = `[hoje 00:00:00 BRT, hoje 23:59:59.999 BRT]`.
  - `7d` = `[hoje-6 00:00:00 BRT, hoje 23:59:59.999 BRT]` (7 dias inclusivos contando hoje).
  - `30d` = `[hoje-29 00:00:00 BRT, hoje 23:59:59.999 BRT]` (30 dias inclusivos).
- **Custom:** `[de 00:00:00 BRT, ate 23:59:59.999 BRT]` com `(ate - de) <= 90 dias` e `ate <= today`.
- **Período de comparação:** janela imediatamente anterior de mesma duração. Ex.: `7d` → `[hoje-13, hoje-7]`.

### 9.2 KPIs do período

- `kpis.fechamentos.contagem` = atendimentos com `estado='Fechado'` e evento `fechado_registrado.created_at` dentro da janela. Mesma fonte da Tela 01 §9.2.
- `kpis.fechamentos.valor_bruto_brl` = `SUM(valor_final)` desses atendimentos.
- `kpis.fechamentos.valor_medio_brl` = `valor_bruto_brl / contagem`. Quando `contagem = 0`, retorna `0`.
- `kpis.perdas.contagem` = atendimentos com `estado='Perdido'` e evento `perdido_registrado.created_at` dentro da janela.
- `kpis.taxa_conversao_pct` = `fechamentos.contagem / (fechamentos.contagem + perdas.contagem) * 100`. Quando denominador `= 0`, retorna `null` (front mostra `—`).
- `kpis.escaladas.contagem` = `escaladas.aberta_em` dentro da janela. Cada escalada conta uma vez (não conta atendimento — uma sequência de pausa/retomada/pausa gera múltiplas escaladas).

### 9.3 Pix em revisão pendentes (snapshot)

- `pix_em_revisao_pendentes_total` = `COUNT(comprovantes_pix)` com `decisao_pipeline='em_revisao' AND decisao_final IS NULL`.
- **Sem corte temporal.** É fila ativa, não série temporal. Mesma fonte do tile do Painel Geral (Tela 01 §9.2).
- Filtrado por modelo quando `modelo_id` é passado.

### 9.4 Funil de estados

- Para cada `EstadoAtendimento` ∈ `{Novo, Triagem, Qualificado, Aguardando_confirmacao, Confirmado, Em_execucao, Fechado, Perdido}`:
  - `contagem` = atendimentos com `created_at` dentro da janela e `estado` correspondente **no momento da query** (snapshot do estado atual). Estados terminais (`Fechado`, `Perdido`) refletem a decisão final; estados intermediários refletem a posição corrente na máquina de estados.
- `total = SUM(contagem)`. **`total` é igual ao número de atendimentos criados na janela**, porque cada atendimento ocupa exatamente um estado.
- **Decisão consciente:** o funil mostra distribuição **estática** dos atendimentos criados na janela, não trajetória cumulativa. Não computa "passou por Triagem" — apenas "está em Triagem agora". Drill-down temporal fica para P1.

### 9.5 Perdas por motivo / Motivos de escalada

- **Perdas por motivo:** `GROUP BY motivo_perda` sobre os atendimentos de `kpis.perdas.contagem`. Motivos com 0 ocorrências não aparecem.
- **Motivos de escalada:**
  - top 5 = `escaladas.motivo` agrupado por **string exata** (sem normalização, sem clustering — ver §17.2), `ORDER BY contagem DESC, motivo ASC` (desempate alfabético), `LIMIT 5`.
  - `outros_total` = soma de contagens das escaladas que não estão no top 5.
  - `total` = soma geral.

### 9.6 CTAs e propagação de filtro

**CTAs de saída NÃO propagam o filtro de período** para a tela destino. Justificativa:

- `/atendimentos`, `/pix`, `/agenda`, `/modelos` são telas operacionais e mostram **estado atual**, não série temporal.
- Propagar `?periodo=7d` para `/atendimentos` daria a impressão de filtrar por janela temporal — mas a Central filtra por `estado`, `tipo`, `urgência`, `IA pausada`, não por `created_at` (Tela 02 §5.2). Resultado seria filtro fantasma.
- A Tela 02 e a Tela 05 têm seus próprios filtros temporais quando aplicáveis (Tela 05 tem "Período de envio" — não confundir com período do dashboard).

CTAs propagam apenas o filtro **lógico** correspondente (estado, motivo, status), nunca o intervalo. O filtro de **modelo** também não propaga no P0 (a Central não expõe filtro de modelo na toolbar conforme Tela 02 §5.2).

### 9.7 Profissionais mais procuradas

- Para cada modelo com pelo menos 1 atendimento na janela:
  - `volume` = `COUNT(atendimentos)` com `created_at` na janela e `modelo_id` correspondente.
  - `fechamentos`, `valor_bruto_brl`, `taxa_conversao_pct` calculados como em §9.2 mas restritos à modelo.
- Modelos sem atendimentos na janela **aparecem mesmo assim** com tudo zero (sinaliza modelos inativas; útil em P1).
- Ordenação: `volume DESC`, depois `valor_bruto_brl DESC`.

---

## 10. Validações

| Onde | Validação | Falha |
|---|---|---|
| Front, antes de habilitar "Aplicar" do range custom | `de` e `ate` preenchidos; `de <= ate`; `ate <= today` (BRT); janela ≤ 90 dias | Botão fica disabled; mensagem inline |
| Front, antes de chamar `GET /api/dashboard` | `periodo ∈ {hoje, 7d, 30d, custom}`; quando `custom`, `de` e `ate` válidos | Filtro reverte para default `7d`; toast de erro inline |
| Backend | mesmo conjunto + `modelo_id` UUID válido se presente | 422 `{ detail: "..." }` para erro de validação; 404 `{ detail: "Modelo não encontrada" }` para `modelo_id` inexistente. Front mostra `<BannerErro/>` com retry. |
| Backend | Usuário tem `papel='fernando'` | RLS + check; 403 Forbidden. Front: `signOut` (fundação §6.4) ou toast genérico "Sem permissão". |

---

## 11. Dados — tipos próprios da tela

Arquivo: `interface/src/tipos/dashboard.ts`.

```ts
import type { EstadoAtendimento, MotivoPerda } from './atendimentos';

export type FiltroPeriodo = 'hoje' | '7d' | '30d' | 'custom';

export interface FiltroAplicado {
  periodo: FiltroPeriodo;
  de: string;          // ISO date YYYY-MM-DD (BRT) — preenchido sempre, inclusive nos presets
  ate: string;         // ISO date YYYY-MM-DD (BRT)
  modelo_id: string | null;
}

export interface JanelaComparacao {
  de: string;
  ate: string;
}

export interface ModeloResumoDashboard {
  id: string;
  nome: string;
}

export interface KpisFechamentos {
  contagem: number;
  valor_bruto_brl: number;
  valor_medio_brl: number;
}

export interface KpisPeriodo {
  taxa_conversao_pct: number | null;     // null quando denominador 0
  fechamentos: KpisFechamentos;
  perdas: { contagem: number };
  escaladas: { contagem: number };
}

export interface FunilEstadoLinha {
  estado: EstadoAtendimento;
  contagem: number;
}

export interface PerdaPorMotivoLinha {
  motivo: MotivoPerda;
  contagem: number;
}

export interface MotivoEscaladaLinha {
  motivo: string;          // texto livre, exato
  contagem: number;
}

export interface MotivosEscalada {
  top5: MotivoEscaladaLinha[];
  outros_total: number;
  total: number;
}

export interface ProfissionalRanking {
  modelo: ModeloResumoDashboard;
  volume: number;
  fechamentos: number;
  valor_bruto_brl: number;
  taxa_conversao_pct: number | null;
}

export interface DashboardResumo {
  filtro_aplicado: FiltroAplicado;
  janela_comparacao: JanelaComparacao | null;     // null quando histórico insuficiente
  pix_em_revisao_pendentes_total: number;
  kpis_periodo: KpisPeriodo;
  kpis_periodo_anterior: KpisPeriodo | null;      // null quando janela_comparacao é null
  funil_estados: FunilEstadoLinha[];              // sempre 8 entradas, ordem canônica
  perdas_por_motivo: PerdaPorMotivoLinha[];       // só motivos com contagem > 0
  motivos_escalada: MotivosEscalada;
  profissionais: ProfissionalRanking[];
  servidor_em: string;                            // ISO 8601
}

export interface EscaladaCompletaLinha {
  motivo: string;
  contagem: number;
}

export interface DashboardEscaladasResponse {
  filtro_aplicado: FiltroAplicado;
  motivos: EscaladaCompletaLinha[];               // todos, ordenados por contagem DESC, motivo ASC
}
```

### Mapeamento backend → resposta

| Campo | Origem em `barravips.*` |
|---|---|
| `pix_em_revisao_pendentes_total` | `COUNT FROM comprovantes_pix WHERE decisao_pipeline='em_revisao' AND decisao_final IS NULL` (filtrado por modelo via join quando aplicável) |
| `kpis_periodo.fechamentos` | `atendimentos` com `estado='Fechado'` join `eventos` tipo `fechado_registrado` na janela; `SUM(valor_final)` para bruto |
| `kpis_periodo.perdas.contagem` | join `eventos` tipo `perdido_registrado` na janela |
| `kpis_periodo.taxa_conversao_pct` | derivado de fechamentos/perdas |
| `kpis_periodo.escaladas.contagem` | `COUNT FROM escaladas WHERE aberta_em` na janela |
| `funil_estados[*]` | `atendimentos.estado` agrupado, com `created_at` na janela |
| `perdas_por_motivo[*]` | `atendimentos` perdidos na janela `GROUP BY motivo_perda` |
| `motivos_escalada.top5` | `escaladas.motivo` `GROUP BY motivo` `ORDER BY count DESC, motivo ASC LIMIT 5` na janela |
| `profissionais[*]` | `atendimentos GROUP BY modelo_id` na janela; ranking com fechados/valor/taxa de §9.7 |

---

## 12. Contrato de API

### 12.1 `GET /api/dashboard`

Headers e tratamento de erro: fundação §7.

Query:

| Parâmetro | Tipo | Uso |
|---|---|---|
| `periodo` | string | `hoje` / `7d` / `30d` / `custom` (default `7d`) |
| `de` | string opcional | obrigatório quando `periodo=custom`; `YYYY-MM-DD` |
| `ate` | string opcional | obrigatório quando `periodo=custom`; `YYYY-MM-DD` |
| `modelo_id` | uuid opcional | filtra por modelo; ausente = todas |

**Resposta 200:**
```json
{
  "filtro_aplicado": {
    "periodo": "7d",
    "de": "2026-04-25",
    "ate": "2026-05-01",
    "modelo_id": null
  },
  "janela_comparacao": { "de": "2026-04-18", "ate": "2026-04-24" },
  "pix_em_revisao_pendentes_total": 2,
  "kpis_periodo": {
    "taxa_conversao_pct": 73.3,
    "fechamentos": { "contagem": 11, "valor_bruto_brl": 18750.00, "valor_medio_brl": 1704.55 },
    "perdas": { "contagem": 4 },
    "escaladas": { "contagem": 7 }
  },
  "kpis_periodo_anterior": {
    "taxa_conversao_pct": 66.7,
    "fechamentos": { "contagem": 8, "valor_bruto_brl": 12000.00, "valor_medio_brl": 1500.00 },
    "perdas": { "contagem": 4 },
    "escaladas": { "contagem": 9 }
  },
  "funil_estados": [
    { "estado": "Novo", "contagem": 18 },
    { "estado": "Triagem", "contagem": 11 },
    { "estado": "Qualificado", "contagem": 9 },
    { "estado": "Aguardando_confirmacao", "contagem": 6 },
    { "estado": "Confirmado", "contagem": 10 },
    { "estado": "Em_execucao", "contagem": 4 },
    { "estado": "Fechado", "contagem": 11 },
    { "estado": "Perdido", "contagem": 4 }
  ],
  "perdas_por_motivo": [
    { "motivo": "preco", "contagem": 2 },
    { "motivo": "sumiu", "contagem": 1 },
    { "motivo": "fora_de_area", "contagem": 1 }
  ],
  "motivos_escalada": {
    "top5": [
      { "motivo": "Dúvida operacional", "contagem": 3 },
      { "motivo": "Risco — local não conhecido", "contagem": 2 },
      { "motivo": "Política comercial", "contagem": 1 },
      { "motivo": "Conflito de agenda", "contagem": 1 }
    ],
    "outros_total": 0,
    "total": 7
  },
  "profissionais": [
    {
      "modelo": { "id": "01950000-0000-7000-8000-000000000001", "nome": "Júlia" },
      "volume": 73,
      "fechamentos": 11,
      "valor_bruto_brl": 18750.00,
      "taxa_conversao_pct": 73.3
    }
  ],
  "servidor_em": "2026-05-01T17:32:11-03:00"
}
```

**Erros:** 422 quando filtros inválidos; 404 quando `modelo_id` inexistente. Padrão da fundação §7.

### 12.2 `GET /api/dashboard/escaladas`

Lazy fetch ao abrir o `DialogTodasEscaladas`.

Query: mesmas chaves do §12.1.

**Resposta 200:**
```json
{
  "filtro_aplicado": { "periodo": "7d", "de": "2026-04-25", "ate": "2026-05-01", "modelo_id": null },
  "motivos": [
    { "motivo": "Dúvida operacional", "contagem": 3 },
    { "motivo": "Risco — local não conhecido", "contagem": 2 },
    { "motivo": "Política comercial", "contagem": 1 },
    { "motivo": "Conflito de agenda", "contagem": 1 }
  ]
}
```

> **Pré-requisito:** ambos os endpoints existem e foram testados em `api/` antes de codificar a tela.

---

## 13. Realtime — específico desta tela

### 13.1 Subscriptions

Tabelas observadas (helper fundação §8.2):

- `atendimentos` — afeta funil, KPIs de fechamento/perda, ranking de profissionais.
- `comprovantes_pix` — afeta tile de Pix em revisão pendentes.
- `escaladas` — afeta KPI de escaladas e top 5 de motivos.

```ts
const cleanup = subscribeTabelas('dashboard',
  ['atendimentos', 'comprovantes_pix', 'escaladas'],
  debouncedRefetch);
```

> **Não** subscrever `eventos` — alta cardinalidade; o backend desnormaliza decisões relevantes nas três tabelas observadas (fechamento atualiza `atendimentos.estado/valor_final`; perdido atualiza `atendimentos.estado/motivo_perda`; escalada nasce em `escaladas`). Consistente com Tela 05 §13.1.

### 13.2 Refetch e refresh JWT

Padrão da fundação §§6.3, 8.3, 8.4. Sem comportamento adicional específico desta tela. Quando o filtro muda durante um refetch em vôo, descartar a resposta anterior (`AbortController` na próxima chamada).

### 13.3 Tabelas requeridas na publicação Realtime

`atendimentos`, `comprovantes_pix`, `escaladas` precisam estar em `supabase_realtime` (fundação §13.4). `escaladas` ainda **não** estava na lista da fundação — adicionar antes desta tela (ver §14).

---

## 14. Mudanças estruturais necessárias

| Antes | Depois | Ação |
|---|---|---|
| `interface/src/app/(interface)/dashboard/` ausente ou stub | rota real | criar `page.tsx` `"use client"` |
| n/a | hook próprio | criar `interface/src/hooks/useDashboard.ts` |
| n/a | tipos próprios | criar `interface/src/tipos/dashboard.ts` |
| n/a | componentes próprios | criar pasta `interface/src/components/dashboard/` |
| `escaladas` fora da publicação `supabase_realtime` | dentro | adicionar à publicação antes desta tela; atualizar fundação §13.4 e helper de tipos `RealtimeTabela` (§8.2) para incluir `'escaladas'` |
| Tela 02 não expõe filtro `motivo_escalada` na toolbar nem aceita query string | suporte mínimo via query string | adicionar leitura do query param `motivo_escalada` no hook da Tela 02 (filtro server-side prefix-match exato) — sem necessariamente mostrar o controle na toolbar do P0. Ver §17.2 sobre limite. |
| Tela 02 não aceita query `motivo_perda` | aceitar via query string | adicionar leitura do query param `motivo_perda` no hook da Tela 02 quando `estado=Perdido`. Mesma estratégia. |

### 14.1 Navegações disparadas pela tela

| Trigger | Destino |
|---|---|
| Botão "Ir para fila" do tile de Pix | `/pix?status=em_revisao` |
| Click em barra do funil | `/atendimentos?estado={Estado}` |
| Click em linha de "Perdas por motivo" | `/atendimentos?estado=Perdido&motivo_perda={motivo}` |
| Click em linha de "Motivos de escalada" (top 5) | `/atendimentos?ia_pausada=true&motivo_escalada={texto-encoded}` |
| Click em "Outros (N)" das escaladas | abre `DialogTodasEscaladas` (não navega) |
| Linha do dialog "Todas escaladas" | `/atendimentos?ia_pausada=true&motivo_escalada={texto-encoded}` (fecha o dialog) |
| Click em linha do ranking de profissionais | `/modelos?modelo={id}&aba=perfil` |
| CTA "Cadastrar modelo" do empty state | `/modelos` |

---

## 15. Critérios de aceite específicos

> Critérios estruturais (lint, build, dev, mobile blocker, foco, dark, primary único, vocabulário, skeletons, 401, JWT refresh, Lighthouse) vêm da fundação §14. Aqui só os específicos da tela.

- [ ] AC-1 — `/dashboard` carrega com filtros default `periodo=7d`, `modelo_id=null`.
- [ ] AC-2 — Toolbar mostra 3 chips de preset + chip "Personalizado…" + select de modelo.
- [ ] AC-3 — Click em "Personalizado…" abre `DialogRangeCustom`; aplicar atualiza URL para `?periodo=custom&de=...&ate=...`.
- [ ] AC-4 — `DialogRangeCustom` bloqueia "Aplicar" quando `de > ate`, `ate > today` ou `(ate-de) > 90 dias`, com mensagem inline.
- [ ] AC-5 — Recarregar a página com `?periodo=30d` ou `?periodo=custom&de=...&ate=...` reidrata a tela com os filtros corretos.
- [ ] AC-6 — Cabeçalho mostra rótulo "PERÍODO" + intervalo absoluto em mono-pt-BR.
- [ ] AC-7 — Tile destacado de Pix em revisão pendentes mostra a contagem snapshot atual com label "AGORA"; botão "Ir para fila" navega para `/pix?status=em_revisao`. Sem propagação de período.
- [ ] AC-8 — Tile de Pix com 0 pendências mostra valor `0`, sem borda lateral, com botão desabilitado e tooltip apropriado.
- [ ] AC-9 — 4 tiles de KPI exibem Conversão, Fechamentos, Perdas e Atendimentos escalados, com valores formatados em pt-BR e indicador de tendência ao lado.
- [ ] AC-10 — Tile Conversão mostra `—` quando `fechamentos.contagem + perdas.contagem = 0` (sem indicador de tendência).
- [ ] AC-11 — Tile Fechamentos exibe linha auxiliar com bruto e ticket médio formatados em BRL.
- [ ] AC-12 — IndicadorTendencia mostra `↑`/`↓`/`=` + delta % com polaridade direta para Conversão/Fechamentos e polaridade invertida para Perdas/Escaladas (cor verde quando ↓, vermelha quando ↑).
- [ ] AC-13 — IndicadorTendencia exibe chip "novo" em `--gold-500` quando base anterior é 0 e atual > 0.
- [ ] AC-14 — IndicadorTendencia exibe `—` em `--text-muted` quando ambos atuais e anteriores são 0.
- [ ] AC-15 — Funil de estados renderiza sempre as 8 barras na ordem canônica, mesmo com 0 atendimentos.
- [ ] AC-16 — Cada barra tem label, barra com largura proporcional ao maior valor, contagem em mono e percentual sobre o total.
- [ ] AC-17 — Estados `Fechado` e `Perdido` usam preenchimento `--success-500` e `--danger-500` respectivamente.
- [ ] AC-18 — Click em qualquer barra navega para `/atendimentos?estado={Estado}` sem propagar `periodo` ou `modelo_id`.
- [ ] AC-19 — Bloco "Perdas por motivo" mostra apenas motivos com contagem > 0, com barra preenchida em `--danger-500`; vazio mostra `✓ Sem perdas no período.`.
- [ ] AC-20 — Click em linha de perda navega para `/atendimentos?estado=Perdido&motivo_perda={motivo}`.
- [ ] AC-21 — Bloco "Motivos de escalada" mostra top 5 + linha "Outros (N)" quando aplicável; total no rótulo do título.
- [ ] AC-22 — Linha "Outros (N)" abre `DialogTodasEscaladas` que faz lazy fetch em `GET /api/dashboard/escaladas` com os mesmos filtros.
- [ ] AC-23 — Click em motivo de escalada (top 5 ou dialog) navega para `/atendimentos?ia_pausada=true&motivo_escalada={texto-encoded}`.
- [ ] AC-24 — Bloco "Profissionais mais procuradas" exibe tabela com colunas: posto, modelo, volume, fechamentos, valor bruto, conversão.
- [ ] AC-25 — No P0 com 1 piloto, ranking renderiza 1 linha com tudo zerado quando não há atendimentos no período.
- [ ] AC-26 — Click em linha do ranking navega para `/modelos?modelo={id}&aba=perfil`.
- [ ] AC-27 — Mudança de qualquer filtro atualiza a URL via `router.replace` e refaz fetch sem skeleton.
- [ ] AC-28 — Insert/update em `atendimentos`, `comprovantes_pix` ou `escaladas` no banco dispara refetch debounced 250ms automaticamente.
- [ ] AC-29 — Inserir manualmente um `comprovantes_pix` com `decisao_pipeline='em_revisao'` no banco faz o tile de Pix incrementar sem reload.
- [ ] AC-30 — Mudar `atendimentos.estado` de `Aguardando_confirmacao` para `Fechado` com `valor_final` no período faz a barra `Fechado` crescer e o tile Fechamentos atualizar.
- [ ] AC-31 — `usePathname` corretamente marca "Dashboard" como item ativo na sidebar com cor `--gold-500`.

---

## 16. Checklist de implementação

> Setup compartilhado (fundação §13) executado uma vez no projeto.

### 16.1 Pré-requisitos da tela

- [ ] CL-1 — Endpoint `GET /api/dashboard` existe e retorna o JSON de §12.1, respeitando `periodo`/`de`/`ate`/`modelo_id`.
- [ ] CL-2 — Endpoint `GET /api/dashboard/escaladas` existe e retorna o JSON de §12.2.
- [ ] CL-3 — Backend valida limites (custom ≤ 90 dias; `ate ≤ today` em BRT) e responde 422 com `detail`.
- [ ] CL-4 — Tabela `escaladas` adicionada à publicação `supabase_realtime`; fundação §13.4 e helper `RealtimeTabela` em `lib/realtime.ts` atualizados.
- [ ] CL-5 — Telas 02 e 05 aceitam query strings `motivo_perda` e `motivo_escalada` (filtros novos no hook da Tela 02 conforme §14).
- [ ] CL-6 — Itens de fundação §13 prontos (deps, shadcn components, env, RLS).

### 16.2 Estrutura

- [ ] CL-7 — Criar `interface/src/app/(interface)/dashboard/page.tsx` (`"use client"`).
- [ ] CL-8 — Criar `interface/src/hooks/useDashboard.ts` (fetch + Realtime + debounced refetch + `AbortController` em troca de filtro).
- [ ] CL-9 — Criar `interface/src/tipos/dashboard.ts` com os tipos de §11.
- [ ] CL-10 — Criar componentes em `interface/src/components/dashboard/`.

### 16.3 Implementação

- [ ] CL-11 — Cabeçalho conforme §5.1 (com rótulo de intervalo absoluto).
- [ ] CL-12 — Toolbar conforme §5.2 + `DialogRangeCustom` conforme §6.1 (com validações §10).
- [ ] CL-13 — Tile destacado de Pix em revisão pendentes conforme §5.3.
- [ ] CL-14 — KPIs do período conforme §5.4 + `IndicadorTendencia` conforme §5.4.3.
- [ ] CL-15 — Funil de estados conforme §5.5.
- [ ] CL-16 — Bloco "Perdas por motivo" conforme §5.6.1.
- [ ] CL-17 — Bloco "Motivos de escalada" conforme §5.6.2 + `DialogTodasEscaladas` conforme §6.2.
- [ ] CL-18 — Ranking de profissionais conforme §5.7.
- [ ] CL-19 — Empty states inline em todos os blocos com 0.
- [ ] CL-20 — A11y conforme §7.5 (ARIA labels, roles, ordem de Tab).

### 16.4 Verificação

- [ ] CL-21 — Lint passa: `pnpm lint`.
- [ ] CL-22 — Build passa: `pnpm build`.
- [ ] CL-23 — Subir backend (`make dev` em `api/`) + frontend (`pnpm dev`) e validar AC-1..31.
- [ ] CL-24 — Testar fluxos Realtime (AC-29, AC-30) inserindo/atualizando registros via Supabase Studio.
- [ ] CL-25 — Testar deep link com `?periodo=custom&de=2026-04-01&ate=2026-04-30` em janela anônima.
- [ ] CL-26 — Lighthouse acessibilidade ≥ 95 (EST-13 da fundação).

---

## 17. Vetos locais e pontos imutáveis da tela

### 17.1 Veto local declarado

- **Fundação §9.6** ("apenas 1 primary por tela"): nesta tela, **a tela não tem nenhum primary**. Justificativa: Dashboard é leitura analítica pura; não há ação canônica humana — todos os CTAs são navegação contextual em `secondary` ou `ghost`. Forçar um primary global inventaria CTA artificial. **Aprovado em:** conversa de QA Tela 07 (2026-05-01).

### 17.2 Pontos imutáveis específicos

- ❌ Sem chart lib externa no P0 (recharts, victory, chart.js, etc.). Barras horizontais do funil e dos breakdowns são `<div>` + Tailwind. Reabrir decisão se P1 introduzir séries temporais.
- ❌ Sem export PDF/CSV no P0.
- ❌ Sem drill-down temporal (gráfico de linha por dia/hora) no P0.
- ❌ Sem cluster/normalização de `escaladas.motivo` — agrupamento é por **string exata** no P0. Decisão consciente: motivos vêm da IA e Fernando precisa ver o vocabulário real para ajustar prompts; clustering automático esconderia variações relevantes. Reabrir quando o volume justificar análise semântica.
- ❌ Sem deep link `/dashboard/{algo}` — tudo via query string (`?periodo=...`).
- ❌ Sem cachear `/api/dashboard` no client (fundação §12).
- ❌ Sem ações de escrita; nenhum `AlertDialog` (apenas dialogs de leitura/configuração de filtro).
- ❌ Não propagar `periodo` ou `modelo_id` em CTAs de saída (§9.6). Reabrir apenas se a tela destino ganhar filtro temporal nativo.
- ❌ Não computar comparação ou taxa de conversão no front. Backend é a fonte (consistente com Tela 01 §17.2 sobre `previsao_termino`).
- ❌ Não esconder tile, barra ou linha com valor zero quando ele faz parte do vocabulário canônico (KPIs, funil, profissionais). Esconder só motivos de perda/escalada com 0 (não fazem parte de vocabulário fechado relevante).
- ❌ Não SSR/RSC desta tela (Realtime exige client; fundação §12).

---

## 18. Pontos em aberto

Nenhum ponto em aberto após alinhamento com o usuário em 2026-05-01.

---

## Anexo A — Wireframe textual

```
┌─────────────────┬───────────────────────────────────────────────────────────────┐
│ Barra Vips      │ Dashboard                          PERÍODO  ·  25 abr – 1 mai │
│  (sidebar       │                                                               │
│   compartilhada │ [ Hoje ] [ 7 dias ] [ 30 dias ] [ Personalizado… ]  [Modelo▾] │
│   — fundação    │                                                               │
│   §5.4)         │ ┌───────────────────────────────────────────────────────────┐ │
│                 │ │┃ PIX EM REVISÃO PENDENTES (AGORA)        [ Ir para fila →]│ │
│                 │ │┃ 2                                                        │ │
│                 │ │┃ Não filtrado por período — fila operacional ativa.       │ │
│                 │ └───────────────────────────────────────────────────────────┘ │
│                 │                                                               │
│                 │ No período                                  vs período anterior│
│                 │ ┌──────────┬──────────┬──────────┬──────────────────────────┐ │
│                 │ │CONVERSÃO │FECHAM.   │PERDAS    │ATEND. ESCALADOS          │ │
│                 │ │  73%     │  11      │  4       │  7                       │ │
│                 │ │ 11/15    │ R$ 18.7k │          │                          │ │
│                 │ │ ↑ +6,6pp │ ↑ +37,5% │ = 0%     │ ↓ −22,2%  (verde)        │ │
│                 │ └──────────┴──────────┴──────────┴──────────────────────────┘ │
│                 │                                                               │
│                 │ Volume por estado                       73 atendimentos       │
│                 │ ┌───────────────────────────────────────────────────────────┐ │
│                 │ │ Novo                  ████████████░░░░░ 18  (24%)         │ │
│                 │ │ Triagem               ███████░░░░░░░░░░ 11  (15%)         │ │
│                 │ │ Qualificado           ██████░░░░░░░░░░░  9  (12%)         │ │
│                 │ │ Aguardando confirma.  ████░░░░░░░░░░░░░  6  ( 8%)         │ │
│                 │ │ Confirmado            ███████░░░░░░░░░░ 10  (14%)         │ │
│                 │ │ Em execução           ███░░░░░░░░░░░░░░  4  ( 5%)         │ │
│                 │ │ Fechado               ██████████████░░░ 11  (15%)  (verde)│ │
│                 │ │ Perdido               █████░░░░░░░░░░░░  4  ( 5%)  (verm.)│ │
│                 │ └───────────────────────────────────────────────────────────┘ │
│                 │                                                               │
│                 │ ┌─────────────────────────────┐ ┌─────────────────────────┐   │
│                 │ │ Perdas por motivo           │ │ Motivos de escalada   7 │   │
│                 │ │ Preço            ████  2 50%│ │ Dúvida operacional    3 │   │
│                 │ │ Sumiu            ██    1 25%│ │ Risco — local não c.  2 │   │
│                 │ │ Fora da área     ██    1 25%│ │ Política comercial    1 │   │
│                 │ │                             │ │ Conflito de agenda    1 │   │
│                 │ │                             │ │                         │   │
│                 │ └─────────────────────────────┘ └─────────────────────────┘   │
│                 │                                                               │
│                 │ Profissionais mais procuradas                                 │
│                 │ ┌───────────────────────────────────────────────────────────┐ │
│                 │ │ #1  Júlia    73 vol.   11 fech.   R$ 18.750,00   73%   > │ │
│                 │ └───────────────────────────────────────────────────────────┘ │
└─────────────────┴───────────────────────────────────────────────────────────────┘
```

— FIM —
