# Central de Atendimentos — Guia UX para Iteração

> Doc operacional para agentes de IA iterarem o módulo. Foca em jornada, UX, propósito e dados — não em implementação técnica.

---

## Propósito no sistema

A Central de Atendimentos é onde Fernando **gerencia os ciclos comerciais em andamento**. Enquanto o Painel Geral mostra o que precisa de ação imediata, a Central é o lugar de trabalho aprofundado: ver o histórico de uma conversa, entender o contexto de um cliente, decidir se aceita ou fecha um negócio.

Fernando abre essa tela com uma pergunta específica: _"O que está acontecendo com este atendimento?"_ ou _"Preciso resolver o handoff do #142."_

---

## Usuário e contexto de uso

**Único usuário:** Fernando. Acessa a Central quando chega do Painel (clicou em um card de handoff), quando quer revisar o histórico de um cliente, ou quando precisa converter/perder um atendimento.

**Contexto típico de chegada:**
- Veio do Painel via deep link (`?id=...`) → atendimento específico já está selecionado
- Abriu diretamente → a tela seleciona automaticamente o primeiro item da lista

**Pergunta que Fernando traz:** "O que aconteceu aqui e o que eu preciso fazer?"

**Critério de sucesso:** Fernando entende a situação e executa (ou descarta) sua ação em menos de 30 segundos.

---

## Jornada do usuário

```
Abrir /atendimentos
    → Skeletons enquanto carrega lista + detalhe
    → Lista exibe atendimentos abertos (filtro padrão)
    → Primeiro item selecionado automaticamente
    → Detalhe carrega à direita

Inspecionar o detalhe
    → Header: quem é o cliente, qual modelo, estado, tempo, telefone em mono
    → Ações disponíveis (Devolver para IA / Converter / Perder)
    → Resumo: o que foi combinado
    → Histórico de mensagens: bolhas da conversa (colapsado)
    → Mídias recebidas: chips de arquivos/comprovantes (colapsado)
    → Histórico do atendimento: eventos do sistema (colapsado)

Aplicar filtros (opcional)
    → Busca por nome, telefone ou #N
    → Filtro por estado, tipo, quando ou IA
    → Lista recarrega, seleciona o primeiro resultado

Executar ação
    → "Devolver para IA" → AlertDialog simples → confirma → IA retoma
    → "Converter"        → AlertDialog com campo Valor Final → confirma → atendimento some da lista
    → "Perder"           → AlertDialog com select de motivo → confirma → atendimento some da lista
```

---

## Blocos visuais

### 1. Layout geral
**Arquivo:** `app/(interface)/atendimentos/page.tsx`

A tela é um flex column com altura `h-[calc(100vh-64px)]`. Estrutura:
```
H1 "Atendimentos" (serif 2xl)
Toolbar de filtros (flex-none)
Grid dois-colunas: [320px | resto] (flex-1, overflow independente)
```

A coluna da lista tem `overflow-y-auto` próprio; o detalhe também — cada coluna rola independentemente.

---

### 2. Toolbar de filtros
**Localização:** componente `Toolbar` inline em `page.tsx` (não arquivo separado)

Grid `grid-cols-[minmax(160px,1fr)_140px_110px_120px_100px]` com 5 controles:

| Controle | Tipo | Opções visíveis |
|---|---|---|
| Busca | Input com ícone Search | placeholder "Buscar cliente, telefone ou #N" |
| Estado | `<select>` nativo | Abertos (padrão) · Novo · Triagem · Qualificado · Aguardando confirmação · Confirmado · Em atendimento · Fechado · Perdido |
| Tipo | `<select>` nativo | Todos · No local da modelo · No local do cliente |
| Quando | `<select>` nativo | Todas · Agora · Marcado · Indefinido · Estimado |
| IA | `<select>` nativo | Todos · IA ativa · IA pausada |

Os selects são `<select>` nativo estilizado — não shadcn Select.

**Loading:** quando `status === "loading"`, a toolbar inteira vira 5 skeletons `h-9`.

**UX:** a busca chama `onBuscaChange` a cada keystroke (sem debounce na toolbar — debounce é responsabilidade do hook).

---

### 3. Lista de atendimentos
**Arquivos:** `components/atendimentos/ListaAtendimentos.tsx` + `ItemAtendimento.tsx`

Coluna fixa de **320px**. Card com `divide-y` separando os itens.

**Anatomia do item:**
```
[Nome do cliente]              [Badge estado]  [tempo relativo]
[Modelo · #N · tipo · urgência]
```

- Nome vem primeiro (flex-1 truncate, negrito), badge e tempo ficam à direita
- Segunda linha: `{modelo.nome} · #{numero_curto} · {tipoLabel} · {urgenciaLabel}` — apenas os campos não-null são incluídos
- **Não há terceira linha** de motivo ou próxima ação

**Sinais visuais da borda esquerda (3px):**

| Situação | Token |
|---|---|
| Item selecionado | `border-l-state-active` |
| IA pausada + não selecionado | `border-l-state-handoff` |
| Default | `border-l-transparent` |

Item selecionado também recebe `bg-ink-200`.

**Paginação:** quando `nextCursor` existe, aparece botão "Carregar mais" ao final da lista.

**Empty states:**
- Filtro padrão (sem filtros): ícone `Inbox` + "Nenhum atendimento aberto." + "Novos atendimentos aparecem quando clientes chamarem no WhatsApp da modelo."
- Com filtros ativos: "Nenhum atendimento encontrado para estes filtros." + "Ajuste os filtros para ampliar a busca."

---

### 4. Header + ações do atendimento
**Arquivo:** `components/atendimentos/DetalheAtendimento.tsx` + `AcoesAtendimento.tsx`

O header e as ações ficam **dentro do mesmo card** com borda esquerda colorida:

| Estado | Token da borda |
|---|---|
| Fechado | `border-l-state-closed` |
| Perdido | `border-l-state-lost` |
| `ia_pausada = true` | `border-l-state-handoff` |
| Default (ativo) | `border-l-state-active` |

**Conteúdo do header:**
```
[Badge estado]  [Nome do cliente]  · {modelo.nome}          #{N} · atualizado há X
                {telefone em mono}
[Ações]
```

**Ações (`AcoesAtendimento`):**

| Botão | Condição de exibição | Variant |
|---|---|---|
| Devolver para IA | `ia_pausada = true` | `primary` |
| Converter | sempre (atendimento aberto) | `primary` se devolver ausente, `secondary` se devolver presente |
| Perder | sempre (atendimento aberto) | `danger` |

> **Atenção:** o botão de encerramento bem-sucedido chama-se **"Converter"**, não "Fechar". O dialog title também é "Converter #N?".

Para atendimentos com estado `Fechado` ou `Perdido`, o componente `AcoesAtendimento` retorna `null` — nenhum botão de ação é renderizado.

**Dialogs:**
- **Devolver:** confirmação simples — "A IA volta a responder o cliente na próxima mensagem."
- **Converter:** campo obrigatório "Valor final" com `inputMode="decimal"`, aceita vírgula brasileira (`1200,00`), valida número ≥ 0.
- **Perder:** select de motivo com padrão `"sumiu"` (Preço · Sumiu · Risco · Indisponibilidade · Fora de área · Outro) + campo "Observação" obrigatório apenas quando "Outro" é selecionado.

Todos os dialogs exibem erro inline abaixo do campo quando validação falha.

**Estado "enviando":** botão de ação fica desabilitado, texto muda para "Devolvendo..." / "Fechando..." / "Registrando...". O dialog fecha apenas no sucesso.

---

### 5. Resumo do atendimento
**Arquivo:** `components/atendimentos/ResumoAtendimento.tsx`

Card sempre visível abaixo do header. Header do card: ícone `ReceiptText` + "Resumo do atendimento".

Grid `xl:grid-cols-2` com quatro grupos:

| Grupo | Campos |
|---|---|
| **Comercial** | Estado · Tipo · Quando · Valor acordado · Forma de pagamento |
| **Agenda/local** | Data desejada · Horário desejado · Duração · Endereço · Bairro · Tipo local |
| **IA** | Responsável · Por que pausou (só se `ia_pausada`) · Próxima ação · Resumo |
| **Pix** | Pix (status formatado) · Último comprovante (data/hora) |

**Comportamento de campos ausentes:** campos com valor `null` são omitidos da lista; grupos inteiros cujos campos são todos `null` não são renderizados. Campos "Próxima ação" e "Resumo" usam fallback `"Não informado ainda"` quando null.

**Seções condicionais abaixo da grid:**
- **Qualificação** — aparece se `sinais_qualificacao` tem campos booleanos; cada sinal vira chip arredondado `{chave}: sim/não`
- **Bloqueio** — aparece se existe `bloqueio`; exibe `{data/hora início} · {estado}` + link "Abrir na agenda" para `/agenda?bloqueio={id}`

---

### 6. Histórico de mensagens
**Arquivo:** `components/atendimentos/HistoricoMensagens.tsx`

Dentro de `SecaoColapsavel` com título **"Histórico de mensagens"** — inicia **colapsado**.

Layout de bolhas de chat: mensagens `ia` e `modelo_manual` ficam à direita (`justify-end`), `cliente` fica à esquerda (`justify-start`).

**Cada bolha:**
- Remetente: "IA" em `text-text-brand` com peso semibold; "MODELO" em muted; "Cliente" em muted
- Horário ao lado do remetente
- Chip de mídia no topo da bolha quando `tipo !== "texto"` ou `media_object_key` não é null — exibe nome do arquivo em mono, não é clicável aqui
- Texto truncado em `line-clamp-2` quando `conteudo.length > 140`; botão ghost "Expandir" / "Recolher" aparece

**Estilos das bolhas:**
- `ia`: borda esquerda `border-l-border-brand` + `bg-ink-200`
- `modelo_manual`: `bg-ink-200` sem borda especial
- `cliente`: `bg-ink-100`

**Empty state:** ícone `MessageSquareOff` + "Nenhuma mensagem vinculada a este atendimento."

---

### 7. Mídias recebidas
**Localização:** função `MidiasRecebidas` dentro de `DetalheAtendimento.tsx`

Dentro de `SecaoColapsavel` com título **"Mídias recebidas"** — inicia **colapsado**.

Mídias são combinadas em uma lista plana: comprovantes Pix primeiro, depois mensagens com mídia. Cada item é um botão chip em mono com ícone `FileText`:
- Comprovantes Pix: `nome = "comprovante Pix"`, `subtitulo = "{decisao_pipeline} · {data/hora}"`, `url = null` (sempre desabilitado)
- Mídias de mensagens: `nome = {media_object_key ?? tipo}`, `url = media_url`

Chips com `url = null` ficam com `disabled` e `cursor-default`. Chips com URL abrem `AlertDialog` com `<Image>` next/image em modal fullscreen.

**Empty state:** ícone `ImageOff` + "Nenhuma mídia recebida neste atendimento."

---

### 8. Histórico do atendimento
**Arquivos:** `components/atendimentos/LinhaEvento.tsx`

Dentro de `SecaoColapsavel` com título **"Histórico do atendimento"** — inicia **colapsado**.

Eventos ordenados do mais recente para o mais antigo (decrescente por `created_at`).

**Cada linha:**
```
[tipo do evento]  [origem]  · [autor se diferente da origem]          [data/hora]
[resumo do payload — até 2 linhas]
```

Não há payload expansível — o `resumoPayload` extrai uma string legível do payload JSON e exibe com `line-clamp-2`.

**Empty state:** "Nenhum evento registrado neste atendimento."

---

## Dados que alimentam a tela

Dois endpoints principais:

| Chamada | O que traz |
|---|---|
| `GET /api/v1/atendimentos` | lista paginada por cursor com filtros |
| `GET /api/v1/atendimentos/{id}` | `atendimento`, `cliente`, `modelo`, `bloqueio`, `mensagens`, `eventos`, `comprovantes_pix` |

Três endpoints de ação (AlertDialog confirma antes de chamar):

| Ação | Endpoint |
|---|---|
| Devolver para IA | `POST /api/v1/atendimentos/{id}/devolver` |
| Converter | `POST /api/v1/atendimentos/{id}/fechar` com `valor_final` |
| Perder | `POST /api/v1/atendimentos/{id}/perder` com `motivo` e `observacao` |

**Realtime:** a tela assina 4 tabelas (`atendimentos`, `mensagens`, `eventos`, `comprovantes_pix`). Qualquer mudança dispara refetch debounced de 250ms — sem patch local.

---

## Comportamento do filtro e deep links

A tela aceita deep links do Painel e do Dashboard:

| Origem | Query string | Resultado |
|---|---|---|
| Painel (card de handoff) | `?id={uuid}` | seleciona o atendimento diretamente sem alterar filtro |
| Dashboard — funil | `?estado=Qualificado` | lista filtra por estado; toolbar reflete |
| Dashboard — perdas | `?estado=Perdido&motivo_perda=preco` | lista filtra server-side; `motivo_perda` invisível na toolbar mas ativo |
| Dashboard — escaladas | `?ia_pausada=true&motivo_escalada=Risco+local` | lista filtra por IA pausada; `motivo_escalada` invisível na toolbar mas ativo |

`motivo_perda` e `motivo_escalada` chegam por deep link como `filtrosUrl` (passados ao hook separadamente dos `filtrosOverride`) — sem controle visível na toolbar. Ficam ativos até o usuário trocar o filtro correspondente.

---

## Estados e variações importantes

| Situação | Comportamento |
|---|---|
| Carregando lista | skeleton de 8 itens de `h-[88px]` |
| Carregando detalhe | skeleton de header (h-24) + resumo (h-72) + mensagens + eventos |
| Lista vazia (filtro padrão) | empty state "Nenhum atendimento aberto" com contexto |
| Lista vazia (com filtros) | empty state "Nenhum atendimento encontrado para estes filtros." |
| Detalhe sem item selecionado | card "Nenhum atendimento selecionado." com instrução |
| Atendimento Fechado/Perdido | sem ações (`AcoesAtendimento` retorna null) |
| Submetendo ação | botão do dialog desabilitado + texto de loading inline |
| Erro ao agir | toast de erro, dialog permanece aberto |
| Erro 403/404 ao agir | toast de erro |
| Sucesso em ação | toast, dialog fecha, lista refaz (item some se sair do filtro) |
| Refetch por Realtime | lista e detalhe atualizam silenciosamente, sem skeleton |

---

## Oportunidades de iteração identificadas

1. **Seções colapsadas por padrão** — mensagens, mídias e eventos iniciam fechados. Fernando que chega de um handoff precisa abrir manualmente para ver o contexto da conversa. Poderia auto-expandir "Histórico de mensagens" quando o atendimento tem `ia_pausada = true`.
2. **Resumo operacional sem hierarquia** — grupos Comercial, IA, Pix e Agenda/local têm o mesmo peso visual. Quando Fernando chega de um handoff, o grupo "IA" (motivo + próxima ação) é o mais relevante mas não está destacado.
3. **Comprovantes Pix sempre desabilitados** — chips de comprovante ficam com `cursor-default` porque `url = null`. Falta link para `/pix` ou prévia do valor/titular extraído.
4. **Paginação de mensagens** — conversas longas carregam todas as mensagens de uma vez. Um "carregar anteriores" reduziria o tempo de carregamento inicial.
5. **Sem indicação visual de mensagens novas** — quando chega mensagem nova via Realtime num atendimento não selecionado, o item na lista não destaca de forma diferente da borda de IA pausada já existente.
6. **Eventos sem filtragem** — em atendimentos com muitos eventos, a timeline fica longa. Um filtro por tipo de evento (handoff, estado, Pix) poderia ajudar.
7. **Valor final não destacado** — para atendimentos Fechados, o `valor_final` está enterrado nos campos do grupo Comercial no resumo. Poderia aparecer no header do card para acesso rápido.
