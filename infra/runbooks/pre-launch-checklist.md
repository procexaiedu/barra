# Runbook de Go/No-Go Pré-Launch — Barra (Elite Baby MVP P0)

> **O que é:** checklist único e ordenado de **todos os passos ao vivo do operador** que faltam para o cutover, consolidado de `docs/mvp/go-live-checklist.md`, `docs/mvp/producao-roadmap-executavel.md` e dos runbooks em `infra/runbooks/`. O **código** das tasks já está na `main`; aqui ficam só os passos que exigem ação humana, segredo, prod ou calibração.
>
> **Banco ÚNICO = prod** (Supabase self-hosted; `db.procexai.tech:5433` → `10.0.0.62:5432`; schema `barravips`). Não há dev/staging separado.
> **`make migrate` é PROIBIDO contra prod** (aplicaria os seeds `00NN_seed_*`). Migrations de schema: **uma a uma**, manualmente, via `scripts/aplicar_sql.py` ou MCP.
> **Veredito de cutover (autoridade):** NO-GO para operação autônoma; GO **condicional** para piloto supervisionado de 1 modelo. Detalhe no §8.

Gerado por workflow de pré-launch (2026-06-01). Achados de drift B1/B2/B3 verificados via introspecção read-only do prod e incorporados no BLOCO C.

---

## Legenda e regras de leitura

- `[ ]` cada item tem **comando/verificação concreta** e **critério de "feito"**.
- **Dependências** marcadas em cada passo (`▶ depende de`).
- **Ponto de rollback** marcado com `⏮ ROLLBACK`.
- Ordem dos blocos é a ordem de execução recomendada (segredo → imagem → migrations → observabilidade → calibração → fumaça final).

---

## PRÉ-VOO (antes de tocar em qualquer coisa)

- [ ] **PRE-1 — Confirmar o alvo do banco.** Toda escrita local/MCP bate em prod.
  - Comando: `SELECT current_database(), inet_server_addr(), inet_server_port();`
  - Feito: retorna o servidor real (`10.0.0.62` / `5432`). Se não bater, **pare**.
- [ ] **PRE-2 — Confirmar `AMBIENTE=producao`** no `api/.env` usado pelo operador (ativa o guard de seed de `scripts/aplicar_sql.py` e `make migrate`).
  - Comando: `uv run python -c "from barra.settings import get_settings; print(get_settings().ambiente)"`
  - Feito: imprime `producao`.
- [ ] **PRE-3 — Backup fresco antes do cutover.** O restore precisa ter sido drillado ao menos 1x.
  - Comando (host self-hosted): rodar `infra/backup/backup_postgres.sh` à mão; conferir `.dump` + `.globals.sql` > 0 bytes.
  - Feito: dump do dia presente **e** o drill de restore já executado uma vez com contagens batendo. ⚠️ **Executar o primeiro drill é pré-condição de GO.**
  - ⏮ ROLLBACK: este backup é o ponto de restauração para todos os passos de migration abaixo.

---

## BLOCO A — Segurança: rotação do secret MinIO (DEPLOY-01) — **AÇÃO #1, BLOQUEANTE**

> A **chave MinIO nunca foi rotacionada** e segue recuperável no histórico de um repo que esteve público — só a **rotação** neutraliza o vazamento; deletar o literal não. **Código pronto (2026-06-02):** `settings.py` lê a chave via `MINIO_SECRET_KEY_FILE` (padrão Docker/Swarm secret — vence o valor inline) e `stack.barra-portainer.yml` monta o Swarm secret `minio_secret_key` em **api e worker**, lendo a access key (não-secreta) de `${MINIO_ACCESS_KEY}`. Isso já corrige o worker que vinha **vazio** (mídia quebrava: STT/vision pulavam por `minio is None`). Restam os passos do **operador** abaixo.

- [ ] **A-1 — Gerar credencial nova no provedor MinIO e REVOGAR a antiga** (a rotação em si).
  - Feito: a chave velha não autentica mais (`mc alias set velho <endpoint> <access-key> <chave-velha> && mc ls velho` falha).
- [ ] **A-2 — Criar o Swarm secret com a chave nova** (no host do Swarm, fora do git):
  ```bash
  printf '%s' '<chave-secreta-nova>' | docker secret create minio_secret_key -
  ```
  - E setar `MINIO_ACCESS_KEY` (não-secreto) no env do stack `barra` no Portainer — a **mesma** para api e worker.
  - Feito: `docker secret ls` lista `minio_secret_key`; o stack já referencia `external: true` (no YAML).
- [ ] **A-3 — Redeploy do stack** (Portainer → "Update the stack" do `barra`, ou `docker stack deploy --with-registry-auth`). O `*_FILE` faz `settings.minio_secret_key` ler `/run/secrets/minio_secret_key` no boot.
  - Feito: `docker service inspect barra_barra-worker --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'` mostra `minio_secret_key` montado; **nenhuma** env expõe o literal da chave.
- [ ] **A-4 — Verificar que o segredo antigo sumiu do HEAD** (o histórico ainda guarda — por isso é a rotação que protege, não a deleção).
  - Comando: `git grep '<prefixo-da-chave-antiga>'` no HEAD → vazio.
- [ ] **A-5 — Provar mídia no worker** após o redeploy: enviar áudio/imagem de teste e confirmar que STT/vision **não** pulam por `minio is None`.
  - Feito: log do worker mostra upload/download MinIO OK; métrica de custo STT/vision incrementa.
  - ⏮ ROLLBACK: a rotação não tem rollback limpo (a chave velha foi revogada de propósito). Se o deploy falhar, recriar o secret com a chave nova e `docker service update --force` (**nunca** `docker restart` em Swarm → órfão ARQ).

---

## BLOCO B — Imagem versionada + flip de tag (DEPLOY-03)

> A CI já tem o job `build-image`; o **cutover do `command`** (trocar `git clone` no boot por imagem GHCR) é do operador. Pré-requisito: **billing do GitHub Actions ativo**. Recipe completa em `infra/runbooks/deploy-imagem-versionada.md`.

- [ ] **B-1 — Habilitar billing do GitHub Actions** na conta `procexaiedu`.
  - Feito: um push na `main` dispara o workflow sem erro de billing.
- [ ] **B-2 — Confirmar a imagem publicada no GHCR.**
  - Comando: `docker manifest inspect ghcr.io/procexaiedu/barra:sha-<commit-da-main>`
  - Feito: manifest existe para a tag `sha-<commit>` imutável.
- [ ] **B-3 — Credencial de pull no Swarm** (se GHCR privado): `docker login ghcr.io` com PAT `read:packages`; deploy com `--with-registry-auth`.
- [ ] **B-4 — Cutover do `command`** para api **e** worker (ver runbook §"Cutover"): `image:` → tag imutável (NÃO `latest`); remover `apt-get`/`git clone`/`uv sync`; baixar `start_period` dos healthchecks de `300s` → ~`30s`; manter healthchecks e labels Traefik.
  - Feito: `docker compose config` exit 0; `IMAGE_TAG=sha-<commit>` setado.
- [ ] **B-5 — Drill de rollback:** deploy `sha-A` → `sha-B` (Traefik sem 502; **1** task worker, sem órfão ARQ) → `docker service update --rollback` volta sem downtime.
  - ⏮ ROLLBACK: `docker service update --rollback`. **Nunca** `docker restart` em Swarm (órfão → entrega ARQ duplicada).

---

## BLOCO C — Migrations de schema em prod (DEPLOY-05/06 + CUSTO-01) — **incorpora os achados de drift**

> **Banco ÚNICO = prod.** Aplicar **uma a uma** via `uv run python scripts/aplicar_sql.py infra/sql/<arquivo>.sql`. **NUNCA `make migrate`.** Runbook: `infra/runbooks/aplicar-migrations-prod.md`.

### Estado real verificado (introspecção read-only do prod, 2026-06-01)

> O estado real do schema é a **única fonte de verdade**: a tabela de tracking **`barravips.schema_migrations` NÃO existia** na auditoria. A introspecção DDL confirmou que **as 42 migrations de schema já estão aplicadas no prod** — INCLUSIVE `20260601090000` (vendedores/comissão/taxa) e `20260602010031`. **Isto corrige a memória antiga "vendedores tabela ausente": `vendedores`, `financeiro_comissao_niveis`, `financeiro_comissoes_pagas`, `modelos.vendedor_id`, `atendimentos.vendedor_id`, `atendimentos.taxa_cartao_snapshot`, `vendedor_nivel_enum` já existem.** (Conflito B1×B3 do relatório de drift resolvido a favor de B1 por query DDL direta; B3 foi falso-alarme.)
>
> **Dois desvios reais:**
> 1. **DRIFT** — `20260526225347_drop_financeiro_despesas.sql` **NÃO aplicada**: `financeiro_despesas`, `financeiro_despesas_recorrentes`, `categoria_despesa_enum` continuam vivos. **NÃO marcar como aplicada no backfill.**
> 2. **`schema_migrations` ausente** → sem tracking/drift-check até C-1/C-2.

- [ ] **C-0 — Confirmar o estado real por introspecção** (read-only).
  - `SELECT to_regclass('barravips.vendedores') IS NOT NULL;` → `true`.
  - colunas (`modelos.vendedor_id`, `atendimentos.vendedor_id`, `atendimentos.taxa_cartao_snapshot`) → 3.
  - `vendedor_nivel_enum` existe → `true`.
  - `SELECT to_regclass('barravips.schema_migrations');` → `NULL` (antes de C-1).

- [ ] **C-1 — Aplicar `20260601100000_schema_migrations.sql`** — **PRIMEIRA, obrigatória.**
  - **Por quê primeira:** `aplicar_sql.py` faz `INSERT INTO barravips.schema_migrations` ao final de todo arquivo de schema; a tabela precisa existir antes.
  - Comando: `uv run python scripts/aplicar_sql.py infra/sql/20260601100000_schema_migrations.sql`
  - Verificação: `SELECT to_regclass('barravips.schema_migrations');` → não-nulo.
  - ⏮ ROLLBACK: `DROP TABLE barravips.schema_migrations;` (objeto isolado, sem dado de domínio).

- [ ] **C-2 — Backfill do tracking** com as 42 migrations de **schema** já aplicadas, para o drift-check **nunca** reaplicar (as legacy `0001-0011/0028/0029` **não são idempotentes**). `ON CONFLICT DO NOTHING`. **NÃO inclui** seeds, `0036_corrigir_duplicatas` (data-fix idempotente) nem `20260526225347` (DRIFT — ver C-4).
  - ▶ depende de: C-1.
  - Verificação: `SELECT count(*) FROM barravips.schema_migrations;` → 42.

- [ ] **C-3 — (CONDICIONAL) Aplicar `20260601090000` SE C-0 mostrar faltando.** Pelo estado verificado **já está aplicada → SKIP** (só garantir que o filename está no backfill C-2).

- [ ] **C-4 — Decidir o DRIFT de `20260526225347_drop_financeiro_despesas.sql`.** Objetos que o repo manda dropar continuam vivos. **Decisão de produto — não automatizar.**
  - Opção A (aplicar o drop): `aplicar_sql.py` no arquivo → depois registrar o filename. ⚠️ confirmar antes que nenhum código vivo lê essas tabelas.
  - Opção B (manter): escrever **migration nova** que cancela o drop (não editar a aplicada — imutabilidade).
  - Enquanto não decidido, o drift-check sinaliza essa migration como pendente — **aceitável como NO-GO suave**, não bloqueia o piloto.
  - ⏮ ROLLBACK: se aplicar o drop por engano, restaurar do backup PRE-3 (drop é destrutivo).

- [ ] **C-5 — Cadastro operacional (CUSTO-01):** cadastrar `vendedores` + setar `modelos.vendedor_id`; ligar a UI de fechamento p/ gravar `taxa_cartao_snapshot`; validar `comissao_evitada`.
  - Feito: ao menos a modelo do piloto tem `vendedor_id` (ou NULL deliberado → IA conduz → comissão 0); dashboard `roi_ia` sem erro.

- [ ] **C-6 — Verificação final de drift** (read-only): `SELECT filename FROM barravips.schema_migrations ORDER BY filename;` vs `ls infra/sql/*.sql` (ignorando `*seed*`). Diferença esperada: só `20260526225347` (até C-4) e `0036`.

> **NOTA seeds** (`00NN_seed_*` + `20260524061000`): data-only, **não vão a prod** (guard `seed_bloqueado`) e **não** entram no tracking.

---

## BLOCO D — Stack de observabilidade (OBS-02 + CUSTO-05)

> 3 serviços (`prometheus-barra`, `alertmanager-barra`, `grafana-barra`) já no stack (aditivos); configs em `infra/monitoring/`. Runbook: `infra/runbooks/monitoring-stack.md`.

- [ ] **D-1 — Validar os configs** (exige Docker vivo):
  ```bash
  docker run --rm -v "$PWD/infra/monitoring:/cfg" --entrypoint promtool prom/prometheus:v2.53.0 check config /cfg/prometheus.yml
  docker run --rm -v "$PWD/infra/monitoring:/cfg" --entrypoint promtool prom/prometheus:v2.53.0 check rules /cfg/alert.rules.yml
  docker run --rm -v "$PWD/infra/monitoring:/cfg" --entrypoint amtool prom/alertmanager:v0.27.0 check-config /cfg/alertmanager.yml
  ```
- [ ] **D-2 — Setar env vars** (Portainer): `ALERT_WEBHOOK_URL` (destino real, não `localhost:9999/noop`); `GRAFANA_ADMIN_PASSWORD` (**trocar do default `admin`**).
- [ ] **D-3 — Redeploy da stack.** Os 3 serviços sobem sem tocar api/worker/redis.
- [ ] **D-4 — DNS/Traefik:** `grafana-barra.procexai.tech` → Swarm.
- [ ] **D-5 — Verificação ao vivo:** Targets `barra-api`/`barra-worker` **UP**; datasource Prometheus provisionado; **5 alertas** carregados (`AgenteSpikeEscaladaDefesa`, `AgenteCacheWriteRateAlto`, `AgenteCustoTurnoAcimaDoAlvo`, `AgenteLatenciaTurnoP95Alta`, `BarraHttpLatenciaP95Alta`).
- [ ] **D-6 — Fumaça de alerta:** elevar `agente_escalada_total{bucket="defesa"}` (ou baixar threshold) e confirmar entrega no `ALERT_WEBHOOK_URL`.
- [ ] **D-7 — Wire de custos no Grafana (CUSTO-02/01):** confirmar tarifas STT/vision; somar `custo_por_atendimento_brl`; ligar `custo_ia_brl` do ROI. ⚠️ alinhar o literal `0.12` da regra `AgenteCustoTurnoAcimaDoAlvo` com `settings.custo_alvo_brl`.
  - ⏮ ROLLBACK: stack aditiva — remover os 3 serviços não afeta api/worker/redis.

---

## BLOCO E — Gate de evals + calibração do judge (EVAL-04/03 + EVAL-10) — **GATE DO CUTOVER Vendedor→IA**

> O cutover do Vendedor → IA por modelo **só é autorizado** depois deste bloco verde ao vivo. Antes dele a IA opera **assistida**; atendimento conduzido pela IA não gera comissão.

- [ ] **E-1 — Run live do runner (EVAL-01/02):** grafo real (Sonnet) com `TEST_DATABASE_URL` (**banco de teste com rollback, NUNCA prod**) + `ANTHROPIC_API_KEY`. Comando: `make evals`.
- [ ] **E-2 — CI bloqueante (EVAL-04/03):** secrets `TEST_DATABASE_URL`/`ANTHROPIC_API_KEY` no workflow; branch protection; graduar adversariais novas `capability` → `regressão` **só após** o primeiro run verde.
  - ▶ depende de: B-1, E-1.
- [ ] **E-3 — Calibrar o judge (EVAL-10) — passo humano:** rotular golden held-out com Fernando + sócia (30-50 turnos). Medir acordo humano-humano **primeiro** (teto). Rodar `evals/calibracao/calibrar.py` → TPR/TNR/κ (+ Gwet AC2 em persona/tom). Limiares ADR 0015: TPR ≥ 0.90, TNR ≥ 0.85, κ ≥ 0.60.
  - Feito: `promove_a_blocker(...)` retorna `True`; **só então** `JUDGE_VINCULANTE=True` em `runners/judge.py`.
- [ ] **E-4 — (Descoberta, NÃO-GATE) EVAL-12:** run live do simulador dual-control. Falhas viram fixtures de `scripted_5/`.

---

## BLOCO F — Reinício do worker e verificação de prompt

> O agente/LLM roda no **`barra-worker`** (ARQ), não na api. Qualquer mudança de prompt/grafo/calibração (E-3) **exige reiniciar o worker**.

- [ ] **F-1 — Forçar update do worker:** `docker service update --force barra_barra-worker`. **Nunca** `docker restart`.
  - Feito: `docker service ps barra_barra-worker` mostra **1** task `Running` nova; nenhum órfão.
- [ ] **F-2 — Confirmar a revisão pelo `revision_id` no trace LangSmith.**
  - ⏮ ROLLBACK: `docker service update --rollback barra_barra-worker`.

---

## VERIFICAÇÃO DE FUMAÇA FINAL (ponta-a-ponta, antes de declarar GO)

- [ ] **S-1 — Webhook → resposta:** mensagem de teste chega, debounce dispara, IA responde no número da modelo. (Confirmar créditos Anthropic ativos — "créditos esgotados" deixa o agente mudo com 400.)
- [ ] **S-2 — Mídia:** áudio (STT) e imagem (vision Pix) processam sem `minio is None` (valida BLOCO A).
- [ ] **S-3 — Isolamento por par:** turno na modelo do piloto não vaza dado de outra modelo (output-guard ativo).
- [ ] **S-4 — Comando de grupo:** `fechado #N <valor>` na Coordenação afeta só o atendimento da modelo certa (SEC-02) e grava financeiro.
- [ ] **S-5 — Observabilidade viva:** targets UP, `agente_eval_pass_rate` scrapeado, alerta de fumaça entregue (D-6).
- [ ] **S-6 — Backup do dia + primeiro drill de restore concluído** (PRE-3).

---

## §8 — VEREDITO GO/NO-GO CONDICIONAL

**GO para PILOTO SUPERVISIONADO de 1 modelo (humano-no-loop)** se e somente se:

- ✅ **BLOCO A** completo — secret MinIO **rotacionado** e worker preenchido (S-2 verde). *Sem isto: NO-GO absoluto.*
- ✅ **BLOCO C** — `schema_migrations` criada (C-1), backfill feito (C-2), vendedores/comissão/taxa confirmados (C-0), DRIFT `20260526225347` **decidido** (C-4) ou aceito como pendência não-bloqueante.
- ✅ **BLOCO D** — observabilidade no ar (2 targets UP, 5 regras, alerta de fumaça, Grafana com senha trocada). *Sem isto: NO-GO.*
- ✅ **PRE-3/S-6** — backup do dia + primeiro drill de restore.
- ✅ **BLOCO F** — worker reiniciado e revisão confirmada.

**NO-GO para OPERAÇÃO AUTÔNOMA / cutover Vendedor→IA / 2ª modelo** até que, adicionalmente:

- ✅ **BLOCO E completo ao vivo** — `EVAL-04/03` verdes em CI (K=5) com branch protection **E** judge calibrado e **vinculante** (`EVAL-10`). Código na `main` **não basta**.
- ✅ **BLOCO B** (imagem versionada + rollback drillado).
- ✅ **ROI demonstrável** — CUSTO-01/02 ao vivo (C-3/C-5 + D-7).

**Não expandir para a 2ª modelo** até a Onda 1 (A/B/C/D) fechada ao vivo e o piloto estável.

---

*Fontes consolidadas: `docs/mvp/go-live-checklist.md`; `docs/mvp/producao-roadmap-executavel.md`; `infra/runbooks/{aplicar-migrations-prod,deploy-imagem-versionada,monitoring-stack,backup-restore-postgres,topologia-banco}.md`; `infra/compose/stack.barra-portainer.yml`; `scripts/aplicar_sql.py`. Achados de drift B1/B2/B3 incorporados no BLOCO C; conflito B1×B3 resolvido por query DDL direta (B1 correto: `20260601090000` JÁ aplicada).*
