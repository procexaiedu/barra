# Deploy por imagem versionada + rollback (DEPLOY-03)

Hoje api e worker sobem da imagem `astral-sh/uv` e **clonam o repo no boot**
(`apt-get` + `git clone` + `uv sync`). Isso causa: boot lento, deploy não-reprodutível
(sempre o `HEAD` da `main`) e nenhum caminho de rollback. A DEPLOY-03 introduz uma
**imagem buildada pela CI** e prepara o stack para o cutover.

> **Estado atual (entrega code-only):** a CI já builda/publica a imagem e o stack já carrega
> a estratégia de update/rollback (`update_config`/`rollback_config`/`stop_grace_period`). O
> **cutover do `command`** (trocar `image:` para o GHCR e remover o `git clone` do boot) é o
> **passo do operador** descrito abaixo — pendente de billing dos Actions liberado e da
> imagem confirmada publicada. Até lá o boot segue via `git clone` (sem quebrar prod).

## O que a CI faz

`.github/workflows/ci.yml` → job `build-image` (depende de `verify`):

- **PR:** builda `api/Dockerfile` para validar (sem push).
- **Push em `main`:** builda e publica no GHCR:
  - `ghcr.io/procexaiedu/barra:sha-<commit-completo>` — **imutável**, é o que se fixa por deploy.
  - `ghcr.io/procexaiedu/barra:latest` — conveniência (move a cada push em main).

Api e worker usam a **mesma** imagem; o worker só troca o `command` para `arq`.

> ⚠️ O job `build-image` exige **GitHub Actions com billing ativo**. Em 30/05 o billing
> estava travado ("account is locked") — enquanto não regularizar, a imagem **não é
> publicada** e o cutover abaixo não pode acontecer.

## Cutover do operador (uma vez, quando a imagem existir)

No `stack.barra-portainer.yml`, para **cada** serviço (`barra-api` e `barra-worker`):

1. Trocar `image: ghcr.io/astral-sh/uv:python3.12-bookworm-slim` por
   `image: ghcr.io/procexaiedu/barra:${IMAGE_TAG:-latest}`.
2. Remover o `command:` de `apt-get`/`git clone`/`uv sync`:
   - **api:** sem `command` (usa o `CMD` da imagem: `uvicorn ... --proxy-headers`).
   - **worker:** `command: ["arq", "barra.workers.settings.WorkerSettings"]`.
3. Remover o `working_dir: /app` (a imagem já define `/app`).
4. Ajustar o `start_period` dos healthchecks de `300s` para algo menor (~30s) — sem
   `uv sync` no boot, o app sobe em segundos.

Os healthchecks da DEPLOY-02 e os `labels` do Traefik **permanecem** — continuam sendo o
sinal de readiness que torna `failure_action: rollback` confiável.

## Pré-requisito: credencial de pull do GHCR no Swarm

Se a imagem/repo estiver **privado**, cada nó do Swarm precisa de credencial. No host (ou
via Portainer → Registries), autentique no GHCR com um PAT de escopo `read:packages`:

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u procexaiedu --password-stdin
```

Em deploy de stack, garanta `--with-registry-auth` para propagar a credencial aos nós:

```bash
docker stack deploy -c stack.barra-portainer.yml barra --with-registry-auth
```

(Portainer faz isso ao associar o registry GHCR à stack.)

## Deploy de uma versão

1. Confirme que o `build-image` da `main` passou e publicou a tag `sha-<commit>`.
2. Na stack do Portainer, defina a env var **`IMAGE_TAG=sha-<commit>`** (NÃO use `latest`
   em prod — tag imutável é o que torna o rollback determinístico).
3. Redeploy da stack. O `update_config` cuida da ordem:
   - **api** → `order: start-first` — sobe a task nova e saudável antes de derrubar a
     velha (sem 502; pareia com o readiness/healthcheck do DEPLOY-02).
   - **worker** → `order: stop-first` — derruba o worker velho **antes** de subir o novo,
     mantendo **1 único consumidor ARQ** no Redis. `start-first` deixaria dois workers no
     overlap → entrega duplicada de jobs.

## Rollback

`failure_action: rollback` reverte automaticamente se a task nova falhar dentro do
`monitor` (30s) — a detecção de "unhealthy" depende do healthcheck do DEPLOY-02; sem ele,
só um crash dentro da janela dispara o rollback automático.

Rollback manual para o spec anterior (imagem anterior inclusa):

```bash
docker service update --rollback barra_barra-api
docker service update --rollback barra_barra-worker
```

> Em Swarm, **nunca** `docker restart` (cria task órfã que duplica entregas no ARQ).
> Use sempre `service update` / `--rollback`.

## Verificação do rollback (drill do operador)

Rode uma vez para provar o caminho (não-executável pelo agente — exige Swarm vivo):

1. Deploy de `sha-A` (ok). Anote `docker service ps barra_barra-api`.
2. Deploy de `sha-B`. Durante o update, confira que o Traefik não retorna 502 (api) e que
   `docker service ps barra_barra-worker` mostra só **1** task `Running` (sem órfão).
3. `docker service update --rollback barra_barra-api` → volta para `sha-A` sem downtime.

| Data | Versão (de→para) | 502 na api? | Worker órfão? | Rollback ok? | Operador |
|------|------------------|-------------|---------------|--------------|----------|
|      |                  |             |               |              |          |
