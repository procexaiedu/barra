---
status: accepted
---

# Stack de produção git-backed (GitOps no Portainer)

A stack de produção `barra-vips` (Portainer Swarm) era um **string-stack editado à mão** no
UI, com **toda a config e todos os segredos inline** num YAML de ~220 linhas e **sem** vínculo
com o git (`AutoUpdate=null`, `GitConfig=null`). Sem fonte única de verdade, cada redeploy
significava colar o YAML inteiro de alguma cópia — e qualquer cópia defasada **apagava ou
corrompia** config silenciosamente. Em uma semana isso causou três incidentes da mesma raiz:
`CORS_ORIGINS` perdeu o domínio `elitebaby.procexai.tech` (interface fora do ar), o mesmo CORS
já tinha sumido antes, e a `SUPABASE_SERVICE_ROLE_KEY` do worker foi mutilada na edição manual.

Decidimos tornar o **repositório a fonte única de verdade** da definição da stack: o Portainer
puxa `infra/compose/stack.barra-portainer.yml` do `main` e redeploya por webhook. Mudança de
config (CORS, JIDs, flags) passa a ser **PR versionado**, não edição de UI.

## Decisões

- **Git-backed no mesmo repo.** A stack aponta para `procexaiedu/barra`,
  `infra/compose/stack.barra-portainer.yml`, ref `main`. Sem repo de infra separado (overhead
  de outro repo/PAT não se paga no estágio atual). O arquivo é **reconciliado com o que roda**
  — não com a versão stale que existia no git — e vira a verdade dali pra frente.
- **Segredos fora do git, em Env vars do Portainer.** O arquivo commitado usa placeholders
  `${VAR}` (DATABASE_URL, SUPABASE_*, REDIS_PASSWORD, MINIO_ACCESS_KEY, ANTHROPIC_API_KEY,
  LANGCHAIN_API_KEY, EVOLUTION_API_KEY, EVOLUTION_WEBHOOK_TOKEN, GRAFANA_ADMIN_PASSWORD,
  GITHUB_PAT). Os valores vivem na seção **Env** do stack (Portainer DB), setados uma vez e
  sobrevivem a redeploys do git. **A chave do MinIO** é o único segredo via **Swarm secret**
  (`minio_secret_key`, external), lido por `MINIO_SECRET_KEY_FILE` — `settings.py` já suporta o
  padrão `*_FILE` para esse campo (`_carregar_secrets_de_arquivo`).
- **Config não-sensível é versionada de propósito.** `CORS_ORIGINS`, `CORS_ORIGIN_REGEX`,
  os JIDs, modelos Anthropic, flags — tudo literal no arquivo. É exatamente o que mata a
  "evaporação": esses valores deixam de depender de quem cola qual YAML.
- **CORS por regex como rede de segurança.** Além da lista explícita, um
  `CORS_ORIGIN_REGEX` escopado a `*.procexai.tech` + `barra-*.vercel.app` garante que um
  domínio sumir da lista não derrube a interface. Passa no gate anti-curinga de `main.py`
  (regex que case origin arbitrária é proibido em produção).
- **Trigger por webhook (manual + auto em mudança do compose).** O webhook do stack no
  Portainer redeploya on-demand e é registrado como webhook de push do GitHub. Como
  `docker stack deploy` é idempotente, push que só mexe em código da app (compose inalterado)
  **não** recria api/worker.
- **git-clone-no-boot mantido (por ora).** api/worker seguem clonando o `main` + `uv sync` no
  boot. O cutover para imagem versionada do GHCR (DEPLOY-03) é decisão **separada**, não
  acoplada a esta. Tornar a stack git-backed controla a **definição** da infra, não a entrega
  do código da app.
- **Observabilidade via docker configs externos.** `prometheus`/`alertmanager`/`grafana`
  consomem `barra_prometheus_yml_v1` / `barra_alert_rules_yml_v2` / `barra_alertmanager_yml_v2`
  / `barra_grafana_ds_yml_v1` (todos `external: true`), como já roda em produção — não o
  git-clone-no-boot que a versão stale do arquivo usava.

## Consequências

- O cutover é **delete + recreate** da stack (Portainer não converte string↔git in-place),
  mantendo o nome `barra-vips` para preservar os volumes nomeados e os recursos externos
  (networks, secret, configs). Janela curta de indisponibilidade da API no recreate.
- Trocar um **segredo** continua sendo ação no Portainer (Env var) — não entra em PR.
- Procedimento operacional em `infra/runbooks/stack-git-backed.md`.
