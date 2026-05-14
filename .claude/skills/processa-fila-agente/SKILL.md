---
name: processa-fila-agente
description: Drena a fila de marcos pendentes (colunas "To Do" + "Backlog") da fila YAML do agente em docs/agente/fila-agente.yml em loop autonomo Plan->Code->Review->Eval, atualizando cada marco para "Review" e encerrando ao esvaziar a fila. Use quando o usuario pedir para processar a fila do agente ou digitar /processa-fila-agente.
---

# processa-fila-agente

## Visao geral

Loop autonomo que drena a fila do **agente LangGraph** (`api/src/barra/agente/` + `api/evals/`). Para cada marco: pesquisar contexto tecnico, planejar, implementar, revisar, **rodar evals com gate de regressao**, marcar Review com branch e hash. Sem merge, sem push, sem PR -- status terminal eh `Review` na fila YAML (humano fecha o ciclo via merge manual em `main`).

Diferenca-chave vs `processa-fila-barra`:
- Fonte da fila eh **YAML versionado em git** (`docs/agente/fila-agente.yml`), nao MCP devcontext.
- **Passo 0.5 (pesquisador)**: antes do planejador, spawnar `pesquisador-langgraph` para anexar nota tecnica (padroes LangGraph, prompt caching, evals) ao prompt do planejador.
- **Passo 4.5 (eval-runner)**: depois do revisor PASS, spawnar `eval-runner-agente` para gate de regressao contra `.claude/state/evals-baseline.json`. Regressao reprova mesmo com revisor PASS.

## Configuracao -- limites de safety

- `MAX_ITERATIONS_POR_SESSAO = 7` -- ha 7 marcos (M0..M6); cabe em uma sessao no pior caso, mas overnight roda em multiplas.
- `TIMEOUT_POR_MARCO_SEGUNDOS = 3600` (60min). M3 e M5 sao maiores (coordenador + midia) -- 45min pode estourar. Compare `now() - marco_started_at` antes de cada handoff (Plan->Code, Code->Review, Review->Eval).
- `RETENCAO_PLANOS_DIAS = 7` -- `.claude/state/plans-agente/*.md` e `.claude/state/research/*.md` com mtime > 7 dias removidos no Passo 0.

### Modo dry-run (`BARRA_PIPELINE_DRY_RUN=1`)

Setada pelo orquestrador `scripts/overnight-agente.ps1 -DryRun`. Comportamento:

- **Pesquisa, Plan, Code, Review e Eval rodam normalmente**, com mesmas worktrees e mesmos subagentes.
- **Pular toda escrita em `docs/agente/fila-agente.yml`**: o marco NAO troca de coluna, NAO recebe `branch`, NAO recebe `hash`. O eval-runner pode atualizar `.claude/state/evals-baseline.json` se passou (manter, eh estado runtime fora do versionado da fila).
- **`LOG_ITER_AGENTE` emitido normalmente**, com campo extra `"dry_run": true` e `review_status` que seria aplicado. Branch e hash continuam reais.
- **Plano (`plans-agente/`), nota de pesquisa (`research/`) e diff** continuam persistidos -- objetivo eh inspecionar o que o pipeline produziria sem mexer no estado canonico.

Leia o env var **uma vez no inicio da sessao** (`dry_run = (env BARRA_PIPELINE_DRY_RUN == "1")`).

## Schema da fila YAML

`docs/agente/fila-agente.yml` (gerado por `scripts/gera-fila-agente.ps1`):

```yaml
schema_version: 1
filas:
  - id: "m0"
    titulo: "Skeleton do grafo"
    coluna: "Backlog" | "To Do" | "In Progress" | "Review" | "Done"
    priority: "high"
    depends_on: ["m..."]
    eval_required: true|false
    eval_config:
      suites: ["canonicos/leitura", "adversariais/disclosure"]
      threshold: 0.85
      metric: "cache_hit_rate"  # opcional
      per_category: true        # opcional, gate >=threshold em CADA suite
    implementation_plan: |
      (texto markdown do roteiro)
```

**Regras de elegibilidade:**
- Marcos elegiveis: `coluna in ("To Do", "Backlog")`.
- **`depends_on` deve estar 100% em `Review` ou `Done`** antes do marco virar elegivel. Se algum dep esta em `Backlog`/`To Do`/`In Progress`, pula -- nao adianta processar M3 com M1 ainda Backlog.
- Ordem: `To Do` antes de `Backlog`; dentro de cada coluna, ordem do arquivo (M0..M6).
- `In Progress` eh intocavel (mesmo padrao do processa-fila-barra; pode ser sessao paralela do humano).

## Passo 0 -- Cleanup de estado stale (idempotente, fail-safe)

Identico ao processa-fila-barra adaptado ao escopo do agente:

1. **Marker zumbi**: se `.claude/state/awaiting-verification-agente` existe E mtime > 1h, remover e logar `WARN: marker awaiting-verification-agente zumbi removido (marco <id>, mtime <ts>)`.
2. **Planos antigos**: `.claude/state/plans-agente/*.md` com mtime > `RETENCAO_PLANOS_DIAS` -> remover.
3. **Notas de pesquisa antigas**: `.claude/state/research/*.md` com mtime > `RETENCAO_PLANOS_DIAS` -> remover.
4. **Baseline malformado**: tentar `ConvertFrom-Json` em `.claude/state/evals-baseline.json`; se falhar, renomear para `.broken-<ts>` e seguir (proxima eval cria baseline limpo).

## Contexto inicial (uma vez por sessao)

1. Verificar que `docs/agente/fila-agente.yml` existe. Se nao: chamar `scripts/gera-fila-agente.ps1 -PreserveStatus` e tentar de novo. Se ainda nao: abortar com mensagem clara.
2. Parsear YAML (regex tolerante, sem dependencia de modulo YAML em PS 5.1). Extrair lista de marcos com campos: `id`, `titulo`, `coluna`, `priority`, `depends_on`, `eval_required`, `eval_config`, `implementation_plan`.
3. **Filtrar elegiveis**: coluna in (`To Do`, `Backlog`) E todos `depends_on` resolvidos (in (`Review`, `Done`)).
4. Ordenar: `To Do` primeiro, depois `Backlog`; dentro de cada coluna ordem natural do YAML (M0->M6).
5. Se fila elegivel vazia: relatar `fila vazia, encerrando` e parar **IMEDIATAMENTE**. **Nao reagendar, nao ScheduleWakeup.**
6. `TaskCreate` interno uma vez por marco da fila (ate `MAX_ITERATIONS_POR_SESSAO`).
7. `iteracoes_concluidas = 0`.
8. **Sincronizar `main` local com `origin/main`** (igual processa-fila-barra):
   ```bash
   git fetch origin && git checkout main && git pull --ff-only origin main
   ```
   Falha em `pull --ff-only` -> abortar sessao (humano resolve). Falha em `fetch` -> warning, segue.
9. Garantir que `.claude/state/plans-agente/`, `.claude/state/research/` existem (mkdir -p).
10. Carregar `.claude/state/evals-baseline.json` (ou criar com `{}` se nao existe -- baseline vazio = primeiro run define).

## Loop -- uma iteracao por marco

Antes de cada iteracao: se `iteracoes_concluidas >= MAX_ITERATIONS_POR_SESSAO`, encerre com `limite de iteracoes atingido`.

### Passo 1 -- selecionar, capturar contexto e travar

- Pegar proximo marco elegivel.
- Registrar `marco_started_at = now()` (epoch seg).
- Capturar do YAML: `id`, `titulo`, `coluna_origem`, `priority`, `depends_on`, `eval_required`, `eval_config`, `implementation_plan` (integral).
- **Travar**: editar `docs/agente/fila-agente.yml` mudando `coluna` deste marco para `"In Progress"` (in-place via regex line-by-line; commitar a mudanca em commit separado `chore(agente): claim m<n>`).
- Criar marker `.claude/state/awaiting-verification-agente` contendo o `id` do marco.
- Gravar `.claude/state/agente-task-started-at` com epoch.
- Em qualquer falha aqui (YAML write falha, marker falha): emitir `LOG_ITER_AGENTE` com `review_status: "exception"` e seguir.

### Passo 0.5 -- pesquisador-langgraph

- **Checagem de timeout** antes de spawnar.
- Spawn `pesquisador-langgraph` com prompt incluindo:
  - `id` e `titulo` do marco
  - `implementation_plan` integral
  - Lista de docs relevantes: `docs/agente/01-arquitetura.md`, `02-estado-fluxo.md`, `03-prompts.md`, `04-tools.md`, `09-roteiro.md`, etc. (filtra pelo conteudo do plano)
  - ADRs aplicaveis (`docs/adr/`)
  - Instrucao: "Produza nota tecnica `.claude/state/research/<id>.md` com padroes idiomaticos, exemplos minimos, armadilhas conhecidas. Cite fontes (link ou arquivo:linha). NAO escreva codigo."
- Receber path da nota (string `.claude/state/research/<id>.md`). Se vazio (sem material util), seguir mesmo assim -- pesquisa eh defesa, nao pre-requisito.

### Passo 2 -- planejador-agente

- **Checagem de timeout** antes de spawnar.
- Spawn `planejador-agente` (variante de planejador-barra para agente/) com prompt incluindo:
  - `implementation_plan` literal do YAML (sempre em modo VALIDAR -- humano ja curou no roteiro).
  - Conteudo da nota de pesquisa em `.claude/state/research/<id>.md` (se existir).
  - Lista de docs: `api/src/barra/agente/CLAUDE.md`, `docs/agente/*.md` referenciados, ADRs.
- Persistir plano em `.claude/state/plans-agente/<id>.md`.
- Saidas terminais identicas ao planejador-barra (`ready` | `blocked-clarification` | `nothing-to-do` | `human-validation-only`). Mesmo tratamento.

### Passo 3 -- codificador-api

- **Checagem de timeout** antes de spawnar.
- Roteamento: marcos do agente quase sempre tocam `api/src/barra/agente/` + `api/tests/` + `api/evals/`. Default: `codificador-api`. Excecao: se plano explicitamente menciona `infra/sql/` (M0 pre-req: 0012/0013/0014 ja aplicados; M3+ pode adicionar tabelas) -> roteia para `migrador-sql` antes do `codificador-api`.
- Spawn em worktree isolada (`isolation: "worktree"`).
- Capturar branch, hash, output literal de `make lint`, `make test`, `make typecheck`.

### Passo 4 -- revisor-barra

- **Checagem de timeout** antes de spawnar.
- Spawn `revisor-barra` com plano + research + diff + branch + hash.
- **Skills extras a invocar para diffs do agente** (adiciona aos ja listados em revisor-barra.md):
  - `claude-api` (prompt caching, thinking, effort, structured output)
  - `simplify` (sempre)
  - `supabase-postgres-best-practices` (se diff toca SQL)
  - `langchain-skills` / `langsmith-skills` (se instalados publicamente -- ver `.claude/agente-pipeline.md`)
- Se FAIL: voltar `coluna` no YAML para `coluna_origem`, registrar `is_blocked: true` no comentario do commit de revert, emitir `LOG_ITER_AGENTE` com `review_status: "needs-rework"`, contar iteracao, seguir.
- Se PASS: continuar.

### Passo 4.5 -- eval-runner-agente (gate de regressao)

**Aplica somente se `eval_required: true` no YAML do marco.**

- **Checagem de timeout** antes de spawnar.
- Spawn `eval-runner-agente` com:
  - `id` do marco, `eval_config` integral
  - Caminho da baseline (`.claude/state/evals-baseline.json`)
  - Branch + hash do codificador
- Eval-runner roda `scripts/roda-evals.ps1` no worktree, mede pass-rate por suite/rubrica, compara com baseline.
- Decisao do eval-runner:
  - `## Resultado: PASS` (todas as rubricas >= threshold E sem regressao > 5%) -> seguir, **atualiza baseline** em `.claude/state/evals-baseline.json`.
  - `## Resultado: FAIL` (qualquer rubrica abaixo de threshold OU regressao > 5%) -> voltar marco para `coluna_origem`, `is_blocked: true`, emitir `LOG_ITER_AGENTE` com `review_status: "eval-failed"`, **nao atualiza baseline**.
  - `## Resultado: SKIP` (suite vazia, baseline vazio) -> seguir, **inicializa baseline** com valores observados.
- Falha do proprio runner (exception, timeout) -> emitir warning, seguir como SKIP (nao bloquear progresso por bug de tooling).

### Passo 5 -- marcar Review

- Editar `docs/agente/fila-agente.yml`: muda `coluna` do marco de `In Progress` para `"Review"`, commitar `chore(agente): review m<n>` com mensagem incluindo branch + hash + resumo do revisor + pass-rate do eval-runner.
- Remover marker `.claude/state/awaiting-verification-agente`.
- Remover `.claude/state/agente-task-started-at`.
- Marcar entrada `TaskList` interna como `completed`.
- `iteracoes_concluidas += 1`.
- Emitir `LOG_ITER_AGENTE` com `review_status: "PASS"`.

### Passo 6 -- proxima iteracao

- Se `iteracoes_concluidas >= MAX_ITERATIONS_POR_SESSAO`: encerre limpo, relate `limite atingido`, **nao reagende**.
- Se fila elegivel acabou: relate `fila vazia, encerrando` e pare.
- Senao: continue dentro da mesma execucao do skill (overnight controla respiro entre sessoes).

## Log estruturado por iteracao

Prefixo `LOG_ITER_AGENTE ` (distinto do `LOG_ITER ` do processa-fila-barra). Formato JSON unilinha:

```json
{"ts":"<ISO-8601 UTC>","marco_id":"m0..m6","titulo":"<ate 80 chars>","branch":"<nome ou null>","hash":"<curto ou null>","review_status":"PASS|needs-rework|eval-failed|blocked-clarification|nothing-to-do|human-validation-only|timeout|exception","duracao_seg":<int>,"plano_path":"<rel ou null>","research_path":"<rel ou null>","eval_summary":{"pass_rate":<float>,"regressoes":[]} | null,"erro":"<so em exception>"}
```

Caminhos terminais:

| Onde | review_status | Notas |
|---|---|---|
| Passo 5 -- PASS | `PASS` | Marco -> Review no YAML; baseline atualizado se eval rodou |
| Passo 4 -- revisor FAIL | `needs-rework` | Marco volta a coluna_origem |
| Passo 4.5 -- eval-runner FAIL | `eval-failed` | Marco volta a coluna_origem com pass-rate observado |
| Passo 2 -- blocked-clarification | `blocked-clarification` | Marco volta a coluna_origem |
| Passo 2 -- nothing-to-do | `nothing-to-do` | Marco vai pra Review (raro com fila YAML curada) |
| Passo 2 -- human-validation-only | `human-validation-only` | Marco vai pra Review |
| Timeout em qualquer passo | `timeout` | Marco volta a coluna_origem |
| Exception | `exception` | Marco volta a coluna_origem, campo `erro` populado |

Exemplo:

```
LOG_ITER_AGENTE {"ts":"2026-05-13T03:14:08Z","marco_id":"m1","titulo":"Tools de leitura","branch":"feat/agente-m1-tools-leitura","hash":"a1b2c3d","review_status":"PASS","duracao_seg":1842,"plano_path":".claude/state/plans-agente/m1.md","research_path":".claude/state/research/m1.md","eval_summary":{"pass_rate":0.91,"regressoes":[]}}
```

## Regras invioláveis

- **Sem merge, sem push, sem PR automatico.** Status terminal = `Review` no YAML.
- **Sem `--no-verify`, sem `--no-gpg-sign`.**
- **Sem destrutivos em git** sem aprovacao humana.
- **Worktree obrigatorio por marco** (`isolation: "worktree"`).
- **Coluna `In Progress` so eh tocada pelo proprio pipeline** (Passo 1 trava, Passo 5/4/4.5 destrava). Humano editando In Progress -> conflito de merge -> pipeline aborta a iteracao e devolve.
- **Sem editar `CLAUDE.md`, `CONTEXT.md`, `docs/adr/`, `.claude/agents/*`, `.claude/skills/*`** dentro do loop.
- **Paths relativos sempre** em prompts dos subagentes.
- **Eval gate eh autoridade final**: revisor PASS + eval FAIL = marco volta para `coluna_origem`. Build verde nao supera regressao de prompt.

## Relatorio por iteracao (no chat principal, 5 linhas + 1 log)

```
- Marco: <id> -- <titulo>
- Branch: <nome> @ <hash curto>
- Revisor: PASS / FAIL -- <motivo>
- Eval: PASS (pass-rate 0.XX, sem regressao) / FAIL (X rubricas abaixo de threshold) / SKIP
- Proximo: <id ou "fila vazia" ou "limite atingido">
LOG_ITER_AGENTE {"ts":...}
```

## Trade-offs deste design

- **YAML como fila** evita dependencia de devcontext MCP. Custo: status do marco vai pro git (commits `chore(agente): claim m<n>` poluem historico). Beneficio: rastreavel, branchable, reverte com `git revert`.
- **Eval gate apos revisor** duplica trabalho em parte (revisor le diff, eval roda codigo) mas pega classes de bug distintas: revisor pega anti-padroes estaticos; eval pega regressao comportamental.
- **Pesquisador antes do planejador**: custo de tokens; beneficio: planejador erra menos em territorio desconhecido (LangGraph, prompt caching).
- **Baseline em arquivo JSON commitado**: simples; pode dar conflito de merge se duas sessoes paralelas atualizam. Aceitavel para single-dev P0.
- **Limite duro 7 iteracoes/sessao**: garante que overnight nao tenta tudo de uma vez; cada sessao foca em 1-3 marcos.
