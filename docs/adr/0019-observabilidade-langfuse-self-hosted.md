---
status: accepted
---

# Observabilidade do agente: migração de LangSmith para Langfuse self-hosted

A observabilidade do agente (LangGraph) roda hoje no **LangSmith**, em dois caminhos distintos
(`core/tracing.py`): produção via `setup_tracing` com um **hard-gate de anonymizer** que mascara
toda PII (content vira `[PII]`), e o simulador de evals via `setup_tracing_sim`, sem anonymizer
porque os dados são sintéticos. O masking de prod é correto para um SaaS de terceiros — RG/CPF/
endereço, telefone e o conteúdo livre da conversa não podem vazar — mas tem um custo operacional
real: **cega quem consome o trace de prod**. Os invariantes online (EVAL-11), o flywheel de
iteração e a calibração precisam ler o que o agente *de fato* falou e decidiu; com o texto `[PII]`,
o diagnóstico de prod cai num proxy (sim/dev) ou no `mensagens.conteudo` do banco fora do trace.

Avaliamos o Langfuse (jun/2026) sob o recorte real do projeto — **o Claude faz a migração e o Claude
consome os dados** (via MCP). O teste, do smoke (custo zero) ao sim com o agente real (1 cenário,
§0 autorizado), provou: árvore LangGraph **fielmente reconstruída** (`LangGraph`→`prepare_context`/
`llm`→`ChatAnthropic`/`tools`→`registrar_extracao`/`output_guard`/`post_process`), **conteúdo
legível**, captura automática de `model`/tokens/**prompt caching**/custo, e um **MCP token-efficient**
(campos pesados são opt-in via `fields`). O ganho decisivo é remover o masking sem furar soberania —
o que só existe **self-hosted**, com a PII na infra de vocês.

Decidimos **migrar toda a observabilidade do agente de LangSmith para Langfuse self-hosted** e
aposentar o LangSmith. Em prod, com o Langfuse na infra própria (mesmo perímetro de confiança do
banco que já guarda a PII), o trace volta a ser legível — desbloqueando os invariantes online, o
flywheel e a calibração diretamente sobre dados de produção.

## Decisões

- **Self-hosted, não Cloud.** O Langfuse roda na infra de vocês (Supabase Postgres + Redis + MinIO
  já existentes; **ClickHouse novo**, dependência do Langfuse v3+). Langfuse Cloud foi **rejeitado**
  para prod: mandaria PII real a um SaaS US. Cloud sem masking fura o hard-gate de PII, o isolamento
  de domínio (`CONTEXT.md`) e a §0; Cloud com masking manteria prod ilegível — sem ganho sobre hoje.
- **Integração via CallbackHandler do LangChain** (integração de framework, não instrumentação
  manual): captura nó/tool/generation, model, tokens (incl. cache) e custo automaticamente. Trace
  escopado por atendimento — `langfuse_session_id = atendimento_id` (agrupa os turnos da jornada),
  tags por `modelo_id`/`atendimento_id`, mantendo a convenção do `metadata_trace_turno`.
- **Custo de adoção aceito: bump do LangGraph 1.1.10 → 1.2.4.** O `CallbackHandler` do Langfuse
  exige o meta-pacote `langchain>=1.3.4`, que depende de `langgraph>=1.2.4` (conflito de resolução
  comprovado — não dá para segurar 1.1.10). A suíte local passou **923/0** no 1.2.4; `needs_db`/
  `needs_key` a validar no gate completo antes do cutover.
- **Sem masking em prod no Langfuse self-hosted.** A PII já vive no mesmo perímetro (banco
  self-hosted); replicá-la no Langfuse self-hosted não amplia a superfície de exposição como o SaaS
  ampliaria. O `setup_tracing` + anonymizer do LangSmith é retirado junto com o LangSmith. **A
  proteção migra de masking-no-egress para controle de acesso ao Langfuse** (a PII continua sensível;
  o acesso ao painel/projeto Langfuse é restrito como o acesso ao banco).
- **sim/dev já migrado.** `setup_langfuse_sim` (espelha `setup_tracing_sim`: dados sintéticos,
  legível) + `langfuse_handler()` gateado num global setado só pelos entrypoints CLI do sim —
  garantindo que o **pytest nunca traça**, mesmo com chaves no `.env`. Fiado em `gerar_conversas`
  (com `flush()`) e em `loop.jornada`.
- **Consumo agêntico via MCP do Langfuse**, substituindo o MCP do LangSmith no fluxo do Claude
  (root-cause, calibração, monitoramento). Convém manter o trace legível por atendimento e os
  campos pesados sob `fields` explícito (token-efficient).

## Faseamento

1. **sim/dev no Langfuse Cloud** (avaliação) — **feito**; provado com o agente real.
2. **Subir Langfuse self-hosted** no Swarm (ClickHouse + langfuse-web/worker; reusa Postgres/Redis/
   MinIO). Projeto de **infra §0** — planejado, executado só sob autorização frase-a-frase. Idem
   ADR 0018 (stack git-backed): a definição entra como PR versionado, segredos em Env do Portainer.
3. **Cutover de prod**: trocar `setup_tracing` (LangSmith+anonymizer) pelo CallbackHandler do
   Langfuse self-hosted no `main.py`/worker; validar gate completo (incl. `needs_db`); reiniciar o
   worker (`service update --force`, nunca `docker restart` — worker órfão no Swarm).
4. **Aposentar o LangSmith**: remover deps/config `langchain_*`/anonymizer, atualizar runbooks e a
   skill `monitorar-e2e` para ler do Langfuse.

## Consequências

- **Positivas:** trace de prod legível desbloqueia invariantes online/flywheel/calibração sobre
  dados reais; baseline de observabilidade (model/tokens/cache/custo) automático; soberania total
  dos dados de telemetria; custo previsível (infra fixa, não por-trace/seat).
- **Negativas / riscos:** **operar um ClickHouse** no Swarm (componente novo, mais pesado que o
  resto da stack); o LangGraph sobe para 1.2.4 (revalidar agente no gate completo); a proteção de
  PII passa a depender de **controle de acesso ao Langfuse**, não de masking — exige disciplina de
  permissão equivalente à do banco.
