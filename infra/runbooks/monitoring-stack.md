# Stack de observabilidade — Prometheus + Grafana + Alertmanager (OBS-02 / CUSTO-05)

Entrega **code-only**: os 3 serviços (`prometheus-barra`, `alertmanager-barra`,
`grafana-barra`) já estão no `stack.barra-portainer.yml` (aditivos aos serviços de app) e
os configs versionados vivem em `infra/monitoring/`. O **deploy ao vivo no Swarm** — scrape
real, datasource, disparo de alerta — é **passo do operador** descrito abaixo.

## O que cada serviço faz

- `prometheus-barra` — clona a `main` no boot (mesmo padrão da api/worker, já que o Swarm
  não tem o repo no host), sobe com `--config.file=/repo/infra/monitoring/prometheus.yml`.
  Scrape de `barra-api:8000/metrics` (FastAPI) e `barra-worker:9091/metrics` (ARQ).
  Avalia `alert.rules.yml` e dispara para o Alertmanager. Interno à rede `traefik_public`.
- `alertmanager-barra` — sobe com `--config.expand-env` para expandir `${ALERT_WEBHOOK_URL}`.
  Rota única → receiver placeholder. Interno.
- `grafana-barra` — datasource Prometheus **e dashboards** provisionados de
  `infra/monitoring/grafana/provisioning` (`GF_PATHS_PROVISIONING`). Publicado via Traefik em
  `grafana-barra.procexai.tech`. O datasource tem `uid: prometheus` fixo p/ os dashboards
  referenciarem a fonte sem clique manual.

## Dashboards provisionados (`infra/monitoring/grafana/`)

Versionados no repo; sobem sozinhos no boot do `grafana-barra` (provider `file`, recarrega a
cada 30s). Aparecem na pasta **Elite Baby** do Grafana — nada de import manual.

| Arquivo | Conteúdo |
|---|---|
| `grafana/provisioning/dashboards/dashboards.yml` | Provider que carrega os `.json` de `grafana/dashboards/`. |
| `grafana/dashboards/elite-baby-visao-geral.json` | Dashboard **Elite Baby — Visão Geral** (uid `elite-baby-visao-geral`): 17 painéis em 4 seções — *Saúde & HTTP*, *Agente desempenho*, *Custo & tokens*, *Segurança & domínio*. Cada painel de p95/write-rate traz a linha tracejada no mesmo limiar dos alertas. |

> As queries batem com os nomes reais em `api/src/barra/core/metrics.py`. Métrica nova no código
> → novo painel aqui (mesmo `datasource.uid: prometheus`). Os contadores de segurança usam
> `… or vector(0)` p/ mostrar `0` em vez de *No data* quando ainda não houve evento.

> **Aplicação em prod via Swarm config (divergência conhecida):** se o `grafana-barra` em prod
> roda pelo *string-stack* com configs montadas (e não pelo clone-at-boot deste repo), o operador
> precisa, além das configs já existentes: (1) criar as Swarm configs do provider e do JSON,
> (2) montá-las sob `…/provisioning/dashboards/` e no `path` do provider, e (3) garantir
> `GF_PATHS_PROVISIONING` no serviço. No modelo clone-at-boot do `stack.barra-portainer.yml` nada
> disso é necessário — basta a `main` ter os arquivos e reiniciar o serviço.

## Sinais cobertos pelas regras (`infra/monitoring/alert.rules.yml`)

| Alerta | Métrica | Disparo |
|---|---|---|
| `AgenteSpikeEscaladaDefesa` | `agente_escalada_total{bucket="defesa"}` | `rate > 0.1/s` por 5m (ataque ativo) |
| `AgenteTaxaEscaladaCapacidadeAlta` | `agente_escalada_total{bucket="capacidade"}` / `agente_turno_resultado_total` | razão `> 15%` em 6h por 1h (deriva lenta de condução) |
| `AgenteVazamentoCrossModelo` | `agente_output_leak_total{motivo="cross_modelo"}` | `increase > 0` em 1h (**critical**, invariante #1) |
| `AgenteEvalOnlineCaiu` | `agente_eval_pass_rate{suite}` | média por suite `< 0.95` em 1h por 30m (4 suites: non_disclosure, system_leak, segredo_agenda, formato_bolha) |
| `AgenteAupSaidaJudgeFalhando` | `agente_aup_saida_bloqueado_total{resultado="judge_falhou"}` | `rate > 0.02/s` por 15m (Etapa 2 cega) |
| `AgenteCacheWriteRateAlto` (CUSTO-05) | `agente_turno_tokens_total{tipo=cache_write}` | write / (input+read+write) `> 15%` por 15m |
| `AgenteCustoTurnoAcimaDoAlvo` | `agente_custo_turno_brl` | p95 `> 0.12 BRL` por 15m |
| `AgenteLatenciaTurnoP95Alta` | `agente_turno_duracao_seconds` | p95 `> 20s` por 10m |
| `BarraHttpLatenciaP95Alta` | `barra_http_request_duration_seconds` | p95 `> 2s` por 10m |

> O alvo de custo `0.12` é literal nas regras. Quando a `feat/custo-roi` (CUSTO-06) entregar
> `settings.custo_alvo_brl`, alinhar o valor da regra `AgenteCustoTurnoAcimaDoAlvo`.

## Passos do operador (uma vez)

1. **Validar os configs** antes do deploy (exige Docker daemon vivo — não roda no CI offline):
   ```bash
   docker run --rm -v "$PWD/infra/monitoring:/cfg" --entrypoint promtool \
     prom/prometheus:v2.53.0 check config /cfg/prometheus.yml
   docker run --rm -v "$PWD/infra/monitoring:/cfg" --entrypoint promtool \
     prom/prometheus:v2.53.0 check rules /cfg/alert.rules.yml
   docker run --rm -v "$PWD/infra/monitoring:/cfg" --entrypoint amtool \
     prom/alertmanager:v0.27.0 check-config /cfg/alertmanager.yml
   ```
2. **Env vars da stack** (Portainer → stack `barra`):
   - `ALERT_WEBHOOK_URL` — destino real do alerta (endpoint do painel / relay WhatsApp).
   - `GRAFANA_ADMIN_PASSWORD` — senha admin do Grafana (default `admin` se omitida).
3. **Redeploy da stack** (`docker stack deploy -c stack.barra-portainer.yml barra
   --with-registry-auth` ou via Portainer). Os 3 serviços sobem sem tocar api/worker/redis.
4. **DNS/Traefik** — apontar `grafana-barra.procexai.tech` para o Swarm (o router Traefik já
   está nos labels do serviço).

## Verificação ao vivo

1. `prometheus-barra` → Status → Targets: `barra-api` e `barra-worker` **UP**.
   (Sem rota pública; ver pelo Grafana → Explore com a query `up`.)
2. Grafana abre em `grafana-barra.procexai.tech`, datasource Prometheus já presente.
3. Dashboards → pasta **Elite Baby** → **Visão Geral** carrega com os 17 painéis; o painel
   *Alvos coletados (UP)* mostra `2` e *Requests/s por status* tem série recente.
4. Status → Rules no Prometheus lista os 9 alertas (estado `inactive`/`pending`/`firing`).
5. Disparo de fumaça: gerar tráfego que eleve `agente_escalada_total{bucket=defesa}` (ou
   abaixar temporariamente o threshold) e confirmar a entrega no `ALERT_WEBHOOK_URL`.

| Data | Targets UP? | Datasource ok? | Regras carregadas? | Alerta entregue? | Operador |
|------|-------------|----------------|--------------------|------------------|----------|
|      |             |                |                    |                  |          |
