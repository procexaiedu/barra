# Roadmap de Prontidão para Produção — Agente Elite Baby

> Documento de arquitetura. Base: auditoria de gaps VERIFICADOS contra o código real em `C:\barra`. Tudo ancorado em `file:line`. Foco: levar a IA por modelo a produção e PROVAR que lucra mais que o vendedor humano.
>
> Gerado por workflow multi-agente (108 agentes, 8 dimensões, gaps verificados adversarialmente) em 2026-05-29.

---

## 1. Sumário Executivo e Veredito GO/NO-GO

### O sistema funciona ponta-a-ponta hoje?

**Sim, para 1 modelo em piloto supervisionado.** O caminho crítico está implementado e coeso:

- **Ingestão:** webhook com 3 gates (token, JID allowlist, instance cadastrada) + dedupe por `evolution_message_id` (`webhook/routes.py`).
- **Concorrência:** debounce first-wins (`webhook/despacho.py`), lock por conversa com heartbeat (`core/redis.py`), drain bounded (`workers/coordenador.py`).
- **Agente:** contexto montado do zero por turno com isolamento por par `(cliente_id, modelo_id)` em todas as queries (`agente/nos/prepare_context.py`), prompt caching com 4 breakpoints byte-idênticos (`agente/llm.py`), Sonnet 4.6 sem fallback, defesa AUP determinística (`_classificador.py` + `nos/intercept_disclosure.py`).
- **Entrega:** humanização com chunking/timing/cancel-on-new/mark-after-send idempotente (`workers/_chunking.py` + `workers/envio.py`).
- **Crons:** timeouts 24h/45min, Pix, lembrete de fechamento, reengajamento (`workers/timeouts.py`, `pix.py`, `lembrete_valor.py`).

**O agente em si NÃO precisa ser refeito.** Os problemas estão no INVÓLUCRO (deploy/infra), na BORDA (segurança), na OBSERVABILIDADE de produção e na ausência de GATE executável.

### O que falta para LUCRAR MAIS que a operação manual?

A tese econômica **não é demonstrável hoje**. Três lacunas encadeadas:

1. **Custo-IA por turno é medido mas incompleto.** `AGENTE_CUSTO_TURNO_BRL` (`core/metrics.py:94`, observado em `agente/nos/llm.py:55`) cobre só o chat Sonnet. STT (Whisper) e vision Pix (OpenRouter) só medem DURAÇÃO, não custo (`core/metrics.py:151,166`) — o `.usage` do OpenRouter é descartado (`workers/pix.py:167`). Custo real por atendimento com áudio + comprovante é subestimado.
2. **Custo não é atribuível ao negócio.** A métrica é rotulada por nome do modelo Anthropic (cardinalidade de cache), não por `modelo_id` da agência nem agregável por `atendimento_id`. Não dá para responder "qual modelo dá prejuízo".
3. **Não existe o outro lado da conta.** Comissão de vendedor e Taxa de cartão (ADRs 0012/0013 **aceitos**) **não existem em código** — `dominio/financeiro/` só calcula repasse bruto/líquido-de-repasse. Sem `valor_servico` (Valor final − taxa) nem comissão, é impossível computar "comissão evitada pela IA" vs "custo da IA".

**Não há instrumentação de ROI por atendimento. O objetivo central do projeto não tem como ser medido.**

### Veredito: **NO-GO** para autônomo / **GO condicional** para piloto supervisionado

O agente está pronto para um piloto com humano-no-loop. **Não está pronto para operar autônomo nem para expandir para a 2a modelo** até fechar a Onda 1. Cutover do vendedor só após o gate de evals existir e passar (Onda 2).

---

## 2. Top Blockers de Produção

| ID | Blocker | Âncora | Ação concreta |
|---|---|---|---|
| **DEPLOY-01** | Secret MinIO em texto claro commitada no git | `infra/compose/stack.barra-portainer.yml:19-20` | Rotacionar `MINIO_SECRET_KEY` JÁ; mover para Swarm secrets + padrão `*_FILE` em `settings.py`; unificar com worker (`:82-83` vazio quebra mídia do worker) |
| **SEC-03** | Download de mídia sem teto nem allowlist (SSRF + DoS) | `webhook/routes.py:32-41` | Validar host vs `settings.evolution_base_url`; `follow_redirects=False`; stream com limite de bytes em vez de `resp.content` |
| **SEC-02** | `numero_curto` resolvido global → corrupção financeira cross-modelo | `webhook/routes.py:416-429` (TODO em :417-418) | Resolver `modelo_id` via `msg.instance_id` + `AND modelo_id = %s`; recusar se modelo não resolvida |
| **DEPLOY-04** | Sem backup do Postgres (única fonte de verdade) nem Redis AOF | `workers/settings.py:108` (sem checkpointer) + ausência total no repo | `pg_dump` diário + WAL archiving (ou pgBackRest); runbook de restore; teste mensal |
| **DEPLOY-02** | Nenhum healthcheck; Traefik roteia para container ainda em `uv sync` | `stack.barra-portainer.yml` (sem `healthcheck:`); `/ready` em `main.py:81` órfão | `healthcheck` batendo `/ready` com `start_period` generoso + label Traefik `loadbalancer.healthcheck.path=/ready` |
| **OBS-04** | Sentry não inicializa no worker (pipeline da IA cego) | `main.py:54-55` só; `workers/settings.py:100-127` nunca chama | Extrair init para `core/tracing.py`; chamar no startup do worker sob o mesmo guard |
| **OBS-01** | Métricas do worker inalcançáveis (`/metrics` só na API) | `main.py:97-99` vs emissão em `workers/*` | `prometheus_client.start_http_server(9091)` no `workers/settings.py` startup |
| **DEPLOY-03** | Clone-main em runtime, sem versão/rollback; `docker restart` → workers órfãos duplicam entregas | `stack.barra-portainer.yml:47/:109` | Imagem versionada (Dockerfile já existe em `api/Dockerfile`); `update_config` start-first + rollback; `docker service update` |
| **PER-05 / TOOLS-01** | `stop_reason=refusal` só loga; cliente fica mudo, sem handoff | `agente/nos/llm.py:99-102` (TODO aberto) | No ramo refusal acionar `escalar_por_exaustao(motivo="modelo_recusou")` (já existe em `coordenador.py:444`, enum/bucket já existem) |
| **SEC-01 / EVAL-01..04** | Gate de evals AUP/isolamento é documento, não comando | `api/evals/runners/` só `.gitkeep` | Runner mínimo (graders determinísticos + LLM-judge binário) com fixture de DUAS modelos; gate K=5, 0-vazamento antes do cutover |
| **CUSTO-01** | Tese econômica não respondível (sem comissão/taxa/ROI) | `dominio/financeiro/` (sem comissão/taxa) | Implementar ADRs 0012/0013 + bloco ROI no dashboard |

---

## 3. Roadmap por Ondas

### ONDA 1 — Bloqueantes de go-live e wins de baixo risco

> Objetivo: tornar seguro e observável o suficiente para um PILOTO supervisionado de 1 modelo. Nada aqui é refatoração; tudo é fechar furos.

#### 3.1 Segurança e Infra (DIMENSÃO: Deploy + Segurança)

**[DEPLOY-01] Rotacionar e mover segredos para Swarm secrets** — *esforço M, risco médio*
- Tocar: `infra/compose/stack.barra-portainer.yml` (remover literais `:13,:19-20,:76`), `api/src/barra/settings.py` (aceitar `*_FILE`), `infra/runbooks/` (documentar).
- Verificação: `git grep AdxUPS6` retorna vazio no HEAD; `docker service inspect` não expõe a secret; worker e api leem a mesma credencial MinIO e o pipeline de mídia funciona no worker (STT/vision não pulam por `minio is None`).

**[SEC-03] Endurecer `_baixar_midia`** — *esforço M, risco baixo*
- Tocar: `webhook/routes.py:32-41`.
- Ações: (1) validar host de `msg.media_url` contra o host de `settings.evolution_base_url`; (2) `follow_redirects=False`; (3) `httpx.stream` abortando acima de `settings.midia_max_bytes` (~25MB).
- Verificação: teste que (a) URL de host fora da allowlist é recusada, (b) corpo > limite aborta, (c) mídia legítima da Evolution passa.

**[SEC-02] Filtrar `numero_curto` por modelo** — *esforço M, risco baixo*
- Tocar: `webhook/routes.py:416-429` + call site `_processar_grupo` (~:271) para passar `msg.instance_id`.
- Ação: resolver `modelo_id` via `evolution_instance_id` (padrão já usado em `_instance_cadastrada`/`_persistir_cliente`) e adicionar `AND modelo_id = %s`; recusar comando com erro curto no grupo se modelo não resolvida.
- Verificação: fixture/teste com dois grupos de coordenação, mesmo `#N` em modelos distintas — `fechado #N` só afeta o atendimento da modelo certa.

**[DEPLOY-02] Healthcheck + readiness no Traefik** — *esforço M, risco baixo*
- Tocar: `infra/compose/stack.barra-portainer.yml` (api e worker).
- Ações: `healthcheck` da api batendo `/ready` com `start_period` cobrindo clone+`uv sync`; label `traefik...loadbalancer.healthcheck.path=/ready`; healthcheck de processo para o worker.
- Verificação: durante um deploy, Traefik não roteia até `/ready` retornar 200; `docker service ps` mostra task `unhealthy` quando DB cai.

**[DEPLOY-04] Backup do Postgres + runbook de restore** — *esforço G, risco baixo*
- Tocar: `infra/runbooks/` (novo runbook), cron de backup (pgBackRest ou `pg_dump` + WAL archiving) no host self-hosted.
- Verificação: restore mensal num schema/instância de teste reconstrói histórico; documento de restore existe e foi executado uma vez.

**[DEPLOY-03] Imagem versionada + update start-first/rollback** — *esforço G, risco médio*
- Tocar: criar `.github/workflows/ci.yml` que builda `api/Dockerfile` (já existe) e pusha tag/digest; `stack.barra-portainer.yml` (referenciar a imagem, remover `apt-get`/`git clone`/`uv sync` do command, adicionar `deploy.update_config: {order: start-first, failure_action: rollback}` + `rollback_config` + `stop_grace_period: 30s`).
- Verificação: rollback testado (`docker service update --rollback`); um deploy não causa 502 nem worker órfão (verificar 1 só task ARQ drenando o Redis).

#### 3.2 Observabilidade (DIMENSÃO: Observabilidade)

**[OBS-04] Sentry no worker** — *esforço P, risco baixo*
- Tocar: `core/tracing.py` (hoje stub) extrair `init_sentry()`; chamar em `main.py:54-55` E `workers/settings.py:startup`.
- Verificação: exceção forçada em `coordenador.py` aparece no Sentry com tag `turno_id`.

**[OBS-01] Expor /metrics do worker** — *esforço M, risco baixo*
- Tocar: `workers/settings.py:startup` → `prometheus_client.start_http_server(9091)` sob guard.
- Verificação: `curl worker:9091/metrics` retorna `agente_turno_duracao`/`agente_custo_turno_brl`.

**[OBS-03] Logging estruturado** — *esforço M, risco baixo*
- Tocar: `core/logging.py` (stub) → structlog JSON em stdout, nível de `settings.log_level`; chamar setup em `build_app()` e `workers/settings.py:startup`; bindar IDs do `ContextAgente`.
- Verificação: logs em prod saem JSON com `turno_id`/`atendimento_id`; `INFO` do coordenador deixa de cair no chão.

#### 3.3 Correção do agente (DIMENSÃO: Persona/Tools + Resiliência)

**[PER-05 / TOOLS-01] refusal escala em vez de silenciar** — *esforço M, risco médio*
- Tocar: `agente/nos/llm.py:99-102` (sinalizar via state `_stop_reason="refusal"`) + `workers/coordenador.py:165` (escalar após `ainvoke`, espelhando timeout/recursion).
- Verificação: fixture adversarial que dispara refusal → handoff para Fernando aberto, IA pausada; cliente não fica mudo sem alerta.

**[TOOLS-02] Exceção de API escala com motivo próprio** — *esforço M, risco médio*
- Tocar: `workers/coordenador.py:165` (capturar `RateLimitError/APITimeoutError/APIStatusError` antes do `except Exception`), `agente/ferramentas/escalada.py:41-43` (+`modelo_indisponivel` no enum), `dominio/escaladas/service.py:364-374` (bucket `infra` ou consciente em capacidade).
- Verificação: simular 5xx persistente → escalada com `motivo=modelo_indisponivel` e bucket correto.

**Wins seguros de Onda 1** (P, risco baixo, sem refatoração):
- **[TOOLS-05]** `try/except ValueError` nas duas `date.fromisoformat` em `agente/ferramentas/leitura.py:31-32` → `"ERRO: data inválida, use YYYY-MM-DD."`
- **[PER-08]** Interpolar `localizacao_operacional` em `prompts/identidade.md.j2:5` em vez de "Rio" hardcoded (fallback genérico se null).
- **[PER-12]** Remover stub `agente/humanizacao.py` e corrigir `agente/CLAUDE.md:37` para apontar `workers/`.
- **[TOOLS-09]** Reduzir payload de `pedir_pix_deslocamento` a `{valor}` em `agente/ferramentas/pix.py:110-116` E em `_idempotencia.py:45` (remover `chave`/`titular` em claro de `eventos` e `tool_calls`).
- **[SEC-06]** Trocar `!=` por `hmac.compare_digest` no gate de token em `webhook/routes.py:60`.
- **[SEC-09]** Validar no boot que `cors_origins` não tem `*`/regex amplo quando `ambiente=="producao"` (`main.py` antes do `add_middleware`).
- **[REL-09]** Não enfileirar `card:loc_pin` enquanto `_card_loc_pin` for `NotImplementedError` (`agente/ferramentas/extracao.py:133-139`) — ou implementar o renderer em `workers/envio.py:320`.
- **[DEPLOY-10]** Corrigir `infra/compose/README.md:5` para apontar `stack.barra-portainer.yml` como o stack real.

---

### ONDA 2 — Robustez e o GATE que autoriza o cutover

> Objetivo: tornar a operação autônoma confiável e construir o mecanismo que prova segurança (AUP/isolamento) antes de tirar o humano do loop.

#### 3.4 Gate de Evals executável (DIMENSÃO: Evals + Segurança)

**[EVAL-01] Runner mínimo** — *esforço G, risco médio*
- Tocar: criar `api/evals/runners/runner.py` (reusar `_seed_*` de `tests/agente/test_fixtures_leitura_decisao.py`), graders determinísticos (`tool_calls_obrigatorias/proibidas`, `nao_deve_conter` regex, `ia_pausada_final`, `state_check`), exit-code de gate; alvo `make evals` em `api/Makefile`.
- Verificação: `make evals` roda fixtures e falha abaixo do threshold.

**[EVAL-08] `NodesVisitedHandler` + `state_check`** — *esforço M, risco médio*
- Tocar: `runner.py` — `BaseCallbackHandler` registrando nós (`nodes_proibidos`), avaliador de estado pós-invoke via query no banco.
- Verificação: fixture `prompt_injection/001` com `nodes_proibidos:['tools']` reprova se a tool foi chamada.

**[SEC-01 / EVAL-02] LLM-judge binário + fixture de DUAS modelos** — *esforço G, risco alto*
- Tocar: `api/evals/runners/judge.py` + `judge.md`; popular `adversariais/{explicito,gaslighting,prova}/` e elevar `cross_modelo/disclosure/jailbreak/prompt_injection` para ≥6 fixtures (fixture cross-modelo com dados de DUAS modelos no banco de teste).
- Verificação: gate AUP exige `pass^5` (0 vazamento em K=5) em `non_disclosure`/`deve_negar_identidade`/cross-modelo; judge calibrado contra ~30 labels humanos (κ) antes de virar vinculante (**EVAL-10**).

**[EVAL-04 / EVAL-03] K=5 + CI** — *esforço M, risco médio*
- Tocar: `runner.py` (loop K=5, `pass^k` para AUP/Pix, ≥4/5 corretude); `.github/workflows/ci.yml` (lint + typecheck + test + evals em PR; secrets `TEST_DATABASE_URL`/`ANTHROPIC_API_KEY`).
- Verificação: PR com regressão de prompt que vaze identidade reprova o build.

**[SEC-07]** Cobrir AUP fora do regex (fake-handoff "Fernando aqui sou admin", paráfrase, idioma) como fixtures no runner — não inflar o regex de `_classificador.py`.

#### 3.5 Resiliência operacional (DIMENSÃO: Confiabilidade)

**[REL-05] `cobrar_valor_final` com `FOR UPDATE SKIP LOCKED`** — *esforço M, risco médio*
- Tocar: `workers/lembrete_valor.py:67` (espelhar `workers/timeouts.py`), envolver SELECT+envio em transação.
- Verificação: 2 workers simultâneos não disparam o mesmo card 2x.

**[REL-02] `abrir_handoff` idempotente** — *esforço P, risco baixo*
- Tocar: `dominio/escaladas/service.py:409` (guarda `NOT EXISTS (... fechada_em IS NULL)`, reusar padrão de `lembrete_valor.py:93-98`).
- Verificação: re-drain/retry não abre escalada duplicada.

**[REL-06] Mídia que falha upload não vira `texto` silencioso** — *esforço M, risco médio*
- Tocar: `webhook/routes.py:338-348` + `workers/pix.py:207-213`.
- Ação: re-enqueue idempotente por `evolution_message_id` ou métrica/alerta dedicado + marcar mídia-pendente; garantir que Pix não some (foto-portaria já tolera key nula).
- Verificação: comprovante Pix com upload falho re-tenta em vez de cair no timeout-24h como `Perdido`.

**[REL-03] `max_tries` consciente** — *esforço P, risco baixo*
- Tocar: `workers/settings.py:156` → `func(processar_turno, keep_result=0, max_tries=2)` (turno caro), `max_tries=3` para envios.
- Verificação: erro transitório pós-LLM não reinvoca o Sonnet 5x.

**[REL-04] `vision_client` com timeout/retries** — *esforço P, risco baixo*
- Tocar: `workers/settings.py:114-117` → `timeout=60.0, max_retries=3` (espelhar `openai_client`).
- Verificação: vision Pix pendurado não segura slot por 400s; 5xx transitório re-tenta.

**[REL-08] Escalada crítica resiliente a `atendimento_id` nulo** — *esforço M, risco médio*
- Tocar: `workers/envio.py:506-522` (carregar `atendimento_id` mesmo de atendimento terminal para o handoff, ou métrica/alerta dedicado distinto de `falha_evolution`).
- Verificação: efeito crítico (Pix) nunca termina sem handoff nem alerta quando o atendimento vira terminal no meio do turno.

**[REL-12] Visibilidade de falha final não-crítica** — *esforço M, risco baixo*
- Tocar: `workers/envio.py:520-521` (logar `error` com `turno_id`+request_id e capturar no Sentry; depende de OBS-04).
- Verificação: mensagem perdida ao cliente é visível à operação.

#### 3.6 Observabilidade de produto (DIMENSÃO: Observabilidade)

- **[OBS-02]** Subir Prometheus + Grafana + Alertmanager (ou apontar stack existente do Portainer) com scrape de api e worker (depende de OBS-01); versionar regras: spike de `agente_escalada_total{bucket=defesa}`, write-rate de cache, p95, custo.
- **[OBS-07]** Middleware de request-id na API + propagar até o worker junto do `turno_id` (depende de OBS-03).
- **[OBS-09/OBS-10]** Tag `modelo_id`/`atendimento_id` (gen_ai.conversation.id) nos traces LangSmith via `core/tracing.py` (sem inflar o label de cache).
- **[TOOLS-04]** Incrementar `AGENTE_ESCALADA` após `abrir_handoff` em `intercept_disclosure.py` (~:60,~:99) para que jailbreak/disclosure apareçam em `bucket=defesa`.

---

### ONDA 3 — Otimização, Economia e a prova de ROI

> Objetivo: provar que a IA lucra mais que o vendedor e proteger a margem.

#### 3.7 Viabilidade econômica (DIMENSÃO: Custo)

**[CUSTO-01] Comissão de vendedor + Taxa de cartão + ROI** — *esforço G, risco médio*
- Tocar: `infra/sql/` (tabela `vendedores`, `modelos.vendedor_id`, `atendimentos.vendedor_id`/`taxa_cartao_snapshot`), `dominio/financeiro/{repo,service,routes}.py` (`valor_servico = Valor final − taxa`; comissão = nível×valor_servico), `dominio/dashboard/` (bloco ROI: `custo_IA_por_fechado` vs `comissao_evitada`).
- Verificação: dashboard responde "a IA custou R$X e evitou R$Y de comissão neste mês, por modelo".

**[CUSTO-02] Custo de STT + vision** — *esforço M, risco baixo*
- Tocar: `workers/pix.py:167` (ler `resposta.usage`), `workers/media.py:282` (usar `resposta.duration`), `core/metrics.py` (Histograms de custo STT/vision), consolidar `custo_por_atendimento_brl`.
- Verificação: custo por atendimento soma chat+STT+vision.

**[CUSTO-04] Teto de turnos por conversa/dia + retry-after** — *esforço M, risco médio*
- Tocar: contador Redis por conversa que escala a Fernando ao estourar (fecha o loop aberto pelo `RECURSION_LIMIT` dormente, `coordenador.py:45`); respeitar `retry-after`; cron de alerta de gasto via `langsmith get_billing_usage`.
- Verificação: cliente em loop não queima orçamento indefinidamente até as 24h.

**[CUSTO-05] Alerta de write-rate de cache** — *esforço P, risco baixo*
- Tocar: regra Alertmanager (depende de OBS-02) sobre `agente_turno_tokens_total{tipo=cache_write}` disparando >15% em regime, espelhando o invariante de `agente/CLAUDE.md`.

**[CUSTO-06] Fonte única do alvo de custo** — *esforço P, risco baixo*
- Tocar: `settings.custo_alvo_brl`, referenciar em `core/metrics.py:96` e no runner; eliminar o 0.12 vs 0.05 divergente.

#### 3.8 Persona e qualidade (DIMENSÃO: Persona + Evals)

- **[PER-01/PER-03]** Destilar diálogos canônicos de `docs/agente/conversas-reais/` em `evals/canonicos/scripted_5/` com rubrica de voz julgada por LLM (depende do runner EVAL-01).
- **[PER-11]** Reminder anti-drift re-ancorar 2-3 pares `<armadilhas_de_voz>` em `prepare_context.py:259` (sem cache_control), validado por fixture multi-turno.
- **[TOOLS-06]** Counter `agente_tool_erro_recuperavel_total{tool,motivo}` nos pontos de `"ERRO:"`.
- **[TOOLS-08]** Eval de recall de `escalar` para AUP ambíguo (gate de capacidade).
- **[EVAL-11]** Reativar `agente_eval_pass_rate` como métrica online (amostra ~5-10% dos turnos, rubric binária de non_disclosure).
- **[DEPLOY-05/06]** Tabela `schema_migrations` + drift-check no CI; banco de staging separado; guarda de ambiente bloqueando seeds em prod.
- **[OBS-05]** Resolver config de tracing duplicada/morta em `settings.py:146-148`.

---

## 4. Wins Seguros (implementar já — baixo risco, alta confiança)

Itens P/M sem refatoração, sem dependências, com critério de verificação trivial. Bom primeiro PR antes mesmo da Onda 1 completa:

| ID | Mudança | Arquivo | Verificação |
|---|---|---|---|
| TOOLS-05 | guarda `try/except ValueError` na parse de data | `agente/ferramentas/leitura.py:31-32` | data malformada vira `"ERRO:..."` recuperável |
| PER-08 | interpolar `localizacao_operacional` (fim do "Rio" hardcoded) | `prompts/identidade.md.j2:5` | modelo de SP não recebe frase do Rio |
| PER-12 | remover stub + corrigir doc | `agente/humanizacao.py`, `agente/CLAUDE.md:37` | doc aponta `workers/` |
| TOOLS-09 | minimizar payload Pix (sem `chave`/`titular`) | `agente/ferramentas/pix.py:110-116`, `_idempotencia.py:45` | `eventos`/`tool_calls` só com `{valor}` |
| SEC-06 | `hmac.compare_digest` no token | `webhook/routes.py:60` | comparação timing-safe |
| SEC-09 | guard CORS no boot | `main.py` | boot falha com `*` em produção |
| REL-09 | não enfileirar `loc_pin` (renderer é `NotImplementedError`) | `agente/ferramentas/extracao.py:133-139` | atendimento interno não gera job que falha 5x |
| DEPLOY-10 | corrigir README do stack real | `infra/compose/README.md:5` | aponta `stack.barra-portainer.yml` |
| REL-03 | `max_tries` por job | `workers/settings.py:156` | turno não reinvoca LLM 5x |
| REL-04 | timeout/retries no `vision_client` | `workers/settings.py:114-117` | paridade com `openai_client` |
| REL-02 | `abrir_handoff` idempotente | `dominio/escaladas/service.py:409` | sem escalada duplicada |
| OBS-04 | Sentry no worker | `workers/settings.py:startup` | exceção do worker no Sentry |
| CUSTO-06 | alvo de custo único | `settings.py`, `core/metrics.py:96` | sem 0.12/0.05 divergente |

> **Nota de prioridade absoluta:** mesmo entre os wins, **rotacionar a `MINIO_SECRET_KEY` (DEPLOY-01) é a ação #1** — é um segredo vivo em texto claro num repo clonado a cada deploy. Faça isso antes de qualquer outra coisa.
