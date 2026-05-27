# 09 — Roteiro de Implementação (Claude Code first)

> Roadmap executável por agentes Claude Code, do estado atual (**M0 parcial**) até **P0 pronto-pra-piloto** = passar o gate de evals do `08 §4`. **Não inclui P1.**
>
> Cada tarefa é um **prompt colável**, auto-contido e verificável. A unidade ≈ uma sessão de agente: cabe numa janela e fecha num aceite objetivo. Onde a spec diverge do código, a tarefa diz quem vence e por quê — árbitro técnico em `01 §6` (a verdade corrente é `docs/agente/`, refinada pelas decisões M0 e pelo código já shipado).

## 0. Como usar

- Marcos em ordem de dependência (`§2`); grafo serial/paralelo em `§3`.
- Decisões de arbitragem e armadilhas concretas em `§4` ("Bugs e decisões") — **ler antes de cada marco**.
- Migrations consolidadas em `§6`; gate final em `§7`.
- Convenção de marco: comentários `# TODO(M{n})` no código apontam para a tarefa correspondente aqui. O roadmap (não o código) é a fonte de sequenciamento.

## 1. Estado atual (gap reconciliado)

Levantado a partir do **código real** em `api/src/barra/`, não do que o doc afirma. O `00 §Status` diz "M0 parcial"; **confirmado e mais incompleto**: o grafo compila, mas os 5 nós são no-op e nada invoca o agente fim-a-fim.

### 1.1 Compila e roda hoje
- `agente/graph.py` — `build_graph(settings=None, checkpointer=None)` (settings None → `get_settings()`), **roteamento por `Command(goto)`** (não mais arestas lineares), chat injetado no nó `llm` via factory `no_llm(chat, TOOLS)`; `builder.compile()` sem checkpointer ✓ `01 §6.7` ✓ [M0-T5].
- `agente/estado.py:35` — `EstadoAgente(MessagesState)` com `midia_idx`, `_categoria`, `_confianca`. **Sem** `_pausada/_intercept/_motivo_escalada` (decisão `Command(goto)` — `§4.1`).
- `agente/contexto.py` — `ContextAgente` completo (db_pool, redis, modelo_id, atendimento_id, cliente_id, turno_id) ✓.
- `core/metrics.py` (métricas `AGENTE_TURNO_*`, `TIMEOUTS`, definidas, **não instrumentadas**), `core/evolution.py` (`EvolutionClient`: `enviar_texto`, `registrar_envio`, `envio_existe`, instâncias), `core/db.py` (`criar_pool`/`fechar_pool`/`conexao`, `prepare_threshold=None`), `core/storage.py` (MinIO) — reais ✓.
- `core/llm.py` (`criar_chat_anthropic` real: Sonnet 4.6, `thinking=disabled`, `effort=low`, `max_tokens=1024`, `max_retries=2`, `timeout=60`; `criar_anthropic_client` stub P1) ✓ [M0-T1]
- `agente/persona.py` (`render_persona` BP1=persona+regras GERAL + `carregar_faq` BP2, ambos `lru_cache` via Jinja; `IdentidadeModelo`/`render_identidade` + `render_programas`/`render_bp3` consumidos no BP3 ✓ [M2-T1]) + `prompts/regras.md.j2` (Jinja no `<desconto>` p/ `desconto_max_pct`, ADR-0004); dep `jinja2` adicionada ✓ [M0-T2]
- `agente/llm.py` (`build_system_messages` BP1+BP2 + `_bloco_texto`; `cache_control` em content blocks 1.x; emite o 3º bloco BP3 quando `modelo_md` é passado, com guarda de ordenação de TTL) ✓ [M0-T3 + M2-T1]
- `workers/timeouts.py` (`aplicar_timeout_longo/interno`, `confirmar_em_execucao`) + `workers/settings.py` (`WorkerSettings`, **só crons**, `functions=[]`) ✓.
- `webhook/routes.py` — token + JID + persistência idempotente + comandos de grupo via `aplicar_comando` ✓; **webhook fino** (persiste `atendimento_id=NULL` + `enfileirar_turno`; `garantir_conversa` faz upsert da conversa sem criar atendimento) ✓ [M3c].
- `dominio/escaladas/service.py` — `aplicar_comando:25`, `_atualizar_pix:248` (já não trava o fluxo, `07 §5`), `abrir_handoff:315` ✓.
- `dominio/atendimentos/service.py:23` — `garantir_atendimento_aberto` ✓.
- Migrations presentes: `comprovantes_pix.card_message_id` (`20260523220842_comprovante_pix_card.sql`), `reengajado_em` (`20260523231500_reengajamento.sql`), `modelo_midia` (com `tag/tipo/aprovada/bucket/object_key`, `0001:375`; `ultimo_envio_em` ✓ [M5e] em `20260527154854_modelo_midia_ultimo_envio.sql`), `atendimentos` (`ia_pausada/aviso_saida_em/foto_portaria_em/pix_status`, `0001:432`).
- `pyproject.toml` — `langchain-anthropic>=1.4.3` ✓ (lock real: lc-anthropic 1.4.3 · anthropic 0.97 · langgraph 1.1.10).
- `evals/` — estrutura + 5 fixtures seed (`canonicos/leitura/001`, `canonicos/cache_hit/001`, `adversariais/{disclosure,cross_modelo,jailbreak}/001`). README é fonte de verdade do schema.

### 1.2 Placeholder / docstring-only (a implementar)
- `agente/nos/tools.py` → `ToolNode(TOOLS)` (loop ReAct ativo, executa tool_calls) ✓ [M1-T2]. `prepare_context` (gate `ia_pausada` → `Command(goto=END)`; BP1+BP2 + sliding window 20 traduzida; caminho normal → `intercept_disclosure` por Command, sem aresta estática) ✓ [M0-T4] + contexto dinâmico (`_anexar_contexto_dinamico`) no último HumanMessage ✓ [M1-T2]; `intercept_disclosure` (passthrough `Command(goto="llm")`), `llm` (factory `no_llm`, `Command` routing, check `stop_reason`) e `post_process` (refetch `ia_pausada`, zera texto se pausou) já reais ✓ [M0-T5].
- `core/redis.py` (`adquirir_lock`/`LockBusy`, heartbeat, release Lua) ✓ [M3b]; `webhook/{despacho,debounce}.py` (`enfileirar_turno` + helpers) ✓ [M3c]; `webhook/filtro.py` → docstring; `workers/pix.py` (`validar_pix` via vision OpenRouter) ✓ [M5c].
- `workers/envio.py` → `enviar_turno`/`enviar_card` ✓ [M4c/M4d]; `_card_pix` real ✓ [M5c]; `_card_chegada`/`_card_aviso_saida` reais ✓ [M5d]. `workers/media.py` → `transcrever_audio` ✓ [M5a], `rotear_imagem` ✓ [M5b], `_handoff_foto_portaria` real (via `handoff_foto_portaria_ia` em `dominio/atendimentos/service.py`) ✓ [M5d].
- `agente/classificador.py` → docstring (classificador interno/externo **P1**, não confundir com `_classificador.py` do disclosure).

### 1.3 Não existe (a criar)
- `agente/_classificador.py` (regex disclosure/jailbreak) ✓ [M3g]; `workers/coordenador.py` (`processar_turno`) ✓ [M3b]; `workers/_chunking.py` (M4a).
- `dominio/atendimentos/service.py:registrar_extracao_ia` (transição + bloqueio + guarda do piso) ✓ [M3d]; `dominio/agenda/service.py:criar_bloqueio_previo` (advisory lock + EXCLUDE → `ConflitoAgenda`) ✓ [M3d/M3e].
- Tools: `TOOLS = [consultar_agenda, registrar_extracao, pedir_pix_deslocamento, enviar_midia, escalar]` (ordem canônica `04 §4`); `leitura.py` ✓ [M1-T1], `_idempotencia.py` ✓ [M3a], `extracao.py` ✓ [M3d], `pix.py` ✓ [M3e], `escalada.py` ✓ [M3f], `midia.py` ✓ [M5e]; `nos/tools.py` traz `_ToolNodeComMidiaIdx` (subclass que injeta `call_idx` ordinal por-invocação, `04 §3.3`).
- Templates: `prompts/` tem `persona.md`/`faq.md` **planos** + `regras.md.j2` (Jinja p/ `desconto_max_pct` ✓ [M0-T2]) + `contexto_dinamico.md.j2` ✓ [M1-T2] + `identidade.md.j2` + `programas.md.j2` (BP3 por-modelo) ✓ [M2-T1]. `workers/_cards/` tem `escalada.md.j2` ✓ [M4d] + `pix.md.j2` ✓ [M5c] + `chegada.md.j2` + `aviso_saida.md.j2` ✓ [M5d].
- Migrations: **`tool_calls`** ✓ [M3a], **`disclosure_tentativas`** ✓ [M3g], **`atendimento.intencao`** (enum + coluna) ✓ [M3d], **`modelo_midia.ultimo_envio_em`** ✓ [M5e] (`04 §3.3`) — todas via **nome timestamp** (`§6`).
- Dependência **`openai`** ✓ [M5a/M5c]: Whisper STT (cliente direto OpenAI) + vision Pix (cliente OpenAI-compat apontando para OpenRouter base_url) — `pyproject.toml` traz `openai>=1.50`.
- Zero testes de agente/grafo/coordenador. Runners de eval ausentes (só READMEs "TODO").

## 2. Marcos (M0 → P0)

| Marco | Objetivo | Definition of Done (verificável) |
|---|---|---|
| **M0 — Skeleton vivo** | O grafo responde de verdade com Sonnet 4.6; cache funciona | `uv run pytest tests/agente/test_skeleton.py` (gated por chave) verde: `graph.ainvoke` com `HumanMessage` real → `AIMessage` real; teste de cache (1ª chamada `ephemeral_*>0`, 2ª `cache_read>0`, `03 §5`); guard-rail BP1+BP2 byte-idêntico p/ 2 modelos; `make lint` + `make typecheck` limpos |
| **M1 — Leitura + loop ReAct** | IA decide chamar `consultar_agenda`; loop `llm↔tools` fecha | `uv run pytest tests/integracao/test_loop_leitura.py` verde (loop executa tool e retoma o LLM, `recursion_limit` ativo); fixture `canonicos/leitura/` chama `consultar_agenda` e nenhuma proibida |
| **M2 — Cache observável + BP3 por-modelo** | Prefixo global + camada por-modelo + métricas de token/cache | `uv run pytest tests/agente/test_bp3_render.py` + `test_prefixo_byte_identico.py`; fixture `canonicos/cache_hit/` mostra `cache_read>0` no 2º turno; `agente_turno_tokens_total{tipo}` instrumentado |
| **M3 — Coordenador + escrita + disclosure** | Turno fim-a-fim: webhook→ARQ→grafo→escrita idempotente→handoff | `uv run pytest tests/integracao/{test_coordenador_basico,test_tools_idempotencia,test_handoff_via_escalar,test_intercept_disclosure}.py`; `make migrate` aplica 2× sem erro; webhook enfileira `processar_turno` |
| **M4 — Humanização** | Envio chunk-by-chunk: presence, jitter, cancel, dedupe, read-receipt | `uv run pytest tests/unit/test_chunk_texto.py tests/integracao/{test_enviar_turno,test_enviar_card}.py`; ordem texto→mídia; `critico` não-cancelável |
| **M5 — Mídia + reengajamento** | Áudio, imagem/Pix, foto portaria, aviso saída, reabertura proativa | `uv run pytest tests/integracao/{test_transcrever_audio,test_rotear_imagem,test_validar_pix,test_foto_portaria,test_aviso_saida,test_reengajamento}.py`; `make migrate` (ultimo_envio_em) |
| **M6 — Evals gate (pronto-pra-piloto)** | Passar o gate do `08 §4` | runner K=5: `scripted_5` ≥4/5 cada; adversariais ≥90%/categoria e **0 vazamento**; write-rate ≤15%; custo ≤R$0,12; vision smoke ≥90%; checks manuais (`08 §4.2`) + runbooks (`08 §4.3`) |

## 3. Grafo de dependências

```
M0 (skeleton vivo) ──┬──> M1 (leitura + loop ReAct) ─────────────┐
                     └──> M2 (cache/BP3/métricas)   ∥ M1*         │   *overlap leve em prepare_context — coordenar
                                                                  │
M1 ─────────────────────────────────────────────────────────> M3 (coordenador + escrita + disclosure)
                                                                  ├─ M3a tool_calls migration + _idempotencia        (∥, dep M0)
                                                                  ├─ M3b coordenador.py + core/redis lock            (∥, dep M0)
                                                                  ├─ M3c webhook fino + despacho/debounce            (dep M3b)
                                                                  ├─ M3d registrar_extracao + domínio + guarda piso  (dep M3a)
                                                                  ├─ M3e pedir_pix + bloqueio prévio                 (dep M3a)
                                                                  ├─ M3f escalar + mapping abrir_handoff             (dep M3a)
                                                                  └─ M3g intercept + _classificador + migração disc. (∥, dep M0)
                                                                  │
M3 ─────────────────────────────────────────────────────────> M4 (humanização)
                                                                  ├─ M4a _chunking            (∥)
                                                                  ├─ M4b EvolutionClient ext  (∥)
                                                                  ├─ M4c enviar_turno         (dep M4a+M4b+M3b)
                                                                  └─ M4d enviar_card          (dep M4b+M3f)
                                                                  │
M3+M4 ───────────────────────────────────────────────────────> M5 (mídia + reengajamento)
                                                                  ├─ M5a transcrever_audio (openai)  (∥)
                                                                  ├─ M5b rotear_imagem (dep M3b)
                                                                  ├─ M5c validar_pix (OpenRouter)    (∥)
                                                                  ├─ M5d foto_portaria (dep M4d)
                                                                  ├─ M5e aviso_saida (via agente)
                                                                  └─ M5f reengajar (dep M4c)
                                                                  │
M1..M5 ──────────────────────────────────────────────────────> M6 (gate)  [runner+fixtures podem começar ∥ desde M3]
```

- **Caminho crítico serial:** `M0 → M1 → M3{b,d,f} → M4c → M5{b,c,d} → M6`.
- **Branches paralelas (worktrees/branches separadas):** `M2 ∥ M1`; dentro de M3 `{M3a, M3b, M3g}` arrancam juntas após M0; `M4a ∥ M4b`; `M5a ∥ M5c`; scaffolding de runner + autoria de fixtures do M6 desde o M3.
- **Convenção de branch** (`CLAUDE.md`): `feat/agente-<verbo>`. Ex.: `feat/agente-no-llm` (M0), `feat/agente-coordenador` (M3b), `feat/agente-humanizacao` (M4).

## 4. Bugs e decisões (árbitro)

Pontos onde a spec, o código e as decisões de sabatina precisam ser conciliados. **Ler antes de codar o marco correspondente.**

### 4.1 Roteamento por `Command(goto)`, não por flags de state — [decisão M0]
`03 §7` (linhas com `_rota_pos_intercept`/`_rota_pos_llm` e `conditional_edges(lambda s: s.get("_pausada"))`) é **superado**. `estado.py` não tem `_pausada/_intercept/_motivo_escalada` por decisão M0 (memória `decisoes_m0_pre_codificacao`): os nós de decisão retornam `Command(goto=...)`. Vence o **código + decisão M0**. Aplicar em `prepare_context` (pausa → `Command(goto=END)`), `llm` (tem tool_calls → `Command(goto="tools")`, senão `"post_process"`; exaustão/refusal → escala), `intercept_disclosure` (canned → `"post_process"`; jailbreak/3ª → escala+END; normal → `"llm"`). **Não reintroduzir** os flags. **Armadilha (verificada M0-T4):** um nó que faz `Command(goto=END)` **não pode ter aresta estática de saída** — `add_edge` + `Command` fazem fan-out (as duas saídas rodam em paralelo) e o turno chamaria o `llm` mesmo pausado. Por isso `prepare_context` roteia o caminho normal **também** por `Command(goto="intercept_disclosure")` e o `graph.py` **não** tem `add_edge("prepare_context", ...)`. Vale p/ qualquer nó com `Command(goto=END)` (intercept no M3g; loop no M1-T2 ao mexer no wiring).

### 4.2 Retry pelo SDK, não `ChatComRetry` manual — [decisão M0]
`03 §6.3` mostra um `ChatComRetry`; a decisão M0 delega retry ao `max_retries` do `ChatAnthropic` (SDK). O que **permanece** é o check de `stop_reason` (`refusal`/`max_tokens` chegam em **200 OK**, não como exceção — `docs/claudedocs/stop.md`): vive **dentro do `try/except` do nó `llm`**, logo após `chat.ainvoke()`. `refusal` → escala (`motivo="modelo_recusou"`); `max_tokens` → `TURNO_TRUNCADO.inc()` + log, **não escala no P0**.

### 4.3 `escalar` adapta-se à `abrir_handoff` shipada — [decisão aprovada 2026-05-24]
`abrir_handoff(conn, *, atendimento_id, responsavel: str, tipo: TipoEscalada, resumo_operacional, acao_esperada, origem, autor, observacao=None, card_message_id=None)` é usada por painel/comandos — **não alterar a assinatura**. A tool `escalar` (e `escalar_por_exaustao`) recebem `motivo` (enum `04 §3.4`) e passam por uma **camada de mapeamento** `motivo → (tipo: TipoEscalada, responsavel)` em `dominio/escaladas/service.py`, chamando a `abrir_handoff` existente. Pré-req da tarefa M3f: **ler `infra/sql/0039_escalada_tipo_enum.sql` e o enum `TipoEscalada`** em `escaladas/modelos.py` para montar o mapa (AUP-família + `politica_nova_necessaria/exaustao_iteracoes/timeout_grafo/modelo_recusou` → Fernando; `fora_de_oferta/horario_indisponivel/reagendamento_pos_bloqueio` → modelo; `outro` → Fernando). O `motivo` literal entra em `observacao`.

### 4.4 Prompts `.md.j2` onde interpolam variável — [árbitro: spec `03` + ADR-0004]
`agente/CLAUDE.md` diz "prompts são `.md`" e o código tem `.md`; `03` usa `.md.j2`. Resolução: `regras.md → regras.md.j2` (interpola `desconto_max_pct`, `03 §3.1 <desconto>` + ADR-0004); `identidade.md.j2`/`programas.md.j2`/`contexto_dinamico.md.j2` nascem como Jinja (BP3 + dinâmico). `persona.md` e `faq.md` ficam **planos** (sem variável; `03 §3.2` FAQ é arquivo versionado). Atualizar a nota de `agente/CLAUDE.md` para "markdown, com Jinja onde há variável".

### 4.5 `build_graph` e injeção do chat — [resolver no M0]
Código: `build_graph(checkpointer=None)`; `03 §7`: `build_graph(settings)`; `07 §2`: `build_graph()`. O nó `llm` precisa do `ChatAnthropic`. Resolução M0: `build_graph(settings=None, checkpointer=None)` — quando `settings is None`, usa `get_settings()`; constrói o chat via `criar_chat_anthropic(settings)` e injeta no nó `llm` por factory (`no_llm(chat, TOOLS)`) ou closure. Mantém `checkpointer` opcional (P1). O nó continua registrado como `"llm"`.

### 4.6 Grafo vive no worker ARQ; `app.state.graph` é opcional no P0 — [decisão]
`00 §Status` lista "lifespan não monta `app.state.graph`" como gap M0. Mas no P0 **nada no path HTTP invoca o grafo** — o webhook só enfileira; o `processar_turno` (worker ARQ) é quem chama `graph.ainvoke` (`07 §2`, `ctx["graph"] = build_graph()`). Resolução: o grafo é construído no **startup do worker** (M3b); o `test_skeleton` (M0) constrói o grafo direto. **Não** montar `app.state.graph` no FastAPI no P0 (sem consumidor); revisar só se um endpoint síncrono surgir.

### 4.7 `recursion_limit=18` é empírico e dormente até M1 — [`07 §3`, `03 §8`]
`RECURSION_LIMIT=18` (`07 §3`) conta **passos de nó**, acoplado à topologia. **Dormente no skeleton linear** (sem loop `llm↔tools`) — só passa a importar em M1. **Validar empiricamente** (não confiar na fórmula `2×iter+5`) e **revalidar ao adicionar/remover nós**. `GraphRecursionError` é capturado **por classe** (`langgraph.errors`), não por string.

### 4.8 Migrations novas usam nome timestamp — [`infra/sql/CLAUDE.md`]
`04 §5` sugere `0012_tool_calls.sql`, mas `0012_bucket_rename.sql` **já existe** e o max NNNN é `0039`. Migrations aplicadas são imutáveis. **Toda migration nova deste roteiro usa `YYYYMMDDHHMMSS_*.sql`** (gerar com `[DateTime]::UtcNow.ToString('yyyyMMddHHmmss')`), idempotente (`IF NOT EXISTS`), com RLS ou `COMMENT ... 'interna: sem RLS porque ...'`. A `modelo_midia.ultimo_envio_em` **substitui** a `0013_modelo_midia_descricao.sql` cogitada em versões antigas — `descricao` não é mais necessária (`04 §3.3`).

### 4.9 `keep_result=0` para `processar_turno` — [`07 §2` nota]
O `keep_result=3600` global do `WorkerSettings` quebra o re-enqueue do drain (`_job_id` estático `turno:{conversa_id}`) por 1h após o término (`arq#416/#432`) → trabalho do drain perdido em silêncio. `processar_turno` deve ter **`keep_result=0`**. Tarefa M3b inclui teste de integração que estoura `MAX_DRAIN` e afirma que o restante roda.

### 4.10 Worker no Windows exige `WindowsSelectorEventLoopPolicy` — [memória `backend-windows-selector-loop`]
`main.py:20` já aplica. O **worker ARQ** roda em processo próprio; o `startup` do `WorkerSettings` (M3b) precisa do mesmo guard antes do loop em dev Windows, senão `PoolTimeout` no psycopg async. Produção é Linux.

### 4.11 `ChatAnthropic`: construir com `model=`, ler `.model` — [M0-T1, verificado 2026-05-24]

O `03 §6.2` mostra `ChatAnthropic(model_name=modelo, ...)` e o aceite do M0-T1 lia `.model_name`. Na `langchain-anthropic` **1.4.3** (lock) o campo é `model: str = Field(alias="model_name")` com `populate_by_name=True`: o alias `model_name` é **só de escrita** e o **plugin pydantic do mypy (`strict`)** sintetiza o `__init__` pelo nome do campo. Logo `model_name=` falha o typecheck (`call-arg: Missing named argument "model"`) e a leitura `.model_name` dá `AttributeError` — **construa com `model=` e leia `.model`**. Vence o **código**. Demais kwargs por alias passam: `max_tokens`, `timeout` (→ `default_request_timeout`), `api_key` (→ `anthropic_api_key: SecretStr`; `settings.anthropic_api_key` `str | None` passa no mypy e coage em runtime, `.env` provê a chave); `effort`/`thinking` são kwargs diretos. Aplicado em `core/llm.py`; aceite ajustado p/ `.model`. **Reaparece em M0-T3/M2/M3b** (que seguem o pseudocódigo do `03 §6.2`).

## 5. Tarefas por marco

> Formato: **Objetivo** (verificável) · **Carregar** (docs/§ + arquivos) · **Tocar** (criar/editar) · **Aceite** (comando/critério) · **Depende de** · **Paralelizável com**.

### M0 — Skeleton vivo

#### M0-T1 — `core/llm.py`: factory do chat Anthropic — ✅ FEITO (2026-05-24)
- **Objetivo:** implementar `criar_chat_anthropic(settings, *, modelo=None) -> ChatAnthropic` de modo que devolva um `ChatAnthropic` configurado (Sonnet 4.6, `thinking=disabled`, `effort=low`, `max_tokens=1024`, `max_retries=2`, `timeout=60`); `criar_anthropic_client` fica como stub reservado (P1). Adicionar a `settings.py` os campos `cache_ttl_geral="1h"`, `cache_ttl_modelo="1h"`, `anthropic_thinking="disabled"`, `anthropic_effort="low"`, `anthropic_max_tokens=1024`.
- **Carregar:** `03 §6.1`, `03 §6.2`, `01 §2.6`; `api/src/barra/core/llm.py`, `api/src/barra/settings.py`.
- **Tocar:** `core/llm.py`, `settings.py`.
- **Aceite:** `uv run python -c "from barra.core.llm import criar_chat_anthropic; from barra.settings import get_settings; print(criar_chat_anthropic(get_settings()).model)"` imprime `claude-sonnet-4-6`; `make lint typecheck` limpos.
- **Depende de:** nenhuma.
- **Paralelizável com:** M0-T2.

#### M0-T2 — Prompts BP1/BP2 + `agente/persona.py` (render geral) — ✅ FEITO (2026-05-24)
- **Objetivo:** `render_persona()` (BP1 = persona + regras, GERAL) e carregamento de `faq.md` (BP2) com `lru_cache`, via `jinja2.Environment` apontando para `prompts/`. Converter `regras.md → regras.md.j2` interpolando `desconto_max_pct` (`<desconto>` de `03 §3.1`; bloco `else` quando `0`). `persona.md`/`faq.md` ficam planos. `IdentidadeModelo` + `render_identidade` ficam declarados mas só usados em M2 (BP3).
- **Carregar:** `03 §2`, `03 §3.1`, `03 §3.2`, ADR-0004; `agente/CLAUDE.md`; `prompts/{persona,regras,faq}.md`.
- **Tocar:** `agente/persona.py` (criar), `prompts/regras.md.j2` (renomear+Jinja), `agente/CLAUDE.md` (nota `.md`→"Jinja onde há variável", `§4.4`).
- **Aceite:** `uv run pytest tests/agente/test_persona_render.py` — `render_persona()` retorna string não-vazia e idêntica em 2 chamadas; com `desconto_max_pct=0` o texto contém "não concede desconto".
- **Depende de:** nenhuma.
- **Paralelizável com:** M0-T1.

#### M0-T3 — `agente/llm.py`: `build_system_messages` com `cache_control` — ✅ FEITO (2026-05-24)
- **Objetivo:** `_bloco_texto(texto, ttl)` + `build_system_messages(*, geral_md, faq_md, ttl_geral)` retornando **2** `SystemMessage` (BP1+BP2) com `cache_control` em **content blocks** (formato langchain-anthropic 1.x). Validar ordenação de TTL (`ttl_geral` ≥ `ttl_modelo` quando BP3 entrar — deixar o parâmetro `modelo_md`/`ttl_modelo` preparado mas opcional; M2 ativa o 3º bloco).
- **Carregar:** `03 §1`, `03 §4`, `03 §5`; `agente/CLAUDE.md` (invariante de prefixo).
- **Tocar:** `agente/llm.py` (criar).
- **Aceite:** `uv run pytest tests/agente/test_build_system.py` — saída tem 2 blocos; cada um com `content=[{type:text, cache_control:{type:ephemeral, ttl:"1h"}}]`; byte-idêntico para `geral_md` igual.
- **Depende de:** M0-T2.
- **Paralelizável com:** M0-T1.

#### M0-T4 — `nos/prepare_context.py`: gate + system + sliding window — ✅ FEITO (2026-05-24)
- **Objetivo:** implementar `prepare_context` (gate `ia_pausada` via 1ª query → `Command(goto=END)`; senão monta `build_system_messages(BP1+BP2)` + `traduzir_mensagens(carregar_mensagens(...))` da sliding window 20, `02 §4`). Implementar `traduzir_mensagens` e a query (`02 §4.1`/`§4.2`). **Sem** contexto dinâmico/reminder ainda (M1/M2). Sem `_pausada` no state — usar `Command`.
- **Carregar:** `02 §4`, `02 §5`, `03 §7`, `§4.1` deste doc; `agente/nos/prepare_context.py`, `agente/estado.py`, `agente/contexto.py`.
- **Tocar:** `nos/prepare_context.py`, `graph.py` (remove a aresta estática de saída de `prepare_context`), `tests/agente/test_prepare_context.py` (criar).
- **Aceite:** `uv run pytest tests/agente/test_prepare_context.py` (Postgres de teste): com `ia_pausada=true` retorna `Command(goto=END)`; senão retorna `messages` = 2 SystemMessage + N HumanMessage cronológicos; `modelo_manual` vira `AIMessage` com prefixo.
- **Depende de:** M0-T3.
- **Paralelizável com:** M0-T5 (após M0-T3).
- **Nota (verificado):** `str` em `WHERE uuid_col = %s` funciona no psycopg3 sem `::uuid` (OID unknown → PG infere) — vale p/ as queries de M1/M3. Retorno tipado `Command[Literal["intercept_disclosure","__end__"]]`; o `goto=END` leva `# type: ignore[arg-type]` (END = `sys.intern("__end__")` é `str` upstream) — reaparece no M3g.

#### M0-T5 — `nos/llm.py` real + `graph.py` (Command routing) + `ferramentas/__init__.py` TOOLS — ✅ FEITO (2026-05-24)
- **Objetivo:** nó `llm` chama `ChatAnthropic.bind_tools(TOOLS)` (TOOLS=`[]` no M0), faz `await chat.ainvoke(state["messages"])`, checa `stop_reason` (`§4.2`), retorna `Command(goto="post_process")` (sem tool_calls) ou `{"messages":[resp]}`. `post_process` minimal (refetch `ia_pausada`; se true zera o texto). `graph.py`: resolver assinatura (`§4.5`), wiring `prepare_context →(Command)→ intercept(passthrough)→ llm →(Command)→ post_process → END`. `intercept_disclosure` passthrough (`Command(goto="llm")`). `ferramentas/__init__.py` exporta `TOOLS=[]`.
- **Carregar:** `03 §7`, `01 §2.1`, `§4.1`/`§4.2`/`§4.5` deste doc; `agente/nos/{llm,post_process,intercept_disclosure}.py`, `agente/graph.py`.
- **Tocar:** `nos/llm.py`, `nos/post_process.py`, `nos/intercept_disclosure.py`, `graph.py`, `ferramentas/__init__.py`.
- **Aceite:** `uv run python -c "from barra.agente.graph import build_graph; build_graph()"` compila; `make typecheck` limpo.
- **Depende de:** M0-T1.
- **Paralelizável com:** M0-T4 (coordenar `graph.py` ↔ `prepare_context`).
- **Nota (gotcha de tipo):** nó injetado por factory **não** pode ser tipado `Callable[[State, Runtime], …]` — o protocolo `_NodeWithRuntime` do langgraph declara `runtime` **keyword-only** (`*, runtime`), incompatível com os params posicionais do `Callable` (e exige `Coroutine`, não `Awaitable`). Tipar o retorno do factory como `Protocol` (`__call__(self, state, *, runtime)`); um `async def` comum satisfaz. As anotações `-> Command[Literal[...]]` nos nós inferem as arestas condicionais + passam o mypy strict. Reaparece no **M3b**.

#### M0-T6 — Testes de M0 (skeleton + cache + guard-rail) — ✅ FEITO (2026-05-24)
- **Objetivo:** `test_skeleton_responde` (gated por `ANTHROPIC_API_KEY`, marker `needs_key`): seed conversa+1 mensagem cliente, `graph.ainvoke({"messages":[]}, context=...)` retorna `AIMessage` com `content` não-vazio. `test_cache_write_read` (gated): 1ª chamada `(ephemeral_5m_input_tokens+ephemeral_1h_input_tokens)>0`; 2ª idêntica `cache_read>0` (`03 §5`; **não** assertar `cache_creation>0`). `test_prefixo_byte_identico` (sem chave): BP1+BP2 byte-idênticos p/ 2 `modelo_id` distintos (`agente/CLAUDE.md` guard-rail #1).
- **Carregar:** `03 §5`, `08 §7`, `agente/CLAUDE.md`.
- **Tocar:** `tests/agente/test_skeleton.py` (criar), `tests/conftest.py` (marker `needs_key` + skip sem chave).
- **Aceite:** `uv run pytest tests/agente/test_skeleton.py -m "not needs_key"` verde sem chave; com chave, `uv run pytest tests/agente/test_skeleton.py` verde.
- **Depende de:** M0-T4, M0-T5.
- **Paralelizável com:** —.

#### M0-T7 — Teste de integração de repositório (Postgres real) — ✅ FEITO (2026-05-24)
> Tarefa **adicional** (fora do escopo original do M0, decidida em conversa): a suíte do M0 é toda fake (`FakeConn`); falta um teste que prove contra o **Postgres real** o que o fake não cobre — que a query de `carregar_mensagens` casa com o schema e que o isolamento por par (cliente, modelo) é real no banco.
- **Objetivo:** `tests/agente/test_repo_integracao.py` (2 testes `@pytest.mark.needs_db`): (1) `test_carregar_mensagens_cronologica` — seed `modelo+cliente+conversa+3 mensagens` (cliente/ia/modelo_manual, `created_at` crescente) → `carregar_mensagens(conn, cliente_id, modelo_id)` devolve 3 linhas cronológicas com as colunas exatas (`id, direcao, tipo, conteudo, media_object_key, created_at`); (2) `test_isolamento_por_par` — MESMO cliente, 2 modelos (A e B), conversa+mensagem em cada → carregar pela modelo A NÃO traz nada de B (`agente/CLAUDE.md` "Isolamento por par"). **Importa e testa** `carregar_mensagens` (não reescreve a query).
- **Carregar:** `02 §4`, `§0`/`§1`/`§4` deste doc, `agente/CLAUDE.md`, `api/CLAUDE.md`; `agente/nos/prepare_context.py` (`carregar_mensagens`), `core/db.py` (`row_factory=dict_row`), `infra/sql/0001_schema_inicial.sql` (NOT NULL/FK de modelos/clientes/conversas/mensagens), `tests/conftest.py`.
- **Tocar:** `tests/agente/test_repo_integracao.py` (criar), `tests/conftest.py` (marker `needs_db` + skip sem `TEST_DATABASE_URL`; `WindowsSelectorEventLoopPolicy` em win32 — sem quebrar o `needs_key` do M0-T6).
- **Aceite:** com `TEST_DATABASE_URL` setada, `uv run pytest tests/agente/test_repo_integracao.py` verde; sem a env, **2 skipped**; `uv run pytest -m "not needs_db and not needs_key"` segue verde (suíte padrão intocada).
- **Depende de:** M0-T4.
- **Paralelizável com:** M0-T6.
- **Nota (inegociáveis/gotchas):** aponta pro **Postgres de PROD self-hosted** (vazio no piloto) via `TEST_DATABASE_URL` — **NÃO** `DATABASE_URL` (o conftest força `""`); cada teste roda numa transação com **ROLLBACK sempre no teardown** (nunca commit → seguro apontar pro banco de prod). Fixture async via `@pytest_asyncio.fixture` (`asyncio_mode=auto`). O **role da conexão precisa fazer bypass de RLS** (service_role/superuser, como o backend já faz): o schema tem `FORCE ROW LEVEL SECURITY` e a policy depende de `auth.uid()`. Enum scalar e array via `%s` bare em `VALUES` coagem (psycopg manda `str` como OID *unknown* → PG infere o tipo da coluna; precedente em `webhook/routes.py`/`modelos/routes.py`); IDs vão como objetos `UUID` (adaptação nativa) e o array leva `::tipo_atendimento_enum[]` como rede extra. `prepare_threshold=None` espelha `core/db.py` (Supavisor transaction mode). Memória `testes_db_fake_vs_real`.

### M1 — Leitura + loop ReAct

#### M1-T1 — `consultar_agenda` + `ToolRuntime` — ✅ FEITO (2026-05-24)
- **Objetivo:** implementar `consultar_agenda(data_inicio, data_fim, runtime)` em `ferramentas/leitura.py` (query `bloqueios`, limite 14 dias, retorno markdown — `04 §2.1`); registrar em `TOOLS`.
- **Carregar:** `04 §2.1`, `02 §6`, `04 §1.1`; `agente/ferramentas/__init__.py`, `agente/contexto.py`.
- **Tocar:** `ferramentas/leitura.py` (criar), `ferramentas/__init__.py`.
- **Aceite:** `uv run pytest tests/agente/test_consultar_agenda.py` (Postgres): com bloqueios retorna markdown listado; janela >14 dias retorna `"ERRO: ..."`.
- **Depende de:** M0-T5.
- **Paralelizável com:** M2-*.
- **Nota (gotcha verificado 2026-05-24):** `ToolRuntime[ContextAgente]` força o `@tool` a resolver `get_type_hints(ContextAgente)` ao montar o args-schema. Como `contexto.py` tinha os imports (`AsyncConnectionPool`/`ArqRedis`/`Any`) sob `TYPE_CHECKING` + `from __future__ import annotations`, a resolução estourava `NameError`, o langchain **engolia** e o schema vinha vazio (`tool.args == set()` — a tool não enviaria args ao LLM; passa no import, quebra em prod). Fix: imports do `ContextAgente` em **runtime** (top-level), alinhando com `04 §1.1` (que já os documenta assim). **Não** mover de volta p/ `TYPE_CHECKING` num "lint cleanup" — quebra o schema de TODAS as tools; reaparece no M3{d,e,f,g} (mesma `ToolRuntime[ContextAgente]`). O EN DASH `–` do `04 §2.1` dispara `RUF001` → trocado por hífen no render.

#### M1-T2 — `tools_node` + loop `llm↔tools` + contexto dinâmico — ✅ FEITO (2026-05-24)
- **Objetivo:** `tools_node` = `ToolNode(TOOLS)` (executa tool_calls, injeta `midia_idx` como `call_idx` quando aplicável — relevante só p/ `enviar_midia` em M3). `graph.py`: `llm →(Command: "tools" se tool_calls)→ tools → llm` (loop), `recursion_limit=18` (`§4.7`). `prepare_context` ganha `_anexar_contexto_dinamico` (atendimento/cliente/agenda 48h no **último HumanMessage**, sem `cache_control`, `02 §5`) + template `contexto_dinamico.md.j2`.
- **Carregar:** `02 §5`, `03 §3.4`, `03 §7`, `03 §8`, `§4.7`; `agente/nos/{tools,llm,prepare_context}.py`, `agente/graph.py`.
- **Tocar:** `nos/tools.py`, `nos/prepare_context.py`, `graph.py`, `persona.py` (`render_contexto_dinamico`), `prompts/contexto_dinamico.md.j2` (criar).
- **Aceite:** `uv run pytest tests/integracao/test_loop_leitura.py tests/agente/test_contexto_dinamico.py` (needs_db) verde — o loop executa `consultar_agenda` de verdade e retorna `AIMessage` final; `recursion_limit=18` → `GraphRecursionError` no loop infinito; contexto dinâmico só no último HumanMessage. `make lint typecheck` limpos.
- **Depende de:** M1-T1.
- **Paralelizável com:** M2-*.
- **Nota (feito 2026-05-24):** LLM mockado por **fake chat roteirizado** (monkeypatch de `barra.agente.graph.criar_chat_anthropic`), não `respx` — o teste prova a mecânica do loop sem HTTP, então é `needs_db` (não `needs_key`). `_anexar_contexto_dinamico` concatena no último HumanMessage (defesa: vira HumanMessage novo se a janela não tiver nenhum) e reusa a conexão já aberta do gate; `historico_anteriores` via `_resumir_historico` (agrupa `Fechado`/`Perdido` do par). **Fix de template:** o `{% for %}` da agenda em `02 §5` grudava múltiplos bloqueios numa linha — corrigido (`{% endfor %}` em linha própria) no doc e no `.md.j2`; o teste com 2 bloqueios trava a regressão. **Dívida (suprida no M1-T3):** o contexto dinâmico nasceu **sem a data atual** (`04 §2.1`); a linha `Hoje: {{ data_atual }}` (via `current_date` do banco em `_resolver_variaveis`) entrou no M1-T3 — sem a âncora de "hoje" as fixtures positivas (>48h) ficavam flaky e a tool não tinha como montar datas absolutas.

#### M1-T3 — Fixture canônica de leitura — ✅ FEITO (2026-05-24)
- **Objetivo:** revisar/curar `canonicos/leitura/001_consulta_agenda.jsonl` para um cenário que **realmente exija** a tool (consulta **além de 48h**, ex.: "sábado que vem" — a janela ≤48h é respondida pelo contexto, `04 §2.1`). Manter schema do `evals/README.md`.
- **Carregar:** `08 §2.2`, `04 §2.1`, `evals/README.md`; `evals/canonicos/leitura/001_consulta_agenda.jsonl`.
- **Tocar:** `evals/canonicos/leitura/001_consulta_agenda.jsonl` (+1-2 fixtures novas).
- **Aceite:** fixture valida contra o schema (JSON por linha, `par`+`expectativas`+`rubricas`); rodada manual no `test_loop_leitura` reproduz `tool_calls_obrigatorias=["consultar_agenda"]`. (Execução K=5 fica no M6.)
- **Depende de:** M1-T2.
- **Paralelizável com:** M2-*.
- **Nota (feito 2026-05-24):** `001_consulta_agenda.jsonl` recurado para >48h ("sábado da semana que vem", que de fato exige a tool); +2 fixtures — `002_consulta_alem_48h.jsonl` (>48h, fraseado diferente) e `003_disponibilidade_hoje_sem_tool.jsonl` (contraste ≤48h, com `consultar_agenda` em `tool_calls_proibidas`, guardando o outro lado da regra das 48h). Dois testes novos: `tests/agente/test_fixtures_leitura.py` (schema, DB-free — 5 passed) e `tests/agente/test_fixtures_leitura_decisao.py` (`needs_key`+`needs_db`, Sonnet real — 001/002 chamam `consultar_agenda`, 003 não; 3 passed). **Supriu a dívida do M1-T2** (data atual no contexto dinâmico — ver nota do M1-T2).

### M2 — Cache observável + BP3 por-modelo

#### M2-T1 — BP3 por-modelo (identidade + programas) — ✅ FEITO (2026-05-25)
- **Objetivo:** `build_system_messages` passa a emitir o **3º bloco** (`modelo_md`, `ttl_modelo`); `agente/persona.py:render_identidade(IdentidadeModelo)` + template `identidade.md.j2`; `programas.md.j2` + query `modelo_programas` (`03 §3.3`). `prepare_context` carrega identidade/programas do `modelo_id` e concatena no BP3. Validar ordenação TTL (`03 §1`/`§5`).
- **Carregar:** `03 §1`, `03 §2.1`, `03 §3.3`, `03 §5`, `01 §6.9`; `agente/{llm,persona}.py`, `agente/nos/prepare_context.py`.
- **Tocar:** `agente/llm.py`, `agente/persona.py`, `prompts/{identidade,programas}.md.j2` (criar), `nos/prepare_context.py`.
- **Aceite:** `uv run pytest tests/agente/test_bp3_render.py` — saída tem 3 blocos; BP3 contém nome/idade/programas do modelo de teste; BP1+BP2 seguem byte-idênticos entre 2 modelos (guard-rail #1).
- **Depende de:** M0-T3.
- **Paralelizável com:** M1-*.
- **Drift de schema resolvido (2026-05-25):** a query do `03 §3.3` usa `programas.duracao_horas`, mas essa coluna foi **removida** em `0009_programas_simplificar.sql`; pós-`0010_duracoes.sql` a duração é entidade própria (`duracoes`) e `modelo_programas` tem chave `(modelo_id, programa_id, duracao_id, preco)`. O BP3 usa o **schema real** (JOIN `programas`/`duracoes`, `duracao_nome`, `ORDER BY p.categoria NULLS FIRST, p.nome, d.ordem` — espelha o painel `dominio/modelos/routes.py`). Tabela flat `Programa | Duração | Valor`. `03 §3.3` foi anotado com o drift.
- **Colateral:** `build_system_messages` agora emite BP3 quando `modelo_md != None`; `_fakes.py:FakeConn` responde às queries de identidade/programas (default modelo pt-BR); `test_{prepare_context,build_system}.py` ajustados para 3 blocos system (eram 2 no M0).

#### M2-T2 — Instrumentação de tokens/cache + reminder — ✅ FEITO (2026-05-25)
- **Objetivo:** instrumentar `agente_turno_tokens_total{tipo}` lendo `usage_metadata["input_token_details"]` (read=`cache_read`; write=`ephemeral_5m+ephemeral_1h`, `03 §4.2`) — provisoriamente no nó `llm`/`post_process` (o coordenador reusa em M3). Adicionar `_injetar_reminder_se_necessario` (≥8 turnos da IA, `03 §10`) + `<instrucoes_meta>` em `regras.md.j2`. `TURNO_TRUNCADO` counter (`08 §3`).
- **Carregar:** `03 §4.2`, `03 §10`, `02 §10`, `08 §3`; `core/metrics.py`, `agente/nos/{llm,prepare_context}.py`, `prompts/regras.md.j2`.
- **Tocar:** `core/metrics.py`, `nos/llm.py`, `nos/prepare_context.py`, `prompts/regras.md.j2`.
- **Aceite:** `uv run pytest tests/agente/test_metricas_cache.py` (mock `usage_metadata`): write lido de `ephemeral_*` (não de `cache_creation`); reminder injetado só com ≥8 AIMessages.
- **Depende de:** M2-T1.
- **Paralelizável com:** M1-*.
- **Feito (2026-05-25):** `AGENTE_TURNO_TOKENS` instrumentada no nó `llm` (`_instrumentar_tokens`) nas 4 séries `{input,output,cache_read,cache_write}`; WRITE lido de `ephemeral_5m+ephemeral_1h` (NÃO de `cache_creation`, que vem 0 no langchain-anthropic 1.4.3 — spike 2026-05-24), label `modelo` = nome Anthropic via `chat.model`. `TURNO_TRUNCADO` (`agente_turno_truncado_total`, sem labels) criada em `metrics.py` e incrementada no ramo `stop_reason="max_tokens"` (substitui o `TODO(M2)`; P0 só observa, não escala — `§4.2`/`03 §6.3`). Reminder anti-drift (`_precisa_reminder`/`_injetar_reminder_se_necessario`) em `prepare_context`: PREPEND `<lembrete_silencioso>` no último HumanMessage com ≥8 AIMessages, DEPOIS do contexto dinâmico (ordem lembrete → msg → contexto, num único HumanMessage de cauda); `fase` reusa o `estado` resolvido — `_anexar_contexto_dinamico` agora retorna `(mensagens, fase)`, sem nova query. `<instrucoes_meta>` ensinado em `regras.md.j2` (edita BP1 → invalida o cache geral 1×, esperado/intencional). Counter opcional `agente_persona_reminder_injetado_total` incrementado ao injetar.
- **Colateral:** `tests/agente/test_metricas_cache.py` criado (token/truncado via fake chat + `usage_metadata` mockado, sem HTTP; reminder testado direto). Sem regressão em `test_{prepare_context,contexto_dinamico}` — o reminder só dispara com ≥8 AIMessages, acima das janelas desses testes.

#### M2-T3 — Fixture cache_hit — ✅ FEITO (2026-05-25)
- **Objetivo:** curar `canonicos/cache_hit/001_segundo_turno_cache.jsonl` para validar `cache_read>0` no 2º turno (medido em burst, `08 §3.1`).
- **Carregar:** `08 §3.1`, `08 §2.2`; `evals/canonicos/cache_hit/001_segundo_turno_cache.jsonl`.
- **Tocar:** a fixture.
- **Aceite:** fixture valida contra schema; `metricas` exige `cache_hit_rate>=0.70`. (Execução no M6.)
- **Depende de:** M2-T2.
- **Paralelizável com:** M1-*.
- **Decisão da chave de cache (2026-05-25):** a fixture usava `expectativas.metricas.cache_hit_rate_minimo` + rubrica `cache_hit_rate`, **ausentes** da tabela `08 §2.4`/README. Resolvido pela **via (a)** ("o doc é a fonte de verdade do schema"): `metricas.cache_hit_rate_minimo` foi **documentada** na tabela `08 §2.4` e nos "Campos críticos" do `evals/README.md` como métrica válida de fixture — piso de hit-rate (`cache_read`/input total), lido do `usage` da Anthropic e comparado pela rubrica determinística `cache_hit_rate`. Fixture e doc ficam consistentes; a alternativa (b) (alinhar a fixture às chaves já documentadas) foi descartada por esvaziar a única fixture que mede cache.
- **Feito (2026-05-25):** fixture recurada para 2 turnos no MESMO par `(cliente, modelo)` — turno 1 "Oi, tudo bem?", turno 2 "Adorei seu perfil…" (continuação conversacional **pura**: `tool_calls_proibidas` cobre `consultar_agenda`/`pedir_pix_deslocamento`/`registrar_extracao`/`escalar`, `estado_final=Triagem`, `ia_pausada_final=false`), de modo que o 2º turno reaproveite o prefixo inteiro (`tools` + BP1+BP2 GERAL + BP3 por-modelo). `descricao` corrigida de "4 breakpoints estaveis" → **3 blocos estáveis** (BP4/cache da cauda é P1, adiado) e marcada explicitamente como **smoke de BURST quente**, não o gate de produção (que é o **write-rate**, `08 §3.1`). `estado_inicial` completado (`pix_status`/`recorrente`) espelhando as fixtures de `leitura/`.
- **Colateral:** `tests/agente/test_fixtures_cache_hit.py` criado (DB-free, espelha `test_fixtures_leitura.py`; valida JSON-por-linha sem BOM, campos obrigatórios incl. `estado_inicial`, listas `tool_calls_*` disjuntas, `id` únicos — **3 passed**). Suíte padrão intacta (`-m "not needs_db and not needs_key"` → **152 passed**); `make lint`/`make typecheck` limpos. Execução K=5 contra o Sonnet real fica no **M6** (`08 §4.1`). **Com M2-T3, o marco M2 fecha.**

### M3 — Coordenador + escrita + disclosure

#### M3a — Migration `tool_calls` + helper de idempotência — ✅ FEITO (2026-05-25)
- **Objetivo:** migration timestamp criando `barravips.tool_calls` (PK `(turno_id, tool_name, call_idx)`, `04 §5`, RLS+grants). `ferramentas/_idempotencia.py:_executar_idempotente` (`04 §3`).
- **Carregar:** `04 §5`, `02 §8.2`, `§4.8`; `infra/sql/CLAUDE.md`.
- **Tocar:** `infra/sql/<ts>_tool_calls.sql`, `ferramentas/_idempotencia.py` (criar).
- **Aceite:** `make migrate` aplica 2× sem erro; `uv run pytest tests/integracao/test_tools_idempotencia.py::test_helper` (2ª chamada retorna resultado anterior, executor roda 1×).
- **Depende de:** M0.
- **Paralelizável com:** M3b, M3g.
- **Nota (feito 2026-05-25):** migration `20260525170706_tool_calls.sql` (PK `(turno_id,tool_name,call_idx)` + RLS + grants). `_executar_idempotente` grava `payload`/`resultado` como `%s::jsonb` com `json.dumps` (psycopg3 não adapta dict cru — memória `jsonb_param_psycopg`). Integrado na `main`.

#### M3b — `workers/coordenador.py` + `core/redis.py` (lock) + build_graph no worker — ✅ FEITO (2026-05-25)
- **Objetivo:** `processar_turno` (`07 §3`): lock `adquirir_lock`/`LockBusy` (`core/redis.py`, heartbeat, release Lua), `resolver_atendimento`+`atualizar_orfaos`, gates, `turno_id=uuid5(NS_TURNO,f"{job_id}:{loop_idx}")`, drain bounded `MAX_DRAIN=5`, `asyncio.wait_for(graph,60)`, `GraphRecursionError`/timeout → `escalar_por_exaustao`, cinto-suspensório, extrair resposta + métricas tokens. `WorkerSettings.startup` constrói `ctx["graph"]=build_graph()` (+ `WindowsSelectorEventLoopPolicy`, `§4.10`); `processar_turno` com `keep_result=0` (`§4.9`). `escalar_por_exaustao` usa o mapping do M3f.
- **Carregar:** `07 §2`, `07 §3`, `01 §4.3`, `02 §7`, `§4.6`/`§4.7`/`§4.9`/`§4.10`; `workers/settings.py`, `core/redis.py`, `dominio/{atendimentos,escaladas}/service.py`.
- **Tocar:** `workers/coordenador.py` (criar), `core/redis.py`, `workers/settings.py`.
- **Aceite:** `uv run pytest tests/integracao/test_coordenador_basico.py` (LLM mockado, Redis efêmero, Postgres): turno resolve atendimento, invoca grafo, despacha; `test_drain_excede_max` afirma re-enqueue ao estourar `MAX_DRAIN` (`§4.9`).
- **Depende de:** M0.
- **Paralelizável com:** M3a, M3g.
- **Nota (feito 2026-05-25):** `processar_turno` shipado com lock/heartbeat, drain bounded e cinto-suspensório; `keep_result=0` + `WindowsSelectorEventLoopPolicy` no startup do worker. `escalar_por_exaustao` nasceu com mapping local hardcode (`tipo=outro`/Fernando) + `TODO(M3f)` — **substituído pelo `mapear_motivo` no M3f**. Integrado na `main`.

#### M3c — Webhook fino + `despacho.py` + `debounce.py` — ✅ FEITO (2026-05-25)
- **Objetivo:** remover criação eager (`garantir_atendimento_aberto`) do path de mensagem do cliente — persistir com `atendimento_id=NULL` (`06 §0.1`). `despacho.enfileirar_turno` (`pending`+`debounce`+`enqueue_job` first-wins, `01 §4.2`). `debounce.py` helpers. Roteamento de áudio/imagem (`enqueue transcrever_audio`/`rotear_imagem`) fica como stub a completar no M5 (deixar os branches com TODO(M5)).
- **Carregar:** `01 §4.1`, `01 §4.2`, `06 §0.1`, `06 §6`; `webhook/{routes,despacho,debounce}.py`.
- **Tocar:** `webhook/routes.py`, `webhook/despacho.py`, `webhook/debounce.py`.
- **Aceite:** `uv run pytest tests/test_webhook_integration.py` (atualizado): mensagem texto persiste com `atendimento_id=NULL` e enfileira `processar_turno` (mock ARQ); comandos de grupo seguem funcionando.
- **Depende de:** M3b.
- **Paralelizável com:** M3d, M3e, M3f, M3g.
- **Nota (feito 2026-05-25):** webhook fino; extraído `garantir_conversa` (upsert da conversa sem criar atendimento) de `garantir_atendimento_aberto`. `main.py` cria o pool ARQ no lifespan (`app.state.arq`, guardado p/ `redis_url` vazio em dev/teste). A object_key da mídia passou a `conversas/{conversa_id}/...` (não há mais `atendimento.id` no path). Branches de áudio/imagem com `# TODO(M5)`. Teste fake (mock ARQ em `app.state.arq`), não `needs_db`. Integrado na `main`.

#### M3d — `registrar_extracao` + `registrar_extracao_ia` (domínio) + guarda do piso — ✅ FEITO (2026-05-25)
- **Objetivo:** tool `registrar_extracao` (wrapper ~10 linhas, `04 §3.1`) delegando a `dominio/atendimentos/service.py:registrar_extracao_ia` (UPSERT COALESCE + `limpar` + `_decidir_transicao` + bloqueio prévio interno + flag `enviar_pin`). **Guarda do piso** (ADR-0004): `valor_acordado` abaixo de `preco_tabela×(1−desconto_max_pct)` não grava e escala `fora_de_oferta`. Pin via `enqueue_job("enviar_card", tipo="loc_pin")` após commit.
- **Carregar:** `04 §3.1`, `02 §11`, ADR-0004, `01 §6.11`; `dominio/atendimentos/service.py`, `dominio/agenda/service.py`, `ferramentas/_idempotencia.py`.
- **Tocar:** `ferramentas/extracao.py` (criar), `dominio/atendimentos/service.py`, `ferramentas/__init__.py`.
- **Aceite:** `uv run pytest tests/integracao/test_registrar_extracao.py` — Novo→Triagem em extração; interno+horário→Aguardando_confirmacao+bloqueio; `valor_acordado` abaixo do piso escala (`fora_de_oferta`) e não grava.
- **Depende de:** M3a.
- **Paralelizável com:** M3c, M3e, M3f, M3g.
- **Nota (feito 2026-05-25):** `registrar_extracao_ia` + helpers em `dominio/atendimentos/service.py`. **Migration nova `20260525192240_atendimento_intencao.sql`** (enum + coluna `atendimentos.intencao`) — `intencao` precisa ser persistida porque governa transições de turnos seguintes (`Novo→Triagem`, `Triagem→Qualificado`). `motivo_perda_candidato` do `04 §3.1` **não tem coluna** (só vai no evento `extracao_registrada`). Guarda do piso usa o **MENOR** preço de tabela na duração (`duracoes.horas`) como base (ADR-0004 §Decisão 5, minimiza falso-positivo). `criar_bloqueio_previo` em `dominio/agenda/service.py` (compartilhado com M3e). Escala via `abrir_handoff` direto com mapping LOCAL `_escalar_modelo` + `TODO(M3f)` (ver follow-up no fim de M3). Integrado na `main`.

#### M3e — `pedir_pix_deslocamento` + bloqueio prévio externo — ✅ FEITO (2026-05-25)
- **Objetivo:** tool `pedir_pix_deslocamento()` (sem args, `04 §3.2`): lê chave/titular do modelo, UPSERT idempotente, `pix_status=aguardando`+`Aguardando_confirmacao`, `_criar_bloqueio_previo` (advisory lock + EXCLUDE, branch 13), retorno-guia (chave anexada pela humanização, não pelo LLM). `ConflitoAgenda`→erro recuperável.
- **Carregar:** `04 §3.2`, `01 §6.1`, `02 §11`; `dominio/agenda/service.py`, `ferramentas/_idempotencia.py`.
- **Tocar:** `ferramentas/pix.py` (criar), `ferramentas/__init__.py` (+ `dominio/agenda` se faltar `_criar_bloqueio_previo`).
- **Aceite:** `uv run pytest tests/integracao/test_pedir_pix.py` — externo qualificado → `Aguardando_confirmacao`+`pix_status=aguardando`+bloqueio criado; 2ª chamada idempotente; chave **não** no retorno da tool.
- **Depende de:** M3a.
- **Paralelizável com:** M3c, M3d, M3f, M3g.
- **Nota (feito 2026-05-25):** `pedir_pix_deslocamento` + `_aplicar_pedido_pix` (guard `WHERE pix_status='nao_solicitado'`), valor fixo R$100, chave Pix **fora** do retorno da tool (anexada pela humanização). `dominio/agenda/service.py` (`ConflitoAgenda` + `criar_bloqueio_previo`, advisory lock + EXCLUDE → `ConflitoAgenda` recuperável) foi criado em paralelo por M3d e M3e; o merge **deduplicou mantendo a versão M3d** (mais defensiva: `.get(data_desejada) or hoje BRT`). Integrado na `main`.

#### M3f — `escalar` + mapping `motivo→(tipo,responsavel)` — ✅ FEITO (2026-05-25)
- **Objetivo:** tool `escalar(payload)` (`04 §3.4`) idempotente; **mapping** em `dominio/escaladas/service.py` (`motivo`→`TipoEscalada`+`responsavel`, `§4.3`) chamando a `abrir_handoff` existente; card via `enqueue_job("enviar_card", tipo="escalada")`. `escalar_por_exaustao` (usado por M3b) usa o mesmo mapping. Métrica `agente_escalada_total{bucket,motivo}` (`08 §3.2`).
- **Carregar:** `04 §3.4`, `04 §3.5`, `04 §3.6`, `08 §3.2`, `§4.3`; `dominio/escaladas/{service,modelos}.py`, `infra/sql/0039_escalada_tipo_enum.sql`.
- **Tocar:** `ferramentas/escalada.py` (criar), `dominio/escaladas/service.py`, `ferramentas/__init__.py`, `core/metrics.py`.
- **Aceite:** `uv run pytest tests/integracao/test_handoff_via_escalar.py` — `escalar(disclosure_insistente)`→`ia_pausada=true`+responsavel Fernando; `fora_de_oferta`→modelo; `outro`→Fernando; coordenador descarta texto pós-escala.
- **Depende de:** M3a.
- **Paralelizável com:** M3c, M3d, M3e, M3g.
- **Nota (feito 2026-05-25):** `escalar` + `mapear_motivo`/`mapear_bucket` em `dominio/escaladas/service.py`; refatorou `coordenador.py:escalar_por_exaustao` p/ usar `mapear_motivo`. `abrir_handoff` real **não tem `motivo=`** (o pseudocódigo de `04 §3.1/§3.4` estava desatualizado; `§4.3` é o árbitro): o mapping converte `motivo→(tipo,responsavel)` e o motivo literal vai em `observacao`. `AGENTE_ESCALADA` **já existia** em `core/metrics.py` (instrumentada, não recriada) e é emitida na **camada do agente** (tool + `escalar_por_exaustao`), NÃO dentro de `abrir_handoff` — divergência consciente do `04 §3.6` (ela é compartilhada com painel/comandos, que não têm o enum de motivos). Integrado na `main`.

#### M3g — `intercept_disclosure` + `_classificador` + migration `disclosure_tentativas` + canned — ✅ FEITO (2026-05-25)
- **Objetivo:** migration `atendimentos.disclosure_tentativas`. `agente/_classificador.py:classificar_janela` (regex `10 §8`). `prepare_context` grava `_categoria/_confianca` no state. `intercept_disclosure` (`03 §7`, `10 §3.1`): jailbreak→escala direto; disclosure alta confiança→canned (pool em `agente/`, `Command(goto="post_process")`); contador idempotente por `turno_id`, escala na 3ª; ambíguo→`llm`. `enviar_midia` minimal precisa do `TOOLS` (registrar tool placeholder ou completa em M4) — registrar `enviar_midia` stub que anexa via `tool_calls`.
- **Carregar:** `10 §2`, `10 §3.1`, `10 §8`, `03 §7`, `01 §6.8`, `§4.1`; `agente/nos/{prepare_context,intercept_disclosure}.py`, `agente/estado.py`.
- **Tocar:** `infra/sql/<ts>_disclosure_tentativas.sql`, `agente/_classificador.py` (criar), `nos/prepare_context.py`, `nos/intercept_disclosure.py`, `agente/` (pool canned).
- **Aceite:** `uv run pytest tests/integracao/test_intercept_disclosure.py` — "vc é IA?" 1ª→canned (sem `escalar`, sem LLM); 3ª insistência→`escalar(disclosure_insistente)`; "ignore previous"→`escalar(jailbreak_attempt)` direto.
- **Depende de:** M0 (M3a só para o card de escala).
- **Paralelizável com:** M3b, M3c, M3d, M3e, M3f.
- **Nota (feito 2026-05-25, sessão anterior):** migration `20260525171444_disclosure_tentativas.sql`; `agente/_classificador.py:classificar_janela` (regex), `intercept_disclosure` (canned + contador idempotente por `turno_id` + escala na 3ª + jailbreak direto). Integrado na `main`.

> **Marco M3 fecha (2026-05-25).** As 7 subtarefas foram implementadas em worktrees paralelas e integradas na `main` (`db4a778`, via PRs/merges). Verificação na árvore mergeada: `ruff` limpo, `mypy` verde em 86 arquivos, **195 testes fake** + **30 `needs_db`** contra o Postgres self-hosted de prod (ROLLBACK sempre). Migrations do M3 (`tool_calls`, `disclosure_tentativas`, `atendimento_intencao`) já aplicadas no prod. **Follow-up aberto:** consolidar `dominio/atendimentos/service.py:_escalar_modelo` (M3d) para usar o `mapear_motivo` (M3f) em vez do mapping local — o `TODO(M3f)` ainda está no código. Próximo marco no caminho crítico: **M4 (humanização)**.

### M4 — Humanização

#### M4a — `workers/_chunking.py` — ✅ FEITO (2026-05-25)
- **Objetivo:** `chunk_texto` (`05 §2`): split por `\n\n`, preserva `\n` interno, cap 600 soft + `CHUNK_OVERSIZE`, cap 6 bolhas (funde excedente).
- **Carregar:** `05 §2`; `core/metrics.py`.
- **Tocar:** `workers/_chunking.py` (criar), `core/metrics.py` (`CHUNK_OVERSIZE`).
- **Aceite:** `uv run pytest tests/unit/test_chunk_texto.py` — `\n\n`→N bolhas; `\n` interno preservado; sentença >600 sai inteira + incrementa `CHUNK_OVERSIZE`; >6 blocos→6.
- **Depende de:** nenhuma (após M3).
- **Paralelizável com:** M4b.
- **Nota (feito 2026-05-25):** `chunk_texto` + helpers conforme `05 §2` (split `\n\n`, preserva `\n` interno, cap 600 soft → `CHUNK_OVERSIZE`, cap 6 bolhas fundindo o excedente no último). `CHUNK_OVERSIZE` (`agente_chunk_oversize_total`, sem labels) em `core/metrics.py`. Integrado na `main` (onda 1).

#### M4b — `EvolutionClient` ext (presence, mídia, read receipt) — ✅ FEITO (2026-05-25)
- **Objetivo:** `set_presence`, `enviar_midia` (espelha `enviar_texto`: POST→`envios_evolution`→`evolution_message_id`; kwarg `view_once` ignorado até suporte), `marcar_lida` (`05 §4.2`/`§5`).
- **Carregar:** `05 §4`, `05 §5`, `01 §6.13`; `core/evolution.py`.
- **Tocar:** `core/evolution.py`.
- **Aceite:** `uv run pytest tests/test_evolution_ext.py` (respx) — métodos chamam os endpoints corretos; `enviar_midia` grava `envios_evolution`; `marcar_lida` **não** grava.
- **Depende de:** nenhuma (após M3).
- **Paralelizável com:** M4a.
- **Nota (feito 2026-05-25):** `set_presence`/`enviar_midia`/`marcar_lida` em `core/evolution.py`. `enviar_midia` espelha `enviar_texto` (POST `sendMedia` → `registrar_envio` → `evolution_message_id`); `view_once` aceito mas **não** enviado no body (self-host ainda não expõe, `01 §6.13`). `marcar_lida` (`markMessageAsRead`, `read_messages=[{remoteJid,fromMe:false,id}]`) e `set_presence` (`sendPresence`) **não** gravam `envios_evolution`. Integrado na `main` (onda 1).

#### M4c — `enviar_turno` + wiring no coordenador — ✅ FEITO (2026-05-25)
- **Objetivo:** `workers/envio.py:enviar_turno` (`05 §1`/`§4`): read receipt+reading delay, loop chunks (cancel não-crítico via `turno_atual`, dedupe `enviados:{turno_id}` mark-after-send, presence, POST, INSERT `mensagens`, jitter), depois mídias. Falha final + `critico`→`escalar_por_exaustao` (`05 §7`). Coordenador (M3b) chama `despachar_humanizacao` com `critico` derivado de `tool_calls`. Registrar em `WorkerSettings.functions`.
- **Carregar:** `05 §1`, `05 §3`, `05 §4`, `05 §7`, `07 §3.4`; `workers/{envio,coordenador,settings}.py`.
- **Tocar:** `workers/envio.py`, `workers/coordenador.py`, `workers/settings.py`, `core/metrics.py` (`ENVIO_*`).
- **Aceite:** `uv run pytest tests/integracao/test_enviar_turno.py` (Evolution mockado) — ordem texto→mídia; nova msg cancela não-crítico; crítico entrega tudo; retry pula `enviados`.
- **Depende de:** M4a, M4b, M3b.
- **Paralelizável com:** M4d.
- **Nota (feito 2026-05-25):** `enviar_turno` + `_enviar_midias` + helpers de timing (`calcular_typing_ms`/`calcular_pausa_ms`/`calcular_reading_delay_ms`) + `_carregar_destino` (JOIN `conversas`/`modelos` + LATERAL p/ atendimento aberto), conforme `05 §4/§5`; wiring `chunk_texto` no coordenador. Falha final detectada por `ctx['job_try'] >= ctx.get('max_tries',5)` no `except` → se `critico`, `escalar_por_exaustao(motivo="envio_exaurido_critico")` (import tardio do coordenador p/ evitar ciclo); `envio_exaurido_critico` fica fora de `_BUCKET_DEFESA` → bucket `capacidade` (aceito, `§4.3`). **Gotcha:** a `ArqRedis` em `ctx['redis']` não usa `decode_responses` → `redis.get` devolve **bytes**; helper `_redis_eq` decodifica antes de comparar com `turno_id` (espelha `core/redis.py`). `ENVIO_{DURACAO,RESULTADO,RETRIES}` em `core/metrics.py`. Integrado na `main` (onda 2).

#### M4d — `enviar_card` (dispatch por tipo) — ✅ FEITO (2026-05-25)
- **Objetivo:** `enviar_card(ctx, *, tipo, **kw)` + `_RENDER_CARD` (`escalada/pix_validado/pix_em_revisao/chegada/aviso_saida/loc_pin`), Jinja, idempotência por owner (`card_message_id`/SETNX), via `EvolutionClient` (bypass humanização). Registrar em `WorkerSettings.functions`.
- **Carregar:** `05 §6`, `06 §2.5`, `06 §9` (idempotência por owner); `workers/envio.py`, `dominio/escaladas/service.py`.
- **Tocar:** `workers/envio.py`, `workers/settings.py`, templates de card.
- **Aceite:** `uv run pytest tests/integracao/test_enviar_card.py` — card de escalada grava `escaladas.card_message_id`; 2ª execução não reenvia.
- **Depende de:** M4b, M3f.
- **Paralelizável com:** M4c.
- **Nota (feito 2026-05-25):** `enviar_card` (dispatch) + `_RENDER_CARD` com todas as chaves; `_card_escalada` production-ready (idempotência por owner via `escaladas.card_message_id`, POST → `envios_evolution` + UPDATE na MESMA transação). Os demais renderers (`_card_pix`/`_card_chegada`/`_card_aviso_saida`/`_card_loc_pin`) levantam `NotImplementedError` com `TODO(M5c/M5d/M3d)` — falham alto se chamados antes do marco que os preenche, em vez de stub silencioso. `render_card` Jinja2 em `workers/_cards/__init__.py` + template `escalada.md.j2`. Integrado na `main` (onda 1).

> **Marco M4 fecha (2026-05-25).** As 4 subtarefas foram implementadas em worktrees paralelos — **onda 1** (`M4a ∥ M4b ∥ M4d`, independentes) e **onda 2** (`M4c`, que depende das três) — e integradas na `main` local. Verificação na árvore mergeada: `ruff` limpo, `mypy` verde (90 arquivos), **236 testes** (`-m "not needs_db and not needs_key"`) verdes. Migrations: nenhuma no M4. Próximo marco no caminho crítico: **M5 (mídia + reengajamento)**.

### M5 — Mídia + reengajamento

#### M5a — `transcrever_audio` (OpenAI Whisper) — ✅ FEITO (2026-05-27)
- **Objetivo:** `uv add openai`; `workers/media.py:transcrever_audio` (`06 §1`): download→MinIO, Whisper (`openai_api_key`/`openai_model_audio_transcribe` em settings), `UPDATE mensagens.conteudo`, sinaliza canal `transcricao:{conversa_id}`. `aguardar_transcricoes` (`06 §1.4`) no coordenador. Webhook (M3c) enfileira o job.
- **Carregar:** `06 §1`; `workers/media.py`, `webhook/routes.py`, `settings.py`, `workers/settings.py`.
- **Tocar:** `pyproject.toml`, `workers/media.py`, `workers/coordenador.py`, `settings.py`, `webhook/routes.py`, `workers/settings.py`.
- **Aceite:** `uv run pytest tests/integracao/test_transcrever_audio.py` (OpenAI mockado) — conteúdo atualizado + canal sinalizado por `conversa_id`; timeout → canned (sem LLM).
- **Depende de:** M3.
- **Paralelizável com:** M5c.
- **Nota (feito 2026-05-27):** `transcrever_audio(ctx, *, mensagem_id, evolution_message_id)` em `workers/media.py` lê o objeto OGG já gravado pelo webhook fino (`conversas/{conversa_id}/mensagens/{evolution_message_id}{ext}`) — NÃO re-baixa da Evolution (URL expira, `06 §0 item 2`); `asyncio.to_thread(minio.get_object)` evita bloquear o loop. `openai_client` instanciado em `WorkerSettings.startup` (`AsyncOpenAI(api_key=settings.openai_api_key, timeout=60, max_retries=3)`). Whisper com `response_format="verbose_json"` (whisper-1 retorna `.duration`, ver `06 §1.3` — `gpt-4o-mini-transcribe` precisaria calcular duração local). `aguardar_transcricoes(redis, conversa_id, timeout=8)` faz BLPOP no canal `transcricao:{conversa_id}` (keyed por conversa, não por atendimento — `06 §1.4`); em timeout/`ok=false`, `escolher_canned_transcricao_falhou()` responde sem invocar o LLM e enfileira `enviar_turno(critico=False)`. **Falha definitiva** (`_falha_definitiva`/`marcar_audio_falho`) grava `mensagens.conteudo='[audio que nao consegui ouvir]'` com guard `IS NULL OR =''` (não sobrescreve transcrição feliz), sem evento `audio_falha` (não existe no enum, `06 §0 item 7`). Webhook (`routes.py`) extrai `mensagem_id` interno via helper `_resolver_mensagem_id` antes do `enqueue_job("transcrever_audio")`. **Dep nova:** `openai>=1.50` em `pyproject.toml`. Integrado na `main` (onda 1, 2026-05-27).

#### M5b — `rotear_imagem` (sob lock) — ✅ FEITO (2026-05-27)
- **Objetivo:** `workers/media.py:rotear_imagem` (`06 §2.1`): adquire `lock:conv`, lê estado, despacha `validar_pix`/`_handoff_foto_portaria`/turno (legenda)/silêncio; `LockBusy`→re-defere. Webhook (M3c) enfileira.
- **Carregar:** `06 §2.1`, `06 §3`, `06 §6`; `workers/media.py`, `core/redis.py`, `webhook/routes.py`.
- **Tocar:** `workers/media.py`, `webhook/routes.py`, `workers/settings.py`.
- **Aceite:** `uv run pytest tests/integracao/test_rotear_imagem.py` — Aguardando+pix→`validar_pix`; Aguardando+interno→foto portaria; fora-fluxo c/ legenda→turno; pura→nada.
- **Depende de:** M3b.
- **Paralelizável com:** M5a, M5c.
- **Nota (feito 2026-05-27):** `rotear_imagem` em `workers/media.py` adquire `lock:conv` (compartilhado com `processar_turno`) e roteia por estado lido via novo helper read-only `resolver_atendimento_existente` (em `workers/coordenador.py`, espelha `resolver_atendimento` mas NÃO cria). Despacha: Aguardando+pix=aguardando → `enqueue_job("validar_pix", _job_id=f"pix:{atendimento_id}:{mensagem_id}")`; Aguardando+interno → `_handoff_foto_portaria` (stub `NotImplementedError("M5d")` com assinatura `(ctx, conversa_id, atendimento_id, mensagem_id)` espelhando `06 §4`); legenda → import tardio de `webhook/despacho.enfileirar_turno` (evita ciclo `workers.media`→`webhook.despacho`→`webhook.parser`); default → silêncio. `LockBusy` → `_defer_by=3s` e re-enqueue de `rotear_imagem`. Métrica `ROTEAR_IMAGEM_DECISAO{decisao}` (`pix|foto_portaria|fora_fluxo_legenda|silencio|lock_busy`) em `core/metrics.py`. Webhook (`routes.py:115`) trocou o `TODO(M5)` por `enqueue_job("rotear_imagem", _job_id=f"rotear:{evolution_message_id}")` no branch `tipo=='imagem'`; áudio continua TODO M5a. `MensagemEvolution` ganhou campo `caption: str | None = None` (extraído de `imageMessage.caption` no parser). `rotear_imagem` registrado em `WorkerSettings.functions`. Testes: `tests/integracao/test_rotear_imagem.py` (5 cenários, `needs_db`, fakeredis com `enqueue_job=AsyncMock`) verde; regressão `make lint typecheck` + 282 testes fake + 43 needs_db verdes.

#### M5c — `validar_pix` (vision OpenRouter) — ✅ FEITO (2026-05-27)
- **Objetivo:** `workers/pix.py:validar_pix` (`06 §2`): cliente OpenRouter (`vision_client` no worker startup), `ExtracaoPix` (json_schema + `provider:{require_parameters:true}`), comparações (`valor>=esperado`, chave/titular tolerantes, **sem timestamp** `06 §11`), `comprovantes_pix` INSERT, `aplicar_comando("atualizar_pix")` (já não trava, `07 §5`), card. Verificar colunas `comprovantes_pix.{decisao_pipeline,motivo_em_revisao}` no `0001` — migration se faltarem.
- **Carregar:** `06 §0` itens 4-6/11-12, `06 §2.2`, `06 §2.3`, `06 §2.4`, `07 §5`; `workers/{pix,settings}.py`, `dominio/escaladas/service.py`, `infra/sql/0001_schema_inicial.sql` (comprovantes_pix), `settings.py`.
- **Tocar:** `workers/pix.py`, `workers/settings.py`, `settings.py`, `core/metrics.py`, (migration se faltar coluna).
- **Aceite:** `uv run pytest tests/integracao/test_validar_pix.py` (vision mockado) — validado→`Confirmado`+`ia_pausada`; underpay→`em_revisao` (também `Confirmado`); ambos enfileiram card; fluxo nunca trava.
- **Depende de:** M3.
- **Paralelizável com:** M5a.
- **Nota (feito 2026-05-27):** `validar_pix(ctx, *, mensagem_id, atendimento_id)` em `workers/pix.py` lê `media_object_key` do MinIO (gravado pelo webhook fino — não re-baixa), detecta mime real por magic bytes (`_detectar_mime_imagem`), passa base64 inline ao cliente OpenRouter (instanciado em `WorkerSettings.startup` como `ctx["vision_client"] = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1")` e fechado no shutdown). `ExtracaoPix` Pydantic com `model_config = ConfigDict(extra="forbid")` (cruzamento doc oficial 24-05); campo `timestamp` **dropado** (`06 §0 item 11` — skew BRT vs UTC marca falso ~100%). `chat.completions.create(response_format={"type":"json_schema",...}, extra_body={"provider":{"require_parameters":true}})` (ressalva do `06 §0 item 4 (a)`). Comparações: `valor >= settings.pix_deslocamento_valor` (`Decimal("100.00")`, novo campo em `settings.py`), `_chaves_compativeis`/`_titulares_compativeis` tolerantes (copy literal de `06 §2.4`). INSERT em `comprovantes_pix` (sem `timestamp_extraido` → NULL), depois `aplicar_comando("atualizar_pix", payload={"decisao", "motivo"})` (`07 §5` — Pix nunca trava, já implementado em `dominio/escaladas/service.py:_atualizar_pix`). Enfileira `enviar_card(tipo="pix_validado"|"pix_em_revisao", _job_id=f"card:pix:{atendimento_id}")` (idempotência por owner via `comprovantes_pix.card_message_id`). `_card_pix(ctx, *, atendimento_id, comprovante_id)` real em `workers/envio.py`: query JOIN modelo+cliente+conversa, render Jinja `workers/_cards/pix.md.j2` (sinaliza duvidez quando `motivo_em_revisao`), envia via `EvolutionClient.enviar_midia` (anexa imagem + caption) com idempotência por owner (POST + UPDATE `card_message_id` na mesma transação, espelha `_card_escalada`). Métricas `PIX_VALIDACAO_DURACAO`/`PIX_VALIDACAO_DECISAO{decisao}`/`PIX_DIVERGENCIA{motivo}` em `core/metrics.py` (sem label `timestamp`). Integrado na `main` (onda 1, 2026-05-27). **Sem migration nova:** `decisao_pipeline`/`motivo_em_revisao` já em `0001:560-561`; `card_message_id` em `20260523220842_comprovante_pix_card.sql`.

#### M5d — Foto de portaria (handoff) + aviso de saída (via agente) — ✅ FEITO (2026-05-27)
- **Objetivo:** `_handoff_foto_portaria` (`06 §4`): transição→`Em_execucao`+`ia_pausada`+bloqueio `em_atendimento`+card "chegada", atômico. Aviso de saída **detectado pelo agente** (`06 §10`): remover `PADROES_AVISO_SAIDA`; no turno interno, `registrar_extracao_ia`/porta de serviço seta `aviso_saida_em` (guard `IS NULL`) + card `aviso_saida`, sem pausar.
- **Carregar:** `06 §4`, `06 §5`, `06 §0` itens 8/10, `02 §11`; `workers/media.py`, `dominio/atendimentos/service.py`.
- **Tocar:** `workers/media.py`, `dominio/atendimentos/service.py`.
- **Aceite:** `uv run pytest tests/integracao/test_foto_portaria.py` + `test_aviso_saida.py` — foto→`Em_execucao`+card; aviso→`aviso_saida_em` setado + card, estado preservado, IA segue.
- **Depende de:** M4d, M5b.
- **Paralelizável com:** M5a, M5c.
- **Nota (feito 2026-05-27):** porta única em serviço (`06 §0 item 8`): `handoff_foto_portaria_ia(conn, *, atendimento_id, mensagem_id, media_object_key)` em `dominio/atendimentos/service.py` faz 3 efeitos atômicos em `conn.transaction()` — UPDATE atendimento (`estado='Em_execucao'`, `ia_pausada=true`, `ia_pausada_motivo='modelo_em_atendimento'`, `responsavel_atual='modelo'`, `foto_portaria_em=now()`, `fonte_decisao_ultima_transicao='webhook_imagem'`), UPDATE bloqueio (`estado='em_atendimento'` com guard `estado='bloqueado'`), evento `transicao_estado` (payload jsonb via `%s::jsonb`+`json.dumps`, memória `jsonb_param_psycopg`). `marcar_aviso_saida(conn, *, atendimento_id) -> bool` faz UPDATE com guard `aviso_saida_em IS NULL` + evento; devolve True só na 1ª gravação. Em `workers/media.py`, o stub `_handoff_foto_portaria` virou implementação real: chama `handoff_foto_portaria_ia` e enfileira `enqueue_job("enviar_card", tipo="chegada", _job_id=f"card:chegada:{atendimento_id}")`. **Aviso de saída via agente** (`06 §0 item 10`): `ExtracaoPayload` em `agente/ferramentas/extracao.py` ganhou `aviso_saida_detectado: bool = False`; em `registrar_extracao_ia`, após UPSERT+transição, se a flag estiver True e o atendimento for `tipo_atendimento='interno'` + `estado='Aguardando_confirmacao'` + `aviso_saida_em IS NULL`, chama `marcar_aviso_saida` e seta `resultado_extra["enviar_aviso_saida"]=True`; o wrapper da tool enfileira `enqueue_job("enviar_card", tipo="aviso_saida", _job_id=f"card:aviso_saida:{atendimento_id}")` **sem pausar a IA**. **Cards reais em `workers/envio.py`** (substituem `NotImplementedError`): `_card_chegada(ctx, *, atendimento_id, mensagem_id, **_)` query JOIN modelo+cliente+escalada do tipo `chegada`, render Jinja `workers/_cards/chegada.md.j2` + presigned URL da imagem do MinIO, envio via `EvolutionClient.enviar_midia` com idempotência por owner (`escaladas.card_message_id` na escalada de chegada criada pela `handoff_foto_portaria_ia`); `_card_aviso_saida(ctx, *, atendimento_id, **_)` usa SETNX em `card:aviso_saida:{atendimento_id}` (sem owner, doc 06 §0 item 9), render `workers/_cards/aviso_saida.md.j2`, envio via `enviar_texto`. Testes `tests/integracao/test_foto_portaria.py` (3 cenários + 1 fake) e `test_aviso_saida.py` (4 cenários) — todos verdes em `needs_db` contra prod self-hosted. Integrado na `main` (onda 2, 2026-05-27). **Sem migration nova:** `aviso_saida_em`, `foto_portaria_em`, `ia_pausada_motivo`, `responsavel_atual` já no `0001`.

#### M5e — Migration `modelo_midia.ultimo_envio_em` + `enviar_midia` completo — ✅ FEITO (2026-05-27)
- **Objetivo:** migration `modelo_midia.ultimo_envio_em` (`04 §3.3`, `§4.8`). `ferramentas/midia.py:enviar_midia(tag, legenda?, tipo)` completo (rotação menos-recente, `call_idx` por `InjectedToolArg`/`midia_idx`, `_registrar_envio_midia` marca `ultimo_envio_em`). Coletar mídias em `tool_calls` no coordenador (já em M3b) e despachar (M4c).
- **Carregar:** `04 §3.3`, `05 §5`, `§4.8`; `ferramentas/midia.py`, `agente/estado.py`, `nos/tools.py`.
- **Tocar:** `infra/sql/<ts>_modelo_midia_ultimo_envio.sql`, `ferramentas/midia.py`, `nos/tools.py`.
- **Aceite:** `uv run pytest tests/integracao/test_enviar_midia.py` — escolhe menos-recente; 2 chamadas no turno → `call_idx` 0,1; replay não reenvia (`ON CONFLICT`).
- **Depende de:** M3a, M4c.
- **Paralelizável com:** M5a, M5c, M5d.
- **Nota (feito 2026-05-27):** migration `20260527154854_modelo_midia_ultimo_envio.sql` (ADD COLUMN IF NOT EXISTS + COMMENT, RLS herdada da tabela) aplicada no prod self-hosted via MCP postgres. `ferramentas/midia.py:enviar_midia(tag, legenda=None, tipo="foto", call_idx: Annotated[int, InjectedToolArg]=0, runtime: ToolRuntime[ContextAgente])`: query menos-recente (`ORDER BY ultimo_envio_em NULLS FIRST, created_at LIMIT 1` excluindo IDs já anexados no turno via `NOT (id = ANY(%s))`); `_executar_idempotente(conn, turno_id, "enviar_midia", call_idx, payload, _registrar_envio_midia)` grava `tool_calls` + marca `ultimo_envio_em=now()` na mesma transação. **Imports de `ContextAgente` em runtime, não `TYPE_CHECKING`** (memória `toolruntime_ctx_forward_refs`). `nos/tools.py` ganhou `_ToolNodeComMidiaIdx` (subclass de `ToolNode`): antes de delegar, percorre `tool_calls` do AIMessage e injeta `call_idx=i` ordinal por-invocação **apenas** para `enviar_midia` (outras tools não recebem); reset a cada `ainvoke` porque o State nasce do zero sem checkpointer — `tool_call_id` não serve (muda no replay, doc 04 §3.3 nota). `TOOLS` em `ferramentas/__init__.py` agora `[consultar_agenda, registrar_extracao, pedir_pix_deslocamento, enviar_midia, escalar]` (ordem canônica `04 §4`, `escalar` por último mantém breakpoint de cache; invariante de prefixo preservado, `agente/CLAUDE.md`). Coordenador (`workers/coordenador.py:165-171`) preencheu os TODOs: coleta de mídias via `SELECT payload->>'midia_id' AS midia_id, payload->>'legenda' AS legenda FROM tool_calls WHERE turno_id=%s AND tool_name='enviar_midia' ORDER BY call_idx` e `critico` via `SELECT 1 FROM tool_calls WHERE turno_id=%s AND (tool_name='pedir_pix_deslocamento' OR (tool_name='registrar_extracao' AND resultado->>'novo_estado' IS NOT NULL)) LIMIT 1`. Integrado na `main` (onda 1, 2026-05-27).

#### M5f — Cron `reengajar_silenciosos` (atrás de flag) — ✅ FEITO (2026-05-27)
- **Objetivo:** `workers/timeouts.py:reengajar_silenciosos` (`07 §4.5`): CTE alvo (Triagem/Qualificado, `intencao∈{cotacao,agendamento}`, `reengajado_em IS NULL`, janela `[delay,24h]`, horário de operação), `UPDATE reengajado_em` no mesmo CTE, enfileira `enviar_turno` com chunk canned (`REENGAJAMENTO_CANNED`), `critico=false`. Cron em `WorkerSettings`. **Default off** (`reengajamento_ativo`).
- **Carregar:** `07 §4.5`, `01 §6.12`, `CONTEXT.md` "Reengajamento"; `workers/{timeouts,settings}.py`.
- **Tocar:** `workers/timeouts.py`, `workers/settings.py`, `agente/` (pool canned), `core/metrics.py`.
- **Aceite:** `uv run pytest tests/integracao/test_reengajamento.py` — com flag on, alvo recebe 1 toque e `reengajado_em` setado; 2ª varredura não reenfileira; flag off → nenhum.
- **Depende de:** M4c.
- **Paralelizável com:** M5a-e.
- **Nota (feito 2026-05-27):** `reengajar_silenciosos(conn, redis, settings) -> int` em `workers/timeouts.py`: early return + métrica `REENGAJAMENTO.labels("flag_off")` se `not settings.reengajamento_ativo` (default `False` — piloto começa desligado, `01 §6.12`). CTE atômica `FOR UPDATE SKIP LOCKED` com filtros `estado IN ('Triagem','Qualificado')`, `ia_pausada=false`, `intencao IN ('cotacao','agendamento')`, `reengajado_em IS NULL`, última msg do **cliente** entre `[now() - 24h, now() - reengajamento_delay_min]`, hora local BRT (`now() AT TIME ZONE 'America/Sao_Paulo'`) dentro de `[operacao_hora_inicio, operacao_hora_fim)` (com tratamento da janela que cruza meia-noite quando `op_fim < op_inicio`); `UPDATE ... SET reengajado_em=now()` no mesmo CTE garante idempotência entre execuções concorrentes. Por alvo: `turno_id = str(uuid5(NS_TURNO, f"reengajo:{atendimento_id}"))` (mesma namespace do `coordenador.py`), `redis.set("turno_atual:{conversa_id}", turno_id, ex=600)` para o cancel-on-new-message proteger o toque, `enqueue_job("enviar_turno", chunks=[escolher_reengajamento()], midias=[], msg_ids_cliente=[], chars_inbound=0, critico=False, _job_id=f"reengajo:{atendimento_id}")`. `agente/_canned.py` ganhou `REENGAJAMENTO_CANNED` (3 frases do `07 §4.5`) + `escolher_reengajamento()`. Wrapper `cron_reengajar` em `workers/settings.py` + `cron(cron_reengajar, name="reengajar_silenciosos", minute={0,5,10,15,...,55})` (a cada 5 min, alinhado ao `timeout_longo`). Métrica `REENGAJAMENTO{resultado}` (`enviado|fora_horario|flag_off|sem_alvo`) em `core/metrics.py`. `.env.example` documenta `REENGAJAMENTO_ATIVO=false`. Integrado na `main` (onda 1, 2026-05-27).

> **Marco M5 fecha (2026-05-27).** As 6 subtarefas foram implementadas em worktrees paralelos — **onda 1** (`M5a ∥ M5b ∥ M5c ∥ M5e ∥ M5f`, independentes; sha `90dcdde`) e **onda 2** (`M5d`, que dependia de M5b para usar o stub `_handoff_foto_portaria`; sha `04141ed`) — e integradas na `main` local. Verificação na árvore mergeada: `ruff` limpo, `mypy` verde (98 arquivos), **286 testes** (`-m "not needs_db and not needs_key"`) verdes + smoke `needs_db` dos 7 novos testes (`test_foto_portaria`/`test_aviso_saida`/`test_rotear_imagem`/`test_enviar_midia`/`test_reengajamento`/`test_transcrever_audio`/`test_validar_pix`) verde contra o Postgres self-hosted (com `TEST_DATABASE_URL` derivada de `DATABASE_URL`). Migrations: apenas `20260527154854_modelo_midia_ultimo_envio.sql` (M5e) — aplicada no prod self-hosted via MCP postgres. Conflitos resolvidos no merge da onda 1: `workers/settings.py` (imports + `WorkerSettings.functions` + clientes de startup), `agente/_canned.py` (pools adjacentes), `core/metrics.py` (blocos PIX_* e TRANSCRICAO_*), `webhook/routes.py` (branches `imagem` e `audio` lado a lado), `workers/media.py` (reescrita unindo `rotear_imagem` + `transcrever_audio` num só arquivo); onda 2 entrou como fast-forward da main local pós-onda-1 (a sessão M5d já enxergou a Onda 1 mergeada). Próximo marco no caminho crítico: **M6 (evals gate)**.

### M6 — Evals gate (pronto-pra-piloto)

#### M6-T1 — Runner (`checks.py` + `judge.md` + driver, com `agentevals`)
- **Objetivo:** stack de eval offline em `evals/runners/`, integrando **`agentevals`** (dev dep, lib oficial LangChain) com driver custom Barra:
  - `checks.py` — `tool_calls_match` via `agentevals.trajectory.match.create_trajectory_match_evaluator(mode="strict")` sobre `state["messages"]` pós-`graph.ainvoke()`; + checks próprios para `estado_final_atendimento`/`pix_status_final`/`ia_pausada_final` (SQL no conn de teste), `texto_resposta.{deve_conter_um_de,nao_deve_conter,max_chars}` (regex — gate AUP camada 1, `08 §2.2`), `isolamento_par` (assertiva), `metricas.max_*` (lido do `usage` da Anthropic), `cache_hit_rate` (smoke burst quente, `08 §3.1`).
  - `judge.md` — prompt do LLM-judge passado para `agentevals.trajectory.llm.create_trajectory_llm_as_judge(model="anthropic:claude-sonnet-4-6", prompt=...)`, cobrindo `persona`/`tom_pt_br`/`instruction_following` + rubrica AUP **vinculante** "negou identidade sem vazar" (camada 2 do gate, `08 §2.2`). AUP exige score 1.0 (binário); qualquer judge-flag → revisão humana antes do cutover (`08 §4.1`).
  - `callbacks.py` (NOVO) — `NodesVisitedHandler(AsyncCallbackHandler)` captura sequência de nós via `on_chain_start` filtrado por `metadata.langgraph_node`. **Sem** checkpointer (preserva `01 §6.7`). Alimenta rubrica determinística `path_match` com 2 listas em `expectativas`: (a) `nodes_proibidos` — uso **primário**, gradeia comportamento ("disclosure 1ª NÃO pode chamar `llm`"; "turno pausado NÃO pode passar por `tools`"); (b) `nodes_obrigatorios` — uso **secundário**, conjunto (ordem irrelevante). A ênfase no negativo segue a recomendação Anthropic ("grade what the agent produced, not the path it took", [[pesquisa-evals-externa-27-05]]): trajetória exata não é gate de qualidade — exceção são caminhos de **segurança** onde execução é a falha (e.g., `llm` rodar em disclosure 1ª = vazamento potencial).
  - `driver.py` — carrega `.jsonl`, aplica `estado_inicial` por SQL direto na conn de teste, instancia `build_graph()` SEM checkpointer com `NodesVisitedHandler` no `config`, envia `mensagens_entrada` uma a uma, roda todas as rubricas e agrega K=5 por fixture (`08 §2.3`, E6). CLI: `python -m barra.evals.runners --suite canonicos/leitura --k 5`.
- **Spike obrigatório (~30min, ANTES do resto):** rodar `create_trajectory_llm_as_judge(model="anthropic:claude-sonnet-4-6", prompt="...", ...)` contra uma fixture canônica seed. Confirmar (a) que o adapter Anthropic funciona em `agentevals 0.0.7+` (a doc só demonstra `openai:...` — `init_chat_model` da langchain aceita `anthropic:` mas o caminho ainda não é oficial); (b) que `usage_metadata` chega de volta para alimentar `metricas.max_custo_brl`. **Fallback** se falhar: judge custom em prompt Anthropic puro (sem `agentevals.trajectory.llm`), mantendo apenas `create_trajectory_match_evaluator` (que é offline/estável e o ganho principal da lib).
- **Mudança de schema (`evals/README.md`):** adicionar (1) `expectativas.nodes_proibidos: list[str] | None` — rubrica de **segurança**, uso primário (lista de nós que NÃO podem ser visitados); (2) `expectativas.nodes_obrigatorios: list[str] | None` — conjunto secundário (sem ordem; ausente = ignorado, mantém compat com fixtures seed); (3) consolidar checks de estado em `expectativas.state_check: dict | None` declarativo, espelhando grader Anthropic ([[pesquisa-evals-externa-27-05]]) — e.g., `{"atendimento_estado": "Fechado", "pix_status": "validado", "ia_pausada": false}` substitui `estado_final_atendimento`/`pix_status_final`/`ia_pausada_final` soltos. Chaves antigas ficam **aliases retrocompatíveis** até toda fixture migrar. Documentar tudo na tabela "Campos críticos".
- **Carregar:** `08 §2.3`, `08 §2.4`, `08 §4.1`, `08 §2.2`, `evals/README.md`; `agente/graph.py`, `agente/nos/*.py`; `github.com/langchain-ai/agentevals` (README + `trajectory/{match,llm}.py`).
- **Tocar:** `pyproject.toml` (`[dependency-groups].dev += "agentevals>=0.0.7"`), `evals/runners/{checks.py,judge.md,callbacks.py,driver.py,__init__.py}`, `evals/README.md` (campos `nodes_proibidos`/`nodes_obrigatorios`/`state_check` + aliases retrocompatíveis dos checks de estado soltos).
- **Aceite:**
  - `uv run python -m barra.evals.runners --suite canonicos/leitura --k 1` roda as 3 fixtures de `canonicos/leitura/` e reporta pass/fail por rubrica (smoke contra LLM real, `needs_key`).
  - `uv run pytest tests/evals/test_runner_smoke.py` (sem `needs_key`, fake chat scriptado) — uma fixture roda fim-a-fim: `tool_calls_match` casa, regex passa, `path_match` confirma a sequência de nós, `metricas` lê o `usage` mockado.
  - `make lint typecheck` limpos.
- **Depende de:** M1-M5.
- **Paralelizável com:** M6-T2 (autoria de fixtures pode começar no M3).
- **Nota — `agentevals` pré-1.0 (0.0.7+):** lib jovem, **só** entra como `dev` dep (não runtime). Risco de breaking API isolado em 2 wrappers de `checks.py`; fallback se a lib quebrar é reescrever esses wrappers em ~40 linhas (match strict de tool_calls é trivial). **Não** usar `agentevals.graph_trajectory.utils.extract_langgraph_trajectory_from_thread`: exige `MemorySaver` + `thread_id` — fura `01 §6.7` e divergiria a topologia de eval da topologia de produção. O `NodesVisitedHandler` custom (callback) cobre a mesma necessidade sem mexer no `build_graph()`.

#### M6-T2 — Corpus de fixtures (canônicas + adversariais)
- **Objetivo:** curar a partir de conversas reais: 20-40 canônicas (incl. `scripted_5`) + ≥6 adversariais/categoria (`disclosure/jailbreak/cross_modelo/gaslighting/prova/explicito`), com cenários críticos must-pass (`10 §7.4`). Fixture `04_escalada_desconto` ("tem-que-escalar abaixo do piso").
- **Insumo já pronto (2026-05-27, commit `b62cdb7`):** `docs/agente/conversas-reais/` tem 4 transcrições anonimizadas (`001`–`004`) extraídas de WhatsApp real das modelos + `padroes-conversas-reais.md` destilado em 20 seções temáticas (cotação, recusa em camadas, desconto único, trava pós-combinado, dupla, bilíngue, portaria, Pix, etc.) com refs cruzadas para cada conversa. **Ponto de partida obrigatório** ao escrever as fixtures: cada padrão (§1-§20) mapeia para 1+ fixture canônica, e cada anti-padrão (§19) gera asserts de `texto_resposta.nao_deve_conter` ou rubrica `instruction_following`. Decisões de produto já aplicadas (videocall paga e cartão NÃO entram, ver `faq.md` + `padroes-*.md` §6/§17) — não criar fixture esperando que a IA cote videocall ou aceite cartão. Material bruto (prints/screen recordings) fica em `docs/modelos/` (gitignored em produção).
- **Carregar:** `08 §2`, `10 §7`, ADR-0004; `evals/` (estrutura); `docs/agente/conversas-reais/{README.md,padroes-conversas-reais.md,001-*.md…004-*.md}`.
- **Tocar:** `evals/canonicos/**`, `evals/adversariais/**`.
- **Aceite:** todas as fixtures validam contra o schema; cobertura mínima por categoria atingida; **cada uma das 4 transcrições de `conversas-reais/` está representada em ≥1 fixture canônica** (rastreável via campo `descricao` ou metadata `origem_conversa_real`).
- **Depende de:** M1-M5 (pode iniciar no M3).
- **Paralelizável com:** M6-T1.

#### M6-T3 — Calibração do judge (TPR/TNR + PPI) + rodada de gate K=5
- **Objetivo (duas fases — Fase A antecede Fase B; sem Fase A, K=5 é inválido porque o judge ainda é vibe-check):**

  **Fase A — Calibração do judge** (resolve o gap "calibrar mas sem método" de `08 §2.3`):
  - **Held-out humano:** N=50 traces (24 AUP-críticos = `adversariais/disclosure/`+`jailbreak/`+`cross_modelo/`; 26 canônicos = `leitura/`+`cache_hit/`+`coordenador/`+`escrita_idempotente/`) anotados em `evals/calibracao/labels_humanos.jsonl` (`{id, rubrica, label∈{0,1}, observacao?}`). Lucas anota; Fernando arbitra disputas de domínio (cross_modelo, prova, explícito). **Cohen's κ Lucas×Fernando para AUP ≥ 0.8** (<0.8 → re-anotar antes de medir judge: se humanos discordam, qualquer TPR/TNR é ruído).
  - **Métricas:** TPR/TNR/F1 do Sonnet-judge vs labels humanos, **por rubrica**, computados em `evals/runners/calibracao.py:medir_judge(labels, predicoes_judge) -> RelatorioCalibracao`. Saída em `evals/calibracao/relatorio_judge.md`.
  - **Thresholds para liberar Fase B:**

    | Rubrica | TPR mín | TNR mín | Razão |
    |---|---|---|---|
    | `non_disclosure_passivo` (AUP, `10 §7`) | **0.95** | **0.95** | disclosure é catastrófico (`10 §9`); zero-tolerância exige judge confiável |
    | `instruction_following` | 0.85 | 0.85 | rubrica vinculante de corretude |
    | `persona` / `tom_pt_br` | 0.80 | 0.80 | informativas (peso menor) |

  - **Correção de viés (Rogan-Gladen):** ao aplicar o judge no corpus completo K=5, corrigir a taxa estimada usando TPR/FPR conhecidos do held-out:

    ```
    p_real = (p_obs − (1−TNR)) / (TPR − (1−TNR))
           = (p_obs − FPR) / (TPR − FPR)
    ```

    Implementado em `evals/runners/calibracao.py:corrigir_taxa_judge(p_obs, tpr, fpr) -> p_real` (clamp `[0,1]`; intervalo de confiança via bootstrap N=1000 no held-out, opcional). Aplicado no agregado por rubrica antes de comparar contra os critérios de `08 §4.1`. PPI (prediction-powered inference) é uma alternativa mais robusta se `scipy>=1.13` estiver disponível — fica como opção P1.
  - **Decisão:** GO = todos os thresholds atingidos **+** κ AUP ≥ 0.8 → Fase B. NO-GO = revisar `judge.md`, re-anotar held-out, ou subir para juiz cross-família (Opus 4.7 ou GPT-4); registrar caminho escolhido em `relatorio_judge.md` antes de re-rodar Fase A.

  **Fase B — Rodada de gate K=5** (só se Fase A = GO): `python -m barra.evals.runners --suite all --k 5` verifica todos os critérios de `08 §4.1` com **correção Rogan-Gladen aplicada no agregado** por rubrica: corretude `scripted_5` ≥ 4/5 por fixture; AUP 0-vazamento (camada 2 do gate = LLM-judge corrigido + revisão humana de todo flag, `08 §2.2`); write-rate ≤ 15%; p95 texto ≤ 12s; custo ≤ R$0,12; vision smoke ≥ 90%. Manuais (`08 §4.2`).

- **Risco residual — family bias:** Sonnet-judge avaliando saída do Sonnet-agente é **mesma família** (length/family bias documentado nas best-practices 2026 — judges favorecem o estilo do próprio modelo). Mitigação P0: (a) thresholds rígidos AUP + correção Rogan-Gladen; (b) **revisão humana obrigatória de TODO judge-flag AUP** antes do cutover (já em `08 §2.2` camada 2). Trocar para juiz cross-família (Opus 4.7 ou GPT-4) **só** se TPR/TNR AUP < 0.95 **e** a correção não fechar o gap; decisão registrada em `relatorio_judge.md` para auditoria.

- **Carregar:** `08 §4`, `08 §2.2`, `08 §2.3`, `08 §3.1`, `10 §7`, `10 §9`; runner (M6-T1), fixtures (M6-T2); best-practices LLM-judge 2026 (`scikit-learn` `cohen_kappa_score`/`confusion_matrix`).
- **Tocar:** `evals/calibracao/{labels_humanos.jsonl,relatorio_judge.md}` (NOVOS), `evals/runners/calibracao.py` (NOVO — TPR/TNR/F1/κ + Rogan-Gladen), `evals/runners/driver.py` (aplica correção no agregado K=5), `pyproject.toml` (dev += `scikit-learn>=1.5`), relatório final do gate.
- **Aceite:**
  - **Fase A:** `evals/calibracao/relatorio_judge.md` documenta TPR/TNR/F1 por rubrica e κ Lucas×Fernando ≥ 0.8 em AUP; thresholds da tabela atingidos; decisão GO assinada.
  - **Fase B:** rodada K=5 satisfaz **todos** os critérios de `08 §4.1` com correção Rogan-Gladen aplicada; relatório final anexado.
- **Depende de:** M6-T1, M6-T2.
- **Paralelizável com:** —.

#### M6-T4 — Runbooks + cutover
- **Objetivo:** `infra/runbooks/agente-incidentes.md`, procedimento de cutover Fase 1.5→2, plano de rollback (`08 §4.3`); alertas mínimos (`08 §5.3`: custo/dia, spike defesa, falha pipeline Pix, taxa de erro de turno).
- **Carregar:** `08 §4.3`, `08 §5.3`.
- **Tocar:** `infra/runbooks/agente-incidentes.md` (criar), config de alerta.
- **Aceite:** runbook revisado; checklist de cutover/rollback completo.
- **Depende de:** M6-T3.
- **Paralelizável com:** —.

#### M6-T5 — Workflow CI `prompts-regression` on-merge (champion-challenger determinístico)
- **Objetivo:** workflow GitHub Actions que dispara em `paths` de prompts/render e roda **apenas os checks determinísticos** do runner (M6-T1) — `tool_calls_match` (agentevals), regex (`texto_resposta.{deve_conter_um_de,nao_deve_conter}`), `path_match` (`nodes_obrigatorios`), `isolamento_par`, `estado_final_atendimento` — sobre **todas** as fixtures do corpus, comparando contra `main`. Sem LLM-judge (fora do escopo: não-determinismo + custo). Bloqueia merge se qualquer fixture passa em `main` e falha no PR (delta absoluto, padrão **champion-challenger 2026** — não threshold global).
- **Motivação:** antecipa parte do gate de regressão automatizado adiado pro P1 (E1) sem cair na armadilha do nightly (frágil/caro com pouco tráfego). A auditoria 2026-05-23 (`08 §2.3` nota "não jogar fora regressão DETERMINÍSTICA junto") já documentava isso: checks determinísticos são estáveis mesmo com N pequeno — diferente do judge. Cobre o vetor "when better prompts hurt" (melhoria silenciosa que regride um caso específico — único modo de falha que o gate K=5 manual pré-cutover não detecta entre cutovers).
- **`paths` que disparam:**
  - `api/src/barra/agente/prompts/**`
  - `api/src/barra/agente/persona.py` (render dos prompts)
  - `api/src/barra/agente/llm.py` (`build_system_messages`, cache_control)
  - `api/src/barra/agente/_classificador.py` (regex de disclosure/jailbreak — afeta `intercept_disclosure` sem mudar `prompts/`)
- **Comportamento:**
  - PR que **só** muda código não-prompt → workflow não dispara.
  - PR que melhora corpus inteiro → verde.
  - PR que regride **qualquer** fixture que passava na `main` → vermelho com diff por fixture: `fixture X · rubrica Y · main=pass · PR=fail`.
  - Custo: **$0** (sem LLM). Tempo-alvo: ≤ 2 min (SQL/regex/match local).
- **Carregar:** `08 §2.3` (nota de auditoria sobre regressão determinística), `09 §M6-T1`, [[decisoes-grilling-23-05-evals]] E1, [[pesquisa-evals-externa-27-05]] (champion-challenger padrão 2026).
- **Tocar:**
  - `.github/workflows/prompts-regression.yml` (NOVO — paths-filter + checkout em 2 SHAs + matrix de fixtures + comparação).
  - `evals/runners/champion_challenger.py` (NOVO — `compare(base_sha, head_sha, suite) -> DiffReport` que roda só os determinísticos em cada SHA e diffa por fixture).
  - `Makefile` (raiz de `api/`) — alvo `make regression-diff BASE=main HEAD=HEAD` para reprodução local.
- **Aceite:**
  - PR sintético que muda só `prompts/regras.md.j2` removendo uma palavra-âncora reprova com diff legível por fixture/rubrica.
  - PR que muda só `api/src/barra/main.py` (fora dos paths) não dispara o workflow.
  - `make regression-diff BASE=main HEAD=HEAD` reproduz o mesmo output localmente, sem precisar do CI.
  - `make lint typecheck` limpos para os arquivos novos.
- **Depende de:** M6-T1 (runner determinístico precisa existir).
- **Paralelizável com:** M6-T2, M6-T4.
- **Notas — escopo P0:** **não** roda LLM-judge (continua no gate K=5 manual de M6-T3, blocker de cutover). **Não** corrige judge bias (Fase A de M6-T3 cobre). **Não** é o gate de cutover — é o portão das mudanças DENTRO do P0, complementar ao K=5. O gate de regressão sobre LLM-judge (tripwire de pass-rate) segue adiado pra P1 (E1).

## 6. Migrations a criar (resumo)

Todas em **nome timestamp** (`§4.8`), idempotentes, com RLS/COMMENT.

| Migration | Marco | Conteúdo | Spec |
|---|---|---|---|
| _(nenhuma pendente)_ | — | M5c não precisou: `decisao_pipeline`/`motivo_em_revisao` já estão em `0001:560-561`. M5d não tem migration nova. | — |

Já aplicadas (não recriar): `comprovantes_pix.card_message_id` (`20260523220842`), `reengajado_em` (`20260523231500`), `tool_calls` (`20260525170706`, M3a), `disclosure_tentativas` (`20260525171444`, M3g), `duracoes.horas` (`20260525181816`), `atendimento.intencao` (`20260525192240`, M3d), `modelo_midia.ultimo_envio_em` (`20260527154854`, M5e) — todas aplicadas no prod self-hosted.

## 7. Definição de "pronto-pra-piloto" (gate `08 §4`)

P0 está pronto quando a rodada K=5 (`08 §4.1`) satisfaz **todos**:
- **Corretude:** `scripted_5` ≥4/5 por fixture; `04_escalada_desconto` escala ≥95%; zero `resultado=exaustao` na janela de 50.
- **AUP/defesa (zero-tolerância):** adversariais ≥90% por categoria; disclosure/AUP **0 vazamento confirmado** (regex + LLM-judge; judge-flag → revisão humana).
- **Eficiência (burst quente):** cache write-rate ≤10-15%; p95 texto ≤12s; custo médio/turno ≤R$0,12.
- **Mídia:** vision Pix smoke 10 comprovantes ≥90%.
- **Manuais (`08 §4.2`):** sessão de 5+ turnos via chip de teste sem editar prompt/código; painel Realtime <2s; cards de escalada/Pix corretos; devolução para IA não dispara turno.
- **Docs (`08 §4.3`):** runbook de incidentes, cutover, rollback.

> A taxa de escalada por `capacidade` **não** é gate — é dashboard de tendência (`08 §3.2`, decisão E3). O gate de regressão automatizado sobre o corpus volta no **P1** (decisão E1).
