# 01 — Arquitetura do Agente

> Decisões arquiteturais, mapa de módulos, divergências com `docs/mvp/` e fluxo end-to-end de uma mensagem.

## 1. Visão de 30 segundos

```
WhatsApp ─▶ Evolution ─▶ Webhook (FastAPI)
                          │
                          ├─ persiste mensagem bruta (mensagens, atendimento_id=NULL)
                          ├─ resolve modelo via msg.instance_id
                          ├─ se mídia áudio → enfileira `transcrever_audio`
                          ├─ se mídia imagem em Aguardando_confirmacao externo → enfileira `validar_pix`
                          └─ enfileira `processar_turno` no ARQ (debounce key = conversa_id)

ARQ worker `processar_turno`:
  1. aguarda janela de debounce (~3-5s) para coalescer mensagens picotadas
  2. adquire lock Redis SETNX `lock:conv:{conversa_id}` (TTL 60s + heartbeat)
  3. resolve/cria atendimento (regra determinística do mvp/03 §5.2)
  4. UPDATE mensagens.atendimento_id em mensagens órfãs da conversa
  5. se há áudio em transcrição pendente → BLPOP do canal Redis (timeout 8s)
  6. se ia_pausada=true → libera lock e encerra (sem turno)
  7. monta system prompt em 4 breakpoints + carrega últimas 20 mensagens
  8. invoca agente: graph.ainvoke({"messages": [...]}, config={"thread_id": conversa_id, "configurable": {...}})
  9. detecta encerramento por escalada (ia_pausada=true após invoke) → descarta texto
  10. enfileira jobs `enviar_chunk` (humanização) com texto + lista de mídias
  11. libera lock; drena pending list

ARQ worker `enviar_chunk`:
  1. consulta dedupe key `dedup:envio:{conversa_id}:{turno_id}:{chunk_idx}` (SET NX)
  2. presence composing por delay proporcional ao tamanho
  3. envia ao Evolution; recebe evolution_message_id
  4. INSERT em mensagens (direcao='ia', evolution_message_id real)
  5. pausa de jitter; próximo chunk
```

## 2. Decisões arquiteturais

### 2.1 StateGraph custom em vez de `create_react_agent`

LangGraph oferece dois caminhos:

- **`langgraph.prebuilt.create_react_agent(...)`** — loop ReAct pronto: nó `agent` chama LLM com tools; nó `tools` executa tools; condicional roteia até LLM emitir AIMessage sem tool_calls.
- **StateGraph custom** — desenhar nós explicitamente.

**Decisão:** **StateGraph custom**. Justificativa:

- `create_react_agent` foi marcado como **legacy/deprecado em LangGraph v1.0** (mai/2025), substituído por `langchain.agents.create_agent` com middleware. O fórum LangChain registra perda de feature concreta na migração (reescrita de histórico de mensagens em função do estado, exatamente o que precisamos para injetar SystemMessages dinâmicas e contexto fresco a cada turno).
- O domínio Barra Vips tem **vários gates determinísticos** que cabem mal num loop ReAct opaco: gate de pausa (`ia_pausada=true` antes do LLM), refetch pós-tool, descarte de texto após `escalar`, decisão de cards no grupo, sliding window por turno. StateGraph permite enxerto natural de nós antes/depois do LLM.
- Observabilidade: cada nó é um span dedicado no LangSmith; com `create_react_agent` o loop fica opaco.
- Não há custo significativo: temos 8 tools no P0, mas o "loop" é tão simples (`prepare → llm → tools → llm → post_process`) que escrever 5 nós explícitos é mais claro que o prebuilt.

Estrutura canônica do grafo (detalhada em `02 §1` e `03 §7`):

```
START
  └─▶ prepare_context  (carrega persona/agenda/cliente, monta SystemMessages)
        └─▶ gate_pausa  (se ia_pausada → END sem invocar LLM)
              └─▶ llm   (ChatAnthropic com cache_control + adaptive thinking)
                    ├─▶ tools (executa tool_calls; loop volta para llm)
                    └─▶ post_process  (refetch atendimento; descarta texto se escalada)
                          └─▶ END
```

A máquina de estados de domínio (`Novo→Triagem→...→Fechado`) **NÃO** é refletida em nós do LangGraph. Cada estado é coluna em `atendimentos.estado`; transições são disparadas pelo coordenador a partir de tools de escrita ou eventos externos (Pix pipeline, foto de portaria, timeouts).

### 2.2 thread_id = `conversa_id`

`conversa_id` é UUID único por par `(cliente_id, modelo_id)` — alinha com isolamento por par definido em `mvp/04 §4.1`. Atendimentos sucessivos da mesma conversa compartilham checkpoint LangGraph; cliente recorrente percebe continuidade.

**Não rotacionamos checkpoint** ao fechar atendimento — o histórico de mensagens da IA fica acumulado na thread, e a sliding window de 20 mensagens (`02 §4`) já limita o que entra no prompt em runtime. O checkpoint serve principalmente para resumir/auditar; o conteúdo do prompt é montado pelo coordenador.

### 2.3 State minimalista (`MessagesState`)

```python
from langgraph.graph import MessagesState

class EstadoAgente(MessagesState):
    """Apenas messages com reducer add_messages. Tudo mais é contexto fresco do coordenador."""
    pass
```

Nada de `atendimento_id`, `cliente_id`, `modelo_id` no State. Esses dados:
- são **injetados como `SystemMessage` dinâmica** a cada turno pelo coordenador (`02 §5`);
- ficam **acessíveis às tools via `RunnableConfig.configurable`** quando precisarem consultar DB com escopo correto.

**Justificativa:** evita duplicar verdade entre Postgres e checkpoint LangGraph. Postgres é fonte de verdade (`mvp/03 §7.4`). Checkpoint só guarda histórico de mensagens; metadados ficam fora.

### 2.4 Coordenador como ARQ job

Webhook responde 200 imediatamente após persistir mensagem e enfileirar `processar_turno`. O turno em si — debounce, lock, montagem de prompt, invocação do grafo, dispatch — roda em worker ARQ separado.

**Justificativa:**
- Evolution tem timeout de webhook (~15s); turnos com 5+ tool calls excedem.
- Permite cancelamento granular: ao chegar nova mensagem do cliente em conversa cuja IA ainda está enviando chunks, ARQ cancela jobs pendentes (`05 §3`).
- Desacopla webhook (latência baixa, idempotência simples) de turno (latência alta, idempotência por `turno_id`).

### 2.5 Anthropic SDK direto (sem OpenRouter)

Todo o chat (e o vision do Pix) vai direto para a Anthropic API via `anthropic` Python SDK. **Não há OpenRouter no caminho.**

Justificativa:
- **Cache funciona como anunciado**: `cache_control` per-block com TTL `5m`/`1h` é nativo da Anthropic; via OpenRouter tem caveats relevantes (a doc oficial OpenRouter restringe `cache_control` automático ao roteamento direto à Anthropic, e issues abertas reportam comportamento "estático" mesmo nesse caso). Provider único elimina essa incerteza.
- **Tool calling premium**: Sonnet 4.6 ~80%+ Toolathlon vs ~50% Kimi K2.6 — diferença material para os turnos com `consultar_*` + `registrar_extracao` + `escalar` no mesmo turno.
- **PT-BR de qualidade premium**: Anthropic investe em multilingual; Moonshot foca CN/EN. Para um produto onde "uma palavra errada perde o cliente premium" é regra de domínio (`CONTEXT.md`), tom é a variável mais cara.
- **Sem adapter custom**: usamos `langchain_anthropic.ChatAnthropic` (mantido pelo LangChain), que já entende `additional_kwargs={"cache_control": ...}` e adaptive thinking. Adeus subclasse de `BaseChatModel`.
- **SDK de Pydantic-first**: `client.messages.parse(output_format=Schema)` valida a saída automaticamente — usado em `registrar_extracao` e no Pix vision.

Cliente Anthropic vive em `core/llm.py` como wrapper fino sobre `anthropic.AsyncAnthropic`. `langchain-anthropic` é dependência opcional usada só pelo grafo.

**Transcrição é exceção.** Anthropic não faz speech-to-text. Para áudio do cliente usamos OpenAI Whisper API direto (`whisper-1`), isolado em `workers/media.py`. Esse é o único provider externo do MVP — escolha consciente para não bloquear no espera de feature.

### 2.6 Sonnet 4.6 como modelo principal, Haiku 4.5 como fallback

| Aspecto | `claude-sonnet-4-6` | `claude-haiku-4-5` (fallback) |
|---------|---------------------|--------------------------------|
| Input | $3.00 / M | $1.00 / M |
| Output | $15.00 / M | $5.00 / M |
| Cache read | ~$0.30 / M (~0.1×) | ~$0.10 / M |
| Cache write 1h | $6.00 / M (2×) | $2.00 / M |
| Context | 1M | 200K |
| Max output | 64K (streaming) | 64K (streaming) |
| Tool calling | top-tier | sólido |
| PT-BR premium | sim | sim (degradação tolerável) |

**Estimativa de custo P0** (1 modelo piloto, ~800 turnos/dia, ~6k tokens input médio, hit rate cache ≥70%):
- Sonnet 4.6: ~$13/dia ≈ **R$ 2 mil/mês** (sem cache hits seria ~$28).
- Haiku 4.5 (se for fallback frequente): ~$5/dia ≈ R$ 750/mês.

**Política de fallback** (detalhes em `03 §6.3`):
- `anthropic.RateLimitError` (429) → retry com backoff (3 tentativas, exponential 2^n + jitter).
- `anthropic.APIStatusError(status >= 500)` após retry → fallback para Haiku 4.5 **com reset do turno** (não reaproveitar tool_calls da resposta Sonnet anterior — formato é compatível, mas misturar mid-turn corrompe contexto).
- Circuit breaker: ≥3 fallbacks consecutivos em 5min → alerta Sentry, próxima invocação pula direto para Haiku.
- **Não há fallback cross-provider.** Se ambos falharem, `escalar_por_exaustao` abre handoff para Fernando.

Detalhes de seleção em `03 §6`.

## 3. Mapa de módulos do agente

```
api/src/barra/
├── agente/                            ← módulo 5.3 da mvp/03
│   ├── __init__.py
│   ├── graph.py                       ← build_graph() retornando StateGraph compilado (5 nós)
│   ├── estado.py                      ← EstadoAgente (alias MessagesState) + tipos auxiliares
│   ├── nos/                           ← NOVO: nós do StateGraph
│   │   ├── prepare_context.py         ← carrega persona/agenda/cliente, monta SystemMessages
│   │   ├── gate_pausa.py              ← curto-circuita se ia_pausada=true
│   │   ├── llm.py                     ← invoca ChatAnthropic; trata fallback Sonnet → Haiku
│   │   ├── tools.py                   ← executa tool_calls; loop volta para llm
│   │   └── post_process.py            ← refetch atendimento; descarta texto se escalada
│   ├── prompts/
│   │   ├── persona.md.j2              ← Jinja2; vars do dataclass Persona
│   │   ├── regras.md.j2               ← Jinja2; vars: tipo_atendimento_aceito, valor_padrao
│   │   ├── faq.md.j2                  ← Jinja2; for faq in faqs ...
│   │   ├── programas.md.j2            ← Jinja2; tabela de programas e valores
│   │   └── contexto_dinamico.md.j2    ← turno-a-turno: atendimento, cliente, agenda, pix_status
│   ├── persona.py                     ← dataclass Persona + render_*() helpers
│   ├── llm.py                         ← build_messages(state) + cache_control kwargs + factory ChatAnthropic
│   ├── classificador.py               ← (P1) classificador de saída interna/externa
│   └── ferramentas/
│       ├── __init__.py                ← export TOOLS = [consultar_*, registrar_extracao, ...]
│       ├── _idempotencia.py           ← helper _executar_idempotente
│       ├── leitura.py                 ← consultar_agenda, consultar_cliente, consultar_faq, consultar_pix_status, consultar_midia
│       ├── extracao.py                ← registrar_extracao (delega a dominio.atendimentos.service.registrar_extracao_ia)
│       ├── pix.py                     ← pedir_pix_deslocamento
│       ├── midia.py                   ← enviar_midia
│       └── escalada.py                ← escalar
├── webhook/
│   ├── routes.py                      ← já existe; adicionar despacho para `processar_turno`
│   ├── debounce.py                    ← marca conversa_id como "aguardando" no Redis com TTL = janela
│   ├── despacho.py                    ← enfileira processar_turno; idempotência via dedupe key
│   └── classificador.py               ← NOVO: detecta disclosure/jailbreak/explicito por regex; anota no config para elevar effort
├── workers/
│   ├── settings.py                    ← ARQ settings (redis pool, queues)
│   ├── coordenador.py                 ← `processar_turno` job (NOVO; ainda não existe)
│   ├── envio.py                       ← já existe; humanização chunk-by-chunk
│   ├── media.py                       ← transcrever_audio (OpenAI Whisper API direto — NOVO)
│   ├── pix.py                         ← validar_pix (Anthropic vision via messages.parse — NOVO)
│   ├── timeouts.py                    ← cron 5min para auto_timeout / auto_timeout_interno
│   └── retencao.py                    ← cron diário para apagar checkpoints LangGraph >90 dias (NOVO)
└── core/
    ├── llm.py                         ← AsyncAnthropic client + factory ChatAnthropic (sonnet + haiku)
    ├── redis.py                       ← já existe; lock + dedupe helpers
    └── ...
```

Pasta `dominio/` permanece como estava — agente **chama** services, não o inverso.

## 4. Fluxo end-to-end de uma mensagem texto do cliente

Detalha o fluxo da §1 com paths e queries.

### 4.1 Webhook (`webhook/routes.py`)

Já implementado. Responsabilidades atuais ficam; adicionar:

- após `_persistir_cliente` retornar com sucesso, chamar `webhook.despacho.enfileirar_turno(redis, conversa_id, evolution_message_id)`.
- se `tipo == "audio"`, primeiro enfileira `transcrever_audio(mensagem_id)` e só depois `processar_turno` (com flag `aguardar_transcricao=True` no payload).

### 4.2 Despacho (`webhook/despacho.py`)

```python
async def enfileirar_turno(
    redis: Redis,
    conversa_id: UUID,
    evolution_message_id: str,
    aguardar_transcricao: bool = False,
) -> None:
    """Marca debounce e enfileira processar_turno respeitando coalescência."""
    # 1. registra última mensagem na janela de debounce
    chave = f"debounce:conv:{conversa_id}"
    await redis.set(chave, evolution_message_id, ex=10)  # TTL > janela de debounce

    # 2. enfileira job único por conversa (substitui se já houver pendente)
    job_id = f"turno:{conversa_id}"
    await arq_pool.enqueue_job(
        "processar_turno",
        conversa_id=str(conversa_id),
        aguardar_transcricao=aguardar_transcricao,
        _job_id=job_id,
        _defer_by=timedelta(seconds=4),  # janela de debounce
    )
```

### 4.3 Coordenador (`workers/coordenador.py`)

```python
async def processar_turno(
    ctx: dict,
    *,
    conversa_id: str,
    aguardar_transcricao: bool = False,
) -> None:
    redis: Redis = ctx["redis"]
    pool: AsyncConnectionPool = ctx["db_pool"]
    graph = ctx["graph"]
    turno_id = uuid7()

    async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat=15) as lock:
        async with pool.connection() as conn:
            # 1. resolve atendimento e atualiza órfãs
            atendimento = await resolver_atendimento(conn, UUID(conversa_id))
            await atualizar_orfaos(conn, UUID(conversa_id), atendimento["id"])

            # 2. se ia_pausada, encerra
            if atendimento["ia_pausada"]:
                logger.info("ia_pausada, sem turno", conversa_id=conversa_id)
                return

            # 3. aguarda transcrição se necessário
            if aguardar_transcricao:
                ok = await aguardar_transcricoes(redis, atendimento["id"], timeout=8)
                if not ok:
                    logger.warning("transcricao_timeout", atendimento_id=atendimento["id"])
                    # segue mesmo assim com placeholder

            # 4. monta contexto e invoca grafo
            persona = await carregar_persona(conn, atendimento["modelo_id"])
            mensagens = await carregar_mensagens(conn, UUID(conversa_id), limite=20)
            system_messages = build_system_messages(persona, atendimento, mensagens)

            entrada = {"messages": system_messages + [HumanMessage(content=ultima_msg(mensagens))]}
            config = {
                "configurable": {
                    "thread_id": conversa_id,
                    "atendimento_id": str(atendimento["id"]),
                    "modelo_id": str(atendimento["modelo_id"]),
                    "cliente_id": str(atendimento["cliente_id"]),
                    "turno_id": str(turno_id),
                    "db_pool": pool,
                    "redis": redis,
                }
            }

            try:
                resultado = await graph.ainvoke(entrada, config=config)
            except RecursionError:
                # exaustão de iterações — escala silenciosamente
                await escalar_por_exaustao(conn, atendimento["id"], turno_id)
                return

            # 5. checa se foi escalada (ia_pausada agora true) → descarta texto
            atendimento_pos = await refetch_atendimento(conn, atendimento["id"])
            if atendimento_pos["ia_pausada"]:
                logger.info("turno_escalado", atendimento_id=atendimento["id"])
                return

            # 6. extrai resposta + mídias do State final e despacha humanização
            resposta = extrair_resposta(resultado["messages"])
            await despachar_humanizacao(redis, conversa_id, turno_id, resposta)
```

### 4.4 Pós-turno (humanização)

Implementada em `workers/envio.py`. Detalhes em `05-humanizacao.md`.

## 5. Direção das dependências

```
webhook/   ─▶ workers/coordenador
workers/coordenador ─▶ agente/graph
                    ─▶ dominio/atendimentos/repo (ler estado)
                    ─▶ dominio/conversas/repo
                    ─▶ dominio/modelos/repo
                    ─▶ dominio/programas/repo
agente/ferramentas/ ─▶ dominio/*/service ou repo (consultas e escritas atômicas)
agente/ferramentas/escalada ─▶ dominio/escaladas/service.abrir_handoff (já existe)
```

`agente/` **nunca** importa de `webhook/` ou `workers/`. Inversão dessa direção é violação arquitetural.

## 6. Divergências conscientes com `docs/mvp/`

Itens onde a spec técnica do agente substitui ou refina a especificação de produto.

### 6.1 Pix recusado mantém IA pausada

`mvp/04 §3.2` diz: "Pix recusado por Fernando → atendimento volta a Aguardando_confirmacao com `ia_pausada=false`."

**Override:** `atualizar_pix(invalido)` mantém `ia_pausada=true` (motivo `pix_em_revisao` permanece). IA só volta ativa quando Fernando devolve manualmente pelo painel ou via comando `IA assume #N` no grupo.

**Justificativa (decisão QA 2026-05-02):** após recusa, a próxima ação não é da IA — é Fernando decidindo se pede 2º Pix, descarta o atendimento ou orienta a modelo. IA voltar ativa significa que próxima mensagem do cliente dispara turno onde a IA pode tentar pedir Pix de novo, contradizendo orientação operacional. Mantê-la pausada força decisão humana explícita.

**Implementação:** alterar `dominio/escaladas/service.py:_atualizar_pix` quando `decisao=="invalido"` para preservar `ia_pausada=true`. Ver `04 §3.5` e `07 §5`.

### 6.2 `mvp/04 §3` valor único R$100 vs schema com `programas`

`mvp/02 §3.2` diz "valor único de R$ 100 no MVP" para Pix de deslocamento e implícito que a oferta da modelo é "R$ 1.000/h fixo".

**Realidade do schema:** `barravips.programas` (1h, 2h, 3h, pernoite, jantar, viagem, programa social) e `modelo_programas (modelo_id, programa_id, preco)` formam catálogo de precificação por modelo.

**Resolução:**
- **Pix de deslocamento permanece R$ 100 fixo** — esse valor não tem nada a ver com programas; é taxa de saída separada. Tool `pedir_pix_deslocamento()` sem args.
- **Precificação do atendimento usa `modelo_programas`** — IA apresenta tabela ao cliente conforme programas ativos da modelo. Tabela renderizada no system prompt; ver `03 §3.3`.

### 6.3 Coordenador via ARQ (não inline)

`mvp/03 §5.2` descreve coordenador genericamente "no processo do backend". Esta spec materializa como **ARQ job separado** do webhook. Justificativa em `01 §2.4`.

### 6.4 `escalar` é tool que grava direto

`mvp/03 §5.3` descreve `escalar` como "única porta de handoff" sem prescrever implementação.

**Implementação:** tool grava direto via `dominio.escaladas.service.abrir_handoff`. Coordenador detecta `ia_pausada=true` após invoke e descarta qualquer texto que viesse depois. Detalhes em `04 §3.5`.

### 6.5 Sliding window 20 mensagens

`mvp/03 §5.3` diz "histórico recente" sem quantificar.

**Materialização:** sliding window fixa de **20 mensagens** (clientes + IA + modelo_manual misturadas), ordenadas por `created_at desc`, depois revertidas para ordem cronológica antes de enviar ao LLM. Detalhes em `02 §4`.

### 6.6 Anthropic SDK direto + StateGraph custom

`mvp/07 §3` cita "Anthropic SDK 0.42 com prompt caching" como stack mas não prescreve provider. `docs/agente` 1.0 colocou OpenRouter + Kimi K2.6 como solução; **esta revisão (1.1) reverte para Anthropic SDK direto + Sonnet 4.6 + fallback Haiku 4.5**.

**Justificativa (revisão pós-QA 2026-05-02):**
- Cache `cache_control` 4 breakpoints é nativo da Anthropic — sem caveats; via OpenRouter tinha comportamento incerto (`OpenRouterTeam/ai-sdk-provider#35`, `sst/opencode#1245`).
- `create_react_agent` foi deprecado em LangGraph v1.0 — adoção viraria dívida técnica de saída. Migramos para StateGraph custom, que casa melhor com gates determinísticos do domínio (`§2.1`).
- Custo absoluto P0: ~R$ 2 mil/mês com Sonnet 4.6 + cache 70% — desprezível vs. ticket médio premium da operação. Diferença para Kimi via OpenRouter é da ordem de R$ 200/mês — não compensa risco em PT-BR e tom premium.

**Implicação para o código existente em `core/llm.py`:** descartar wrapper `OpenRouterClient` e substituir por `core/llm.py:criar_anthropic_client(settings) -> AsyncAnthropic` + `core/llm.py:criar_chat_anthropic(settings, modelo) -> ChatAnthropic`. Nada de subclasse de `BaseChatModel`.

### 6.7 Retenção de checkpoint LangGraph

`mvp/03 §7.4` define Postgres como fonte de verdade mas não prescreve TTL para tabelas de checkpoint LangGraph (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`).

**Decisão:** cron noturno em `workers/retencao.py` que apaga checkpoints sem atividade há **>90 dias por thread** (`thread_id = conversa_id`). `mensagens` permanece como histórico oficial.

**Justificativa:** sem retenção, `checkpoint_blobs` cresce indefinidamente — em 6 meses em produção com cliente premium recorrente, vira problema operacional (Lord Patil reportou esse padrão em jun/2025). Como o coordenador monta o prompt do zero a cada turno (sliding window 20 + contexto fresco), o checkpoint serve para auditoria e resume-from-error — 90 dias é folga para análise post-mortem sem inflar DB.

**Implementação:** ARQ cron diário (03:00 BRT) com SQL idempotente:

```sql
WITH threads_inativas AS (
  SELECT thread_id
    FROM checkpoints
   GROUP BY thread_id
  HAVING max(created_at) < now() - interval '90 days'
)
DELETE FROM checkpoint_blobs WHERE thread_id IN (SELECT thread_id FROM threads_inativas);
DELETE FROM checkpoint_writes WHERE thread_id IN (SELECT thread_id FROM threads_inativas);
DELETE FROM checkpoints WHERE thread_id IN (SELECT thread_id FROM threads_inativas);
```

Métrica `agente_checkpoint_purgado_total{tipo}` exportada para alertar se volume diário diverge muito do esperado (sinal de bug).

### 6.8 Non-disclosure passivo (override `CONTEXT.md` "nunca admite ser IA")

`CONTEXT.md` (linha de domínio) e `mvp/01-contexto-negocio.md` afirmam que a IA "não admite ser IA em hipótese alguma".

**Override (revisão 1.2 pós-pesquisa):** adotar **non-disclosure passivo** — Bia não nega ativamente ser IA, mas também não confessa proativamente. Em pergunta direta, deflecte 1-2 vezes em personagem (com frases ambíguas, não juramento ativo); em insistência, escala via `escalar(motivo="disclosure_insistente")`.

**Justificativa:**
1. **Anthropic Acceptable Use Policy** ([anthropic.com/legal/aup](https://www.anthropic.com/legal/aup)) proíbe "*impersonate a human...intended to convince a natural person they are communicating with a natural person when they are not*" e exige "*all consumer-facing chatbots must disclose to users that they are interacting with AI rather than a human*". Mentira ativa = violação literal = risco de banimento de conta + risco jurídico.
2. **Sonnet 4.6 resiste a mentir** sobre identidade quando pressionado ([anthropic.com/news/...companionship](https://www.anthropic.com/news/how-people-use-claude-for-support-advice-and-companionship)). Forçar persona explícita produz: recusa visível quebrando tom, resposta evasiva azedando conversa, ou banimento eventual.

**Implementação:** detalhada em `10-persona-jailbreak.md`. Toca:
- `agente/prompts/persona.md.j2` (removida instrução "nunca admite ser IA").
- `agente/prompts/regras.md.j2` (`<protocolo_disclosure>` com deflecções few-shot + escalada).
- `webhook/classificador.py` (NOVO — detecção heurística de tentativas adversariais).
- `agente/ferramentas/escalada.py` (motivos AUP-família).
- Adversarial dataset em `api/evals/adversarial/` (gateia deploy com pass-rate ≥90%).

## 7. O que está fora da spec do agente

- **CRUD de modelos/FAQ/mídia** — pertence a `dominio/modelos/`, painel.
- **Painel Next.js** — fora completamente.
- **Schema do banco** — em `infra/sql/` (já estabilizado).
- **Comandos no grupo de Coordenação** (parser texto + `aplicar_comando`) — já implementado em `webhook/routes.py` + `dominio/escaladas/service.py`.
- **Pipeline de OCR/vision Pix** — está em `06-pipelines-midia.md`, mas o pipeline em si vive em `workers/pix.py`, fora do agente.
