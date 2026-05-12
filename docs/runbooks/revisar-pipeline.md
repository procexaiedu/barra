# Runbook — Revisar o pipeline autônomo Barra Vips

Como revisar, validar localmente e mergear o trabalho deixado em `Review` pelo `/processa-fila-barra` (overnight ou ad-hoc).

> Pré-requisito: o pipeline produz branches em `feat/*` ou `fix/*` e move a task do devcontext para a coluna `Review`. Nada sobe sozinho.

## Fluxo

```
+----------+        +-------------+        +-------------+        +----------+
| overnight| -----> | task Review | -----> | revisão     | -----> | merge em |
| (drena   |        | + branch    |        | humana      |        | main     |
|  fila)   |        | + worktree  |        | (este doc)  |        |          |
+----------+        +-------------+        +-------------+        +----------+
                          |                       |
                          v                       v
                 .claude/worktrees/      rebase + pnpm dev
                 agent-<hash>/           + smoke manual
```

## Passo a passo

### 1. Achar o que precisa revisar

```bash
# Status do overnight mais recente (PASS / rework / blocked / nothing-to-do / human-validation-only)
powershell -NoProfile -File scripts\overnight-status.ps1
```

Cada linha PASS tem `task_id | duração | branch | título`. Use a branch para os próximos passos.

### 2. Atualizar main antes de rebase

```bash
git checkout main
git fetch origin
git pull --ff-only origin main
```

> Falhou em `pull --ff-only`? Sua main divergiu. **Não force** — investigue o que está local e não-pushed. Geralmente é commit manual residual.

### 3. Rebase da branch contra main fresh

A branch nasceu de algum HEAD antigo do main (overnight pode ter rodado antes de commits de infra). Rebase resolve o ruído de diff falso:

```bash
git checkout <branch-do-pipeline>
git rebase main
# Se houver conflito real: resolva manualmente. Se for só conflito de NNNN
# em infra/sql/, renomeie o .sql para o próximo livre (ver scripts/proxima-migration.ps1).
```

### 4. Copiar `.env` se for tela autenticada

Worktrees nascem sem `.env`. Se a branch toca `interface/`, o dev server cai em redirect pra `/login` sem as chaves do Supabase:

```bash
cp interface/.env interface/.env  # já está no lugar se você não está numa worktree
# Se você foi para uma worktree (cd .claude/worktrees/agent-<hash>):
cp C:/barra/interface/.env interface/.env
```

> `.env` é gitignored. Nunca commit.

### 5. Validar localmente

| Tipo de mudança | Comandos |
|---|---|
| Backend (`api/`) | `cd api && make test && make lint` |
| Frontend (`interface/`) | `cd interface && pnpm lint && pnpm build && pnpm dev` (abrir no navegador) |
| Migration (`infra/sql/`) | aplicar contra DB dev: `make migrate` em `api/` com `DATABASE_URL` apontando para dev |
| Transversal | rodar os três acima em ordem migration → backend → frontend |

Para mudanças de UI: rode `pnpm dev`, navegue na rota afetada, confira console sem erros, e teste o golden path do que foi pedido. O screenshot da pasta `.playwright-evidence/` do worktree é referência, não prova — repita você mesmo.

### 6. Comparar com o que o devcontext disse

A task em `Review` carrega o resumo do revisor no `comment`. Confirme:
- O escopo bate com o `implementation_plan` original?
- Os arquivos tocados são razoáveis (sem refactor adjacente)?
- Os testes que o codificador rodou existem e são significativos?

Se algo parece fora: **devolva a task para `To Do` no devcontext** com `is_blocked: true` e motivo. Não force merge.

### 7. Mergear

```bash
# Volte para main, faça squash merge ou merge --ff conforme o projeto pede
git checkout main
git merge --ff-only <branch-do-pipeline>   # ou squash se preferir
git push origin main
```

Mova a task para `Done` no devcontext após o push.

### 8. Limpar worktrees mergeadas

Depois de mergear uma porção de branches, libere o disco:

```bash
# Dry-run primeiro
powershell -NoProfile -File scripts\cleanup-merged-worktrees.ps1

# Execute para remover
powershell -NoProfile -File scripts\cleanup-merged-worktrees.ps1 -Execute

# Se algum worktree estiver travado por file lock (node.exe residual):
powershell -NoProfile -File scripts\cleanup-merged-worktrees.ps1 -Execute -Force
```

## 6 gotchas conhecidos

1. **Worktrees nascem de main antigo.** Se o overnight rodou às 02:05 e você commitou infra às 23:00 do dia anterior, as 20 worktrees do overnight não têm essa infra. Sempre rebase contra `origin/main` fresh antes de avaliar diff.
2. **`.env` ausente derruba Playwright.** Telas autenticadas redirecionam para `/login` sem as chaves do Supabase. Screenshots do worktree podem mostrar "login page" — não é bug da feature, é setup do worktree.
3. **Migrations colidem em NNNN.** Duas worktrees podem criar `0031_*.sql` simultaneamente. O helper `scripts/proxima-migration.ps1` previne; mas migrations já criadas no overnight 2026-05-12 podem ter colidido — rename na revisão.
4. **`git worktree remove` falha por file lock.** `node_modules`, dev server residual, ou `pnpm-store` mantêm handles. Use `cleanup-merged-worktrees.ps1 -Execute -Force` que mata node.exe direcionado e tenta Remove-Item bruto.
5. **`In Progress` no devcontext é zona humana.** O pipeline **nunca** seleciona dali. Se uma task ficou presa em `In Progress` com `is_blocked: true` e motivo `claimed by /processa-fila-barra`, foi erro de cleanup — devolva manualmente para coluna de origem.
6. **Status terminal `nothing-to-do` e `human-validation-only` vão direto pra `Review`.** Não confundir com `blocked-clarification`. O planejador deixou comentário com a evidência (já implementado em `arquivo:linha`) ou o passo manual (testar com WhatsApp real). Não exija que o pipeline "implemente" essas tasks de novo.

## Quando NÃO confiar em PASS

- Branch toca mais de 200 linhas em mais de 5 arquivos: revisão fina obrigatória.
- Toca `agente/`, `webhook/`, `infra/sql/`, ou `dominio/pix/`: revisão fina obrigatória (regras de negócio críticas).
- Foi `needs-rework` antes e voltou PASS no retry: confira que o fix foi cirúrgico, não rewrite.
- Resumo do revisor diz "achados secundários ignorados" ou similar: leia o diff inteiro.

## Referências

- `scripts/overnight-status.ps1` — sumário do log do overnight
- `scripts/overnight-loop.ps1` — execução do loop (parâmetros: `-MaxInvocations`, `-MaxTasks`)
- `scripts/proxima-migration.ps1` — anti-colisão de NNNN em infra/sql/
- `scripts/cleanup-merged-worktrees.ps1` — limpeza pós-merge
- `.claude/skills/processa-fila-barra/SKILL.md` — contrato do pipeline
- `.claude/agents/codificador-interface.md` — setup de `.env` no worktree
- `.claude/agents/migrador-sql.md` — sequência da migration via helper
