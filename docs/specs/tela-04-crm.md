# Tela 04 - CRM

> **Herda decisões de** `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto local declarado em §17. Não repetir aqui o que está na fundação.

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome | CRM |
| Slug | `crm` |
| Rota | `/crm` |
| Arquivo Next.js | `interface/src/app/(interface)/crm/page.tsx` |
| Tipo | Client Component (`"use client"`) - Realtime exige client |
| Hook próprio | `interface/src/hooks/useCrm.ts` |
| Tipos | `interface/src/tipos/crm.ts` |
| Componentes próprios | `interface/src/components/crm/{ListaConversas,ItemConversa,DetalheConversa,DadosCliente,DadosConversa,ObservacoesInternas,AtendimentoAberto,HistoricoAtendimentosConversa,ItemAtendimentoHistorico}.tsx` |

---

## 2. Objetivo

Dar a Fernando uma visão histórica e relacional do par **cliente + modelo** (a unidade de "Conversa cliente" do `CONTEXT.md`): quem é o cliente, quantas vezes voltou nessa conversa, qual foi o último motivo de perda e o que está registrado como observação interna. Inclui edição leve de nome do cliente e observações internas; demais ações comerciais permanecem na Central de Atendimentos.

Citação literal de `docs/mvp/06-dados-interfaces.md` §4.4: *"Histórico de conversas (par cliente, modelo) — não de clientes globais — porque histórico, recorrência e observações são por par."*

---

## 3. Contexto funcional

- **Usuário no P0:** Fernando.
- **Unidade da tela:** **conversa** (par cliente, modelo). No P0 com 1 modelo piloto, em geral haverá 1 conversa por cliente; a tela é defensiva contra múltiplas conversas do mesmo cliente quando entrar a 2ª modelo.
- **Origem dos dados:** endpoints REST de conversas/clientes (§12).
- **Realtime:** assinatura em `conversas`, `clientes` e `atendimentos` (§13).
- **Escrita inline permitida:** nome do cliente (campo de `clientes`) e observações internas da conversa (campo de `conversas`).
- **Fora do escopo desta tela:** abrir/fechar atendimentos, validar Pix, editar mensagens, mesclar clientes, excluir conversas, alterar `recorrente` (derivado por trigger), alterar `ultimo_motivo_perda` (snapshot).

---

## 4. Fluxo do usuário

### 4.1 Caminho feliz

1. Fernando acessa `/crm`.
2. A tela carrega skeleton da lista e do detalhe.
3. `useCrm` chama `GET /api/conversas` com filtro padrão (todos os filtros vazios) ordenado por `ultima_mensagem_em DESC`.
4. Ao receber a lista, a tela seleciona automaticamente a conversa mais recente.
5. A seleção dispara `GET /api/conversas/{id}`.
6. O detalhe mostra: dados do cliente (com nome editável), dados da conversa (recorrente, último motivo de perda, última mensagem), observações internas (textarea + botão "Salvar"), atendimento aberto destacado quando houver, e histórico de atendimentos read-only.
7. Fernando aplica filtros ou busca; a lista refaz o fetch e seleciona a primeira conversa do novo resultado.
8. Fernando edita nome do cliente ou observações; ao salvar, a tela chama `PATCH` correspondente e mostra toast de sucesso.

### 4.2 Caminhos alternativos específicos

| Cenário | Comportamento |
|---|---|
| Lista vazia sem filtros | Empty state: "Nenhuma conversa registrada ainda." |
| Lista vazia com filtros aplicados | Empty state: "Nenhuma conversa encontrada para estes filtros." |
| Cliente com múltiplas conversas (P1) | Aparecem N linhas — uma por par (cliente, modelo) — cada uma navegável. |
| Conversa selecionada sai do filtro após Realtime | Mantém o detalhe visível até o refetch concluir; depois seleciona a primeira conversa do novo resultado. Se a lista ficar vazia, mostra empty state no painel de detalhe. |
| Edição com erro de rede/servidor | Mantém o textarea/input em estado dirty; toast de erro; nenhum dado local é descartado. |
| Conversa sem atendimentos ainda | Bloco "Atendimento aberto" e "Histórico" mostram empty state próprio. |

---

## 5. Layout detalhado dos blocos próprios

> Sidebar e shell de 2 colunas vêm da fundação §5. Esta seção descreve apenas o conteúdo do `<main>` da rota `/crm`.

Estrutura dentro do `<main>`:

```
[Cabeçalho da página]
[Toolbar de filtros e busca]
[Split 360px lista | detalhe flexível]
```

### 5.1 Cabeçalho da página

- Título "CRM" em Cormorant Garamond `display-lg`.
- Subtítulo `body-sm --text-muted`: "Conversas por par cliente e modelo. Histórico, recorrência e observações."
- Sem botão primary global no cabeçalho.

### 5.2 Toolbar de filtros e busca

- Linha horizontal com busca e filtros.
- Busca por nome ou telefone.
- Controles:

| Controle | Tipo | Opções |
|---|---|---|
| Busca | input | placeholder "Buscar nome ou telefone" |
| Recorrência | select | `Todas`, `Novas`, `Recorrentes` |
| Motivo da última perda | select | `Todos`, `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro` |
| Período do último atendimento | select | `Todos`, `7 dias`, `30 dias`, `90 dias` |
| Modelo | select | `Todas` + lista de modelos `ativa`/`pausada` (no P0 = piloto única) |

- Busca com debounce 300ms.
- Mudança de filtro reseta paginação/cursor e cancela seleção anterior; tela seleciona a primeira conversa do novo resultado.
- Sem botão "Limpar filtros" no MVP — voltar cada select para `Todas` faz o papel.

### 5.3 Split lista/detalhe

- Grid de duas colunas:
  - Lista: largura fixa 360px.
  - Detalhe: ocupa o restante.
- Gap `spacing.5`.
- Altura mínima: `calc(100vh - shell/header)`, sem esconder conteúdo essencial.

### 5.4 Lista de conversas

- Container `<section aria-label="Lista de conversas">`.
- Lista vertical de cards compactos.
- Ordenação: `ultima_mensagem_em DESC` (conversas sem mensagem ainda vão para o fim, ordenadas por `created_at DESC`).
- Paginação: cursor simples com botão ghost "Carregar mais" no fim.

#### 5.4.1 Item da lista

Conteúdo:

```
[Badge Recorrente?] [tempo relativo]
Cliente nome ou telefone formatado (heading-md --text-primary)
Modelo · ultimo motivo de perda quando houver
Último atendimento: estado · há X (caption --text-muted)
```

- Card clicável com `role="button"` e `aria-pressed` quando selecionado.
- Selecionado: borda esquerda `3px solid var(--gold-500)`.
- Conversa **com atendimento aberto**: borda esquerda `3px solid var(--warn-500)` se não selecionado (sinalização sutil de que há ação pendente na Central).
- Badge `Recorrente` (variante `paused`, neutro) renderizado **apenas** quando `conversas.recorrente === true`. Conversa nova (recorrente=false) não exibe badge.
- Telefone usa `formatTelefone` da fundação, sem mascaramento.
- Tempo relativo via `formatTempoRelativo(ultima_mensagem_em ?? created_at)`.

#### 5.4.2 Empty state da lista

Sem filtros:

```
Nenhuma conversa registrada ainda.
Conversas aparecem aqui assim que clientes chamarem no WhatsApp da modelo.
```

Com filtros:

```
Nenhuma conversa encontrada para estes filtros.
Ajuste busca, recorrência, motivo de perda, período ou modelo.
```

### 5.5 Detalhe da conversa

Container `<section aria-label="Detalhe da conversa">`.

Ordem dos blocos:

```
[Header da conversa]
[Dados do cliente]
[Dados da conversa]
[Observações internas]
[Atendimento aberto] (quando houver)
[Histórico de atendimentos]
```

### 5.6 Header da conversa

Mostra:

- Nome do cliente em `heading-lg --text-primary` (ou telefone formatado se nome ausente).
- Badge `Recorrente` (variante `paused`) quando `recorrente=true`.
- Modelo da conversa em `body-sm --text-muted`: "Conversa com {modelo.nome}".
- Última atividade: "Última mensagem há X" via `formatTempoRelativo`, ou "Sem mensagens ainda" quando `ultima_mensagem_em` for null.

### 5.7 Dados do cliente

Card com `<dl>`:

| Campo | Comportamento |
|---|---|
| Telefone | `formatTelefone`, mono-sm. **Read-only** (chave). |
| Nome | **Editável inline.** `<Input>` com valor inicial preenchido; salva via botão `button-secondary` "Salvar nome". Botão só fica habilitado quando dirty. |
| Primeiro contato | Nome da modelo de `primeiro_contato_modelo_id` quando existir; caso contrário, "Não informado". Read-only. |
| Cliente desde | `formatData(clientes.created_at)`. Read-only. |

- Validação no front: `nome` aceita string vazia (limpa o campo) ou string com 1+ caracteres não-espaço; sem máscara.
- Sucesso → toast `Nome do cliente atualizado`.
- Erro 4xx → toast com `detail`; campo permanece dirty.

### 5.8 Dados da conversa

Card com `<dl>` read-only:

| Campo | Conteúdo |
|---|---|
| Recorrência | "Recorrente" ou "Nova" (texto + ícone `RefreshCw` 16px `--text-muted` quando recorrente). |
| Último motivo de perda | label legível do enum (ex.: `preco` → "Preço") quando `ultimo_motivo_perda` não nulo; "Nenhum" caso contrário. |
| Última mensagem | `formatDataHora(ultima_mensagem_em)` + chip de direção (`cliente`, `ia`, `modelo_manual`); "Sem mensagens ainda" quando null. |
| Conversa desde | `formatData(conversas.created_at)`. |

### 5.9 Observações internas

Card com:

- Label `caption --text-muted`: "OBSERVAÇÕES INTERNAS".
- `<Textarea>` shadcn, altura mínima 120px, valor inicial = `conversas.observacoes_internas ?? ""`.
- Hint `body-sm --text-muted`: "Visíveis apenas para Fernando e a modelo. A IA não consulta este campo."
- Rodapé do card (flex row, `justify-end`):
  - Botão `button-ghost` "Descartar" quando dirty (reverte para o último salvo).
  - Botão **`button-primary` "Salvar observações"** — visível **apenas quando dirty** (ver veto local §17).

#### 5.9.1 Comportamento

- Estado `dirty` = valor atual ≠ valor salvo (após trim).
- Limite máximo: 2000 caracteres; contador `caption --text-muted` aparece quando >1500.
- `Cmd/Ctrl+Enter` no textarea = atalho para "Salvar observações" quando dirty.
- Submit:
  1. Botão e textarea desabilitados + spinner inline no botão.
  2. `PATCH /api/conversas/{id}` com body `{ "observacoes_internas": "<valor>" }`.
  3. Sucesso → toast `Observações atualizadas`; botão "Salvar observações" some (não está mais dirty).
  4. Erro → toast com `detail`; textarea permanece dirty e habilitado.

### 5.10 Atendimento aberto

Renderiza **apenas quando** `atendimento_aberto !== null` no payload (ver §11).

Card com `border-left: 3px solid var(--warn-500)`:

```
[Badge estado] [#N mono-sm] (heading-md --text-primary cliente)
Tipo · urgência · valor acordado quando houver (body-sm --text-muted)
Próxima ação esperada: <texto> (body-sm --text-primary) quando houver
[button-secondary "Abrir na Central"]
```

- Botão `button-secondary` "Abrir na Central" → `router.push('/atendimentos')` (deep link `/atendimentos/{id}` está fora do P0; na Central, o atendimento mais recente já é o pré-selecionado por `updated_at DESC`, conforme Tela 02 §5.4).
- O bloco inteiro **não** é clicável; apenas o botão.

#### 5.10.1 Empty state

Quando `atendimento_aberto === null`:

```
Sem atendimento aberto nesta conversa.
```

`body-sm --text-muted`, sem ícone, sem CTA.

### 5.11 Histórico de atendimentos

- Container `<section aria-label="Histórico de atendimentos da conversa">`.
- Lista cronológica reversa por `created_at DESC`.
- Cada linha (altura 56px, padding `spacing.3 spacing.4`, separadas por `1px var(--border)`):

```
[#N mono-sm] [Badge estado] Início (formatData) · Valor final ou Motivo de perda
```

- **Badge** por estado conforme fundação §4.5 (`active`, `paused`, `closed`, `lost`).
- **Valor final**: `formatBRL(valor_final)` quando `estado='Fechado'`.
- **Motivo de perda**: label legível quando `estado='Perdido'`; se `motivo_perda='outro'`, mostra a observação truncada (40 caracteres).
- Linhas **não navegáveis** no P0 (deep link para atendimento individual está fora do escopo do MVP, conforme Tela 02 §17.2).
- Atendimento aberto **não** aparece nesta lista (já está em §5.10).

#### 5.11.1 Empty state

Quando `historico_atendimentos.length === 0`:

```
Nenhum atendimento registrado ainda nesta conversa.
```

`body-sm --text-muted`.

---

## 6. Formulários inline

### 6.1 Edição de nome do cliente

- Input com valor preenchido.
- Sem AlertDialog (alteração reversível e de baixo impacto).
- Botão `button-secondary` "Salvar nome" só habilitado quando dirty.
- Endpoint: `PATCH /api/clientes/{cliente_id}`.
- Body:
  ```json
  { "nome": "Carlos M." }
  ```
- Toast de sucesso: `Nome do cliente atualizado`.

### 6.2 Edição de observações internas

- Textarea + botão primary contextual (§5.9).
- Sem AlertDialog.
- Endpoint: `PATCH /api/conversas/{id}`.
- Body:
  ```json
  { "observacoes_internas": "Cliente prefere horário noturno." }
  ```
- Toast de sucesso: `Observações atualizadas`.

> Nenhuma ação destrutiva nesta tela no P0 (mesclar clientes, excluir conversa, anular recorrência, redefinir último motivo de perda → todos P1+).

---

## 7. Comportamentos esperados

### 7.1 Inicialização

`useEffect` no mount:

1. Carrega lista com filtros vazios.
2. Seleciona a primeira conversa retornada.
3. Carrega detalhe da conversa selecionada.
4. Abre subscriptions Realtime (§13).
5. Registra listener `onAuthStateChange` conforme fundação §6.3.

### 7.2 Mudança de filtros

- Atualiza query local.
- Debounce apenas na busca textual (300ms).
- Cancela seleção anterior.
- Após novo resultado, seleciona a primeira conversa.

### 7.3 Seleção manual

- Clique ou Enter/Space em item da lista seleciona a conversa.
- Trocar de seleção com edição dirty pendente:
  - Se houver alteração não salva em **observações internas** ou **nome**, mostrar `<AlertDialog>` "Descartar alterações não salvas?" (botão `button-danger` "Descartar"; `button-ghost` "Cancelar"). Confirmar troca = descartar.

### 7.4 Reconciliação Realtime

- Eventos em tabelas observadas disparam refetch debounced 250ms.
- Se houver conversa selecionada, refetch do detalhe também ocorre.
- **Edição em curso protegida:** se `observacoes_internas` ou `nome` estão dirty no momento do refetch, o refetch atualiza apenas os blocos não dirty; o textarea/input dirty permanece com o valor digitado por Fernando. Após salvar com sucesso, o detalhe é refetchado integralmente.

### 7.5 Teclado / a11y

Ordem do Tab:

1. Sidebar.
2. Busca e filtros.
3. Itens da lista.
4. Input de nome + botão "Salvar nome".
5. Textarea de observações + botões "Descartar" / "Salvar observações".
6. Botão "Abrir na Central" (quando houver atendimento aberto).

Roles:

- `<section aria-label="Lista de conversas">`.
- `<section aria-label="Detalhe da conversa">`.
- `<dl>` para "Dados do cliente" e "Dados da conversa".
- `<section aria-label="Histórico de atendimentos da conversa">`.
- Lista com itens focáveis por teclado.

---

## 8. Estados específicos da tela

| Estado | Quando | Aparência |
|---|---|---|
| `loading-lista` | primeiro fetch da lista | skeleton de toolbar + 8 itens |
| `loading-detalhe` | primeiro fetch do detalhe | skeleton de header, dados cliente, dados conversa, observações |
| `success-vazio-lista` | lista vazia | empty state §5.4.2 |
| `success-sem-historico` | conversa sem atendimentos | empty state §5.10.1 e §5.11.1 |
| `nome-dirty` | valor do input difere do salvo | botão "Salvar nome" habilitado |
| `observacoes-dirty` | textarea difere do salvo | botão "Salvar observações" visível |
| `submitting-nome` | PATCH de nome em voo | input + botão desabilitados, spinner inline |
| `submitting-observacoes` | PATCH de observações em voo | textarea + botões desabilitados, spinner inline |

### 8.1 Skeletons específicos

- Lista: 8 linhas-fantasma de 88px.
- Detalhe header: 64px.
- Dados do cliente: card com 4 pares label/valor.
- Dados da conversa: card com 4 pares label/valor.
- Observações: card com bloco de 120px de altura.
- Atendimento aberto: card de 96px (renderiza apenas após resolução do detalhe).
- Histórico: 4 linhas-fantasma de 56px.

---

## 9. Regras de negócio

### 9.1 Lista

- Ordenação default: `ultima_mensagem_em DESC NULLS LAST`; secundária `created_at DESC`.
- Filtro de **recorrência** mapeia para `conversas.recorrente`:
  - `Todas` → sem filtro.
  - `Novas` → `recorrente=false`.
  - `Recorrentes` → `recorrente=true`.
- Filtro de **motivo da última perda** mapeia para `conversas.ultimo_motivo_perda`.
- Filtro de **período do último atendimento** filtra por `MAX(atendimentos.created_at)` por conversa, em fuso `America/Sao_Paulo`:
  - `Todos` → sem filtro.
  - `7 dias` → último atendimento em `[now() - 7 dias, now()]`.
  - `30 dias` → análogo.
  - `90 dias` → análogo.
  - Conversas sem nenhum atendimento ficam **fora** quando o filtro de período é aplicado.
- Filtro de **modelo** mapeia para `conversas.modelo_id`.
- Busca textual: prefixo case-insensitive em `clientes.nome` E em `clientes.telefone` (após normalização para dígitos).

### 9.2 Edição de nome do cliente

- `clientes.nome` é nullable; string vazia após trim → backend recebe `null`.
- Sem normalização de caixa; preserva o que Fernando digitou.
- Update afeta o cliente globalmente — todas as conversas do cliente passam a exibir o novo nome (no P0, em geral é só uma).

### 9.3 Edição de observações internas

- Campo livre, escopo restrito à conversa selecionada (`CONTEXT.md` — observações são por par cliente, modelo).
- Não consultado pela IA (hint visível para Fernando em §5.9).
- Limite 2000 caracteres no front; backend valida o mesmo.
- Salvar com string vazia (após trim) envia `null` para o backend (limpa observação).

### 9.4 Recorrência

- `conversas.recorrente` é derivado por trigger no banco (true após primeiro `Fechado` ou `Perdido` da conversa). **Front nunca altera** este campo; só lê.
- Indicação visual: badge `Recorrente` (variante `paused`) na lista e no header do detalhe.

### 9.5 Atendimento aberto

- Por constraint do schema, no máximo 1 atendimento aberto por conversa (par cliente, modelo) — `atendimentos.estado NOT IN ('Fechado', 'Perdido')`.
- Backend retorna o aberto em `atendimento_aberto` (objeto) ou `null`.
- Tela **não** abre/fecha/perde atendimento aqui; "Abrir na Central" navega para `/atendimentos`.

### 9.6 Histórico

- Lista todos os atendimentos da conversa **em estado terminal** (`Fechado` ou `Perdido`), ordenados `created_at DESC`.
- Atendimento aberto não aparece no histórico (renderizado em §5.10).
- Sem ações inline no histórico no P0.

---

## 10. Validações

| Onde | Validação | Falha |
|---|---|---|
| Front | Nome do cliente: ≤ 200 caracteres após trim | Bloqueia salvamento; mensagem inline |
| Front | Observações internas: ≤ 2000 caracteres | Bloqueia salvamento; contador em vermelho a partir de 1900 |
| Front | Não permitir trocar de conversa com edição dirty sem confirmação | `<AlertDialog>` "Descartar alterações não salvas?" |
| Backend | Cliente/Conversa existe | 404 `{ detail: "Cliente não encontrado" }` ou `{ detail: "Conversa não encontrada" }` |
| Backend | Usuário tem permissão | 403; toast com `detail` ou "Sem permissão" |
| Backend | Tamanho de campos respeitado | 422 com `detail` legível |

---

## 11. Dados - tipos próprios da tela

Arquivo: `interface/src/tipos/crm.ts`.

```ts
export type MotivoPerda = 'preco' | 'sumiu' | 'risco' | 'indisponibilidade' | 'fora_de_area' | 'outro';
export type DirecaoMensagem = 'cliente' | 'ia' | 'modelo_manual';
export type EstadoAtendimento =
  | 'Novo'
  | 'Triagem'
  | 'Qualificado'
  | 'Aguardando_confirmacao'
  | 'Confirmado'
  | 'Em_execucao'
  | 'Fechado'
  | 'Perdido';
export type TipoAtendimento = 'interno' | 'externo';
export type Urgencia = 'imediato' | 'agendado' | 'indefinido' | 'estimado';

export type FiltroRecorrencia = 'todas' | 'novas' | 'recorrentes';
export type FiltroPeriodo = 'todos' | '7d' | '30d' | '90d';

export interface ClienteResumo {
  id: string;
  nome: string | null;
  telefone: string;
}

export interface ModeloResumo {
  id: string;
  nome: string;
}

export interface UltimoAtendimentoResumo {
  numero_curto: number;
  estado: EstadoAtendimento;
  created_at: string;
  valor_final: number | null;
  motivo_perda: MotivoPerda | null;
}

export interface ConversaListaItem {
  id: string;
  cliente: ClienteResumo;
  modelo: ModeloResumo;
  recorrente: boolean;
  ultima_mensagem_em: string | null;
  ultima_mensagem_direcao: DirecaoMensagem | null;
  ultimo_motivo_perda: MotivoPerda | null;
  ultimo_atendimento: UltimoAtendimentoResumo | null;
  tem_atendimento_aberto: boolean;
  created_at: string;
}

export interface ConversasListaResponse {
  items: ConversaListaItem[];
  next_cursor: string | null;
}

export interface ClienteDetalhe {
  id: string;
  nome: string | null;
  telefone: string;
  primeiro_contato_modelo_nome: string | null;
  created_at: string;
}

export interface AtendimentoAberto {
  id: string;
  numero_curto: number;
  estado: EstadoAtendimento;
  tipo_atendimento: TipoAtendimento | null;
  urgencia: Urgencia | null;
  valor_acordado: number | null;
  proxima_acao_esperada: string | null;
}

export interface AtendimentoHistoricoItem {
  id: string;
  numero_curto: number;
  estado: 'Fechado' | 'Perdido';
  valor_final: number | null;
  motivo_perda: MotivoPerda | null;
  motivo_perda_obs: string | null;
  created_at: string;
}

export interface ConversaDetalheResponse {
  conversa: {
    id: string;
    recorrente: boolean;
    observacoes_internas: string | null;
    ultimo_motivo_perda: MotivoPerda | null;
    ultima_mensagem_em: string | null;
    ultima_mensagem_direcao: DirecaoMensagem | null;
    created_at: string;
  };
  cliente: ClienteDetalhe;
  modelo: ModeloResumo;
  atendimento_aberto: AtendimentoAberto | null;
  historico_atendimentos: AtendimentoHistoricoItem[];
}
```

> Tipos refletem o contrato esperado de `api/src/barra/dominio/conversas/schemas.py` e `api/src/barra/dominio/clientes/schemas.py` em 2026-05-01.

---

## 12. API - específica desta tela

Prefixo conforme montagem do backend (`/api/...` ou `/api/v1/...`). Esta spec usa caminhos lógicos.

### 12.1 `GET /api/conversas`

Query:

| Parâmetro | Tipo | Uso |
|---|---|---|
| `recorrente` | boolean opcional | true/false |
| `motivo_perda` | string opcional | enum `MotivoPerda` |
| `periodo` | string opcional | `7d`/`30d`/`90d` |
| `modelo_id` | uuid opcional | filtra por modelo |
| `q` | string opcional | nome ou telefone |
| `limit` | number | default 50, máximo 100 |
| `cursor` | string opcional | cursor por `ultima_mensagem_em` |

Resposta 200:

```json
{
  "items": [
    {
      "id": "01950000-0000-7000-8000-000000000300",
      "cliente": {
        "id": "01950000-0000-7000-8000-000000000010",
        "nome": "Carlos M.",
        "telefone": "5521987654321"
      },
      "modelo": {
        "id": "01950000-0000-7000-8000-000000000001",
        "nome": "Júlia"
      },
      "recorrente": true,
      "ultima_mensagem_em": "2026-05-01T14:32:00-03:00",
      "ultima_mensagem_direcao": "ia",
      "ultimo_motivo_perda": "sumiu",
      "ultimo_atendimento": {
        "numero_curto": 142,
        "estado": "Fechado",
        "created_at": "2026-04-29T22:00:00-03:00",
        "valor_final": 1200.00,
        "motivo_perda": null
      },
      "tem_atendimento_aberto": false,
      "created_at": "2026-03-12T19:00:00-03:00"
    }
  ],
  "next_cursor": null
}
```

### 12.2 `GET /api/conversas/{id}`

Retorna detalhe da conversa, dados do cliente associado, atendimento aberto (se houver) e histórico de atendimentos terminais.

Requisitos específicos:

- `cliente.telefone` sem mascaramento.
- `historico_atendimentos` ordenado por `created_at DESC`.
- `atendimento_aberto` é `null` quando não há atendimento em estado não terminal.
- `cliente.primeiro_contato_modelo_nome` é o `modelos.nome` correspondente a `clientes.primeiro_contato_modelo_id`, ou `null` se ausente.

### 12.3 `PATCH /api/conversas/{id}`

Body parcial:

```json
{ "observacoes_internas": "Cliente prefere horário noturno." }
```

Campos editáveis no P0 a partir desta tela: **apenas `observacoes_internas`**. Outros campos do contrato MVP (`recorrente`, `ultimo_motivo_perda`) ficam fora da escrita pelo CRM (são sistema).

200:

```json
{ "id": "01950000-0000-7000-8000-000000000300", "observacoes_internas": "Cliente prefere horário noturno." }
```

### 12.4 `PATCH /api/clientes/{id}`

Body parcial:

```json
{ "nome": "Carlos M." }
```

Campos editáveis no P0 a partir desta tela: **apenas `nome`**. `telefone` é chave (read-only); `primeiro_contato_modelo_id` é setado na criação e não é editado pelo painel no P0.

200:

```json
{ "id": "01950000-0000-7000-8000-000000000010", "nome": "Carlos M.", "telefone": "5521987654321" }
```

> **Pré-requisito:** os 4 endpoints existem e foram testados em `api/` antes de codificar a tela.

---

## 13. Realtime - específico desta tela

### 13.1 Subscriptions

Tabelas observadas:

- `conversas` — recorrente, observações, último motivo de perda, última mensagem (campos desnormalizados via trigger).
- `clientes` — nome editado em outra superfície/conversa do mesmo cliente.
- `atendimentos` — estado/valor/motivo do último atendimento e existência de atendimento aberto.

```ts
const cleanup = subscribeTabelas(
  'crm',
  ['conversas', 'clientes', 'atendimentos'],
  debouncedRefetch,
);
```

> **Não** subscrever `mensagens` — alta cardinalidade; o campo `conversas.ultima_mensagem_em` é mantido por trigger e propagado via `conversas`.

### 13.2 Refetch

- Evento em qualquer tabela refaz lista e detalhe selecionado.
- Refetch debounced 250ms.
- Refetch preserva edição dirty (§7.4).
- Sem skeleton em refetch após primeiro sucesso.

---

## 14. Mudanças estruturais necessárias

| Antes | Depois | Ação |
|---|---|---|
| `interface/src/app/(interface)/crm/` ausente ou stub | rota real | criar `page.tsx` |
| n/a | hook próprio | criar `interface/src/hooks/useCrm.ts` |
| n/a | tipos próprios | criar `interface/src/tipos/crm.ts` |
| n/a | componentes próprios | criar pasta `interface/src/components/crm/` |
| shadcn `input` e `textarea` ainda não instalados (caso) | adicionar | `pnpm dlx shadcn@latest add input textarea` |

### 14.1 Navegações disparadas pela tela

| Trigger | Destino |
|---|---|
| Botão "Abrir na Central" no atendimento aberto | `/atendimentos` |

---

## 15. Critérios de aceite específicos

> Critérios estruturais vêm da fundação §14. Aqui só os específicos da tela.

- [ ] AC-1 - `/crm` carrega lista e detalhe em split 360px/restante.
- [ ] AC-2 - Lista ordenada por `ultima_mensagem_em DESC` (NULLS LAST por `created_at DESC`).
- [ ] AC-3 - Toolbar mostra busca, recorrência, motivo da última perda, período do último atendimento e modelo (todos visíveis no P0).
- [ ] AC-4 - Mudança de qualquer filtro reseta seleção e seleciona a primeira conversa do novo resultado.
- [ ] AC-5 - Busca por nome ou telefone refaz a lista com debounce 300ms.
- [ ] AC-6 - Item da lista mostra badge `Recorrente` apenas quando `recorrente=true`.
- [ ] AC-7 - Item com atendimento aberto destaca borda esquerda em `--warn-500` quando não selecionado.
- [ ] AC-8 - Header do detalhe mostra nome (ou telefone), badge de recorrência e nome da modelo.
- [ ] AC-9 - Bloco "Dados do cliente" permite editar nome via input + botão `button-secondary` "Salvar nome".
- [ ] AC-10 - Bloco "Dados da conversa" é read-only, mostra recorrência, último motivo de perda, última mensagem e data da conversa.
- [ ] AC-11 - Textarea de observações internas tem limite 2000 caracteres com contador a partir de 1500.
- [ ] AC-12 - Botão `button-primary` "Salvar observações" aparece **apenas** quando o textarea está dirty.
- [ ] AC-13 - Quando não há edição dirty, a tela não tem nenhum `button-primary` global (veto local §17).
- [ ] AC-14 - Botão "Descartar" reverte para o último valor salvo sem chamar API.
- [ ] AC-15 - `Cmd/Ctrl+Enter` no textarea envia o salvamento de observações quando dirty.
- [ ] AC-16 - Bloco "Atendimento aberto" só aparece quando `atendimento_aberto !== null` e mostra botão `button-secondary` "Abrir na Central".
- [ ] AC-17 - Histórico de atendimentos lista apenas atendimentos `Fechado` e `Perdido`, em ordem `created_at DESC`.
- [ ] AC-18 - Atendimento `Fechado` no histórico mostra `valor_final` formatado em BRL; `Perdido` mostra label do motivo (ou observação truncada para `outro`).
- [ ] AC-19 - Linhas do histórico **não** são navegáveis no P0.
- [ ] AC-20 - Trocar de conversa com edição dirty exibe AlertDialog "Descartar alterações não salvas?".
- [ ] AC-21 - Refetch via Realtime preserva textarea/input dirty.
- [ ] AC-22 - Empty state da lista sem filtros: "Nenhuma conversa registrada ainda."
- [ ] AC-23 - Empty state da lista com filtros: "Nenhuma conversa encontrada para estes filtros."
- [ ] AC-24 - Empty state do bloco "Atendimento aberto" mostra "Sem atendimento aberto nesta conversa." quando `null`.
- [ ] AC-25 - Empty state do histórico mostra "Nenhum atendimento registrado ainda nesta conversa." quando vazio.
- [ ] AC-26 - Insert/update em `conversas`, `clientes` ou `atendimentos` no banco dispara refetch debounced.
- [ ] AC-27 - Telefone aparece formatado (fundação §10.1) e sem mascaramento.

---

## 16. Checklist de implementação

### 16.1 Pré-requisitos da tela

- [ ] CL-1 - Endpoint `GET /api/conversas` retorna o JSON de §12.1.
- [ ] CL-2 - Endpoint `GET /api/conversas/{id}` retorna o JSON de §12.2 incluindo `cliente`, `atendimento_aberto` e `historico_atendimentos`.
- [ ] CL-3 - Endpoint `PATCH /api/conversas/{id}` aceita body `{ "observacoes_internas": ... }`.
- [ ] CL-4 - Endpoint `PATCH /api/clientes/{id}` aceita body `{ "nome": ... }`.
- [ ] CL-5 - Tabelas `conversas`, `clientes`, `atendimentos` na publicação `supabase_realtime`.

### 16.2 Estrutura

- [ ] CL-6 - Criar `interface/src/app/(interface)/crm/page.tsx` (`"use client"`).
- [ ] CL-7 - Criar `interface/src/hooks/useCrm.ts` (fetch lista + detalhe + Realtime + debounced refetch).
- [ ] CL-8 - Criar `interface/src/tipos/crm.ts` com os tipos de §11.
- [ ] CL-9 - Criar componentes em `interface/src/components/crm/`.
- [ ] CL-10 - Instalar `input` e `textarea` via `pnpm dlx shadcn@latest add input textarea` se ainda não existirem.

### 16.3 Implementação

- [ ] CL-11 - Toolbar de busca + filtros (recorrência, motivo de perda, período, modelo).
- [ ] CL-12 - Lista com seleção automática da primeira conversa.
- [ ] CL-13 - Header do detalhe com badge Recorrente.
- [ ] CL-14 - Bloco "Dados do cliente" com edição inline de nome.
- [ ] CL-15 - Bloco "Dados da conversa" read-only.
- [ ] CL-16 - Bloco "Observações internas" com textarea + Salvar/Descartar contextuais e atalho `Cmd/Ctrl+Enter`.
- [ ] CL-17 - Bloco "Atendimento aberto" condicional, com "Abrir na Central".
- [ ] CL-18 - Histórico de atendimentos read-only.
- [ ] CL-19 - AlertDialog "Descartar alterações não salvas?" ao trocar conversa com dirty.
- [ ] CL-20 - Realtime + refetch debounced preservando dirty.

### 16.4 Verificação

- [ ] CL-21 - `pnpm lint` passa.
- [ ] CL-22 - `pnpm build` passa.
- [ ] CL-23 - `pnpm dev` sobe e `/crm` carrega sem erro de console.
- [ ] CL-24 - Validar filtros (recorrência, motivo de perda, período, modelo) contra dados de teste.
- [ ] CL-25 - Validar edição de nome do cliente: salvar, descartar, erro 4xx, erro 5xx.
- [ ] CL-26 - Validar edição de observações: salvar, descartar, atalho de teclado, dirty preservado em refetch.
- [ ] CL-27 - Validar empty states (lista, atendimento aberto, histórico).
- [ ] CL-28 - Validar Realtime inserindo/atualizando registros via Supabase Studio.

---

## 17. Vetos locais e pontos imutáveis da tela

### 17.1 Veto local declarado

- **Fundação §9.6** ("apenas 1 primary por tela"): nesta tela, o `button-primary` global é **contextual** — "Salvar observações" aparece apenas quando o textarea está dirty. Quando não há edição pendente, **a tela não tem nenhum primary**. **Justificativa:** o CRM é tela de leitura+edição leve; forçar um primary global inventaria CTA artificial e confundiria sinal de "há algo para salvar". **Aprovado em:** conversa de QA Tela 04 (2026-05-01).

### 17.2 Pontos imutáveis específicos

- ❌ Não permitir **mesclar clientes**, **excluir conversas** ou **alterar `recorrente`** nesta tela (P1+).
- ❌ Não permitir editar `ultimo_motivo_perda` ou `ultima_mensagem_em` (são snapshot/sistema).
- ❌ Não navegar para `/atendimentos/{id}` no P0 (deep link fora do escopo do MVP, conforme Tela 02 §17.2). "Abrir na Central" navega para `/atendimentos` sem id.
- ❌ Não fechar/abrir/perder atendimento nesta tela; ações comerciais ficam na Central.
- ❌ Não validar/recusar Pix nesta tela.
- ❌ Não exibir mensagens brutas da conversa nesta tela; histórico de mensagens fica em `/atendimentos`.
- ❌ Não persistir `observacoes_internas` automaticamente (sem autosave); salvamento explícito.
- ❌ Não consultar `observacoes_internas` na IA (campo é restrito ao painel).

---

## 18. Pontos em aberto

Nenhum ponto em aberto após alinhamento com o usuário em 2026-05-01.

---

## Anexo A - Wireframe textual

```text
┌─────────────────┬──────────────────────────────────────────────────────────────┐
│ Sidebar         │ CRM                                                          │
│ compartilhada   │ Conversas por par cliente e modelo. Histórico, recorrência   │
│                 │ e observações.                                               │
│                 │                                                              │
│                 │ [Buscar nome ou telefone] [Todas v] [Motivo v] [Período v]  │
│                 │ [Modelo v]                                                   │
│                 │                                                              │
│                 │ ┌──────────────────────────────┐ ┌─────────────────────────┐ │
│                 │ │ [Recorrente]  há 12 min      │ │ Carlos M.  [Recorrente] │ │
│                 │ │ Carlos M.                    │ │ Conversa com Júlia      │ │
│                 │ │ Júlia · perda: sumiu         │ │ Última mensagem há 12 m │ │
│                 │ │ #142 Fechado · há 1 d        │ │                         │ │
│                 │ ├──────────────────────────────┤ │ Dados do cliente        │ │
│                 │ │ Bruno                        │ │ Telefone (21) 98765...  │ │
│                 │ │ Júlia                        │ │ Nome [Carlos M.] [Sa..] │ │
│                 │ │ #141 Perdido · há 3 d        │ │ Primeiro contato Júlia  │ │
│                 │ ├──────────────────────────────┤ │                         │ │
│                 │ │ ⚠ Jorge                      │ │ Dados da conversa       │ │
│                 │ │ Júlia                        │ │ Recorrência Recorrente  │ │
│                 │ │ Aguardando confirmação       │ │ Último motivo Sumiu     │ │
│                 │ └──────────────────────────────┘ │ Última msg 01 mai 14:32 │ │
│                 │ [Carregar mais]                  │                         │ │
│                 │                                  │ OBSERVAÇÕES INTERNAS    │ │
│                 │                                  │ ┌─────────────────────┐ │ │
│                 │                                  │ │ Cliente prefere ... │ │ │
│                 │                                  │ └─────────────────────┘ │ │
│                 │                                  │ [Descartar] [Salvar...] │ │
│                 │                                  │                         │ │
│                 │                                  │ Atendimento aberto      │ │
│                 │                                  │ ┃[Em handoff] #143      │ │
│                 │                                  │ ┃interno · imediato     │ │
│                 │                                  │ ┃[Abrir na Central]     │ │
│                 │                                  │                         │ │
│                 │                                  │ Histórico               │ │
│                 │                                  │ #142 [Fechado] 29 abr   │ │
│                 │                                  │   R$ 1.200,00           │ │
│                 │                                  │ #138 [Perdido] 15 abr   │ │
│                 │                                  │   Sumiu                 │ │
│                 │                                  └─────────────────────────┘ │
└─────────────────┴──────────────────────────────────────────────────────────────┘
```

— FIM —
