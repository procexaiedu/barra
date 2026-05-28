# 01 — Arquitetura do Agente

> Decisões arquiteturais, mapa de módulos, divergências com `docs/mvp/` e fluxo end-to-end de uma mensagem.

## 1. Visão de 30 segundos

```
WhatsApp ─▶ Evolution ─▶ Webhook (FastAPI)
                          │
                          ├─ persiste mensagem bruta (mensagens, atendimento_id=NULL); só o coordenador cria atendimento
                          ├─ resolve modelo via msg.instance_id
                          ├─ se mídia áudio → enfileira `transcrever_audio` + `processar_turno`
                          ├─ se mídia imagem → enfileira `rotear_imagem` (decide validar_pix/portaria/fora-fluxo sob lock:conv — branch 14)
                          └─ se texto → enfileira `processar_turno` no ARQ (debounce key = conversa_id)

ARQ worker `processar_turno`:
  1. aguarda janela de debounce (~3-5s) para coalescer mensagens picotadas
  2. adquire lock Redis SETNX `lock:conv:{conversa_id}` (TTL 60s + heartbeat)
  3. resolve/cria atendimento (regra determinística do mvp/03 §5.2)
  4. UPDATE mensagens.atendimento_id em mensagens órfãs da conversa
  5. se há áudio em transcrição pendente → BLPOP do canal Redis (timeout 8s)
  6. se ia_pausada=true ou estado terminal (Fechado/Perdido) → encerra (sem turno)
  7. (montagem do prompt migrou para o nó prepare_context, dentro do grafo)
  8. invoca agente: graph.ainvoke({"messages": []}, config={"configurable": {"thread_id": conversa_id}}, context=ContextAgente(...))  # prepare_context monta 3 breakpoints (P0; BP4 adiado P1) + 20 msgs
  9. detecta encerramento por escalada (ia_pausada=true após invoke) → descarta texto
  10. enfileira UM job `enviar_turno` (humanização) com chunks + mídias + msgs do cliente (read receipt) + critico
  11. drena pending list: se chegou msg durante o turno, re-roda 3-10 sob o MESMO lock; senão libera lock

ARQ worker `enviar_turno` (um por turno; percorre chunks → mídias em ordem):
  0. read receipt: marca msgs do cliente como lidas + reading delay (~len do inbound) — lê antes de digitar (05 §4.2)
  1. cancel-on-new-message: se não-crítico e `turno_atual:{conversa_id}` != turno_id → aborta
  2. dedupe por item via set `enviados:{turno_id}` (mark-after-send)
  3. presence composing ~0.8-2.0s; envia ao Evolution; recebe evolution_message_id
  4. INSERT em mensagens (direcao='ia') + registro em envios_evolution (via EvolutionClient)
  5. pausa de jitter; próximo item
```

## 2. Decisões arquiteturais

### 2.1 StateGraph custom em vez de `create_react_agent`

LangGraph oferece dois caminhos:

- **`langgraph.prebuilt.create_react_agent(...)`** — loop ReAct pronto: nó `agent` chama LLM com tools; nó `tools` executa tools; condicional roteia até LLM emitir AIMessage sem tool_calls.
- **StateGraph custom** — desenhar nós explicitamente.

**Decisão:** **StateGraph custom**. Justificativa:

- `create_react_agent` foi marcado como **legacy/deprecado em LangGraph v1.0** (GA out/2025), substituído por `langchain.agents.create_agent` com middleware. O **StateGraph custom não foi deprecado** — segue como o caminho de baixo nível suportado; só o prebuilt saiu. O fórum LangChain registra perda de feature concreta na migração (reescrita de histórico de mensagens em função do estado, exatamente o que precisamos para injetar SystemMessages dinâmicas e contexto fresco a cada turno).
- O domínio Elite Baby tem **vários gates determinísticos** que cabem mal num loop ReAct opaco: gate de pausa (`ia_pausada=true` antes do LLM), refetch pós-tool, descarte de texto após `escalar`, decisão de cards no grupo, sliding window por turno. StateGraph permite enxerto natural de nós antes/depois do LLM.
- Observabilidade: cada nó é um span dedicado no LangSmith; com `create_react_agent` o loop fica opaco.
- Não há custo significativo: temos 5 tools no P0, mas o "loop" é tão simples (`prepare → llm → tools → llm → post_process`) que escrever 5 nós explícitos é mais claro que o prebuilt.

Estrutura canônica do grafo (detalhada em `02 §1` e `03 §7`):

```
START
  └─▶ prepare_context  (lê ia_pausada 1º; se pausada → END. Senão monta TODO o contexto: persona/agenda/cliente + janela)
        └─▶ intercept_disclosure  (alta confiança → canned+post_process; 3ª insistência → escala+END; ambíguo/normal → llm)
              └─▶ llm   (ChatAnthropic com cache_control; thinking disabled + effort=low no P0 — só Sonnet, §2.6)
                    ├─▶ tools (executa tool_calls; loop volta para llm)
                    └─▶ post_process  (refetch atendimento; descarta texto se escalada)
                          └─▶ END
```

A máquina de estados de domínio (`Novo→Triagem→...→Fechado`) **NÃO** é refletida em nós do LangGraph. Cada estado é coluna em `atendimentos.estado`; transições são disparadas pelo coordenador a partir de tools de escrita ou eventos externos (Pix pipeline, foto de portaria, timeouts).

### 2.2 thread_id = `conversa_id`

`conversa_id` é UUID único por par `(cliente_id, modelo_id)` — alinha com isolamento por par definido em `mvp/04 §4.1`. É usado como `thread_id` no `RunnableConfig` (tag de trace LangSmith e chave de escopo das tools), mesmo **sem checkpointer no P0** (`§2.3`, `02 §3`).

**Sem persistência de estado entre turnos:** o nó `prepare_context` monta o prompt do zero a cada turno a partir da tabela `mensagens` (sliding window de 20, `02 §4`). O histórico vive no Postgres, não num checkpoint LangGraph; a continuidade para o cliente recorrente vem do Postgres, não do estado do grafo.

### 2.3 State minimalista (`MessagesState`)

```python
from langgraph.graph import MessagesState

class EstadoAgente(MessagesState):
    """Apenas messages com reducer add_messages. Tudo mais é contexto fresco do coordenador."""
    pass
```

Nada de `atendimento_id`, `cliente_id`, `modelo_id` no State. Esses dados:
- são **injetados como `SystemMessage` dinâmica** a cada turno pelo coordenador (`02 §5`);
- ficam **acessíveis aos nós e tools via Runtime Context API** (`runtime.context`) quando precisarem consultar DB com escopo correto.

**Justificativa:** Postgres é a única fonte de verdade (`mvp/03 §7.4`). O estado do grafo é efêmero por invocação (**sem checkpointer no P0**, `02 §3`) e carrega só as mensagens daquele turno; deps de runtime (pool, redis) e ids de escopo ficam no **`context`** (`graph.ainvoke(..., context=ContextAgente(...))`), não no estado.

> **Por que `context` e não `config['configurable']` (LangGraph 1.x):** no 1.x a **Runtime Context API** (`context_schema=ContextAgente` + `context=`) é a forma idiomática de passar dependências de runtime; `config['configurable']` é o padrão legado. Decisivo aqui: o checkpointer **serializa o `configurable`** — passar `db_pool`/`redis` (não-serializáveis) por ali quebra com `TypeError` (`langgraph#3441`) assim que o checkpointer for religado no P1 (`§6.7`). O `context` é run-scoped e **não** é serializado. Só o `thread_id` (= `conversa_id`) fica em `configurable`, que é nativo do checkpointer. Nós lêem `runtime: Runtime[ContextAgente]`; tools lêem `runtime: ToolRuntime[ContextAgente]` (`ContextAgente` definido em `agente/contexto.py`; detalhe em `04 §1.1`).

### 2.4 Coordenador como ARQ job

Webhook responde 200 imediatamente após persistir mensagem e enfileirar `processar_turno`. O turno em si — debounce, lock, montagem de prompt, invocação do grafo, dispatch — roda em worker ARQ separado.

**Justificativa:**
- Evolution tem timeout de webhook (~15s); turnos com 5+ tool calls excedem.
- Permite cancelamento granular: ao chegar nova mensagem do cliente em conversa cuja IA ainda está enviando chunks, ARQ cancela jobs pendentes (`05 §3`).
- Desacopla webhook (latência baixa, idempotência simples) de turno (latência alta, idempotência por `turno_id`).

### 2.5 Anthropic SDK direto para o chat (vision via OpenRouter, áudio via OpenAI)

O **chat** vai direto para a Anthropic API via `anthropic` Python SDK (default `llm_chat_provider="anthropic"`). O **vision do Pix** migrou para **OpenRouter** (cliente OpenAI-compatível, `06 §2.3`/`§0` item 4) e a **transcrição** usa OpenAI Whisper direto (`06 §1.3`) — ambos isolados nos workers, fora do chat.

Justificativa:
- **Cache funciona como anunciado**: `cache_control` per-block com TTL `5m`/`1h` é nativo da Anthropic; via OpenRouter tem caveats relevantes (a doc oficial OpenRouter restringe `cache_control` automático ao roteamento direto à Anthropic, e issues abertas reportam comportamento "estático" mesmo nesse caso). Provider único elimina essa incerteza.
- **Tool calling premium**: Sonnet 4.6 ~80%+ Toolathlon vs ~50% Kimi K2.6 — diferença material para os turnos com `consultar_*` + `registrar_extracao` + `escalar` no mesmo turno.
- **PT-BR de qualidade premium**: Anthropic investe em multilingual; Moonshot foca CN/EN. Para um produto onde "uma palavra errada perde o cliente premium" é regra de domínio (`CONTEXT.md`), tom é a variável mais cara.
- **Sem adapter custom**: usamos `langchain_anthropic.ChatAnthropic` **1.x** (mantido pelo LangChain), que entende `cache_control` em **content blocks** do `SystemMessage` (forma idiomática que adotamos; `additional_kwargs` do 0.3 **continua funcionando** no 1.x — não é migração obrigatória, ver `03 §5`) e o controle de `thinking`. Adeus subclasse de `BaseChatModel`.
- **SDK de Pydantic-first**: `client.messages.parse(output_format=Schema)` valida saída estruturada automaticamente — agora com **constrained decoding real** (Structured Outputs **GA, sem beta header**; o antigo `structured-outputs-2025-11-13` foi promovido a GA e o param migrou para `output_config.format`; garantia de schema mais forte que JSON prompt-based). (O Pix vision, antes por aqui, migrou para OpenRouter json_schema — `06 §2.3`; ver ressalva de robustez lá.)

Cliente Anthropic vive em `core/llm.py` como wrapper fino sobre `anthropic.AsyncAnthropic`. `langchain-anthropic` é dependência opcional usada só pelo grafo.

**Transcrição e vision são as exceções não-Anthropic.** Anthropic não faz speech-to-text: para áudio do cliente usamos OpenAI Whisper API direto (`whisper-1`), isolado em `workers/media.py`; o vision do Pix usa OpenRouter (`06 §2.3`). São os dois providers externos do MVP — escolhas conscientes para não bloquear em features.

### 2.6 Sonnet 4.6 como modelo único (sem fallback de modelo)

| Aspecto | `claude-sonnet-4-6` |
|---------|---------------------|
| Input | $3.00 / M |
| Output | $15.00 / M |
| Cache read | ~$0.30 / M (~0.1×) |
| Cache write 1h | $6.00 / M (2×) |
| Context | 1M |
| Max output | 64K (streaming) |
| Tool calling | top-tier |
| PT-BR premium | sim |

**Estimativa de custo P0** (1 modelo piloto, ~800 turnos/dia, ~6k tokens input médio, hit rate cache ≥70%):
- Sonnet 4.6: ~$13/dia ≈ **R$ 2 mil/mês** (sem cache hits seria ~$28).

**Política de indisponibilidade** (detalhes em `03 §6.3`): **não há modelo de fallback** — o chat roda só em Sonnet 4.6.
- `anthropic.RateLimitError` (429) → retry com backoff (3 tentativas, exponential 2^n + jitter).
- 429 esgotado, `anthropic.APIStatusError(status >= 500)` ou timeout → `escalar_por_exaustao` abre handoff para Fernando. Não trocamos de modelo: quando o Sonnet não responde, a conversa vai para um humano.

**Effort (Sonnet 4.6):** o chat roda com `thinking={"type":"disabled"}` **+ `output_config={"effort":"low"}`** — o default de effort é `high` (mais latência/custo) e tom/tamanho da resposta vêm da persona/few-shot, não do effort. (Effort é GA, sem beta header.) Detalhe em `03 §6`.

Detalhes de seleção em `03 §6`.

## 3. Mapa de módulos do agente

```
api/src/barra/
├── agente/                            ← módulo 5.3 da mvp/03
│   ├── __init__.py
│   ├── graph.py                       ← build_graph() retornando StateGraph compilado (5 nós)
│   ├── estado.py                      ← EstadoAgente (alias MessagesState) + tipos auxiliares
│   ├── nos/                           ← NOVO: nós do StateGraph
│   │   ├── prepare_context.py         ← dono do contexto: gate ia_pausada + persona/agenda/cliente + janela
│   │   ├── intercept_disclosure.py    ← canned/escala/llm p/ disclosure (10 §3.1, §8)
│   │   ├── llm.py                     ← invoca ChatAnthropic; retry no 429, exaustão → escala
│   │   ├── tools.py                   ← executa tool_calls; loop volta para llm
│   │   └── post_process.py            ← refetch atendimento; descarta texto se escalada
│   ├── prompts/
│   │   ├── persona.md.j2              ← Jinja2 GERAL (voz/conduta/disclosure; sem vars por-modelo)
│   │   ├── regras.md.j2               ← Jinja2 GERAL (conduta; tipos_aceitos saiu p/ identidade)
│   │   ├── faq.md                     ← arquivo versionado GERAL (modelo_faq foi dropada em 0030; ver 03 §3.2)
│   │   ├── identidade.md.j2           ← Jinja2 POR-MODELO: nome/idade/idiomas/localização + tipos_aceitos
│   │   ├── programas.md.j2            ← Jinja2 POR-MODELO: tabela de programas e valores
│   │   └── contexto_dinamico.md.j2    ← turno-a-turno: atendimento, cliente, agenda, pix_status
│   ├── persona.py                     ← dataclass IdentidadeModelo + render_persona()/render_identidade()
│   ├── llm.py                         ← build_messages(state) + cache_control kwargs + factory ChatAnthropic
│   ├── classificador.py               ← (P1) classificador de saída interna/externa
│   └── ferramentas/
│       ├── __init__.py                ← export TOOLS = [consultar_*, registrar_extracao, ...]
│       ├── _idempotencia.py           ← helper _executar_idempotente
│       ├── leitura.py                 ← consultar_agenda (única leitura; cliente/pix_status/faq viram contexto no prompt, consultar_midia colapsada em enviar_midia(tag) — 04 §1, decisão 2026-05-23)
│       ├── _classificador.py          ← NOVO: regex disclosure/jailbreak/prova sobre a janela (chamado pelo prepare_context)
│       ├── extracao.py                ← registrar_extracao (delega a dominio.atendimentos.service.registrar_extracao_ia)
│       ├── pix.py                     ← pedir_pix_deslocamento
│       ├── midia.py                   ← enviar_midia
│       └── escalada.py                ← escalar
├── webhook/
│   ├── routes.py                      ← já existe; adicionar despacho para `processar_turno`
│   ├── debounce.py                    ← marca conversa_id como "aguardando" no Redis com TTL = janela
│   ├── despacho.py                    ← enfileira processar_turno; idempotência via dedupe key
│   └── classificador.py               ← (opcional) regex só p/ métrica/log; a classificação que DIRIGE o intercept roda no grafo (agente/_classificador.py, decisão 2026-05-23)
├── workers/
│   ├── settings.py                    ← ARQ settings (redis pool, queues)
│   ├── coordenador.py                 ← `processar_turno` job (NOVO; ainda não existe)
│   ├── envio.py                       ← já existe; humanização chunk-by-chunk
│   ├── media.py                       ← transcrever_audio (OpenAI Whisper API direto — NOVO)
│   ├── pix.py                         ← validar_pix (vision via OpenRouter, json_schema — NOVO)
│   └── timeouts.py                    ← cron 5min para auto_timeout / auto_timeout_interno
└── core/
    ├── llm.py                         ← AsyncAnthropic client + factory ChatAnthropic (sonnet)
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
    """Marca debounce + pendência e enfileira processar_turno respeitando coalescência."""
    # 1. marca pendência — lida pelo drain loop do coordenador (§4.3 passo 7)
    await redis.set(f"pending:conv:{conversa_id}", evolution_message_id, ex=120)

    # 2. registra última mensagem na janela de debounce
    chave = f"debounce:conv:{conversa_id}"
    await redis.set(chave, evolution_message_id, ex=10)  # TTL > janela de debounce

    # 3. coalesce via _job_id estático: ARQ faz SET NX (o 1º vence; enqueues seguintes
    #    na janela são DESCARTADOS — não há "substituição"). O turno lê a sliding window
    #    inteira ao rodar, então quem chegou na janela já entra; quem chega COM o turno
    #    já rodando é recuperado pelo drain loop (§4.3), não por reenfileiramento.
    job_id = f"turno:{conversa_id}"
    await arq_pool.enqueue_job(
        "processar_turno",
        conversa_id=str(conversa_id),
        aguardar_transcricao=aguardar_transcricao,
        _job_id=job_id,
        _defer_by=timedelta(seconds=4),  # janela de debounce
    )
```

> **`processar_turno` precisa ser definido com `keep_result=0`** (na função/`WorkerSettings`, `07`). O `enqueue_job` deduplica pela *result key* além da *job key*: com o `keep_result` default de 3600s do ARQ, o re-enqueue do mesmo `_job_id` (drain loop, `07`) retornaria `None` silenciosamente por 1h após o turno terminar (`arq#416`/`#432`) — quebrando a coalescência. `keep_result=0` libera a chave assim que o job acaba.

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

    async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat=15) as lock:
        loop_idx = 0
        while True:  # drena pending list (passo 11): msgs chegadas durante o turno
            # turno_id DETERMINÍSTICO por (job, iteração): no retry do ARQ as dedupe keys
            # de envio/tool são reusadas → sem resposta duplicada (§6.7). Nunca uuid7() runtime.
            turno_id = uuid5(NS_TURNO, f"{ctx['job_id']}:{loop_idx}")
            await redis.delete(f"pending:conv:{conversa_id}")  # limpa ANTES de ler a janela

            async with pool.connection() as conn:
                # 1. resolve atendimento e atualiza órfãs
                atendimento = await resolver_atendimento(conn, UUID(conversa_id))
                await atualizar_orfaos(conn, UUID(conversa_id), atendimento["id"])

                # 2. se ia_pausada ou estado terminal, encerra
                if atendimento["ia_pausada"] or atendimento["estado"] in ESTADOS_TERMINAIS:
                    logger.info("sem turno", conversa_id=conversa_id, estado=atendimento["estado"])
                    return

                # 3. aguarda transcrição se necessário
                if aguardar_transcricao:
                    ok = await aguardar_transcricoes(redis, atendimento["id"], timeout=8)
                    if not ok:
                        logger.warning("transcricao_timeout", atendimento_id=atendimento["id"])
                        # segue mesmo assim com placeholder

                # 4. invoca grafo — prepare_context monta TODO o contexto dentro do grafo.
                #    thread_id em configurable (nativo do checkpointer); deps de runtime e
                #    ids de escopo no context (Runtime Context API, §2.3). NUNCA pool/redis
                #    em configurable: o checkpointer serializa o configurable (langgraph#3441).
                config = {"configurable": {"thread_id": conversa_id}}
                contexto = ContextAgente(
                    db_pool=pool,
                    redis=redis,
                    modelo_id=str(atendimento["modelo_id"]),
                    atendimento_id=str(atendimento["id"]),
                    cliente_id=str(atendimento["cliente_id"]),
                    turno_id=str(turno_id),
                )
                try:
                    resultado = await graph.ainvoke(
                        {"messages": []}, config=config, context=contexto
                    )
                except GraphRecursionError:  # de langgraph.errors; captura por classe (07 §3)
                    await escalar_por_exaustao(conn, atendimento["id"], turno_id)  # exaustão → escala
                    return

                # 5. escalada OU transição externa (cron/comando): ia_pausada OU estado
                #    terminal → descarta texto (compare-and-set, §6.10)
                atendimento_pos = await refetch_atendimento(conn, atendimento["id"])
                if atendimento_pos["ia_pausada"] or atendimento_pos["estado"] in ESTADOS_TERMINAIS:
                    logger.info("turno_descartado", atendimento_id=atendimento["id"])
                    return

                # 6. extrai resposta + mídias do State final e despacha humanização
                resposta = extrair_resposta(resultado["messages"])
                await despachar_humanizacao(redis, conversa_id, turno_id, resposta)

            # 7. drena: se chegou msg durante o turno, repete sob o MESMO lock
            if not await redis.get(f"pending:conv:{conversa_id}"):
                break
            loop_idx += 1
```

> `ESTADOS_TERMINAIS = {"Fechado", "Perdido"}`; `NS_TURNO` é um namespace UUID fixo do módulo. O drain loop fecha a janela "mensagem chega com o turno rodando"; resta um intervalo sub-milissegundo entre o passo 7 e o retorno do job — recuperado pela próxima mensagem do cliente.

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

### 6.1 Pix nunca trava o fluxo (validado ou duvidoso)

`mvp/04 §3.2` tratava Pix recusado como decisão de Fernando que volta o atendimento para `Aguardando_confirmacao`. Versões anteriores desta spec endureciam isso ("Pix duvidoso → IA permanece pausada até Fernando devolver").

**Decisão (grilling 2026-05-22):** o fluxo **nunca trava por Pix**. O recebimento do comprovante sempre faz o atendimento avançar para `Confirmado` com `ia_pausada=true` (motivo `modelo_em_atendimento`), igual ao Pix validado — seja o comprovante validado ou duvidoso. A duvidez é **informativa**, não bloqueante:

- o card "saída confirmada" no grupo **sinaliza a duvidez** à modelo (com o motivo), porque é ela quem decide pedir o Uber e assume o risco do deslocamento;
- o caso entra numa **fila assíncrona de revisão de Fernando** no painel (ele vê depois, no fim do dia);
- não há handoff síncrono, nem pausa esperando decisão de Fernando, nem `pix_em_revisao` bloqueante.

**Justificativa:** a maioria das divergências é benigna (formato de chave, valor com/sem centavos, timestamp). Travar o fluxo gerava handoff para Fernando em todo caso duvidoso e atrasava a saída da modelo. Mover a decisão para a modelo (que está no momento certo e assume o risco) + revisão assíncrona de Fernando preserva a velocidade sem cegar quem paga o Uber.

**Implementação:** `workers/pix.py:validar_pix` aplica a transição para `Confirmado` em ambos os casos; o resultado da validação (validado/duvidoso + motivo) vai no payload do card e numa fila de revisão. Remover o override que preservava `ia_pausada=true` por `pix_em_revisao`. Ver `06 §2.2` e `07 §5`.

**Estados legados (P0 não produz):** como o fluxo sempre avança, o pipeline só seta `pix_status ∈ {validado, em_revisao}` e `ia_pausada_motivo='modelo_em_atendimento'`. Os valores `pix_status ∈ {invalido, enviado}` e `ia_pausada_motivo='pix_em_revisao'` permanecem no schema (remover valor de ENUM no Postgres é custoso e o schema está estabilizado) mas **não são produzidos pelo pipeline P0** — `invalido` só existiria como veredito manual histórico. A revisão assíncrona de Fernando vive em `comprovantes_pix.decisao_final` (índice da fila já criado em `0001`). Se a modelo desconfiar do comprovante, a saída é o comando **`perdido motivo=risco`** no grupo (Registro de resultado), não um estado de Pix.

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

`mvp/07 §3` cita "Anthropic SDK 0.42 com prompt caching" como stack mas não prescreve provider. `docs/agente` 1.0 colocou OpenRouter + Kimi K2.6 como solução; **esta revisão (1.1) reverte para Anthropic SDK direto + Sonnet 4.6** (sem modelo de fallback — ver `§2.6`).

**Justificativa (revisão pós-QA 2026-05-02):**
- Cache `cache_control` 4 breakpoints é nativo da Anthropic — sem caveats; via OpenRouter tinha comportamento incerto (`OpenRouterTeam/ai-sdk-provider#35`, `sst/opencode#1245`).
- `create_react_agent` foi deprecado em LangGraph v1.0 — adoção viraria dívida técnica de saída. Migramos para StateGraph custom, que casa melhor com gates determinísticos do domínio (`§2.1`).
- Custo absoluto P0: ~R$ 2 mil/mês com Sonnet 4.6 + cache 70% — desprezível vs. ticket médio premium da operação. Diferença para Kimi via OpenRouter é da ordem de R$ 200/mês — não compensa risco em PT-BR e tom premium.

**Implicação para o código existente em `core/llm.py`:** descartar wrapper `OpenRouterClient` e usar `core/llm.py:criar_chat_anthropic(settings, modelo) -> ChatAnthropic` para o chat. (`criar_anthropic_client(settings) -> AsyncAnthropic` ficou **dispensável no P0** — o vision do Pix migrou para OpenRouter, `06 §2.3`; sem consumidor do cliente raw.) Nada de subclasse de `BaseChatModel`.

### 6.7 Sem checkpointer LangGraph no P0

Versões anteriores usavam `AsyncPostgresSaver` (checkpoint por `thread_id`) + cron de retenção de 90 dias. **Decisão (grilling 2026-05-22): removido no P0.**

**Justificativa:** o prompt é montado do zero a cada turno a partir do Postgres (sliding window 20, `02 §4`), então o checkpoint nunca alimentava o prompt — e o reducer `add_messages` com `thread_id` persistente acumulava todo o histórico no estado (quebrando a sliding window) e duplicava as `SystemMessage` dinâmicas a cada turno. Auditoria já vem de `mensagens` + `eventos`; idempotência/resume já vêm de `tool_calls` (`04 §5`) + re-execução do turno. **Mas a idempotência do retry exige `turno_id` determinístico:** `turno_id = uuid5(NS_TURNO, f"{job_id}:{loop_idx}")` (`04 §3.3`), nunca `uuid7()` em runtime — senão o retry do ARQ gera `turno_id` novo, fura a dedupe `dedup:envio:{conversa_id}:{turno_id}:{chunk_idx}` e o cliente recebe a resposta duplicada. O grafo roda com `grafo.compile()` **sem** `checkpointer=` — estado efêmero por invocação. Some o `workers/retencao.py` e seu cron. Se P1 trouxer interrupts/time-travel, reintroduzir o checkpointer com ids estáveis por mensagem desde o início.

### 6.8 Negação ativa de IA + interceptação canned (override `CONTEXT.md`)

`CONTEXT.md` e `mvp/01-contexto-negocio.md` afirmam que a IA "não admite ser IA em hipótese alguma".

**Decisão (grilling 2026-05-22, refinada 2026-05-23):** **negação ativa** — a Bia nega ser IA diretamente na 1ª e 2ª pergunta, em personagem; escala via `escalar(motivo="disclosure_insistente")` só na 3ª insistência. **Pedido de modelo nomeado ("você é Claude/GPT?") é tratado como o genérico** (canned + contador, escala na 3ª — 2026-05-23). Só **jailbreak explícito** (DAN / ignore previous / override) escala direto, sem deflecção. Hierarquia completa em `10 §2`.

**Mecanismo (híbrido):** disclosure de **alta confiança** detectado pelo classificador **dentro do grafo** (`prepare_context`, sobre a cauda da janela — não no webhook, decisão 2026-05-23) é respondido por um **pool de negações canned** (determinístico, 5-8 variações em personagem), interceptado no **nó `intercept_disclosure`** — não confiando no LLM para a parte que o Sonnet 4.6 é pós-treinado a resistir (negar identidade). O contador de insistência (1ª/2ª negar → 3ª escalar) é avaliado pelo contador persistido `atendimentos.disclosure_tentativas` (sobrevive à janela de 20). Casos ambíguos seguem para o LLM com os protocolos few-shot. Ver `10 §2-3` e `10 §8`.

**Implementação:** detalhada em `10-persona-jailbreak.md`. Toca:
- `agente/prompts/persona.md.j2` e `regras.md.j2` (`<protocolo_disclosure>` com negação few-shot + escalada na 3ª).
- `agente/_classificador.py` (regex disclosure/jailbreak sobre a janela, chamado pelo `prepare_context`; `webhook/classificador.py` fica só métrica).
- nó `intercept_disclosure` no grafo (lê `_categoria`/`_confianca` do state; jailbreak escala direto; pool canned p/ disclosure; contador `atendimentos.disclosure_tentativas`).
- `agente/ferramentas/escalada.py` (motivos AUP-família).
- Adversarial dataset em `api/evals/adversariais/` (gateia deploy com pass-rate ≥90%).

### 6.9 Persona/voz/FAQ gerais (override `mvp/` e `CONTEXT.md`)

`mvp/03-modulos-sistema.md`, `mvp/07-stack-tecnica.md` e `docs/specs/tela-06-modelos.md` descrevem **persona e FAQ por modelo** (campos interpolados no template de persona por modelo; `modelo_faq.modelo_id` específico por modelo).

**Decisão (grilling 2026-05-22):** persona/voz/comportamento/conduta/FAQ são **gerais — compartilhadas entre todas as modelos**. As modelos respondem igual no WhatsApp; só variam **as coisas dela**: identidade óbvia (nome, idade, idiomas, localização), programas/preços e `tipos_aceitos`. A isolação de **dados do cliente** por par cliente-modelo permanece intacta. `CONTEXT.md` "IA por modelo" já foi atualizado; os docs de `mvp/` ficam como contexto histórico (esta spec é a verdade técnica corrente).

**Implicações:**
- Breakpoints: `geral (BP1+BP2) → por-modelo (BP3)` no `system` (3 blocos estáveis) + BP4 **condicional na cauda do histórico**; o contexto dinâmico vai no **último user turn, sem `cache_control`** (não é BP — decisão 2026-05-23, ver `03 §1`, `03 §4.4`). Prefixo geral cacheado **uma vez no sistema** (escalável p/ N modelos — `08 §3.1`).
- `agente/prompts/persona.md.j2`/`regras.md.j2` ficam gerais; `faq.md` é arquivo versionado geral (tabela `modelo_faq` dropada em 0030, `03 §3.2`); novo `identidade.md.j2` por-modelo; `Persona` dataclass → `IdentidadeModelo`.
- **Pendente fora do agente (flag p/ painel):** `docs/specs/tela-06-modelos.md` assume configuração de persona/FAQ por modelo — a tela de cadastro deve passar a configurar só identidade óbvia + programas + tipos_aceitos por modelo (persona/voz viram config global; FAQ vira o arquivo `faq.md`, sem CRUD no painel).

### 6.10 Contrato de concorrência do atendimento: `lock:conv` + compare-and-set

**Decisão (grilling 2026-05-22):** `lock:conv:{conversa_id}` serializa apenas **sequências multi-step exclusivas** — o turno (`processar_turno`) e o roteamento de imagem (`rotear_imagem`, §1). Ele **não** é o mutex de toda mutação do atendimento.

Transições terminais atômicas — cron de timeouts (`workers/timeouts.py`) e comandos no grupo (`webhook → escaladas`) — usam **UPDATE condicional (compare-and-set)** com guarda no `WHERE` (`... WHERE id=? AND estado=<esperado> AND ia_pausada=false`), no estilo `FOR UPDATE SKIP LOCKED` que o cron já adota. São instantâneos (sem esperar lock) e atômicos.

Consequências:
- As **write-tools do turno** ganham a mesma guarda no `WHERE`. Se o cron já virou `Perdido` no meio do turno, a tool vira no-op (0 linhas afetadas).
- O **`post_process`** passa a checar **`estado` terminal além de `ia_pausada`** — fecha o furo em que o cron marca `Perdido`/`sumiu` (sem setar `ia_pausada`, ver `workers/timeouts.py`) e a IA responderia um cliente já dado como perdido.
- Resíduo aceito: janela sub-segundo (ex.: `enviar_midia` disparar microssegundos antes de um timeout). Eliminá-la exigiria o cron adquirir `lock:conv` — **rejeitado** por enfiar dependência Redis num cron hoje SQL-puro/atômico.

**Justificativa:** estende o padrão que o cron já usa (`SKIP LOCKED` + `WHERE` guard) em vez de bolt-on de mutex Redis em toda mutação; consistente com ADR-0002 (SQL puro) e responsivo para o painel/comandos de Fernando.

### 6.11 Desconto de fechamento — IA negocia até um piso (reverte `mvp`)

`mvp/02`, `mvp/03` e `mvp/05 §14` afirmam que a IA **não negocia** ("desconto não autorizado → escala"). **Decisão (grilling 2026-05-23, ADR-0004):** a IA pode conceder **Desconto de fechamento** (`CONTEXT.md`) de até `settings.desconto_max_pct` (~15%) sobre o **preço de tabela** do programa — reativo (cliente pede) ou proativo (reengajamento), em **uma** contraproposta no piso; recusou/insistiu → `escalar(fora_de_oferta)`. Nunca incide no Pix de deslocamento. Regra do % no prompt geral (`03 §3.1 <desconto>`); guarda determinística no `registrar_extracao_ia` barra `valor_acordado` abaixo do piso (`04 §3.1`). `desconto_max_pct=0` restaura o "não negocia". `mvp/05 §14` vira contexto histórico.

### 6.12 Reengajamento proativo (novo — antes só timeout passivo)

`mvp` só previa timeout passivo (24h → `Perdido`). **Decisão (grilling 2026-05-23):** a IA reabre proativamente, **uma vez**, o cliente que recebeu a cotação e silenciou — toque único ~`settings.reengajamento_delay_min` (30min) depois, dentro do horário de operação, com mensagem canned calorosa **sem desconto**; via cron `varrer_timeouts` (`07 §4`); marca `reengajado_em`; não reseta o relógio de 24h. **P0 atrás de flag** `settings.reengajamento_ativo` (default off). Ver `CONTEXT.md` "Reengajamento".

### 6.13 Mídia exclusiva — narrativa no P0, view-once condicional

A ata pede vídeo como visualização única ("ao vivo, só pra ele"). A doc oficial da Evolution v2 **não expõe `viewOnce`** no `sendMedia`. **Decisão (grilling 2026-05-23):** o P0 entrega a **narrativa de exclusividade** (foto→vídeo via `enviar_midia(tipo)`, legenda "ao vivo"; `03 §3.1 <midia>`, `04 §3.3`); o **view-once técnico** é pré-req a confirmar na instância self-host (passa o campo → liga; senão P1). Ver `CONTEXT.md` "Mídia exclusiva".

## 7. O que está fora da spec do agente

- **CRUD de modelos/FAQ/mídia** — pertence a `dominio/modelos/`, painel.
- **Painel Next.js** — fora completamente.
- **Schema do banco** — em `infra/sql/` (já estabilizado).
- **Comandos no grupo de Coordenação** (parser texto + `aplicar_comando`) — já implementado em `webhook/routes.py` + `dominio/escaladas/service.py`.
- **Pipeline de OCR/vision Pix** — está em `06-pipelines-midia.md`, mas o pipeline em si vive em `workers/pix.py`, fora do agente.
