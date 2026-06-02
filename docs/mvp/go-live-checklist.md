# Go-live checklist — pendências vivas pós-roadmap

> **O que é:** o que sobrou de pendente quando a fila de produção foi concluída e os docs de roadmap
> (`producao-roadmap-executavel.md`, `producao-prontidao-roadmap.md`, `gap-analysis-prontidao.md`,
> `COMO-EXECUTAR.md`) foram removidos (estão no histórico do git). Aqui ficam **só** os itens que ainda
> exigem ação ao vivo (operador, prod, segredo, calibração humana) — o **código** das tasks já está na `main`.
> Consolidado em 2026-06-01.
>
> Carrega também o **veredito GO/NO-GO** e o critério de **cutover** que o `docs/agente/08-evals.md` referencia.
>
> O **passo-a-passo ordenado do operador** (comandos, rollback, dependências) vive em
> `infra/runbooks/pre-launch-checklist.md` — este arquivo é o registro de pendências; aquele é o roteiro de execução.

---

## 1. Veredito GO/NO-GO (autoridade do cutover)

- **NO-GO para operação autônoma. GO condicional para piloto supervisionado** (humano-no-loop, 1 modelo).
- **Não expandir para a 2ª modelo** até a Onda 1 estar fechada ao vivo (segurança/infra/observabilidade).
- **Cutover do Vendedor → IA por modelo só depois que o gate de evals existir E PASSAR ao vivo** — não basta
  o código do runner estar na `main`: exige `EVAL-04/03` verdes em CI (K=5) + judge calibrado e **vinculante**
  (`EVAL-10`). Atendimento conduzido pela IA não gera comissão; antes do gate, a IA opera assistida.
- **Tese econômica (ROI) só é demonstrável** depois do **cadastro operacional** (`CUSTO-01`: popular
  `vendedores` + `modelos.vendedor_id`) e de `CUSTO-02` (tarifa STT) ao vivo. A migration de schema do
  `CUSTO-01` já está em prod (2026-06-02); falta popular os dados — sem comissão/taxa preenchidas, "a IA
  lucra mais que o vendedor" não tem como ser medido.

---

## 2. Segurança — item aberto (ação #1)

- [ ] **DEPLOY-01 — rotacionar a `MINIO_SECRET_KEY`** (ainda é a prioridade absoluta). A chave segue
      **recuperável no histórico de um repo que esteve público** — só a **rotação** neutraliza o vazamento;
      a deleção do literal não.
  - ✅ **Código pronto (2026-06-02):** padrão `*_FILE` em `settings.py` (`MINIO_SECRET_KEY_FILE` lê o Swarm
    secret montado e vence o valor inline) + `stack.barra-portainer.yml` monta o secret `minio_secret_key`
    em **api e worker** e lê a access key de `${MINIO_ACCESS_KEY}` (worker antes vinha vazio → mídia quebrava
    por `minio is None`; agora unificado). Testes em `api/tests/test_deploy_01_secret_file.py`.
  - ⏳ **Falta o operador:** gerar a chave nova no MinIO + revogar a antiga, criar o Swarm secret
    (`docker secret create minio_secret_key -`), setar `MINIO_ACCESS_KEY` no Portainer e redeploy. Passo-a-passo
    em `infra/runbooks/pre-launch-checklist.md` (BLOCO A).

---

## 3. Gate de evals + cutover (Onda 2 — passos ao vivo)

O código está na `main` (branch `feat/evals-cutover-gate`); falta rodar/ligar:

- [ ] **EVAL-01/02 — run live** do runner (grafo real + Sonnet) com `TEST_DATABASE_URL` (banco de teste, **nunca prod**) + `ANTHROPIC_API_KEY`.
- [ ] **EVAL-04/03 — CI bloqueante:** habilitar os secrets `TEST_DATABASE_URL`/`ANTHROPIC_API_KEY` no workflow
      `.github/workflows/evals.yml`, ligar **branch protection** (status check obrigatório) e **graduar** as
      adversariais novas de `capability` → `regressão` depois do primeiro run verde (senão CI fica vermelho perpétuo).
- [ ] **EVAL-10 — calibrar o judge** (hoje **advisory**, não bloqueia): rotular golden held-out com Fernando+sócia
      (30–50 turnos), medir **acordo humano-humano primeiro** (é o teto da meta), rodar o judge, computar
      TPR/TNR/κ (+ Gwet AC2 em rubricas de prevalência assimétrica). Só quando `promove_a_blocker` der `True` é que
      `JUDGE_VINCULANTE` vira `True` em `runners/judge.py`.
- [ ] **EVAL-12 — run live** do simulador dual-control (descoberta, não-gate).

---

## 4. Deploy / infra (código pronto, cutover do operador)

- [ ] **DEPLOY-03 — imagem versionada:** habilitar **billing do GitHub Actions** (estava travado), publicar a
      imagem no GHCR, fazer o **cutover do `command`** no stack (`image: ghcr.io/procexaiedu/barra:${IMAGE_TAG}`,
      removendo `apt-get`/`git clone`/`uv sync`) e rodar o **drill de `docker service update --rollback`**.
      Recipe em `infra/runbooks/deploy-imagem-versionada.md`. (branch `feat/deploy-migrations`/CI já tem `build-image`.)
- [ ] **OBS-02 — subir Prometheus + Grafana + Alertmanager** (branch `feat/obs-monitoring`, code-only). Destrava
      `CUSTO-05` (alerta de write-rate de cache) e o scrape vivo de `EVAL-11` (`agente_eval_pass_rate`).
- [ ] **DEPLOY-05/06 — migrations:** banco de **staging separado** + **aplicar as migrations de schema** em prod
      **manualmente via psycopg** (nunca `make migrate` — aplica seeds). `schema_migrations` + drift-check no CI já em código.

---

## 5. Financeiro / ROI (migration pendente)

- [x] **CUSTO-01 — migration aplicada (verificado em prod 2026-06-02).** `vendedores`, `modelos.vendedor_id`,
      `atendimentos.vendedor_id` e `atendimentos.taxa_cartao_snapshot` existem no schema `barravips`. O bloco de
      ROI no dashboard (`custo_IA_por_fechado` vs `comissao_evitada`) já tem onde puxar dados. Resta o **cadastro
      operacional** (popular `vendedores` + setar `modelos.vendedor_id`) — ver `pre-launch-checklist.md` C-5.
      ADRs 0012/0013.

---

> **Nota:** o histórico completo das 44 tasks (com PRs/commits) está no git em
> `docs/mvp/producao-roadmap-executavel.md` antes do commit de remoção. Esta lista é só o que falta ao vivo.
