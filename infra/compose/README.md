# Compose

Stacks Docker usadas pelo deploy via Portainer.

- `stack.barra-portainer.yml`: **fonte única de verdade da stack de produção `barra-vips`**,
  git-backed (o Portainer puxa do `main` e redeploya por webhook — ver ADR 0018 e
  `infra/runbooks/stack-git-backed.md`). Inclui a stack de observabilidade do OBS-02
  (`prometheus-barra` + `alertmanager-barra` + `grafana-barra`), aditiva aos serviços de app.
  Só o Grafana publica via Traefik (`grafana-barra.procexai.tech`); Prometheus e Alertmanager
  ficam internos à rede `traefik_public`. Inclui também o `barra-interface` (painel Next.js
  migrado da Vercel — `elitebaby.procexai.tech`), no mesmo padrão git-clone-no-boot de
  api/worker; cutover em `infra/runbooks/interface-portainer.md`.
- `stack.barra.yml`: esqueleto base/legado (Compose local, não é o que roda em produção).
- `env/`: exemplos de variáveis por serviço, sem segredos.

## Segredos (NÃO ficam no git)

O arquivo commitado usa placeholders `${VAR}`. Os valores reais vivem **fora do git**:

- **Env vars do stack no Portainer** (Portainer DB): `DATABASE_URL`, `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `REDIS_PASSWORD`, `MINIO_ACCESS_KEY`,
  `ANTHROPIC_API_KEY`, `LANGCHAIN_API_KEY`, `EVOLUTION_API_KEY`, `EVOLUTION_WEBHOOK_TOKEN`,
  `GRAFANA_ADMIN_PASSWORD`, `GITHUB_PAT`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
  `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`, `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` (as três `NEXT_PUBLIC_*`
  vêm da aba Environment Variables da Vercel; ver runbook da interface).
- **Swarm secret** `minio_secret_key` (external), lido via `MINIO_SECRET_KEY_FILE`
  (`settings.py` suporta o padrão `*_FILE`). Criado pelo operador:
  `printf '%s' '<chave-minio>' | docker secret create minio_secret_key -`.

Config **não-sensível** (CORS, JIDs, modelos, flags) é versionada aqui de propósito — é o que
impede config de "evaporar" em redeploys.

## Observabilidade (OBS-02 / CUSTO-05)

Configs versionados em `infra/monitoring/`, entregues como **docker configs externos**
(`barra_prometheus_yml_v1`, `barra_alert_rules_yml_v2`, `barra_alertmanager_yml_v2`,
`barra_grafana_ds_yml_v1`):

- `prometheus.yml`: scrape de `barra-api:8000/metrics` e `barra-worker:9091/metrics`.
- `alert.rules.yml`: regras dos 4 sinais do OBS-02 (spike de `agente_escalada_total{bucket=defesa}`,
  p95 de latência, custo por turno) + a regra CUSTO-05 de write-rate de cache (`agente_turno_tokens_total{tipo=cache_write}` > 15%).
- `alertmanager.yml`: rota única + receiver placeholder (`ALERT_WEBHOOK_URL`).
- `grafana/provisioning/datasources/prometheus.yml`: datasource Prometheus do Grafana.

Env vars opcionais da stack (Portainer): `ALERT_WEBHOOK_URL` (destino do alerta),
`GRAFANA_ADMIN_PASSWORD`. O deploy ao vivo (subir no Swarm, scrape real, disparo de alerta)
é passo do operador.
