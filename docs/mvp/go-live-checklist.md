# Go-live checklist — pendências vivas pós-roadmap

> **O que é:** o que sobrou de pendente quando a fila de produção foi concluída e os docs de roadmap
> (`producao-roadmap-executavel.md`, `producao-prontidao-roadmap.md`, `gap-analysis-prontidao.md`,
> `COMO-EXECUTAR.md`) foram removidos (estão no histórico do git). Aqui ficam **só** os itens que ainda
> exigem ação ao vivo (operador, prod, segredo, calibração humana) — o **código** das tasks já está na `main`.
> Consolidado em 2026-06-01.
>
> Carrega também o **veredito GO/NO-GO** e o critério de **cutover** que o `docs/agente/08-evals.md` referencia.

---

## 1. Veredito GO/NO-GO (autoridade do cutover)

- **NO-GO para operação autônoma. GO condicional para piloto supervisionado** (humano-no-loop, 1 modelo).
- **Não expandir para a 2ª modelo** até a Onda 1 estar fechada ao vivo (segurança/infra/observabilidade).
- **Cutover do Vendedor → IA por modelo só depois que o gate de evals existir E PASSAR ao vivo** — não basta
  o código do runner estar na `main`: exige `EVAL-04/03` verdes em CI (K=5) + judge calibrado e **vinculante**
  (`EVAL-10`). Atendimento conduzido pela IA não gera comissão; antes do gate, a IA opera assistida.
- **Tese econômica (ROI) só é demonstrável** depois de `CUSTO-01`/`CUSTO-02` ao vivo (migration aplicada) —
  sem `valor_servico`/comissão/taxa em prod, "a IA lucra mais que o vendedor" não tem como ser medido.

---

## 2. Segurança — item aberto (ação #1)

- [ ] **DEPLOY-01 — rotacionar a `MINIO_SECRET_KEY`.** Status no roadmap era `done ⚠️ parcial`: o literal foi
      removido do stack, **mas a chave nunca foi rotacionada** e segue **recuperável no histórico de um repo
      público**. A deleção do arquivo **não** neutraliza o vazamento — só a rotação. Falta ainda: mover para
      **Swarm secret** + padrão `*_FILE` em `settings.py` + **unificar a credencial MinIO do worker**
      (`stack.barra-portainer.yml:82-83` vazio quebra mídia no worker). É a prioridade absoluta do projeto.

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

- [ ] **CUSTO-01 — aplicar a migration** (tabela `vendedores`, `modelos.vendedor_id`,
      `atendimentos.vendedor_id`/`taxa_cartao_snapshot`) em prod via psycopg. Sem ela o bloco de ROI no dashboard
      (`custo_IA_por_fechado` vs `comissao_evitada`) não tem dados. ADRs 0012/0013; branch `feat/custo-roi`.

---

> **Nota:** o histórico completo das 44 tasks (com PRs/commits) está no git em
> `docs/mvp/producao-roadmap-executavel.md` antes do commit de remoção. Esta lista é só o que falta ao vivo.
