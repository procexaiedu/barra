# Tela 02 - Central de Atendimentos

> **Herda decisões de** `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto local declarado em §17. Não repetir aqui o que está na fundação.

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome | Central de Atendimentos |
| Slug | `central-atendimentos` |
| Rota | `/atendimentos` |
| Arquivo Next.js | `interface/src/app/(interface)/atendimentos/page.tsx` |
| Tipo | Client Component (`"use client"`) - Realtime exige client |
| Hook próprio | `interface/src/hooks/useAtendimentos.ts` |
| Tipos | `interface/src/tipos/atendimentos.ts` |
| Componentes próprios | `interface/src/components/atendimentos/{ListaAtendimentos,ItemAtendimento,DetalheAtendimento,ResumoAtendimento,HistoricoMensagens,LinhaEvento,AcoesAtendimento}.tsx` |

---

## 2. Objetivo

Centralizar os ciclos comerciais da operação, permitindo que Fernando veja rapidamente quais atendimentos estão em andamento, inspecione o contexto completo de um atendimento e execute as ações humanas do P0: **Devolver para IA**, **Fechar** e **Perder**.

Citação literal de `docs/mvp/06-dados-interfaces.md` §4.2: *"Lista e detalhe dos atendimentos abertos."*

---

## 3. Contexto funcional

- **Usuário no P0:** Fernando.
- **Escopo padrão da lista:** atendimentos abertos, isto é, `estado NOT IN ('Fechado', 'Perdido')`.
- **Filtro:** a tela permite filtrar também `Fechado` e `Perdido`.
- **Detalhe inicial:** ao carregar `/atendimentos`, selecionar automaticamente o atendimento mais recente da lista carregada.
- **Escrita inline:** `Devolver para IA`, `Fechar`, `Perder`.
- **Fora do escopo desta tela:** `Corrigir registro`, validação/recusa de Pix e edição de conteúdo bruto de mensagens.
- **Origem dos dados:** endpoints REST de atendimentos (§12).
- **Realtime:** assinatura em `atendimentos`, `mensagens`, `eventos` e `comprovantes_pix` (§13).

---

## 4. Fluxo do usuário

### 4.1 Caminho feliz

1. Fernando acessa `/atendimentos`.
2. A tela carrega skeleton da lista e do detalhe.
3. `useAtendimentos` chama `GET /api/atendimentos` com filtro padrão de abertos.
4. Ao receber a lista, a tela seleciona automaticamente o item mais recente.
5. A seleção dispara `GET /api/atendimentos/{id}`.
6. O detalhe mostra resumo operacional, histórico de mensagens com prévia expansível, mídias recebidas e linha do tempo de eventos.
7. Fernando aplica filtros ou busca; a lista refaz o fetch e seleciona o primeiro item do novo resultado.
8. Fernando executa uma ação permitida no detalhe; a tela abre `<AlertDialog>`, confirma, chama o endpoint e atualiza via Realtime/refetch.

### 4.2 Caminhos alternativos específicos

| Cenário | Comportamento |
|---|---|
| Lista vazia com filtro padrão | Empty state: "Nenhum atendimento aberto." |
| Lista vazia com filtros aplicados | Empty state: "Nenhum atendimento encontrado para estes filtros." |
| Atendimento selecionado sai do filtro após Realtime | Mantém o detalhe visível até o refetch concluir; depois seleciona o primeiro item da nova lista. Se a lista ficar vazia, mostra empty state no detalhe. |
| Filtro inclui `Fechado` ou `Perdido` | Detalhe é read-only; botões de ação ficam ocultos. |
| Mensagem longa | Mostra prévia; expansão inline por clique deliberado. |

---

## 5. Layout detalhado dos blocos próprios

> Sidebar e shell de 2 colunas vêm da fundação §5. Esta seção descreve apenas o conteúdo do `<main>` da rota `/atendimentos`.

Estrutura dentro do `<main>`:

```
[Cabeçalho da página]
[Toolbar de filtros e busca]
[Split 360px lista | detalhe flexível]
```

### 5.1 Cabeçalho da página

- Título "Atendimentos" em Cormorant Garamond `display-lg`.
- Subtítulo `body-sm --text-muted`: "Ciclos comerciais e handoffs da IA por modelo."
- Sem botão primary global no cabeçalho.

### 5.2 Toolbar de filtros

- Linha horizontal com busca e filtros.
- Busca por nome, telefone ou `#N`.
- Controles:

| Controle | Tipo | Opções |
|---|---|---|
| Busca | input | placeholder "Buscar cliente, telefone ou #N" |
| Estado | select | `Abertos`, `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`, `Confirmado`, `Em_execucao`, `Fechado`, `Perdido` |
| Tipo | select | `Todos`, `interno`, `externo` |
| Urgência | select | `Todas`, `imediato`, `agendado`, `indefinido`, `estimado` |
| IA | select | `Todos`, `IA ativa`, `IA pausada` |

- Busca com debounce 300ms.
- Mudança de filtro reseta paginação/cursor.

### 5.3 Split lista/detalhe

- Grid de duas colunas:
  - Lista: largura fixa 360px.
  - Detalhe: ocupa o restante.
- Gap `spacing.5`.
- Altura mínima: `calc(100vh - shell/header)`, sem esconder conteúdo essencial.

### 5.4 Lista de atendimentos

- Container `<section aria-label="Lista de atendimentos">`.
- Lista vertical de cards compactos, sem card dentro de card.
- Ordenação: `updated_at DESC`.
- Paginação: cursor simples com botão ghost "Carregar mais" no fim.

#### 5.4.1 Item da lista

Conteúdo:

```
[Badge estado] [#N mono] [tempo relativo]
Cliente ou telefone
Modelo · tipo · urgência
Motivo/proxima ação quando houver ia_pausada
```

- Card clicável com `role="button"` e `aria-pressed` quando selecionado.
- Selecionado: borda esquerda `3px solid var(--gold-500)`.
- Com `ia_pausada=true`: borda esquerda `3px solid var(--warn-500)` se não selecionado.
- Estados `Fechado` e `Perdido` usam badge `closed`/`lost`.
- Telefone usa `formatTelefone` da fundação, sem mascaramento.

#### 5.4.2 Empty state da lista

Filtro padrão:

```
Nenhum atendimento aberto.
Novos atendimentos aparecem quando clientes chamarem no WhatsApp da modelo.
```

Com filtros:

```
Nenhum atendimento encontrado para estes filtros.
Ajuste busca, estado, tipo, urgência ou pausa da IA.
```

### 5.5 Detalhe do atendimento

Container `<section aria-label="Detalhe do atendimento">`.

Ordem dos blocos:

```
[Header do atendimento]
[Ações]
[Resumo operacional]
[Histórico de mensagens]
[Mídias recebidas]
[Linha do tempo de eventos]
```

### 5.6 Header do atendimento

Mostra:

- Badge de estado.
- `#N` em mono.
- Cliente: nome ou telefone formatado.
- Modelo.
- Última atualização via `formatTempoRelativo`.
- Indicador de IA:
  - `Ativa` quando `ia_pausada=false`.
  - `Em handoff` quando `ia_pausada=true` e motivo `handoff_ia`.
  - `Em revisão` quando motivo `pix_em_revisao`.
  - `Pausada` quando motivo `modelo_em_atendimento`.

### 5.7 Ações do atendimento

As ações aparecem apenas quando `estado NOT IN ('Fechado', 'Perdido')`.

| Ação | Quando aparece | Variante |
|---|---|---|
| `Devolver para IA` | `ia_pausada=true` e backend permitir devolução | `primary` |
| `Fechar` | atendimento aberto | `primary` se `Devolver para IA` não estiver visível; senão `secondary` |
| `Perder` | atendimento aberto | `danger` |

- Regra de primary: no máximo uma ação primary visível no detalhe.
- `Corrigir registro` não aparece nesta tela.
- Pix em revisão não oferece validar/recusar aqui; usar `/pix`.

### 5.8 Resumo operacional

Card único com grupos em `<dl>`:

| Grupo | Campos |
|---|---|
| Comercial | estado, tipo, urgência, valor acordado, forma de pagamento |
| Agenda/local | data desejada, horário desejado, duração, endereço, bairro, tipo local |
| IA/handoff | responsável atual, motivo de escalada, próxima ação esperada, resumo operacional |
| Qualificação | sinais de qualificação em chips booleanos |
| Pix | `pix_status` e último comprovante se existir |
| Bloqueio | horário, estado e link para `/agenda?bloqueio={id}` se existir |

- Campos ausentes aparecem como `Não informado`, não como traço.
- Endereço aparece apenas quando persistido; a tela não pede nem edita endereço.

### 5.9 Histórico de mensagens

- Read-only.
- Ordenação visual: mais antigas em cima, mais recentes embaixo.
- Backend pode retornar em `DESC`; front normaliza para exibição cronológica.
- Cada mensagem mostra:
  - Direção: `cliente`, `ia`, `modelo_manual`.
  - Tipo: `texto`, `audio`, `imagem`.
  - Horário.
  - Prévia do conteúdo.

#### 5.9.1 Prévia e expansão

- Texto/transcrição com até 2 linhas por padrão.
- Se exceder 2 linhas, mostra botão ghost pequeno "Expandir".
- Clique expande inline e muda para "Recolher".
- Imagem/mídia nunca tem preview automático; renderiza chip mono com `media_object_key` ou nome derivado e botão "Abrir mídia" quando houver URL assinada disponível.

### 5.10 Mídias recebidas

- Lista chips de comprovantes Pix, fotos de portaria e outras imagens vinculadas ao atendimento.
- Sem preview automático.
- Clique deliberado abre modal simples com fundo `--ink-0`, quando o backend fornecer URL assinada.
- Se não houver mídia: empty state compacto "Nenhuma mídia recebida neste atendimento."

### 5.11 Linha do tempo de eventos

- Lista cronológica reversa (`created_at DESC`).
- Cada linha mostra:
  - tipo de evento em label legível;
  - origem;
  - autor;
  - horário;
  - resumo curto do payload quando aplicável.
- Conteúdo bruto de payload grande fica recolhido por padrão.

---

## 6. AlertDialogs e formulários

### 6.1 `Devolver para IA`

Padrão da fundação §9.5.

Texto:

```
Devolver #N para a IA?
A IA voltará a responder o cliente apenas na próxima mensagem recebida. O histórico da pausa continuará registrado.
```

Endpoint: `POST /api/atendimentos/{id}/devolver`.

Body:

```json
{ "observacao": null }
```

Toast de sucesso: `Atendimento #N devolvido para a IA`.

### 6.2 `Fechar`

Abre AlertDialog com input de **Valor final**.

Validações:

- valor obrigatório;
- número maior ou igual a zero;
- aceita vírgula brasileira no input, normaliza para decimal antes do POST.

Endpoint: `POST /api/atendimentos/{id}/fechar`.

Body:

```json
{ "valor_final": 1200.00 }
```

Toast de sucesso: `Atendimento #N fechado`.

### 6.3 `Perder`

Abre AlertDialog com select de **Motivo de perda**.

Motivos fechados:

- `preco`
- `sumiu`
- `risco`
- `indisponibilidade`
- `fora_de_area`
- `outro`

Quando `outro`, campo `observacao` é obrigatório.

Endpoint: `POST /api/atendimentos/{id}/perder`.

Body:

```json
{ "motivo": "sumiu", "observacao": null }
```

Toast de sucesso: `Atendimento #N marcado como perdido`.

---

## 7. Comportamentos esperados

### 7.1 Inicialização

`useEffect` no mount:

1. Carrega lista com filtro padrão de abertos.
2. Seleciona o primeiro item retornado.
3. Carrega detalhe do item selecionado.
4. Abre subscriptions Realtime (§13).
5. Registra listener `onAuthStateChange` conforme fundação §6.3.

### 7.2 Mudança de filtros

- Atualiza query local.
- Debounce apenas na busca textual.
- Cancela seleção anterior.
- Após novo resultado, seleciona automaticamente o primeiro item.

### 7.3 Seleção manual

- Clique ou Enter/Space em item da lista seleciona o atendimento.
- URL pode permanecer `/atendimentos` no P0; deep link `/atendimentos/{id}` fica fora desta spec.

### 7.4 Reconciliação Realtime

- Eventos em tabelas observadas disparam refetch debounced 250ms.
- Se houver atendimento selecionado, refetch do detalhe também ocorre.
- Sem patch local; snapshot REST é fonte de reconciliação.

### 7.5 Teclado / a11y

Ordem do Tab:

1. Sidebar.
2. Busca e filtros.
3. Itens da lista.
4. Ações do detalhe.
5. Controles de expansão de mensagens/mídias/eventos.

Roles:

- `<section aria-label="Lista de atendimentos">`.
- `<section aria-label="Detalhe do atendimento">`.
- Lista com itens focáveis por teclado.
- `<dl>` para resumo operacional.

---

## 8. Estados específicos da tela

| Estado | Quando | Aparência |
|---|---|---|
| `loading-lista` | primeiro fetch da lista | skeleton de toolbar + 8 itens |
| `loading-detalhe` | primeiro fetch do detalhe | skeleton de header, ações, resumo e mensagens |
| `success-vazio-lista` | lista vazia | empty state §5.4.2 |
| `success-sem-selecao` | lista vazia ou erro de detalhe | painel de detalhe com empty/banner |
| `submitting` | ação em voo | botões do dialog desabilitados + spinner inline |
| `mensagem-expandida` | usuário clicou Expandir | texto completo inline |

### 8.1 Skeletons específicos

- Lista: 8 linhas-fantasma de 88px.
- Detalhe header: 96px.
- Resumo: card com 8 pares label/valor.
- Mensagens: 6 linhas-fantasma de 64px.
- Eventos: 4 linhas-fantasma de 48px.

---

## 9. Regras de negócio

### 9.1 Lista

- Filtro padrão: abertos (`estado NOT IN ('Fechado', 'Perdido')`).
- Estados fechados/perdidos só aparecem quando o filtro de estado pedir explicitamente.
- Ordenação: `updated_at DESC`.
- Busca aceita nome, telefone e `numero_curto`.

### 9.2 Devolução para IA

- A tela só renderiza o botão quando `ia_pausada=true`.
- Backend decide se o motivo permite devolução.
- Após devolução, a IA não envia mensagem proativa; aguarda próxima mensagem do cliente.

### 9.3 Fechar

- Exige **Valor final**.
- Fechamento registra `Registro de resultado`.
- Após sucesso, atendimento sai do filtro padrão de abertos.

### 9.4 Perder

- Exige **Motivo de perda**.
- `outro` exige observação.
- Após sucesso, atendimento sai do filtro padrão de abertos.

### 9.5 Histórico

- Mensagens do grupo de **Coordenação por modelo** não aparecem em `mensagens`.
- Cards, comandos e confirmações aparecem por `eventos`/`escaladas`, quando persistidos.
- Conteúdo bruto de mensagens é read-only.

---

## 10. Validações

| Onde | Validação | Falha |
|---|---|---|
| Front | Valor final preenchido e numérico | Mantém dialog aberto e mostra erro inline |
| Front | `motivo='outro'` com observação preenchida | Mantém dialog aberto e mostra erro inline |
| Front | Não renderizar ações para `Fechado`/`Perdido` | Detalhe read-only |
| Backend | Atendimento existe | 404 `{ detail: "Atendimento não encontrado" }` |
| Backend | Usuário tem permissão | 403; toast com `detail` ou "Sem permissão" |
| Backend | Regras de estado/pausa válidas | 409; toast com `detail` e dialog permanece aberto |

---

## 11. Dados - tipos próprios da tela

Arquivo: `interface/src/tipos/atendimentos.ts`.

```ts
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
export type IaPausadaMotivo = 'pix_em_revisao' | 'modelo_em_atendimento' | 'handoff_ia';
export type ResponsavelAtual = 'IA' | 'Fernando' | 'modelo';
export type MotivoPerda = 'preco' | 'sumiu' | 'risco' | 'indisponibilidade' | 'fora_de_area' | 'outro';
export type DirecaoMensagem = 'cliente' | 'ia' | 'modelo_manual';
export type TipoMensagem = 'texto' | 'audio' | 'imagem';

export interface AtendimentoListaItem {
  id: string;
  numero_curto: number;
  cliente: {
    id: string;
    nome: string | null;
    telefone: string;
  };
  modelo: {
    id: string;
    nome: string;
  };
  estado: EstadoAtendimento;
  tipo_atendimento: TipoAtendimento | null;
  urgencia: Urgencia | null;
  ia_pausada: boolean;
  ia_pausada_motivo: IaPausadaMotivo | null;
  responsavel_atual: ResponsavelAtual;
  motivo_escalada: string | null;
  proxima_acao_esperada: string | null;
  updated_at: string;
}

export interface AtendimentosListaResponse {
  items: AtendimentoListaItem[];
  next_cursor: string | null;
}

export interface MensagemAtendimento {
  id: string;
  direcao: DirecaoMensagem;
  tipo: TipoMensagem;
  conteudo: string;
  media_object_key: string | null;
  created_at: string;
}

export interface EventoAtendimento {
  id: string;
  tipo: string;
  origem: string;
  autor: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ComprovantePixResumo {
  id: string;
  valor_extraido: number | null;
  chave_extraida: string | null;
  titular_extraido: string | null;
  decisao_pipeline: 'validado' | 'em_revisao';
  decisao_final: 'validado' | 'invalido' | null;
  motivo_em_revisao: string | null;
  created_at: string;
}

export interface AtendimentoDetalheResponse {
  atendimento: Record<string, unknown>;
  cliente: {
    id: string;
    nome: string | null;
    telefone: string;
  };
  modelo: {
    id: string;
    nome: string;
  };
  bloqueio: {
    id: string;
    inicio: string;
    fim: string;
    estado: string;
  } | null;
  mensagens: MensagemAtendimento[];
  eventos: EventoAtendimento[];
  comprovantes_pix: ComprovantePixResumo[];
}
```

> Tipos refletem o contrato esperado de `api/src/barra/dominio/atendimentos/routes.py` em 2026-04-30, com ajuste necessário para expor telefone sem mascaramento conforme fundação §10.1.

---

## 12. API - específica desta tela

Prefixo conforme montagem do backend: `/api/atendimentos` ou `/api/v1/atendimentos` se `api/src/barra/api/v1.py` aplicar versionamento. A spec da tela usa caminhos lógicos.

### 12.1 `GET /api/atendimentos`

Query:

| Parâmetro | Tipo | Uso |
|---|---|---|
| `estado` | string opcional | omitido = abertos; valor específico filtra estado |
| `tipo_atendimento` | string opcional | `interno`/`externo` |
| `urgencia` | string opcional | urgência específica |
| `ia_pausada` | boolean opcional | true/false |
| `modelo_id` | uuid opcional | reservado para P1/múltiplas modelos |
| `q` | string opcional | nome, telefone ou `#N` |
| `limit` | number | default 50, máximo 100 |
| `cursor` | string opcional | cursor por `updated_at` |

Resposta 200:

```json
{
  "items": [
    {
      "id": "01950000-0000-7000-8000-000000000042",
      "numero_curto": 142,
      "cliente": {
        "id": "01950000-0000-7000-8000-000000000010",
        "nome": "Carlos M.",
        "telefone": "5521987654321"
      },
      "modelo": {
        "id": "01950000-0000-7000-8000-000000000001",
        "nome": "Júlia"
      },
      "estado": "Aguardando_confirmacao",
      "tipo_atendimento": "externo",
      "urgencia": "imediato",
      "ia_pausada": true,
      "ia_pausada_motivo": "handoff_ia",
      "responsavel_atual": "Fernando",
      "motivo_escalada": "Dúvida operacional",
      "proxima_acao_esperada": "Decidir se aceita o local",
      "updated_at": "2026-04-30T17:32:11-03:00"
    }
  ],
  "next_cursor": null
}
```

### 12.2 `GET /api/atendimentos/{id}`

Retorna detalhe, mensagens, eventos, comprovantes Pix e escaladas quando disponíveis.

Requisitos específicos:

- `cliente.telefone` sem mascaramento.
- Mensagens podem vir em `DESC`; front normaliza para cronológico.
- Conteúdo de mídia vem como `media_object_key`; URL assinada é opcional.

### 12.3 `POST /api/atendimentos/{id}/devolver`

Body:

```json
{ "observacao": null }
```

200:

```json
{ "id": "01950000-0000-7000-8000-000000000042", "estado": "Confirmado", "ia_pausada": false }
```

### 12.4 `POST /api/atendimentos/{id}/fechar`

Body:

```json
{ "valor_final": 1200.00 }
```

200:

```json
{ "id": "01950000-0000-7000-8000-000000000042", "estado": "Fechado" }
```

### 12.5 `POST /api/atendimentos/{id}/perder`

Body:

```json
{ "motivo": "sumiu", "observacao": null }
```

200:

```json
{ "id": "01950000-0000-7000-8000-000000000042", "estado": "Perdido" }
```

---

## 13. Realtime - específico desta tela

### 13.1 Subscriptions

Tabelas observadas:

- `atendimentos` - lista, estado, pausa, resultado, resumo.
- `mensagens` - histórico do detalhe selecionado.
- `eventos` - linha do tempo e ações concluídas.
- `comprovantes_pix` - mídia/dados Pix vinculados ao atendimento.

```ts
const cleanup = subscribeTabelas(
  'atendimentos',
  ['atendimentos', 'mensagens', 'eventos', 'comprovantes_pix'],
  debouncedRefetch,
);
```

### 13.2 Refetch

- Evento em qualquer tabela refaz lista e detalhe selecionado.
- Refetch debounced 250ms.
- Sem skeleton em refetch após primeiro sucesso.

---

## 14. Mudanças estruturais necessárias

| Antes | Depois | Ação |
|---|---|---|
| `interface/src/app/(interface)/atendimentos/` ausente ou stub | rota real | criar `page.tsx` |
| n/a | hook próprio | criar `interface/src/hooks/useAtendimentos.ts` |
| n/a | tipos próprios | criar `interface/src/tipos/atendimentos.ts` |
| n/a | componentes próprios | criar pasta `interface/src/components/atendimentos/` |
| backend retorna `telefone_mascarado` | contrato sem mascaramento | ajustar endpoint ou adaptar novo campo antes da tela |

### 14.1 Navegações disparadas pela tela

| Trigger | Destino |
|---|---|
| Link de bloqueio no resumo | `/agenda?bloqueio={id}` |
| Pix em revisão citado no detalhe | `/pix?atendimento={id}` |

---

## 15. Critérios de aceite específicos

> Critérios estruturais vêm da fundação §14. Aqui só os específicos da tela.

- [ ] AC-1 - `/atendimentos` carrega lista e detalhe em split 360px/restante.
- [ ] AC-2 - Filtro padrão mostra apenas atendimentos abertos.
- [ ] AC-3 - Filtro de estado permite selecionar `Fechado` e `Perdido`.
- [ ] AC-4 - Ao carregar a lista, o atendimento mais recente é selecionado automaticamente.
- [ ] AC-5 - Busca por nome, telefone e `#N` refaz a lista com debounce 300ms.
- [ ] AC-6 - Itens da lista mostram badge de estado, `#N`, cliente/modelo, tipo, urgência e tempo relativo.
- [ ] AC-7 - Item com `ia_pausada=true` destaca borda esquerda em `--warn-500`.
- [ ] AC-8 - Detalhe mostra resumo operacional com campos ausentes como "Não informado".
- [ ] AC-9 - Histórico de mensagens renderiza prévia de até 2 linhas.
- [ ] AC-10 - Mensagem longa expande e recolhe inline por clique.
- [ ] AC-11 - Mídias aparecem como chips; não há preview automático.
- [ ] AC-12 - Linha do tempo mostra eventos em `created_at DESC`.
- [ ] AC-13 - `Devolver para IA` aparece apenas quando `ia_pausada=true`.
- [ ] AC-14 - Quando `Devolver para IA` está visível, ele é o único `button-primary` do detalhe.
- [ ] AC-15 - Quando `Devolver para IA` não está visível e atendimento está aberto, `Fechar` é o `button-primary`.
- [ ] AC-16 - `Perder` usa `button-danger`.
- [ ] AC-17 - `Corrigir registro` não aparece em nenhum estado.
- [ ] AC-18 - Atendimentos `Fechado` e `Perdido` exibem detalhe read-only sem ações.
- [ ] AC-19 - Fechar exige Valor final e chama `POST /api/atendimentos/{id}/fechar`.
- [ ] AC-20 - Perder exige Motivo de perda; `outro` exige observação.
- [ ] AC-21 - Sucesso em Fechar/Perder remove o item da lista quando o filtro padrão está ativo.
- [ ] AC-22 - Eventos Realtime em `atendimentos`, `mensagens`, `eventos` ou `comprovantes_pix` disparam refetch debounced.
- [ ] AC-23 - Lista vazia no filtro padrão mostra empty state "Nenhum atendimento aberto."
- [ ] AC-24 - Lista vazia com filtros mostra empty state específico de filtros.
- [ ] AC-25 - Telefone aparece formatado e sem mascaramento.

---

## 16. Checklist de implementação

### 16.1 Pré-requisitos da tela

- [ ] CL-1 - Endpoints `GET /api/atendimentos` e `GET /api/atendimentos/{id}` retornam os campos necessários.
- [ ] CL-2 - Endpoints `POST /devolver`, `POST /fechar`, `POST /perder` existem.
- [ ] CL-3 - Endpoint de lista aceita filtro padrão de abertos ou o front monta `estado` equivalente conforme contrato definido.
- [ ] CL-4 - Telefone não vem mascarado no contrato consumido pela tela.
- [ ] CL-5 - Tabelas `atendimentos`, `mensagens`, `eventos`, `comprovantes_pix` estão no Realtime.

### 16.2 Estrutura

- [ ] CL-6 - Criar `interface/src/app/(interface)/atendimentos/page.tsx`.
- [ ] CL-7 - Criar `interface/src/hooks/useAtendimentos.ts`.
- [ ] CL-8 - Criar `interface/src/tipos/atendimentos.ts`.
- [ ] CL-9 - Criar componentes próprios em `interface/src/components/atendimentos/`.

### 16.3 Implementação

- [ ] CL-10 - Toolbar de busca/filtros.
- [ ] CL-11 - Lista com seleção automática do mais recente.
- [ ] CL-12 - Detalhe com resumo operacional.
- [ ] CL-13 - Histórico com prévia expansível.
- [ ] CL-14 - Mídias como chips sem preview automático.
- [ ] CL-15 - Linha do tempo de eventos.
- [ ] CL-16 - AlertDialogs de Devolver, Fechar e Perder.
- [ ] CL-17 - Realtime + refetch debounced.

### 16.4 Verificação

- [ ] CL-18 - `pnpm lint` passa.
- [ ] CL-19 - `pnpm build` passa.
- [ ] CL-20 - `pnpm dev` sobe e `/atendimentos` carrega sem erro de console.
- [ ] CL-21 - Validar filtros, seleção automática e ações contra backend local.
- [ ] CL-22 - Validar expansão/recolhimento de mensagens longas.
- [ ] CL-23 - Validar que mídias não têm preview automático.
- [ ] CL-24 - Validar Realtime inserindo mensagem/evento de teste.

---

## 17. Vetos locais e pontos imutáveis da tela

### 17.1 Vetos locais

Nenhum veto local. A regra de um único `button-primary` é preservada por prioridade contextual no detalhe.

### 17.2 Pontos imutáveis específicos

- Não implementar `Corrigir registro` nesta tela.
- Não validar ou recusar Pix nesta tela; usar `/pix`.
- Não editar conteúdo bruto de mensagens.
- Não mostrar preview automático de mídia.
- Não criar deep link `/atendimentos/{id}` no P0 sem spec própria.
- Não transformar a Central em fila de prioridade ou score de cliente.

---

## 18. Pontos em aberto

Nenhum ponto em aberto após alinhamento com o usuário em 2026-04-30.

---

## Anexo A - Wireframe textual

```text
┌─────────────────┬──────────────────────────────────────────────────────────────┐
│ Sidebar         │ Atendimentos                                                 │
│ compartilhada   │ Ciclos comerciais e handoffs da IA por modelo.               │
│                 │                                                              │
│                 │ [Buscar cliente, telefone ou #N] [Abertos] [Tipo] [IA]       │
│                 │                                                              │
│                 │ ┌──────────────────────────────┐ ┌─────────────────────────┐ │
│                 │ │ [Em handoff] #142   há 4 min │ │ [Em handoff] #142       │ │
│                 │ │ Carlos M.                    │ │ Carlos M. · Júlia       │ │
│                 │ │ Júlia · externo · imediato   │ │ Atualizado há 4 min     │ │
│                 │ │ Decidir se aceita o local    │ │                         │ │
│                 │ ├──────────────────────────────┤ │ [Devolver para IA]      │ │
│                 │ │ [Qualificado] #141 há 12 min │ │ [Fechar] [Perder]       │ │
│                 │ │ Bruno                        │ │                         │ │
│                 │ │ Júlia · interno · agendado   │ │ Resumo operacional      │ │
│                 │ └──────────────────────────────┘ │ estado, tipo, valor...  │ │
│                 │                                  │                         │ │
│                 │                                  │ Histórico de mensagens  │ │
│                 │                                  │ Cliente · 14:31         │ │
│                 │                                  │ "Queria saber se..."    │ │
│                 │                                  │ [Expandir]              │ │
│                 │                                  │                         │ │
│                 │                                  │ Mídias recebidas        │ │
│                 │                                  │ [comprovante_pix.jpg]   │ │
│                 │                                  │                         │ │
│                 │                                  │ Linha do tempo          │ │
│                 │                                  │ handoff_aberto · 14:35  │ │
│                 │                                  └─────────────────────────┘ │
└─────────────────┴──────────────────────────────────────────────────────────────┘
```

— FIM —
