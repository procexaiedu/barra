# Tela 05 - Pix de deslocamento

> **Herda decisões de** `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto local declarado em §17. Não repetir aqui o que está na fundação.

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome | Pix de deslocamento |
| Slug | `pix-deslocamento` |
| Rota | `/pix` |
| Arquivo Next.js | `interface/src/app/(interface)/pix/page.tsx` |
| Tipo | Client Component (`"use client"`) - Realtime exige client |
| Hook próprio | `interface/src/hooks/usePix.ts` |
| Tipos | `interface/src/tipos/pix.ts` |
| Componentes próprios | `interface/src/components/pix/{HeaderPix,ToolbarPix,ListaPix,ItemPix,DetalhePix,MetadadosPix,ChecagensPix,ComprovantePix,AtendimentoVinculadoPix,LinhaTempoPix,DialogVisualizarComprovante}.tsx` |

---

## 2. Objetivo

Permitir que Fernando decida com rapidez sobre cada **Pix de deslocamento** que a IA marcou para revisão humana, e ofereça uma trilha de auditoria sobre Pix aprovados automaticamente e rejeitados. **Nenhum Pix em revisão deve ficar sem decisão por mais de poucos minutos**, porque o cliente espera para sair.

Citação literal de `docs/mvp/06-dados-interfaces.md` §4.5: *"Decidir Pix duvidosos e auditar Pix aprovados automaticamente."*

---

## 3. Contexto funcional

- **Usuário no P0:** Fernando.
- **Unidade da tela:** registro em `comprovantes_pix`. Cada registro está vinculado a um atendimento e a uma conversa (par cliente, modelo).
- **Origem dos dados:** endpoints REST de Pix (§12).
- **Realtime:** assinatura em `comprovantes_pix` e `atendimentos` (§13).
- **Escopo padrão da lista:** "Pendentes" — `decisao_pipeline='em_revisao' AND decisao_final IS NULL`. Histórico (validados automaticamente, validados por Fernando, rejeitados) é alcançado pelo filtro de status na toolbar.
- **Escrita inline:** `Validar Pix`, `Rejeitar Pix`, `Reabrir Pix`. Demais ações comerciais ficam na Central de Atendimentos.
- **Fora do escopo desta tela:** abrir/fechar/perder atendimento, editar OCR, anular handoff de motivo distinto, cancelar bloqueio.

### 3.1 Efeitos colaterais que a tela apenas dispara (backend executa)

- **Aprovação manual de Pix em revisão** = handoff implícito para a modelo. Backend grava: card "saída confirmada" no grupo de **Coordenação por modelo** (com a imagem anexada), `ia_pausada=true` com motivo `modelo_em_atendimento` e atendimento → `Confirmado`. Front somente chama o endpoint e mostra toast.
- **Rejeição** = backend posta a mensagem padronizada ao cliente conforme o motivo selecionado, sem alterar estado do atendimento (permanece no estado anterior; se a IA estava pausada por `pix_em_revisao`, ela continua pausada até a próxima decisão sobre um novo comprovante).
- **Reabrir Pix Rejeitado** = backend volta `decisao_final` para `null`, mantém `decisao_pipeline='em_revisao'` e não toca no atendimento (ele já estava no estado anterior).

---

## 4. Fluxo do usuário

### 4.1 Caminho feliz

1. Fernando acessa `/pix` (ou clica em "Ver N Pix em revisão" no Painel Geral).
2. A tela carrega skeleton da lista e do detalhe.
3. `usePix` chama `GET /api/pix?status=em_revisao` (default).
4. Ao receber a lista, a tela seleciona automaticamente o primeiro item (mais antigo em revisão = topo da fila FIFO).
5. A seleção dispara `GET /api/pix/{id}`.
6. O detalhe mostra: cabeçalho com cliente/atendimento, ações, comprovante (chip), metadados extraídos, checagens automáticas, atendimento vinculado e linha do tempo.
7. Fernando clica no chip do comprovante → modal abre com a imagem (ou PDF embed) em fundo `--ink-0`.
8. Fernando clica em `Validar Pix` (primary do detalhe). AlertDialog confirma → `POST /api/pix/{id}/aprovar` → toast `Pix #{N} validado` + a tela atualiza via Realtime.
9. Ou clica em `Rejeitar Pix` (danger). AlertDialog com select de motivo + observação opcional → `POST /api/pix/{id}/rejeitar` → toast `Pix #{N} rejeitado` + atualização via Realtime.

### 4.2 Caminhos alternativos específicos da tela

| Cenário | Comportamento |
|---|---|
| Fila vazia (`status=em_revisao` sem itens) | Empty state §5.4.2 sem filtros: "Nenhum Pix aguardando decisão." |
| Lista vazia com outros filtros | Empty state §5.4.2 com filtros. |
| Pix aprovado/rejeitado/reaberto enquanto Fernando estava com ele aberto | Detalhe atualiza via Realtime; ações inválidas para o novo status somem; toast de sistema não é mostrado. |
| Deep link `?atendimento={id}` (vindo de `/atendimentos`) | Toolbar recebe filtro de atendimento via URL (não exposto como controle) e `status` muda para "Todos"; lista mostra todos os Pix do atendimento. |
| Deep link `?status=em_revisao` (vindo do Painel) | Toolbar pré-seleciona "Pendentes". |
| OCR falhou parcialmente (`valor_extraido` ausente) | Bloco metadados mostra "Não extraído" no campo; checagens correspondentes vêm com falha + motivo. |
| OCR falhou completamente (sem nenhum metadado) | Bloco metadados mostra todos como "Não extraído"; checagens vêm todas com falha; comprovante chip continua disponível para inspeção visual. |
| URL assinada do comprovante expirou ou falhou | Modal mostra `<BannerErro/>` com retry; botão de retry pede nova URL via `GET /api/pix/{id}/comprovante-url`. |

> Cenários de auth, 401, mobile, erro de rede, refresh JWT são tratados pela fundação (§§6, 7, 5.3, 9.2).

---

## 5. Layout detalhado dos blocos próprios

> Sidebar e shell de 2 colunas vêm da fundação §5. Esta seção descreve apenas o conteúdo do `<main>` da rota `/pix`.

Estrutura dentro do `<main>`:

```
[Cabeçalho da página]
[Toolbar de filtros e busca]
[Split 360px lista | detalhe flexível]
```

### 5.1 Cabeçalho da página

- Título "Pix de deslocamento" em Cormorant Garamond `display-lg`.
- Subtítulo `body-sm --text-muted`: "Decisão humana sobre Pix duvidosos e auditoria de Pix aprovados automaticamente."
- Sem botão primary global no cabeçalho.

### 5.2 Toolbar de filtros

- Linha horizontal com busca e filtros.
- Busca por valor, nome ou telefone do cliente, ou `#N` do atendimento.
- Controles:

| Controle | Tipo | Opções |
|---|---|---|
| Busca | input | placeholder "Buscar valor, cliente, telefone ou #N" |
| Status | select | `Pendentes` (default), `Validado automaticamente`, `Validado por Fernando`, `Rejeitado`, `Todos` |
| Modelo | select | `Todas` + lista de modelos ativas/pausadas (no P0 = piloto única) |
| Motivo de revisão | select | `Todos`, `valor_divergente`, `fora_da_janela`, `conta_destino_invalida`, `duplicado`, `ocr_falhou`, `outro` |
| Período de envio | select | `Todos`, `24 h`, `7 dias`, `30 dias` |

- Busca com debounce 300ms.
- Mudança de filtro reseta paginação/cursor e cancela seleção anterior; tela seleciona o primeiro item do novo resultado.
- Filtro por **atendimento vinculado** vem por URL (`?atendimento={id}`), não há controle visível no toolbar.

### 5.3 Split lista/detalhe

- Grid de duas colunas:
  - Lista: largura fixa 360px.
  - Detalhe: ocupa o restante.
- Gap `spacing.5`.
- Altura mínima: `calc(100vh - shell/header)`, sem esconder conteúdo essencial.

### 5.4 Lista de Pix

- Container `<section aria-label="Lista de Pix">`.
- Lista vertical de cards compactos.
- Ordenação: `created_at DESC` em todos os filtros, **exceto** `status='em_revisao'`/`Pendentes`, onde a ordenação é `created_at ASC` (FIFO — mais antigo no topo, porque o cliente está esperando).
- Paginação: cursor simples com botão ghost "Carregar mais" no fim.

#### 5.4.1 Item da lista

Conteúdo:

```
[Badge status] [tempo relativo]
[Valor formatado em BRL] (heading-md --text-primary)
Cliente · Modelo · #N (caption --text-muted)
Motivo de revisão quando houver (body-sm --text-muted)
```

- Card clicável com `role="button"` e `aria-pressed` quando selecionado.
- Selecionado: borda esquerda `3px solid var(--gold-500)`.
- Status `em_revisao` (sem decisão final): borda esquerda `3px solid var(--warn-500)` quando não selecionado.
- Status `validado` (auto ou manual) e `invalido` aparecem sem borda lateral colorida quando não selecionados.
- Telefone e nome usam `formatTelefone` da fundação, sem mascaramento.
- Valor usa `formatBRL`. Quando `valor_extraido` é null, mostra "Valor não extraído" em `--text-muted`.

#### 5.4.2 Mapeamento badge por status

| Combinação | Variante | Label |
|---|---|---|
| `decisao_pipeline='em_revisao' AND decisao_final IS NULL` | `revisao` | "Em revisão" |
| `decisao_pipeline='validado' AND decisao_final IS NULL` | `closed` | "Validado auto" |
| `decisao_final='validado'` | `closed` | "Validado por Fernando" |
| `decisao_final='invalido'` | `lost` | "Rejeitado" |

#### 5.4.3 Empty state da lista

Filtro padrão (Pendentes):

```
Nenhum Pix aguardando decisão.
Pix duvidosos aparecem aqui automaticamente quando a IA pausar por pix_em_revisao.
```

Com filtros explícitos:

```
Nenhum Pix encontrado para estes filtros.
Ajuste status, modelo, motivo de revisão ou período.
```

### 5.5 Detalhe do Pix

Container `<section aria-label="Detalhe do Pix">`.

Ordem dos blocos:

```
[Header do Pix]
[Ações]
[Comprovante]
[Metadados extraídos]
[Checagens automáticas]
[Atendimento vinculado]
[Linha do tempo]
```

### 5.6 Header do Pix

Mostra:

- Badge de status (variante conforme §5.4.2).
- Cliente: nome em `heading-lg --text-primary` (ou telefone formatado se nome ausente).
- Modelo da conversa em `body-sm --text-muted`: "Conversa com {modelo.nome}".
- Recebido `formatTempoRelativo(comprovante.created_at)`.

### 5.7 Ações

| Ação | Quando aparece | Variante |
|---|---|---|
| `Validar Pix` | `decisao_pipeline='em_revisao' AND decisao_final IS NULL` | `primary` |
| `Rejeitar Pix` | `decisao_pipeline='em_revisao' AND decisao_final IS NULL` | `danger` |
| `Reabrir Pix` | `decisao_final='invalido'` | `secondary` |
| `Abrir atendimento` | sempre que `atendimento` não for null | `ghost` |
| `Abrir conversa` | sempre que `conversa` não for null | `ghost` |

- Regra de primary: no máximo 1 visível no detalhe. `Validar Pix` é o primary contextual (mesmo padrão da Tela 02 com "Devolver para IA").
- Pix com `decisao_pipeline='validado' AND decisao_final IS NULL` (validado automaticamente, sem revisão humana) é **read-only**: nenhuma das três ações de decisão aparece. Há apenas `Abrir atendimento` e `Abrir conversa` em `ghost`.
- Pix com `decisao_final='validado'` (validado por Fernando) também é **read-only**: sem reabrir, sem rejeitar (decisão imutável).

### 5.8 Comprovante

Card único:

- Label `caption --text-muted maiúsculo`: "COMPROVANTE".
- Linha 1: chip mono com `nome_arquivo` + `formatBytes(tamanho)` (ex.: `comprovante.jpg · 412 KB`). Ícone `Paperclip` 16px à esquerda.
- Linha 2: botão `button-secondary` "Visualizar comprovante" com ícone `Eye` 16px.
- Click no botão (ou no chip) → abre `DialogVisualizarComprovante` (§6.4).
- **Sem preview automático** (fundação §9.8).
- Quando `mime_type` começa com `image/`: modal renderiza `<img>` com `max-width: 90vw; max-height: 90vh; object-fit: contain`.
- Quando `mime_type='application/pdf'`: modal renderiza `<iframe>` com URL assinada (mesma altura/largura), e botão `button-ghost` "Abrir em nova aba" como fallback.

### 5.9 Metadados extraídos

Card com `<dl>` read-only:

| Campo | Conteúdo |
|---|---|
| Valor | `formatBRL(valor_extraido)` ou "Não extraído" em `--text-muted`. |
| Data/hora da transação | `formatDataHora(horario_transacao)` ou "Não extraído". |
| Remetente | `titular_extraido` ou "Não extraído". CPF/CNPJ aparecem ao lado em mono-sm quando `documento_extraido` presente. |
| Chave/conta destino | `chave_extraida` em mono-sm; tipo (CPF/CNPJ/email/telefone/aleatória) em `caption --text-muted`. |
| Hash de duplicidade | `hash_duplicidade` em mono-sm `--text-muted`, truncado a 12 caracteres com tooltip mostrando o hash completo. |

- Campos ausentes aparecem como `Não extraído` em `--text-muted`, nunca como traço.
- Endereço/dados sensíveis adicionais não aparecem nesta tela.

### 5.10 Checagens automáticas

Card `<section aria-label="Checagens automáticas">` listando o array `checagens[]` retornado pelo backend (§11). Cada linha:

```
[ícone CheckCircle2/XCircle] [nome da checagem] (heading-sm --text-primary)
[motivo curto quando falhar] (body-sm --text-muted)
```

- Linhas com `passou=true`: ícone `CheckCircle2 --success-500` 16px, sem motivo.
- Linhas com `passou=false`: ícone `XCircle --danger-500` 16px, motivo em `--text-muted`.
- Bloco renderiza **mesmo em Pix validado automaticamente** — auditoria.
- Ordem: a do array (backend define).

#### 5.10.1 Checagens canônicas (vocabulário fechado)

| `chave` | Label visível | Critério (referência) |
|---|---|---|
| `valor_esperado` | "Valor esperado" | Valor extraído == valor esperado para o atendimento. |
| `janela_temporal` | "Janela temporal" | Comprovante emitido dentro da janela aceitável a partir da combinação. |
| `duplicidade` | "Duplicidade" | `hash_duplicidade` não consta em outro `comprovantes_pix` validado. |
| `conta_destino` | "Conta destino" | `chave_extraida` corresponde à conta cadastrada para a modelo. |

Backend pode adicionar checagens novas no futuro (`chave` desconhecida pelo front renderiza com label = `chave` capitalizada). Front nunca renderiza zero checagens; se array vier vazio, mostra empty inline "Nenhuma checagem registrada para este Pix."

### 5.11 Atendimento vinculado

Renderiza **apenas quando** `atendimento !== null`.

Card com `border-left: 3px solid var(--warn-500)` quando o atendimento ainda não está em `Fechado`/`Perdido`; `border-left: 3px solid var(--ink-400)` quando terminal.

```
[Badge estado] [#N mono-sm] [cliente]
Tipo · urgência · valor acordado quando houver
Próxima ação esperada quando houver
[button-ghost "Abrir na Central"]
```

- Botão "Abrir na Central" → `router.push('/atendimentos')`. Deep link `/atendimentos/{id}` está fora do P0 conforme Tela 02 §17.2.
- O bloco inteiro **não** é clicável; apenas o botão.

#### 5.11.1 Empty state

Quando `atendimento === null` (caso degenerado — só ocorre se o vínculo for perdido por inconsistência de dados):

```
Pix sem atendimento vinculado.
```

`body-sm --text-muted`, sem CTA.

### 5.12 Linha do tempo

- Container `<section aria-label="Linha do tempo do Pix">`.
- Lista cronológica reversa por `created_at DESC` do array `eventos[]` retornado pelo detalhe.
- Cada linha (altura 56px, padding `spacing.3 spacing.4`, separadas por `1px var(--border)`):

```
[ícone do tipo] [Label do evento] [autor] [tempo absoluto]
[resumo curto quando aplicável]
```

#### 5.12.1 Eventos canônicos

| `tipo` | Label visível | Ícone Lucide | Origem típica |
|---|---|---|---|
| `comprovante_recebido` | "Comprovante recebido" | `Inbox` `--text-muted` | webhook |
| `pipeline_validado` | "Pipeline validou automaticamente" | `CheckCircle2` `--success-500` | sistema |
| `pipeline_em_revisao` | "Pipeline marcou em revisão" | `AlertCircle` `--warn-500` | sistema |
| `pix_validado_manual` | "Validado por Fernando" | `CheckCircle2` `--success-500` | painel |
| `pix_rejeitado` | "Rejeitado por Fernando" | `XCircle` `--danger-500` | painel |
| `pix_reaberto` | "Reaberto por Fernando" | `RefreshCw` `--warn-500` | painel |

- Linhas com `tipo` desconhecido renderizam com label legível derivado do `tipo` e ícone neutro `Dot`.
- `resumo curto`: quando `tipo='pix_rejeitado'`, mostra `motivo` + observação truncada (40 chars). Outros eventos mostram resumo se vier do backend; senão, omite linha 2.

---

## 6. AlertDialogs e Dialogs

### 6.1 `Validar Pix`

Padrão da fundação §9.5.

```
Validar Pix manualmente?

A IA será reativada para a modelo: card "saída confirmada" será enviado no
grupo de Coordenação por modelo, a IA pausa por modelo_em_atendimento e o
atendimento avança para Confirmado. Esta decisão é definitiva.

[Cancelar] [Confirmar validação]
```

Endpoint: `POST /api/pix/{id}/aprovar`.

Body:

```json
{}
```

Toast de sucesso: `Pix de {valor} validado`.

### 6.2 `Rejeitar Pix`

AlertDialog com select de motivo e observação opcional.

Estrutura:

```
Rejeitar Pix?

Selecionando o motivo abaixo, a IA enviará a mensagem padrão correspondente
ao cliente pedindo um novo comprovante. O atendimento permanece no estado
atual e a IA continua pausada por pix_em_revisao até receber novo Pix.

[ Motivo: select ]
[ Observação interna (opcional): textarea ]   ← obrigatória se motivo='outro'

[Cancelar] [Confirmar rejeição]
```

Motivos canônicos:

| `motivo` | Label visível |
|---|---|
| `valor_incorreto` | "Valor incorreto" |
| `comprovante_ilegivel` | "Comprovante ilegível" |
| `conta_destino_errada` | "Conta destino errada" |
| `duplicado` | "Comprovante duplicado" |
| `fora_da_janela` | "Fora da janela temporal" |
| `outro` | "Outro" |

- Quando `motivo='outro'`, `observacao` é obrigatória (front bloqueia confirmar).
- `observacao` é interna (registrada no evento `pix_rejeitado`); a mensagem ao cliente é definida pelo backend a partir do `motivo`.
- Limite `observacao`: 500 caracteres.

Endpoint: `POST /api/pix/{id}/rejeitar`.

Body:

```json
{ "motivo": "valor_incorreto", "observacao": null }
```

Toast de sucesso: `Pix rejeitado`.

### 6.3 `Reabrir Pix`

Padrão da fundação §9.5.

```
Reabrir Pix?

O Pix volta para a fila de revisão. O atendimento não é alterado.

[Cancelar] [Confirmar reabertura]
```

Endpoint: `POST /api/pix/{id}/reabrir`.

Body:

```json
{}
```

Toast de sucesso: `Pix reaberto para revisão`.

### 6.4 `DialogVisualizarComprovante`

Modal sem AlertDialog (sem confirmação destrutiva).

- Fundo do modal: `--ink-0` (sem decoração — fundação §9.8).
- Conteúdo:
  - imagem (`<img>`) ou PDF (`<iframe>`), centralizada;
  - botão `button-ghost` no canto superior direito: "Fechar" (`X` 16px);
  - link `button-ghost` "Abrir em nova aba" no rodapé do modal (URL assinada).
- Esc/click fora fecha.
- Sem download direto — Fernando tem acesso à URL assinada se realmente precisar baixar.
- Front pede a URL assinada via `GET /api/pix/{id}/comprovante-url` quando o detalhe é carregado e cacheia em estado local. Em caso de expiração (erro 4xx ao carregar), `<BannerErro/>` no modal com retry que reusa o mesmo endpoint.

---

## 7. Comportamentos esperados

### 7.1 Inicialização

`useEffect` no mount:

1. Lê query string para detectar `status` e `atendimento`.
2. Carrega lista via `api('/pix?...filtros')`.
3. Seleciona o primeiro item retornado.
4. Carrega detalhe do item selecionado via `api('/pix/{id}')`.
5. Pede URL assinada do comprovante via `api('/pix/{id}/comprovante-url')` em paralelo.
6. Abre subscriptions Realtime (§13).
7. Registra listener `onAuthStateChange` conforme fundação §6.3.

### 7.2 Mudança de filtros

- Atualiza query local e a URL (sem reload — `router.replace`).
- Debounce apenas na busca textual (300ms).
- Cancela seleção anterior.
- Após novo resultado, seleciona o primeiro item.

### 7.3 Seleção manual

- Clique ou Enter/Space em item da lista seleciona o Pix.
- URL pode permanecer `/pix?...` no P0; deep link `/pix/{id}` fica fora desta spec.
- Trocar de seleção descarta o estado local da URL assinada do comprovante anterior.

### 7.4 Ações

```
click Validar Pix
  -> AlertDialog
  -> confirmar
    -> setLoading(true)
    -> POST /api/pix/{id}/aprovar
      -> 200 fecha dialog + toast `Pix de {valor} validado`
      -> 409 mantém dialog + toast com detail
      -> 401 fundação §6.4
      -> 5xx mantém dialog + toast genérico

click Rejeitar Pix
  -> AlertDialog com select de motivo e textarea
  -> confirmar (validações §10)
    -> POST /api/pix/{id}/rejeitar
      -> 200 fecha dialog + toast `Pix rejeitado`
      -> 4xx/5xx idem acima

click Reabrir Pix
  -> AlertDialog
  -> confirmar
    -> POST /api/pix/{id}/reabrir
      -> 200 fecha dialog + toast `Pix reaberto para revisão`
```

### 7.5 Reconciliação Realtime

- Eventos em tabelas observadas disparam refetch debounced 250ms (lista + detalhe selecionado).
- Sem patch local; snapshot REST é fonte de reconciliação.
- Se o Pix selecionado sair do filtro corrente após Realtime, mantém o detalhe visível até o refetch concluir; depois seleciona o primeiro item da nova lista.

### 7.6 Teclado / a11y

Ordem do Tab:

1. Sidebar.
2. Busca e filtros.
3. Itens da lista.
4. Ações do detalhe.
5. Botão `Visualizar comprovante`.
6. Botão `Abrir na Central` no atendimento vinculado.

Roles:

- `<section aria-label="Lista de Pix">`.
- `<section aria-label="Detalhe do Pix">`.
- `<dl>` para metadados extraídos.
- `<section aria-label="Checagens automáticas">`.
- `<section aria-label="Linha do tempo do Pix">`.
- Lista com itens focáveis por teclado.

---

## 8. Estados específicos da tela

| Estado | Quando | Aparência |
|---|---|---|
| `loading-lista` | primeiro fetch da lista | skeleton de toolbar + 8 itens |
| `loading-detalhe` | primeiro fetch do detalhe | skeleton de header, ações, comprovante, metadados, checagens |
| `success-vazio-lista` | lista vazia | empty state §5.4.3 |
| `success-sem-selecao` | lista vazia ou erro de detalhe | painel de detalhe com empty/banner |
| `success-readonly` | Pix validado auto, validado manual ou rejeitado (sem reabrir aberto) | sem ações primárias/perigosas |
| `submitting` | ação em vôo (validar/rejeitar/reabrir) | botões do dialog desabilitados + spinner inline |
| `comprovante-loading` | URL assinada em fetch | chip + botão `Visualizar comprovante` desabilitado com spinner inline 16px |
| `comprovante-erro` | URL assinada falhou | chip mantém-se; botão troca para "Tentar novamente" em variante danger |

### 8.1 Skeletons específicos

- Lista: 8 linhas-fantasma de 88px.
- Detalhe header: 64px.
- Comprovante: card de 96px com chip-fantasma + botão-fantasma.
- Metadados: card com 5 pares label/valor.
- Checagens: 4 linhas-fantasma de 40px.
- Atendimento vinculado: card de 96px (renderiza apenas após resolução do detalhe).
- Linha do tempo: 4 linhas-fantasma de 56px.

---

## 9. Regras de negócio

### 9.1 Lista e ordenação

- Filtro padrão: `Pendentes` (`decisao_pipeline='em_revisao' AND decisao_final IS NULL`).
- Ordenação:
  - `Pendentes` → `created_at ASC` (FIFO; cliente está esperando).
  - Demais filtros → `created_at DESC`.
- Filtro de **status** mapeia para combinações de `decisao_pipeline` + `decisao_final` (§5.4.2).
- Filtro de **modelo** filtra por `comprovantes_pix.modelo_id` (via join com atendimento/conversa).
- Filtro de **motivo de revisão** filtra por `motivo_em_revisao` (apenas registros com `decisao_pipeline='em_revisao'`).
- Filtro de **período** filtra `comprovantes_pix.created_at` em `America/Sao_Paulo`.
- Busca textual: prefixo case-insensitive em `clientes.nome`, `clientes.telefone` (após normalização para dígitos), `comprovantes_pix.valor_extraido` (string), e `atendimentos.numero_curto` quando o input começa com `#`.

### 9.2 Aprovação manual (Validar Pix)

- Permitida apenas para Pix com `decisao_pipeline='em_revisao' AND decisao_final IS NULL`.
- Backend executa o handoff implícito (`docs/mvp/05-escalada-regras-ia.md` §5): card "saída confirmada" no grupo de **Coordenação por modelo** com a imagem anexada, `ia_pausada=true` motivo `modelo_em_atendimento`, atendimento → `Confirmado`. Registro de evento `pix_validado_manual`.
- Front confia na transição: a tela só refaz fetch via Realtime e mostra toast.
- Pix `validado` automaticamente pelo pipeline **não** oferece "Validar Pix" — já está decidido pelo sistema.

### 9.3 Rejeição

- Permitida apenas para Pix com `decisao_pipeline='em_revisao' AND decisao_final IS NULL`.
- Backend posta a mensagem padronizada ao cliente conforme o `motivo` (mapa motivo→mensagem é responsabilidade de `agente/prompts/regras.md` no backend; front não conhece o texto).
- Atendimento permanece no estado anterior.
- IA continua pausada por `pix_em_revisao` até novo comprovante chegar (timeout do `pix_em_revisao` é responsabilidade do worker, fora do escopo da tela).
- Registro de evento `pix_rejeitado` com `motivo` e `observacao` opcional.

### 9.4 Reabrir

- Permitida apenas para Pix com `decisao_final='invalido'`.
- Reabrir grava `decisao_final=null` e mantém `decisao_pipeline='em_revisao'`.
- **Sem efeito colateral no atendimento** (já estava no estado anterior; este permanece igual).
- Registro de evento `pix_reaberto`.
- Pix `validado` (auto ou por Fernando) **não** oferece "Reabrir Pix" no P0 — decisão imutável; correção depende de novo comprovante do cliente.

### 9.5 Comprovante

- URL assinada vem do MinIO com expiração curta (definida no backend; front não assume valor). Front apenas refaz a chamada quando carregar uma seleção nova ou quando o usuário pedir retry.
- Sem cachear URL no localStorage (fundação §12).
- Sem preview automático (fundação §9.8) — modal sob clique deliberado.
- **Política de retenção do anexo no MinIO** é responsabilidade do backend/storage, fora do escopo desta tela. A spec exige apenas que `nome_arquivo`, `tamanho` e `mime_type` continuem disponíveis em `comprovantes_pix` após a decisão; o blob pode ser purgado em janela maior, e quando isso ocorrer o backend retorna `comprovante_disponivel=false` e o botão "Visualizar comprovante" é desabilitado com tooltip "Arquivo não está mais disponível".

### 9.6 Auditoria

- Pix validado automaticamente entra no histórico com `decisao_pipeline='validado' AND decisao_final IS NULL` e fica visível via filtro de status `Validado automaticamente`.
- Linha do tempo (§5.12) mostra todos os eventos canônicos (recebimento, decisão pipeline, decisão humana, reabertura) — auditoria por instância.
- Checagens automáticas (§5.10) renderizam mesmo em Pix já decidido — auditoria das verificações que motivaram a decisão.

---

## 10. Validações

| Onde | Validação | Falha |
|---|---|---|
| Front | `motivo` presente em rejeitar | Bloqueia confirmar; mensagem inline. |
| Front | `motivo='outro'` exige `observacao` não vazia | Bloqueia confirmar; mensagem inline. |
| Front | `observacao` ≤ 500 caracteres | Bloqueia confirmar; contador a partir de 400. |
| Front | Não renderizar Validar/Rejeitar quando o Pix não está pendente | Detalhe read-only. |
| Front | Não renderizar Reabrir quando `decisao_final !== 'invalido'` | Botão omitido. |
| Backend | Pix existe | 404 `{ detail: "Pix não encontrado" }`. |
| Backend | Pix está em estado válido para a ação | 409 com `detail`; dialog permanece aberto e mostra toast. |
| Backend | Atendimento vinculado existe e está em estado compatível | 409 com `detail`; dialog permanece aberto. |
| Backend | Usuário tem permissão | 403; toast com `detail` ou "Sem permissão". |

---

## 11. Dados - tipos próprios da tela

Arquivo: `interface/src/tipos/pix.ts`.

```ts
export type DecisaoPipeline = 'validado' | 'em_revisao';
export type DecisaoFinal = 'validado' | 'invalido' | null;
export type MotivoRevisao =
  | 'valor_divergente'
  | 'fora_da_janela'
  | 'conta_destino_invalida'
  | 'duplicado'
  | 'ocr_falhou'
  | 'outro';
export type MotivoRejeicao =
  | 'valor_incorreto'
  | 'comprovante_ilegivel'
  | 'conta_destino_errada'
  | 'duplicado'
  | 'fora_da_janela'
  | 'outro';
export type FiltroStatusPix =
  | 'pendentes'
  | 'validado_auto'
  | 'validado_manual'
  | 'rejeitado'
  | 'todos';
export type FiltroPeriodoPix = 'todos' | '24h' | '7d' | '30d';

export interface ClienteResumoPix {
  id: string;
  nome: string | null;
  telefone: string;
}

export interface ModeloResumoPix {
  id: string;
  nome: string;
}

export interface AtendimentoResumoPix {
  id: string;
  numero_curto: number;
  estado: string;
  tipo_atendimento: 'interno' | 'externo' | null;
  urgencia: 'imediato' | 'agendado' | 'indefinido' | 'estimado' | null;
  valor_acordado: number | null;
  proxima_acao_esperada: string | null;
}

export interface ConversaResumoPix {
  id: string;
}

export interface ChecagemPix {
  chave: string;
  label: string;
  passou: boolean;
  motivo: string | null;
}

export interface EventoPix {
  id: string;
  tipo: string;
  origem: string;
  autor: string;
  resumo: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface PixListaItem {
  id: string;
  cliente: ClienteResumoPix;
  modelo: ModeloResumoPix;
  atendimento: { id: string; numero_curto: number; estado: string } | null;
  decisao_pipeline: DecisaoPipeline;
  decisao_final: DecisaoFinal;
  motivo_em_revisao: MotivoRevisao | null;
  valor_extraido: number | null;
  created_at: string;
}

export interface PixListaResponse {
  items: PixListaItem[];
  next_cursor: string | null;
}

export interface PixDetalheResponse {
  pix: {
    id: string;
    decisao_pipeline: DecisaoPipeline;
    decisao_final: DecisaoFinal;
    motivo_em_revisao: MotivoRevisao | null;
    valor_extraido: number | null;
    horario_transacao: string | null;
    titular_extraido: string | null;
    documento_extraido: string | null;
    chave_extraida: string | null;
    tipo_chave: 'cpf' | 'cnpj' | 'email' | 'telefone' | 'aleatoria' | null;
    hash_duplicidade: string | null;
    nome_arquivo: string;
    tamanho: number;
    mime_type: string;
    comprovante_disponivel: boolean;
    created_at: string;
  };
  cliente: ClienteResumoPix;
  modelo: ModeloResumoPix;
  conversa: ConversaResumoPix | null;
  atendimento: AtendimentoResumoPix | null;
  checagens: ChecagemPix[];
  eventos: EventoPix[];
}

export interface ComprovanteUrlResponse {
  url: string;
  expires_at: string;
}

export interface AprovarPixInput {}

export interface RejeitarPixInput {
  motivo: MotivoRejeicao;
  observacao: string | null;
}

export interface ReabrirPixInput {}
```

> Tipos refletem o contrato esperado de `api/src/barra/dominio/pix/schemas.py` em 2026-05-01. O back deve garantir telefone sem mascaramento conforme fundação §10.1.

---

## 12. API - específica desta tela

Prefixo conforme montagem do backend (`/api/...` ou `/api/v1/...`). Esta spec usa caminhos lógicos.

### 12.1 `GET /api/pix`

Query:

| Parâmetro | Tipo | Uso |
|---|---|---|
| `status` | string opcional | `pendentes` (default) / `validado_auto` / `validado_manual` / `rejeitado` / `todos` |
| `modelo_id` | uuid opcional | filtra por modelo |
| `motivo_em_revisao` | string opcional | enum `MotivoRevisao` |
| `periodo` | string opcional | `24h` / `7d` / `30d` |
| `atendimento_id` | uuid opcional | usado apenas via deep link |
| `q` | string opcional | nome, telefone, valor, ou `#N` |
| `limit` | number | default 50, máximo 100 |
| `cursor` | string opcional | cursor por `created_at` |

Resposta 200:

```json
{
  "items": [
    {
      "id": "01950000-0000-7000-8000-000000000500",
      "cliente": {
        "id": "01950000-0000-7000-8000-000000000010",
        "nome": "Carlos M.",
        "telefone": "5521987654321"
      },
      "modelo": {
        "id": "01950000-0000-7000-8000-000000000001",
        "nome": "Júlia"
      },
      "atendimento": {
        "id": "01950000-0000-7000-8000-000000000042",
        "numero_curto": 142,
        "estado": "Aguardando_confirmacao"
      },
      "decisao_pipeline": "em_revisao",
      "decisao_final": null,
      "motivo_em_revisao": "valor_divergente",
      "valor_extraido": 195.00,
      "created_at": "2026-05-01T17:32:00-03:00"
    }
  ],
  "next_cursor": null
}
```

### 12.2 `GET /api/pix/{id}`

Retorna detalhe completo conforme `PixDetalheResponse` (§11).

Requisitos específicos:

- `cliente.telefone` sem mascaramento.
- `eventos` ordenados por `created_at DESC`.
- `checagens` ordenadas conforme regra do backend; front renderiza na ordem recebida.
- `comprovante_disponivel=false` quando o blob foi purgado pela política de retenção do MinIO.

### 12.3 `GET /api/pix/{id}/comprovante-url`

200:

```json
{
  "url": "https://minio.barra.local/.../comprovante.jpg?X-Amz-Signature=...",
  "expires_at": "2026-05-01T17:42:00-03:00"
}
```

404 quando `comprovante_disponivel=false`.

### 12.4 `POST /api/pix/{id}/aprovar`

Body: `{}`.

200:

```json
{ "id": "01950000-0000-7000-8000-000000000500", "decisao_final": "validado" }
```

409: Pix não está em revisão.

### 12.5 `POST /api/pix/{id}/rejeitar`

Body:

```json
{ "motivo": "valor_incorreto", "observacao": null }
```

200:

```json
{ "id": "01950000-0000-7000-8000-000000000500", "decisao_final": "invalido" }
```

422: motivo inválido ou observação obrigatória ausente.

409: Pix não está em revisão.

### 12.6 `POST /api/pix/{id}/reabrir`

Body: `{}`.

200:

```json
{ "id": "01950000-0000-7000-8000-000000000500", "decisao_final": null }
```

409: Pix não está em estado `invalido`.

> **Pré-requisito:** os 6 endpoints existem e foram testados em `api/` antes de codificar a tela.

---

## 13. Realtime - específico desta tela

### 13.1 Subscriptions

Tabelas observadas:

- `comprovantes_pix` - status, decisão final, motivo de revisão, novos comprovantes.
- `atendimentos` - estado do atendimento vinculado (após aprovação manual o estado muda; a tela mostra esse novo estado no bloco "Atendimento vinculado").

```ts
const cleanup = subscribeTabelas(
  'pix',
  ['comprovantes_pix', 'atendimentos'],
  debouncedRefetch,
);
```

> **Não** subscrever `eventos` — alta cardinalidade; o backend já desnormaliza eventos relevantes em `comprovantes_pix.updated_at` e o detalhe é refetchado integralmente.

### 13.2 Refetch

- Evento em qualquer tabela refaz lista e detalhe selecionado.
- Refetch debounced 250ms.
- Sem skeleton em refetch após primeiro sucesso.

---

## 14. Mudanças estruturais necessárias

| Antes | Depois | Ação |
|---|---|---|
| `interface/src/app/(interface)/pix/` ausente ou stub | rota real | criar `page.tsx` |
| n/a | hook próprio | criar `interface/src/hooks/usePix.ts` |
| n/a | tipos próprios | criar `interface/src/tipos/pix.ts` |
| n/a | componentes próprios | criar pasta `interface/src/components/pix/` |
| shadcn `dialog` ainda não instalado (caso) | adicionar | `pnpm dlx shadcn@latest add dialog` |

### 14.1 Navegações disparadas pela tela

| Trigger | Destino |
|---|---|
| Ação `Abrir atendimento` | `/atendimentos` |
| Ação `Abrir conversa` | `/crm` |
| Botão "Abrir na Central" no atendimento vinculado | `/atendimentos` |
| Link "Abrir em nova aba" no modal de comprovante | URL assinada (externa, MinIO) |

---

## 15. Critérios de aceite específicos

> Critérios estruturais vêm da fundação §14. Aqui só os específicos da tela.

- [ ] AC-1 - `/pix` carrega lista e detalhe em split 360px/restante.
- [ ] AC-2 - Filtro padrão é `Pendentes`; lista ordenada `created_at ASC` (FIFO).
- [ ] AC-3 - Demais filtros usam ordenação `created_at DESC`.
- [ ] AC-4 - Filtro de status oferece `Pendentes`, `Validado automaticamente`, `Validado por Fernando`, `Rejeitado`, `Todos`.
- [ ] AC-5 - Filtros adicionais visíveis: modelo, motivo de revisão, período de envio.
- [ ] AC-6 - Deep link `?status=em_revisao` pré-seleciona "Pendentes".
- [ ] AC-7 - Deep link `?atendimento={id}` muda status para "Todos" e filtra por atendimento (sem controle visível).
- [ ] AC-8 - Item da lista mostra badge de status, valor em BRL, cliente, modelo, `#N` e motivo de revisão quando houver.
- [ ] AC-9 - Item `Em revisão` (sem decisão final) destaca borda esquerda em `--warn-500`.
- [ ] AC-10 - Selecionado tem borda esquerda em `--gold-500`.
- [ ] AC-11 - Detalhe mostra header, ações, comprovante (chip), metadados, checagens, atendimento vinculado, linha do tempo.
- [ ] AC-12 - Comprovante aparece como chip; clique abre `DialogVisualizarComprovante` com fundo `--ink-0`.
- [ ] AC-13 - Modal renderiza `<img>` para `mime_type=image/*` e `<iframe>` para `application/pdf`.
- [ ] AC-14 - Quando `comprovante_disponivel=false`, botão "Visualizar comprovante" fica desabilitado com tooltip apropriado.
- [ ] AC-15 - Metadados extraídos mostram "Não extraído" para campos null.
- [ ] AC-16 - Checagens automáticas listam todas as checagens com chip `pass`/`fail` e motivo curto quando falha; renderizam mesmo em Pix decidido.
- [ ] AC-17 - `Validar Pix` aparece apenas em Pix `Em revisão` e é o `button-primary` do detalhe.
- [ ] AC-18 - `Rejeitar Pix` aparece apenas em Pix `Em revisão`, em `button-danger`.
- [ ] AC-19 - `Reabrir Pix` aparece apenas em Pix `Rejeitado`, em `button-secondary`.
- [ ] AC-20 - Pix `Validado automaticamente` e `Validado por Fernando` ficam read-only; nenhuma das três ações de decisão aparece.
- [ ] AC-21 - AlertDialog de validar deixa explícito o handoff implícito (card no grupo, IA pausada por modelo_em_atendimento, atendimento → Confirmado).
- [ ] AC-22 - AlertDialog de rejeitar exige `motivo` (enum); `motivo='outro'` exige `observacao`.
- [ ] AC-23 - Aprovação manual chama `POST /api/pix/{id}/aprovar`; sucesso mostra toast `Pix de {valor} validado`.
- [ ] AC-24 - Rejeição chama `POST /api/pix/{id}/rejeitar`; sucesso mostra toast `Pix rejeitado`.
- [ ] AC-25 - Reabertura chama `POST /api/pix/{id}/reabrir`; sucesso mostra toast `Pix reaberto para revisão`.
- [ ] AC-26 - Erro 409 mantém AlertDialog aberto e mostra toast com `detail`.
- [ ] AC-27 - Atendimento vinculado mostra badge de estado, `#N`, próxima ação esperada e botão "Abrir na Central".
- [ ] AC-28 - Linha do tempo lista eventos em `created_at DESC` com ícones canônicos.
- [ ] AC-29 - Insert/update em `comprovantes_pix` ou `atendimentos` no banco dispara refetch debounced.
- [ ] AC-30 - Telefone aparece formatado (fundação §10.1) e sem mascaramento.

---

## 16. Checklist de implementação

### 16.1 Pré-requisitos da tela

- [ ] CL-1 - Endpoint `GET /api/pix` retorna o JSON de §12.1.
- [ ] CL-2 - Endpoint `GET /api/pix/{id}` retorna o JSON de §12.2 incluindo `cliente`, `atendimento`, `checagens` e `eventos`.
- [ ] CL-3 - Endpoint `GET /api/pix/{id}/comprovante-url` retorna URL assinada do MinIO.
- [ ] CL-4 - Endpoints `POST /api/pix/{id}/aprovar`, `POST /api/pix/{id}/rejeitar`, `POST /api/pix/{id}/reabrir` existem.
- [ ] CL-5 - Aprovação manual no backend executa o handoff implícito (card "saída confirmada" + ia_pausada + atendimento → Confirmado).
- [ ] CL-6 - Rejeição no backend dispara mensagem padronizada ao cliente conforme `motivo`.
- [ ] CL-7 - Reabertura no backend reverte `decisao_final` para `null` mantendo `decisao_pipeline='em_revisao'`, sem afetar atendimento.
- [ ] CL-8 - Tabelas `comprovantes_pix` e `atendimentos` na publicação `supabase_realtime`.

### 16.2 Estrutura

- [ ] CL-9 - Criar `interface/src/app/(interface)/pix/page.tsx` (`"use client"`).
- [ ] CL-10 - Criar `interface/src/hooks/usePix.ts` (fetch lista + detalhe + comprovante-url + Realtime + debounced refetch).
- [ ] CL-11 - Criar `interface/src/tipos/pix.ts` com os tipos de §11.
- [ ] CL-12 - Criar componentes em `interface/src/components/pix/`.
- [ ] CL-13 - Instalar `dialog` via `pnpm dlx shadcn@latest add dialog` se ainda não existir.

### 16.3 Implementação

- [ ] CL-14 - Toolbar de busca + filtros (status, modelo, motivo de revisão, período).
- [ ] CL-15 - Lista com seleção automática do primeiro item e ordenação dinâmica conforme filtro de status.
- [ ] CL-16 - Header do detalhe.
- [ ] CL-17 - Bloco Ações com Validar/Rejeitar/Reabrir contextuais.
- [ ] CL-18 - Bloco Comprovante com chip + botão `Visualizar comprovante`.
- [ ] CL-19 - `DialogVisualizarComprovante` com `<img>`/`<iframe>` e fallback para nova aba.
- [ ] CL-20 - Bloco Metadados extraídos.
- [ ] CL-21 - Bloco Checagens automáticas com pass/fail + motivo.
- [ ] CL-22 - Bloco Atendimento vinculado com "Abrir na Central".
- [ ] CL-23 - Linha do tempo de eventos.
- [ ] CL-24 - AlertDialogs de Validar, Rejeitar e Reabrir.
- [ ] CL-25 - Empty states (lista padrão e com filtros).
- [ ] CL-26 - Realtime + refetch debounced.

### 16.4 Verificação

- [ ] CL-27 - `pnpm lint` passa.
- [ ] CL-28 - `pnpm build` passa.
- [ ] CL-29 - `pnpm dev` sobe e `/pix` carrega sem erro de console.
- [ ] CL-30 - Validar fluxo completo de aprovação manual: confirmar → atendimento vai para `Confirmado`, IA pausa por `modelo_em_atendimento`, card "saída confirmada" aparece no grupo de teste.
- [ ] CL-31 - Validar fluxo de rejeição: confirmar → cliente recebe mensagem padrão correspondente ao motivo; atendimento permanece no estado anterior.
- [ ] CL-32 - Validar fluxo de reabertura: Pix volta para "Pendentes" sem alterar atendimento.
- [ ] CL-33 - Validar Realtime inserindo um `comprovantes_pix` com `decisao_pipeline='em_revisao'` via Supabase Studio.
- [ ] CL-34 - Validar visualização do comprovante (imagem e PDF), incluindo URL expirada (retry).

---

## 17. Vetos locais e pontos imutáveis da tela

### 17.1 Vetos locais

Nenhum veto local. A regra de um único `button-primary` é preservada por prioridade contextual no detalhe (`Validar Pix` aparece como primary apenas quando o Pix está em revisão; quando read-only, a tela não tem nenhum primary).

### 17.2 Pontos imutáveis específicos

- ❌ Não editar metadados do OCR nesta tela; correção exige novo comprovante do cliente.
- ❌ Não permitir reabrir Pix `Validado por Fernando` no P0 (decisão imutável).
- ❌ Não permitir reabrir Pix `Validado automaticamente` no P0.
- ❌ Não fechar/perder atendimento nesta tela.
- ❌ Não cancelar bloqueio de agenda nesta tela.
- ❌ Não redigir manualmente a mensagem ao cliente — o backend é dono do mapa motivo→mensagem.
- ❌ Não exibir `observacao` da rejeição ao cliente; ela é interna (registrada no evento).
- ❌ Não fazer preview automático de comprovante (fundação §9.8).
- ❌ Não cachear URL assinada em `localStorage` (fundação §12).
- ❌ Não criar deep link `/pix/{id}` no P0 sem spec própria.

---

## 18. Pontos em aberto

Nenhum ponto em aberto após alinhamento com o usuário em 2026-05-01.

---

## Anexo A - Wireframe textual

```text
┌─────────────────┬──────────────────────────────────────────────────────────────┐
│ Sidebar         │ Pix de deslocamento                                          │
│ compartilhada   │ Decisão humana sobre Pix duvidosos e auditoria de Pix        │
│                 │ aprovados automaticamente.                                   │
│                 │                                                              │
│                 │ [Buscar valor, cliente, telefone ou #N]                      │
│                 │ [Pendentes v] [Modelo v] [Motivo v] [Período v]              │
│                 │                                                              │
│                 │ ┌──────────────────────────────┐ ┌─────────────────────────┐ │
│                 │ │ [Em revisão]      há 12 min  │ │ Carlos M.   [Em revisão]│ │
│                 │ │ R$ 195,00                    │ │ Conversa com Júlia      │ │
│                 │ │ Carlos · Júlia · #142        │ │ Recebido há 12 min      │ │
│                 │ │ valor_divergente             │ │                         │ │
│                 │ ├──────────────────────────────┤ │ [Validar Pix]           │ │
│                 │ │ [Em revisão]      há 28 min  │ │ [Rejeitar Pix]          │ │
│                 │ │ R$ 220,00                    │ │ [Abrir atendimento]     │ │
│                 │ │ Bruno · Júlia · #141         │ │                         │ │
│                 │ │ ocr_falhou                   │ │ COMPROVANTE             │ │
│                 │ ├──────────────────────────────┤ │ 📎 comprovante.jpg ·    │ │
│                 │ │ [Validado auto] há 1 h       │ │     412 KB              │ │
│                 │ │ R$ 200,00                    │ │ [👁 Visualizar]         │ │
│                 │ │ Jorge · Júlia · #140         │ │                         │ │
│                 │ └──────────────────────────────┘ │ Metadados extraídos     │ │
│                 │ [Carregar mais]                  │ Valor       R$ 195,00   │ │
│                 │                                  │ Hora        01 mai 17:30│ │
│                 │                                  │ Remetente   Carlos M.   │ │
│                 │                                  │ Chave       cpf 123...  │ │
│                 │                                  │ Hash        a3f9b2c1... │ │
│                 │                                  │                         │ │
│                 │                                  │ Checagens automáticas   │ │
│                 │                                  │ ✓ Janela temporal       │ │
│                 │                                  │ ✓ Conta destino         │ │
│                 │                                  │ ✓ Duplicidade           │ │
│                 │                                  │ ✗ Valor esperado        │ │
│                 │                                  │   esperado R$ 200,00,   │ │
│                 │                                  │   recebido R$ 195,00    │ │
│                 │                                  │                         │ │
│                 │                                  │ Atendimento vinculado   │ │
│                 │                                  │ ┃[Aguardando_conf.] #142│ │
│                 │                                  │ ┃externo · imediato     │ │
│                 │                                  │ ┃[Abrir na Central]     │ │
│                 │                                  │                         │ │
│                 │                                  │ Linha do tempo          │ │
│                 │                                  │ ⚠ pipeline_em_revisao   │ │
│                 │                                  │   há 12 min · sistema   │ │
│                 │                                  │ 📥 comprovante_recebido │ │
│                 │                                  │   há 12 min · webhook   │ │
│                 │                                  └─────────────────────────┘ │
└─────────────────┴──────────────────────────────────────────────────────────────┘
```

— FIM —
