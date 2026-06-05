# Runbook — stack `barra-vips` git-backed (GitOps)

Procedimento do cutover do string-stack para git-backed e operação do dia a dia.
Contexto e decisões: ADR 0018. Stack: Portainer Swarm, endpoint `1`, SwarmId
`d77mkguumsddrqfu5t7unyi1t`. Compose: `infra/compose/stack.barra-portainer.yml` no `main`.

## Mudar config DEPOIS do cutover (o caminho novo)

- **Config não-sensível** (CORS, JIDs, modelos, flags): editar `stack.barra-portainer.yml`,
  abrir PR, mergear no `main`. O webhook redeploya. **Nunca** editar no UI do Portainer — a
  edição manual volta a ser fonte de "evaporação".
- **Segredo** (qualquer `${VAR}`): editar a **Env var** do stack no Portainer (não vai a PR).
  Exceção: a chave do MinIO é Swarm secret (rotacionar com `docker secret`).

> ⚠️ **Redeploy é só pelo webhook do GitHub.** O webhook **preserva** o `Env` guardado do
> stack. **Nunca** dispare um redeploy git pela **API/MCP** (`StackGitRedeploy`,
> `StackUpdateGit`) sem repassar o array `Env` completo: a API trata `Env` ausente como
> **vazio** e **sobrescreve os 12 segredos guardados de uma vez** → todo `${VAR}` resolve pra
> string vazia e o stack inteiro cai (api/worker dão `RuntimeError` no boot; o `redis-barra`
> sobe com `--requirepass` sem valor e some do DNS). Aconteceu em 2026-06-05 ao aplicar uma
> env via API. Se precisar redeployar fora do webhook, use o **UI do Portainer** (que mantém o
> `Env`) ou repasse o `Env` completo — e mesmo assim prefira o webhook.
>
> **Recuperar se zerou:** rollback Docker serviço-a-serviço (o daemon guarda o `PreviousSpec`
> com a env resolvida, então não precisa redigitar segredo). `redis-barra` **antes** de
> api/worker, senão eles não resolvem o host e ficam em loop:
> `POST /services/<nome>/update?version=<idx>&rollback=previous` (header `Content-Type:
> application/json`, body = o `Spec` atual verbatim; corpo `{}` falha com "mismatched Runtime
> and *Spec fields"). Depois **repovoar o `Env` guardado** no UI do Portainer (o rollback
> conserta os serviços, não o `Env` do stack).

## Cutover (uma vez)

Pré-requisitos:
1. `stack.barra-portainer.yml` reconciliado já no `main` (este refactor).
2. Swarm secret `minio_secret_key` existe. Verificar (`docker secret ls`); se não, criar do
   valor atual de `MINIO_SECRET_KEY`:
   `printf '%s' '<chave-minio>' | docker secret create minio_secret_key -`.
3. Salvar o YAML atual da stack (`StackFileInspect 144`) como artefato de rollback.
4. Listar os valores de todas as Env vars de segredo (copiar do YAML salvo) — ver tabela abaixo.
5. Git credential no Portainer (PAT com `repo:read` de `procexaiedu/barra`) — pode reusar o GITHUB_PAT.

Env vars de segredo a setar no `Env` do novo stack (nome → valor do YAML salvo):
`DATABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`,
`REDIS_PASSWORD`, `MINIO_ACCESS_KEY`, `ANTHROPIC_API_KEY`, `LANGCHAIN_API_KEY`,
`EVOLUTION_API_KEY`, `EVOLUTION_WEBHOOK_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, `GITHUB_PAT`.

> ⚠️ Sem `EVOLUTION_WEBHOOK_TOKEN` ou `SUPABASE_JWT_SECRET` a API dá `RuntimeError` no boot
> (fail-closed por design, `main.py:86-95`). Conferir a lista contra o YAML salvo.

Passos:
1. `StackDelete` da stack `barra-vips`. Recursos `external: true` (networks `traefik_public`/
   `supabase_default`, secret `minio_secret_key`, os 4 configs `barra_*`) **sobrevivem**.
   Volumes nomeados (`redis-barra-data` etc.) persistem pelo prefixo `barra-vips_` — **manter
   o nome `barra-vips`**.
2. Recriar como git repository stack (`StackCreateDockerSwarmRepository`):
   - `Name=barra-vips`, `endpointId=1`, `SwarmID=d77mkguumsddrqfu5t7unyi1t`
   - `RepositoryURL=https://github.com/procexaiedu/barra`, `RepositoryReferenceName=refs/heads/main`
   - `ComposeFile=infra/compose/stack.barra-portainer.yml`
   - `RepositoryAuthentication=true` + git credential
   - `Env=[...]` (tabela acima)
   - `AutoUpdate={Webhook:<uuid>}` (gera o webhook de redeploy)
3. Registrar a URL do webhook (`POST /api/stacks/webhooks/<uuid>`) como **webhook de push**
   do GitHub no repo (Settings → Webhooks). Push que altera o compose → redeploy.

## Verificação (pós-cutover)

- `curl https://api-barra.procexai.tech/health` → 200; `/ready` → 200.
- Preflight CORS: `elitebaby.procexai.tech` → 200; `<qualquer>.procexai.tech` → 200 (regex);
  `evil.com` → 400.
- Worker consumindo a fila ARQ; Redis com a fila intacta (volume persistido).
- `grafana-barra.procexai.tech` responde; Prometheus targets UP.
- Painel loga e carrega dados, 0 erro de console.
- `StackInspect` do novo id → `GitConfig` populado, `AutoUpdate.Webhook` setado.
- **Prova final:** PR alterando o compose (ex.: + um CORS origin de teste) → webhook redeploya
  sozinho → origin aparece no preflight, sem tocar no Portainer. Reverter o PR depois.

## Rollback

Se o git-backed falhar: `StackDelete` + recriar o **string-stack** (`StackCreateDockerSwarmString`)
a partir do YAML salvo no pré-requisito 3 → volta ao estado anterior em minutos.
