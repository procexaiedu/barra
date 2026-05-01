# 07 — Stack Técnica e Infraestrutura

## 1. Visão consolidada


| Camada | Escolha (versão alvo) |
| --- | --- |
| **Linguagem do orquestrador** | **Python 3.12** |
| **Package/Env manager Python** | **uv ≥ 0.5** (gerencia Python, venv e lockfile) |
| **Framework web** | **FastAPI 0.136.x** (lifespan async + Pydantic v2) |
| **Orquestrador de agentes** | **LangGraph 0.4.x** + `AsyncPostgresSaver` (checkpointer) + `interrupt()`/`Command(resume=...)` para handoff |
| **LLM provider** | **Anthropic Claude** Sonnet 4.6 + Haiku 4.5 via SDK Python **anthropic ≥ 0.42** com `cache_control` nativo |
| **Banco de dados** | **Postgres 17** via **Supabase managed** (conexão por **Supavisor**, transaction mode) |
| **Storage S3-compatível (mídia)** | **MinIO** self-hosted em Docker, **tag pinada** (CE arquivado 2026-04-25 — sem novos binários; plano B: SeaweedFS via `mc mirror`) |
| **Auth do painel** | **Supabase Auth** (RLS + JWT) |
| **Realtime no painel** | **Supabase Realtime** (Postgres Changes com RLS) |
| **Cache + fila de jobs** | **Redis 8.x** self-hosted em Docker (`redis:8-alpine`) + **ARQ** (worker async Python) |
| **Frontend (painel)** | **Next.js 16.2** (App Router, Turbopack default) + **React 19** + TypeScript + **shadcn/ui** (data-slot pattern) + **Tailwind CSS v4.2** |
| **Canal WhatsApp** | **Evolution API v2.3.7** self-hosted (Baileys 7.0.0-rc.6) no mesmo Portainer stack |
| **Orquestração de containers** | **Portainer CE 2.39 LTS** (Server + Agent), deploy via Stacks com Git + webhook |
| **Reverse proxy + TLS** | **Traefik v3.6** (auto-discovery por labels, Let's Encrypt HTTP-01 ou DNS-01) + **docker-socket-proxy** lendo o socket |
| **Observabilidade IA** | **LangSmith** (managed) — Plus US$ 39/seat/mês, projeto por ambiente, tags por `conversa_id`/`modelo_id` |
| **Erros de aplicação** | **Sentry** (Python + Next.js SDKs) |
| **Logs estruturados** | stdout JSON com Docker `json-file` driver (`max-size: 10m`, `max-file: 3`) |
| **Hospedagem backend + agente + Redis + MinIO + Evolution** | **VPS dedicada Hetzner CPX31** (4 vCPU/8 GB) com Docker + Portainer |
| **Hospedagem frontend** | **Vercel** |


---

## 2. Justificativas e trade-offs

### 2.2 LangGraph como orquestrador

**Por quê:** o MVP tem máquina de estados explícita (`Novo → Triagem → Qualificado → Aguardando_confirmacao → ...`, `04 §8`), human-in-the-loop pesado (handoff/devolução), persistência obrigatória (conversation history + checkpoint após cada turno) e durabilidade (cliente pode ficar dias parado e voltar). Esses são exatamente os casos onde LangGraph supera orquestração ad-hoc.

**Como mapear o domínio:**

- **Nó por estado**: cada estado da máquina (`04 §8`) vira um node ou sub-graph.
- **Checkpointer Postgres**: `AsyncPostgresSaver` salva o estado após cada turno; recuperação automática se o serviço cair.
- **Interrupt para handoff**: quando a IA escala, o graph chama `interrupt()` e fica pausado até receber `Command(resume=...)` — mapeia direto pra `ia_pausada=true`.
- **Stream para chunks**: a humanização consome a stream do LangGraph chunk a chunk.

**Boas práticas de produção (validadas em pesquisa 2026-04-29):**

- **Lifespan do FastAPI** controla o ciclo de vida do `AsyncPostgresSaver` e do `AsyncConnectionPool`; **nunca** usar `.from_conn_string()` em produção (cria pool por chamada e exaure conexões).
- Inicializar o pool **uma vez** no startup, com `autocommit=True` e `row_factory=dict_row` (de `psycopg.rows`).
- Chamar `await checkpointer.setup()` na primeira execução para criar tabelas de checkpoint.
- Não usar `AsyncSqliteSaver` em produção — write performance ruim.
- LangGraph **não tem timeout/expiração nativa** para `interrupt()`; precisamos cron job que varre threads pausadas e escala se passar do prazo (cobre o caso "modelo não respondeu em 5 min" do `04`).
- O checkpointer **não é audit log** — para registro humano-legível ("quem decidiu, quando, por quê") usamos a tabela `eventos` do schema (`06`).

**Trade-off:** LangGraph adiciona uma camada de abstração que pode dificultar debug em produção. Mitigamos com LangSmith tracing desde o dia 0.

### 2.3 Supabase para Postgres/Auth + MinIO para mídia

**Por quê:** Supabase entrega Postgres 17 + Auth + Realtime gerenciado, enquanto MinIO mantém a mídia sob controle do time e preserva compatibilidade S3. Para o MVP, isso evita montar Postgres, pgbouncer, Auth e WebSocket próprios sem abrir mão de storage self-hosted.

**Cuidado novo (2026-04-29):** o **repositório MinIO CE foi arquivado em 2026-04-25** — não há mais releases binários da Community Edition. Decisão do projeto é **manter MinIO** com a seguinte mitigação:

- **Pinar a tag Docker** numa release estável conhecida (`minio/minio:RELEASE.2025-12-13T05-26-58Z` ou outra validada) — não usar `latest` nem `RELEASE.2026-04-11T...` (essa só existe na linha AIStor enterprise).
- Subscrever lista de CVEs do MinIO; se aparecer crítica sem patch, executar plano B documentado abaixo.
- **Plano B: SeaweedFS** (Apache 2.0, dominante para arquivos pequenos como nossas imagens/áudio) — manter um runbook de migração: criar bucket equivalente, `mc mirror` MinIO → SeaweedFS, swap de endpoint na env do backend. Não é pré-implementado, fica como fallback.

**Trade-off:** mantém duas peças de infra (Supabase + MinIO) e adiciona risco de manutenção zero do upstream MinIO. Aceito conscientemente — MinIO é o que o time já conhece e a tag pinada cobre o MVP. Reabrir decisão se aparecer CVE crítica sem patch.

**Conexão Postgres da app:** sempre via **Supavisor** (porta 6543, transaction mode), nunca direto na 5432. Pool gerenciado pelo Supavisor + `AsyncConnectionPool` (psycopg) no FastAPI.

### 2.4 Redis self-hosted + ARQ para humanização e jobs

**Por quê:** a humanização precisa de delays controlados, presence on/off no Evolution, jitter e cancelamento de envios em fila. Isso vive **fora do request HTTP** — não pode bloquear a chamada do webhook. ARQ (async Redis-backed worker) é a opção mais leve em Python e integra com FastAPI/asyncio sem fricção. ARQ entrega **at-least-once** e exige tasks idempotentes — modelamos cada envio com `dedupe_key = (conversa_id, turno_id, chunk_idx)` consultado no Redis antes de mandar para o Evolution.

**Por que self-hosted (e não Upstash):** ARQ depende de **conexão TCP persistente** com Redis (BRPOP, pub/sub). Upstash oferece API HTTP serverless, mas o modo TCP é pago/limitado e perde a vantagem. Como já temos VPS rodando Docker, subir um contêiner Redis no mesmo stack é trivial e elimina latência de rede e custo recorrente.

**Por que Redis e não Valkey:** decisão do projeto é manter **Redis 8.x** (`redis:8-alpine`). Valkey 8.1 é a alternativa OSI pura (BSD-3, governance Linux Foundation) e foi avaliada — vale considerar em uma fase futura se a licença AGPLv3/SSPL do Redis virar problema (não é o caso usando Redis "unmodified" como backend).

**Lock de conversa no webhook:** o Evolution pode disparar dois eventos de mensagem do mesmo `conversation_id` em sequência antes de o primeiro ser processado. O Coordenador de Turno usa **Redis SETNX** (`lock:conv:{conversation_id}`, TTL ≈ 15s) para serializar o processamento: se o lock estiver ocupado, o evento novo entra numa lista Redis `pending:conv:{conversation_id}` e é processado quando o lock for liberado. Sem isso, dois turnos do LangGraph correm em paralelo no mesmo thread e corrompem o checkpoint. Isso é separado do `dedupe_key` de envio — que evita reenvio de chunk; o lock de conversa evita execução concorrente do grafo.

**Trade-off:** Redis self-host vira responsabilidade nossa (persistência AOF, backup, monitoramento). Mitigação: volume nomeado Docker, snapshot RDB diário copiado para bucket MinIO, e healthcheck no compose.

### 2.5 LangSmith para observabilidade da IA

**Por quê:** integra nativo com LangGraph; cada turno vira trace automaticamente, com prompt, resposta, tokens, custo e latência. Para um MVP com risco de banimento alto, ver o que a IA está dizendo em produção sem montar pipeline próprio é valor imediato. Em outubro/2025 a "LangGraph Platform" foi renomeada para **LangSmith Deployment**, e os traces agora ligam direto aos logs do servidor — útil quando aparecer um trace estranho e for preciso pular pro log da requisição.

**Configuração mínima:** `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY=...` + `LANGCHAIN_PROJECT=barra-vips-{ambiente}` no contêiner do backend. Toda chamada `graph.invoke()`/`graph.astream()` aparece no projeto sem código adicional.

**Pricing atual (2026-04):** Developer free (5k traces/mês, 14 dias retenção), **Plus US$ 39/seat/mês** (10k traces inclusos, $2.50/1k overage), Enterprise sob proposta. LangGraph Platform/Deployment cobra à parte: $0.001 por node executado + uptime do deployment (primeiros 100k nodes free no Developer).

**Trade-off:** custo cresce com volume. Mitigação documentada: **Langfuse self-host** (MIT, sobe no mesmo Portainer) ou **Pydantic Logfire** (OTel-nativo, melhor visão full-stack incluindo FastAPI, Postgres e LLM no mesmo lugar) ficam como sucessores quando virar prioridade. No MVP, mantemos LangSmith por simplicidade e integração nativa com LangGraph.

### 2.6 Cuidados com Evolution/Baileys

- Sessão Baileys é **state file persistente** — montar volume nomeado, nunca recriar o contêiner sem backup.
- Reinício pode forçar relogin via QR; usar `restart: unless-stopped` e evitar updates durante atendimento.
- Webhook → backend via rede Docker interna (não exposto ao público).
- Evolution roda Postgres próprio interno — não confundir com o Supabase, que é a fonte de verdade do domínio.

### 2.7 Prompt caching da Anthropic (SDK 0.42+)

**Por quê:** o sistema-prompt da IA Atendimento é grande (persona, FAQ da modelo, regras de domínio do `04`) e se repete a cada turno. Sem caching, paga input tokens completo em cada chamada. Com `cache_control` ativo, hit cacheado custa **~10% do preço de input** e remove ~85ms de latência do prefixo cacheado.

**Como aplicamos:**

- SDK Python `anthropic ≥ 0.42` (suporte nativo a `cache_control`, sem beta header).
- Marcar **até 4 breakpoints** de cache nos blocos `system` e `messages` da request — colocar persona + FAQ + regras nos primeiros blocos, conversa atual no final.
- TTL padrão de 5 minutos basta para o ritmo de uma conversa ativa; usar TTL de 1 hora para FAQ/persona quando o turno seguinte vier mais espaçado (sem custo extra para o TTL longo no SDK 0.42+).
- Monitorar hit rate via campo `usage.cache_read_input_tokens` no response — meta ≥ 70% após estabilização.

**Trade-off:** adicionar lógica de breakpoints ao construir messages aumenta acoplamento com o provedor. Mitigação: encapsular numa função `build_anthropic_messages(state)` no módulo `agente/llm.py` para que troca de provedor não vaze para os nós LangGraph.

---

## 3. Arquitetura física (alta granularidade)

```text
                       ┌──────────────────────┐
                       │  Cliente (WhatsApp)  │
                       └─────────┬────────────┘
                                 │ HTTPS (443)
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  VPS Hetzner CPX31 (Linux, Docker 27+, Portainer 2.39 LTS)       │
│  Server + Agent na mesma VPS                                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  Traefik v3.6 (rede pública: edge)                      │     │
│  │  ├── TLS automático (Let's Encrypt HTTP-01 ou DNS-01)   │     │
│  │  ├── roteia para os serviços por label Docker           │     │
│  │  └── lê socket via docker-socket-proxy (read-only)      │     │
│  └────────────────┬────────────────────────────────────────┘     │
│                   │                                              │
│  ┌────────────────┴───── Rede interna Docker (sem expor) ─┐      │
│  │                                                        │      │
│  │  ┌──────────────────┐   ┌────────────────────────────┐ │      │
│  │  │ Evolution v2.3.7 │◀─▶│ Backend FastAPI 0.136.x    │ │      │
│  │  │ (Baileys 7.0-rc) │   │ ├── /webhook (Evolution)   │ │      │
│  │  │ + Postgres int.  │   │ ├── /api (painel)          │ │      │
│  │  └──────────────────┘   │ ├── LangGraph 0.4.x        │ │      │
│  │                         │ └── Anthropic SDK 0.42+    │ │      │
│  │                         │     (cache_control)        │ │      │
│  │                         └────────┬───────────────────┘ │      │
│  │                                  │                     │      │
│  │  ┌──────────────────┐   ┌────────┴───────────────────┐ │      │
│  │  │ Redis 8-alpine   │◀─▶│ ARQ workers (idempotent)   │ │      │
│  │  │ + AOF + RDB      │   │ humanização, OCR, jobs     │ │      │
│  │  │ + senha          │   │ + cron de timeouts         │ │      │
│  │  └──────────────────┘   └────────────────────────────┘ │      │
│  │                                                        │      │
│  │  ┌──────────────────┐   ┌────────────────────────────┐ │      │
│  │  │ MinIO (tag pin)  │   │ Portainer 2.39 LTS         │ │      │
│  │  │ buckets: media,  │   │ Stacks via Git + webhook   │ │      │
│  │  │ backups, temp    │   │ UI :9443 atrás do Traefik  │ │      │
│  │  └──────────────────┘   └────────────────────────────┘ │      │
│  └────────────────────────────────────────────────────────┘      │
└────────┬───────────────────────────────────────────┬─────────────┘
         │ Anthropic API                             │ tracing
         ▼                                           ▼
   ┌──────────────┐                            ┌─────────────┐
   │ Claude       │                            │ LangSmith   │
   │ Sonnet/Haiku │                            │ (managed)   │
   └──────────────┘                            └─────────────┘
                                                                
         ▲ Supavisor :6543 (transaction mode) + Realtime (WS)
         │
   ┌─────┴──────────────────┐                  ┌─────────────┐
   │ Supabase managed       │                  │ Sentry      │
   │ ├── Postgres 17        │                  │ (Python +   │
   │ ├── Auth (RLS opt-out) │                  │  Next SDK)  │
   │ └── Realtime (Postgres │                  └─────────────┘
   │     Changes c/ RLS)    │
   └─────────┬──────────────┘
             │
             ▼
   ┌─────────────────────────────────┐
   │ Frontend (Vercel)               │
   │ Next.js 16.2 + React 19         │
   │ shadcn/ui + Tailwind v4.2       │
   │ painel para Fernando            │
   └─────────────────────────────────┘
```

**Observações sobre a topologia:**

- **Apenas Traefik** abre porta no host (80/443 + 9443 da UI Portainer, esta restrita por IP allowlist + 2FA).
- Backend, Redis, MinIO e Postgres interno do Evolution **não publicam portas** no host — só ouvem na rede interna do Compose.
- Evolution API é exposto via Traefik **só** no caminho `/manager` (painel) com auth + IP allowlist; o webhook é tráfego interno entre contêineres.
- Postgres do domínio é **Supabase managed** (externo); o Postgres do Evolution é apenas cache/sessão da própria Evolution e nunca é fonte de verdade.
- Traefik **não monta `/var/run/docker.sock` direto** — usa **docker-socket-proxy** (Tecnativa) read-only para reduzir o blast radius caso Traefik seja comprometido.

---

## 4. Custos estimados por mês (MVP, 1 modelo piloto)


| Item                                  | Plano                                                                                     | Estimativa BRL/mês     |
| ------------------------------------- | ----------------------------------------------------------------------------------------- | ---------------------- |
| Supabase Pro                          | 1 projeto, ~5 GB DB, Auth, Realtime, daily backup, Supavisor                              | R$ 130                 |
| Hetzner CPX31 (Docker host)           | 4 vCPU, 8 GB RAM, 160 GB SSD — backend + Redis + MinIO + Evolution + Portainer + Traefik  | R$ 90                  |
| Backup off-site (Hetzner Storage Box) | 100 GB, snapshots Postgres + dump MinIO + RDB Redis + state Evolution                     | R$ 25                  |
| Vercel (frontend)                     | Hobby (free) ou Pro                                                                       | R$ 0–100               |
| LangSmith Plus                        | 2 seats × US$ 39 (10k traces/seat inclusos)                                               | R$ 400                 |
| Anthropic Claude                      | ~30 atend/dia × 4 turnos × Sonnet **com prompt caching** (~70% hit rate)                  | R$ 150–350             |
| Sentry Team                           | Python + Next.js SDK                                                                      | R$ 130                 |
| Portainer CE 2.39 LTS                 | Free                                                                                      | R$ 0                   |
| Redis 8 self-hosted                   | Free (Docker)                                                                             | R$ 0                   |
| MinIO self-hosted (tag pinada)        | Free (Docker)                                                                             | R$ 0                   |
| Traefik v3.6 + docker-socket-proxy    | Free (Docker)                                                                             | R$ 0                   |
| **Total estimado**                    |                                                                                           | **R$ 925–1.225/mês**   |


Custo cresce principalmente com seats LangSmith e tokens Anthropic — **prompt caching reduz a faixa de Anthropic em ~50%** comparado à estimativa anterior (R$ 300–600). A consolidação na VPS Hetzner economiza ~R$ 80/mês frente ao desenho anterior (Railway + Upstash + VPS Evolution separadas) e reduz superfície operacional.

LangSmith e Sentry têm planos free que cobrem o início se quiser apertar. Quando volume crescer, considerar Portainer BE (RBAC, audit log, ~US$ 24/mês para 3 nós) e Langfuse self-host no mesmo Portainer (substitui LangSmith) ou migrar Sentry+LangSmith → Pydantic Logfire (full-stack OTel-nativo).

---

## 5. Roadmap de implementação técnica

### Sprint 0 (dias 0–3) — Infra base

- Provisionar VPS Hetzner CPX31 (Ubuntu 24.04 LTS).
- Instalar Docker Engine 27+ + Docker Compose plugin.
- Subir **Portainer CE 2.39 LTS** (Server + Agent) — UI atrás de Traefik com IP allowlist + 2FA.
- Configurar **Traefik v3.6** (rede `edge`), DNS, certificados Let's Encrypt; **docker-socket-proxy** para isolar acesso ao socket.
- Criar repo `barra-vips-infra` com `docker-compose.yml` versionado; conectar Portainer Stack via Git + webhook redeploy.
- Provisionar Supabase Pro (Postgres 17), schema inicial conforme `06`, RLS habilitado, daily backup confirmado, conexão via Supavisor.
- Inicializar repo `barra-vips-backend` com **uv** (`uv init`, `pyproject.toml`, `.python-version` em 3.12).

### Sprint 1 (semanas 1–2)

- Subir Stack inicial via Portainer: Postgres do Evolution, **Evolution API v2.3.7**, **Redis 8-alpine** (volume + AOF + senha), **MinIO em tag pinada** (buckets `media`, `backups`, `temp`).
- Conectar Evolution ao **número X** (chip de teste do Lucas), gerar QR.
- Stub do backend FastAPI 0.136.x com webhook do Evolution + healthcheck no compose; build via Dockerfile multi-stage com `uv sync --frozen --no-dev`.
- Schema Supabase: clientes, conversas, mensagens, atendimentos, modelos, modelo_perfil, modelo_faq, bloqueios (ver `06`).

### Sprint 2 (semana 3)

- **LangGraph 0.4.x** com StateGraph cobrindo `Novo → Triagem → Qualificado → Aguardando_confirmacao`.
- `AsyncPostgresSaver` configurado em lifespan FastAPI com `AsyncConnectionPool` (`min_size=4, max_size=20`), `autocommit=True`, `row_factory=dict_row`.
- **Anthropic SDK 0.42+** com `cache_control` em persona/FAQ/regras desde o primeiro turno; verificar hit rate via `usage.cache_read_input_tokens`.
- LangSmith ativo desde o primeiro turno (`LANGCHAIN_TRACING_V2=true`, projetos `barra-vips-test` e `barra-vips-prod`).
- Camada de humanização ARQ + Redis self-host funcional, com cancelamento de jobs em fila e dedupe key.
- Tela básica de Atendimentos e Modelo em **Next.js 16.2** + React 19 + shadcn/ui + Tailwind v4.2 + Supabase Auth + Realtime subscribe.

### Sprint 3 (semana 4 — Fase 1.5)

- Pipeline OCR + extração para Pix (workers ARQ; mídia lida do MinIO).
- Grupo de coordenação por modelo (decisões grilling 29/04: 2 participantes).
- `interrupt()` para handoff e Command(resume=...) para devolução.
- Cron job de varredura de threads pausadas (timeout de handoff).
- Bateria de conversas de teste pré-piloto + revisão dos traces no LangSmith.

### Sprint 4 (semana 5 — Fase 2)

- QR code da modelo piloto na tela de Modelo.
- Cutover: parar Evolution do número X, conectar Evolution do número da modelo piloto (mesmo contêiner, instância nova ou troca de credencial Baileys conforme decisão operacional).
- Snapshot pré-cutover via Portainer (volumes Evolution + Redis + MinIO) + snapshot Hetzner.
- Acompanhar piloto, calibrar.

---

## 6. Pontos abertos

- **Backup do Postgres**: Supabase faz daily snapshot no plano Pro. Confirmar retenção (default 7 dias) e configurar `pg_dump` diário extra para o bucket `backups/postgres/` do MinIO (off-site real).
- **Disaster recovery do Evolution**: sessão Baileys é state file persistente no volume Docker. Definir cron de cópia do volume para MinIO `backups/evolution/` + procedimento de restore (relogin via QR é o último recurso).
- **MinIO arquivado**: monitorar lista de CVEs. Tag pinada cobre o MVP, mas vulnerabilidade crítica sem patch dispara plano B (migração para SeaweedFS via `mc mirror`).
- **Rate limit do Anthropic**: confirmar tier da conta e estratégia de fallback Sonnet → Haiku quando bater limite. Prompt caching reduz mas não elimina o problema.
- **Aquecimento do número da modelo piloto**: decisão consciente do operador foi não fazer aquecimento (`02 §3.2`). Vale revisar à luz do volume real esperado.
- **Custos de LangSmith em escala**: monitorar; Langfuse self-hosted no mesmo Portainer ou Pydantic Logfire (full-stack OTel) são as mitigações previstas.
- **VPS como SPOF**: snapshot diário Hetzner cobre, mas RTO real depende de runbook. Documentar.
- **Acesso ao Portainer UI**: confirmado IP allowlist + 2FA. Avaliar Tailscale na fase 2 se time crescer.
- **Audit log de handoff/decisão**: o checkpointer LangGraph não é audit log. Implementar inserts na tabela `eventos` (`06`) em todo `interrupt`/`resume`.
- **Timeout de `interrupt`**: LangGraph não tem mecanismo nativo. Cron worker percorre threads pausadas e escala — projetar query e cadência (sugestão: a cada 30 s).
- **Idempotência ARQ**: ARQ entrega at-least-once. Confirmar que toda task de envio ao Evolution checa `dedupe_key` em Redis antes de mandar (evita reenvio duplicado ao cliente).
- **Cache hit rate Anthropic**: medir após 1 semana de produção; se < 60%, revisar ordem dos blocos `cache_control`.

---

## 7. Boas práticas operacionais por peça (consolidado de pesquisa 2026-04-29)

### 7.1 LangGraph + FastAPI

- Lifespan FastAPI inicializa `AsyncConnectionPool(min_size=4, max_size=20)` apontando para Supabase via Supavisor (porta 6543, transaction mode).
- `AsyncPostgresSaver` recebe o pool no startup, chama `await saver.setup()` na primeira execução.
- **Nunca** `from_conn_string` em produção — vaza pool por chamada.
- Ao criar conexão manual: `autocommit=True` + `row_factory=dict_row`.
- `graph.astream(..., stream_mode="messages")` para humanização chunk a chunk.
- `interrupt()` dentro do node de handoff; `Command(resume=...)` dispara devolução.
- Thread ID = `conversa_id` para isolamento por par cliente-modelo.

### 7.2 Portainer CE

- **Portainer Server** + **Portainer Agent** na mesma VPS (single-node OK para MVP).
- Stacks via **Git repository** (`docker-compose.yml` versionado em `barra-vips-infra`); webhook do Portainer faz redeploy a cada push em `main`.
- Variáveis sensíveis (DATABASE_URL, ANTHROPIC_API_KEY, JWT secrets) ficam em **Stack environment variables**, nunca no compose commitado.
- UI exposta apenas via Traefik com IP allowlist + 2FA.
- Backup do BoltDB do Portainer entra na rotina de snapshot (volume `portainer_data`).
- Edition Business só vira opção quando precisar de RBAC, audit log estruturado ou multi-cluster.

### 7.3 MinIO (tag pinada após arquivamento do CE)

- **Tag Docker pinada** (`minio/minio:RELEASE.2025-12-13T05-26-58Z` ou outra release CE estável validada). Nunca `latest`.
- `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` apenas para bootstrap. Criar service accounts dedicados por aplicação (backend, workers, Evolution backup) com IAM policies por bucket.
- Buckets nomeados: `media` (mídia de cliente), `backups` (dumps Postgres + state Evolution + RDB Redis), `temp` (uploads em processamento, lifecycle 24 h).
- Não publicar 9000/9001 no host — só Traefik com TLS na porta da API S3 e console em path interno + auth.
- Healthcheck `mc ready local` no compose, alimenta `depends_on: condition: service_healthy`.
- Lifecycle policy nos buckets `temp` (expire 24 h) e `backups` (expire 30 dias).
- Métricas Prometheus expostas em `/minio/v2/metrics/cluster` (Loki/Grafana opcional na fase 2).
- **Subscrever lista de CVEs do MinIO**; runbook de migração para SeaweedFS pré-redigido caso surja vulnerabilidade crítica sem patch upstream.

### 7.4 Redis 8 self-hosted

- Imagem `redis:8-alpine` com `--appendonly yes --appendfsync everysec` (durável, overhead baixo).
- Volume nomeado para `/data`; cron exporta RDB para MinIO `backups/redis/` diariamente.
- Sem porta publicada; só rede Docker interna.
- Healthcheck `redis-cli ping` no compose.
- Senha via env var (`REDIS_PASSWORD`), TLS desnecessário pois é tráfego intra-host.
- ARQ usa pool de conexões padrão (TCP nativo); funciona out-of-the-box.
- **Idempotência ARQ**: armazenar `dedupe_key = sha256(conversa_id|turno_id|chunk_idx)` com TTL ≥ retry window; checar via `SET NX` antes de chamar Evolution.

### 7.5 LangSmith

- Variáveis no contêiner: `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT=barra-vips-{ambiente}`.
- Projetos separados por ambiente: `barra-vips-test`, `barra-vips-prod`.
- Tags por conversa (`conversa_id`) e por modelo (`modelo_id`) para filtros de dashboard.
- Alertas LangSmith em latência e custo por turno.
- Retenção: plano Plus padrão (~30 dias) é suficiente para MVP.

### 7.6 Evolution API

- Imagem `evolutionapi/evolution-api:v2.3.7` (Baileys 7.0.0-rc.6) em tag fixa (não `latest`).
- Volume persistente para `instances/` (sessões Baileys).
- Postgres interno do Evolution roda como contêiner próprio com `pgbouncer` ativo (`USE_PGBOUNCER=true` desde v2.3.1).
- Webhook configurado para `http://backend:8000/webhook/evolution` (rede interna).
- `restart: unless-stopped`; nunca recriar o contêiner sem snapshot.
- Manager UI exposto via Traefik em path com auth + IP allowlist.

### 7.7 Docker Compose (padrões da stack)

- Duas redes: `edge` (Traefik + serviços com label de roteamento) e `internal` (DB-like services).
- `depends_on: condition: service_healthy` em todo serviço dependente.
- Healthchecks obrigatórios em backend, Evolution, Postgres interno, Redis, MinIO.
- Logging driver `json-file` com `max-size: 10m`, `max-file: 3` (evita encher disco).
- Volumes nomeados (não bind-mounts) para dados; bind-mounts só leitura para configs.
- Imagens com tag fixa (semver), nunca `latest` em produção.
- Healthcheck do backend FastAPI deve incluir verificação do pool Postgres antes de retornar 200.

### 7.8 Supabase (managed)

- Conexões da app via **Supavisor (porta 6543, transaction mode)** — não conectar direto na 5432.
- Daily backups do plano Pro + dump complementar diário para `backups/postgres/` no MinIO.
- RLS habilitado em todas as tabelas; políticas por `modelo_id` para isolamento. Lembrar do **opt-out by default a partir de maio/2026** (grants explícitos para Data API).
- Realtime apenas nas tabelas que o painel consome (atendimentos, mensagens, eventos), respeitando RLS automaticamente desde o release de Realtime Authorization.
- Logs e métricas via dashboard Supabase no MVP; quando crescer, exportar via Logflare para Loki próprio.

### 7.9 uv + Dockerfile do backend

- `pyproject.toml` + `uv.lock` versionados; `.python-version` pinando 3.12.x.
- Dockerfile multi-stage:

  ```dockerfile
  FROM python:3.12-slim AS builder
  COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
  WORKDIR /app
  COPY pyproject.toml uv.lock ./
  RUN uv sync --frozen --no-dev --no-install-project
  COPY . .
  RUN uv sync --frozen --no-dev

  FROM python:3.12-slim
  WORKDIR /app
  COPY --from=builder /app /app
  ENV PATH="/app/.venv/bin:$PATH"
  CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
  ```

- Não instalar uv na imagem final — só venv pronto.
- `uv lock --upgrade-package <pkg>` para upgrades cirúrgicos; `uv sync` para reproduzir o ambiente.

### 7.10 Anthropic SDK + prompt caching

- SDK Python `anthropic >= 0.42` (cache_control nativo, sem beta header).
- Wrap único `agente/llm.py:build_messages(state)` constrói a request com até 4 breakpoints:
  1. Persona da modelo (mais estável → cache TTL 1h).
  2. FAQ da modelo (estável por sessão → cache TTL 1h).
  3. Regras do `04` resumidas (estável → cache TTL 1h).
  4. Histórico de mensagens da conversa atual (volátil, fora do cache).
- Métricas a logar por turno: `usage.input_tokens`, `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens`, `usage.output_tokens`.
- Alerta no LangSmith se hit rate cair abaixo de 60% por 24 h (provável regressão na ordem dos blocos).
- Fallback Sonnet → Haiku quando rate limit aparecer; Haiku 4.5 também suporta `cache_control`.

### 7.11 Frontend Next.js 16.2

- App Router como única opção; sem Pages Router.
- **Turbopack** já é default em dev (não precisa de `--turbo`); produção segue webpack até estabilizar.
- `<Link>` com `transitionTypes` para View Transitions estáveis.
- `unstable_retry()` substitui `reset()` em error boundaries.
- `experimental.prefetchInlining` ligado para reduzir requests de prefetch.
- shadcn/ui CLI inicializa o projeto já em Tailwind v4 + React 19 (data-slot pattern, sem `forwardRef`).
- Tailwind v4: `@theme` no CSS principal; sem `tailwind.config.js` na maioria dos casos.
- Supabase Realtime client com `useSyncExternalStore` para refletir RLS na UI.
- Sentry via `@sentry/nextjs` com tunnel para evitar adblock.

### 7.12 Traefik v3.6 + docker-socket-proxy

- **Não montar `/var/run/docker.sock`** direto no Traefik. Subir `tecnativa/docker-socket-proxy:latest` como serviço separado com `CONTAINERS=1` apenas; Traefik aponta `providers.docker.endpoint` para o proxy.
- Routers com `tls.certresolver=le`, `entrypoints=websecure`; redirect global de `web` → `websecure`.
- Middlewares globais: `rateLimit` (primeiro, rejeita abuso antes), `headers` (HSTS, sec headers), `compress`.
- Wildcard via DNS-01 (Cloudflare ou outro provedor) se mais de 5 subdomínios.
- `acme.json` em volume nomeado com permissões `600`.
- Dashboard Traefik desligado em produção ou exposto via path interno + auth.
