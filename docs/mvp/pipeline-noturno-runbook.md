# Runbook — Pipeline noturno do roadmap (Claude Code Routines)

> **Estado (2026-06-01):** a fila de produção que este pipeline drenava foi **concluída** e os docs de
> roadmap removidos (no histórico do git). Pendências vivas migraram para `go-live-checklist.md`. Mantido
> como **referência operacional** do formato de fan-out via Routines, reutilizável numa próxima leva.
>
> **O que é:** fan-out de **Claude Code Routines one-off**, uma por task elegível da fila de produção.
> Cada routine clona `main`, trabalha isolada num branch
> `claude/<task-id>`, **verifica por comando** e abre **um PR draft** (sucesso com evidência, ou
> `[FAIL]` documentado). Você revisa de manhã. Motor: Routines na cloud Anthropic; modelo
> `claude-opus-4-8`. Desenho aprovado em 2026-05-30.
>
> Este runbook é a fonte de verdade **operacional**; o racional vive na sessão de desenho e no
> próprio roadmap. Não duplica os specs das tasks — a fila é que manda.

---

## 1. Por que este formato (e não um orquestrador)

- **Onda 1 + wins são quase todas independentes** (`Depende de: —`) → fan-out paralelo, sem estado
  compartilhado entre runs. Conflitos resolvidos no merge (a fila já prevê).
- **A espinha de dependência é estreita** (EVAL-01 → evals; DEPLOY-03 → CI) → serializa no passo de
  seleção, não precisa de grafo.
- **A cloud é o ponto:** máquina desligada, e — decisivo — o agente **não alcança produção**
  (`api/.env` aponta pra prod e fica fora do clone; `db.procexai.tech:5433` fora da allowlist
  Trusted; `guard_prod.py` trava `make migrate`/seeds em segunda camada). Loops/orquestradores
  **locais** rodariam com acesso a prod — por isso foram descartados.

## 2. Pré-requisitos (uma vez)

1. **Scaffolding em `main`** (carrega dentro da Routine porque está no repo):
   - `.claude/agents/{domain-isolation,security,langgraph,migration}-reviewer.md` — revisores advisory.
   - `.claude/hooks/{guard_prod,ruff_format,eslint_fix,aviso_reload_worker}.py` + `.claude/settings.json`.
   - `.github/workflows/ci.yml` — CI mínimo (juiz objetivo; ver §3).
2. **`gh` autenticado** e branch base **pushada para origin** (a cloud só clona do remote).
3. ⚠️ **Repo é PÚBLICO.** Todo branch `claude/*` e PR draft é mundialmente visível, e o histórico
   carrega o segredo MinIO vazado (rotação = DEPLOY-01, **manual**). Guardrail inegociável no
   template: **nunca** escrever segredo num branch, nunca `git add .`, nunca incluir `api/.env`.

## 3. Verificação: o que roda na cloud vs. o que fica para você

| Verificação | Roda na cloud? | Observação |
|---|---|---|
| `ruff` (arquivos tocados) | sim | via hook `ruff_format.py` (PostToolUse) |
| `mypy src`, `pytest` (FakeConn) | sim | `needs_db`/`needs_key` pulam sem env — não tocam prod/API |
| `grep`/asserção determinística | sim | o campo `Verificação` de cada task |
| Banco de **prod** real (`needs_db`) | não | fora da allowlist Trusted → REL-05/02/06/08, evals = bucket B |
| Google Maps / Playwright visual | não | `*.googleapis.com` bloqueado → humano de manhã |
| Deploy Swarm / Sentry / LangSmith / Prometheus reais | não | wiring verificado por teste; o resto, humano |

**CI mínimo (`.github/workflows/ci.yml`):** roda `mypy src` + `pytest` (sem `TEST_DATABASE_URL`
nem `ANTHROPIC_API_KEY`) em cada PR — o **juiz objetivo independente do agente**. Não inclui `ruff`
global porque há dívida de formatação preexistente (57 arquivos); o lint dos arquivos **tocados** já
é garantido pelo hook. Limpeza global de ruff é decisão à parte (fora do escopo de mudança cirúrgica).

## 4. Despachar uma noite

1. **Seleção** (interativa, ~2 min): do Índice do roadmap, pegue
   `Status:todo ∧ (todas as deps Done) ∧ bucket A (§6) ∧ menor onda aberta` (wins + Onda 1 primeiro).
2. **Filtro de colisão de arquivo:** nunca despache na mesma noite duas tasks que editam o mesmo
   arquivo. Coalescer quando coerente. Pares conhecidos:
   - `workers/settings.py`: REL-03 / REL-04 / OBS-01
   - `core/tracing.py`: SEC-10 -> OBS-04 -> OBS-09/10 -> OBS-05
   - `core/metrics.py`: CUSTO-02 / CUSTO-06 / TOOLS-06 / TOOLS-04 / AGENTE-OG
   - `webhook/routes.py`: SEC-02 / REL-06 · `main.py`: WIN-SEC-09 / OBS-03
3. Para cada task, preencher o **template (§5)** e criar **uma Routine one-off** (model
   `claude-opus-4-8`, `effort: xhigh` se o schema expuser). One-off **não conta** no cap de
   15 recurring/dia (Max 20x), mas consome o bucket de uso compartilhado — agende fora do pico PT.

### Schema RemoteTrigger (one-off) — confirmar via skill `/schedule` (research preview)

```jsonc
{
  "name": "barra <TASK_ID>",
  "run_once_at": "YYYY-MM-DDTHH:MM:SSZ",   // UTC futuro
  "enabled": true,
  "mcp_connections": [],
  "job_config": { "ccr": {
    "environment_id": "<ENV_ID_PADRAO>",   // pegar via /schedule
    "session_context": {
      "model": "claude-opus-4-8",
      "sources": [{ "git_repository": { "url": "https://github.com/procexaiedu/barra" } }],
      "allowed_tools": ["Bash","Read","Write","Edit","Glob","Grep","WebFetch","WebSearch","Task"]
    },
    "events": [{ "data": {
      "uuid": "<lowercase-v4-uuid>",
      "session_id": "",
      "type": "user",
      "parent_tool_use_id": null,
      "message": { "content": "<PROMPT_PREENCHIDO_DO_TEMPLATE>", "role": "user" }
    }}]
  }}
}
```

`Task` no `allowed_tools` é o que habilita os revisores subagentes.

## 5. Template de prompt por-task (Opus 4.8)

Preencher os `<PLACEHOLDERS>` com os campos da task no roadmap. Calibrado para Opus 4.8:
seguimento literal (escopo explícito), anti-overengineering, evidência por exit-code, FAIL
documentado em vez de chute.

```text
Você é um engenheiro sênior executando UMA task isolada da fila de produção do projeto "barra"
(central de atendimento Elite Baby: FastAPI + LangGraph + ARQ em api/, Next.js em interface/).
Trabalhe de forma autônoma e abra UM PR draft ao final. Esta é uma tarefa de múltiplas etapas —
raciocine com cuidado antes de cada decisão.

<contexto>
Você está num agente remoto (cloud), clone fresco da branch main, sem contexto prévio e sem acesso
a produção. A autoridade de decisão segue, nesta ordem: ADRs vigentes (docs/adr/) > CONTEXT.md >
CLAUDE.md > este prompt. Não há revisor humano agora; há revisão de manhã.
</contexto>

<primeiro_passo>
git switch -c claude/<TASK_ID>     # trabalhe SÓ neste branch; nunca na main
</primeiro_passo>

<leitura_obrigatoria>
Antes de editar QUALQUER arquivo, leia: CLAUDE.md, CONTEXT.md, <ADRs_RELEVANTES> e cada arquivo
listado em <escopo_de_arquivos>. Nunca afirme nada sobre um arquivo que você não abriu; nunca edite
um arquivo que você não leu.
</leitura_obrigatoria>

<tarefa>
<!-- Colar VERBATIM da fila: Objetivo (DoD) + Passos. -->
<OBJETIVO_E_PASSOS>
</tarefa>

<escopo_de_arquivos>
Toque SOMENTE nestes arquivos: <LISTA_POSITIVA>. Não "melhore" código, comentário ou formatação
adjacente. Não refatore o que não está quebrado. Toda linha alterada deve estar diretamente ligada
à tarefa. Esta instrução vale para TODOS os arquivos da lista, não só o primeiro.
</escopo_de_arquivos>

<como_decidir_em_caso_de_ambiguidade>
Se houver ambiguidade REAL não resolvível pela hierarquia de autoridade, NÃO escolha em silêncio:
pare e siga <saida_caso_falha>. Conta como "chutar" (proibido): criar abstração/utilitário para uso
único, adicionar prop/config/flag não pedida, refatorar código vizinho, tratar erro de cenário
impossível, ou generalizar a instrução além do escopo. Um PR [FAIL] documentado é preferível a um
chute.
</como_decidir_em_caso_de_ambiguidade>

<validacao>
Critério de sucesso (rode exatamente isto): <COMANDO_DE_VERIFICACAO>
Regras: apenas exit code 0 é sucesso — qualquer ≠0 é falha real, nunca "deu certo". pytest com exit
5 (nenhum teste coletado) é FALHA. PROIBIDO para fazer passar: editar/apagar testes, enfraquecer
asserções, `assert True`, mockar a função sob teste, ou usar -k/skip/xfail para não rodar. Ataque a
causa raiz; não suprima o erro. Capture o comando, o exit code e a saída bruta — você vai colá-los
no PR como evidência (mostre evidência, não afirme sucesso).
</validacao>

<revisao_antes_do_pr>
Invoque (em paralelo) os subagentes revisores que a condição ativar:
- domain-isolation-reviewer — diff toca agente/, dominio/ ou webhook/ (isolamento por par, PII, camadas).
- security-reviewer — toca webhook/, auth, mídia ou dado sensível.
- langgraph-reviewer — toca agente/ ou workers/ (Command/edge, factory runtime, dedupe de turno).
- migration-reviewer — cria/altera infra/sql/*.sql.
(Opus 4.8 dispara poucos subagentes por default — chame explicitamente os ativados.) Cole o parecer
no corpo do PR em "Revisão automática (advisory)". Achado bloqueante/[CRITICO] -> corrija antes do
PR ou, se não resolvível, vá para <saida_caso_falha>.
</revisao_antes_do_pr>

<saida_caso_sucesso>
git add <CAMINHOS_EXPLICITOS>   # NUNCA `git add .`; nunca inclua arquivos órfãos que você não criou
git commit -m "<tipo>(<area>): <resumo>" -m "" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push -u origin claude/<TASK_ID>
gh pr create --draft --title "<TASK_ID> — <resumo>" --body "<corpo>"
Corpo do PR: o que mudou e por quê (ligado ao DoD) + bloco ``` com comando/exit code/saída + seção
da revisão advisory. NÃO faça merge. NÃO pushe na main.
</saida_caso_sucesso>

<saida_caso_falha>
Se não conseguir fazer a Verificação passar com correção legítima em até 3 tentativas, ou se a task
estiver genuinamente bloqueada/ambígua: PARE. Não force solução nem finja sucesso. Abra o PR draft
com título "[FAIL] <TASK_ID> — <resumo>", label `verificacao-falhou`, e no corpo: o comando exato,
o exit code, o stderr BRUTO completo, a última hipótese e o que falta. Um bloqueio honesto e
auditável é resultado aceitável; um PR verde-falso não é.
</saida_caso_falha>

<limites>
- Mínimo de código que resolve. Não adicione features, abstrações, docstrings/comentários/tipos em
  código que você não mudou, nem tratamento de erro para o impossível. Valide só em fronteira.
- Ações reversíveis e locais (editar arquivo, rodar teste) são livres. PROIBIDO: merge, push na main,
  git push --force, git reset --hard, --no-verify, rotacionar/expor segredo, tocar o banco de
  produção, `make migrate`, aplicar *_seed_*.sql, ou descartar arquivos que você não criou.
- Convenções: domínio PT-BR / infra EN; sempre `from barra.x import y`; psycopg3 puro (jsonb ->
  json.dumps + %s::jsonb); feature-first em dominio/ (sem models/ ou services/ globais).
</limites>

Reancore: faça o MÍNIMO que satisfaz a Verificação, só nos arquivos listados. Prefira um PR [FAIL]
documentado a um chute. Não generalize a instrução além do escopo.
```

## 6. Partição das tasks (qual bucket, e por quê)

- **A — automatizar já:** verificação determinística que roda no sandbox (grep/ruff/mypy/unit
  FakeConn ou injeção de fake), sem prod/segredo/Maps/DB-real/comportamento-de-agente-sem-gate.
  -> **8 wins**, SEC-02, SEC-10, OBS-03, OBS-01, OBS-04, TOOLS-02, PER-05/TOOLS-01, REL-03, REL-04,
  TOOLS-04, CUSTO-02, CUSTO-06, TOOLS-06, e os encadeados (OBS-07/09/10/05, REL-12, CUSTO-04).
- **B — depois do gate/pré-requisito:** precisa do runner EVAL-01, do gate de CI (EVAL-04/03), do
  **banco de teste real**, ou é **mudança de persona/comportamento do agente** sem o gate
  adversarial. -> EVAL-*, AGENTE-OG, PER-01/03, PER-11, SEC-07, TOOLS-08, REL-05/02/06/08.
- **C — manual:** prod/segredo/migration/deploy Swarm/infra-host/visual-Maps. -> DEPLOY-01/02/03/04,
  DEPLOY-05/06, OBS-02, CUSTO-05, CUSTO-01 (migration), e qualquer coisa com Google Maps.

> Constraint que separa A de B: `TEST_DATABASE_URL` aponta para prod e o banco **não** está na
> allowlist da cloud — verificação que precise do Postgres real não roda lá. **Não** adicione o DB de
> prod à allowlist para contornar isso.

## 7. Revisão de manhã

- **Um PR por task.** Leia: o bloco de evidência (comando/exit/saída) + a seção advisory dos
  revisores. Para verificação parcial (Sentry/LangSmith/Prometheus/Redis/DB reais), rode a parte que
  faltou localmente.
- PRs `[FAIL]` têm a label `verificacao-falhou` e o bloqueio documentado — triagem rápida.
- Merge ou feche; **marque `Status: done`** no roadmap e referencie o PR. Conflitos cross-PR são
  resolvidos no merge (esperado num fan-out).

## 8. Custo, caps e segurança

- One-off fora do cap recurring; mas o bucket de uso é **compartilhado** com seu chat/Cowork —
  ative o teto de "extra usage" e reconcilie com `ccusage` de manhã. Comece com lotes pequenos.
- **Segurança:** só PR draft, nunca merge/push em main, nunca migrar prod, nunca expor segredo. O
  `guard_prod.py` é a segunda camada; o sandbox de rede é a primeira.
