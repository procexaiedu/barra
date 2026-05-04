# 02 — Estado, Thread e Fluxo de Turno

> Define `EstadoAgente`, `thread_id`, política de hidratação, sliding window, contexto dinâmico e ciclo de vida de um turno.

## 1. State do LangGraph

```python
# api/src/barra/agente/estado.py
from langgraph.graph import MessagesState

class EstadoAgente(MessagesState):
    """State do agente Barra Vips.

    Reduce: add_messages (default do MessagesState).
    Não carregamos atendimento_id, modelo_id ou cliente_id no State —
    esses ficam em config['configurable'] para acesso pelas tools, e são
    re-injetados como SystemMessage dinâmica a cada turno pelo coordenador.

    Postgres é a fonte de verdade; checkpoint só guarda histórico de mensagens.
    """
```

**Não estendemos** com campos adicionais no P0. Se em P1 surgir necessidade (ex.: classificador interno/externo armazenado), adicionar como campo opcional com reducer apropriado.

### 1.1 Por que minimalista

Alternativas consideradas:
- **State gordo** (atendimento dict + agenda + cliente) — duplica verdade; checkpoint cresce; cache invalida ao mudar dado.
- **State médio** (IDs + flags) — economia marginal; idempotência via `turno_id` em config já cobre.

A escolha minimalista mantém o checkpoint pequeno e fiel à intenção: **histórico conversacional**. Tools acessam dados via `RunnableConfig` (`02 §6`).

## 2. thread_id

```python
config = {"configurable": {"thread_id": str(conversa_id), ...}}
```

`conversa_id` é UUID do par `(cliente_id, modelo_id)` na tabela `conversas`. Único e estável ao longo da vida da conversa, mesmo entre múltiplos atendimentos sucessivos.

**Implicações:**
- Quando o cliente fecha um atendimento e volta dias depois, **a thread é a mesma** — o checkpoint LangGraph contém todas as AIMessage anteriores (sliding window depois corta para 20).
- Multi-modelo: cliente que conversa com modelo A e modelo B tem **duas threads distintas** (uma por par). Isolamento natural; alinha com `mvp/04 §4.1`.

**Não fazemos rotação de thread** ao fechar/perder. Justificativa: o checkpoint cresce devagar (10–30 mensagens por atendimento), e o coordenador sempre monta o prompt do zero a partir da `mensagens` table — checkpoint serve para auditoria/resume, não para alimentar prompt.

## 3. Checkpointer

```python
# Lifespan FastAPI (api/src/barra/main.py:lifespan)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
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

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()  # idempotente; cria tabelas de checkpoint na 1a vez

    graph = build_graph(checkpointer)

    app.state.db_pool = pool
    app.state.checkpointer = checkpointer
    app.state.graph = graph

    yield

    await pool.close()
```

- **Pool único** compartilhado entre checkpointer, repos de domínio e tools.
- **`autocommit=True`** é exigência do Supavisor transaction mode.
- **`setup()`** cria tabelas `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` no schema default. Aceitável; manter fora do `barravips` para isolar.

### 3.2 Política de retenção (cron noturno)

`AsyncPostgresSaver` não faz retenção automática — em produção com cliente premium recorrente, `checkpoint_blobs` cresce continuamente. Como o coordenador monta o prompt do zero a cada turno (sliding window 20 + contexto fresco do Postgres), o checkpoint serve apenas para auditoria/resume-from-error.

**Política:** apagar checkpoints sem atividade há **>90 dias por `thread_id`** via cron ARQ diário (03:00 BRT).

```python
# api/src/barra/workers/retencao.py
from arq import cron

@cron(hour=3, minute=0)
async def limpar_checkpoints_antigos(ctx) -> None:
    """Apaga checkpoints LangGraph de threads inativas há >90 dias."""
    pool = ctx["db_pool"]
    async with pool.connection() as conn, conn.transaction():
        res = await conn.execute(
            """
            WITH threads_inativas AS (
              SELECT thread_id
                FROM checkpoints
               GROUP BY thread_id
              HAVING max(created_at) < now() - interval '90 days'
            ),
            del_blobs AS (DELETE FROM checkpoint_blobs WHERE thread_id IN (SELECT thread_id FROM threads_inativas) RETURNING 1),
            del_writes AS (DELETE FROM checkpoint_writes WHERE thread_id IN (SELECT thread_id FROM threads_inativas) RETURNING 1),
            del_main AS (DELETE FROM checkpoints WHERE thread_id IN (SELECT thread_id FROM threads_inativas) RETURNING thread_id)
            SELECT
              (SELECT count(*) FROM del_blobs) AS blobs,
              (SELECT count(*) FROM del_writes) AS writes,
              (SELECT count(*) FROM del_main)  AS main
            """,
        )
        stats = await res.fetchone()
    CHECKPOINT_PURGADO.labels("blobs").inc(stats["blobs"])
    CHECKPOINT_PURGADO.labels("writes").inc(stats["writes"])
    CHECKPOINT_PURGADO.labels("main").inc(stats["main"])
```

**Métrica:** `agente_checkpoint_purgado_total{tipo ∈ blobs|writes|main}` — alerta se volume diário divergir >3× da média móvel de 7 dias (possível bug).

**Justificativa:** em `mensagens` mantemos histórico oficial para o prompt; checkpoint é só replay/debug. 90 dias cobre janela de análise post-mortem sem inflar DB indefinidamente.

### 3.1 Worker ARQ usa o mesmo padrão

ARQ workers rodam em processo próprio (não FastAPI). Cada worker tem seu pool e checkpointer no `on_startup`:

```python
# api/src/barra/workers/settings.py
class WorkerSettings:
    async def on_startup(ctx):
        pool = AsyncConnectionPool(...)
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        ctx["db_pool"] = pool
        ctx["graph"] = build_graph(checkpointer)
        ctx["redis"] = await criar_redis(settings.redis_url)

    async def on_shutdown(ctx):
        await ctx["db_pool"].close()
        await ctx["redis"].close()

    functions = [processar_turno, enviar_chunk, transcrever_audio, validar_pix]
    cron_jobs = [varrer_timeouts]  # a cada 5min
```

## 4. Sliding window de mensagens

Cada turno carrega as **20 últimas mensagens** da conversa (todas as direções: `cliente`, `ia`, `modelo_manual`).

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
 ORDER BY m.created_at DESC
 LIMIT 20;
```

Resultado revertido em Python para ordem cronológica antes de virar `messages` no entrada do grafo.

### 4.2 Tradução para LangChain messages

```python
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

def traduzir_mensagens(linhas: list[dict]) -> list:
    out = []
    for linha in linhas:
        if linha["direcao"] == "cliente":
            conteudo = linha["conteudo"] or ""
            if linha["tipo"] == "audio":
                if not conteudo:
                    # transcrição falhou ou não chegou (timeout) — placeholder explícito
                    conteudo = "[áudio não transcrito]"
                else:
                    conteudo = f"{conteudo}\n_(originalmente áudio)_"
            elif linha["tipo"] == "imagem":
                conteudo = "_[cliente enviou imagem; conteúdo não interpretado]_"
            out.append(HumanMessage(content=conteudo, id=str(linha["id"])))
        elif linha["direcao"] == "ia":
            out.append(AIMessage(content=linha["conteudo"], id=str(linha["id"])))
        elif linha["direcao"] == "modelo_manual":
            # mensagem manual da modelo durante handoff — vinculante, mas não-IA
            out.append(SystemMessage(
                content=f"[mensagem manual da modelo no WhatsApp do cliente]: {linha['conteudo']}",
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
- Mídia do cliente sem transcrição/conteúdo — entra como placeholder textual.
- Áudio do cliente cuja transcrição falhou — entra como `"[áudio não transcrito, Xs]"`.

## 5. Contexto dinâmico (re-injetado a cada turno)

O coordenador monta um conjunto de mensagens do tipo:

```
[
  SystemMessage (persona renderizada — cache_control 1h),
  SystemMessage (regras renderizadas — cache_control 1h),
  SystemMessage (FAQ renderizada — cache_control 1h),
  SystemMessage (programas + valor — cache_control 1h),
  SystemMessage (contexto dinâmico — cache_control 5min),
  ... últimas 20 mensagens ...
  HumanMessage (mensagem do cliente que disparou o turno — implícita; já está nas 20)
]
```

Detalhes do template em `03-prompts.md`. O **contexto dinâmico** é uma `SystemMessage` montada por turno com:

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
{% if ultimo_motivo_perda %}- Último motivo de perda nesta conversa: {{ ultimo_motivo_perda }}{% endif %}
{% if observacoes_internas %}- Observações operacionais: {{ observacoes_internas }}{% endif %}

# Agenda da modelo (próximas 48h)

{% if bloqueios %}
{% for b in bloqueios %}- {{ b.inicio.strftime("%a %d/%m %H:%M") }} – {{ b.fim.strftime("%H:%M") }} ({{ b.estado }}){% endfor %}
{% else %}
- Sem bloqueios nas próximas 48h. Disponibilidade total.
{% endif %}

# Turno

- turno_id: `{{ turno_id }}` (use exatamente este valor ao chamar tools de escrita).
```

Coordenador resolve cada variável via queries específicas (ver `07 §2`).

## 6. RunnableConfig e tools

Tools recebem o contexto via `langchain_core.runnables.RunnableConfig`. Padrão:

```python
from typing import Annotated
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langchain_core.runnables import RunnableConfig

@tool
async def consultar_agenda(
    data_inicio: str,
    data_fim: str,
    config: RunnableConfig,
) -> str:
    """Consulta bloqueios da modelo em janela. Datas no formato YYYY-MM-DD."""
    pool = config["configurable"]["db_pool"]
    modelo_id = config["configurable"]["modelo_id"]
    # ... query e retorno
```

**Campos em `config["configurable"]`** (preenchidos pelo coordenador):

| Chave | Tipo | Uso |
|-------|------|-----|
| `thread_id` | `str` | Convenção LangGraph; igual a `conversa_id` |
| `atendimento_id` | `str` | UUID do atendimento corrente |
| `modelo_id` | `str` | UUID da modelo |
| `cliente_id` | `str` | UUID do cliente |
| `conversa_id` | `str` | redundante com thread_id; conveniência |
| `turno_id` | `str` | UUID7 gerado pelo coordenador para idempotência |
| `db_pool` | `AsyncConnectionPool` | Pool psycopg |
| `redis` | `Redis` | Cliente redis para tools que precisam (raro) |

**Não passar** dados gordos (atendimento dict, persona) via config — re-leitura é barata e mantém referência única no DB.

## 7. Ciclo de vida de um turno

Sequência canônica do coordenador (`workers/coordenador.py:processar_turno`):

```
1. Despertar (ARQ delay = janela debounce)
   ├─ debounce já naturalmente coalesce: jobs com mesmo job_id substituem o anterior
   └─ ao despertar, qualquer mensagem que tenha chegado entre enfileiramento e agora já está em DB

2. Adquirir lock Redis SETNX `lock:conv:{conversa_id}` (TTL 60s)
   ├─ se ocupado: APPEND em `pending:conv:{conversa_id}` e encerra
   └─ se livre: prossegue + inicia heartbeat task (EXPIRE +60s a cada 15s)

3. Resolver atendimento (transação curta)
   ├─ SELECT atendimento aberto para (cliente_id, modelo_id) ∉ {Fechado, Perdido}
   ├─ se não houver: INSERT em estado=Novo
   └─ UPDATE mensagens SET atendimento_id = ? WHERE conversa_id = ? AND atendimento_id IS NULL

4. Verificar gates de pausa
   ├─ se atendimento.ia_pausada=true: log e encerra (sem invocar grafo)
   └─ se há áudio pendente E aguardar_transcricao=true:
        BLPOP redis canal `transcricao:{atendimento_id}` (timeout 8s)
        se timeout: prossegue; mensagens com tipo=audio e conteudo='' viram placeholder

5. Montar contexto e invocar grafo
   ├─ carregar persona + faqs + programas (com cache em memória do worker)
   ├─ carregar últimas 20 mensagens
   ├─ montar SystemMessages (4 estáticos + 1 dinâmico)
   ├─ build entrada = SystemMessages + HumanMessages/AIMessages/SystemMessages traduzidas
   └─ graph.ainvoke(entrada, config={"configurable": {...}, "recursion_limit": 25})
        # recursion_limit = 2 * iter_max + 5 (segurança); iter_max=10 → 25

6. Tratar saída
   a) RecursionError ou timeout LLM → escalar_por_exaustao() e encerrar
   b) refetch atendimento; se ia_pausada=true (escalada via tool): log e encerrar
   c) caso normal: extrair último AIMessage do State; parse mídias anexadas; despachar humanização

7. Despachar humanização
   ├─ split do texto por \n\n (chunks)
   ├─ para cada chunk: enqueue enviar_chunk(conversa_id, turno_id, chunk_idx, texto)
   └─ para cada midia_id na resposta: enqueue enviar_midia(conversa_id, turno_id, midia_idx, midia_id)

8. Liberar lock e drenar pending
   ├─ DEL lock:conv:{conversa_id}
   └─ se LLEN pending:conv:{conversa_id} > 0:
        re-enfileira processar_turno (sem delay) e LTRIM
```

## 8. Cancelamento e idempotência

### 8.1 Cancel-on-new-message

Cliente envia nova mensagem enquanto IA ainda está enviando chunks anteriores:

1. Webhook persiste nova mensagem e re-enfileira `processar_turno` com mesmo `_job_id=turno:{conversa_id}`.
2. ARQ não permite jobs duplicados pelo mesmo job_id; `_defer_by` reinicia janela de debounce.
3. Quando coordenador acordar do novo job, primeira ação é **invalidar dedupe keys de chunks pendentes do turno anterior**:

```python
# Antes de adquirir o lock
turno_anterior = await redis.get(f"turno_atual:{conversa_id}")
if turno_anterior:
    # marca todos os chunks/mídias do turno anterior como "cancelados"
    await redis.delete(f"chunks_pendentes:{turno_anterior}")
    # workers de envio checam essa key antes de enviar e abortam se ausente
```

Detalhes do protocolo de cancelamento em `05 §3`.

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
| Múltiplos workers ARQ tentam mesmo conversa_id | Lock SETNX serializa; perdedor acumula em `pending:conv:{...}` |
| Conversa com mais de 20 turnos sem reset | Sliding window corta; checkpoint LangGraph cresce mas não entra no prompt |

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
