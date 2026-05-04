# Pix de Deslocamento — Guia UX para Iteração

> Doc operacional para agentes de IA iterarem o módulo. Foca em jornada, UX, propósito e dados — não em implementação técnica.

---

## Propósito no sistema

A tela de Pix é uma **fila de triagem com urgência real**. Quando um comprovante de Pix chega e a IA detecta algo suspeito, ela pausa e coloca o Pix em revisão — o cliente está parado esperando confirmação para sair de casa. Fernando precisa decidir rápido: validar ou rejeitar.

A tela tem dois modos de uso distintos:
- **Decisão urgente** (filtro padrão "Aguardando você"): fila FIFO — mais antigo aparece primeiro porque é o que está esperando há mais tempo
- **Auditoria** (filtros de histórico): verificar Pix aprovados automaticamente, rever rejeições, entender padrões

Nenhuma outra tela do sistema decide Pix — esta é a única superfície de validação/rejeição.

---

## Usuário e contexto de uso

**Único usuário:** Fernando. Acessa a tela quando o Painel avisa sobre Pix pendentes, ou proativamente para auditar.

**Pergunta que Fernando traz ao abrir com pendências:** "Esse comprovante é legítimo? Posso liberar o cliente?"

**Pergunta na auditoria:** "Quais Pix foram aprovados automaticamente ontem?" ou "Por que rejeitamos esse?"

**Critério de sucesso da decisão:** Fernando visualiza o comprovante, verifica as checagens, decide e confirma em menos de 60 segundos.

---

## Jornada do usuário

```
Abrir /pix (vindo do Painel via "Ver N Pix em revisão")
    → Filtro "Aguardando você" pré-selecionado
    → Lista em ordem FIFO (mais antigo no topo)
    → Primeiro Pix selecionado automaticamente

Inspecionar o Pix pendente
    → Header: quem enviou e quando
    → Ações: [Validar Pix] · [Rejeitar Pix] · [Abrir atendimento] · [Abrir conversa]
    → Comprovante: chip com nome/tamanho → "Visualizar comprovante"
    → Dados do comprovante: valor, data/hora, remetente, chave, identificador
    → Verificações automáticas: passou/falhou cada checagem
    → Atendimento vinculado: contexto do negócio em andamento
    → Histórico: jornada do comprovante desde o recebimento

Decidir
    → "Validar Pix" → AlertDialog com descrição dos efeitos → confirmar
        → Backend dispara: card "saída confirmada" no grupo da modelo,
          IA pausa por modelo_em_atendimento, atendimento → Confirmado
        → Toast "Pix de R$ X validado"
    → "Rejeitar Pix" → AlertDialog com select de motivo + observação → confirmar
        → Backend envia mensagem padronizada ao cliente pedindo novo comprovante
        → Toast "Pix rejeitado"
    → Lista recarrega, próximo Pix pendente aparece automaticamente

Auditar (outro momento)
    → Trocar filtro para "Validado automaticamente" / "Validado por você" / "Rejeitado" / "Todos"
    → Lista muda para ordem DESC (mais recente no topo)
    → Ver histórico e verificações para cada Pix
```

---

## Blocos visuais

### 1. Header
**Arquivo:** `components/pix/HeaderPix.tsx`

Título "Pix de deslocamento" em serif 40px + subtítulo "Aprove Pix duvidosos e revise os já validados." em muted. Sempre visível, sem estado variável.

---

### 2. Toolbar de filtros
**Arquivo:** `components/pix/ToolbarPix.tsx`

Grid `grid-cols-[minmax(260px,1fr)_180px_160px_180px_140px]` com 5 controles nativos:

| Controle | Tipo | Opções |
|---|---|---|
| Busca | Input + ícone | "Buscar valor, cliente, telefone ou #N" |
| Status | `<select>` | **Aguardando você** (default) · Validado automaticamente · Validado por você · Rejeitado · Todos |
| Modelo | `<select>` | Todas · [lista dinâmica] |
| Motivo de revisão | `<select>` | Todos · Valor divergente · Fora da janela · Conta destino inválida · Comprovante duplicado · **Não conseguimos ler** · Outro |
| Período | `<select>` | Todos · 24 h · 7 dias · 30 dias |

> **Labels reais diferem do vocabulário interno:** o status "em revisão" aparece para o usuário como "Aguardando você" e "Validado por você" (não "por Fernando"). O motivo `ocr_falhou` é exibido como "Não conseguimos ler".

A lista de modelos é construída dinamicamente a partir dos itens carregados na lista e do detalhe ativo — não vem de um endpoint dedicado.

**Busca com debounce** de 300ms (gerenciado no hook). Os selects são imediatos.

**Loading:** quando `listaStatus === "loading"`, a toolbar vira 5 skeletons `h-9`.

**Deep link `?atendimento={id}`:** lido na inicialização do hook — muda o status para "Todos" automaticamente e filtra por aquele atendimento. Sem controle visível na toolbar.

**Deep link `?status=em_revisao`:** também aceito e mapeado para "pendentes".

---

### 3. Lista de Pix
**Arquivos:** `components/pix/ListaPix.tsx` + `ItemPix.tsx`

Coluna fixa de **360px**. Skeleton de 8 itens `h-[88px]` durante o carregamento.

**Anatomia do item:**
```
[Badge status]                    [tempo relativo]
R$ Valor  (ou "Valor não extraído" em muted quando null)
{cliente} · {modelo} · #{numero_curto}
{label do motivo}  ← só quando em_revisao e motivo_em_revisao não null
```

**Badges de status:**

| Status interno | Variant | Label exibido |
|---|---|---|
| `em_revisao` | `revisao` | "Aguardando você" |
| `validado_auto` | `closed` | "Validado auto" |
| `validado_manual` | `closed` | "Validado por você" |
| `rejeitado` | `lost` | "Rejeitado" |

**Sinais visuais da borda esquerda:**
- Item selecionado: `border-l-state-active`
- Em revisão (pendente) + não selecionado: `border-l-state-handoff`
- Demais: `border-l-transparent`

**Paginação:** botão "Carregar mais" aparece ao final quando `nextCursor` existe.

**Empty states:**
- Filtro padrão sem itens: "Nenhum Pix aguardando decisão." + "Pix duvidosos aparecem aqui assim que precisarem da sua decisão."
- Com filtros ativos: "Nenhum Pix encontrado para estes filtros." + "Ajuste os filtros para ampliar a busca."

---

### 4. Header do detalhe
**Arquivo:** `components/pix/DetalhePix.tsx`

Card com badge de status + nome do cliente (ou telefone) em 22px + "Conversa com {modelo.nome}" + tempo relativo "Recebido há X".

**Estado sem seleção:** card com "Selecione um Pix na lista para ver os detalhes."

**Skeleton:** 7 skeletons de alturas variadas empilhados.

---

### 5. Ações
**Arquivo:** `components/pix/AcoesPix.tsx`

| Situação | Botões disponíveis |
|---|---|
| Pendente (`em_revisao`) | **Validar Pix** (primary) · Rejeitar Pix (danger) · Abrir atendimento (ghost) · Abrir conversa (ghost) |
| Validado (auto ou manual) | Abrir atendimento (ghost) · Abrir conversa (ghost) |
| Rejeitado | Reabrir Pix (secondary) · Abrir atendimento (ghost) · Abrir conversa (ghost) |

"Abrir atendimento" só aparece quando `detalhe.atendimento !== null` → navega para `/atendimentos` (sem deep link para o atendimento específico).

"Abrir conversa" só aparece quando `detalhe.conversa !== null` → navega para `/crm`.

**AlertDialog de validação:** "A modelo recebe a saída confirmada no grupo de Coordenação e o atendimento avança para Confirmado. Esta decisão é definitiva."

**AlertDialog de rejeição:**
- Select de motivo com default `"valor_incorreto"` (Valor incorreto · Comprovante ilegível · Conta destino errada · Comprovante duplicado · Fora da janela temporal · Outro)
- Textarea de observação: obrigatória apenas quando motivo = "outro"; para os demais é opcional — placeholder "Não exibida ao cliente"
- Contador `{N}/500` aparece apenas quando `>= 400` caracteres; max 500

**AlertDialog de reabertura:** "O Pix volta para revisão. O atendimento não é alterado."

---

### 6. Comprovante
**Arquivo:** `components/pix/ComprovantePix.tsx`

Card com título "Comprovante" (label style). Exibe `nome_arquivo` + `tamanho` formatado em chip com ícone `Paperclip`.

**Estados do botão:**

| `comprovante_disponivel` | `comprovanteStatus` | Botão |
|---|---|---|
| false | qualquer | "Visualizar comprovante" disabled + tooltip "Arquivo não está mais disponível" |
| true | `loading` | "Carregando…" disabled (sem spinner) |
| true | `error` | "Tentar novamente" em `variant="danger"` |
| true | `idle` ou `success` | "Visualizar comprovante" em `variant="secondary"` |

A URL do comprovante é carregada **após** o detalhe (sequencial) — só quando `comprovante_disponivel === true`.

Clicar no botão abre `DialogVisualizarComprovante`.

---

### 7. Dialog de visualização do comprovante
**Arquivo:** `components/pix/DialogVisualizarComprovante.tsx`

Usa shadcn `Dialog` — fullscreen `h-[100vh] w-[100vw]` com fundo `bg-ink-0`. Botão X (ghost icon) no canto superior direito via `DialogClose`.

**Por tipo MIME:**
- **Imagem** (`image/*`): `<img>` com `max-h-[90vh] max-w-[90vw] object-contain`
- **PDF** (`application/pdf`): `<iframe>` `h-[90vh] w-[90vw]` + link "Abrir em nova aba" com ícone `ExternalLink`
- **Outros**: apenas link "Abrir em nova aba"

**Loading dentro do modal:** texto "Carregando…"

**Erro no modal:** `BannerErro` com botão "Tentar novamente".

---

### 8. Dados do comprovante (metadados extraídos)
**Arquivo:** `components/pix/MetadadosPix.tsx`

Card com título "Dados do comprovante". Grid `sm:grid-cols-[180px_1fr]` com pares label/valor.

| Campo | Label | Valor quando ausente |
|---|---|---|
| `valor_extraido` | Valor | "Não identificado" |
| `horario_transacao` | Data e hora | "Não identificado" |
| `titular_extraido` + `documento_extraido` | Remetente | "Não identificado" — quando presente, exibe nome + CPF/CNPJ em mono |
| `chave_extraida` + `tipo_chave` | Chave de destino | "Não identificado" — quando presente, mostra chave em mono + tipo como label |
| `hash_duplicidade` | Identificador | **Omitido quando null** — quando presente, truncado a 12 chars com tooltip do valor completo |

> Campos ausentes mostram "Não identificado" (não "Não extraído"). O hash só aparece quando existe.

---

### 9. Verificações automáticas
**Arquivo:** `components/pix/ChecagensPix.tsx`

Card com título "Verificações automáticas". A lista de checagens vem do backend — não há checagens canônicas fixas no frontend.

Cada item:
```
[CheckCircle2 verde / XCircle vermelho]  [LABEL EM MAIÚSCULAS]
                                          {motivo da falha — só quando !passou}
```

Ícones: `CheckCircle2` em `text-state-closed` / `XCircle` em `text-state-lost`.

**Empty state:** "Nenhuma verificação registrada para este Pix."

Este bloco aparece em todos os estados — é a trilha de auditoria que explica por que o pipeline aprovou ou colocou em revisão.

---

### 10. Atendimento vinculado
**Arquivo:** `components/pix/AtendimentoVinculadoPix.tsx`

Borda esquerda: atendimento aberto → `border-l-state-handoff`; terminal (Fechado/Perdido) → `border-l-border-strong`.

**Quando há atendimento:**
```
[Badge estado]  #{numero_curto}
{tipo} · {urgência} · {valor acordado}
{próxima ação esperada em text-state-handoff}  ← omitida se null
[Abrir na Central]
```

> **Nome do cliente não é exibido** neste card — apenas `#N` e badge.

"Abrir na Central" navega para `/atendimentos` (sem deep link para o atendimento específico).

**Quando não há atendimento:** "Pix sem atendimento vinculado."

---

### 11. Histórico
**Arquivo:** `components/pix/LinhaTempoPix.tsx`

Card com título "Histórico". Eventos renderizados na ordem em que chegam do backend (sem ordenação client-side).

Cada evento:
```
[Ícone cor]  [Label]  · {autor}             {data/hora}
             {resumo ou motivo+obs — truncado}
```

**Tipos de evento com ícone/cor definidos:**

| Tipo | Label | Ícone | Cor |
|---|---|---|---|
| `comprovante_recebido` | "Comprovante recebido" | `Inbox` | muted |
| `pipeline_validado` | "Validado automaticamente" | `CheckCircle2` | success |
| `pipeline_em_revisao` | "Marcado para revisão" | `AlertCircle` | warn |
| `pix_validado_manual` | "Validado por você" | `CheckCircle2` | success |
| `pix_rejeitado` | "Rejeitado por você" | `XCircle` | danger |
| `pix_reaberto` | "Reaberto por você" | `RefreshCw` | warn |
| outros | label gerado do tipo | `Dot` | muted |

Para `pix_rejeitado`: o resumo exibe `{motivo} · {observação truncada em 40 chars}`.

**Empty state:** "Nenhum evento registrado."

---

## Dados que alimentam a tela

| Chamada | O que faz |
|---|---|
| `GET /v1/pix?...` | lista com filtros e cursor (limit 50) |
| `GET /v1/pix/{id}` | detalhe: metadados, checagens, atendimento, eventos, conversa |
| `GET /v1/pix/{id}/comprovante-url` | URL assinada do MinIO; chamada sequencialmente após detalhe quando `comprovante_disponivel === true` |
| `POST /v1/pix/{id}/aprovar` | valida manualmente, dispara handoff no backend |
| `POST /v1/pix/{id}/rejeitar` | rejeita; backend envia mensagem ao cliente |
| `POST /v1/pix/{id}/reabrir` | volta para fila de revisão sem afetar atendimento |

Após aprovar, rejeitar ou reabrir, o hook recarrega a lista imediatamente (não aguarda Realtime).

**Realtime:** assina `comprovantes_pix` e `atendimentos`. Qualquer mudança dispara refetch debounced de 250ms — `loadLista("replace", true, true)` (mantém seleção, atualiza detalhe).

---

## Efeitos colaterais que Fernando precisa entender

A tela Pix é a única onde uma ação de Fernando dispara uma cascata automática no backend:

**Ao validar um Pix manualmente:**
1. Backend envia card "saída confirmada" no grupo de Coordenação por modelo
2. IA pausa com motivo `modelo_em_atendimento`
3. Atendimento avança para estado `Confirmado`

Fernando não precisa fazer mais nada — a validação substitui toda essa sequência. Está explícito no AlertDialog de validação para que ele não aja por impulso.

**Ao rejeitar:**
- Backend escolhe e envia mensagem ao cliente com base no motivo selecionado — Fernando não redige a mensagem
- Atendimento permanece no estado anterior
- IA continua pausada por `pix_em_revisao` aguardando novo comprovante

---

## Estados e variações importantes

| Situação | Comportamento |
|---|---|
| Carregando lista | skeleton de 8 itens `h-[88px]` |
| Carregando detalhe | 7 skeletons empilhados |
| Fila vazia (Aguardando você) | empty state com contexto de quando aparecem |
| Lista vazia com filtros | empty state "Ajuste os filtros para ampliar a busca." |
| Sem item selecionado | card "Selecione um Pix na lista para ver os detalhes." |
| Pix decidido (validado/rejeitado) | sem "Validar"/"Rejeitar" nos ações; "Reabrir" para rejeitado |
| Carregando URL do comprovante | botão mostra "Carregando…" e fica desabilitado |
| Arquivo indisponível (`comprovante_disponivel=false`) | botão disabled com tooltip |
| Erro ao carregar URL | botão vira "Tentar novamente" em `variant="danger"` |
| Erro no modal aberto | `BannerErro` com retry |
| Submetendo ação | botões do dialog desabilitados + texto de loading ("Validando…" / "Rejeitando…" / "Reabrindo…") |
| Sucesso em ação | toast + dialog fecha + lista recarrega |
| Realtime durante sessão | lista e detalhe atualizam silenciosamente |

---

## Oportunidades de iteração identificadas

1. **Ausência de contador de fila no header** — Fernando não sabe quantos Pix pendentes existem sem contar os cards na lista. Um "N aguardando decisão" daria noção de volume sem precisar scrollar.
2. **Verificações sem legenda de severidade** — todas as reprovadas parecem igualmente graves. Uma checagem de "valor divergente" é muito mais crítica que "fora da janela por 3 minutos". Uma hierarquia visual (bloqueante vs. aviso) ajudaria na decisão.
3. **Modal de comprovante sem zoom** — imagens de comprovante frequentemente têm texto pequeno. Um zoom por pinch/scroll ou botão facilitaria a verificação visual.
4. **Ausência de comparação valor combinado × valor do comprovante** — a checagem mais frequente de rejeição, mas Fernando precisa rolar até o atendimento vinculado para ver o valor combinado. Mostrar "esperado R$ 200 · recebido R$ 195" diretamente nos dados ou ações eliminaria esse vai-e-volta.
5. **Rejeição sem histórico da mensagem enviada** — Fernando não vê qual texto exato foi enviado ao cliente após a rejeição. Exibir no histórico daria transparência.
6. **Fila pode crescer enquanto Fernando decide** — se chegarem novos Pix durante a sessão, a lista atualiza via Realtime. Não há sinal visual de que a lista foi atualizada, o que pode desorientar quem acompanhava a posição de um Pix específico.
7. **"Abrir atendimento" sem deep link** — navega para `/atendimentos` sem selecionar o atendimento específico; Fernando precisa encontrá-lo na lista.
