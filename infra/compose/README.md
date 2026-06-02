# Compose

Stacks Docker usadas pelo deploy via Portainer.

- `stack.barra-portainer.yml`: stack principal (deploy via Portainer). Inclui a stack de
  observabilidade do OBS-02 (`prometheus-barra` + `alertmanager-barra` + `grafana-barra`),
  aditiva aos serviços de app. Só o Grafana publica via Traefik (`grafana-barra.procexai.tech`);
  Prometheus e Alertmanager ficam internos à rede `traefik_public`.
- `stack.barra.yml`: esqueleto base.
- `env/`: exemplos de variáveis por serviço, sem segredos.

## Observabilidade (OBS-02 / CUSTO-05)

Configs versionados em `infra/monitoring/`:

- `prometheus.yml`: scrape de `barra-api:8000/metrics` e `barra-worker:9091/metrics`.
- `alert.rules.yml`: regras dos 4 sinais do OBS-02 (spike de `agente_escalada_total{bucket=defesa}`,
  p95 de latência, custo por turno) + a regra CUSTO-05 de write-rate de cache (`agente_turno_tokens_total{tipo=cache_write}` > 15%).
- `alertmanager.yml`: rota única + receiver placeholder (`ALERT_WEBHOOK_URL`).
- `grafana/provisioning/datasources/prometheus.yml`: datasource Prometheus do Grafana.

Env vars opcionais da stack (Portainer): `ALERT_WEBHOOK_URL` (destino do alerta),
`GRAFANA_ADMIN_PASSWORD`. O deploy ao vivo (subir no Swarm, scrape real, disparo de alerta)
é passo do operador.
