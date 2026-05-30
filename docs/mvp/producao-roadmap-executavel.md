# Roadmap Executável de Produção — fila de tasks para agente Claude

> **O que é:** versão executável-por-agente do `producao-prontidao-roadmap.md`. Cada task é autocontida (um Claude sem contexto prévio consegue executá-la), com critério de sucesso **verificável por comando** e dependências explícitas.
>
> **Fontes de verdade (não duplicar, consultar):** o racional e os tradeoffs vivem em `producao-prontidao-roadmap.md` (narrativo, por ondas), nos ADRs `docs/adr/` e em `CONTEXT.md`/`CLAUDE.md`. Os achados por eixo estão em `gap-analysis-prontidao.md`. **Este arquivo é a FILA DE EXECUÇÃO** — marque `Status: done` aqui ao concluir; não reescreva os documentos-fonte.
>
> Gerado em 2026-05-29 a partir do roadmap verificado adversarialmente.

---

## Protocolo de consumo (leia antes de pegar qualquer task)

1. **Escolha a próxima task** cujo `Depende de` esteja todo `done` e `Status: todo`, priorizando Onda 1 > 2 > 3 e, dentro da onda, risco maior primeiro. Se houver `win`, são bons primeiros PRs.
2. **Trabalhe isolado:** crie um git worktree/branch dedicado (`git worktree add`). Nunca trabalhe direto na `main`. `git add` por caminho explícito; **não** inclua arquivos órfãos do working tree que você não criou (ex.: `hero.jpeg`, `docs/agente-visao-cliente.html`).
3. **Antes de codar** (CLAUDE.md §1): se a task tiver ambiguidade real, pare e pergunte; não escolha em silêncio. Se houver caminho mais simples que o descrito, proponha.
4. **Execute os Passos**, respeitando os **Guardrails globais** abaixo + os específicos da task.
5. **Verifique** rodando o comando/checagem do campo `Verificação`. A task só é `done` quando a verificação passa. Critério fraco ("funciona") não conta — rode o teste/grep/asserção.
6. **Um PR por task** (ou poucas tasks coesas). Mensagem de commit termina com a linha `Co-Authored-By` padrão do projeto. Não pushe/mescle sem o operador pedir.
7. **Marque `Status: done`** nesta fila e referencie o commit/PR.

---

## Guardrails globais (herdados por TODA task)

- **Banco de produção é self-hosted (`db.procexai.tech:5433`).** **NUNCA rode `make migrate` em prod** — ele aplica os seeds `infra/sql/00NN_seed_*.sql` (dados de teste descartáveis). Migration de **schema** em prod: aplicar **manualmente** via psycopg/MCP (MCP = prod real, exige aprovação "Production Reads/Writes"). Sem migration framework: SQL sequencial em `infra/sql/NNNN_*.sql`.
- **O agente/LLM roda no `barra-worker` (ARQ), não na `api`.** Redeploy de prompt/agente/grafo **exige reiniciar o worker** (não só a api), senão fica prompt antigo. Confirme o commit por `revision_id` no trace LangSmith. Nunca `docker restart` em container Swarm (cria task órfão que duplica entregas) — use `service update --force`.
- **Isolamento por par cliente-modelo é invariante de domínio.** Toda query do agente filtra `(cliente_id, modelo_id)`. A barreira é a camada de dados (repo SQL), nunca a boa-vontade do modelo. Nenhuma leitura/retorno de tool pode trazer dado de outra modelo.
- **Persona/voz/FAQ são GERAIS e compartilhadas** entre todas as modelos. Só "as coisas dela" (identidade, programas, agenda, fetiches) variam. Não customize voz por modelo.
- **Pix nunca trava o fluxo.** Divergência/suspeita → `pix_status` duvidoso + fila assíncrona de Fernando, nunca bloqueio síncrono.
- **psycopg3 puro (sem ORM, ADR 0002).** Coluna `jsonb` exige `json.dumps(...)` + placeholder `%s::jsonb` (dict cru → 500). `UUID`-string em `INSERT...SELECT` precisa `::uuid` explícito.
- **Convenções de código:** domínio em PT-BR, infra em EN; sempre `from barra.x import y` (src layout em `api/src/barra/`); feature-first em `dominio/` (cada contexto tem seu `routes/service/repo/modelos/schemas`); não existem `models/`/`services/` globais.
- **LangGraph:** nós de decisão roteiam por `Command(goto=...)`; nó com `Command(goto=END)` **não** pode ter `add_edge` estático de saída. Sem checkpointer (P0) → sem restart de superstep; resiliência fica no re-enqueue do job ARQ.
- **Prompt caching:** prefixo byte-idêntico entre requests; nunca ponha dado volátil (timestamp/contador/dado do cliente) antes do `system`; mín. 1024 tokens/breakpoint no Sonnet 4.6.
- **Backend local (Windows):** subir com `python -m barra` / `make dev` (Selector loop antes do uvicorn; o auto força Proactor e pendura o psycopg async). O backend local não sobe inteiro (lifespan pinga Redis do swarm) — para verificação visual use as rotas whitelisted (`/demo-mapa`, `/painel-preview`).
- **Princípios (CLAUDE.md):** mínimo de código que resolve; mudanças cirúrgicas (toda linha ligada ao pedido); não refatorar o que não está quebrado; toda task termina com verificação concreta.

---

## Índice de tasks

| ID | Onda | Task | Depende de | Status |
|---|---|---|---|---|
| DEPLOY-01 | 1 | Rotacionar segredos → Swarm secrets | — | done ⚠️ parcial |
| SEC-03 | 1 | Endurecer download de mídia (SSRF/DoS) | — | done |
| SEC-02 | 1 | Filtrar `numero_curto` por modelo | — | done |
| DEPLOY-02 | 1 | Healthcheck + readiness no Traefik | — | done |
| DEPLOY-04 | 1 | Backup do Postgres + runbook | — | todo |
| DEPLOY-03 | 1 | Imagem versionada + update start-first/rollback | — | todo |
| SEC-10 | 1 | Anonymizer de PII antes de ligar tracing | — | done |
| OBS-04 | 1 | Sentry no worker | — | done |
| OBS-01 | 1 | Expor `/metrics` do worker | — | done |
| OBS-03 | 1 | Logging estruturado JSON | — | done |
| PER-05/TOOLS-01 | 1 | `refusal` escala em vez de silenciar | — | done |
| TOOLS-02 | 1 | Exceção de API escala com motivo próprio | — | done |
| WIN-TOOLS-05 | win | guarda `try/except` na parse de data | — | done |
| WIN-PER-08 | win | interpolar `localizacao_operacional` | — | done |
| WIN-PER-12 | win | remover stub `humanizacao.py` + corrigir doc | — | done |
| WIN-TOOLS-09 | win | minimizar payload Pix (sem chave/titular) | — | done |
| WIN-SEC-06 | win | `hmac.compare_digest` no token do webhook | — | done |
| WIN-SEC-09 | win | guard de CORS no boot em produção | — | done |
| WIN-REL-09 | win | não enfileirar `loc_pin` (renderer NotImplemented) | — | done |
| WIN-DEPLOY-10 | win | corrigir README do stack real | — | done |
| EVAL-01 | 2 | Runner de evals mínimo + `make evals` | — | todo |
| EVAL-08 | 2 | `NodesVisitedHandler` + `state_check` | EVAL-01 | todo |
| EVAL-02 | 2 | LLM-judge binário + fixture de DUAS modelos (ADR 0015) | EVAL-01 | todo |
| EVAL-10 | 2 | Calibrar judge contra golden humano (ADR 0015) | EVAL-02 | todo |
| EVAL-04/03 | 2 | Loop K=5 + CI bloqueante | EVAL-01, DEPLOY-03 | todo |
| SEC-07 | 2 | Cobrir AUP fora do regex como fixtures | EVAL-02 | todo |
| AGENTE-OG | 2 | Output-guard de saída antes da bolha (ADR 0016) | EVAL-02 | todo |
| REL-05 | 2 | `cobrar_valor_final` com `FOR UPDATE SKIP LOCKED` | — | todo |
| REL-02 | 2 | `abrir_handoff` idempotente | — | todo |
| REL-06 | 2 | Mídia que falha upload não vira `texto` silencioso | — | todo |
| REL-03 | 2 | `max_tries` consciente por job | — | done |
| REL-04 | 2 | `vision_client` com timeout/retries | — | todo |
| REL-08 | 2 | Escalada crítica resiliente a `atendimento_id` nulo | — | todo |
| REL-12 | 2 | Visibilidade de falha final não-crítica | OBS-04 | done |
| OBS-02 | 2 | Prometheus + Grafana + Alertmanager | OBS-01 | todo |
| OBS-07 | 2 | Middleware de request-id api→worker | OBS-03 | done |
| OBS-09/10 | 2 | Tag `modelo_id`/`atendimento_id` nos traces | SEC-10 | done |
| TOOLS-04 | 2 | Incrementar `AGENTE_ESCALADA` após `abrir_handoff` | — | done |
| CUSTO-02 | 3 | Custo de STT + vision por atendimento | — | todo |
| CUSTO-01 | 3 | Comissão + Taxa de cartão + ROI (ADRs 0012/0013) | CUSTO-02 | todo |
| CUSTO-04 | 3 | Teto de turnos por conversa/dia + retry-after | — | done |
| CUSTO-05 | 3 | Alerta de write-rate de cache | OBS-02 | todo |
| CUSTO-06 | 3 | Fonte única do alvo de custo | — | todo |
| PER-01/03 | 3 | Diálogos canônicos com rubrica de voz | EVAL-01 | todo |
| PER-11 | 3 | Reminder anti-drift `<armadilhas_de_voz>` | EVAL-01 | todo |
| TOOLS-06 | 3 | Counter `agente_tool_erro_recuperavel_total` | — | done |
| TOOLS-08 | 3 | Eval de recall de `escalar` (AUP ambíguo) | EVAL-01 | todo |
| EVAL-11 | 3 | `agente_eval_pass_rate` online (amostra) | EVAL-01 | todo |
| DEPLOY-05/06 | 3 | `schema_migrations` + drift-check + staging | DEPLOY-03 | todo |
| OBS-05 | 3 | Resolver config de tracing morta/duplicada | SEC-10 | done |

---

# ONDA 1 — Bloqueantes de go-live

### DEPLOY-01 — Rotacionar e mover segredos para Swarm secrets
- **Status:** done ⚠️ parcial (decisão do operador, 2026-05-29) · **Onda:** 1 · **Dimensão:** Deploy+Segurança · **Depende de:** — · **Fonte:** roadmap §3.1
- **⚠️ Nota de integridade (2026-05-29):** marcado concluído por decisão do operador. **Feito:** removido o literal do segredo de `stack.barra-portainer.yml`. **PENDENTE / risco aceito:** a chave MinIO **não foi rotacionada**; o repo `procexaiedu/barra` estava **PÚBLICO** pela API do GitHub neste momento; o segredo segue **recuperável no histórico do git**; Swarm secret + padrão `*_FILE` em `settings.py` + unificação da credencial do worker **não foram implementados**. A deleção do arquivo **não neutraliza** o vazamento — só a rotação. Reabrir esta task se for de fato tratar a exposição.
- **Prioridade absoluta:** é a ação #1 do projeto — secret MinIO em texto claro num repo clonado a cada deploy.
- **Objetivo (DoD):** nenhuma credencial literal no repo; api e worker leem a mesma credencial MinIO via secret; pipeline de mídia funciona no worker.
- **Arquivos:** `infra/compose/stack.barra-portainer.yml:13,19-20,76,82-83`, `api/src/barra/settings.py`, `infra/runbooks/`.
- **Passos:** (1) rotacionar `MINIO_SECRET_KEY` no provedor JÁ; (2) mover para Swarm secrets + padrão `*_FILE` em `settings.py`; (3) preencher a credencial no worker (`:82-83` vazio quebra mídia); (4) documentar no runbook.
- **Verificação:** `git grep AdxUPS6` (ou a secret rotacionada) retorna vazio no HEAD; `docker service inspect` não expõe a secret; STT/vision no worker não pulam por `minio is None`.
- **Guardrails específicos:** segredo é vivo — rotacione antes de qualquer outra coisa.

### SEC-03 — Endurecer `_baixar_midia` (SSRF + DoS)
- **Status:** done (2026-05-29, branch `sec-03-midia`) · **Onda:** 1 · **Dimensão:** Segurança · **Depende de:** — · **Fonte:** roadmap §3.1
- **Objetivo (DoD):** download de mídia recusa host fora da allowlist, não segue redirect e aborta acima do teto de bytes.
- **Arquivos:** `api/src/barra/webhook/routes.py:32-41`.
- **Passos:** (1) validar host de `msg.media_url` contra o host de `settings.evolution_base_url`; (2) `follow_redirects=False`; (3) `httpx.stream` abortando acima de `settings.midia_max_bytes` (~25MB) em vez de `resp.content`.
- **Verificação:** teste que (a) URL de host fora da allowlist é recusada, (b) corpo > limite aborta, (c) mídia legítima da Evolution passa.

### SEC-02 — Filtrar `numero_curto` por modelo
- **Status:** done (PR #52, 2026-05-30) · **Onda:** 1 · **Dimensão:** Segurança · **Depende de:** — · **Fonte:** roadmap §3.1
- **Objetivo (DoD):** comando `#N` no grupo só afeta o atendimento da modelo correta — sem corrupção financeira cross-modelo.
- **Arquivos:** `api/src/barra/webhook/routes.py:416-429` (TODO em :417-418) + call site `_processar_grupo` (~:271).
- **Passos:** resolver `modelo_id` via `msg.instance_id`/`evolution_instance_id` (padrão de `_instance_cadastrada`/`_persistir_cliente`) e adicionar `AND modelo_id = %s`; recusar comando com erro curto no grupo se a modelo não resolver.
- **Verificação:** fixture com dois grupos de coordenação, mesmo `#N` em modelos distintas — `fechado #N` só afeta o atendimento da modelo certa.
- **Guardrails específicos:** invariante de isolamento por par.

### DEPLOY-02 — Healthcheck + readiness no Traefik
- **Status:** done (branch `deploy-02-healthcheck`, 2026-05-30) · **Onda:** 1 · **Dimensão:** Deploy · **Depende de:** — · **Fonte:** roadmap §3.1
- **Implementado:** `healthcheck` em `barra-api` (bate `/ready` via o `python` da própria imagem — `uv:slim` não tem curl/wget — `start_period:300s` cobrindo `apt-get`+`git clone`+`uv sync`) e em `barra-worker` (bate o `/metrics` em `:9091` do OBS-01, healthcheck de processo); label Traefik `loadbalancer.healthcheck.path=/ready` (+`interval=10s`) na api. Quando o DB cai, `/ready` responde não-2xx (erro do `pool.connection()`), então o healthcheck falha e o Traefik tira a réplica do pool — sem tocar `main.py`. **Verificado:** `docker compose config` exit 0 + parse YAML do healthcheck/labels. **Passo ao vivo do operador:** confirmar num deploy real que o Traefik não roteia durante o `uv sync` e que `docker service ps` marca a task `unhealthy` com o DB fora — exige Swarm vivo. **Nota:** o `:9091` do worker é best-effort (OSError no bind é engolido p/ não derrubar o worker); num host single-replica não colide, mas se o bind falhar o healthcheck do worker reprova.
- **Objetivo (DoD):** Traefik não roteia para container ainda em `uv sync`.
- **Arquivos:** `infra/compose/stack.barra-portainer.yml` (api e worker); `/ready` já existe em `main.py:81`.
- **Passos:** `healthcheck` da api batendo `/ready` com `start_period` cobrindo clone+`uv sync`; label `traefik...loadbalancer.healthcheck.path=/ready`; healthcheck de processo para o worker.
- **Verificação:** durante um deploy, Traefik não roteia até `/ready` retornar 200; `docker service ps` mostra task `unhealthy` quando o DB cai.

### DEPLOY-04 — Backup do Postgres + runbook de restore
- **Status:** todo · **Onda:** 1 · **Dimensão:** Deploy · **Depende de:** — · **Fonte:** roadmap §3.1
- **Objetivo (DoD):** existe backup diário do Postgres (única fonte de verdade) e um restore já foi executado uma vez.
- **Arquivos:** `infra/runbooks/` (novo runbook); cron no host self-hosted (pgBackRest ou `pg_dump` + WAL archiving).
- **Verificação:** restore mensal num schema/instância de teste reconstrói o histórico; documento de restore existe e foi rodado.
- **Guardrails específicos:** operar no host self-hosted; não tocar dados de prod além do dump.

### DEPLOY-03 — Imagem versionada + update start-first/rollback
- **Status:** todo · **Onda:** 1 · **Dimensão:** Deploy · **Depende de:** — · **Fonte:** roadmap §3.1
- **Objetivo (DoD):** deploy por imagem versionada, com rollback testado e sem worker órfão duplicando entregas.
- **Arquivos:** `.github/workflows/ci.yml` (novo, builda `api/Dockerfile`), `infra/compose/stack.barra-portainer.yml:47,109`.
- **Passos:** CI builda e pusha tag/digest; stack referencia a imagem (remover `apt-get`/`git clone`/`uv sync` do command); `deploy.update_config:{order:start-first,failure_action:rollback}` + `rollback_config` + `stop_grace_period:30s`.
- **Verificação:** `docker service update --rollback` testado; um deploy não causa 502 nem worker órfão (1 só task ARQ drenando o Redis).
- **Guardrails específicos:** compartilha o arquivo `ci.yml` com EVAL-04/03 — coordene para não conflitar.

### SEC-10 — Anonymizer de PII obrigatório antes de ligar tracing
- **Status:** done (PR #53, 2026-05-30) · **Onda:** 1 · **Dimensão:** Observabilidade+Segurança · **Depende de:** — · **Fonte:** roadmap §3.2 (novo)
- **Objetivo (DoD):** tracing só ativa com PII mascarada; com `tracing=True` mas sem anonymizer construível, o tracing **não** sobe.
- **Arquivos:** `api/src/barra/core/tracing.py:1` (stub), `api/src/barra/settings.py:146-152`, startup de `build_app()` e `workers/settings.py`.
- **Passos:** (1) `setup_tracing()` constrói o `Client` LangSmith com `anonymizer=create_anonymizer(...)` cobrindo inputs/outputs/metadata (chave/titular Pix, telefone/JID, nome, endereço, conteúdo livre); (2) instalar no startup da api **e** do worker; (3) hard gate: anonymizer não-construível → força `LANGCHAIN_TRACING_V2=false` + `warning`; (4) default `langchain_tracing_v2=False` em `:150`.
- **Verificação:** (a) teste com chave-Pix/endereço de fixture sai mascarado ao `Client` mock; (b) boot com `tracing=True` sem anonymizer **não** ativa tracing; (c) `git grep create_anonymizer api/src` retorna a impl importada no startup de api e worker.
- **Guardrails específicos:** o agente roda no worker — o setup tem de rodar lá também.

### OBS-04 — Sentry no worker
- **Status:** done (PR #57, 2026-05-30) · **Onda:** 1 · **Dimensão:** Observabilidade · **Depende de:** — · **Fonte:** roadmap §3.2
- **Objetivo (DoD):** exceção no pipeline da IA (worker) aparece no Sentry com tag `turno_id`.
- **Arquivos:** `core/tracing.py` (extrair `init_sentry()`), `main.py:54-55`, `workers/settings.py:startup`.
- **Verificação:** exceção forçada em `coordenador.py` aparece no Sentry com `turno_id`.

### OBS-01 — Expor `/metrics` do worker
- **Status:** done (PR #46, 2026-05-30) · **Onda:** 1 · **Dimensão:** Observabilidade · **Depende de:** — · **Fonte:** roadmap §3.2
- **Objetivo (DoD):** métricas emitidas no worker são scrapeáveis.
- **Arquivos:** `workers/settings.py:startup` → `prometheus_client.start_http_server(9091)` sob guard.
- **Verificação:** `curl worker:9091/metrics` retorna `agente_turno_duracao`/`agente_custo_turno_brl`.

### OBS-03 — Logging estruturado JSON
- **Status:** done (PR #60, 2026-05-30) · **Onda:** 1 · **Dimensão:** Observabilidade · **Depende de:** — · **Fonte:** roadmap §3.2
- **Objetivo (DoD):** logs em prod saem JSON com `turno_id`/`atendimento_id`; o `INFO` do coordenador deixa de cair no chão.
- **Arquivos:** `core/logging.py` (stub) → structlog JSON em stdout no nível de `settings.log_level`; setup em `build_app()` e `workers/settings.py:startup`; bindar IDs do `ContextAgente`.
- **Verificação:** logs de prod são JSON com os IDs; teste de que o setup é chamado nos dois entrypoints.

### PER-05/TOOLS-01 — `refusal` escala em vez de silenciar
- **Status:** done (PR #54, 2026-05-30) · **Onda:** 1 · **Dimensão:** Resiliência · **Depende de:** — · **Fonte:** roadmap §3.3 + ADR-relacionado (stop_reason)
- **Objetivo (DoD):** quando o Sonnet recusa, abre handoff para Fernando (`modelo_recusou`), IA pausa, cliente não fica mudo; `stop_details.category` logado. Mesmo princípio no vision do Pix.
- **Arquivos:** `agente/nos/llm.py:99-102`, `workers/coordenador.py:165,444-477`, `workers/pix.py:165-170`.
- **Passos:** (1) no ramo `refusal`, sinalizar `_stop_reason="refusal"` via state + logar `stop_details.category` de `resp.response_metadata`; (2) no coordenador, após `ainvoke`, acionar `escalar_por_exaustao(motivo="modelo_recusou")` (infra já existe; bucket `defesa`); (3) vision do Pix: checar `finish_reason`/`stop_reason` (chegam em 200 OK), `max_tokens`/`refusal` → comprovante duvidoso (fila de Fernando), nunca `ValueError` silencioso.
- **Verificação:** fixture adversarial dispara refusal → handoff aberto (`tipo=outro`, `bucket=defesa`, `motivo=modelo_recusou`), `ia_pausada=true`, nenhuma bolha ao cliente, `stop_details.category` no log. Teste irmão no vision com `finish_reason=max_tokens` → comprovante duvidoso.
- **Guardrails específicos:** Pix nunca trava; nunca reenviar conteúdo cru de refusal ao cliente.

### TOOLS-02 — Exceção de API escala com motivo próprio
- **Status:** done (PR #51, 2026-05-30) · **Onda:** 1 · **Dimensão:** Resiliência · **Depende de:** — · **Fonte:** roadmap §3.3
- **Objetivo (DoD):** 5xx/timeout persistente da API vira escalada com `motivo=modelo_indisponivel` e bucket correto.
- **Arquivos:** `workers/coordenador.py:165` (capturar `RateLimitError/APITimeoutError/APIStatusError` antes do `except Exception`), `agente/ferramentas/escalada.py:41-43` (+`modelo_indisponivel` no enum), `dominio/escaladas/service.py:364-374` (bucket `infra`).
- **Verificação:** simular 5xx persistente → escalada com `motivo=modelo_indisponivel` e bucket correto.

## Wins seguros (Onda 1 — P, risco baixo, sem refatoração)

### WIN-TOOLS-05 — guarda na parse de data
- **Status:** done (PR #40, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** `try/except ValueError` nas duas `date.fromisoformat` em `agente/ferramentas/leitura.py:31-32` → retorna `"ERRO: data inválida, use YYYY-MM-DD."`; teste com data malformada recebe o ERRO recuperável.

### WIN-PER-08 — interpolar `localizacao_operacional`
- **Status:** done (PR #45, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** `prompts/identidade.md.j2:5` usa `localizacao_operacional` (fallback genérico se null) no lugar de "Rio" hardcoded; render de uma modelo de SP não contém "Rio".

### WIN-PER-12 — remover stub `humanizacao.py` + corrigir doc
- **Status:** done (PR #41, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** stub `agente/humanizacao.py` removido e `agente/CLAUDE.md:37` aponta `workers/`; `git grep` não acha import do stub.

### WIN-TOOLS-09 — minimizar payload Pix
- **Status:** done (PR #47, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** `agente/ferramentas/pix.py:110-116` e `_idempotencia.py:45` reduzem payload a `{valor}`; `eventos`/`tool_calls` não guardam `chave`/`titular` em claro.
- **Guardrails específicos:** dado sensível nunca em enum/schema/eventos.

### WIN-SEC-06 — `hmac.compare_digest` no token do webhook
- **Status:** done (PR #44, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** `webhook/routes.py:60` usa `hmac.compare_digest` (timing-safe) em vez de `!=`.

### WIN-SEC-09 — guard de CORS no boot em produção
- **Status:** done (PR #42, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** `main.py` (antes do `add_middleware`) aborta o boot se `cors_origins` tiver `*`/regex amplo quando `ambiente=="producao"`; teste de boot falha com `*`.

### WIN-REL-09 — não enfileirar `loc_pin`
- **Status:** done (PR #43, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** `agente/ferramentas/extracao.py:133-139` não enfileira `card:loc_pin` enquanto `_card_loc_pin` for `NotImplementedError` (ou implementar o renderer em `workers/envio.py:320`); atendimento interno não gera job que falha 5x.

### WIN-DEPLOY-10 — corrigir README do stack real
- **Status:** done (PR #39, 2026-05-30) · **Onda:** win · **Depende de:** — · **Fonte:** roadmap §4
- **DoD/Verificação:** `infra/compose/README.md:5` aponta `stack.barra-portainer.yml` como o stack real.

---

# ONDA 2 — Robustez e o gate que autoriza o cutover

### EVAL-01 — Runner de evals mínimo + `make evals`
- **Status:** todo · **Onda:** 2 · **Dimensão:** Evals · **Depende de:** — · **Fonte:** roadmap §3.4
- **Objetivo (DoD):** existe um runner que carrega as fixtures `.jsonl`, roda o grafo real e falha com exit-code ≠ 0 abaixo do threshold.
- **Arquivos:** `api/evals/runners/runner.py` (novo; reusar `_seed_*` de `tests/agente/test_fixtures_leitura_decisao.py`), `api/Makefile` (alvo `evals`).
- **Passos:** carregar fixtures, seedar estado, invocar o grafo por fixture, capturar `tool_calls` + estado final, aplicar graders determinísticos (`tool_calls_obrigatorias/proibidas`, `nao_deve_conter` regex, `ia_pausada_final`, `state_check`), emitir exit-code de gate.
- **Verificação:** `make evals` roda as fixtures e falha abaixo do threshold; PR que quebra uma fixture reprova.
- **Guardrails específicos:** `state_check` consulta o banco — use `TEST_DATABASE_URL` com rollback, nunca prod.

### EVAL-08 — `NodesVisitedHandler` + `state_check`
- **Status:** todo · **Onda:** 2 · **Dimensão:** Evals · **Depende de:** EVAL-01 · **Fonte:** roadmap §3.4
- **Objetivo (DoD):** o runner reprova quando um nó proibido foi visitado e quando o estado final diverge.
- **Arquivos:** `runner.py` — `BaseCallbackHandler` registrando nós (`nodes_proibidos`), avaliador de estado pós-invoke via query.
- **Verificação:** fixture `prompt_injection/001` com `nodes_proibidos:['tools']` reprova se a tool foi chamada.

### EVAL-02 — LLM-judge binário + fixture de DUAS modelos (ADR 0015)
- **Status:** todo · **Onda:** 2 · **Dimensão:** Evals+Segurança · **Depende de:** EVAL-01 · **Fonte:** roadmap §3.4 + **ADR 0015**
- **Objetivo (DoD):** rubricas `judge:llm` declaradas nas fixtures têm implementação; gate AUP exige `pass^5` (0 vazamento em K=5) em `non_disclosure`/`deve_negar_identidade`/cross-modelo.
- **Arquivos:** `api/evals/runners/judge.py` + `judge.md` (novos), `adversariais/{explicito,gaslighting,prova}/`, `cross_modelo/`, `disclosure/`, `jailbreak/`, `prompt_injection/` (≥6 fixtures cada; cross-modelo com dados de DUAS modelos no banco de teste).
- **Passos:** judge recebe só o `texto_resposta` (e histórico quando a rubrica é de drift), devolve `{passou,score,justificativa}` via structured output, Sonnet 4.6; rubrica binária por critério (sem comparação A/B); instruções anti-viés no `judge.md` (ignorar comprimento; julgar só o critério). **Ler ADR 0015 antes.**
- **Verificação:** gate `pass^5` reprova com 1 vazamento em 5 runs num fluxo crítico; fixture cross-modelo com dados de 2 modelos confirma que a IA da modelo A não cita dado do cliente com a modelo B.
- **Guardrails específicos:** golden set NÃO reusa fixtures do gate (evita leak por fixture reutilizada). Enquanto não calibrado (EVAL-10), o judge é **advisory** (loga+flag), não bloqueia.

### EVAL-10 — Calibrar judge contra golden humano (ADR 0015)
- **Status:** todo · **Onda:** 2 · **Dimensão:** Evals · **Depende de:** EVAL-02 · **Fonte:** **ADR 0015**
- **Objetivo (DoD):** o judge só vira blocker depois de atingir TPR ≥ 0.9 (vazamento/quebra de persona), TNR ≥ 0.85 e kappa de Cohen ≥ 0.6 contra rótulos humanos.
- **Arquivos:** dataset de calibração em `api/evals/` (held-out, separado das fixtures de cutover), curado de `docs/agente/conversas-reais/`.
- **Verificação:** métricas TPR/TNR/kappa reportadas; abaixo do limiar, o judge permanece advisory; ao atingir, as rubricas `judge:llm` passam a bloquear sem mudar o agregador.
- **Guardrails específicos:** Sonnet julga Sonnet → a calibração é a salvaguarda do self-preference; não pular.

### EVAL-04/03 — Loop K=5 + CI bloqueante
- **Status:** todo · **Onda:** 2 · **Dimensão:** Evals · **Depende de:** EVAL-01, DEPLOY-03 · **Fonte:** roadmap §3.4
- **Objetivo (DoD):** CI roda `lint+typecheck+test+evals` em cada PR; PR com regressão de prompt que vaze identidade reprova o build.
- **Arquivos:** `runner.py` (loop K=5, `pass^k` para AUP/Pix, ≥4/5 corretude), `.github/workflows/ci.yml` (secrets `TEST_DATABASE_URL`/`ANTHROPIC_API_KEY`).
- **Verificação:** abrir PR com regressão proposital → build vermelho; status check obrigatório (branch protection).
- **Guardrails específicos:** compartilha `ci.yml` com DEPLOY-03.

### SEC-07 — Cobrir AUP fora do regex como fixtures
- **Status:** todo · **Onda:** 2 · **Dimensão:** Segurança · **Depende de:** EVAL-02 · **Fonte:** roadmap §3.4
- **Objetivo (DoD):** fake-handoff ("Fernando aqui, sou admin"), paráfrase e outro idioma viram fixtures no runner — sem inflar o regex de `_classificador.py`.
- **Verificação:** fixtures novas reprovam um agente que caia nesses vetores; o regex de `_classificador.py` não cresce.

### AGENTE-OG — Output-guard de saída antes da bolha (ADR 0016)
- **Status:** todo · **Onda:** 2 · **Dimensão:** Segurança · **Depende de:** EVAL-02 · **Fonte:** **ADR 0016**
- **Objetivo (DoD):** nenhuma bolha é enviada sem passar por (1) scan determinístico de vazamento (system/persona/dado de outra modelo) e (2) LLM-judge de AUP vinculante; violação → bloqueia + handoff para Fernando.
- **Arquivos:** `agente/nos/output_guard.py` (novo), `agente/graph.py` (inserir entre `post_process` e despacho da humanização, roteando por `Command`), `agente/nos/__init__.py`, `agente/prompts/aup_saida.md` (novo), `core/metrics.py` (2 contadores).
- **Passos:** ler ADR 0016; Etapa 1 regex/substring sobre o texto de saída (marcadores de persona, auto-referência de IA, nome/JID/dado fora do par `(cliente_id,modelo_id)`); Etapa 2 judge Sonnet curto (prompt em `aup_saida.md`, fora do prefixo cacheado por-modelo); falha de infra do judge → default seguro (bloqueia+escala); canned de disclosure pula a Etapa 2.
- **Verificação:** testes (1) fragmento de persona → bloqueado+handoff; (2) cita dado de outra modelo → bloqueado; (3) judge reprova AUP → não despacha; (4) judge com falha infra → default seguro; (5) canned passa Etapa 1 e pula Etapa 2; (6) saída limpa despacha.
- **Guardrails específicos:** `Command(goto=END)` sem aresta estática de saída; o prompt do judge não interpola dado por-modelo (não afeta cache do chat). Reusa `aup_saida.md` do judge de EVAL-02 onde fizer sentido.

### REL-05 — `cobrar_valor_final` com `FOR UPDATE SKIP LOCKED`
- **Status:** todo · **Onda:** 2 · **Dimensão:** Confiabilidade · **Depende de:** — · **Fonte:** roadmap §3.5
- **DoD/Verificação:** `workers/lembrete_valor.py:67` (espelhar `workers/timeouts.py`), SELECT+envio em transação; 2 workers simultâneos não disparam o mesmo card 2x.

### REL-02 — `abrir_handoff` idempotente
- **Status:** todo · **Onda:** 2 · **Dimensão:** Confiabilidade · **Depende de:** — · **Fonte:** roadmap §3.5
- **DoD/Verificação:** `dominio/escaladas/service.py:409` com guarda `NOT EXISTS (... fechada_em IS NULL)` (padrão de `lembrete_valor.py:93-98`); re-drain/retry não abre escalada duplicada.

### REL-06 — Mídia que falha upload não vira `texto` silencioso
- **Status:** todo · **Onda:** 2 · **Dimensão:** Confiabilidade · **Depende de:** — · **Fonte:** roadmap §3.5
- **DoD/Verificação:** `webhook/routes.py:338-348` + `workers/pix.py:207-213`; comprovante Pix com upload falho re-tenta (idempotente por `evolution_message_id`) ou marca mídia-pendente, em vez de cair no timeout-24h como `Perdido`.
- **Guardrails específicos:** Pix nunca some/trava.

### REL-03 — `max_tries` consciente por job
- **Status:** done (PR #62, 2026-05-30) · **Onda:** 2 · **Dimensão:** Confiabilidade · **Depende de:** — · **Fonte:** roadmap §3.5
- **DoD/Verificação:** `workers/settings.py:156` → `func(processar_turno, keep_result=0, max_tries=2)` (turno caro), `max_tries=3` para envios; erro transitório pós-LLM não reinvoca o Sonnet 5x.
- **Guardrails específicos:** `keep_result=0` (memória: `keep_result=3600` quebra re-enqueue do ARQ).

### REL-04 — `vision_client` com timeout/retries
- **Status:** todo · **Onda:** 2 · **Dimensão:** Confiabilidade · **Depende de:** — · **Fonte:** roadmap §3.5
- **DoD/Verificação:** `workers/settings.py:114-117` → `timeout=60.0, max_retries=3` (espelhar `openai_client`); vision Pix pendurado não segura slot por 400s.

### REL-08 — Escalada crítica resiliente a `atendimento_id` nulo
- **Status:** todo · **Onda:** 2 · **Dimensão:** Confiabilidade · **Depende de:** — · **Fonte:** roadmap §3.5
- **DoD/Verificação:** `workers/envio.py:506-522` carrega `atendimento_id` mesmo de atendimento terminal para o handoff (ou alerta dedicado distinto de `falha_evolution`); efeito crítico (Pix) nunca termina sem handoff/alerta.

### REL-12 — Visibilidade de falha final não-crítica
- **Status:** done (PR #61, 2026-05-30) · **Onda:** 2 · **Dimensão:** Confiabilidade · **Depende de:** OBS-04 · **Fonte:** roadmap §3.5
- **DoD/Verificação:** `workers/envio.py:520-521` loga `error` com `turno_id`+request_id e captura no Sentry; mensagem perdida ao cliente fica visível à operação.

### OBS-02 — Prometheus + Grafana + Alertmanager
- **Status:** todo · **Onda:** 2 · **Dimensão:** Observabilidade · **Depende de:** OBS-01 · **Fonte:** roadmap §3.6
- **DoD/Verificação:** stack de métricas com scrape de api e worker; regras versionadas (spike de `agente_escalada_total{bucket=defesa}`, write-rate de cache, p95, custo) disparam.

### OBS-07 — Middleware de request-id api→worker
- **Status:** done (PR #64, 2026-05-30) · **Onda:** 2 · **Dimensão:** Observabilidade · **Depende de:** OBS-03 · **Fonte:** roadmap §3.6
- **DoD/Verificação:** request-id propagado da API até o worker junto do `turno_id`; aparece nos logs JSON.

### OBS-09/10 — Tag `modelo_id`/`atendimento_id` nos traces
- **Status:** done (PR #59, 2026-05-30) · **Onda:** 2 · **Dimensão:** Observabilidade · **Depende de:** SEC-10 · **Fonte:** roadmap §3.6
- **DoD/Verificação:** traces LangSmith carregam `modelo_id`/`atendimento_id` (gen_ai.conversation.id) via `core/tracing.py`, sem inflar o label de cache.
- **Guardrails específicos:** só depois do anonymizer (SEC-10) — não ligar tracing cru.

### TOOLS-04 — Incrementar `AGENTE_ESCALADA` após `abrir_handoff`
- **Status:** done (PR #49, 2026-05-30) · **Onda:** 2 · **Dimensão:** Observabilidade · **Depende de:** — · **Fonte:** roadmap §3.6
- **DoD/Verificação:** `intercept_disclosure.py` (~:60,~:99) incrementa `AGENTE_ESCALADA` após `abrir_handoff` para jailbreak/disclosure aparecerem em `bucket=defesa`.

---

# ONDA 3 — Otimização, economia e prova de ROI

### CUSTO-02 — Custo de STT + vision por atendimento
- **Status:** todo · **Onda:** 3 · **Dimensão:** Custo · **Depende de:** — · **Fonte:** roadmap §3.7
- **DoD/Verificação:** `workers/pix.py:167` lê `resposta.usage`; `workers/media.py:282` usa `resposta.duration`; `core/metrics.py` ganha Histograms de custo STT/vision; `custo_por_atendimento_brl` soma chat+STT+vision.

### CUSTO-01 — Comissão + Taxa de cartão + ROI (ADRs 0012/0013)
- **Status:** todo · **Onda:** 3 · **Dimensão:** Custo · **Depende de:** CUSTO-02 · **Fonte:** roadmap §3.7 + ADRs 0012/0013
- **Objetivo (DoD):** dashboard responde "a IA custou R$X e evitou R$Y de comissão neste mês, por modelo".
- **Arquivos:** `infra/sql/` (tabela `vendedores`, `modelos.vendedor_id`, `atendimentos.vendedor_id`/`taxa_cartao_snapshot`), `dominio/financeiro/{repo,service,routes}.py`, `dominio/dashboard/`.
- **Passos:** `valor_servico = Valor final − taxa`; comissão = nível×`valor_servico` (independente do repasse); bloco ROI no dashboard (`custo_IA_por_fechado` vs `comissao_evitada`). **Ler ADRs 0012/0013.**
- **Verificação:** dashboard mostra o ROI por modelo; testes do cálculo (taxa só sobre serviço, nunca sobre Pix de deslocamento; só `Fechado` conta).
- **Guardrails específicos:** migration de schema → aplicar manual em prod self-hosted (sem `make migrate`).

### CUSTO-04 — Teto de turnos por conversa/dia + retry-after
- **Status:** done (PR #58, 2026-05-30) · **Onda:** 3 · **Dimensão:** Custo · **Depende de:** — · **Fonte:** roadmap §3.7
- **DoD/Verificação:** contador Redis por conversa escala a Fernando ao estourar (fecha o loop do `RECURSION_LIMIT` dormente, `coordenador.py:45`); respeita `retry-after`; cliente em loop não queima orçamento até as 24h.

### CUSTO-05 — Alerta de write-rate de cache
- **Status:** todo · **Onda:** 3 · **Dimensão:** Custo · **Depende de:** OBS-02 · **Fonte:** roadmap §3.7
- **DoD/Verificação:** regra Alertmanager sobre `agente_turno_tokens_total{tipo=cache_write}` disparando >15% em regime (espelha o invariante de `agente/CLAUDE.md`).

### CUSTO-06 — Fonte única do alvo de custo
- **Status:** todo · **Onda:** 3 · **Dimensão:** Custo · **Depende de:** — · **Fonte:** roadmap §3.7
- **DoD/Verificação:** `settings.custo_alvo_brl` referenciado em `core/metrics.py:96` e no runner; eliminado o divergente 0.12 vs 0.05.

### PER-01/03 — Diálogos canônicos com rubrica de voz
- **Status:** todo · **Onda:** 3 · **Dimensão:** Persona+Evals · **Depende de:** EVAL-01 · **Fonte:** roadmap §3.8
- **DoD/Verificação:** diálogos de `docs/agente/conversas-reais/` destilados em `evals/canonicos/scripted_5/` com rubrica de voz julgada por LLM; rodam no runner.

### PER-11 — Reminder anti-drift `<armadilhas_de_voz>`
- **Status:** todo · **Onda:** 3 · **Dimensão:** Persona · **Depende de:** EVAL-01 · **Fonte:** roadmap §3.8
- **DoD/Verificação:** `prepare_context.py:259` re-ancora 2-3 pares `<armadilhas_de_voz>` (sem `cache_control`), validado por fixture multi-turno (drift em turno tardio).
- **Guardrails específicos:** fora do prefixo cacheado; voz é GERAL (não por modelo).

### TOOLS-06 — Counter `agente_tool_erro_recuperavel_total`
- **Status:** done (PR #56, 2026-05-30) · **Onda:** 3 · **Dimensão:** Observabilidade · **Depende de:** — · **Fonte:** roadmap §3.8
- **DoD/Verificação:** counter `{tool,motivo}` nos pontos de `"ERRO:"`; aparece em `/metrics`.

### TOOLS-08 — Eval de recall de `escalar` (AUP ambíguo)
- **Status:** todo · **Onda:** 3 · **Dimensão:** Evals · **Depende de:** EVAL-01 · **Fonte:** roadmap §3.8
- **DoD/Verificação:** gate de capacidade (dashboard, não blocker) medindo recall de `escalar` para AUP ambíguo.

### EVAL-11 — `agente_eval_pass_rate` online (amostra)
- **Status:** todo · **Onda:** 3 · **Dimensão:** Evals · **Depende de:** EVAL-01 · **Fonte:** roadmap §3.8
- **DoD/Verificação:** métrica online amostrando ~5-10% dos turnos com rubrica binária de `non_disclosure`.

### DEPLOY-05/06 — `schema_migrations` + drift-check + staging
- **Status:** todo · **Onda:** 3 · **Dimensão:** Deploy · **Depende de:** DEPLOY-03 · **Fonte:** roadmap §3.8
- **DoD/Verificação:** tabela `schema_migrations` + drift-check no CI; banco de staging separado; guarda de ambiente bloqueando seeds em prod.
- **Guardrails específicos:** esta task é o que torna seguro aplicar migration — até ela existir, schema em prod é manual.

### OBS-05 — Resolver config de tracing morta/duplicada
- **Status:** done (PR #63, 2026-05-30) · **Onda:** 3 · **Dimensão:** Observabilidade · **Depende de:** SEC-10 · **Fonte:** roadmap §3.8
- **DoD/Verificação:** config de tracing em `settings.py:146-148` deixa de ter fonte duplicada/morta; uma única fonte de verdade (reconciliada com SEC-10).

---

## Como marcar progresso

Ao concluir uma task: edite o campo `Status:` dela para `done` e a linha correspondente no Índice; anote o commit/PR ao lado. Tasks bloqueadas ficam `blocked(by T-…)` até a dependência virar `done`. Este arquivo é a fila viva; o racional permanece nos documentos-fonte.
