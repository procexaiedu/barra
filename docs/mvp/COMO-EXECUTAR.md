# Como executar o roadmap — playbook do agente Claude

> **Par deste doc:** `producao-roadmap-executavel.md` é a **fila de tasks** (o quê). Este arquivo é **como rodar** essa fila com agilidade. Racional/decisões: `producao-prontidao-roadmap.md` + `docs/adr/`.

---

## 1. Não escreva um prompt por task — use um launcher único

Cada task do roadmap já é autocontida (Objetivo, Arquivos:linha, Passos, Verificação) e herda o *Protocolo de consumo* + *Guardrails globais* do topo do roadmap. **A task é o prompt.** Cole isto numa sessão Claude Code:

```
Leia docs/mvp/producao-roadmap-executavel.md.
Pegue a PRÓXIMA task com Status: todo cujas dependências estejam todas done,
seguindo o Protocolo de consumo e os Guardrails globais do topo do arquivo.
Antes de codar: confirme em 2 linhas o que entendeu e qual é o critério de
Verificação. Implemente. Rode a Verificação. PARE antes de commitar para eu revisar.
```

Para fixar a task: troque a 2ª frase por `Execute a task EVAL-01`.

**Exceção — tasks com decisão de design.** Não rode no automático; comece com o ADR:
- `AGENTE-OG` (ADR 0016 — output-guard)
- `EVAL-02` + `EVAL-10` (ADR 0015 — LLM-judge)
- `CUSTO-01` (ADRs 0012/0013 — comissão/taxa/ROI)

Para essas: `Leia docs/adr/00XX-*.md e me proponha o plano de implementação antes de codar` (ou rode `/grill-with-docs`).

---

## 2. Agilidade: worktrees por *trilha*

Duas sessões Claude no mesmo `C:\barra` colidem (HEAD/índice). Uma worktree por branch = N sessões em paralelo sem se atropelar. Use o script:

```powershell
# da raiz do repo:
scripts/nova-trilha.ps1 -Nome evals          # cria ../barra-evals na branch track-evals (a partir da main)
scripts/nova-trilha.ps1 -Nome webhook-sec
scripts/nova-trilha.ps1 -Nome infra
```

O script faz `git worktree add` a partir da `main`, copia o `api/.env` (worktree não copia gitignored) e deriva `TEST_DATABASE_URL` de `DATABASE_URL`. Abra um Claude Code em cada pasta criada e cole o launcher.

Ao terminar uma trilha: `git worktree remove ../barra-<nome>` (depois de mesclar/promover a branch).

### Paralelismo só paga em arquivos disjuntos

Tasks que brigam pelo **mesmo arquivo** têm que ser **sequenciais** (não as ponha em worktrees simultâneas):

| Cluster (mesmo arquivo) | Tasks | Ordem |
|---|---|---|
| `core/tracing.py` | SEC-10 → OBS-04 → OBS-09/10 → OBS-05 | SEC-10 cria o setup primeiro |
| `.github/workflows/ci.yml` | DEPLOY-03 → EVAL-04/03 | DEPLOY-03 primeiro |
| `webhook/routes.py` | SEC-03, SEC-02, REL-06, WIN-SEC-06 | uma de cada vez |
| `agente/nos/llm.py` | PER-05/TOOLS-01 → TOOLS-02 | — |
| `evals/runners/runner.py` | EVAL-01 → 08 → 02 → 10 → 04 | já serial pelas deps |
| `workers/settings.py` | REL-03, REL-04, OBS-01, OBS-04 | sequencial (merges fáceis) |

### Trilhas que rodam em paralelo (sweet spot: 3 worktrees)

- **Trilha Infra** — DEPLOY-01, DEPLOY-02, DEPLOY-04 (`infra/compose`, `runbooks`; fora do código).
- **Trilha Webhook/Sec** — SEC-03, SEC-02, WIN-SEC-* (`webhook/`, `main.py`).
- **Trilha Evals** — EVAL-01→08→02→10→04 (`api/evals/`).
- **Trilha Observabilidade** — SEC-10→OBS-04→OBS-01→OBS-03 (serial internamente: compartilham `tracing.py`/`metrics.py`/`settings.py`).
- **Trilha Agente** — PER-05/TOOLS-01→TOOLS-02 (`agente/nos/llm.py`, `coordenador.py`).

---

## 3. Lotes e granularidade

- **`WIN-*` (8 tasks):** minúsculas e independentes → **uma sessão, um PR** ("limpe todos os wins"). Não faça 8 PRs.
- **Tasks substanciais:** 1 PR por task (revisável).

---

## 4. O que delegar vs. o que precisa de você

Separe pelo campo **Verificação**:

- **Self-verificável** (Claude itera sozinho até passar): tem `make test`/`make evals`/`git grep`/fixture. Maioria das tasks de código, evals e métricas.
- **Precisa de você/infra** (Claude prepara o diff, você executa/valida):
  - `DEPLOY-01` — rotacionar segredo é ação humana no provedor.
  - `DEPLOY-04` — backup/restore no host.
  - `OBS-04` — confirmar evento no Sentry.
  - `DEPLOY-02`/`DEPLOY-03` — validar no Swarm/Traefik.

### Routines overnight (cloud Anthropic)

Mande para Routines **só** as self-verificáveis, mecânicas e de baixo risco, e **depois que `EVAL-01` existir** (sem runner não há verificação automática). Bons alvos: `TOOLS-06`, `WIN-*`, fixtures de `SEC-07`, `EVAL-08`. **Nunca** overnight: tasks de segredo/prod e as 3 de design (ADR). Restrições da Routine: branch a partir da main, sem memórias locais, 1 prompt autocontido por routine.

---

## 5. Cadência recomendada

1. **Você, hoje:** `DEPLOY-01` (rotacionar `MINIO_SECRET_KEY` — ação #1, não-delegável).
2. **1 sessão:** batch dos `WIN-*`.
3. **2-3 worktrees em paralelo:** Trilha Webhook/Sec + Trilha Infra + iniciar `EVAL-01`.
4. **Marco crítico:** fechar `EVAL-01→08→02→10→04` (o gate). Sem ele não há rede nem critério de cutover.
5. **Sessões interativas dedicadas** (ADR-first/grill): `AGENTE-OG`, `EVAL-02/10`, `CUSTO-01`.
6. **Pós-gate:** ligar Routines overnight para a cauda mecânica da Onda 3.

---

## 6. Anti-drift (regra obrigatória)

Ao concluir uma task, o Claude **flipa `Status: done` + cola o hash do commit** na task e na linha do Índice de `producao-roadmap-executavel.md`. Esse arquivo é a única fonte de progresso. Tasks bloqueadas ficam `blocked(by …)` até a dependência virar `done`.
