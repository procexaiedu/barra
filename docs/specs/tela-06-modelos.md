# Tela 06 — Modelos

> **Herda decisões de** `docs/specs/00-fundacao-frontend.md`. Em conflito, a fundação vence salvo veto local declarado em §17. Não repetir aqui o que está na fundação.

---

## 1. Identificação

| Campo | Valor |
|---|---|
| Nome | Modelos |
| Slug | `modelos` |
| Rota | `/modelos` (split lista|detalhe; deep link `?modelo={id}&aba={aba}`) |
| Arquivo Next.js | `interface/src/app/(interface)/modelos/page.tsx` |
| Tipo | Client Component (`"use client"`) — Realtime exige client |
| Hook próprio | `interface/src/hooks/useModelos.ts` |
| Tipos | `interface/src/tipos/modelos.ts` |
| Componentes próprios | `interface/src/components/modelos/{HeaderModelos,ToolbarModelos,ListaModelos,ItemModelo,DetalheModelo,AbasModelo,AbaPerfil,AbaPrompt,AbaFaq,AbaMidia,AbaCoordenacao,FotoPerfil,DialogCriarModelo,DialogConectarWhatsapp,DialogFaq,DialogMidiaUpload,GridMidia,ItemMidia,DialogVisualizarMidia,PreviewPrompt}.tsx` |

---

## 2. Objetivo

Centralizar o cadastro e a operação das modelos da agência: perfil comercial, configuração da **IA por modelo** (campos estruturados interpolados no template de persona + FAQ + mídia aprovada), pareamento com a Evolution (número de WhatsApp da modelo), vínculo com a **Coordenação por modelo** (grupo de 2 participantes), e pausar/ativar a IA em escala. **Toda decisão que altera a IA da modelo passa por aqui** — qualquer outra tela apenas consome.

Citação literal de `docs/mvp/06-dados-interfaces.md` §4.5: *"Cadastro e dados operacionais da modelo piloto."*

---

## 3. Contexto funcional

- **Único usuário no P0:** Fernando. Modelos não acessam o painel (`docs/mvp/03-modulos-sistema.md` §4.5; reforçado pelo escopo grilling 29/04).
- **Unidade da tela:** registro em `modelos`. Cada modelo agrega `modelo_faq` (FAQ) e `modelo_midia` (mídia aprovada) e referencia uma instância Evolution + um grupo de **Coordenação por modelo**.
- **Modelo é entidade transversal:** filtra Atendimentos, Agenda e CRM; alimenta o snapshot `percentual_repasse_snapshot` no fechamento; configura a IA que conduz toda Conversa cliente; define o grupo de Coordenação por modelo.
- **Persona da IA é template versionado no repositório** (`api/src/barra/agente/prompts/persona.md`); o painel **não edita texto livre de persona** — só os campos estruturados interpolados (`docs/mvp/06-dados-interfaces.md` §2.1).
- **Origem dos dados:** endpoints REST de modelos (§12).
- **Realtime:** assinatura em `modelos`, `modelo_faq`, `modelo_midia` (§13). **Não** assinar `atendimentos` aqui — indicadores rápidos vêm agregados pelo `GET /api/modelos`.
- **Escrita inline permitida:** criar modelo, editar perfil, editar campos estruturados do prompt, CRUD de FAQ e Mídia, parear/desparear Evolution, vincular/verificar grupo de Coordenação, pausar/ativar modelo, upload de foto de perfil.
- **Fora do escopo desta tela:** abrir/fechar atendimento, validar Pix, mesclar clientes, editar persona livre, alterar histórico de mensagens, importar base antiga (`docs/mvp/02-mvp-escopo.md` §3.2).

### 3.1 Efeitos colaterais que a tela apenas dispara (backend executa)

- **Pausar modelo (`status='ativa'` → `'pausada'`)** = backend pausa a IA em **todas as conversas com `ia_pausada=false`** dessa modelo, motivo `modelo_em_atendimento` (vocabulário fechado do `CONTEXT.md` — não inventar `modelo_pausada`), e envia card "modelo pausada operacionalmente" no grupo de **Coordenação por modelo**. Atendimentos em `Em_execucao` permanecem; nenhum dado é descartado.
- **Reativar modelo (`status='pausada'` → `'ativa'`)** = backend apenas muda o status. **A IA não é devolvida automaticamente** nas conversas que ficaram pausadas pela operação anterior — devolução é por conversa, manual, na Central de Atendimentos. A tela apresenta atalho para `/atendimentos?ia_pausada=true&modelo={id}` quando há pausas pendentes.
- **Trocar `numero_whatsapp` ou desparear Evolution** = backend reseta `evolution_instance_id` para `NULL`. Workers (`envio.py`) bloqueiam novos envios da IA enquanto `evolution_instance_id IS NULL`. Tela apresenta CTA primary "Conectar WhatsApp" no header da modelo.
- **Conectar/repararar Evolution** = `POST /api/modelos/{id}/conectar-whatsapp` retorna QR code. Modal exibe o QR; após o pareamento, refetch confirma `evolution_instance_id` preenchido.
- **Editar campos estruturados do prompt** (idade, idiomas, localização, tipos aceitos) = afeta o **próximo turno da IA** em qualquer Conversa cliente. Não reescreve histórico nem reabre conversas pausadas.
- **Editar `percentual_repasse`** = afeta **apenas fechamentos futuros** (`atendimentos.percentual_repasse_snapshot` é gravado no momento do `fechado valor`). Atendimentos já fechados mantêm o snapshot anterior.

---

## 4. Fluxo do usuário

### 4.1 Caminho feliz

1. Fernando acessa `/modelos`. Middleware (fundação §6.1) garante autenticação.
2. Tela monta com skeleton da lista (esquerda) e do detalhe (direita).
3. `useModelos` chama `GET /api/modelos` (lista com indicadores) — em paralelo, abre 3 subscriptions Realtime (§13) e registra listener `onAuthStateChange`.
4. Lista chega → seleciona automaticamente a primeira modelo `ativa` por `created_at ASC` (no P0 = piloto). Se não houver `ativa`, seleciona a primeira por `created_at ASC`.
5. A seleção dispara `GET /api/modelos/{id}` e `GET /api/modelos/{id}/prompt-preview` em paralelo.
6. Detalhe abre na aba `Perfil` por padrão (ou na aba do query string `?aba=`).
7. Fernando edita campos do perfil → cada bloco tem seu próprio "Salvar" contextual (sem autosave).
8. Fernando navega entre as 5 abas (`Perfil`, `Prompt`, `FAQ`, `Mídia`, `Coordenação`) sem perder seleção.
9. Ações destrutivas (pausar modelo, desparear Evolution, trocar número, deletar FAQ/mídia) abrem `<AlertDialog>`.

### 4.2 Caminhos alternativos específicos

| Cenário | Comportamento |
|---|---|
| Lista vazia | Empty state §5.4.2 com CTA `button-primary` "Adicionar modelo". |
| Modelo selecionada sai do filtro após Realtime | Mantém detalhe visível até refetch concluir; depois seleciona a primeira da nova lista. Lista vazia → painel de detalhe com empty state. |
| Modelo sem `evolution_instance_id` | Header da modelo destaca chip `Evolution: não pareada` (warn) e a aba `Perfil` apresenta CTA primary "Conectar WhatsApp". |
| Modelo sem `coordenacao_chat_id` | Aba `Coordenação` mostra CTA `button-secondary` "Vincular grupo" e banner explicativo. Pausar modelo nesse estado emite warning no AlertDialog ("Card de pausa não será enviado — grupo não vinculado"). |
| Edição com erro de rede/servidor | Inputs/textareas dirty permanecem com o valor digitado; toast de erro; nenhum dado local é descartado. |
| QR code da Evolution expira durante pareamento | Modal mostra `<BannerErro/>` com retry; botão refaz `POST /api/modelos/{id}/conectar-whatsapp`. |
| Trocar `numero_whatsapp` em modelo já pareada | AlertDialog "Trocar número exige novo pareamento da Evolution. Continuar?" → backend reseta `evolution_instance_id`; modelo entra em estado "não pareada"; bloqueio de envios da IA até reconexão. |
| Pausar modelo com atendimentos `Em_execucao` | AlertDialog específico (§6.4) mostra contagem de `Em_execucao` em curso; confirmar pausa não interrompe esses atendimentos. |
| Reativar modelo com conversas previamente pausadas pela operação | Toast `Modelo reativada` + atalho ghost "Devolver IA em N conversa(s) pausada(s) →" navega para `/atendimentos?ia_pausada=true&modelo={id}`. |

> Cenários de auth, 401, mobile, erro de rede, refresh JWT são tratados pela fundação (§§6, 7, 5.3, 9.2).

---

## 5. Layout detalhado dos blocos próprios

> Sidebar e shell de 2 colunas vêm da fundação §5. Esta seção descreve apenas o conteúdo do `<main>` da rota `/modelos`.

Estrutura dentro do `<main>`:

```
[Cabeçalho da página]
[Toolbar de filtros e busca]
[Split 360px lista | detalhe flexível com abas]
```

### 5.1 Cabeçalho da página

- Container: `padding: spacing.6 spacing.6 spacing.4`; flex row, `justify-content: space-between; align-items: center`.
- **Esquerda:** título "Modelos" em **Cormorant Garamond `display-lg`** (40px, peso 500, `--text-primary`).
- **Direita:** botão **`button-primary` "Adicionar modelo"** com ícone `UserPlus` 16px à esquerda. Único `button-primary` global da tela quando o detalhe não exibe ação primary contextual (ver §17 veto local sobre exclusividade).

### 5.2 Toolbar de filtros e busca

- Linha horizontal com busca e filtros.
- Busca por nome, número de WhatsApp ou bairro/região.
- Controles:

| Controle | Tipo | Opções |
|---|---|---|
| Busca | input | placeholder "Buscar nome, número ou bairro" |
| Status | select | `Todos`, `Ativa`, `Pausada`, `Inativa` |
| Evolution | select | `Todos`, `Pareada`, `Não pareada` |
| Tipo de atendimento | select | `Todos`, `Aceita interno`, `Aceita externo` |

- Busca com debounce 300ms.
- Mudança de filtro reseta paginação/cursor e cancela seleção anterior; tela seleciona a primeira modelo do novo resultado.
- Sem botão "Limpar filtros" no MVP — voltar cada select para `Todos` faz o papel.

### 5.3 Split lista/detalhe

- Grid de duas colunas:
  - Lista: largura fixa 360px.
  - Detalhe: ocupa o restante.
- Gap `spacing.5`.
- Altura mínima: `calc(100vh - shell/header)`, sem esconder conteúdo essencial.

### 5.4 Lista de modelos

- Container `<section aria-label="Lista de modelos">`.
- Lista vertical de cards compactos, sem card dentro de card.
- Ordenação: `status='ativa' ASC` (ativas no topo), depois `created_at ASC`.
- Paginação: cursor simples com botão ghost "Carregar mais" no fim. No P0 (1 piloto), nunca aparece.

#### 5.4.1 Item da lista

Conteúdo:

```
[Badge status] [Chip Evolution]
Nome (heading-md --text-primary)
(21) 98765-4321 (mono-sm --text-muted)
N abertos · M IA pausada · último handoff há X
```

- Card clicável com `role="button"` e `aria-pressed` quando selecionado.
- Selecionado: borda esquerda `3px solid var(--gold-500)`.
- Modelo `ativa` **não selecionada**: sem borda lateral.
- Modelo `pausada` **não selecionada**: borda esquerda `3px solid var(--ink-400)` (neutra).
- Modelo `inativa` **não selecionada**: opacidade 0.6, sem borda lateral.
- Modelo com `evolution_instance_id IS NULL`: chip `Evolution: não pareada` em warn; quando pareada, chip `Evolution: pareada` em `--text-muted` (informativo, não enfático).
- Telefone usa `formatTelefone` da fundação (sem mascaramento).
- Indicadores rápidos (linha de baixo):
  - `N abertos` = `atendimentos abertos` daquela modelo (`estado NOT IN ('Fechado','Perdido')`).
  - `M IA pausada` = quantas conversas dessa modelo têm atendimento aberto com `ia_pausada=true`.
  - `último handoff há X` = `formatTempoRelativo(MAX(escaladas.created_at))` por modelo, ou "sem handoff" quando nunca houve.

#### 5.4.2 Mapeamento badge por status

| `status` | Variante | Label |
|---|---|---|
| `ativa` | `active` | "Ativa" |
| `pausada` | `paused` | "Pausada" |
| `inativa` | `lost` | "Inativa" |

> `inativa` usa variante `lost` (vermelho) por ser estado terminal de fato (modelo desligada da operação) — vocabulário do enum, não decisão da tela.

#### 5.4.3 Empty state da lista

Sem filtros:

```
Nenhuma modelo cadastrada.
Adicione a primeira modelo para começar a operar.
[ button-primary "Adicionar modelo" ]
```

- Ícone `Users --text-muted` 20px à esquerda da primeira linha.
- Texto principal: `body-md --text-primary`. Auxiliar: `body-sm --text-muted`.
- CTA reusa o mesmo dialog de §6.1.

Com filtros:

```
Nenhuma modelo encontrada para estes filtros.
Ajuste status, Evolution ou tipo de atendimento.
```

### 5.5 Detalhe da modelo

Container `<section aria-label="Detalhe da modelo">`.

Estrutura:

```
[Header da modelo]
[Abas: Perfil | Prompt | FAQ | Mídia | Coordenação]
[Conteúdo da aba ativa]
```

### 5.6 Header da modelo

Mostra:

- Foto de perfil circular 56px à esquerda (`<FotoPerfil/>` — render-only; upload/troca via aba Perfil).
- Nome em `heading-lg --text-primary`.
- Linha 2: badge status + chip Evolution + chip Coordenação (`Coordenação: vinculada`/`Coordenação: não vinculada`) + nome da modelo (visualmente: "Júlia · 28 · pt-BR · Copacabana").
- À direita: ações contextuais conforme estado:

| Estado | Ação visível | Variante |
|---|---|---|
| `evolution_instance_id IS NULL` | `Conectar WhatsApp` | `primary` |
| `status='ativa'` E Evolution pareada | `Pausar modelo` | `secondary` |
| `status='pausada'` | `Reativar modelo` | `primary` |
| `status='inativa'` | (sem ação primária; só edição via aba Perfil) | — |

- Regra de primary: **no máximo 1 visível no detalhe**. Quando o header expõe primary contextual (ex.: "Conectar WhatsApp"), o `button-primary` global "Adicionar modelo" do cabeçalho da página continua presente — exceção declarada em §17 (veto local).

### 5.7 Abas

Componente `<AbasModelo/>` (shadcn `Tabs`):

| Aba | Slug em URL (`?aba=`) | Conteúdo |
|---|---|---|
| Perfil | `perfil` (default) | §5.8 |
| Prompt | `prompt` | §5.9 |
| FAQ | `faq` | §5.10 |
| Mídia | `midia` | §5.11 |
| Coordenação | `coordenacao` | §5.12 |

- Mudança de aba atualiza URL via `router.replace('/modelos?modelo={id}&aba={slug}', { scroll: false })`.
- Aba ativa: bg `--ink-200`, label e ícone em `--gold-500`. Inativa: `--text-secondary` em hover `--ink-200`.
- Trocar de aba com edição dirty pendente em algum bloco: AlertDialog "Descartar alterações não salvas?" (mesmo padrão da Tela 04 §7.3).

### 5.8 Aba Perfil

Conjunto de cards verticais. Cada card tem seu próprio "Salvar" `button-secondary` contextual habilitado quando dirty (sem autosave).

#### 5.8.1 Card "Identidade"

| Campo | Tipo input | Regra |
|---|---|---|
| Foto de perfil | upload via botão "Alterar foto" abre `DialogMidiaUpload` em modo "perfil" (renderiza preview no card). Botão `button-ghost` "Remover foto" quando há foto. | Imagem aceita: `image/jpeg`, `image/png`, `image/webp`. Tamanho máximo 5 MB. |
| Nome | input texto | obrigatório, ≤ 100 caracteres |
| Idade | input number | obrigatório, > 0 |
| Status | select | `Ativa`, `Pausada`, `Inativa`. **Mudar via select aqui é proibido**; a transição passa pelas ações do header (§5.6) que disparam dialogs específicos. Select fica `disabled` e mostra tooltip "Use os botões do cabeçalho para alterar status." |

#### 5.8.2 Card "WhatsApp e Evolution"

| Campo | Comportamento |
|---|---|
| Número de WhatsApp | input texto, format E.164 (`+5521987654321`). Editar e salvar com mudança de número abre `<AlertDialog>` (§6.5) para confirmar reset do pareamento. |
| Status Evolution | linha read-only: chip `pareada`/`não pareada` + `evolution_instance_id` em mono-sm `--text-muted` + botão `button-secondary` "Reparear" quando pareada / `button-primary` "Conectar WhatsApp" quando não pareada (espelha o do header). |

#### 5.8.3 Card "Acordo financeiro"

| Campo | Tipo | Regra |
|---|---|---|
| Valor padrão (BRL/hora) | input numérico (vírgula brasileira) | obrigatório, ≥ 0 |
| Percentual de repasse (%) | input numérico | opcional (`docs/mvp/01-contexto-negocio.md` §1); 0–100 quando preenchido. Hint `body-sm --text-muted`: "Aplica-se apenas a fechamentos futuros (snapshot)." |
| Chave Pix | input texto | opcional |
| Titular da chave | input texto | opcional |

#### 5.8.4 Card "Operação"

| Campo | Tipo | Regra |
|---|---|---|
| Localização operacional | input texto | opcional; bairro/região (interpolado no prompt). |
| Idiomas | multi-select com chips | array de BCP-47; default `['pt-BR']`; mínimo 1. |
| Tipos de atendimento aceitos | checkbox group | `interno`, `externo`; mínimo 1. |

> **`idade`, `idiomas`, `localizacao_operacional`, `tipos_atendimento_aceito` aparecem aqui *e* na aba Prompt** (§5.9) porque são interpolados no template — ver veto local §17 sobre duplicação visual proposital.

### 5.9 Aba Prompt

#### 5.9.1 Card "Campos estruturados"

Mostra os campos do `Card Operação` (§5.8.4) + idade em **modo somente-leitura espelhado**, como referência. O input editável fica na aba Perfil. Banner topo: `body-sm --text-muted` "Persona e tom estão versionados em `api/src/barra/agente/prompts/persona.md` (Git). Aqui você edita os campos estruturados que o template interpola; mudanças vigem no próximo turno da IA."

#### 5.9.2 Card "Preview do prompt renderizado"

- Header `heading-md --text-primary` "Prompt da IA — preview".
- Sub-header `caption --text-muted`: "Renderização atual de `persona.md` com os campos da modelo. Atualiza ao salvar campos da aba Perfil."
- Container: `<pre>` `--ink-100` `rounded.md` `padding spacing.4`, fonte `--font-mono`, `font-size: 13px`, `white-space: pre-wrap`, altura máxima 480px com scroll vertical, `aria-label="Preview do prompt renderizado"`.
- Botão `button-ghost` "Copiar" no canto superior direito → `navigator.clipboard.writeText(...)` + toast `Prompt copiado`.
- Conteúdo vem de `GET /api/modelos/{id}/prompt-preview` (string única).
- **Sem diff entre versões; sem editor inline; sem rollback** (rollback de persona = `git revert` no repositório). Esta tela não versiona prompt no banco — decisão de `docs/mvp/06-dados-interfaces.md` §2.1.

### 5.10 Aba FAQ

#### 5.10.1 Toolbar interna

| Controle | Tipo | Opções |
|---|---|---|
| Busca | input | placeholder "Buscar pergunta, resposta ou tag" |
| Escopo | select | `Específicas` (default), `Globais`, `Todas` |

- `Específicas` filtra `WHERE modelo_id = {id}` (regras dessa modelo).
- `Globais` filtra `WHERE modelo_id IS NULL` (FAQ herdada de todas).
- `Todas` une os dois (com chip "global" no card).
- À direita: `button-primary` "Adicionar FAQ" (abre `DialogFaq` §6.7). Ao habilitar este primary, oculta o `button-primary` global do cabeçalho (§17 veto local).

#### 5.10.2 Lista de FAQs

Lista vertical de cards compactos:

```
[chip "global" se modelo_id IS NULL] [tags]
Pergunta (heading-sm --text-primary)
Resposta truncada 2 linhas (body-sm --text-muted)
[button-ghost "Editar"] [button-ghost "Excluir"]
```

- "Editar" abre `DialogFaq` (§6.7) preenchido.
- "Excluir" abre `<AlertDialog>` "Excluir FAQ?" (§6.8). FAQ global só pode ser editada/excluída quando `escopo='Globais'` está selecionado (proteção contra exclusão acidental enquanto Fernando está focado em uma modelo específica).
- Empty state: "Nenhuma FAQ cadastrada para esta modelo. Adicione regras específicas que a IA deve seguir."

### 5.11 Aba Mídia

#### 5.11.1 Toolbar interna

| Controle | Tipo | Opções |
|---|---|---|
| Tipo | select | `Todos`, `Foto`, `Vídeo` |
| Tag | select | `Todas` + lista de tags distintas (`apresentacao`, `corpo`, `lifestyle`, `evento` etc.) |
| Aprovação | select | `Aprovadas` (default), `Não aprovadas`, `Todas` |

- À direita: `button-primary` "Adicionar mídia" (abre `DialogMidiaUpload` §6.9). Mesma regra de oculta-primary-global de §5.10.1.

#### 5.11.2 Grade de mídia

`<section aria-label="Mídia aprovada da modelo">` em grid responsivo:

- 3 colunas em `lg`, 4 colunas em `xl`. Gap `spacing.4`.
- Cada `<ItemMidia/>`:
  - Container `--card --rounded.lg`, padding `spacing.3`.
  - Thumbnail 200×200px, `object-fit: cover`, `rounded.md`. Vídeo mostra ícone `Play` central + thumbnail do primeiro frame quando disponível; senão, ícone `Film` em `--text-muted`.
  - URL assinada do MinIO via `GET /api/modelos/{id}/midia` (já existente em backend, retorna `url_assinada`).
  - Overlay inferior com chips: `tipo` + `tag` + ícone `CheckCircle2 --success-500` quando `aprovada=true`.
  - Click no thumbnail abre `DialogVisualizarMidia` (§6.10).
  - Menu kebab (`MoreVertical`) abre dropdown: `Editar tag`, `Aprovar`/`Rejeitar`, `Excluir`.

#### 5.11.3 Empty state

```
Nenhuma mídia cadastrada para esta modelo.
Mínimo recomendado: 10 mídias aprovadas antes do piloto.
[ button-primary "Adicionar mídia" ]
```

> **Veto da fundação §❌** ("Não mostrar foto de modelo em sidebar, lista, hover…") **não se aplica aqui**: esta aba é a única superfície explicitamente autorizada do painel para renderizar mídia da modelo. Ver §17 veto local.

### 5.12 Aba Coordenação

#### 5.12.1 Card "Grupo de Coordenação por modelo"

Banner topo (`body-sm --text-muted`):

> Grupo de WhatsApp com **2 participantes**: o número desta modelo (operado pela IA) e Fernando. A IA envia cards/resumos acionáveis aqui a partir do número da modelo. (Vocabulário: ver `CONTEXT.md`.)

| Campo | Comportamento |
|---|---|
| JID do grupo | input texto, placeholder `5521xxxxxxxxx-1234567890@g.us`. Salva via botão `button-secondary` "Vincular grupo". Aceita string vazia (limpa o vínculo). |
| Status | linha read-only: chip `vinculada`/`não vinculada` + last check (`formatTempoRelativo` da última verificação, opcional). |
| Verificar grupo | botão `button-secondary` "Verificar grupo" — chama `POST /api/modelos/{id}/coordenacao/verificar` que pinga Evolution para confirmar que o grupo existe e tem exatamente Fernando + número da modelo. Resultado: toast `Grupo verificado` ou `error` com `detail`. |

- Quando `coordenacao_chat_id IS NULL`: card mostra estado vazio com hint operacional "Crie o grupo manualmente no WhatsApp (Fernando + número da modelo) e cole o JID acima. O JID está disponível na Evolution API em `/group/findGroupInfos`."
- **Sem CRUD de mensagens do grupo nesta tela** — visualização e auditoria de cards/escaladas pertencem ao backend e ao próprio WhatsApp.

#### 5.12.2 Card "Atalhos da modelo"

Lista de links operacionais que filtram outras telas pela modelo selecionada:

| Atalho | Texto | Destino |
|---|---|---|
| Atendimentos | "Ver N atendimentos abertos" (count vem do `GET /api/modelos/{id}`) | `/atendimentos?modelo_id={id}` (filtro pela URL — consumido pela toolbar da Tela 02) |
| IA pausada | "Devolver IA em M conversas pausadas" — só aparece quando M > 0 | `/atendimentos?ia_pausada=true&modelo_id={id}` |
| Agenda | "Abrir agenda da modelo" | `/agenda?modelo_id={id}` |
| CRM | "Abrir CRM filtrado por esta modelo" | `/crm?modelo_id={id}` |

- Cada atalho é `button-ghost` com ícone Lucide 16px à esquerda, label `body-md`, padding `spacing.3 spacing.5`, `rounded.md`.

---

## 6. AlertDialogs e Dialogs

### 6.1 `DialogCriarModelo`

Modal `<Dialog>` (não AlertDialog — operação reversível, sem confirmação destrutiva).

Campos obrigatórios mínimos (resto pode ser preenchido pós-criação na aba Perfil):

| Campo | Tipo | Regra |
|---|---|---|
| Nome | input texto | obrigatório, ≤ 100 caracteres |
| Idade | input number | obrigatório, > 0 |
| Número de WhatsApp | input texto E.164 | obrigatório |
| Valor padrão (BRL/hora) | input numérico | obrigatório, ≥ 0 |
| Idiomas | multi-select chips | mínimo 1; default `['pt-BR']` |
| Tipos de atendimento aceitos | checkbox group | mínimo 1 |

Endpoint: `POST /api/modelos`. Body conforme §12.2.

Sucesso → fecha dialog, lista refetch via Realtime, seleciona a modelo recém-criada, abre aba `Perfil`. Toast `Modelo {nome} criada`.

### 6.2 `DialogConectarWhatsapp`

Modal `<Dialog>` exibido após `POST /api/modelos/{id}/conectar-whatsapp`.

Conteúdo:

```
Conectar WhatsApp da modelo {nome}

[QR code 256×256 centralizado]

Aponte a câmera do WhatsApp da modelo para parear o número à instância
Evolution. O painel detecta a conexão automaticamente.

[ button-ghost "Fechar" ]   [ button-secondary "Atualizar QR" ]
```

- QR code em base64 vem do payload da Evolution.
- Polling: a tela já recebe `evolution_instance_id` confirmado via Realtime em `modelos`. Quando confirmar, modal fecha sozinho + toast `WhatsApp conectado`.
- Botão "Atualizar QR" refaz `POST /api/modelos/{id}/conectar-whatsapp`.
- Se Fernando fechar antes do pareamento, modelo permanece "não pareada".

### 6.3 `AlertDialog` "Reativar modelo"

Padrão da fundação §9.5.

```
Reativar {nome}?

A modelo volta para 'ativa'. Conversas que ficaram pausadas pela operação
anterior NÃO retomam automaticamente — devolva a IA conversa por conversa
na Central de Atendimentos.

[Cancelar] [Confirmar reativação]
```

Endpoint: `POST /api/modelos/{id}/ativar`. Body: `{}`. Toast: `Modelo {nome} reativada`.

### 6.4 `AlertDialog` "Pausar modelo"

```
Pausar {nome}?

A IA ficará pausada em N conversa(s) ativa(s) com motivo modelo_em_atendimento.
M atendimento(s) em Em_execucao não serão interrompidos.
Card de pausa será enviado no grupo de Coordenação por modelo.
{ aviso quando coordenacao_chat_id IS NULL: "Atenção: grupo não vinculado — card não será enviado." }

[Cancelar] [Confirmar pausa]
```

- N e M vêm do snapshot atual do detalhe (`GET /api/modelos/{id}` retorna esses contadores).
- Endpoint: `POST /api/modelos/{id}/pausar`. Body: `{}`.
- Toast: `Modelo {nome} pausada`.

### 6.5 `AlertDialog` "Trocar número de WhatsApp"

```
Trocar número de {nome}?

O pareamento atual com a Evolution será removido. Novos envios da IA ficam
bloqueados até o novo número ser pareado. Você precisará escanear um novo
QR code logo em seguida.

[Cancelar] [Confirmar troca]
```

- Confirmar dispara `PATCH /api/modelos/{id}` com novo `numero_whatsapp` + `evolution_instance_id=null` (backend reseta atomicamente).
- Após sucesso, abre automaticamente `DialogConectarWhatsapp` (§6.2).

### 6.6 `AlertDialog` "Desparear Evolution"

```
Desparear Evolution de {nome}?

Novos envios da IA ficam bloqueados até reconectar. Mensagens recebidas
pelo número continuam chegando se a instância Evolution permanecer ativa
no servidor.

[Cancelar] [Confirmar despareamento]
```

- Endpoint: `POST /api/modelos/{id}/desparear-whatsapp`. Body: `{}`.

### 6.7 `DialogFaq`

Modal `<Dialog>` (operação reversível).

| Campo | Tipo | Regra |
|---|---|---|
| Pergunta | textarea | obrigatório, ≤ 300 caracteres |
| Resposta | textarea | obrigatório, ≤ 2000 caracteres |
| Tags | input chips (entrada por Enter) | opcional |

Modo criação: `POST /api/modelos/{id}/faq`. Modo edição: `PATCH /api/modelos/{id}/faq/{faq_id}`. Toast: `FAQ adicionada` / `FAQ atualizada`.

### 6.8 `AlertDialog` "Excluir FAQ"

```
Excluir esta FAQ?

A IA não consultará mais esta resposta. Operação irreversível.

[Cancelar] [Confirmar exclusão]
```

Endpoint: `DELETE /api/modelos/{id}/faq/{faq_id}`. Toast: `FAQ excluída`.

### 6.9 `DialogMidiaUpload`

Modal `<Dialog>` para upload de mídia (e foto de perfil).

Fluxo (espelha o backend já existente):

1. Fernando seleciona arquivo (drag & drop ou file picker).
2. Front pede URL assinada PUT via `POST /api/modelos/{id}/midia/upload-url` com `{ filename, content_type }`.
3. Front faz `PUT` direto no MinIO com a URL assinada.
4. Front confirma o upload via `POST /api/modelos/{id}/midia` com `{ tipo, tag, object_key, aprovada }`.
5. Lista refetch via Realtime.

Campos:

| Campo | Tipo | Regra |
|---|---|---|
| Arquivo | file picker / drop zone | aceita `image/*`, `video/*`. Limite 50 MB. |
| Tipo | select | `foto`, `vídeo` (auto-derivado pelo `content_type`). |
| Tag | input texto | obrigatório, ≤ 50 caracteres. |
| Aprovada | checkbox | default `true`. |

- Modo "perfil" (chamado da §5.8.1): usa endpoint dedicado `POST /api/modelos/{id}/foto-perfil/upload-url` + `PATCH /api/modelos/{id}/foto-perfil`. Não cria registro em `modelo_midia`.
- Toast: `Mídia adicionada` / `Foto de perfil atualizada`.

### 6.10 `DialogVisualizarMidia`

Modal sem AlertDialog (sem confirmação destrutiva). Mesmo padrão da Tela 05 §6.4 (`DialogVisualizarComprovante`):

- Fundo do modal: `--ink-0`.
- `<img>` para imagens; `<video controls>` para vídeos.
- Botão `button-ghost` "Fechar" (`X` 16px) no canto superior direito.
- Link `button-ghost` "Abrir em nova aba" no rodapé do modal (URL assinada).
- Esc/click fora fecha.
- Sem download direto.

---

## 7. Comportamentos esperados

### 7.1 Inicialização

`useEffect` no mount:

1. Lê query string para `modelo` e `aba`.
2. `fetch` via `api('/modelos')` (lista com indicadores).
3. Seleciona modelo do `?modelo=` se válida; senão, primeira `ativa` por `created_at ASC`; senão, primeira da lista.
4. Para a modelo selecionada: `GET /api/modelos/{id}` + `GET /api/modelos/{id}/prompt-preview` em paralelo.
5. Abre subscriptions Realtime (§13).
6. Registra listener `onAuthStateChange` (fundação §6.3).

Cleanup no unmount: cancela subscriptions e listener.

### 7.2 Reconciliação Realtime

- Eventos em tabelas observadas disparam refetch debounced 250ms (lista + detalhe selecionado + prompt-preview quando a modelo selecionada muda).
- **Edição em curso protegida:** se algum bloco está dirty, refetch atualiza apenas blocos não-dirty. Após salvar com sucesso, refetch integral.
- Sem patch local; snapshot REST é fonte de reconciliação.

### 7.3 Mudança de aba

- Atualiza URL via `router.replace` (sem reload).
- Trocar de aba com edição dirty pendente: `<AlertDialog>` "Descartar alterações não salvas?" (`button-danger` "Descartar" / `button-ghost` "Cancelar"). Confirmar = descarta e troca.

### 7.4 Salvar campos da aba Perfil

```
[click "Salvar {bloco}"]
  → setSubmitting(true) → desabilita inputs do bloco + spinner inline no botão
    → PATCH /api/modelos/{id} com diff do bloco
      → 200 → toast "{bloco} atualizado", botão "Salvar" some (não está mais dirty)
      → 4xx → toast com {detail}, bloco permanece dirty e habilitado
      → 401 → fundação §6.4
      → 5xx → toast genérico, bloco permanece dirty
```

### 7.5 Pausar / Reativar modelo

- Header chama `POST /api/modelos/{id}/pausar` ou `POST /api/modelos/{id}/ativar`.
- Sucesso → toast + refetch via Realtime.
- Quando o resultado de `ativar` indica `conversas_pausadas_pendentes > 0`, toast inclui CTA "Devolver IA →" que navega para `/atendimentos?ia_pausada=true&modelo_id={id}`.

### 7.6 Conectar / Reparear / Desparear Evolution

- "Conectar" / "Reparear" → `POST /api/modelos/{id}/conectar-whatsapp` → abre `DialogConectarWhatsapp` (§6.2) com QR.
- "Desparear" → AlertDialog (§6.6) → `POST /api/modelos/{id}/desparear-whatsapp` → toast `Evolution desconectada`.

### 7.7 Vincular / Verificar Coordenação

- "Vincular grupo" → `PATCH /api/modelos/{id}` com `coordenacao_chat_id` → toast `Grupo vinculado`.
- "Verificar grupo" → `POST /api/modelos/{id}/coordenacao/verificar` → toast `Grupo verificado` ou `error` com `detail` (membros incorretos, grupo inexistente, instância offline).

### 7.8 Teclado / a11y

Ordem do Tab:
1. Sidebar (fundação).
2. Cabeçalho: botão "Adicionar modelo".
3. Toolbar de filtros.
4. Itens da lista.
5. Header da modelo: ações contextuais.
6. Tabs (com `role="tablist"`).
7. Conteúdo da aba ativa (na ordem visual dos blocos).

Roles:
- `<section aria-label="Lista de modelos">`.
- `<section aria-label="Detalhe da modelo">`.
- `<Tabs role="tablist">` com `role="tab"` em cada gatilho.
- `<dl>` para blocos read-only do header.
- Lista com itens focáveis por teclado (Enter/Space ativam).

---

## 8. Estados específicos da tela

> Padrões gerais de loading/erro/empty na fundação §9.

| Estado | Quando | Aparência |
|---|---|---|
| `loading-lista` | primeiro fetch | skeleton de toolbar + 4 itens-fantasma |
| `loading-detalhe` | primeiro fetch | skeleton de header + tabs + bloco da aba ativa |
| `loading-prompt-preview` | preview em fetch | skeleton 8 linhas no `<pre>` |
| `success-vazio-lista` | lista vazia (sem filtros) | empty state §5.4.3 |
| `success-vazio-filtros` | lista vazia (com filtros) | empty state §5.4.3 |
| `nao-pareada` | `evolution_instance_id IS NULL` | header destaca chip warn + CTA primary "Conectar WhatsApp" |
| `coordenacao-vazia` | `coordenacao_chat_id IS NULL` | aba Coordenação destaca card vazio + hint |
| `bloco-dirty` | input/textarea diferente do salvo | botão "Salvar" do bloco habilitado |
| `submitting` | request de escrita em vôo | inputs/botões do bloco/dialog desabilitados + spinner inline |
| `qr-aguardando-pareamento` | `DialogConectarWhatsapp` aberto sem confirmação | QR visível; refetch via Realtime fecha o modal automaticamente |

### 8.1 Skeletons específicos

- Lista: 4 linhas-fantasma de 96px.
- Detalhe header: 80px.
- Tabs: barra de 40px com 5 itens-fantasma.
- Aba Perfil: 4 cards-fantasma (Identidade, WhatsApp, Financeiro, Operação) com 4 inputs cada.
- Aba Prompt: 1 card de 240px (Campos) + 1 `<pre>` fantasma de 480px.
- Aba FAQ: 6 linhas-fantasma de 88px.
- Aba Mídia: grade 3×2 de cards 200×200px.
- Aba Coordenação: 2 cards-fantasma.

---

## 9. Regras de negócio

### 9.1 Lista e seleção

- Ordenação default: `status='ativa' ASC` (ativas no topo), depois `created_at ASC`.
- Filtros conforme §5.2 (status, Evolution, tipo de atendimento).
- Busca textual: prefixo case-insensitive em `modelos.nome`, `modelos.numero_whatsapp` (após normalização para dígitos), `modelos.localizacao_operacional`.
- Seleção inicial: `?modelo={id}` válido; senão primeira `ativa`; senão primeira da lista.

### 9.2 Cadastro

- `POST /api/modelos` exige campos mínimos do `DialogCriarModelo` (§6.1).
- `numero_whatsapp` único (constraint do schema).
- `tipo_atendimento_aceito` array não vazio (regra do MVP `06-dados-interfaces.md` §2.1).
- Após criar: novo registro entra em `status='ativa'` por default do banco; `evolution_instance_id IS NULL` (modelo cadastrada mas não pareada).

### 9.3 Edição de perfil

- `PATCH /api/modelos/{id}` aceita diff parcial.
- Mudança de `numero_whatsapp`: backend é responsável por **resetar `evolution_instance_id`** atomicamente. Front antecipa o efeito no AlertDialog (§6.5) e abre `DialogConectarWhatsapp` em seguida.
- `valor_padrao`, `percentual_repasse`, `chave_pix`, `titular_chave` afetam apenas fechamentos futuros.
- `idade`, `idiomas`, `localizacao_operacional`, `tipo_atendimento_aceito`: vigem no próximo turno da IA (sem reescrever histórico nem reabrir conversas).

### 9.4 Status: ativar / pausar / inativar

- **Pausar** (`POST /api/modelos/{id}/pausar`): backend executa transação:
  1. `UPDATE modelos SET status='pausada' WHERE id={id}`.
  2. Para cada conversa com atendimento aberto e `ia_pausada=false`: `UPDATE atendimentos SET ia_pausada=true, ia_pausada_motivo='modelo_em_atendimento', ia_pausada_em=now()` (vocabulário fechado do `CONTEXT.md`).
  3. Insert em `eventos` tipo `modelo_pausada` com `payload={ conversas_pausadas: N, em_execucao_em_curso: M }`.
  4. Quando `coordenacao_chat_id IS NOT NULL`: posta card "modelo pausada operacionalmente" no grupo via Evolution.
- **Reativar** (`POST /api/modelos/{id}/ativar`): backend executa:
  1. `UPDATE modelos SET status='ativa' WHERE id={id}`.
  2. Insert em `eventos` tipo `modelo_reativada`.
  3. **Não** altera `ia_pausada` em nenhuma conversa — devolução é por conversa, manual, na Central.
  4. Resposta inclui `conversas_pausadas_pendentes` (count de conversas com `ia_pausada=true` e motivo `modelo_em_atendimento` para essa modelo).
- **Inativar** (via `PATCH /api/modelos/{id}` com `status='inativa'`): bloqueado se `evolution_instance_id IS NOT NULL` (backend retorna 409 "Despareie a Evolution antes de inativar"). Inativa não dispara card no grupo.

### 9.5 Evolution e pareamento

- `POST /api/modelos/{id}/conectar-whatsapp`: cria/reusa `instance_id` na Evolution e retorna QR + status. Quando o WhatsApp da modelo escaneia, Evolution notifica o backend (webhook) e `evolution_instance_id` é confirmado em `modelos`.
- `POST /api/modelos/{id}/desparear-whatsapp`: `UPDATE modelos SET evolution_instance_id=NULL`. Backend pode adicionalmente desativar a instância na Evolution (decisão de infra, fora do escopo da tela).
- Workers (`api/src/barra/workers/envio.py`) **não** enviam mensagens da IA enquanto `evolution_instance_id IS NULL` (responsabilidade do worker; tela apenas reflete o estado).

### 9.6 Coordenação por modelo

- `coordenacao_chat_id` é o JID Evolution do grupo de **2 participantes** (`CONTEXT.md`). Validação no backend garante exatamente 2 membros: o `numero_whatsapp` da modelo + o número de Fernando.
- `POST /api/modelos/{id}/coordenacao/verificar` consulta Evolution; retorna `{ ok: true }` ou `{ ok: false, motivo: <texto> }` (membros incorretos, grupo inexistente, instância offline).
- Pausar modelo sem `coordenacao_chat_id` é permitido — só não envia o card; AlertDialog (§6.4) avisa.

### 9.7 FAQ

- `modelo_faq.modelo_id` nullable: `NULL` = FAQ global (herdada por todas), `id` preenchido = específica da modelo (`docs/mvp/06-dados-interfaces.md` §2.2).
- Esta tela edita FAQ específicas por padrão (`escopo='Específicas'`). FAQ globais aparecem com chip "global" e só são editáveis quando `escopo='Globais'` está selecionado (proteção operacional).
- Sem versionamento; deleção é hard-delete (já é o comportamento do backend atual).

### 9.8 Mídia

- `modelo_midia` em MinIO (bucket `media`, prefixo `modelos/{modelo_id}/midia/...`). Constraint do prefixo já validada em `routes.py:_validar_prefixo_midia` (linhas 302–311).
- Apenas mídia com `aprovada=true` é consumida pela IA.
- Mínimo recomendado: 10 mídias aprovadas antes do piloto (`docs/mvp/03-modulos-sistema.md` §4.5).
- Foto de perfil **não** é registrada em `modelo_midia` — vai em coluna dedicada `modelos.foto_perfil_object_key` (mesmo bucket, prefixo `modelos/{modelo_id}/perfil/...`).

### 9.9 Prompt preview

- `GET /api/modelos/{id}/prompt-preview` lê `api/src/barra/agente/prompts/persona.md` no servidor, interpola com os campos atuais de `modelos` e retorna a string final.
- Sem cache no front; refetch acompanha o do detalhe.
- Sem versão / diff / rollback no banco.

---

## 10. Validações

| Onde | Validação | Falha |
|---|---|---|
| Front | `nome` ≤ 100, `idade > 0`, `numero_whatsapp` E.164, `valor_padrao ≥ 0`, `percentual_repasse 0–100 ou null`, `idiomas` mín. 1, `tipo_atendimento_aceito` mín. 1 | Bloqueia "Salvar" do bloco / "Criar modelo" do dialog; mensagem inline. |
| Front | Foto de perfil: `image/jpeg|png|webp`, ≤ 5 MB | Bloqueia upload; toast `error`. |
| Front | Mídia: `image/*` ou `video/*`, ≤ 50 MB | Bloqueia upload; toast `error`. |
| Front | FAQ: `pergunta ≤ 300`, `resposta ≤ 2000` | Bloqueia salvar dialog. |
| Front | Não permitir trocar de aba/seleção com bloco dirty sem confirmar | `<AlertDialog>` "Descartar alterações não salvas?". |
| Front | Status do header desabilita ações inválidas (ex.: "Pausar" só visível com `status='ativa'` E Evolution pareada) | Botão simplesmente não renderiza. |
| Backend | `numero_whatsapp` único | 409 `{ detail: "Número já cadastrado" }`. |
| Backend | Modelo existe | 404 `{ detail: "Modelo não encontrada" }`. |
| Backend | Inativar com Evolution pareada | 409 `{ detail: "Despareie a Evolution antes de inativar" }`. |
| Backend | `coordenacao_chat_id` membros incorretos na verificação | 200 com `{ ok: false, motivo: ... }` (não é erro HTTP). |
| Backend | Usuário tem `papel='fernando'` | RLS + check; 403 toast genérico "Sem permissão". |

---

## 11. Dados — tipos próprios da tela

Arquivo: `interface/src/tipos/modelos.ts`.

```ts
export type StatusModelo = 'ativa' | 'pausada' | 'inativa';
export type TipoAtendimento = 'interno' | 'externo';
export type TipoMidia = 'foto' | 'video';
export type AbaModelo = 'perfil' | 'prompt' | 'faq' | 'midia' | 'coordenacao';

export interface ModeloIndicadores {
  atendimentos_abertos: number;
  conversas_ia_pausada: number;
  ultimo_handoff_em: string | null; // ISO 8601; null se nunca houve
}

export interface ModeloListaItem {
  id: string;
  nome: string;
  numero_whatsapp: string;
  status: StatusModelo;
  evolution_instance_id: string | null;
  coordenacao_chat_id: string | null;
  foto_perfil_url: string | null; // URL assinada do MinIO
  indicadores: ModeloIndicadores;
}

export interface ModelosListaResponse {
  items: ModeloListaItem[];
  next_cursor: string | null;
}

export interface ModeloDetalhe {
  id: string;
  nome: string;
  idade: number;
  numero_whatsapp: string;
  status: StatusModelo;
  evolution_instance_id: string | null;
  coordenacao_chat_id: string | null;
  coordenacao_verificada_em: string | null;
  valor_padrao: number;
  percentual_repasse: number | null;
  chave_pix: string | null;
  titular_chave: string | null;
  idiomas: string[];
  localizacao_operacional: string | null;
  tipo_atendimento_aceito: TipoAtendimento[];
  foto_perfil_object_key: string | null;
  foto_perfil_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface FaqItem {
  id: string;
  modelo_id: string | null; // null = global
  pergunta: string;
  resposta: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface MidiaItem {
  id: string;
  modelo_id: string;
  tipo: TipoMidia;
  tag: string;
  bucket: string;
  object_key: string;
  aprovada: boolean;
  url_assinada: string;
  created_at: string;
}

export interface ModeloDetalheResponse {
  modelo: ModeloDetalhe;
  faq: FaqItem[];
  midia: MidiaItem[];
  evolution_status: { instance_id: string | null };
  indicadores: ModeloIndicadores;
}

export interface PromptPreviewResponse {
  texto: string;
  gerado_em: string;
}

export interface CriarModeloInput {
  nome: string;
  idade: number;
  numero_whatsapp: string;
  valor_padrao: number;
  percentual_repasse?: number | null;
  chave_pix?: string | null;
  titular_chave?: string | null;
  idiomas: string[];
  localizacao_operacional?: string | null;
  tipo_atendimento_aceito: TipoAtendimento[];
}

export interface PatchModeloInput {
  nome?: string;
  idade?: number;
  numero_whatsapp?: string;
  valor_padrao?: number;
  percentual_repasse?: number | null;
  chave_pix?: string | null;
  titular_chave?: string | null;
  idiomas?: string[];
  localizacao_operacional?: string | null;
  tipo_atendimento_aceito?: TipoAtendimento[];
  status?: StatusModelo;
  coordenacao_chat_id?: string | null;
}

export interface ConectarWhatsappResponse {
  status: 'pending' | 'connected' | string;
  instance_id: string;
  qr_code: string | null; // base64 PNG
}

export interface VerificarCoordenacaoResponse {
  ok: boolean;
  motivo: string | null;
  membros: string[]; // JIDs encontrados, para auditoria visual
}

export interface PausarModeloResponse {
  modelo_id: string;
  status: 'pausada';
  conversas_pausadas: number;
  em_execucao_em_curso: number;
  card_enviado: boolean;
}

export interface AtivarModeloResponse {
  modelo_id: string;
  status: 'ativa';
  conversas_pausadas_pendentes: number;
}
```

> Tipos refletem o contrato esperado de `api/src/barra/dominio/modelos/schemas.py` em 2026-05-01, com extensões para os novos endpoints/campos descritos em §12 e §14.

---

## 12. Contrato de API

Prefixo conforme montagem do backend: `/api/modelos` (ou `/api/v1/modelos` se `api/src/barra/api/v1.py` aplicar versionamento).

### 12.1 `GET /api/modelos`

Query:

| Parâmetro | Tipo | Uso |
|---|---|---|
| `status` | string opcional | filtra `ativa`/`pausada`/`inativa` |
| `evolution` | string opcional | `pareada`/`nao_pareada` |
| `tipo` | string opcional | `interno`/`externo` (filtro por elemento do array) |
| `q` | string opcional | nome, número ou bairro |
| `limit` | number | default 50, máximo 100 |
| `cursor` | string opcional | cursor por `created_at` |

Resposta 200: ver `ModelosListaResponse` (§11). Backend agrega `indicadores` por subquery em `atendimentos` e `escaladas`.

### 12.2 `POST /api/modelos`

Já existente (`routes.py:31`). Body conforme `CriarModeloInput` (§11). 201 retorna `ModeloDetalhe`.

### 12.3 `GET /api/modelos/{id}`

Já existente (`routes.py:63`). **Estender** o payload atual para incluir `indicadores` (contadores) + `foto_perfil_url` + `coordenacao_chat_id` + `coordenacao_verificada_em`. Resposta: `ModeloDetalheResponse`.

### 12.4 `PATCH /api/modelos/{id}`

Já existente (`routes.py:86`). **Estender** para aceitar `coordenacao_chat_id` no body. Quando o body inclui `numero_whatsapp` diferente do atual, backend reseta `evolution_instance_id=null` na mesma transação.

### 12.5 `POST /api/modelos/{id}/conectar-whatsapp`

Já existente (`routes.py:110`). Body: `{ "confirmar_rotacao": false }`. 200: `ConectarWhatsappResponse`.

### 12.6 `POST /api/modelos/{id}/desparear-whatsapp` (NOVO)

Body: `{}`. 200: `{ "modelo_id": "...", "evolution_instance_id": null }`.

### 12.7 `POST /api/modelos/{id}/pausar` (NOVO)

Body: `{}`. 200: `PausarModeloResponse`. 409 quando já `pausada` ou `inativa`.

### 12.8 `POST /api/modelos/{id}/ativar` (NOVO)

Body: `{}`. 200: `AtivarModeloResponse`. 409 quando já `ativa` ou `inativa`.

### 12.9 `POST /api/modelos/{id}/coordenacao/verificar` (NOVO)

Body: `{}`. 200: `VerificarCoordenacaoResponse`. **`ok=false` não é erro HTTP** (front trata como informação).

### 12.10 `POST /api/modelos/{id}/foto-perfil/upload-url` (NOVO)

Body: `{ "filename": "...", "content_type": "image/jpeg" }`. 200: `{ "object_key": "...", "upload_url": "...", "expires_in": 900 }`. Espelha `routes.py:196`.

### 12.11 `PATCH /api/modelos/{id}/foto-perfil` (NOVO)

Body: `{ "object_key": "modelos/{id}/perfil/..." }`. 200: `ModeloDetalhe` atualizada (com `foto_perfil_url`).

### 12.12 `DELETE /api/modelos/{id}/foto-perfil` (NOVO)

204. Limpa `foto_perfil_object_key` e (opcionalmente) deleta o blob no MinIO.

### 12.13 `GET /api/modelos/{id}/prompt-preview` (NOVO)

200: `PromptPreviewResponse`. Backend lê `api/src/barra/agente/prompts/persona.md`, interpola com os campos atuais e retorna. **Sem cache no front.**

### 12.14 FAQ (já existentes em `routes.py:132–193`)

- `GET /api/modelos/{id}/faq`
- `POST /api/modelos/{id}/faq`
- `PATCH /api/modelos/{id}/faq/{faq_id}`
- `DELETE /api/modelos/{id}/faq/{faq_id}`

> A tela passa filtro de escopo (`?escopo=especificas|globais|todas`) que o backend aplica via `WHERE modelo_id = $1 OR modelo_id IS NULL` conforme valor.

### 12.15 Mídia (já existentes em `routes.py:196–279`)

- `POST /api/modelos/{id}/midia/upload-url`
- `POST /api/modelos/{id}/midia`
- `GET /api/modelos/{id}/midia`
- `PATCH /api/modelos/{id}/midia/{midia_id}`
- `DELETE /api/modelos/{id}/midia/{midia_id}`

> **Pré-requisito:** os endpoints novos (12.6–12.13) existem e foram testados em `api/` antes de codificar a tela. Endpoints existentes recebem as extensões descritas em 12.3–12.5.

---

## 13. Realtime — específico desta tela

### 13.1 Subscriptions

Tabelas observadas (helper fundação §8.2):

- `modelos` — status, número, evolution_instance_id, coordenacao_chat_id, foto_perfil_object_key, campos do perfil.
- `modelo_faq` — CRUD de FAQ específica e global.
- `modelo_midia` — CRUD de mídia.

```ts
const cleanup = subscribeTabelas(
  'modelos',
  ['modelos', 'modelo_faq', 'modelo_midia'],
  debouncedRefetch,
);
```

> **Não** subscrever `atendimentos` aqui — indicadores rápidos (`atendimentos_abertos`, `conversas_ia_pausada`, `ultimo_handoff_em`) são agregados pelo `GET /api/modelos`. As Telas 01, 02 e 04 já assinam `atendimentos`; ler o agregado periodicamente quando o usuário focar nesta tela é suficiente. Eventos de `escaladas` que poderiam afetar `ultimo_handoff_em` chegam indiretamente quando refetch dispara por mudança em `modelos` (ex.: `updated_at` propagado por trigger), ou quando o usuário troca de seleção. Veto local §17 declara essa simplificação.

### 13.2 Refetch e refresh JWT

Padrões de fundação §§6.3, 8.3, 8.4. Edição dirty preservada conforme §7.2.

---

## 14. Mudanças estruturais necessárias

### 14.1 Backend — schema

Nova migration `infra/sql/NNNN_modelos_painel.sql`:

| Mudança | Comando |
|---|---|
| Adicionar `foto_perfil_object_key` em `modelos` | `ALTER TABLE barravips.modelos ADD COLUMN foto_perfil_object_key text NULL;` |
| Adicionar `coordenacao_chat_id` em `modelos` | `ALTER TABLE barravips.modelos ADD COLUMN coordenacao_chat_id text NULL;` |
| Adicionar `coordenacao_verificada_em` em `modelos` | `ALTER TABLE barravips.modelos ADD COLUMN coordenacao_verificada_em timestamptz NULL;` |
| Confirmar `modelos`, `modelo_faq`, `modelo_midia` na publicação `supabase_realtime` | `ALTER PUBLICATION supabase_realtime ADD TABLE barravips.modelos, barravips.modelo_faq, barravips.modelo_midia;` (idempotente — só aplica o que falta) |

### 14.2 Backend — endpoints

| Antes | Depois | Ação |
|---|---|---|
| `GET /api/modelos` (lista crua atual `routes.py:25`) | Lista enriquecida com `indicadores`, `foto_perfil_url`, `coordenacao_chat_id` | Substituir |
| `GET /api/modelos/{id}` (já agrega faq/midia) | Adicionar `indicadores` + `foto_perfil_url` + campos novos | Estender |
| `PATCH /api/modelos/{id}` | Aceitar `coordenacao_chat_id`; resetar `evolution_instance_id` quando `numero_whatsapp` muda | Estender |
| n/a | `POST /api/modelos/{id}/desparear-whatsapp` | Criar |
| n/a | `POST /api/modelos/{id}/pausar` | Criar |
| n/a | `POST /api/modelos/{id}/ativar` | Criar |
| n/a | `POST /api/modelos/{id}/coordenacao/verificar` | Criar |
| n/a | `POST /api/modelos/{id}/foto-perfil/upload-url` | Criar |
| n/a | `PATCH /api/modelos/{id}/foto-perfil` | Criar |
| n/a | `DELETE /api/modelos/{id}/foto-perfil` | Criar |
| n/a | `GET /api/modelos/{id}/prompt-preview` | Criar |

### 14.3 Frontend

| Antes | Depois | Ação |
|---|---|---|
| `interface/src/app/(interface)/modelos/` ausente ou stub | rota real | criar `page.tsx` |
| n/a | hook próprio | criar `interface/src/hooks/useModelos.ts` |
| n/a | tipos próprios | criar `interface/src/tipos/modelos.ts` |
| n/a | componentes próprios | criar pasta `interface/src/components/modelos/` |
| shadcn `tabs`, `input`, `textarea`, `select`, `dialog`, `dropdown-menu`, `checkbox` ainda não instalados | adicionar | `pnpm dlx shadcn@latest add tabs input textarea select dialog dropdown-menu checkbox` |

### 14.4 Ajuste em outras telas

| Tela | Ajuste | Razão |
|---|---|---|
| Tela 01 — Painel Geral §5.5 (Atalho "Conectar WhatsApp") | Trocar destino `/modelos/{modelo_ativa.id}?aba=perfil` por `/modelos?modelo={modelo_ativa.id}&aba=perfil` | Esta tela usa split + deep link via query string; rota `/modelos/{id}` não existe. |

### 14.5 Navegações disparadas pela tela

| Trigger | Destino |
|---|---|
| Atalho "Atendimentos abertos" (aba Coordenação) | `/atendimentos?modelo_id={id}` |
| Atalho "Devolver IA em conversas pausadas" | `/atendimentos?ia_pausada=true&modelo_id={id}` |
| Atalho "Abrir agenda da modelo" | `/agenda?modelo_id={id}` |
| Atalho "Abrir CRM filtrado" | `/crm?modelo_id={id}` |
| CTA pós-reativação (toast) | `/atendimentos?ia_pausada=true&modelo_id={id}` |

---

## 15. Critérios de aceite específicos

> Critérios estruturais (lint, build, dev, mobile blocker, foco, dark, primary único, vocabulário, skeletons, 401, JWT refresh, Lighthouse) vêm da fundação §14. Aqui só os específicos da tela.

- [ ] AC-1 — `/modelos` carrega split lista 360px + detalhe, com aba `Perfil` ativa por default.
- [ ] AC-2 — Deep link `/modelos?modelo={id}&aba=faq` seleciona a modelo correta e abre na aba FAQ.
- [ ] AC-3 — Lista ordena ativas no topo (`status='ativa' ASC`, depois `created_at ASC`).
- [ ] AC-4 — Item da lista mostra badge status, chip Evolution, nome, número formatado e indicadores (`N abertos`, `M IA pausada`, `último handoff há X`).
- [ ] AC-5 — Botão "Adicionar modelo" no cabeçalho abre `DialogCriarModelo` com campos mínimos validados; sucesso seleciona a recém-criada e abre aba Perfil.
- [ ] AC-6 — Header da modelo mostra foto + status + chip Evolution + chip Coordenação + ação contextual (Conectar/Pausar/Reativar) conforme tabela §5.6.
- [ ] AC-7 — Aba Perfil tem 4 cards independentes com "Salvar" próprio; salvar um bloco não envia o diff dos outros.
- [ ] AC-8 — Mudar `numero_whatsapp` na aba Perfil dispara `<AlertDialog>` de troca de número (§6.5) e, ao confirmar, abre `DialogConectarWhatsapp` automaticamente.
- [ ] AC-9 — `Pausar modelo` abre AlertDialog (§6.4) com contagem real de conversas pausadas e atendimentos `Em_execucao` em curso; aviso adicional aparece quando `coordenacao_chat_id IS NULL`.
- [ ] AC-10 — `Reativar modelo` abre AlertDialog (§6.3) que deixa explícito que devolução é por conversa.
- [ ] AC-11 — Toast pós-reativação inclui CTA "Devolver IA →" quando `conversas_pausadas_pendentes > 0`.
- [ ] AC-12 — Aba Prompt mostra banner sobre persona versionada no Git e renderiza `<pre>` com o preview de `GET /api/modelos/{id}/prompt-preview`.
- [ ] AC-13 — Botão "Copiar" da aba Prompt copia o conteúdo via clipboard e mostra toast.
- [ ] AC-14 — Salvar campos da aba Perfil que afetam o prompt (idade, idiomas, localização, tipos aceitos) refaz o preview automaticamente.
- [ ] AC-15 — Aba FAQ filtra por escopo (`Específicas` default, `Globais`, `Todas`); FAQ global mostra chip "global".
- [ ] AC-16 — CRUD de FAQ funciona via `DialogFaq` (§6.7) e AlertDialog de exclusão (§6.8); validações de tamanho aplicadas.
- [ ] AC-17 — Aba Mídia mostra grade de thumbs com URL assinada do MinIO; click abre `DialogVisualizarMidia` em fundo `--ink-0`.
- [ ] AC-18 — Upload de mídia segue o fluxo de 4 passos (upload-url → PUT MinIO → POST midia); aprovação inicial é `true`.
- [ ] AC-19 — Veto da fundação §❌ ("não mostrar foto de modelo em sidebar/lista") continua respeitado: thumbs aparecem APENAS na aba Mídia desta tela.
- [ ] AC-20 — Foto de perfil aparece APENAS no header do detalhe da modelo (§5.6) e no card "Identidade" da aba Perfil (§5.8.1); upload usa `DialogMidiaUpload` em modo "perfil" e endpoint dedicado.
- [ ] AC-21 — Aba Coordenação permite vincular `coordenacao_chat_id` via input + botão "Vincular grupo".
- [ ] AC-22 — Botão "Verificar grupo" chama `POST /api/modelos/{id}/coordenacao/verificar` e mostra toast com `ok` ou `motivo`.
- [ ] AC-23 — Atalhos da aba Coordenação navegam para `/atendimentos`, `/agenda` e `/crm` com `modelo_id` na URL.
- [ ] AC-24 — Trocar de aba ou de seleção com bloco dirty exibe AlertDialog "Descartar alterações não salvas?".
- [ ] AC-25 — Refetch via Realtime preserva inputs/textareas dirty.
- [ ] AC-26 — Insert/update em `modelos`, `modelo_faq` ou `modelo_midia` no banco dispara refetch debounced 250ms.
- [ ] AC-27 — Modal `DialogConectarWhatsapp` fecha sozinho quando `evolution_instance_id` é confirmado via Realtime.
- [ ] AC-28 — Empty state da lista (sem filtros) tem CTA "Adicionar modelo" como `button-primary`.
- [ ] AC-29 — Tentar inativar modelo com Evolution pareada retorna 409 + toast com `detail`.
- [ ] AC-30 — Telefone aparece formatado (fundação §10.1) e sem mascaramento.

---

## 16. Checklist de implementação

> Setup compartilhado (fundação §13) executado uma vez no projeto.

### 16.1 Pré-requisitos da tela

- [ ] CL-1 — Migration `infra/sql/NNNN_modelos_painel.sql` aplicada (campos `foto_perfil_object_key`, `coordenacao_chat_id`, `coordenacao_verificada_em`).
- [ ] CL-2 — Tabelas `modelos`, `modelo_faq`, `modelo_midia` na publicação `supabase_realtime`.
- [ ] CL-3 — Endpoints novos (12.6–12.13) implementados e testados em `api/`.
- [ ] CL-4 — Endpoints existentes (12.1, 12.3, 12.4) estendidos conforme §14.2.
- [ ] CL-5 — `prompt-preview` lê `api/src/barra/agente/prompts/persona.md` e interpola com sucesso.
- [ ] CL-6 — Workers (`envio.py`) confirmadamente bloqueiam envios da IA quando `evolution_instance_id IS NULL`.
- [ ] CL-7 — Itens de fundação §13 prontos (deps, shadcn components, env, RLS).
- [ ] CL-8 — Atalho do Painel Geral atualizado para `/modelos?modelo={id}&aba=perfil` (§14.4).

### 16.2 Estrutura

- [ ] CL-9 — Criar `interface/src/app/(interface)/modelos/page.tsx` (`"use client"`).
- [ ] CL-10 — Criar `interface/src/hooks/useModelos.ts` (fetch + Realtime + debounced refetch + dirty preservation).
- [ ] CL-11 — Criar `interface/src/tipos/modelos.ts` com os tipos de §11.
- [ ] CL-12 — Criar componentes próprios em `interface/src/components/modelos/` (lista de §1).
- [ ] CL-13 — Instalar shadcn primitives faltantes via `pnpm dlx shadcn@latest add tabs input textarea select dialog dropdown-menu checkbox`.

### 16.3 Implementação

- [ ] CL-14 — Cabeçalho com "Adicionar modelo" + Toolbar de filtros.
- [ ] CL-15 — Lista com indicadores rápidos e seleção automática.
- [ ] CL-16 — Header da modelo (foto + chips + ação contextual).
- [ ] CL-17 — Tabs com URL sync e proteção de dirty.
- [ ] CL-18 — Aba Perfil (4 cards independentes com "Salvar" contextual).
- [ ] CL-19 — Aba Prompt (banner + preview + Copiar).
- [ ] CL-20 — Aba FAQ (toolbar interna + lista + DialogFaq + AlertDialog excluir).
- [ ] CL-21 — Aba Mídia (toolbar interna + grade + DialogMidiaUpload + DialogVisualizarMidia).
- [ ] CL-22 — Aba Coordenação (vincular/verificar + atalhos).
- [ ] CL-23 — DialogCriarModelo, DialogConectarWhatsapp, AlertDialogs (Pausar, Reativar, Trocar número, Desparear).
- [ ] CL-24 — Empty states e skeletons.
- [ ] CL-25 — Realtime + refetch debounced + dirty preservation.
- [ ] CL-26 — A11y (roles, ordem do Tab, focus rings).

### 16.4 Verificação

- [ ] CL-27 — `pnpm lint` passa.
- [ ] CL-28 — `pnpm build` passa.
- [ ] CL-29 — `pnpm dev` sobe e `/modelos` carrega sem erro de console.
- [ ] CL-30 — Validar fluxo completo de pareamento Evolution: Conectar → QR → escanear → confirmação automática via Realtime.
- [ ] CL-31 — Validar pausar com atendimento `Em_execucao` em curso (atendimento permanece, IA pausa nas demais conversas).
- [ ] CL-32 — Validar reativar e ver toast com CTA "Devolver IA →" navegando para Central com filtros.
- [ ] CL-33 — Validar troca de número (reset de `evolution_instance_id` + abertura automática do QR).
- [ ] CL-34 — Validar CRUD de FAQ específica e edição de FAQ global (com escopo correto).
- [ ] CL-35 — Validar upload de mídia (drag & drop + tag + aprovação) e foto de perfil.
- [ ] CL-36 — Validar visualização de mídia (imagem e vídeo) em modal `--ink-0`.
- [ ] CL-37 — Validar Realtime: insert/update em `modelos`, `modelo_faq`, `modelo_midia` via Supabase Studio dispara refetch sem perder dirty.
- [ ] CL-38 — Lighthouse acessibilidade ≥ 95 (EST-13 da fundação).

---

## 17. Vetos locais e pontos imutáveis da tela

### 17.1 Vetos locais declarados

- **Fundação §9.6** ("apenas 1 primary por tela"): nesta tela coexistem **dois primaries em situações específicas** — o `button-primary` global "Adicionar modelo" no cabeçalho da página e um `button-primary` contextual no header do detalhe ("Conectar WhatsApp" ou "Reativar modelo") ou nas abas FAQ/Mídia ("Adicionar FAQ"/"Adicionar mídia"). **Justificativa:** Modelos é simultaneamente lista (precisa de CTA de criação visível) e workspace de configuração (precisa de CTA contextual destacado para a ação principal do estado atual da modelo). Forçar um único primary distorceria sinal. Mitigamos com **prioridade visual hierárquica**: o primary global desaparece quando o detalhe expõe primary contextual de mesma família (Conectar/Reativar) ou quando uma aba interna habilita seu próprio primary (FAQ/Mídia). **Aprovado em:** conversa de QA Tela 06 (2026-05-01).

- **Fundação §❌** ("Não mostrar foto de modelo em sidebar, lista, hover ou qualquer superfície que não a tela explícita de cadastro"): esta tela é **a única superfície autorizada** do painel para renderizar foto/mídia da modelo. O veto continua valendo para todas as outras telas (Painel, Atendimentos, Agenda, CRM, Pix, Dashboard) — nenhuma delas exibe `foto_perfil_url` ou thumbs de `modelo_midia`. **Aprovado em:** conversa de QA Tela 06 (2026-05-01).

- **Fundação §8.1 / fundação §12** (Realtime exigir cobertura completa): esta tela **não** assina `atendimentos` apesar de exibir indicadores derivados deles (`atendimentos_abertos`, `conversas_ia_pausada`, `ultimo_handoff_em`). **Justificativa:** dados são agregados pelo `GET /api/modelos`; tabela `atendimentos` tem alta cardinalidade e já é assinada por Telas 01/02/04. Refetch acontece quando `modelos.updated_at` ou `modelo_faq`/`modelo_midia` mudam, ou quando o usuário re-seleciona uma modelo. Indicadores podem ficar até 250ms desatualizados após uma transição em `atendimentos` — aceitável para uma tela de configuração. **Aprovado em:** conversa de QA Tela 06 (2026-05-01).

### 17.2 Pontos imutáveis específicos

- ❌ Não editar texto livre de **persona** no painel — persona vive em `api/src/barra/agente/prompts/persona.md` (Git). Painel só interpola campos estruturados.
- ❌ Não versionar prompt no banco — versionamento é via Git no repositório.
- ❌ Não fazer rollback de prompt no painel — rollback = `git revert`.
- ❌ Não exibir `foto_perfil_url` ou thumbs de `modelo_midia` em qualquer outra superfície do painel (vide §17.1 acima).
- ❌ Não preview automático de mídia (chip + click → modal — exceto thumbs em grade na aba Mídia, que **são** preview deliberado dentro da única superfície autorizada).
- ❌ Não permitir mesclar/desligar modelos a partir desta tela; "Inativa" é o estado terminal acessível.
- ❌ Não enviar mensagens manualmente pelo grupo de **Coordenação por modelo** a partir desta tela; aba Coordenação é só vínculo + verificação.
- ❌ Não criar novo motivo de `ia_pausada_motivo` para "modelo pausada" — usar `modelo_em_atendimento` (vocabulário fechado do `CONTEXT.md`).
- ❌ Não retomar IA automaticamente ao reativar modelo — devolução é por conversa, manual.
- ❌ Não cachear `prompt-preview` no cliente.
- ❌ Não criar deep link em rotas `/modelos/{id}` (path) — esta tela usa `/modelos?modelo={id}&aba={slug}` (query string) por consistência com o split lista|detalhe das demais telas.

---

## 18. Pontos em aberto

- ⚠ **OPEN-1 — Validação dos 2 membros do grupo de Coordenação:** o backend precisa conhecer o número de Fernando para conferir os membros do grupo na verificação. Sugerido: configurar `BARRAVIPS_FERNANDO_NUMERO` em `api/settings.py` e usar na verificação. Decisão fica fora desta spec (pertence a backend/infra).
- ⚠ **OPEN-2 — Política de retenção da foto de perfil:** sem política de purga no MinIO no P0; foto removida da modelo via `DELETE /api/modelos/{id}/foto-perfil` deve idealmente disparar `RemoveObject` no MinIO, mas comportamento depende de bucket policy. Decisão fica fora desta spec.
- ⚠ **OPEN-3 — Filtros `?modelo_id=` em outras telas:** atalhos da aba Coordenação (§5.12.2) assumem que Tela 02 (Atendimentos), Tela 03 (Agenda) e Tela 04 (CRM) aceitam `modelo_id` na query string. Tela 04 já lista a opção (§5.2 Tela 04). Telas 02 e 03 mencionam `modelo_id` apenas como reservado para P1. **Pré-requisito de implementação:** estender as toolbars dessas telas para aceitar e aplicar o filtro via URL antes de codificar os atalhos aqui.

---

## Anexo A — Wireframe textual

```text
┌─────────────────┬───────────────────────────────────────────────────────────────┐
│ Sidebar         │ Modelos                              [ + Adicionar modelo ]   │
│ compartilhada   │                                                               │
│                 │ [Buscar nome, número ou bairro] [Status v] [Evolution v] [Tipo│
│                 │                                                               │
│                 │ ┌──────────────────────────────┐ ┌─────────────────────────┐ │
│                 │ │┃[Ativa] [Evolution: pareada] │ │ ⬤ Júlia · 28 · pt-BR ·   │ │
│                 │ │ Júlia                        │ │   Copacabana             │ │
│                 │ │ (21) 98765-4321              │ │ [Ativa] [Evolution: pa.] │ │
│                 │ │ 12 abertos · 3 IA pausada    │ │ [Coordenação: vinculada] │ │
│                 │ │ último handoff há 14 min     │ │       [ Pausar modelo ]  │ │
│                 │ ├──────────────────────────────┤ │                         │ │
│                 │ │ [Pausada] [Evolution: pa.]   │ │ [Perfil][Prompt][FAQ]   │ │
│                 │ │ Camila                       │ │ [Mídia][Coordenação]    │ │
│                 │ │ (21) 99887-7766              │ │                         │ │
│                 │ │ 0 abertos · 2 IA pausada     │ │ Identidade              │ │
│                 │ │ último handoff há 3 d        │ │ Foto: [● Alterar foto] │ │
│                 │ └──────────────────────────────┘ │ Nome [Júlia]            │ │
│                 │ [Carregar mais]                  │ Idade [28]              │ │
│                 │                                  │ Status [Ativa] (hdr)    │ │
│                 │                                  │ [ Salvar identidade ]   │ │
│                 │                                  │                         │ │
│                 │                                  │ WhatsApp e Evolution    │ │
│                 │                                  │ Número [+5521987654321] │ │
│                 │                                  │ Status: pareada         │ │
│                 │                                  │ inst_abc123             │ │
│                 │                                  │ [ Reparear ]            │ │
│                 │                                  │ [ Salvar WhatsApp ]     │ │
│                 │                                  │                         │ │
│                 │                                  │ Acordo financeiro       │ │
│                 │                                  │ Valor padrão R$ 1.000,00│ │
│                 │                                  │ Repasse %  40           │ │
│                 │                                  │ Aplica a fechamentos    │ │
│                 │                                  │ futuros (snapshot).     │ │
│                 │                                  │ Chave Pix [...]         │ │
│                 │                                  │ Titular [...]           │ │
│                 │                                  │ [ Salvar financeiro ]   │ │
│                 │                                  │                         │ │
│                 │                                  │ Operação                │ │
│                 │                                  │ Localização [Copacabana]│ │
│                 │                                  │ Idiomas [pt-BR][en-US]  │ │
│                 │                                  │ Tipos ☑ interno ☑ ext.  │ │
│                 │                                  │ [ Salvar operação ]     │ │
│                 │                                  └─────────────────────────┘ │
└─────────────────┴───────────────────────────────────────────────────────────────┘
```

— FIM —
