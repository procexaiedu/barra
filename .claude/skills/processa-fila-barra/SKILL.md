---
name: processa-fila-barra
description: Drena a fila de tasks pendentes (colunas "To Do" + "Backlog") do projeto barravips no devcontext em loop autônomo Plan→Code→Review, atualizando cada task para "Review" e encerrando ao esvaziar a fila. Use quando o usuário pedir para processar a fila do barravips ou digitar /processa-fila-barra.
---

# processa-fila-barra

## Visão geral

Loop autônomo que drena a fila do projeto `barravips` no devcontext. Para cada task: planejar com `planejador-barra`, implementar com o codificador da área, revisar com `revisor-barra`, marcar `Review` com branch e hash. Sem merge, sem push, sem PR — o status terminal é sempre `Review` (humano fecha o ciclo).

## Configuração — limites de safety

- `MAX_ITERATIONS_POR_SESSAO = 20` — número máximo de tasks processadas por execução do skill. Conta cada iteração concluída (review PASS, FAIL/needs-rework ou blocked). Ao atingir 20, encerre limpo (sem reagendar) e relate `limite de iterações atingido`.
- `TIMEOUT_POR_TASK_SEGUNDOS = 2700` (45min). Registre `task_started_at = now()` no início do Passo 1. Antes de cada handoff entre passos (Plan→Code, Code→Review), compare `now() - task_started_at`. Se ultrapassar 2700s: interrompa o subagente em execução com mensagem clara, chame `update_task({ status: <coluna_origem>, is_blocked: true, blocked_reason: "timeout_overnight" })`, remova o marker, emita `LOG_ITER` com `review_status: "timeout"` e siga para a próxima iteração.

## Schema do devcontext (descoberto em smoke)

- Colunas reais do projeto `BarraVIPs` (case-sensitive, com espaços): `Backlog`, `To Do`, `In Progress`, `Review`, `Done`.
- `mcp__devcontext__get_tasks` filtra pela coluna passada em `status` (nome exato da coluna). **Truncamento conhecido**: o campo de descrição volta cortado com `…` (~150 chars). **Contexto completo (incluindo `implementation_plan`) vem por HTTP direto** — `scripts/get-task.ps1 -TaskId <id> -OutFile <path>` consulta `{url}/api/mcp/tasks?mine=false&limit=500` e devolve JSON com todos os campos (smoke 2026-05-12: o MCP `devcontext-mcp` v1.0.7 descarta `implementation_plan` no formatter — bug conhecido — mas a API HTTP retorna inteiro). O pipeline usa o helper no Passo 1.4.
- **`mine=true` é o padrão e mascara a fila inteira.** Tasks do BarraVIPs ficam atribuídas a Rafael (e outros responsáveis), não ao usuário autenticado deste pipeline (`ProcexAI`) — sem `mine=false` explícito, `get_tasks` devolve zero tasks e o loop encerra como falsa "fila vazia".
- **`In Progress` é PROIBIDA como fonte.** Essa coluna é trabalho humano manual do Rafael — o pipeline nunca pega tasks dali, mesmo que o discovery a retorne. Filtre-a explicitamente do conjunto elegível.

## Contexto inicial (uma vez por sessão)

1. Confirmar que `mcp__devcontext__get_tasks` e `mcp__devcontext__update_task` estão acessíveis. Se faltar, abortar com mensagem clara.
2. **Descobrir os nomes reais das duas colunas elegíveis** antes de filtrar (defensivo contra renomeação):
   - Chamar `mcp__devcontext__get_tasks({ mine: false })` uma vez sem `status`.
   - Coletar todos os nomes únicos de coluna do retorno.
   - Mapear duas colunas:
     - **prioridade A** ("pronto pra começar"): primeira que case (case-insensitive) com `to do`, `todo`, `pending`. Fallback `To Do` literal.
     - **prioridade B** ("não refinado mas elegível"): primeira que case com `backlog`. Fallback `Backlog` literal.
   - **Nunca incluir** colunas que casem com `in progress`, `in-progress`, `doing` ou `done`/`review` — log warn se aparecerem.
3. Listar tasks de cada coluna: `mcp__devcontext__get_tasks({ mine: false, status: "<nome>" })` para A e B separadamente. Concatene mantendo a ordem A→B (To Do primeiro, depois Backlog). Dentro de cada coluna, ordene por prioridade do devcontext (`urgent` > `high` > `medium` > `low`).
4. **Inspecionar o schema do retorno antes de presumir nomes de campos** (`id`, `title`, `priority`, `status`/`column_name` podem variar de versão para versão).
5. Se a fila concatenada estiver vazia: relatar `fila vazia, encerrando` e parar **IMEDIATAMENTE**. **NÃO reagendar, NÃO entrar em sleep, NÃO chamar `ScheduleWakeup`.** O processo termina.
6. Criar tracking interno chamando `TaskCreate` uma vez por task da fila (até o limite `MAX_ITERATIONS_POR_SESSAO`) — assim o progresso fica visível sem poluir o devcontext.
7. Inicializar `iteracoes_concluidas = 0`.
8. **Sincronizar `main` local com `origin/main` antes de criar qualquer worktree.** Rodar via Bash, na raiz do repo (`C:/barra`):
   ```bash
   git fetch origin && git checkout main && git pull --ff-only origin main
   ```
   - Worktrees nascem de `HEAD` do repo no momento da criação. Se `main` local estiver atrás de `origin/main`, o subagente codificador commita em cima de árvore antiga e o diff fica sujo com "remoção" de tudo que já foi mergeado depois. (Overnight 2026-05-12: 14 worktrees ficaram baseadas em main pré-infra → diffs com 600+ linhas falsas.)
   - Se o `pull --ff-only` falhar (`main` local divergiu): **abortar a sessão** com mensagem clara — humano resolve. **Não force fast-forward, não rebase, não merge automaticamente.**
   - Se `git fetch origin` falhar (sem rede, credencial): seguir com warning no log, mas avisar no relatório final.

> Se a API do devcontext mudar nomes de colunas, filtros ou campos, ajustar esta seção antes de tudo.

## Loop — uma iteração por task

Antes de iniciar cada iteração: se `iteracoes_concluidas >= MAX_ITERATIONS_POR_SESSAO`, encerre com `limite de iterações atingido` e pare.

### Passo 1 — selecionar, capturar contexto e travar

- Pegar a próxima task na ordem definida (To Do primeiro, depois Backlog; por prioridade dentro da coluna).
- Registrar `task_started_at = now()` (epoch seg) para conta de timeout e duração no log.
- Registrar `coluna_origem` (string `"To Do"` ou `"Backlog"`) e capturar `titulo` + `descricao_truncada` direto do item já retornado por `get_tasks`.
- **1.4 Buscar contexto completo da task via helper HTTP**:
  ```powershell
  $tmp = Join-Path $env:TEMP "devctx-task-$task_id.json"
  & powershell -NoProfile -File C:\barra\scripts\get-task.ps1 -TaskId $task_id -OutFile $tmp
  $task_full = Get-Content -Raw -Path $tmp -Encoding utf8 | ConvertFrom-Json
  Remove-Item $tmp -Force
  ```
  Retorna JSON com **todos** os campos: `implementation_plan`, `description` completa, `priority`, `due_date`, `is_blocked`, `tags`. Guardar em `task_full`.
  - **Por que HTTP direto e não MCP**: devcontext-mcp v1.0.7 descarta `implementation_plan` no formatter (bug conhecido — smoke 2026-05-12). API HTTP retorna corretamente.
  - **Sempre via `-OutFile`**: stdout direto sofre mojibake quando PS 5.1 captura via `& powershell ...` por causa do `[Console]::OutputEncoding` cross-process; o helper resolve isso gravando UTF-8 em arquivo.
  - Se o helper retornar exit ≠ 0 (task não encontrada, HTTP falhou, ambíguo): devolver task para `coluna_origem` com `is_blocked:true` e `blocked_reason:"helper get-task falhou: <stderr>"`, emitir `LOG_ITER` com `review_status:"exception"`, seguir.
- **Só agora travar**: `mcp__devcontext__update_task({ task_id, status: "In Progress", comment: "claimed by /processa-fila-barra" })`. Travar depois da captura evita prender uma task se o helper falhar.
- `mcp__devcontext__start_time` para medir.
- Criar marker `C:/barra/.claude/state/awaiting-verification` contendo o ID da task. Esse marker é lido pelo hook `enforce_verification.ps1` — sem ele, o LLM pode declarar terminado prematuramente.
- Se o item retornado por `get_tasks` vier sem título ou sem id (regressão de API): devolver para `coluna_origem` com `is_blocked: true` e `blocked_reason: "regressão get_tasks — item sem id/título"`, emitir `LOG_ITER` com `review_status: "descricao-truncada"`, contar iteração e seguir. **Fail loud, nunca chutar.**

### Passo 2 — planejar com subagente

- **Checagem de timeout** antes de spawnar: se `now() - task_started_at > 2700`, abortar (ver Configuração).
- Ler `task_full.implementation_plan` (capturado no Passo 1.4) e bifurcar:

  **Modo VALIDAR** — `implementation_plan` está preenchido e substantivo (`length > 200`):
  - Spawn `planejador-barra` com prompt que inclui literalmente:
    > O usuário JÁ escreveu este plano de implementação. Sua tarefa é VALIDAR, REFINAR e OPERACIONALIZAR — não criar do zero. Identifique arquivos prováveis com base nas etapas. Quebre em sub-passos se necessário. Marque como `blocked-clarification` SOMENTE se o plano contradiz a arquitetura do projeto (CLAUDE.md, ADRs, CONTEXT.md), referencia arquivos/módulos inexistentes, ou é fisicamente impossível.
  - Anexar ao prompt: título completo, `description` completa (do `task_full`), o `implementation_plan` literal, `priority`, `due_date`.

  **Modo CRIAR** — `implementation_plan` ausente ou < 200 chars:
  - Spawn `planejador-barra` com prompt que inclui literalmente:
    > Plano ausente ou muito curto. Produza o plano com confiança baixa, marque ambiguidades explícitas, prefira `blocked-clarification` sobre chutar requisito não declarado.
  - Anexar ao prompt: título, `description` completa do `task_full`, e o que houver de `implementation_plan` (mesmo curto, pra contexto).

- Receber plano em markdown. O planejador pode devolver **três saídas terminais distintas** (antes mesmo de chegar no codificador):

  | Saída do planejador | Status emitido | Ação no devcontext |
  |---|---|---|
  | `## Aprovação: blocked-clarification` | `blocked-clarification` | `coluna_origem`, `is_blocked:true`, `blocked_reason: <dúvida>` |
  | `## Aprovação: nothing-to-do` | `nothing-to-do` | `Review`, `is_blocked:false`, comentário `"código já implementado, planejador auditou: <evidência>"` |
  | `## Aprovação: human-validation-only` | `human-validation-only` | `Review`, `is_blocked:false`, comentário `"requer validação manual humana: <o que validar>"` |

  Em qualquer dos três casos: remover marker, emitir `LOG_ITER` com o `review_status` correspondente, incrementar contador e seguir para a próxima iteração — **sem spawnar codificador**.

#### Critério estrito de `blocked-clarification`

`blocked-clarification` SÓ é aceitável quando se enquadra em um dos quatro casos:

1. **Plano vazio + descrição vaga**: `implementation_plan` ausente E `description` < 80 chars sem detalhe acionável.
2. **Contradição arquitetural**: plano fere CLAUDE.md, ADR vigente, ou direção de dependência canônica (ex: `dominio/` importando `agente/`).
3. **Referências inexistentes**: plano cita arquivos/módulos/endpoints que não existem no repo (verificável por `Glob`/`Grep`).
4. **Escopo multi-sprint**: > 4 sub-features distintas em contextos diferentes (ex: tocar 3+ bounded contexts mais migration mais frontend mais infra). Nesse caso o planejador deve sugerir split, não bloquear silencioso.

Fora desses quatro casos, o planejador **operacionaliza o plano que o usuário deu** — não bloqueia por estilo, ergonomia, ou dúvida secundária.

#### Critério estrito de `nothing-to-do`

Reservado para tasks que **já estão implementadas em main** — o trabalho descrito no plano existe e está coberto por teste/uso. O planejador comprova com referências concretas (arquivo:linha) no campo `## Evidência`. Não confundir com `human-validation-only`.

Exemplo (overnight 2026-05-12): task `26aae67b` (Modelos: integrar Evolution) tinha plano para implementar fluxo que já vivia em `api/src/barra/dominio/modelos/service.py` há semanas. Caía em `blocked-clarification` por engano; passa a ser `nothing-to-do`.

#### Critério estrito de `human-validation-only`

Reservado para tasks onde o código está pronto, **mas a validação exige humano operando ferramenta externa** que o pipeline não acessa: WhatsApp real, conta Supabase de produção, MinIO produtivo, pagamento Pix real, etc. O planejador descreve no campo `## Como validar` exatamente o que o humano precisa fazer. Não inclui validações que Playwright local resolve.

### Passo 3 — rotear o codificador

**Checagem de timeout** antes de spawnar: se `now() - task_started_at > 2700`, abortar.

Decidir baseado nos arquivos prováveis listados pelo plano:

- Tocou `api/` → `codificador-api`.
- Tocou `interface/` → `codificador-interface`.
- Tocou `infra/sql/` → `migrador-sql`.
- Tocou múltiplas áreas → executar em sequência na **mesma branch/worktree**, ordem ditada pelo plano (migrations primeiro quando houver).

Spawn: `Agent({ subagent_type: <codificador>, isolation: "worktree", description: "Implement task <id>", prompt: <plano completo> })`. Capturar branch, hash do commit, output literal de testes/lint.

### Passo 4 — revisar

- **Checagem de timeout** antes de spawnar: se `now() - task_started_at > 2700`, abortar.
- `Agent({ subagent_type: "revisor-barra", description: "Review task <id>", prompt: <plano + diff resumido + branch + hash> })`.
- Se `## Aprovação: FAIL`: voltar a task para `coluna_origem` no devcontext (`update_task({ status: <coluna_origem>, is_blocked: true, blocked_reason: <resumo dos achados> })`), remover marker, emitir `LOG_ITER` com `review_status: "needs-rework"`, contar iteração, seguir para a próxima. **Máximo 1 retry no mesmo problema** — não entre em loop de fix.
- Se `## Aprovação: PASS`: continuar.

### Passo 5 — marcar review

- `mcp__devcontext__update_task({ task_id, status: "Review", comment: <branch + hash + resumo em 3 linhas + caminho do worktree + resumo do `## Achados`/`## Sugestões opcionais` do revisor> })`.
- `mcp__devcontext__stop_time`.
- Remover marker `C:/barra/.claude/state/awaiting-verification`.
- Marcar entrada correspondente em `TaskList` como `completed`.
- Incrementar `iteracoes_concluidas`.
- Emitir **log JSON estruturado** (ver seção abaixo) com `review_status: "PASS"`.

### Passo 6 — próxima iteração

- Se `iteracoes_concluidas >= MAX_ITERATIONS_POR_SESSAO`: encerre limpo, relate `limite de iterações atingido`, pare. **Não reagende.**
- Se a fila concatenada acabou: relate `fila vazia, encerrando` e pare. **Não reagende.**
- Caso contrário: continue dentro da mesma execução do skill (sem `ScheduleWakeup`) — o orquestrador overnight controla o tempo entre execuções, e ficar parado em sleep aqui é desperdício de janela.

## Log estruturado por iteração

**Contrato inviolável**: toda iteração que tocou uma task (ou seja, passou do Passo 1 a partir do `update_task → In Progress`) **deve** emitir exatamente uma linha `LOG_ITER` antes de seguir para a próxima ou encerrar a sessão. Sem exceção, mesmo em erro inesperado.

Caminhos terminais cobertos (emit obrigatório em cada um):

| Onde | `review_status` | Notas |
|---|---|---|
| Passo 5 — review PASS | `PASS` | Caminho feliz; task → `Review` |
| Passo 4 — revisor FAIL | `needs-rework` | Task volta para `coluna_origem`, `is_blocked:true` |
| Passo 2 — planejador devolve `blocked-clarification` | `blocked-clarification` | Cobre os 4 casos estritos (ver Critério estrito acima); task volta para `coluna_origem` |
| Passo 2 — planejador devolve `nothing-to-do` | `nothing-to-do` | Trabalho já existe em main; task → `Review` com evidência (arquivo:linha) |
| Passo 2 — planejador devolve `human-validation-only` | `human-validation-only` | Código pronto, validação só com ferramenta externa (WhatsApp/Supabase prod); task → `Review` com instruções pro humano |
| Timeout em qualquer passo | `timeout` | Task volta para `coluna_origem`, `is_blocked:true` |
| Passo 1 — regressão de `get_tasks` (sem id/título) | `descricao-truncada` | Caminho residual; descrição truncada normal NÃO cai aqui (vira `blocked-clarification` via planejador) |
| Erro inesperado / exceção / abort de subagente | `exception` | Inclui mensagem em `erro` (até 200 chars); task volta para `coluna_origem` com `is_blocked:true` e `blocked_reason:"exception: <msg>"` |

Formato:

```json
{"ts":"<ISO-8601 UTC>","task_id":"<uuid>","titulo":"<até 80 chars>","codificador_usado":"<api|interface|sql|none>","branch":"<nome ou null>","hash":"<curto ou null>","review_status":"PASS|needs-rework|blocked-clarification|nothing-to-do|human-validation-only|timeout|descricao-truncada|exception","duracao_seg":<int>,"erro":"<opcional, só em exception>"}
```

A linha deve ser autocontida (parseável com `ConvertFrom-Json` por linha) e prefixada com `LOG_ITER ` para ser extraível por `Select-String -Pattern '^LOG_ITER '`. Exemplo:

```
LOG_ITER {"ts":"2026-05-13T03:14:08Z","task_id":"26aae67b-...","titulo":"Modelos: integrar Evolution","codificador_usado":"interface","branch":"feat/modelos-evolution-conexao","hash":"a1b2c3d","review_status":"PASS","duracao_seg":612}
```

**Padrão de tratamento de exceção** (envolve Passos 1-5):
- Capture qualquer erro inesperado (subagente cai, MCP devcontext rejeita, hook falha, etc.).
- Reverta o estado: se o `update_task → In Progress` já foi feito, volte para `coluna_origem` com `is_blocked:true` e `blocked_reason:"exception: <msg curta>"`; remova o marker.
- Emita `LOG_ITER` com `review_status:"exception"` e o campo `erro`.
- Incremente o contador e siga para a próxima iteração — **não derrube a sessão inteira por erro de uma task**.

## Regras invioláveis

- **Sem merge, sem push, sem PR automático.** Status terminal = `Review` no devcontext. Humano decide o resto.
- **Sem `--no-verify`, sem `--no-gpg-sign`, sem `-c commit.gpgsign=false`.** Os hooks bloqueiam, mas reforce na instrução enviada aos codificadores.
- **Sem destrutivos em git** (`reset --hard`, `branch -D`, `checkout .`, `restore .`, `clean -f`, `push --force`) sem aprovação humana.
- **Worktree obrigatório por task** (`isolation: "worktree"`) — falha em uma task não contamina as outras.
- **Coluna `In Progress` é intocável.** Tasks ali pertencem ao Rafael; o pipeline nunca seleciona, atualiza ou comenta nelas.
- **Fail loud**: ambiguidade de requisito → devolver task para coluna de origem com `is_blocked: true` + `blocked_reason`, **nunca** chutar interpretação. Plano `blocked-clarification` segue a mesma regra.
- **Sem editar `CLAUDE.md`, `CONTEXT.md`, `.claude/agents/*`** dentro do loop — esses arquivos são governados pelo humano.

## Relatório por iteração (no chat principal, 4 linhas + 1 log)

```
- Task: <id> — <título>
- Branch: <nome> @ <hash curto>
- Revisor: PASS / FAIL — <motivo se FAIL>
- Próxima: <id ou "fila vazia, encerrando" ou "limite de iterações atingido">
LOG_ITER {"ts":...}
```

## Trade-offs deste design

- **Sem `ScheduleWakeup` entre iterações dentro da mesma sessão**: a sessão fica acordada drenando até o limite. Quem dá respiro entre sessões é o orquestrador overnight (`scripts/overnight-loop.ps1`), que faz sleep 30s entre runs.
- **Worktrees isolados por task**: testes/lint de uma task não derrubam outras; custo é disco e setup mais lento por iteração — aceitável para drenar fila sem ruído.
- **Status `Review` sempre humano**: blast radius controlado. Pipeline pode rodar de madrugada sem risco de merge ruim.
- **1 retry máximo**: protege contra loop infinito de fix; o custo é tasks que poderiam ser salvas com mais 1 tentativa voltarem com `is_blocked: true`. Aceito.
- **Limite duro de 20 iterações por sessão e 45min por task**: protege contra runaway overnight. Em 20 tasks * 45min = 15h pior caso por sessão — na prática o overnight roda em ~3-5h por sessão drenando a fila inteira.
