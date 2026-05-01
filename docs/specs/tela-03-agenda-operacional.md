# Tela 03 - Agenda Operacional

> **Herda decisões de** `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto local declarado em §17. Não repetir aqui o que está na fundação.

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome | Agenda Operacional |
| Slug | `agenda-operacional` |
| Rota | `/agenda` |
| Arquivo Next.js | `interface/src/app/(interface)/agenda/page.tsx` |
| Tipo | Client Component (`"use client"`) - Realtime exige client |
| Hook próprio | `interface/src/hooks/useAgenda.ts` |
| Tipos | `interface/src/tipos/agenda.ts` |
| Componentes próprios | `interface/src/components/agenda/{HeaderAgenda,ToolbarAgenda,CalendarioMes,PainelDia,BloqueioAgenda,DialogBloqueio}.tsx` |

---

## 2. Objetivo

Controlar a disponibilidade da modelo piloto, criar e editar bloqueios de agenda, apontar conflitos antes da gravação e permitir que Fernando libere horários sem sair da tela.

Citação de `docs/mvp/03-modulos-sistema.md` §4.3: "Controlar disponibilidade da modelo piloto e evitar conflitos de horário."

---

## 3. Contexto funcional

- **Usuário:** Fernando.
- **Escopo P0:** modelo piloto; a tela não implementa gestão multi-modelo como fluxo principal.
- **Visão inicial:** `Mês`.
- **Granularidade operacional:** slots de 1h.
- **Janela exibida no painel do dia:** 24h (`00:00-23:59`), para cobrir operação de madrugada.
- **CRUD:** permitido para bloqueios manuais e bloqueios vinculados a atendimento.
- **Cancelamento de `em_atendimento`:** permitido, sempre com confirmação explícita.
- **Realtime:** assinatura em `bloqueios` e `eventos` (§13).

---

## 4. Fluxo do usuário

### 4.1 Caminho feliz

1. Fernando acessa `/agenda`.
2. Tela monta com skeleton de calendário mensal e painel do dia.
3. `useAgenda` busca bloqueios do mês corrente e seleciona hoje.
4. Calendário mensal mostra dias com indicadores de bloqueio.
5. Painel lateral/direito mostra o dia selecionado em slots de 1h.
6. Fernando clica em slot livre ou no botão `Bloquear janela`.
7. Dialog abre com data, início, fim e observação.
8. Confirmar chama `POST /api/agenda/bloqueios`.
9. Sucesso fecha dialog, mostra toast e atualiza via Realtime/refetch.
10. Fernando clica em bloqueio existente para editar ou cancelar.

### 4.2 Caminhos alternativos específicos da tela

| Cenário | Comportamento |
|---|---|
| Mês sem bloqueios | Calendário renderiza normalmente; painel do dia mostra empty state por slot livre. |
| Dia sem bloqueios | Painel do dia mostra todos os slots livres e CTA secundário para bloquear. |
| Tentativa de sobreposição | Backend retorna `409`; dialog permanece aberto e toast mostra `detail`. |
| Bloqueio vinculado a atendimento | Dialog mostra vínculo com `#N` e cliente, permite CRUD, e oferece link para `/atendimentos?selecionado={id}`. |
| Cancelar bloqueio `em_atendimento` | AlertDialog exige confirmação; request envia `confirmar=true`. |
| Cancelar bloqueio `concluido` | Ação não aparece; se backend retornar 409, toast mostra `detail`. |

---

## 5. Layout detalhado dos blocos próprios

Sequência dentro do `<main>`:

```text
[Cabeçalho da página]
[Toolbar: visão, mês, ações]
[Grid: Calendário mensal + Painel do dia selecionado]
```

### 5.1 Cabeçalho da página

- Título "Agenda" em Cormorant Garamond `display-lg`.
- Subtexto `body-sm --text-muted`: nome da modelo ativa ou "Nenhuma modelo ativa".
- À direita, resumo do mês:

| Métrica | Fonte |
|---|---|
| Bloqueios ativos | `bloqueado` + `em_atendimento` no mês carregado |
| Em atendimento | `em_atendimento` no mês carregado |
| Cancelados | `cancelado` no mês carregado |

### 5.2 Toolbar

- Segmented control: `Dia`, `Semana`, `Mês`; default `Mês`.
- Navegação de período: `ChevronLeft`, label do período, `ChevronRight`, botão ghost `Hoje`.
- Único `button-primary` visível da tela: `Bloquear janela` com ícone `CalendarPlus`.
- Mudança de período refaz `GET /api/agenda/bloqueios` para a janela visível.

### 5.3 Visão Mês

- Grid 7 colunas, iniciando na segunda-feira.
- Cada célula de dia:
  - número do dia;
  - até 3 chips compactos de bloqueios do dia;
  - contador `+N` quando houver mais que 3;
  - borda/realce no dia selecionado.
- Click em dia seleciona o dia e atualiza o Painel do dia.
- Click duplo em dia vazio abre `DialogBloqueio` preenchido com esse dia e próximo slot livre.

### 5.4 Painel do dia selecionado

- Coluna fixa à direita em desktop dentro do conteúdo, largura 360px.
- Header: data selecionada (`formatData`) e contador de bloqueios do dia.
- Lista de 24 slots de 1h (`00:00`, `01:00`, ... `23:00`).
- Slot livre:
  - visual discreto com borda `--border`;
  - click abre criação de bloqueio com `inicio` no slot e `fim = inicio + 1h`.
- Slot ocupado:
  - renderiza `BloqueioAgenda`;
  - click abre detalhe/edição.

### 5.5 BloqueioAgenda

Conteúdo do card/linha:

```text
[HORÁRIO mono-sm] [BADGE estado]
[Cliente ou observação]
[Origem] [#N se vinculado]
```

Mapeamento:

| Campo | Renderização |
|---|---|
| Horário | `HH:MM-HH:MM`, via `formatHorario` |
| Estado `bloqueado` | badge `paused`, label "Bloqueado" |
| Estado `em_atendimento` | badge `active`, label "Em atendimento" |
| Estado `concluido` | badge `closed`, label "Concluído" |
| Estado `cancelado` | badge `paused`, label "Cancelado", opacidade 0.6 e texto riscado |
| Origem `ia` | ícone `Bot`, tooltip "IA" |
| Origem `painel_fernando` | ícone `User`, tooltip "Fernando" |
| Origem `manual` | ícone `Hand`, tooltip "Manual" |

### 5.6 DialogBloqueio

Usado para criar e editar.

Campos:

| Campo | Tipo | Regra |
|---|---|---|
| Data | input date | obrigatório |
| Início | select/input horário | obrigatório, passo 1h |
| Fim | select/input horário | obrigatório, maior que início |
| Observação | textarea curta | opcional, máximo 160 caracteres |

Ações:

| Situação | Botões |
|---|---|
| Criando | `Cancelar`, `Criar bloqueio` |
| Editando `bloqueado` avulso | `Cancelar`, `Salvar`, `Cancelar bloqueio` |
| Editando vinculado a atendimento | `Ver atendimento`, `Salvar`, `Cancelar bloqueio` |
| Editando `em_atendimento` | `Ver atendimento` quando houver vínculo, `Salvar`, `Cancelar bloqueio` com AlertDialog |
| `concluido` ou `cancelado` | read-only; sem `Salvar`, sem `Cancelar bloqueio` |

`Salvar` usa variante `primary` somente dentro do dialog. A regra de primary visível da tela continua preservada porque o dialog é modal e substitui o foco operacional.

### 5.7 Empty states

| Bloco | Quando | Texto |
|---|---|---|
| Calendário | mês sem bloqueios | "Nenhum bloqueio neste mês." + "Crie um bloqueio manual quando precisar reservar a agenda." |
| Painel do dia | dia sem bloqueios | "Dia livre." + "Clique em um horário para bloquear uma janela." |

---

## 6. AlertDialogs

### 6.1 Cancelar bloqueio

Padrão da fundação §9.5.

```text
Cancelar bloqueio?

Este horário ficará liberado na agenda. Se houver atendimento vinculado,
confira se a operação também precisa ser ajustada na Central de Atendimentos.

[Cancelar] [Cancelar bloqueio]
```

Endpoint: `POST /api/agenda/bloqueios/{id}/cancelar`.

### 6.2 Cancelar bloqueio em atendimento

```text
Cancelar bloqueio em atendimento?

Este bloqueio já está marcado como Em atendimento. A ação pode deixar o
histórico operacional inconsistente se o atendimento ainda estiver acontecendo.

[Voltar] [Confirmar cancelamento]
```

Endpoint: `POST /api/agenda/bloqueios/{id}/cancelar` com body `{ "confirmar": true }`.

---

## 7. Comportamentos esperados

### 7.1 Inicialização

1. Define período inicial como mês atual em `America/Sao_Paulo`.
2. Seleciona o dia atual.
3. Busca bloqueios via `api('/agenda/bloqueios?inicio=...&fim=...')`.
4. Abre subscriptions Realtime (§13).
5. Registra listener de refresh JWT conforme fundação.

### 7.2 Navegação de período

- `ChevronLeft` e `ChevronRight` deslocam conforme visão ativa:
  - Dia: 1 dia.
  - Semana: 1 semana.
  - Mês: 1 mês.
- `Hoje` volta para mês atual e seleciona hoje.
- Trocar visão mantém o dia selecionado quando possível.

### 7.3 Criação

```text
click slot livre ou Bloquear janela
  -> abre DialogBloqueio
  -> Confirmar
    -> POST /api/agenda/bloqueios
      -> 200/201 fecha dialog + toast "Bloqueio criado"
      -> 409 mantém dialog + toast com detail
```

### 7.4 Edição

```text
click bloqueio
  -> abre DialogBloqueio preenchido
  -> Salvar
    -> PATCH /api/agenda/bloqueios/{id}
      -> 200 fecha dialog + toast "Bloqueio atualizado"
      -> 409 mantém dialog + toast com detail
```

### 7.5 Cancelamento

```text
click Cancelar bloqueio
  -> AlertDialog
  -> confirmar
    -> POST /api/agenda/bloqueios/{id}/cancelar
      -> 200 fecha dialog + toast "Bloqueio cancelado"
```

---

## 8. Estados específicos da tela

| Estado | Quando | Aparência |
|---|---|---|
| `loading-inicial` | primeiro fetch | skeleton do calendário e do painel |
| `success-vazio-mes` | nenhum bloqueio no mês | calendário vazio com empty state discreto |
| `success-vazio-dia` | nenhum bloqueio no dia selecionado | slots livres e texto "Dia livre" |
| `submitting` | criação/edição/cancelamento em voo | botões desabilitados + spinner inline |
| `erro-conflito` | backend retorna 409 | toast com `detail`, dialog permanece aberto |

### 8.1 Skeletons específicos

- Calendário: grade 7x5 com células fantasma.
- Painel do dia: 8 linhas fantasma de slot, mantendo altura.
- Toolbar: skeleton no label do período e botão desabilitado.

---

## 9. Regras de negócio

### 9.1 Janela e granularidade

- A tela trabalha com slots de 1h.
- O backend continua aceitando `inicio` e `fim` ISO; o front valida apenas que `fim > inicio`.
- A janela visual do painel do dia é 24h.

### 9.2 Conflitos

- O front aponta conflito visual quando o novo intervalo cruza bloqueio ativo (`bloqueado` ou `em_atendimento`) já carregado.
- O backend é autoridade final e retorna `409` quando houver sobreposição ativa.
- Bloqueios `cancelado` e `concluido` não bloqueiam criação de novos horários.

### 9.3 CRUD

- Criar bloqueio sempre grava `origem='painel_fernando'` no backend.
- Editar pode alterar horário e observação.
- Cancelar muda estado para `cancelado`.
- Bloqueio `concluido` é read-only na tela.
- Bloqueio `cancelado` é read-only na tela.

### 9.4 Bloqueios vinculados a atendimento

- A tela permite editar e cancelar, conforme decisão do usuário.
- Quando houver `atendimento_id`, o dialog mostra vínculo e link para Central de Atendimentos.
- O backend valida qualquer efeito colateral necessário; o front não altera atendimento diretamente.

### 9.5 Cancelamento de `em_atendimento`

- Permitido no P0.
- Sempre exige AlertDialog.
- Body deve enviar `confirmar=true`.

---

## 10. Validações

| Onde | Validação | Falha |
|---|---|---|
| Front | `fim > inicio` | Desabilita confirmar e mostra texto inline. |
| Front | Observação até 160 caracteres | Desabilita confirmar. |
| Front | Sobreposição com bloqueio ativo carregado | Mostra aviso inline; ainda permite tentar salvar para o backend decidir. |
| Backend | Sem sobreposição ativa por modelo | 409 `{ detail: "Horário conflita com bloqueio existente" }`. |
| Backend | Bloqueio `concluido` não cancela | 409 com `detail`. |
| Backend | `em_atendimento` sem confirmação | 400/409 com `detail`; front reabre fluxo de confirmação. |

---

## 11. Dados - tipos próprios da tela

Arquivo: `interface/src/tipos/agenda.ts`.

```ts
export type EstadoBloqueio = 'bloqueado' | 'em_atendimento' | 'concluido' | 'cancelado';
export type OrigemBloqueio = 'ia' | 'painel_fernando' | 'manual';
export type VisaoAgenda = 'dia' | 'semana' | 'mes';

export interface ModeloAgenda {
  id: string;
  nome: string;
}

export interface AtendimentoAgendaResumo {
  id: string;
  numero_curto: number;
  cliente_nome: string | null;
  cliente_telefone_formatado: string;
  estado: string;
}

export interface BloqueioAgenda {
  id: string;
  modelo_id: string;
  inicio: string;
  fim: string;
  estado: EstadoBloqueio;
  origem: OrigemBloqueio;
  observacao: string | null;
  atendimento_id: string | null;
  atendimento: AtendimentoAgendaResumo | null;
}

export interface AgendaResponse {
  modelo: ModeloAgenda | null;
  inicio: string;
  fim: string;
  bloqueios: BloqueioAgenda[];
}

export interface CriarBloqueioInput {
  modelo_id?: string;
  inicio: string;
  fim: string;
  observacao: string | null;
}

export interface AtualizarBloqueioInput {
  inicio: string;
  fim: string;
  observacao: string | null;
}
```

---

## 12. API - específica desta tela

Prefixo conforme montagem do backend: `/api/agenda` ou `/api/v1/agenda`. A spec da tela usa caminhos lógicos.

### 12.1 `GET /api/agenda/bloqueios`

Query:

| Parâmetro | Tipo | Uso |
|---|---|---|
| `inicio` | ISO obrigatório | início da janela carregada |
| `fim` | ISO obrigatório | fim da janela carregada |
| `estado` | string opcional | filtra estado quando presente |
| `modelo_id` | uuid opcional | omitido no P0 usa modelo ativa |

200:

```json
{
  "modelo": {
    "id": "01950000-0000-7000-8000-000000000001",
    "nome": "Julia"
  },
  "inicio": "2026-05-01T00:00:00-03:00",
  "fim": "2026-05-31T23:59:59-03:00",
  "bloqueios": [
    {
      "id": "01950000-0000-7000-8000-000000000077",
      "modelo_id": "01950000-0000-7000-8000-000000000001",
      "inicio": "2026-05-02T22:00:00-03:00",
      "fim": "2026-05-02T23:00:00-03:00",
      "estado": "bloqueado",
      "origem": "painel_fernando",
      "observacao": "Bloqueio manual",
      "atendimento_id": null,
      "atendimento": null
    }
  ]
}
```

### 12.2 `POST /api/agenda/bloqueios`

Body:

```json
{
  "modelo_id": "01950000-0000-7000-8000-000000000001",
  "inicio": "2026-05-02T22:00:00-03:00",
  "fim": "2026-05-02T23:00:00-03:00",
  "observacao": "Bloqueio manual"
}
```

201/200: retorna `BloqueioAgenda`.

409: conflito de horário, `{ "detail": "Horário conflita com bloqueio existente" }`.

### 12.3 `PATCH /api/agenda/bloqueios/{id}`

Body:

```json
{
  "inicio": "2026-05-02T23:00:00-03:00",
  "fim": "2026-05-03T00:00:00-03:00",
  "observacao": "Ajustado por Fernando"
}
```

200: retorna `BloqueioAgenda`.

### 12.4 `POST /api/agenda/bloqueios/{id}/cancelar`

Body para bloqueio comum:

```json
{ "confirmar": false }
```

Body para `em_atendimento`:

```json
{ "confirmar": true }
```

200: `{ "ok": true }`.

---

## 13. Realtime - específico desta tela

### 13.1 Subscriptions

Tabelas observadas:

- `bloqueios` - criação, edição, cancelamento e mudança automática por registro de resultado.
- `eventos` - auditoria de transições que podem impactar a agenda vinculada.

```ts
const cleanup = subscribeTabelas('agenda', ['bloqueios', 'eventos'], debouncedRefetch);
```

### 13.2 Refetch

- Evento em qualquer tabela refaz o período visível.
- Refetch debounced 250ms.
- Sem skeleton em refetch após primeiro sucesso.
- Se o dia selecionado sair do período, selecionar hoje quando estiver dentro da nova janela; senão selecionar o primeiro dia do período.

---

## 14. Mudanças estruturais necessárias

| Antes | Depois | Ação |
|---|---|---|
| Stub de `/agenda`, se existir | Tela real de Agenda Operacional | substituir |
| n/a | `interface/src/hooks/useAgenda.ts` | criar |
| n/a | `interface/src/tipos/agenda.ts` | criar |
| n/a | `interface/src/components/agenda/` | criar componentes próprios |

### 14.1 Navegações disparadas pela tela

| Trigger | Destino |
|---|---|
| Link "Ver atendimento" | `/atendimentos?selecionado={atendimento_id}` |
| Sidebar Agenda | `/agenda` |

---

## 15. Critérios de aceite específicos

> Critérios estruturais vêm da fundação §14. Aqui só os específicos da tela.

- [ ] AC-1 - `/agenda` carrega em visão `Mês`.
- [ ] AC-2 - Toolbar permite alternar `Dia`, `Semana` e `Mês`.
- [ ] AC-3 - Navegação anterior/próximo muda o período conforme visão ativa.
- [ ] AC-4 - Botão `Hoje` volta para o período atual e seleciona hoje.
- [ ] AC-5 - Calendário mensal mostra dias com bloqueios e contador `+N` quando houver overflow.
- [ ] AC-6 - Click em dia atualiza o painel do dia selecionado.
- [ ] AC-7 - Painel do dia mostra slots de 1h de `00:00` a `23:00`.
- [ ] AC-8 - Click em slot livre abre criação com início/fim preenchidos.
- [ ] AC-9 - Botão `Bloquear janela` abre criação.
- [ ] AC-10 - Criar bloqueio chama `POST /api/agenda/bloqueios` e mostra toast `Bloqueio criado`.
- [ ] AC-11 - Click em bloqueio abre dialog de edição.
- [ ] AC-12 - Salvar edição chama `PATCH /api/agenda/bloqueios/{id}` e mostra toast `Bloqueio atualizado`.
- [ ] AC-13 - Cancelar bloqueio comum abre AlertDialog e chama endpoint de cancelamento.
- [ ] AC-14 - Cancelar bloqueio `em_atendimento` exige AlertDialog específico e envia `confirmar=true`.
- [ ] AC-15 - Bloqueio `concluido` aparece read-only e não oferece cancelamento.
- [ ] AC-16 - Bloqueio `cancelado` aparece riscado/opaco e read-only.
- [ ] AC-17 - Bloqueio vinculado mostra `#N`, cliente e link para Central de Atendimentos.
- [ ] AC-18 - Conflito 409 mantém dialog aberto e mostra toast com `detail`.
- [ ] AC-19 - Realtime em `bloqueios` atualiza a agenda sem reload.
- [ ] AC-20 - Realtime em `eventos` refaz o período visível.

---

## 16. Checklist de implementação

### 16.1 Pré-requisitos da tela

- [ ] CL-1 - Endpoint `GET /api/agenda/bloqueios` retorna bloqueios com atendimento resumido.
- [ ] CL-2 - Endpoint `POST /api/agenda/bloqueios` cria bloqueio manual.
- [ ] CL-3 - Endpoint `PATCH /api/agenda/bloqueios/{id}` edita horário/observação.
- [ ] CL-4 - Endpoint `POST /api/agenda/bloqueios/{id}/cancelar` cancela, incluindo `em_atendimento` com confirmação.
- [ ] CL-5 - Tabelas `bloqueios` e `eventos` estão no Realtime.

### 16.2 Estrutura

- [ ] CL-6 - Criar `interface/src/app/(interface)/agenda/page.tsx`.
- [ ] CL-7 - Criar `interface/src/hooks/useAgenda.ts`.
- [ ] CL-8 - Criar `interface/src/tipos/agenda.ts`.
- [ ] CL-9 - Criar componentes próprios em `interface/src/components/agenda/`.

### 16.3 Implementação

- [ ] CL-10 - Header e toolbar.
- [ ] CL-11 - Calendário mensal default.
- [ ] CL-12 - Visões Dia/Semana/Mês.
- [ ] CL-13 - Painel do dia com slots de 1h.
- [ ] CL-14 - Dialog de criação/edição.
- [ ] CL-15 - AlertDialogs de cancelamento.
- [ ] CL-16 - Empty states e skeletons.
- [ ] CL-17 - Realtime + refetch debounced.

### 16.4 Verificação

- [ ] CL-18 - `pnpm lint` passa.
- [ ] CL-19 - `pnpm build` passa.
- [ ] CL-20 - `pnpm dev` sobe e `/agenda` carrega sem erro de console.
- [ ] CL-21 - Validar criação, edição e cancelamento contra backend local.
- [ ] CL-22 - Validar conflito de horário com resposta 409.
- [ ] CL-23 - Validar cancelamento de `em_atendimento` com `confirmar=true`.
- [ ] CL-24 - Validar Realtime alterando um bloqueio de teste.

---

## 17. Vetos locais e pontos imutáveis da tela

### 17.1 Vetos locais

Nenhum veto local. O único `button-primary` visível da tela é `Bloquear janela`; botões primary dentro de dialog pertencem ao foco modal.

### 17.2 Pontos imutáveis específicos

- Não implementar agenda por áudio no P0.
- Não decidir segurança de saída nesta tela.
- Não criar bloqueio externo apenas por comprovante recebido.
- Não editar estado do atendimento diretamente pela Agenda.
- Não esconder bloqueios cancelados/concluídos quando estiverem na janela carregada.
- Não usar preview de mídia ou dados sensíveis nesta tela.

---

## 18. Pontos em aberto

Nenhum ponto em aberto após alinhamento com o usuário em 2026-05-01.

---

## Anexo A - Wireframe textual

```text
┌─────────────────┬──────────────────────────────────────────────────────────────┐
│ Sidebar         │ Agenda                                      Maio 2026        │
│                 │ Modelo Julia                         [Bloquear janela]      │
│                 │                                                              │
│                 │ [Dia] [Semana] [Mês]   <   Maio 2026   >   [Hoje]           │
│                 │                                                              │
│                 │ ┌──────────────────────────────────────┐ ┌────────────────┐ │
│                 │ │ Seg Ter Qua Qui Sex Sab Dom          │ │ 01 mai 2026    │ │
│                 │ │        1   2   3                     │ │ 3 bloqueios    │ │
│                 │ │        [22:00 Bloqueado]             │ │                │ │
│                 │ │  4   5   6   7   8   9  10           │ │ 00:00 livre    │ │
│                 │ │ 11  12  13  14  15  16  17           │ │ 01:00 livre    │ │
│                 │ │ 18  19  20  21  22  23  24           │ │ ...            │ │
│                 │ │ 25  26  27  28  29  30  31           │ │ 22:00          │ │
│                 │ │                                      │ │ [Bloqueado]    │ │
│                 │ └──────────────────────────────────────┘ │ Bloqueio manual│ │
│                 │                                          │                │ │
│                 │                                          │ 23:00 livre    │ │
│                 │                                          └────────────────┘ │
└─────────────────┴──────────────────────────────────────────────────────────────┘
```

--- FIM ---
