---
name: processa-fila-barra
description: Drena a fila de tasks pendentes (coluna "To Do") do projeto barravips no devcontext em loop autônomo Plan→Code→Review, atualizando cada task para "Review" e pausando ao esvaziar a fila. Use quando o usuário pedir para processar a fila do barravips ou digitar /processa-fila-barra.
---

# processa-fila-barra

## Visão geral

Loop autônomo que drena a fila do projeto `barravips` no devcontext. Para cada task: planejar com `planejador-barra`, implementar com o codificador da área, revisar com `revisor-barra`, marcar `Review` com branch e hash. Sem merge, sem push, sem PR — o status terminal é sempre `Review` (humano fecha o ciclo).

## Schema do devcontext (descoberto em smoke)

- Colunas reais do projeto `BarraVIPs` (case-sensitive, com espaços): `Backlog`, `To Do`, `In Progress`, `Review`, `Done`.
- `mcp__devcontext__get_tasks` filtra pela coluna passada em `status` (nome exato da coluna). **Truncamento conhecido**: o campo de descrição volta cortado com `…` (~150 chars).
- **`mine=true` é o padrão e mascara a fila inteira.** Tasks do BarraVIPs ficam atribuídas a Rafael (e outros responsáveis), não ao usuário autenticado deste pipeline (`ProcexAI`) — sem `mine=false` explícito, `get_tasks` devolve zero tasks e o loop encerra como falsa "fila vazia".

## Contexto inicial (uma vez por sessão)

1. Confirmar que `mcp__devcontext__get_tasks` e `mcp__devcontext__update_task` estão acessíveis. Se faltar, abortar com mensagem clara.
2. **Descobrir o nome real da coluna pendente** antes de filtrar (defensivo contra renomeação):
   - Chamar `mcp__devcontext__get_tasks({ mine: false })` uma vez sem `status`.
   - Coletar todos os nomes únicos de coluna do retorno.
   - Escolher a primeira coluna que case (case-insensitive) com `to do`, `todo`, `pending` ou `backlog`. Cair para `To Do` literal se nada casar e logar aviso.
3. Listar tasks pendentes: `mcp__devcontext__get_tasks({ mine: false, status: "<nome descoberto>" })`. **Sempre passar `mine: false`** — sem isso, get_tasks filtra pelo usuário autenticado e a fila parece vazia.
4. **Inspecionar o schema do retorno antes de presumir nomes de campos** (`id`, `title`, `priority`, `status`/`column_name` podem variar de versão para versão).
5. Se a fila filtrada estiver vazia: relatar `fila vazia, encerrando` e parar. **NÃO reagendar**.
6. Criar tracking interno chamando `TaskCreate` uma vez por task da fila — assim o progresso fica visível sem poluir o devcontext.

> Se a API do devcontext mudar nomes de colunas, filtros ou campos, ajustar esta seção antes de tudo.

## Loop — uma iteração por task

### Passo 1 — selecionar, travar e obter descrição completa

- Pegar a task de maior prioridade (campo conforme inspecionado).
- `mcp__devcontext__update_task({ task_id, status: "In Progress", comment: "claimed by /processa-fila-barra" })` — esta chamada tem efeito colateral útil: **retorna o registro da task atualizado, do qual extraímos a descrição completa** (a versão truncada de `get_tasks` é insuficiente para o planejador).
- **Por que aqui e não em `get_context` ou `vault_read`?** Smoke 2026-05-12: `vault_read` espera `path` de artigo do vault (não aceita ID de task — retorna `Erro ao ler artigo`); `get_context` só retorna tasks atribuídas ao usuário autenticado (fila do BarraVIPs está atribuída a Rafael, não a ProcexAI, então vem vazia). O retorno de `update_task` após o travamento é o único caminho que dá a descrição completa pelo ID. Se o devcontext expuser um `get_task(id)` direto no futuro, migrar para ele e remover este workaround.
- Se o retorno do `update_task` não contiver descrição completa (campo truncado ou ausente): `update_task({ status: "To Do", is_blocked: true, blocked_reason: "descrição truncada — ajustar pipeline" })` e seguir para a próxima. **Fail loud, nunca chutar.**
- `mcp__devcontext__start_time` para medir.
- Criar marker `C:/barra/.claude/state/awaiting-verification` contendo o ID da task. Esse marker é lido pelo hook `enforce_verification.ps1` — sem ele, o LLM pode declarar terminado prematuramente.

### Passo 2 — planejar com subagente

- `Agent({ subagent_type: "planejador-barra", description: "Plan task <id>", prompt: <título + descrição completa capturada no Passo 1 + critérios verificáveis solicitados> })`.
- Receber plano em markdown. Se vier `blocked-clarification`, devolver a task para `To Do` com `is_blocked: true` e `blocked_reason` citando a dúvida do planejador, remover marker, e seguir para a próxima — **não invente resposta**.

### Passo 3 — rotear o codificador

Decidir baseado nos arquivos prováveis listados pelo plano:

- Tocou `api/` → `codificador-api`.
- Tocou `interface/` → `codificador-interface`.
- Tocou `infra/sql/` → `migrador-sql`.
- Tocou múltiplas áreas → executar em sequência na **mesma branch/worktree**, ordem ditada pelo plano (migrations primeiro quando houver).

Spawn: `Agent({ subagent_type: <codificador>, isolation: "worktree", description: "Implement task <id>", prompt: <plano completo> })`. Capturar branch, hash do commit, output literal de testes/lint.

### Passo 4 — revisar

- `Agent({ subagent_type: "revisor-barra", description: "Review task <id>", prompt: <plano + diff resumido + branch + hash> })`.
- Se `## Aprovação: FAIL`: voltar a task para `To Do` no devcontext (`update_task({ status: "To Do", is_blocked: true, blocked_reason: <resumo dos achados> })`), remover marker, seguir para a próxima. **Máximo 1 retry no mesmo problema** — não entre em loop de fix.
- Se `## Aprovação: PASS`: continuar.

### Passo 5 — marcar review

- `mcp__devcontext__update_task({ task_id, status: "Review", comment: <branch + hash + resumo em 3 linhas + caminho do worktree + resumo do `## Achados`/`## Sugestões opcionais` do revisor> })`.
- `mcp__devcontext__stop_time`.
- Remover marker `C:/barra/.claude/state/awaiting-verification`.
- Marcar entrada correspondente em `TaskList` como `completed`.

### Passo 6 — próxima iteração

- `ScheduleWakeup({ delaySeconds: 90, prompt: "/processa-fila-barra" })` para reentrar no skill. 90s mantém o cache do Anthropic quente (TTL 5min) e dá folga para a Evolution API/Supabase respirarem entre lotes.

## Regras invioláveis

- **Sem merge, sem push, sem PR automático.** Status terminal = `Review` no devcontext. Humano decide o resto.
- **Sem `--no-verify`, sem `--no-gpg-sign`, sem `-c commit.gpgsign=false`.** Os hooks bloqueiam, mas reforce na instrução enviada aos codificadores.
- **Sem destrutivos em git** (`reset --hard`, `branch -D`, `checkout .`, `restore .`, `clean -f`, `push --force`) sem aprovação humana.
- **Worktree obrigatório por task** (`isolation: "worktree"`) — falha em uma task não contamina as outras.
- **Fail loud**: ambiguidade de requisito → devolver task para `To Do` com `is_blocked: true` + `blocked_reason`, **nunca** chutar interpretação. Plano `blocked-clarification` segue a mesma regra.
- **Sem editar `CLAUDE.md`, `CONTEXT.md`, `.claude/agents/*`** dentro do loop — esses arquivos são governados pelo humano.

## Relatório por iteração (no chat principal, 4 linhas)

```
- Task: <id> — <título>
- Branch: <nome> @ <hash curto>
- Revisor: PASS / FAIL — <motivo se FAIL>
- Próxima: <id ou "fila vazia, encerrando">
```

## Trade-offs deste design

- **90s entre iterações**: cache do Anthropic quente (TTL 5min); ainda dá tempo de a fila ser editada por fora.
- **Worktrees isolados por task**: testes/lint de uma task não derrubam outras; custo é disco e setup mais lento por iteração — aceitável para drenar fila sem ruído.
- **Status `Review` sempre humano**: blast radius controlado. Pipeline pode rodar de madrugada sem risco de merge ruim.
- **1 retry máximo**: protege contra loop infinito de fix; o custo é tasks que poderiam ser salvas com mais 1 tentativa voltarem para `To Do` com `is_blocked: true`. Aceito.
