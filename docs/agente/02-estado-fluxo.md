# 02 — Estado, Thread e Fluxo de Turno

> Define `EstadoAgente`, `thread_id`, política de hidratação, sliding window, contexto dinâmico e ciclo de vida de um turno.

## 1. State do LangGraph

```python
# api/src/barra/agente/estado.py
from langgraph.graph import MessagesState

class EstadoAgente(MessagesState):
    """State do agente Elite Baby.

    Reduce: add_messages (default do MessagesState) para `messages`.
    Não carregamos atendimento_id, modelo_id ou cliente_id no State —
    esses ficam no ContextAgente (Runtime Context API, 04 §1.1) para acesso pelas tools,
    e o contexto dinâmico é re-injetado no último turno do usuário a cada turno pelo
    prepare_context.

    Postgres é a fonte de verdade; sem checkpointer no P0 (01 §6.7) —
    estado efêmero por invocação, montado do zero a cada turno.
    """

    midia_idx: int           # call_idx determinístico p/ idempotência de enviar_midia (04 §3.3)
    _categoria: str | None    # disclosure/jailbreak classificado pelo prepare_context (10 §8)
    _confianca: float | None  # confiança da classificação; lido pelo intercept_disclosure
```

Estendemos com **campos transitórios por-turno** (`midia_idx`, `_categoria`, `_confianca`) — não persistidos, sem dado de domínio. `_categoria`/`_confianca` são gravadas pelo `prepare_context`, que **classifica disclosure/jailbreak dentro do grafo** (regex sobre a cauda de mensagens da janela), em vez de receber a categoria do webhook — robusto a debounce/drain, que processam uma janela e não um evento de mensagem único (decisão grilling 2026-05-23; ver `10 §8`); o `intercept_disclosure` lê esses campos para rotear. **A pausa não usa flag de state:** o `prepare_context` faz early exit via `Command(goto=END)` quando `ia_pausada` (`03 §7`) — por isso não há `_pausada`/`_intercept`. Se em P1 surgir necessidade (ex.: classificador interno/externo armazenado), adicionar como campo opcional com reducer apropriado.

### 1.1 Por que minimalista

Alternativas consideradas:
- **State gordo** (atendimento dict + agenda + cliente) — duplica verdade; checkpoint cresce; cache invalida ao mudar dado.
- **State médio** (IDs + flags) — economia marginal; idempotência via `turno_id` no context já cobre.

A escolha minimalista mantém o checkpoint pequeno e fiel à intenção: **histórico conversacional**. Tools acessam dados via `runtime.context` (Runtime Context API, `02 §6`).

## 2. thread_id

```python
config = {"configurable": {"thread_id": str(conversa_id)}}  # demais deps/ids vão no context (§6)
```

`conversa_id` é UUID do par `(cliente_id, modelo_id)` na tabela `conversas`. Único e estável ao longo da vida da conversa, mesmo entre múltiplos atendimentos sucessivos.

**Implicações:**
- Quando o cliente fecha um atendimento e volta dias depois, **o `thread_id` é o mesmo** — mas, sem checkpointer (`§3`), nada do turno anterior é re-hidratado pelo grafo; a continuidade vem da `mensagens` table (sliding window 20, `§4`).
- Multi-modelo: cliente que conversa com modelo A e modelo B tem **dois `thread_id` distintos** (um por par). Isolamento natural; alinha com `mvp/04 §4.1`.

`thread_id` serve só como tag de trace LangSmith e chave de escopo das tools — não há estado de grafo persistido para rotacionar. O `prepare_context` sempre monta o prompt do zero a partir da `mensagens` table.

## 3. Sem checkpointer no P0

O grafo é compilado **sem checkpointer** (`grafo.compile()` puro) — estado efêmero por invocação. O prompt é montado do zero a cada turno a partir do Postgres (sliding window 20, `§4`), então não há histórico para persistir no grafo. Justificativa completa em `01 §6.7`.

```python
# Lifespan FastAPI (api/src/barra/main.py:lifespan)
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = AsyncConnectionPool(
        settings.database_url,  # Supavisor 6543
        min_size=4,
        max_size=20,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )
    await pool.open()

    graph = build_graph(settings)  # sem checkpointer

    app.state.db_pool = pool
    app.state.graph = graph

    yield

    await pool.close()
```

- **Pool único** compartilhado entre repos de domínio e tools.
- **`autocommit=True`** é exigência do Supavisor transaction mode.
- **Sem tabelas de checkpoint** — não criamos `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`. Auditoria vem de `mensagens` + `eventos`; idempotência de `tool_calls` (`04 §5`).

### 3.1 Worker ARQ usa o mesmo padrão

ARQ workers rodam em processo próprio (não FastAPI). Cada worker tem seu pool e compila o grafo no `on_startup` (sem checkpointer):

```python
# api/src/barra/workers/settings.py
class WorkerSettings:
    async def on_startup(ctx):
        pool = AsyncConnectionPool(...)
        await pool.open()
        ctx["db_pool"] = pool
        ctx["graph"] = build_graph(settings)  # sem checkpointer
        ctx["redis"] = await criar_redis(settings.redis_url)

    async def on_shutdown(ctx):
        await ctx["db_pool"].close()
        await ctx["redis"].close()

    functions = [processar_turno, enviar_turno, enviar_card, transcrever_audio, rotear_imagem, validar_pix]
    cron_jobs = [varrer_timeouts]  # a cada 5min
```

## 4. Sliding window de mensagens

Cada turno carrega as **20 últimas mensagens** da conversa (todas as direções: `cliente`, `ia`, `modelo_manual`).

> **Caveat (chunking infla a contagem):** cada resposta da IA é persistida como **uma linha por chunk** (`enviar_turno`, `05 §4.2`). Um turno de 3 chunks = 3 linhas `direcao='ia'`. Logo **20 linhas ≠ 20 turnos lógicos** — na prática são ~5-6 trocas de cliente de memória conversacional. Isso é aceito porque os **fatos duráveis** (horário, endereço, tipo, intenção) vivem no snapshot do `registrar_extracao` em `atendimentos.*` e são re-injetados no contexto dinâmico **todo turno**, independentemente da janela. Se o error analysis do piloto mostrar perda de memória, a saída é coalescer chunks consecutivos da IA — o que exigiria uma coluna de agrupamento (`turno_id`/`grupo_envio`) em `mensagens`, inexistente hoje; não antecipar (`CLAUDE.md §2`).

### 4.1 Query

```sql
SELECT m.id,
       m.direcao,
       m.tipo,
       m.conteudo,
       m.media_object_key,
       m.created_at
  FROM barravips.mensagens m
 WHERE m.conversa_id = %s
 ORDER BY m.created_at DESC, m.id DESC
 LIMIT 20;
```

Resultado revertido em Python para ordem cronológica antes de virar `messages` na entrada do grafo. O desempate por `m.id` (uuidv7, time-ordered) garante ordem **determinística** mesmo com `created_at` empatado (picotadas no mesmo instante) — pré-requisito do render byte-idêntico exigido pelo cache (`agente/CLAUDE.md`).

### 4.2 Tradução para LangChain messages

```python
from langchain_core.messages import HumanMessage, AIMessage

def traduzir_mensagens(linhas: list[dict]) -> list:
    out = []
    for linha in linhas:
        if linha["direcao"] == "cliente":
            conteudo = linha["conteudo"] or ""
            if linha["tipo"] == "audio":
                if not conteudo:
                    # transcrição falhou/não chegou — placeholder só de contexto;
                    # a resposta ao áudio falho do turno atual é canned (06 §1.4), não via LLM
                    conteudo = "[áudio que não consegui ouvir]"
                else:
                    conteudo = f"{conteudo}\n_(originalmente áudio)_"
            elif linha["tipo"] == "imagem":
                # IA é cega a imagens no P0. Imagem pura fora-fluxo nem dispara turno (06 §3);
                # aqui ela só aparece como contexto de turnos futuros. Com legenda, a legenda é o
                # conteúdo textual real; sem legenda, placeholder discreto.
                conteudo = conteudo or "[imagem]"
            out.append(HumanMessage(content=conteudo, id=str(linha["id"])))
        elif linha["direcao"] == "ia":
            out.append(AIMessage(content=linha["conteudo"], id=str(linha["id"])))
        elif linha["direcao"] == "modelo_manual":
            # Mensagem manual da modelo durante handoff: saiu no MESMO número da IA,
            # então é turno assistant. SystemMessage interspersed seria içada para o
            # param `system` pelo langchain_anthropic (perde cronologia + fura o cache);
            # o prefixo no texto distingue da IA para o modelo não se atribuir o que ela disse.
            out.append(AIMessage(
                content=f"[mensagem manual da modelo]: {linha['conteudo']}",
                id=str(linha["id"]),
            ))
        else:
            # Defesa: schema só permite cliente/ia/modelo_manual; chegar aqui é bug.
            raise ValueError(
                f"direcao desconhecida em mensagens.id={linha['id']}: {linha['direcao']!r}"
            )
    return out
```

### 4.3 O que **não** vai na window

- Mensagens do grupo de Coordenação por modelo (cards, confirmações) — não estão em `mensagens` (`mvp/06 §2.6`).
- Imagem pura fora-fluxo não dispara turno (`06 §3`); só aparece como placeholder `[imagem]` em turnos futuros disparados por texto. Imagem com legenda entra com a legenda como conteúdo.
- Áudio do cliente cuja transcrição falhou — entra como `"[áudio que não consegui ouvir]"` (contexto); a resposta imediata é canned (`06 §1.4`).

## 5. Contexto dinâmico (re-injetado a cada turno)

O nó `prepare_context` monta um conjunto de mensagens do tipo:

```
[
  SystemMessage (persona + regras — GERAL, cache_control 1h),                       # BP1 compartilhado
  SystemMessage (FAQ — GERAL, cache_control 1h),                                    # BP2 compartilhado
  SystemMessage (identidade modelo + programas + tipos_aceitos — cache_control 1h), # BP3 por-modelo
  ... últimas 20 mensagens (penúltima leva cache_control 5min SÓ se append-only) ... # BP4 condicional na cauda (adiado P1; P0 sem cache aqui)
  HumanMessage (msg do cliente + contexto dinâmico + reminder — SEM cache_control)  # turno volátil
]
```

Detalhes do template em `03-prompts.md`. O **contexto dinâmico** é montado por turno e **concatenado no último `HumanMessage`** (junto da msg do cliente e do reminder), **fora do prefixo cacheável** — "stable first, volatile last" (`03 §1`, `03 §4.4`). NÃO é uma `SystemMessage` e não leva `cache_control`. Conteúdo:

```jinja2
# Estado atual do atendimento

- Atendimento: #{{ numero_curto }}
- Estado: {{ estado }}
- Tipo: {{ tipo_atendimento or "ainda não definido" }}
- Urgência: {{ urgencia or "não capturada" }}
- Pix de deslocamento: {{ pix_status }}
{% if data_desejada %}- Data desejada: {{ data_desejada }} às {{ horario_desejado }}{% endif %}
{% if endereco %}- Endereço/local: {{ endereco }}{% if bairro %} ({{ bairro }}){% endif %}{% endif %}

# Cliente

- Nome: {{ cliente_nome or "ainda não informado" }}
- Recorrente nesta conversa: {{ "sim" if recorrente else "não" }}
{% if historico_anteriores %}- Histórico nesta conversa: {{ historico_anteriores }}{% endif %}
{% if ultimo_motivo_perda %}- Último motivo de perda nesta conversa: {{ ultimo_motivo_perda }}{% endif %}
{% if observacoes_internas %}- Observações operacionais: {{ observacoes_internas }}{% endif %}

# Agenda da modelo (próximas 48h)

{% if bloqueios %}
{% for b in bloqueios %}- {{ b.inicio.strftime("%a %d/%m %H:%M") }} – {{ b.fim.strftime("%H:%M") }} ({{ b.estado }})
{% endfor %}
{% else %}
- Sem bloqueios nas próximas 48h. Disponibilidade total.
{% endif %}
```

O nó `prepare_context` resolve cada variável via queries específicas (ver `07 §2`).

> **`historico_anteriores`** é um resumo curto dos atendimentos `Fechado`/`Perdido` do par `(cliente, modelo)` — ex.: `"fechou 2x (R$1.2k), perdeu 1x (preco)"`. Foi dobrado aqui ao remover a tool `consultar_cliente` (grilling 2026-05-23, `04 §2.2`): `recorrente` (booleano) não distingue quem fechou 3x de quem perdeu 3x, e ter isso sempre no contexto evita um round-trip de tool. Isolamento por par é preservado (a query já filtra `cliente_id` **e** `modelo_id`).

> **Sem `turno_id` no prompt:** versões anteriores injetavam `turno_id` no contexto dinâmico "para o LLM usar nas tools de escrita". Removido — nenhuma tool aceita `turno_id` como argumento; elas leem de `runtime.context.turno_id` (`04 §3.1`). Instruir o LLM a passar um valor que nenhuma tool recebe só confunde.

## 6. Runtime context e tools

Tools recebem deps e IDs de escopo via **`ToolRuntime[ContextAgente]`** (Runtime Context API, idiomático no LangGraph 1.x) — **não** pelo dict `config["configurable"]`, que é o padrão **legado** (e que o checkpointer serializa, quebrando com pool/redis ao religar no P1; `01 §2.3`, `04 §1.1`). `ContextAgente` é definido em `agente/contexto.py`. Padrão:

```python
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from ..contexto import ContextAgente

@tool
async def consultar_agenda(
    data_inicio: str,
    data_fim: str,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Consulta bloqueios da modelo em janela. Datas no formato YYYY-MM-DD."""
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    # ... query e retorno
```

`runtime: ToolRuntime[ContextAgente]` é injetado automaticamente pelo `ToolNode` (não aparece no schema enviado ao LLM) e dá acesso **tipado**: `runtime.context.db_pool`, `runtime.context.turno_id`, etc. Também expõe `runtime.config` (`RunnableConfig`), `runtime.state` e `runtime.tool_call_id` quando preciso.

**Campos do `ContextAgente`** (injetados pelo coordenador via `context=`; `04 §1.1`):

| Campo | Tipo | Uso |
|-------|------|-----|
| `db_pool` | `AsyncConnectionPool` | Pool psycopg |
| `redis` | `ArqRedis` | Cliente redis para tools que precisam (raro) |
| `modelo_id` | `str` | UUID da modelo |
| `atendimento_id` | `str` | UUID do atendimento corrente |
| `cliente_id` | `str` | UUID do cliente |
| `turno_id` | `str` | **UUID5 determinístico** `uuid5(NS_TURNO, f"{job_id}:{loop_idx}")` — idempotência de retry do ARQ (`01 §6.7`). Nunca `uuid7()` runtime |

O `thread_id` (= `conversa_id`) **não** vai no `ContextAgente` — fica em `config["configurable"]["thread_id"]`, que é nativo do LangGraph/checkpointer (`§2`).

**Não passar** dados gordos (atendimento dict, persona) via context — re-leitura é barata e mantém referência única no DB.

## 7. Ciclo de vida de um turno

Sequência canônica do coordenador (`workers/coordenador.py:processar_turno`):

```
1. Despertar (ARQ delay = janela debounce, `_defer_by` fixo)
   ├─ debounce é **first-wins**: o 1º enqueue na janela vence (SET NX no `_job_id` estático);
   │  os seguintes são DESCARTADOS (sem substituição, sem reset de `_defer_by`)
   └─ ao despertar, o turno lê a janela inteira — toda mensagem chegada na janela já está no DB

2. Adquirir lock Redis SETNX `lock:conv:{conversa_id}` (TTL 60s)
   ├─ se ocupado (contenda com `rotear_imagem`, único outro dono do lock): captura `LockBusy`
   │  e re-defere o próprio job ~2-3s (espelha `rotear_imagem`, `06 §2.1`); `pending` já setado
   └─ se livre: prossegue + inicia heartbeat task (EXPIRE +60s a cada 15s)

3. Resolver atendimento (transação curta)
   ├─ SELECT atendimento aberto para (cliente_id, modelo_id) ∉ {Fechado, Perdido}
   ├─ se não houver: INSERT em estado=Novo
   └─ UPDATE mensagens SET atendimento_id = ? WHERE conversa_id = ? AND atendimento_id IS NULL

4. Verificar gates de pausa
   ├─ pre-check barato: se atendimento.ia_pausada=true: log e encerra (sem invocar grafo).
   │    O gate é dobrado dentro do grafo, no prepare_context (que já carrega a linha do
   │    atendimento); não há nó gate_pausa separado (01 §2.1).
   └─ se há áudio pendente E aguardar_transcricao=true:
        BLPOP redis canal `transcricao:{atendimento_id}` (timeout 8s)
        se timeout/falha: mensagens com tipo=audio e conteudo='' viram placeholder

4b. Gate de áudio falho (antes de invocar o grafo)
   └─ se o conteúdo novo do cliente neste turno for SÓ áudio falho (sem texto utilizável):
        responde canned (pool de variações, `06 §1.4`) e encerra — não invoca o LLM.
        Se houver texto junto, segue para o grafo (o placeholder vira só contexto).

5. Invocar grafo (contexto montado dentro dele, pelo prepare_context)
   ├─ build entrada = {"messages": []}  # prepare_context monta persona+faqs+programas+dinâmico+janela
   └─ graph.ainvoke(entrada, config={"configurable": {"thread_id": conversa_id}, "recursion_limit": 18}, context=ContextAgente(...))
        # RECURSION_LIMIT=18 (canônico em 07 §3): ~6-7 round-trips llm↔tools (5 tools no P0). É
        # contagem de PASSOS DE NÓ, acoplada à topologia — validar empiricamente (NÃO confiar na
        # fórmula 2×iter+5) e reavaliar se adicionar/remover nós (09 "Bugs e decisões").

6. Tratar saída
   a) `except GraphRecursionError` (classe, não string-match) ou timeout LLM → escalar_por_exaustao() e encerrar
   b) refetch atendimento; se ia_pausada=true OU estado terminal (escalada via tool / cron): log e encerrar (compare-and-set, `01 §6.10`)
   c) caso normal: extrair último AIMessage do State; parse mídias anexadas; despachar humanização

7. Despachar humanização
   ├─ chunk_texto(texto) → chunks (05 §2); coletar mídias do turno (tool_calls, ORDER BY call_idx)
   ├─ coletar msg_ids_cliente + chars_inbound (msgs do cliente do turno, p/ read receipt — 05 §4.2)
   ├─ critico = houve write tool com efeito? (pedir_pix / registrar_extracao c/ transição)
   └─ enqueue UM job enviar_turno(conversa_id, turno_id, chunks, midias, msg_ids_cliente, chars_inbound, critico)

8. Drenar pending (MESMO lock) e liberar
   ├─ se `pending:conv:{conversa_id}` existe: loop_idx++ e re-roda 3-7 sob o MESMO lock
   │    (drain loop, `01 §4.3`) — turno_id da nova iteração = uuid5(job_id, loop_idx)
   └─ senão: libera lock (DEL condicional via Lua, `07 §3.1`)
```

## 8. Cancelamento e idempotência

### 8.1 Cancel-on-new-message (mecanismo **cross-job**)

Com first-wins + drain loop (`§7`), o cancel-on-new-message cobre **um caso específico**: o turno anterior **já liberou o lock** e seu job `enviar_turno` ainda está enviando os chunks (jitter/typing levam alguns segundos). Mensagem que chega **enquanto o lock ainda está retido** é absorvida pelo drain loop, não por aqui.

1. Webhook persiste a nova mensagem e enfileira `processar_turno` (`_job_id=turno:{conversa_id}`). Se o turno anterior já terminou (lock livre), um novo job nasce; se ainda roda, o enqueue é descartado (first-wins) e a mensagem é recuperada pelo drain loop.
2. Ao iniciar, o novo turno sobrescreve `turno_atual:{conversa_id}` com o próprio `turno_id`. **Isso é o cancel:** o job `enviar_turno` do turno anterior compara `turno_atual` antes de cada item e aborta os pendentes ao detectar que foi superado.

```python
# processar_turno, antes de invocar o grafo (07 §3, passo 3)
await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)

# enviar_turno, antes de cada chunk/mídia (05 §3.1)
if not critico and await redis.get(f"turno_atual:{conversa_id}") != turno_id:
    break  # superado por turno mais novo → aborta os pendentes
```

Detalhes do protocolo em `05 §3`. **Exceção:** turnos com efeito de write tool (`critico=true` no payload do job) **não são cancelados** — a mensagem (ex.: chave Pix) precisa chegar ao cliente, senão o efeito já commitado fica órfão (`05 §3`).

### 8.2 Idempotência de tools de escrita

Cada chamada de tool de escrita usa `(turno_id, tool_name)` como chave. Esquema:

```sql
-- tabela auxiliar (cria em migration nova; ainda não existe)
CREATE TABLE barravips.tool_calls (
  turno_id uuid NOT NULL,
  tool_name text NOT NULL,
  call_idx smallint NOT NULL,        -- enviar_midia pode ser chamada várias vezes
  payload jsonb NOT NULL,
  resultado jsonb,
  created_at timestamptz DEFAULT now(),
  PRIMARY KEY (turno_id, tool_name, call_idx)
);
```

Tool `registrar_extracao` força `call_idx=0` e UPSERT (segunda chamada no mesmo turno é ignorada e retorna o resultado anterior — coerente com `mvp/03 §5.3` "uma vez por turno").

Tool `enviar_midia` permite múltiplas chamadas; `call_idx` é o número da chamada (0, 1, 2...).

Tool `escalar` força `call_idx=0`; segunda chamada no mesmo turno retorna erro estruturado para o LLM (que ignora — turno já foi marcado como pausado).

## 9. Prevenção de turnos zumbis

Casos a tratar:

| Situação | Tratamento |
|----------|------------|
| Worker crashou no meio do turno | Lock TTL expira em ≤60s; nova mensagem do cliente cria novo turno |
| LLM travou >timeout do client HTTP (60s) | Coordenador captura exceção, escala_por_exaustao, libera lock |
| ARQ retentou job parcialmente executado | Cada tool tem chave idempotente em `tool_calls`; humanização via `dedupe_key` |
| `processar_turno` contende lock com `rotear_imagem` | Lock SETNX serializa; perdedor (`LockBusy`) re-defere ~2-3s. Dois `processar_turno` da mesma conversa nunca coexistem (job_id estático first-wins) |
| Conversa com mais de 20 turnos sem reset | Sliding window corta; sem checkpointer, nada acumula no grafo |

## 10. Métricas Prometheus do turno

Exportadas pelo coordenador:

```python
TURNO_DURACAO = Histogram("agente_turno_duracao_seconds", ...)
TURNO_ITERACOES = Histogram("agente_turno_iteracoes_total", ...)
TURNO_RESULTADO = Counter("agente_turno_resultado_total", ["resultado"])
  # resultado ∈ {ok, escalado, exaustao, ia_pausada_skip, lock_busy, transcricao_timeout}
TURNO_TOKENS = Counter("agente_turno_tokens_total", ["tipo"])
  # tipo ∈ {input, output, cache_read, cache_write}
```

Usados pelo dashboard/eval (`08 §3`).

## 11. Tabela de transições de estado (fonte única do lado do agente)

Reflete a **verdade técnica corrente** (esta spec); onde diverge de `mvp/04 §8.2`, está marcado e o porquê fica em `01 §6`. A máquina de domínio **não** é refletida em nós do LangGraph (`01 §2.1`) — cada linha é disparada por tool, pipeline, webhook/worker ou cron.

| De | Para | Gatilho | Onde (agente) | Efeitos colaterais |
|----|------|---------|---------------|--------------------|
| (criação) | `Novo` | 1ª msg sem atendimento reusável | `resolver_atendimento` (`07 §3.2`) | — |
| `Novo` | `Triagem` | extração com intenção mínima | `registrar_extracao` (`04 §3.1`) | — |
| `Triagem` | `Qualificado` | extração: `intencao=agendamento` + horário + tipo | `registrar_extracao` | — |
| `Qualificado` | `Aguardando_confirmacao` (interno) | extração: `tipo=interno` + horário | `registrar_extracao` | cria **bloqueio prévio** (advisory lock + EXCLUDE, branch 13) |
| `Qualificado` | `Aguardando_confirmacao` (externo) | `pedir_pix_deslocamento` | tool pix (`04 §3.2`) | `pix_status=aguardando` + **bloqueio prévio** (branch 5). Invariante: externo nesse estado ⟹ Pix solicitado |
| `Aguardando_confirmacao` | `Confirmado` (externo) | comprovante recebido — **validado OU duvidoso** | `validar_pix`→`atualizar_pix` (`06 §2.2`, `07 §5`) | `ia_pausada=true` (`modelo_em_atendimento`). Duvidoso: card sinaliza + fila Fernando. **Diverge do mvp** (Pix nunca trava, `01 §6.1`) |
| `Aguardando_confirmacao` | `Em_execucao` (interno) | foto de portaria | `rotear_imagem`→`_handoff_foto_portaria` (sob lock, `06 §4`/branch 14), determinístico | `ia_pausada=true` (`modelo_em_atendimento`); bloqueio→`em_atendimento`; card "cliente chegou". IA é cega à imagem |
| `Confirmado` | `Em_execucao` (externo) | horário previsto chega | cron/coordenador, determinístico | bloqueio→`em_atendimento` |
| `Em_execucao` | `Fechado` | `fechado valor` / `finalizado valor` | grupo/painel (**fora do agente**) | bloqueio→`concluido`; financeiro |
| qualquer (até `Em_execucao`) | `Perdido` | `perdido motivo` | grupo/painel | bloqueio→`cancelado` se ∉ {em_atendimento, concluido} |
| pré-confirmação (`Novo`/`Triagem`/`Qualificado`/`Aguardando_confirmacao`) | `Perdido` | timeout 24h sem **mensagem do cliente** (IA/modelo não contam; `timeouts.py`) | cron `varrer_timeouts` (`07 §4`) | `motivo=sumiu`; bloqueio→`cancelado` |
| `Aguardando_confirmacao` (interno) | `Perdido` | **45 min do `aviso_saida_em`** sem foto | cron (`07 §4`) | `motivo=sumiu`; bloqueio→`cancelado`. **Diverge do mvp §8.2** (que diz "30 min após horário"); referência é o aviso de saída (`CONTEXT.md`) |

**Transições nulas (eventos colaterais — estado preserva):**
- Aviso de saída (texto) em `Aguardando_confirmacao` interno → grava `aviso_saida_em` + card; IA segue conduzindo (`06 §5`).
- Imagem fora-fluxo → IA cega (`06 §3`); pura não dispara turno.
- **Reagendamento pós-bloqueio** → não muda estado; escala para a modelo (`reagendamento_pos_bloqueio`, branch 12).
- **Reengajamento** (cliente sumiu após cotação) → não muda estado: o cron envia 1 toque proativo ao cliente e marca `reengajado_em` (não reseta o timeout de 24h; `07 §4`). Desligável por `settings.reengajamento_ativo` (default off).
- Disclosure 3ª insistência / jailbreak / pedido explícito repetido etc. → não muda estado de domínio; `ia_pausada=true` via `escalar`/`intercept_disclosure` (handoff Fernando).

> `pix_status` é campo, não estado: o atendimento fica em `Aguardando_confirmacao` enquanto `pix_status ∈ {nao_solicitado, aguardando}`; o **recebimento do comprovante** (validado ou duvidoso) move para `Confirmado` (`01 §6.1`). `invalido`/`enviado`/`pix_em_revisao` são legado não produzido pelo pipeline P0 (`01 §6.1`).
