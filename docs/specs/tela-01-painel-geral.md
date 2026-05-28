# Tela 01 — Painel Geral

> **Herda decisões de** `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto local declarado em §17. Não repetir aqui o que está na fundação.

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome | Painel Geral |
| Slug | `painel-geral` |
| Rota | `/` (raiz autenticada) |
| Arquivo Next.js | `interface/src/app/(interface)/page.tsx` |
| Tipo | Client Component (`"use client"`) — Realtime exige client (fundação §12 ❌ SSR/RSC com Realtime) |
| Hook próprio | `interface/src/hooks/usePainelResumo.ts` |
| Tipos | `interface/src/tipos/painel.ts` |
| Componentes próprios | `interface/src/components/painel/{HeaderPainel,CardDestaque,TileMetrica,LinhaAgenda,AtalhoContextual}.tsx` |

---

## 2. Objetivo

Dar a Fernando uma visão operacional rápida do dia: ações humanas pendentes (Pix em revisão, handoff da IA, modelo em atendimento com tempo previsto expirado), métricas do dia, agenda do dia e atalhos contextuais. **A próxima ação que Fernando precisa tomar deve ser perceptível em até 3 segundos após carregar a tela.**

Citação literal de `docs/mvp/06-dados-interfaces.md` §4.1: *"Tela inicial. Visão operacional rápida do dia."*

---

## 3. Contexto funcional

- **Único usuário no P0:** Fernando.
- **Única modelo ativa esperada no P0:** 1 piloto. Tela é defensiva contra 0 ou múltiplas (ver §9.6).
- **Origem dos dados:** endpoint agregado `GET /api/painel/resumo` (a ser implementado pelo backend antes desta tela).
- **Realtime:** assinatura em 4 tabelas (§13).
- **Escrita inline:** apenas `Devolver para IA` — uma única ação. Resto é leitura.

---

## 4. Fluxo do usuário

### 4.1 Caminho feliz

1. Fernando acessa `/`. Middleware (fundação §6.1) garante autenticação.
2. Tela monta com 4 skeletons (cards, métricas, agenda; atalhos só após `success`).
3. `useEffect` chama `GET /api/painel/resumo` via `lib/api.ts`; em paralelo, abre 4 subscriptions Supabase Realtime (§13.1) e registra listener `onAuthStateChange` (fundação §6.3).
4. Snapshot chega → skeletons substituídos pelo conteúdo.
5. Cards de destaque ordenados por urgência fixa (Pix → Handoff → Modelo expirado).
6. Click em card → navega para `/atendimentos/{id}`.
7. Click em "Devolver para IA" (apenas card amarelo) → AlertDialog → confirma → `POST /api/atendimentos/{id}/devolver` → toast `success`. Card desaparece via Realtime.
8. Métricas e agenda atualizam ao vivo conforme eventos chegam (refetch debounced 250ms).

### 4.2 Caminhos alternativos específicos da tela

| Cenário | Comportamento |
|---|---|
| 0 modelos ativas | Cabeçalho mostra "Nenhuma modelo ativa" em `--text-muted`; demais blocos seguem com seus dados. |
| Múltiplas modelos ativas | Cabeçalho mostra a primeira por `created_at ASC` + ícone `triangle-alert --warn-500` 16px com tooltip "há N modelos ativas". |
| Sem pendências, sem agenda, métricas zeradas | Cada bloco renderiza seu empty-state próprio (§5). |

> Cenários de auth, 401, mobile, erro de rede, refresh JWT são tratados pela fundação (§§6, 7, 5.3, 9.2).

---

## 5. Layout detalhado dos blocos próprios

> Sidebar e shell de 2 colunas vêm da fundação §5. Esta seção descreve apenas o conteúdo do `<main>` da rota `/`.

Sequência vertical dentro do `<main>`:

```
[Cabeçalho da página]
[Cards de destaque]
[Métricas do dia]
[Agenda do dia]
[Atalhos contextuais]
```

### 5.1 Cabeçalho da página

- Container: `padding: spacing.6 spacing.6 spacing.4`; flex row, `justify-content: space-between; align-items: center`.
- **Esquerda:** título "Painel" em **Cormorant Garamond `display-lg`** (40px, peso 500, `--text-primary`).
- **Direita:** stack horizontal com gap `spacing.5`:

| Bloco | Label | Valor |
|---|---|---|
| Modelo ativa | `caption --text-muted` "MODELO" maiúsculo | nome em `heading-md --text-primary`. Se 0: "Nenhuma modelo ativa" em `--text-muted`. Se múltiplas: nome + `triangle-alert --warn-500` + tooltip "há N ativas". |
| Data/hora | `caption --text-muted` "AGORA" maiúsculo | `heading-md --text-primary` em mono — `30 abr 2026 · 14:32` (formato `formatData` + " · " + `formatHorario`). Re-render a cada 60s via `setInterval` em `useEffect` próprio. |

### 5.2 Bloco "Cards de destaque"

- **Título da seção:** `heading-md --text-primary` "Pendências humanas" + à direita, quando há pelo menos 1 card, `caption --text-muted` "{N} aguardando ação".
- Padding seção: `spacing.5 spacing.6 spacing.3`.
- **Grid:** 1 coluna até `xl`; 2 colunas a partir de `xl`. Gap `spacing.4`.
- **Ordem fixa:** Pix em revisão → Handoff IA → Modelo expirado. Dentro de cada categoria: FIFO por `ia_pausada_em ASC` (mais antigo primeiro).

#### 5.2.1 Card individual

Estrutura (DESIGN.md §Cards de decisão; fundação §4.6):

```
[border-left: 3px solid var(--warn-500)]
HEADER:  [Badge estado] · #N (mono-sm --text-muted) · cliente (heading-md --text-primary)
BODY:    MOTIVO (caption --text-muted) <texto> (body-sm --text-primary)
         PRÓXIMA AÇÃO (caption --text-muted) <texto> (body-sm --text-muted)
AÇÃO:    [button-primary "Devolver para IA"]  ← APENAS card de modelo expirado
FOOTER:  Em handoff há X · Responsável: Fernando|modelo  (caption --text-muted)
```

- Container: `--card`, `rounded.lg`, `padding: spacing.5`, `border-left: 3px solid var(--warn-500)` (todos os 3 tipos).
- **Mapeamento badge por tipo:**

| `ia_pausada_motivo` | Badge variant | Label badge | Ícone extra |
|---|---|---|---|
| `pix_em_revisao` | `revisao` | "Em revisão" | — |
| `handoff_ia` | `handoff` | "Em handoff" | — |
| `modelo_em_atendimento` (expirado) | `paused` | "Pausada" | `clock-alert --warn-500` 16px à direita do badge |

- **Header:** flex row, gap `spacing.3`, `align-items: center`. Cliente: `cliente_nome` se existir; senão, `cliente_telefone_formatado` em `mono-sm --text-primary` (formatador da fundação §10.1).
- **Footer:** padding-top `spacing.3`, separado por `1px var(--border)`. Tempo via `formatTempoRelativo(ia_pausada_em)` da fundação §10.4.
- **Card inteiro é clicável** (exceto o botão): `<article role="link" tabIndex={0}>`, hover `--ink-200`, navega para `/atendimentos/{atendimento_id}`. Enter/Space ativam.
- **Botão "Devolver para IA":** apenas em cards `modelo_em_atendimento`. `e.stopPropagation()` no click. Abre AlertDialog (§6).

#### 5.2.2 Empty state

Quando `cards_destaque.length === 0`:

```
[card --card --rounded.lg --padding spacing.5, sem borda lateral]
✓ Sem pendências humanas no momento.
Os cards aparecem quando a IA pausar (Pix em revisão, escalada ou tempo previsto da modelo expirado).
```

- Ícone `CheckCircle2 --success-500` 20px à esquerda da primeira linha.
- Texto principal: `body-md --text-primary`. Auxiliar: `body-sm --text-muted`.

### 5.3 Bloco "Métricas do dia"

- Título: `heading-md --text-primary` "Hoje" + à direita `caption --text-muted` `{Quinta · 30 abr 2026}` (capitalização do dia da semana).
- Padding seção: `spacing.5 spacing.6`.
- **Grid:** 4 colunas desde `lg`. Gap `spacing.4`.
- **Tiles** (cada um `<Card>` shadcn `--card --rounded.lg --padding spacing.5`):

| # | Label (caption --text-muted maiúsculo) | Valor | Cor do número |
|---|---|---|---|
| 1 | ATENDIMENTOS ABERTOS | `metricas_dia.abertos` (inteiro) | `--text-primary` |
| 2 | FECHAMENTOS HOJE | `metricas_dia.fechamentos_hoje` (inteiro) | `--success-500` |
| 3 | PERDAS HOJE | `metricas_dia.perdas_hoje` (inteiro) | `--danger-500` |
| 4 | VALOR BRUTO HOJE | `formatBRL(metricas_dia.valor_bruto_hoje_brl)` | `--text-primary` |

- Estrutura HTML semântica: `<dl><dt>{label}</dt><dd>{valor}</dd></dl>`.
- Valor zero **renderiza normalmente** (`0`, `R$ 0,00`); sem traço, sem esconder.
- Tipografia do valor: `display-lg` (40px, peso 500, Inter). Tipografia do label: `caption`.

### 5.4 Bloco "Agenda do dia"

- Título: `heading-md --text-primary` "Agenda de hoje".
- Padding seção: `spacing.5 spacing.6`.
- Container: `<Card --card --rounded.lg>` com lista vertical.
- **Linha de bloqueio** (altura 56px, padding `spacing.3 spacing.4`, separadas por `1px var(--border)`):

```
[HORÁRIO mono-sm] [BADGE estado] [Cliente body-sm] [Origem ícone]    [→ ChevronRight]
```

- **HORÁRIO:** `mono-sm --text-primary` formato `HH:MM–HH:MM` (ex.: `14:00–16:00`). Se `inicio === fim`, só `HH:MM`. Usa `formatHorario` da fundação §10.3.
- **BADGE estado:**

| Estado | Variante | Label | Efeito visual extra |
|---|---|---|---|
| `bloqueado` | `paused` | "Bloqueado" | — |
| `em_atendimento` | `active` | "Em atendimento" | — |
| `concluido` | `closed` | "Concluído" | — |
| `cancelado` | `paused` | "Cancelado" | linha inteira com `text-decoration: line-through` e opacidade 0.6 |

- **Cliente:** se vinculado a atendimento, `cliente_nome`. Se avulso (`atendimento_id IS NULL`), mostra `observacao` em `--text-muted` ou "Bloqueio manual" se observação ausente.
- **Ícone origem** (16px Lucide `--text-muted`, com `<Tooltip>`): `Bot` para `ia` (tooltip "IA"), `User` para `painel_fernando` (tooltip "Fernando"), `Hand` para `manual` (tooltip "Manual").
- **ChevronRight 16px à direita** sinaliza clicabilidade.
- **Click na linha:** navega para `/agenda?data=YYYY-MM-DD&bloqueio={id}`.
- **Ordenação:** `inicio ASC`.

#### 5.4.1 Empty state

```
[card --card --rounded.lg --padding spacing.5]
🗓  Nenhum horário reservado hoje.
[ button-ghost ] Bloquear janela manualmente
```
- Ícone `CalendarOff` 20px `--text-muted`.
- `body-md --text-primary` na linha 1.
- Botão ghost leva para `/agenda?action=bloquear`.

### 5.5 Bloco "Atalhos contextuais"

- Sem título; separador horizontal `1px var(--border)` acima.
- Padding `spacing.5 spacing.6`.
- Flex row wrap, gap `spacing.3`.
- Cada atalho = `<button>` (variante conforme tabela), texto `heading-md`, ícone Lucide 16px à esquerda, padding `spacing.3 spacing.5`, `rounded.md`.

| Atalho | Visível quando | Texto | Ícone | Variante | Destino |
|---|---|---|---|---|---|
| Pix em revisão | `metricas.pix_em_revisao_pendentes > 0` | "Ver {N} Pix em revisão" | `Receipt` | secondary | `/pix?status=em_revisao` |
| Atendimentos abertos | `metricas.abertos > 0` | "Ver {N} atendimentos abertos" | `MessagesSquare` | secondary | `/atendimentos` |
| Conectar WhatsApp | `modelo_ativa.evolution_instance_id IS NULL` | "Conectar WhatsApp da modelo" | `QrCode` | **primary** | `/modelos/{modelo_ativa.id}?aba=perfil` |
| Bloquear janela | sempre | "Bloquear janela" | `CalendarPlus` | secondary | `/agenda?action=bloquear` |

- **Ordem:** se "Conectar WhatsApp" estiver visível, vem primeiro. Senão, ordem da tabela.
- **Único `button-primary`** da tela é "Conectar WhatsApp" — aparece **apenas** quando `evolution_instance_id IS NULL`. Quando ele NÃO está visível, **a tela não tem nenhum primary** (decisão consciente; ver §17 veto local).

---

## 6. AlertDialog "Devolver para IA"

Padrão da fundação §9.5.

```
[AlertDialog --card --rounded.lg --padding spacing.5, max-w-md]

heading-lg --text-primary  | Devolver #142 para a IA?

body-md --text-secondary   | A IA voltará a responder o cliente assim que ele
                           | enviar a próxima mensagem. O motivo desta pausa
                           | ficará registrado no histórico de eventos.

flex row gap spacing.3, justify-end
[button-ghost] Cancelar  [button-primary] Confirmar devolução
```

Comportamento conforme fundação §9.5. Endpoint: `POST /api/atendimentos/{id}/devolver` (§12.2). Toast de sucesso: `Atendimento #{N} devolvido para a IA`.

---

## 7. Comportamentos esperados

### 7.1 Inicialização

`useEffect` no mount:

1. `fetch` via `api('/painel/resumo')` (fundação §7.1).
2. `subscribeTabelas('painel', ['atendimentos','comprovantes_pix','bloqueios','eventos'], debouncedRefetch)` (helper fundação §8.2).
3. Listener `onAuthStateChange` (fundação §6.3).
4. `setInterval` 60s para re-render do bloco data/hora.

Cleanup no unmount: cancela subscriptions, listener e interval.

### 7.2 Reconciliação Realtime

Conforme fundação §8.3 e §8.4: refetch debounced 250ms; sem patch local; sem skeleton em refetches subsequentes.

### 7.3 Click em card de destaque

- `<article>` é navegável por click e teclado (Enter, Space).
- Botão "Devolver para IA" usa `e.stopPropagation()`.
- Navegação: `router.push('/atendimentos/' + atendimento.id)`.

### 7.4 Devolução para IA

```
[click no botão] → [abre AlertDialog]
  → [confirma] → setLoading(true)
    → api.post('/atendimentos/{id}/devolver')
      → 200 → close dialog, toast.success "Atendimento #N devolvido para a IA"
      → 4xx → toast.error com {detail} (dialog ABERTO, botões reabilitados)
      → 401 → fundação §6.4 (signOut + redirect)
      → 5xx → toast.error genérico (dialog ABERTO)
```

### 7.5 Teclado / a11y

Ordem do Tab: itens da sidebar (fundação) → cabeçalho (sem foco no h1) → cards de destaque (cada um focável) → linhas de agenda (focáveis) → atalhos (focáveis). Tiles métricos não são focáveis (`<dl>`).

Roles ARIA:
- `<section aria-label="Pendências humanas">` no bloco de cards.
- `<section aria-label="Métricas de hoje">` no bloco de métricas (com `<dl>` interno).
- `<section aria-label="Agenda de hoje">` no bloco de agenda.
- `<section aria-label="Atalhos">` nos atalhos.

---

## 8. Estados específicos da tela

> Padrões gerais de loading/erro/empty na fundação §9.

| Estado | Quando | Aparência |
|---|---|---|
| `success-vazio (cards)` | `cards_destaque.length === 0` | Empty state §5.2.2 |
| `success-vazio (agenda)` | `agenda_dia.length === 0` | Empty state §5.4.1 |
| `success-zerado (métricas)` | tiles com 0 / R$ 0,00 | Tiles renderizam normalmente com 0 |
| `success-sem-modelo` | `modelo_ativa === null` | Cabeçalho "Nenhuma modelo ativa" |
| `success-multi-modelo` | `modelos_ativas_count > 1` | Cabeçalho com primeira + ícone aviso |
| `submitting` (Devolver IA) | request em vôo | Botão e Confirm desabilitados + spinner |

### 8.1 Skeletons específicos

- **Cards de destaque:** 2 cards-fantasma 120px altura, `--card --rounded.lg`, com 3 `Skeleton` empilhados (heading, body, footer).
- **Métricas:** 4 tiles 96px altura, cada com 2 `Skeleton` (label 16px, valor 36px).
- **Agenda:** card com 3 linhas-fantasma de 56px.
- **Atalhos:** sem skeleton (renderizam só após `success`).

---

## 9. Regras de negócio

### 9.1 Cards de destaque

- **Critério de inclusão:** atendimentos com `ia_pausada=true`. Sem corte temporal.
- **Tipos:** os 3 motivos canônicos de `ia_pausada_motivo` (`pix_em_revisao`, `modelo_em_atendimento`, `handoff_ia`). Outros motivos não geram cards.
- **Filtro adicional para `modelo_em_atendimento`:** inclui apenas se `expirado=true`. Backend deriva conforme fundação §10.5.
- **Ordem:** Pix em revisão → Handoff IA → Modelo expirado. FIFO por `ia_pausada_em ASC` interno.
- **Click no card:** navega para `/atendimentos/{id}`.
- **Botão inline "Devolver para IA":** **apenas** em cards de tipo `modelo_em_atendimento`. Pix em revisão exige Validar/Recusar na tela `/pix`; Handoff IA exige decisão na Central.

### 9.2 Métricas do dia

- **Janela:** `[hoje 00:00:00 BRT, hoje 23:59:59.999 BRT]`. Backend resolve com `AT TIME ZONE 'America/Sao_Paulo'`.
- `abertos` = `COUNT(atendimentos)` com `estado NOT IN ('Fechado', 'Perdido')`. **Sem corte por data.**
- `fechamentos_hoje` = `COUNT(atendimentos)` com `estado='Fechado'` E evento `fechado_registrado` hoje.
- `perdas_hoje` = análogo, `estado='Perdido'` + evento `perdido_registrado` hoje.
- `valor_bruto_hoje_brl` = `SUM(valor_final)` dos fechados hoje. Em BRL.
- `pix_em_revisao_pendentes` = `COUNT(comprovantes_pix)` com `decisao_pipeline='em_revisao'` E `decisao_final IS NULL`.

### 9.3 Agenda do dia

- **Filtro:** bloqueios cuja janela `[inicio, fim]` intersecta o dia atual em America/Sao_Paulo.
- **Ordem:** `inicio ASC`.
- **Estados exibidos:** todos os 4 (`bloqueado`, `em_atendimento`, `concluido`, `cancelado`).
- **Cancelados** aparecem riscados, opacidade 0.6.

### 9.4 Atalhos contextuais

Vide tabela em §5.5. **Sem regra adicional.**

### 9.5 Devolução para IA

- Permitida apenas para atendimentos com `ia_pausada=true` E `ia_pausada_motivo='modelo_em_atendimento'` (regra do Painel Geral; outros motivos exigem fluxos próprios).
- Backend valida (regra canônica em `docs/mvp/05-escalada-regras-ia.md` §4).
- Após devolução, IA não envia turno automático — apenas libera `ia_pausada=false`.

### 9.6 Modelo ativa

- Backend retorna `modelo_ativa` com a primeira modelo `status='ativa'` por `created_at ASC`, e `modelos_ativas_count` total.
- Se 0: `modelo_ativa = null`, `modelos_ativas_count = 0`.
- Se múltiplas: retorna a primeira + `modelos_ativas_count = N`.

---

## 10. Validações

| Onde | Validação | Falha |
|---|---|---|
| Front, antes de mostrar botão | `atendimento.ia_pausada === true && atendimento.ia_pausada_motivo === 'modelo_em_atendimento'` | Botão simplesmente não renderiza para outros casos. |
| Backend | Atendimento existe, `ia_pausada=true`, motivo é `modelo_em_atendimento` | 409 Conflict `{ detail: "Atendimento não está pausado por modelo_em_atendimento" }`. Front mostra toast com `detail`. |
| Backend | Usuário tem `papel='fernando'` | RLS + check; 403 Forbidden. Front mostra toast genérico "Sem permissão". |

---

## 11. Dados — tipos próprios da tela

Arquivo: `interface/src/tipos/painel.ts`.

```ts
export type IaPausadaMotivo = 'pix_em_revisao' | 'modelo_em_atendimento' | 'handoff_ia';
export type EstadoBloqueio = 'bloqueado' | 'em_atendimento' | 'concluido' | 'cancelado';
export type OrigemBloqueio = 'ia' | 'painel_fernando' | 'manual';

export interface ModeloAtiva {
  id: string;
  nome: string;
  evolution_instance_id: string | null;
}

export interface CardDestaque {
  atendimento_id: string;
  numero_curto: number;
  cliente_nome: string | null;
  cliente_telefone_formatado: string;     // backend formata via fundação §10.1
  ia_pausada_motivo: IaPausadaMotivo;
  motivo_escalada: string | null;          // texto livre da IA quando handoff_ia
  proxima_acao_esperada: string | null;
  responsavel_atual: 'IA' | 'Fernando' | 'modelo';
  ia_pausada_em: string;                   // ISO 8601
  previsao_termino: string | null;         // ISO 8601 (apenas modelo_em_atendimento)
  expirado: boolean;
}

export interface MetricasDia {
  abertos: number;
  fechamentos_hoje: number;
  perdas_hoje: number;
  valor_bruto_hoje_brl: number;
  pix_em_revisao_pendentes: number;
}

export interface LinhaAgenda {
  id: string;
  inicio: string;
  fim: string;
  estado: EstadoBloqueio;
  origem: OrigemBloqueio;
  cliente_nome: string | null;
  observacao: string | null;
  atendimento_id: string | null;
}

export interface PainelResumo {
  modelo_ativa: ModeloAtiva | null;
  modelos_ativas_count: number;
  cards_destaque: CardDestaque[];
  metricas_dia: MetricasDia;
  agenda_dia: LinhaAgenda[];
  servidor_em: string;                     // ISO 8601, hora atual do backend
}
```

### Mapeamento backend → resposta

| Campo | Origem em `barravips.*` |
|---|---|
| `modelo_ativa` | `modelos WHERE status='ativa' ORDER BY created_at ASC LIMIT 1` |
| `modelos_ativas_count` | `COUNT(*) FROM modelos WHERE status='ativa'` |
| `cards_destaque[*]` | `atendimentos WHERE ia_pausada=true` join `clientes`; filtragem por motivo §9.1; `previsao_termino`/`expirado` derivados conforme fundação §10.5 |
| `metricas_dia.abertos` | `COUNT FROM atendimentos WHERE estado NOT IN ('Fechado','Perdido')` |
| `metricas_dia.fechamentos_hoje` | join `eventos` tipo `fechado_registrado` no dia em BRT |
| `metricas_dia.perdas_hoje` | join `eventos` tipo `perdido_registrado` no dia em BRT |
| `metricas_dia.valor_bruto_hoje_brl` | `SUM(valor_final) FROM atendimentos` fechados hoje |
| `metricas_dia.pix_em_revisao_pendentes` | `COUNT FROM comprovantes_pix WHERE decisao_pipeline='em_revisao' AND decisao_final IS NULL` |
| `agenda_dia[*]` | `bloqueios` filtrados por intersecção com `today` em BRT, ordenados por `inicio` |

---

## 12. Contrato de API

### 12.1 `GET /api/painel/resumo`

Headers e tratamento de erro: fundação §7.

**Resposta 200:**
```json
{
  "modelo_ativa": {
    "id": "01950000-0000-7000-8000-000000000001",
    "nome": "Júlia",
    "evolution_instance_id": "inst_abc123"
  },
  "modelos_ativas_count": 1,
  "cards_destaque": [
    {
      "atendimento_id": "01950000-0000-7000-8000-000000000042",
      "numero_curto": 142,
      "cliente_nome": "Carlos M.",
      "cliente_telefone_formatado": "(21) 98765-4321",
      "ia_pausada_motivo": "pix_em_revisao",
      "motivo_escalada": null,
      "proxima_acao_esperada": "Validar Pix de R$ 200,00",
      "responsavel_atual": "Fernando",
      "ia_pausada_em": "2026-04-30T16:42:00-03:00",
      "previsao_termino": null,
      "expirado": false
    }
  ],
  "metricas_dia": {
    "abertos": 12,
    "fechamentos_hoje": 3,
    "perdas_hoje": 1,
    "valor_bruto_hoje_brl": 4500.00,
    "pix_em_revisao_pendentes": 2
  },
  "agenda_dia": [
    {
      "id": "01950000-0000-7000-8000-000000000077",
      "inicio": "2026-04-30T14:00:00-03:00",
      "fim": "2026-04-30T16:00:00-03:00",
      "estado": "bloqueado",
      "origem": "ia",
      "cliente_nome": "Carlos M.",
      "observacao": null,
      "atendimento_id": "01950000-0000-7000-8000-000000000042"
    }
  ],
  "servidor_em": "2026-04-30T17:32:11-03:00"
}
```

### 12.2 `POST /api/atendimentos/{id}/devolver`

Body: `{}`. **200** → `{ "ok": true }`. **409** → `{ "detail": "Atendimento não está pausado por modelo_em_atendimento" }`. Outros: padrão fundação §7.

> **Pré-requisito:** ambos os endpoints existem e foram testados em `api/` antes de codificar a tela.

---

## 13. Realtime — específico desta tela

### 13.1 Subscriptions

Tabelas observadas (helper fundação §8.2):

- `atendimentos` — refletir `ia_pausada`, `estado`, `valor_final`.
- `comprovantes_pix` — Pix em revisão entra/sai em tempo real.
- `bloqueios` — agenda do dia atualiza ao vivo.
- `eventos` — eventos de transição/escalada/devolução/registro invalidam todo o snapshot.

```ts
const cleanup = subscribeTabelas('painel',
  ['atendimentos', 'comprovantes_pix', 'bloqueios', 'eventos'],
  debouncedRefetch);
```

### 13.2 Refetch e refresh JWT

Padrão da fundação §§6.3, 8.3, 8.4. Sem comportamento adicional específico desta tela.

---

## 14. Mudanças estruturais necessárias

| Antes | Depois | Ação |
|---|---|---|
| `interface/src/app/page.tsx` (landing pública atual) | excluir | `rm` o arquivo |
| `interface/src/app/(interface)/interface/page.tsx` (stub atual) | excluir | `rm -rf` o diretório |
| n/a | `interface/src/app/(interface)/page.tsx` (Painel Geral) | criar |
| n/a | `interface/src/middleware.ts` | criar conforme fundação §6.1 |
| stub `lib/supabase.ts` | cliente real | criar conforme fundação §6.2 |
| `lib/api.ts` atual | fetcher tipado com 401 handler | substituir conforme fundação §7.1 |
| `(interface)/layout.tsx` atual (sidebar inline simples) | layout com `<Sidebar/>` real | substituir conforme fundação §5.4 |

### 14.1 Navegações disparadas pela tela

| Trigger | Destino |
|---|---|
| Click em card de destaque | `/atendimentos/{id}` |
| Click em linha de agenda | `/agenda?data=YYYY-MM-DD&bloqueio={id}` |
| Atalho "Pix em revisão" | `/pix?status=em_revisao` |
| Atalho "Atendimentos abertos" | `/atendimentos` |
| Atalho "Conectar WhatsApp" | `/modelos/{modelo_ativa.id}?aba=perfil` |
| Atalho "Bloquear janela" | `/agenda?action=bloquear` |
| Empty state da agenda → "Bloquear janela manualmente" | `/agenda?action=bloquear` |

---

## 15. Critérios de aceite específicos

> Critérios estruturais (lint, build, dev, mobile blocker, foco, dark, primary único, vocabulário, skeletons, 401, JWT refresh, Lighthouse) vêm da fundação §14. Aqui só os específicos da tela.

- [ ] AC-1 — Cabeçalho mostra título "Painel" em Cormorant Garamond + bloco modelo + bloco data/hora em mono pt-BR/BRT.
- [ ] AC-2 — Hora no cabeçalho atualiza a cada 60s sem reload.
- [ ] AC-3 — 0 modelos ativas → cabeçalho mostra "Nenhuma modelo ativa" em `--text-muted`.
- [ ] AC-4 — Múltiplas modelos ativas → cabeçalho mostra a primeira + ícone aviso com tooltip "há N modelos ativas".
- [ ] AC-5 — Cards de destaque aparecem na ordem fixa (Pix → Handoff → Modelo expirado), FIFO interno.
- [ ] AC-6 — Card de Pix em revisão **não** mostra botão "Devolver para IA".
- [ ] AC-7 — Card de Handoff IA **não** mostra botão "Devolver para IA".
- [ ] AC-8 — Card de Modelo expirado mostra botão "Devolver para IA" como `button-primary`.
- [ ] AC-9 — Click no botão abre `<AlertDialog>` com Cancelar e Confirmar devolução.
- [ ] AC-10 — Confirmar dialog chama `POST /api/atendimentos/{id}/devolver`; sucesso → toast `Atendimento #{N} devolvido para a IA` + dialog fecha.
- [ ] AC-11 — Erro 409 mantém dialog aberto e mostra toast com `detail`.
- [ ] AC-12 — Click em qualquer outro lugar do card navega para `/atendimentos/{id}`.
- [ ] AC-13 — Tiles de métricas mostram valores formatados em pt-BR (`R$ 12.500,00`, `12`).
- [ ] AC-14 — Tile com valor 0 ainda renderiza (não esconde).
- [ ] AC-15 — Agenda do dia lista bloqueios em ordem cronológica de `inicio`, com horário em mono e badge de estado.
- [ ] AC-16 — Bloqueio cancelado aparece com texto riscado e opacidade 0.6.
- [ ] AC-17 — Click em linha de agenda navega para `/agenda?data=…&bloqueio=…`.
- [ ] AC-18 — Atalho "Pix em revisão" só aparece quando `pix_em_revisao_pendentes > 0`; texto inclui o N.
- [ ] AC-19 — Atalho "Atendimentos abertos" só aparece quando `abertos > 0`; texto inclui o N.
- [ ] AC-20 — Atalho "Conectar WhatsApp" aparece se `evolution_instance_id IS NULL`, em variante `primary`, primeiro na ordem.
- [ ] AC-21 — Atalho "Bloquear janela" aparece sempre.
- [ ] AC-22 — Empty state em "Pendências humanas" aparece quando lista vazia (texto e ícone §5.2.2).
- [ ] AC-23 — Empty state em "Agenda" aparece quando vazia, com botão "Bloquear janela manualmente" (§5.4.1).
- [ ] AC-24 — Insert/update em `atendimentos`, `comprovantes_pix`, `bloqueios` ou `eventos` no banco dispara refetch (debounced 250ms) automaticamente.
- [ ] AC-25 — `usePathname` corretamente marca "Painel" como item ativo na sidebar com cor `--gold-500`.
- [ ] AC-26 — Inserir manualmente um `comprovantes_pix` com `decisao_pipeline='em_revisao'` no banco faz aparecer um card sem reload.
- [ ] AC-27 — Devolver para IA num card amarelo de teste atualiza o painel sozinho via Realtime.

---

## 16. Checklist de implementação

> Setup compartilhado (fundação §13) executado uma vez no projeto.

### 16.1 Pré-requisitos da tela

- [ ] CL-1 — Endpoint `GET /api/painel/resumo` existe e retorna o JSON de §12.1.
- [ ] CL-2 — Endpoint `POST /api/atendimentos/{id}/devolver` existe conforme §12.2.
- [ ] CL-3 — Tabelas `atendimentos`, `comprovantes_pix`, `bloqueios`, `eventos` na publicação `supabase_realtime`.
- [ ] CL-4 — Itens de fundação §13 prontos (deps, shadcn components, env, RLS).

### 16.2 Estrutura

- [ ] CL-5 — Excluir `interface/src/app/page.tsx`.
- [ ] CL-6 — Excluir `interface/src/app/(interface)/interface/page.tsx` e seu diretório.
- [ ] CL-7 — Criar `interface/src/app/(interface)/page.tsx` (Painel Geral, `"use client"`).
- [ ] CL-8 — Criar `interface/src/components/painel/{HeaderPainel,CardDestaque,TileMetrica,LinhaAgenda,AtalhoContextual}.tsx`.
- [ ] CL-9 — Criar `interface/src/tipos/painel.ts` com os tipos de §11.
- [ ] CL-10 — Criar `interface/src/hooks/usePainelResumo.ts` (fetch + Realtime + debounced refetch).

### 16.3 Implementação

- [ ] CL-11 — Cabeçalho conforme §5.1 (com hora atualizando a cada 60s).
- [ ] CL-12 — Cards de destaque conforme §5.2 (com botão inline + AlertDialog).
- [ ] CL-13 — Tiles de métricas conforme §5.3.
- [ ] CL-14 — Agenda do dia conforme §5.4.
- [ ] CL-15 — Atalhos contextuais conforme §5.5.
- [ ] CL-16 — Empty states conforme §5.2.2 e §5.4.1.
- [ ] CL-17 — A11y conforme §7.5.

### 16.4 Verificação

- [ ] CL-18 — Lint passa: `pnpm lint`.
- [ ] CL-19 — Build passa: `pnpm build`.
- [ ] CL-20 — Subir backend (`make dev` em `api/`) + frontend (`pnpm dev`) e validar AC-1..27.
- [ ] CL-21 — Testar fluxos Realtime (AC-26, AC-27) inserindo/atualizando registros via Supabase Studio ou `psql`.
- [ ] CL-22 — Lighthouse acessibilidade ≥ 95 (EST-13 da fundação).

---

## 17. Vetos locais e pontos imutáveis da tela

### 17.1 Veto local declarado

- **Fundação §9.6** ("apenas 1 primary por tela"): nesta tela, **a tela não tem nenhum primary** quando `evolution_instance_id IS NOT NULL`. Quando o piloto está conectado, o atalho "Conectar WhatsApp" some e o primary desaparece junto. Os botões "Devolver para IA" dentro de cards de modelo expirado **não contam** como primary global da tela porque são contextuais a cada card individual. **Justificativa:** o Painel Geral é leitura pesada com ações distribuídas por contexto; forçar um primary global inventaria CTA artificial. **Aprovado em:** conversa de QA Tela 01 (2026-04-30).

### 17.2 Pontos imutáveis específicos

- ❌ Não permitir ações destrutivas inline aqui (Fechar, Perder, Recusar Pix). Única ação inline = "Devolver para IA".
- ❌ Não introduzir paginação ou virtualização nos cards/agenda no MVP.
- ❌ Não cachear `/api/painel/resumo` no cliente.
- ❌ Não computar `previsao_termino` ou `expirado` no front. Backend é a fonte (fundação §10.5).
- ❌ Não esconder tile com valor zero. Tile zerado é informação válida.
- ❌ Não SSR/RSC desta tela (regra geral de Realtime já está na fundação §12; aqui é repetido por ênfase).

---

## 18. Pontos em aberto

- ⚠ **OPEN-3 — Tela de Login completa:** não está no escopo deste documento. Precisa de especificação própria; o que existe aqui é apenas o mínimo (form de email/senha + `signInWithPassword`) para o middleware funcionar e a tela do Painel ser testável.

### Decisões fechadas (antes em aberto)

- ✅ **OPEN-1** — `previsao_termino` derivado dinamicamente. Movido para fundação §10.5.
- ✅ **OPEN-2** — Formato telefone sem mascaramento. Movido para fundação §10.1.
- ✅ **OPEN-4** — Refresh JWT via `onAuthStateChange` + `realtime.setAuth`. Movido para fundação §6.3.
- ✅ **OPEN-5** — Anti-rajada Realtime debounce 250ms + monitoramento. Movido para fundação §8.3.

---

## Anexo A — Wireframe textual

```
┌─────────────────┬───────────────────────────────────────────────────────────────┐
│ Elite Baby      │ Painel                              MODELO   AGORA            │
│  (sidebar       │                                     Júlia    30 abr · 14:32   │
│   compartilhada │                                                               │
│   — fundação    │ Pendências humanas                              3 aguardando  │
│   §5.4)         │ ┌──────────────────────────┐ ┌──────────────────────────────┐ │
│                 │ │┃ [Em revisão] #142 Carlos M. │┃ [Em handoff] #138 Bruno  │ │
│                 │ │┃ MOTIVO Pipeline OCR falhou  │┃ MOTIVO fora_de_oferta    │ │
│                 │ │┃ PRÓXIMA AÇÃO Validar Pix    │┃ PRÓXIMA AÇÃO decidir     │ │
│                 │ │┃ Em handoff há 12 min · Fer. │┃ Em handoff há 4 min · Fer│ │
│                 │ └──────────────────────────┘ └──────────────────────────────┘ │
│                 │ ┌──────────────────────────┐                                  │
│                 │ │┃ [Pausada] #129 ⏰ Jorge  │                                  │
│                 │ │┃ MOTIVO Tempo previsto…   │                                  │
│                 │ │┃ PRÓXIMA AÇÃO Devolver?   │                                  │
│                 │ │┃ [ Devolver para IA ]     │                                  │
│                 │ │┃ Em handoff há 1 h · modelo│                                 │
│                 │ └──────────────────────────┘                                  │
│                 │                                                               │
│                 │ Hoje                                          Quinta · 30 abr │
│                 │ ┌──────────┬──────────┬──────────┬─────────────────────────┐ │
│                 │ │ABERTOS   │FECHAM.   │PERDAS    │VALOR BRUTO              │ │
│                 │ │   12     │    3     │    1     │      R$ 4.500,00        │ │
│                 │ └──────────┴──────────┴──────────┴─────────────────────────┘ │
│                 │                                                               │
│                 │ Agenda de hoje                                                │
│                 │ ┌─────────────────────────────────────────────────────────┐   │
│                 │ │ 14:00–16:00  [Bloqueado]  Carlos M.       🤖     >     │   │
│                 │ │ 18:00–20:00  [Em atendi…] Jorge           👤     >     │   │
│                 │ │ 22:00–23:00  [Bloqueado]  Bloqueio manual ✋     >     │   │
│                 │ └─────────────────────────────────────────────────────────┘   │
│                 │                                                               │
│                 │ ─────────────────────────────────────────────────────────     │
│                 │ [ Conectar WhatsApp da modelo (primary) ]                     │
│                 │ [ Ver 2 Pix em revisão ] [ Ver 12 atendimentos ]              │
│                 │ [ Bloquear janela ]                                           │
└─────────────────┴───────────────────────────────────────────────────────────────┘
```

— FIM —
