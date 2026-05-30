# 04 — Catálogo de Tools

> Contratos completos das 5 tools do P0 (1 leitura + 4 escrita): consulta de agenda, extração, escrita operacional. Inclui Pydantic schemas, idempotência e comportamento de borda.

## 1. Visão geral

| Tool | Tipo | Idempotência | Quem chama | Efeito colateral |
|------|------|--------------|------------|-------------------|
| `consultar_agenda` | leitura | n/a | IA | nenhum |
| `registrar_extracao` | escrita | UPSERT por `(turno_id, "registrar_extracao", 0)` | IA, 1x por turno | atualiza `atendimentos.*` + transição de estado se aplicável |
| `pedir_pix_deslocamento` | escrita | UPSERT por `(turno_id, "pedir_pix_deslocamento", 0)` | IA | `pix_status='aguardando'`, atendimento → `Aguardando_confirmacao`, cria bloqueio prévio do slot; humanização anexa a chave Pix |
| `enviar_midia` | escrita | UPSERT por `(turno_id, "enviar_midia", call_idx)` (`call_idx` = contador por-invocação, `§3.3`) | IA, várias por turno | anexa mídia (por tag, rotação no sistema) à resposta do turno; sem efeito imediato no DB |
| `escalar` | escrita | UPSERT por `(turno_id, "escalar", 0)` | IA, 1x por turno | abre handoff, `ia_pausada=true`, card no grupo |

Todas as tools são **`async`** e recebem `runtime: ToolRuntime[ContextAgente]` (de `langgraph.prebuilt`). Acessam `db_pool`, `redis` e os IDs de escopo (`modelo_id`, `atendimento_id`, `cliente_id`, `turno_id`) por `runtime.context` **tipado** — não pelo dict `config["configurable"]`, que é o padrão **legado** no LangGraph 1.x (`§1.1`). `ToolRuntime` também expõe `runtime.config` (`RunnableConfig`), `runtime.state` e `runtime.tool_call_id` quando preciso.

> **Escopo — o que NÃO é tool e por quê (grilling 2026-05-23).** Uma tool de leitura só existe se entrega algo que o contexto já injetado por turno não tem; senão é round-trip do loop desperdiçado (e `exaustao_iteracoes` é motivo de escalada). Por isso o P0 tem **só `consultar_agenda`** de leitura:
> - `pix_status`, dados do cliente (nome, recorrente, último motivo de perda, observações **e resumo dos atendimentos anteriores**) e a FAQ inteira **já vêm no prompt** (BP4 e BP2; `02 §5` / `03 §3.2`) — não há `consultar_pix_status`, `consultar_cliente` nem `consultar_faq`.
> - O envio de mídia foi colapsado em `enviar_midia(tag)` com rotação no sistema — não há `consultar_midia` nem `midia_id` exposto ao LLM (`§3.3`).
> - O pin de endereço do fluxo interno é **side-effect determinístico** da transição, não tool (`§3.1`): um pin é estruturado e não-textável pela IA, então o sistema o despacha de qualquer forma.

### 1.1 Acesso a dependências: `ToolRuntime` + `ContextAgente` (não `config.configurable`)

As dependências de run (`db_pool`, `redis`) e os IDs de escopo entram via **Runtime context API** (LangGraph ≥ v0.6; idiomático no 1.x). Definir um `ContextAgente` tipado e injetá-lo na compilação/invocação do grafo:

```python
# api/src/barra/agente/contexto.py
from dataclasses import dataclass
from psycopg_pool import AsyncConnectionPool
from arq import ArqRedis

@dataclass
class ContextAgente:
    """Run dependencies + IDs de escopo. Estáticos DENTRO de um turno (uma ainvoke).
    Injetados em graph.ainvoke(state, context=ContextAgente(...)) pelo coordenador."""
    db_pool: AsyncConnectionPool
    redis: ArqRedis
    modelo_id: str
    atendimento_id: str
    cliente_id: str
    turno_id: str
```

```python
# graph.py — declara o schema do context no StateGraph
builder = StateGraph(EstadoAgente, context_schema=ContextAgente)
...
# coordenador — injeta as deps por turno (não mais em config["configurable"])
await graph.ainvoke(state, context=ContextAgente(db_pool=pool, redis=arq, ...))
```

Nas tools, `runtime: ToolRuntime[ContextAgente]` é injetado automaticamente pelo `ToolNode` (não aparece no schema enviado ao LLM) e dá acesso **tipado**: `runtime.context.db_pool`, `runtime.context.turno_id`, etc.

**Por que migrar (verificado no SDK instalado):** `config["configurable"]["db_pool"]` é o padrão **legado** no LangGraph 1.x — `langgraph/runtime.py` documenta a migração `configurable → context`, e o pacote instalado (`langgraph 1.1.10` / `langgraph-prebuilt 1.0.12`) já expõe `Runtime`/`ToolRuntime`. Além de tipado, evita o **bug de serialização** que `configurable` causa ao ligar checkpointer (relevante no P1, quando o checkpointer voltar; `01 §6.7`).

**Aplicado em todo o agente (2026-05-23):** `agente/contexto.py` (define `ContextAgente`), `graph.py` (`context_schema=ContextAgente`), `estado.py` (docstring), `02-estado-fluxo.md §6`, `01-arquitetura.md §2.3` e os 5 nós (`Runtime[ContextAgente]`) + 5 tools (`ToolRuntime[ContextAgente]`). O único uso remanescente de `config["configurable"]` é o `thread_id` (= `conversa_id`), nativo do checkpointer — não é dep de runtime (`02 §6`). Nunca pôr pool/redis em `configurable`: o checkpointer o serializa e quebra (`TypeError`, langgraph#3441).

## 2. Tools de leitura

### 2.1 `consultar_agenda(data_inicio, data_fim)`

```python
# api/src/barra/agente/ferramentas/leitura.py
from datetime import date
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from .contexto import ContextAgente  # @dataclass com db_pool/redis/IDs (§1.1)

@tool
async def consultar_agenda(
    data_inicio: str,
    data_fim: str,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Consulta os bloqueios (horários OCUPADOS) da modelo entre data_inicio e data_fim.

    As próximas 48h já estão no contexto do turno (BP4, `02 §5`) — use esta tool
    APENAS para janelas além disso (ex.: "tem horário sábado que vem?").

    Args:
        data_inicio: data inicial inclusiva, formato YYYY-MM-DD.
        data_fim: data final inclusiva, formato YYYY-MM-DD. Máximo 14 dias após data_inicio.

    Returns:
        Markdown com os bloqueios ativos no período (o que NÃO está listado está livre).
    """
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    di = date.fromisoformat(data_inicio)
    df = date.fromisoformat(data_fim)
    if (df - di).days > 14:
        return "ERRO: janela máxima é 14 dias. Refine sua consulta."

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT inicio, fim, estado
              FROM barravips.bloqueios
             WHERE modelo_id = %s
               AND estado IN ('bloqueado', 'em_atendimento')
               AND inicio::date BETWEEN %s AND %s
             ORDER BY inicio
            """,
            (modelo_id, di, df),
        )
        rows = await res.fetchall()
    if not rows:
        return f"Sem bloqueios entre {di} e {df}. Disponibilidade total."
    linhas = [f"- {r['inicio']:%a %d/%m %H:%M} – {r['fim']:%H:%M} ({r['estado']})" for r in rows]
    return "Bloqueios:\n" + "\n".join(linhas)
```

**Observações:**
- IA sempre escreve datas absolutas (`2026-05-04`), nunca relativas (`amanhã`). Coordenador inclui no contexto dinâmico a data atual para evitar erro.
- Limite 14 dias evita ataques de janela infinita.

### 2.2 Tools de leitura removidas (decisão grilling 2026-05-23)

`consultar_agenda` é a **única** tool de leitura do P0. As outras quatro foram removidas porque o dado já chega no prompt todo turno — manter a tool seria round-trip do loop desperdiçado.

| Removida | Onde o dado vive agora |
|----------|------------------------|
| `consultar_cliente` | BP4 (`02 §5`): nome, recorrente, último motivo de perda, observações **+ resumo dos atendimentos anteriores** (`Fechado`/`Perdido`+valor). O resumo é a única coisa que a tool dava a mais; foi dobrado no BP4 porque `recorrente` (booleano) não distingue quem fechou 3x de quem perdeu 3x. Isolamento por par `(cliente, modelo)` é preservado — o BP4 já é escopado assim. |
| `consultar_faq` | Arquivo de prompt versionado `agente/prompts/faq.md` renderizado inteiro no BP2 (`03 §3.2`). A tabela `barravips.modelo_faq` foi dropada em `0030_remove_modelo_faq.sql`. Pergunta fora da FAQ que exija política nova → `escalar(motivo="politica_nova_necessaria")`. |
| `consultar_pix_status` | BP4 injeta `pix_status` todo turno; dentro de um turno esse valor é autoritativo (validação do comprovante roda em worker/pipeline ENTRE turnos, `01 §6.1`). |
| `consultar_midia` | Colapsada em `enviar_midia(tag)` — o sistema escolhe a mídia por rotação, então a IA nunca precisa listar nem manipular `midia_id` (`§3.3`). |

## 3. Tools de escrita

Todas escrevem em `barravips.tool_calls` para idempotência (schema em `02 §8.2`). Padrão:

```python
async def _executar_idempotente(
    conn,
    turno_id: str,
    tool_name: str,
    call_idx: int,
    payload: dict,
    executor,  # async fn(conn, payload) -> resultado
) -> dict:
    async with conn.transaction():
        # tenta inserir; se já existir, retorna resultado anterior
        res = await conn.execute(
            """
            INSERT INTO barravips.tool_calls (turno_id, tool_name, call_idx, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (turno_id, tool_name, call_idx) DO NOTHING
            RETURNING (SELECT NULL::jsonb)
            """,
            (turno_id, tool_name, call_idx, payload),
        )
        if (await res.fetchone()) is None:
            # já existe — retorna resultado anterior
            res = await conn.execute(
                "SELECT resultado FROM barravips.tool_calls WHERE turno_id=%s AND tool_name=%s AND call_idx=%s",
                (turno_id, tool_name, call_idx),
            )
            return (await res.fetchone())["resultado"]

        resultado = await executor(conn, payload)

        await conn.execute(
            "UPDATE barravips.tool_calls SET resultado=%s WHERE turno_id=%s AND tool_name=%s AND call_idx=%s",
            (resultado, turno_id, tool_name, call_idx),
        )
        return resultado
```

Helper vive em `agente/ferramentas/_idempotencia.py`.

### 3.1 `registrar_extracao(...)`

```python
# api/src/barra/agente/ferramentas/extracao.py
from typing import Literal
from datetime import date, time
from decimal import Decimal
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from .contexto import ContextAgente  # §1.1

class ExtracaoPayload(BaseModel):
    """Snapshot estruturado do que a IA aprendeu nesta conversa.

    Todos os campos opcionais — registre o que está claro; deixe NULL o que ainda não.
    Coordenador faz UPSERT: campos não-nulos sobrescrevem; campos nulos preservam o anterior.
    """
    intencao: Literal["curiosidade", "cotacao", "agendamento"] | None = None
    urgencia: Literal["imediato", "agendado", "indefinido", "estimado"] | None = None
    tipo_atendimento: Literal["interno", "externo"] | None = None
    data_desejada: date | None = None
    horario_desejado: time | None = None
    duracao_horas: Decimal | None = Field(None, ge=0, le=48)
    endereco: str | None = None
    bairro: str | None = None
    tipo_local: Literal["hotel", "casa", "apartamento", "outro"] | None = None
    forma_pagamento: Literal["pix", "dinheiro", "outro"] | None = None
    valor_acordado: Decimal | None = Field(None, ge=0)
    sinais_qualificacao: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Sinais bool {informa_horario, informa_local, aceita_valor, envia_pix, "
            "responde_objetivamente}. Inclua só os True."
        ),
    )
    motivo_perda_candidato: Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] | None = None
    limpar: list[str] = Field(
        default_factory=list,
        description=(
            "Campos a ZERAR (NULL) quando o cliente RECUA/desmarca — ex.: disse um horário "
            "e depois 'não sei o dia ainda'. Nomes dos campos acima (ex.: "
            "['data_desejada','horario_desejado']). Só o que o cliente retratou; tem precedência sobre o payload."
        ),
    )
    proxima_acao_esperada: str = Field(min_length=3, max_length=240)


@tool
async def registrar_extracao(
    payload: ExtracaoPayload,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Registre o snapshot do que aprendeu nesta conversa. Chame UMA vez por turno, perto do fim.

    Esta tool dispara transições de estado:
    - intencao=curiosidade/cotacao/agendamento + estado=Novo → Triagem
    - intencao=agendamento + dados mínimos (horario_desejado, tipo_atendimento) + estado=Triagem → Qualificado
    - tipo_atendimento=interno + horario_desejado + estado=Qualificado → Aguardando_confirmacao
      (cria bloqueio prévio E dispara o pin de endereço — side-effect, não tool; ver Notas)
    - externo NÃO é promovido aqui: só pedir_pix_deslocamento leva externo a Aguardando_confirmacao
      (invariante "externo em Aguardando_confirmacao ⟹ Pix solicitado"; ver 01 §6.1)

    O campo proxima_acao_esperada (obrigatório) é exibido no painel para Fernando.
    Use `limpar` para ZERAR campos que o cliente retratou (ex.: desmarcou o horário) —
    o snapshot é incremental (COALESCE), então sem `limpar` um valor antigo nunca some.
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id

    async with pool.connection() as conn:
        resultado = await _executar_idempotente(
            conn, turno_id, "registrar_extracao", 0,
            payload=payload.model_dump(mode="json"),
            executor=lambda c, p: _aplicar_extracao(c, atendimento_id, p),
        )
    # pin de endereço do fluxo interno: enfileirado APÓS o commit (simétrico ao card do escalar).
    # Re-disparo em replay é inofensivo — o worker do pin é idempotente por atendimento_id.
    if resultado.get("enviar_pin"):
        arq = runtime.context.redis  # ArqRedis: enqueue_job (05 §6)
        await arq.enqueue_job(
            "enviar_card", tipo="loc_pin", atendimento_id=atendimento_id,
            _job_id=f"card:loc_pin:{atendimento_id}",
        )
    return resultado["mensagem"]


async def _aplicar_extracao(conn, atendimento_id: str, payload: dict) -> dict:
    """Faz UPSERT em atendimentos e dispara transição de estado."""
    # branch 12 (grilling): reagendar horário de atendimento que JÁ tem bloqueio prévio
    # não sobrescreve — escala para a modelo (slot reservado, ela realoca). Antes do bloqueio,
    # o COALESCE abaixo sobrescreve o horário livremente.
    if await _reagendamento_pos_bloqueio(conn, atendimento_id, payload):
        from barra.dominio.escaladas.service import abrir_handoff
        await abrir_handoff(conn, atendimento_id=UUID(atendimento_id),
                            motivo="reagendamento_pos_bloqueio",  # responsavel derivado → modelo
                            resumo_operacional="Cliente quer mudar horário já reservado.",
                            acao_esperada="Realocar o bloqueio ou recusar.",
                            origem="agente", autor="IA")
        return {"mensagem": "Reagendamento pós-bloqueio escalado para a modelo."}

    # 1. UPDATE com COALESCE — só sobrescreve campos não-nulos.
    #    Campos em `limpar` (branch 18) são forçados a NULL e têm PRECEDÊNCIA sobre o payload
    #    (cliente recuou — ex.: desmarcou data/horário). COALESCE sozinho não zera.
    limpar = set(payload.get("limpar", []))
    sets = []
    valores = []
    for campo in ("intencao", "urgencia", "tipo_atendimento", "data_desejada",
                  "horario_desejado", "duracao_horas", "endereco", "bairro",
                  "tipo_local", "forma_pagamento", "valor_acordado",
                  "motivo_perda_candidato", "proxima_acao_esperada"):
        if campo in limpar:
            sets.append(f"{campo} = NULL")
        elif payload.get(campo) is not None:
            sets.append(f"{campo} = %s")
            valores.append(payload[campo])
    if payload.get("sinais_qualificacao"):
        sets.append("sinais_qualificacao = sinais_qualificacao || %s::jsonb")
        valores.append(json.dumps(payload["sinais_qualificacao"]))

    if not sets:
        return {"mensagem": "Nenhum campo novo para registrar."}

    valores.append(atendimento_id)
    await conn.execute(
        f"UPDATE barravips.atendimentos SET {', '.join(sets)}, fonte_decisao_ultima_transicao='extracao_ia' WHERE id = %s",
        valores,
    )

    # 2. transição de estado conforme regras
    resultado_extra: dict = {}
    novo_estado = await _decidir_transicao(conn, atendimento_id)
    if novo_estado:
        await conn.execute(
            "UPDATE barravips.atendimentos SET estado = %s WHERE id = %s",
            (novo_estado, atendimento_id),
        )
        await _evento(conn, atendimento_id, "transicao_estado",
                      origem="agente", autor="IA",
                      payload={"para": novo_estado})
        # se interno + horário definido → cria bloqueio prévio (mvp/04 §2.1)
        if novo_estado == "Aguardando_confirmacao":
            atendimento = await _refetch(conn, atendimento_id)
            if atendimento["tipo_atendimento"] == "interno":
                # branch 13: advisory lock por (modelo, slot) + EXCLUDE de backstop.
                # Conflito (slot tomado por outra conversa) → ConflitoAgenda → rollback do
                # turno; a tool retorna erro recuperável e a IA re-oferta outro horário.
                await _criar_bloqueio_previo(conn, atendimento)
                # pin de endereço (interno): side-effect determinístico desta transição,
                # NÃO tool. Sinaliza p/ o wrapper enfileirar após o commit (ver Notas).
                resultado_extra["enviar_pin"] = True

    await _evento(conn, atendimento_id, "extracao_registrada",
                  origem="agente", autor="IA",
                  payload=payload)
    return {"mensagem": "Extração registrada.", "novo_estado": novo_estado, **resultado_extra}


async def _decidir_transicao(conn, atendimento_id: str) -> str | None:
    """Aplica as transições de extração. Visão consolidada do lado do agente: 02 §11
    (fonte única; mvp/04 §8.2 é a canônica de produto, com divergências em 01 §6)."""
    res = await conn.execute(
        "SELECT estado, intencao, tipo_atendimento, horario_desejado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a["estado"] == "Novo" and a["intencao"] is not None:
        return "Triagem"
    if a["estado"] == "Triagem" and a["intencao"] == "agendamento" \
            and a["horario_desejado"] is not None and a["tipo_atendimento"] is not None:
        return "Qualificado"
    if a["estado"] == "Qualificado" and a["tipo_atendimento"] == "interno" \
            and a["horario_desejado"] is not None:
        return "Aguardando_confirmacao"  # interno: bloqueio prévio criado em _aplicar_extracao
    # externo NÃO é promovido por extração — só pedir_pix_deslocamento promove
    # (invariante: externo em Aguardando_confirmacao ⟹ Pix solicitado; ver 01 §6.1, 06 §2)
    return None
```

**Notas:**
- **Mover `_aplicar_extracao` e `_decidir_transicao` para `dominio/atendimentos/service.py:registrar_extracao_ia(conn, atendimento_id, payload)`.** A tool em `agente/ferramentas/extracao.py` fica como wrapper de ~10 linhas que chama o serviço de domínio **na mesma transação** (snapshot + transição + bloqueio são atômicos — o advisory lock + EXCLUDE não toleram janela). Justificativa: regra de transição de estado é domain logic, não tool logic — pertence ao mesmo módulo onde os outros estados são manipulados (`aplicar_comando`, `_atualizar_pix`, etc.). O serviço **retorna flags** (ex.: `enviar_pin`); transporte (enqueue_job) fica no wrapper, fora do domínio.
- **Pin de endereço (interno) — side-effect, não tool.** Um pin (`/message/sendLocation`) é estruturado e a IA não consegue expressá-lo como texto, então o sistema o despacha de qualquer forma. O serviço de domínio sinaliza `enviar_pin=True` quando interno entra em `Aguardando_confirmacao`; o wrapper enfileira o job ARQ `enviar_card {tipo: loc_pin}` após o commit (simétrico ao card do `escalar`). Re-disparo em replay é inofensivo (worker idempotente por `atendimento_id`). Para EXTERNO não há pin — cita-se só `localizacao_operacional` (bairro/cidade). Substitui a tool `enviar_localizacao` cogitada no placeholder de `ferramentas/__init__.py`.
- Bloqueio prévio (interno) é criado em `_criar_bloqueio_previo`; reaproveita `dominio/agenda/service.py`. **Branch 13 (escalável/edge-case):** `_criar_bloqueio_previo` toma `pg_advisory_xact_lock` por `(modelo_id, slot)` e conta com a EXCLUDE constraint da tabela `bloqueios` como backstop duro; em sobreposição levanta `ConflitoAgenda` → a tool reverte o turno e retorna erro recuperável para a IA re-ofertar (escala só se não resolver). Serializa booking entre conversas distintas da mesma modelo.
- **Branch 12 (reagendamento pós-bloqueio):** se o cliente muda o horário de um atendimento já em `Aguardando_confirmacao` com bloqueio, `_aplicar_extracao` escala para a modelo (`reagendamento_pos_bloqueio`) em vez de sobrescrever o horário e deixar o bloqueio órfão.
- **Guarda do piso de desconto (ADR-0004).** Quando o payload traz `valor_acordado` **abaixo do piso** (`preço de tabela do programa × (1 − settings.desconto_max_pct)`), `registrar_extracao_ia` **não grava o valor** e abre `escalar(motivo="fora_de_oferta")` — defesa-em-profundidade sobre a regra do prompt (`03 §3.1 <desconto>`), que o LLM pode ignorar. O preço de tabela vem de `modelo_programas` pela duração acordada; sem programa correspondente, trata como abaixo do piso (escala). Com `desconto_max_pct=0` o piso é o próprio valor de tabela (qualquer abatimento escala). A regra do percentual vive no prompt geral; o valor mínimo nunca é exposto ao LLM.
- **`input_examples` (avaliar nas evals `08`, cruzamento 2026-05-24).** A doc oficial recomenda o campo opcional `input_examples` para tools com nested/format-sensitive params — `registrar_extracao` (~15 campos, `sinais_qualificacao`, `limpar`) e `escalar` são o alvo exato. Custo ~100-200 tokens/exemplo, pagos 1x no prefixo cacheado (entra na tool definition, então precisa ser tão estável quanto o resto). Pré-req: confirmar que `langchain-anthropic` propaga `input_examples` (mesma pendência do `strict`, `§7`); cada exemplo deve validar contra o `input_schema` (senão a API retorna 400). Tratar como ajuste fino, não bloqueador.

### 3.2 `pedir_pix_deslocamento()`

```python
# api/src/barra/agente/ferramentas/pix.py
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from .contexto import ContextAgente  # §1.1

@tool
async def pedir_pix_deslocamento(runtime: ToolRuntime[ContextAgente]) -> str:
    """Solicita Pix de R$100 para deslocamento (saída externa).

    Sem parâmetros — valor é fixo R$100 (MVP), chave/titular vêm do cadastro da modelo.
    Após chamada: pix_status=aguardando, atendimento → Aguardando_confirmacao,
    cria bloqueio prévio do horário (reserva o slot). A humanização ANEXA a
    chave/titular/valor exatos à sua mensagem — você NÃO redigita a chave (string crítico).

    Escreva só o pedido no seu tom ("pra garantir teu horário, manda o pixzinho do deslocamento").
    Use APENAS para atendimento externo após acordar horário e endereço.
    Use APENAS UMA vez por atendimento (segunda chamada é idempotente, não duplica mensagem).
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    modelo_id = runtime.context.modelo_id
    turno_id = runtime.context.turno_id

    async with pool.connection() as conn:
        # busca chave/titular da modelo
        res = await conn.execute(
            "SELECT chave_pix, titular_chave FROM barravips.modelos WHERE id = %s",
            (modelo_id,),
        )
        m = await res.fetchone()
        if not m["chave_pix"] or not m["titular_chave"]:
            return "ERRO: modelo não tem chave Pix cadastrada. Escale para Fernando."

        resultado = await _executar_idempotente(
            conn, turno_id, "pedir_pix_deslocamento", 0,
            payload={"valor": 100, "chave": m["chave_pix"], "titular": m["titular_chave"]},
            executor=lambda c, p: _aplicar_pedido_pix(c, atendimento_id, p),
        )
    # Retorno NÃO inclui a chave — a humanização a anexa deterministicamente após o texto da IA.
    # Guia o LLM a escrever só o pedido em persona, sem redigitar o string crítico.
    return (
        "Pix de R$ 100 solicitado e slot reservado. Escreva o pedido no seu tom, "
        "SEM digitar a chave — o sistema anexa chave/titular/valor exatos após sua mensagem."
    )


async def _aplicar_pedido_pix(conn, atendimento_id: str, payload: dict) -> dict:
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET pix_status = 'aguardando',
               estado = 'Aguardando_confirmacao',
               fonte_decisao_ultima_transicao = 'extracao_ia'
         WHERE id = %s AND pix_status = 'nao_solicitado'
        """,
        (atendimento_id,),
    )
    # bloqueio prévio do externo nasce AQUI (simétrico ao interno em registrar_extracao):
    # reserva o slot ao entrar em Aguardando_confirmacao e fecha a janela de double-booking.
    # O timeout de 24h cancela o bloqueio se o Pix nunca vier (07 §4).
    atendimento = await _refetch(conn, atendimento_id)
    # branch 13: advisory lock + EXCLUDE backstop; conflito levanta ConflitoAgenda → rollback de
    # TODO o turno (pix_status volta a nao_solicitado), e a tool retorna erro recuperável p/ re-ofertar.
    await _criar_bloqueio_previo(conn, atendimento)  # reusa dominio/agenda/service
    await _evento(conn, atendimento_id, "pix_solicitado", origem="agente", autor="IA", payload=payload)
    return {"mensagem": "Pix solicitado."}
```

**Observação importante:** a tool **não chama Evolution** — apenas atualiza estado e retorna texto guia. A IA escreve o pedido em persona; a **humanização anexa a chave/titular/valor exatos** (lidos do payload persistido em `tool_calls`) como bloco copia-e-cola após o texto. Assim o string crítico nunca passa pelo LLM (zero risco de mangle numa chave aleatória de 32+ chars) e a tool segue desacoplada do Evolution. Ver `05` (humanização).

### 3.3 `enviar_midia(tag, legenda?)`

A IA **não escolhe foto específica nem manipula `midia_id`** — pede por **tag** e o sistema escolhe qual foto enviar (rotação: menos-recente-enviada), evitando repetir. Isso colapsa o antigo par `consultar_midia`+`enviar_midia(midia_id)` numa tool só e elimina toda a classe de bug de transcrição de UUID.

```python
# api/src/barra/agente/ferramentas/midia.py
from typing import Annotated, Literal
from langchain_core.tools import tool, InjectedToolArg
from langgraph.prebuilt import ToolRuntime

from .contexto import ContextAgente  # §1.1

TagMidia = Literal["apresentacao", "corpo", "lifestyle", "evento"]

@tool
async def enviar_midia(
    tag: TagMidia,
    legenda: str | None = None,
    tipo: Literal["foto", "video"] = "foto",
    # call_idx é INJETADO pelo tools_node (índice ordinal por-invocação), NÃO é param do LLM.
    # Permanece InjectedToolArg mesmo com ToolRuntime — ver Nota call_idx abaixo.
    call_idx: Annotated[int, InjectedToolArg] = 0,
    runtime: ToolRuntime[ContextAgente] | None = None,
) -> str:
    """Anexa uma foto pré-aprovada da modelo (escolhida pelo sistema) à resposta do turno.

    Args:
        tag: categoria da foto. O sistema escolhe QUAL foto da tag (rotação:
             menos-recente-enviada), evitando repetir — você não escolhe foto específica.
        legenda: opcional, texto curto que aparece junto da mídia no WhatsApp.
        tipo: "foto" (default) ou "video". Mande fotos primeiro; use "video" depois,
              apresentando-o como exclusivo/ao vivo na legenda (estratégia foto→vídeo, 05 §5).
              Vídeo vai como visualização única quando a plataforma suportar (pré-req, 05 §5).

    Pode ser chamada várias vezes no mesmo turno (ex.: 2 fotos da mesma tag);
    as mídias são enviadas após o texto.
    """
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    turno_id = runtime.context.turno_id

    async with pool.connection() as conn:
        # sistema escolhe: menos-recente-enviada da tag, excluindo as já anexadas neste turno.
        ja_no_turno = await _midias_do_turno(conn, turno_id)  # ids já em tool_calls do turno
        res = await conn.execute(
            """
            SELECT id, object_key
              FROM barravips.modelo_midia
             WHERE modelo_id = %s AND tag = %s AND tipo = %s AND aprovada = true
               AND NOT (id = ANY(%s))
             ORDER BY ultimo_envio_em NULLS FIRST, created_at
             LIMIT 1
            """,
            (modelo_id, tag, tipo, ja_no_turno),
        )
        m = await res.fetchone()
        if not m:
            return f"ERRO: nenhuma mídia tipo '{tipo}' disponível para a tag '{tag}'."

        # call_idx é o contador POR-INVOCAÇÃO (vem do tools_node, reset a cada ainvoke).
        # No replay reinicia em 0 → ON CONFLICT deduplica → NÃO reenvia. Jamais COUNT(*) no DB
        # (no replay COUNT(*) geraria idx novos sobre as linhas persistidas → envio duplicado).
        await _executar_idempotente(
            conn, turno_id, "enviar_midia", call_idx,
            payload={"midia_id": str(m["id"]), "tag": tag, "tipo": tipo, "legenda": legenda or ""},
            executor=lambda c, p: _registrar_envio_midia(c, p),  # grava + marca ultimo_envio_em=now()
        )

    return f"{tipo.capitalize()} de '{tag}' anexada (enviada após o texto)."
```

**Notas:**
- **`call_idx` determinístico (branch grilling 2026-05-23).** O `tools_node` (`nos/tools.py`) mantém um contador por-invocação em `EstadoAgente.midia_idx` (`02 §6`), inicializado em 0 a cada `ainvoke` (não há checkpointer) e incrementado a cada `enviar_midia`, injetado via `InjectedToolArg`. Como o State nasce do zero no replay, o contador reinicia em 0 e o `ON CONFLICT` deduplica — sem reenvio. A seleção da foto roda antes do `_executar_idempotente`; no replay o `ON CONFLICT` devolve o `payload` cacheado (mesma foto), então a re-seleção é descartada — replay-safe. O "unordered" da doc oficial refere-se à *execução* (não assumir que uma chamada terminou antes da outra), **não** à posição no array de `content`: o `tools_node` indexa `call_idx` pela ordem dos `tool_use` blocks na resposta, que é estável — a indexação ordinal não conflita com a semântica de paralelo.
- **Por que `call_idx` NÃO migra para `ToolRuntime` (nuance da migração §1.1).** `ToolRuntime` dá `tool_call_id` e `state`, mas nenhum serve como índice ordinal replay-safe: `tool_call_id` é gerado pela API e **muda no replay** (quebraria a PK de `tool_calls`); `runtime.state["midia_idx"]` carrega o **mesmo valor** para todas as chamadas de `enviar_midia` do mesmo turno (o State só consolida no fim do nó) → colisão de `call_idx`. O índice ordinal por ordem de chamada — injetado pelo `tools_node` via `InjectedToolArg` — é a única fonte determinística. As **demais** deps (`db_pool`, `modelo_id`, `turno_id`) migram para `runtime.context`; só `call_idx` continua `InjectedToolArg`.
- **Schema:** rotação por menos-recente exige `barravips.modelo_midia.ultimo_envio_em timestamptz` (marcada em `_registrar_envio_midia`). Substitui a migration `0013_modelo_midia_descricao.sql` do roteiro — `descricao` deixou de ser necessária (a IA não escolhe mais por descrição). Atualizar `09`.

Coordenador, ao processar a resposta final, lê `tool_calls` do `turno_id` para a lista de fotos a despachar (o `midia_id` resolvido já está no payload):

```sql
SELECT payload->>'midia_id' AS midia_id, payload->>'legenda' AS legenda
  FROM barravips.tool_calls
 WHERE turno_id = %s AND tool_name = 'enviar_midia'
 ORDER BY call_idx;
```

### 3.4 `escalar(motivo, resumo_operacional, acao_esperada)`

`responsavel` (Fernando | modelo) **não é param** — é derivado de `motivo` em `dominio/escaladas/service.py` (tabela `RESP[motivo]`, `outro`→Fernando). `motivo` já é a chave única de roteamento **e** do bucket de métrica (`§3.6`); expor `responsavel` ao LLM só criaria um campo contradizível (que já era sobrescrito para a família AUP).

```python
# api/src/barra/agente/ferramentas/escalada.py
from typing import Literal
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from .contexto import ContextAgente  # §1.1

class EscaladaPayload(BaseModel):
    # responsavel NÃO entra aqui — derivado de motivo no serviço de domínio.
    motivo: Literal[
        # Operacionais
        "fora_de_oferta",
        "horario_indisponivel",
        "reagendamento_pos_bloqueio",
        "politica_nova_necessaria",
        "exaustao_iteracoes",
        "timeout_grafo",
        "modelo_recusou",   # stop_reason="refusal" do Sonnet (filtro de safety). Sistema-emitido
                            # via escalar_por_exaustao, nunca escolhido pelo LLM (ele recusou). Ver 03 §6.3.
        # AUP / persona / jailbreak (cf. 10-persona-jailbreak.md)
        "disclosure_insistente",
        "disclosure_explicito",  # LEGADO: modelo nomeado ("vc é Claude?") agora passa por canned+contador
                                 # como o genérico (decisão 2026-05-23) → só disclosure_insistente na 3ª.
                                 # Mantido no enum por compat; não é mais acionado pelo pipeline P0.
        "jailbreak_attempt",
        "pedido_explicito_repetido",
        "prova_humanidade_persistente",
        "cross_modelo_fishing",
        # Genérico (fallback)
        "outro",
    ]
    resumo_operacional: str = Field(min_length=10, max_length=1000)
    acao_esperada: str = Field(min_length=3, max_length=400)


@tool
async def escalar(
    motivo: MotivoEscalada,
    resumo_operacional: str,
    acao_esperada: str,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Escale o atendimento. O destino (Fernando p/ decisão sensível, ou modelo p/ ação
    operacional) é decidido pelo `motivo` — você não escolhe o responsável.

    Após chamar, sua próxima fala virá quando Fernando devolver para você
    explicitamente, ou quando a modelo registrar finalizado pelo grupo. Não
    escreva mais texto nesse turno.

    Args:
        motivo: enum fechado (`MotivoEscalada`, alias do Literal compartilhado com
          `EscaladaPayload` em §3.4). Categorias:
          - operacionais (fora_de_oferta, horario_indisponivel, ...)
          - AUP / persona (disclosure_insistente, jailbreak_attempt, ...)
        resumo_operacional: 1-3 frases descrevendo o que aconteceu na conversa.
                            Para AUP, incluir TEXTO LITERAL da pergunta do cliente.
        acao_esperada: o que Fernando/modelo devem decidir/fazer.

    Parâmetros de topo (não wrapper `payload`, ADR/§7): o corpo reconstrói
    `EscaladaPayload(...)` internamente para revalidar (min/max_length + enum).
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id

    from barra.dominio.escaladas.service import abrir_handoff

    async with pool.connection() as conn:
        resultado = await _executar_idempotente(
            conn, turno_id, "escalar", 0,
            payload=payload.model_dump(),
            executor=lambda c, p: _executar_handoff(c, atendimento_id, p),
        )
    # Enfileira card como JOB ARQ (05 §6) com tipo; despachado direto pelo Evolution (bypass humanização)
    arq = runtime.context.redis  # ArqRedis: enqueue_job
    await arq.enqueue_job(
        "enviar_card",
        tipo="escalada",
        escalada_id=str(resultado["escalada_id"]),
        atendimento_id=atendimento_id,
        _job_id=f"card:escalada:{resultado['escalada_id']}",
    )

    return f"Escalada aberta para {resultado['responsavel']}. Próxima fala virá quando devolverem para você — não escreva mais texto neste turno."


async def _executar_handoff(conn, atendimento_id: str, payload: dict) -> dict:
    """Wraps abrir_handoff e retorna escalada_id + responsavel (derivado do motivo)."""
    from barra.dominio.escaladas.service import abrir_handoff
    await abrir_handoff(
        conn,
        atendimento_id=UUID(atendimento_id),
        # responsavel NÃO é passado — abrir_handoff deriva de motivo (RESP[motivo], outro→Fernando).
        motivo=payload["motivo"],
        resumo_operacional=payload["resumo_operacional"],
        acao_esperada=payload["acao_esperada"],
        origem="agente",
        autor="IA",
    )
    res = await conn.execute(
        "SELECT id, responsavel FROM barravips.escaladas WHERE atendimento_id = %s ORDER BY aberta_em DESC LIMIT 1",
        (atendimento_id,),
    )
    row = await res.fetchone()
    return {"escalada_id": row["id"], "responsavel": row["responsavel"]}
```

**Comportamento crítico:**

1. Tool grava direto via `dominio.escaladas.service.abrir_handoff` — `ia_pausada=true` é setado dentro da transação.
2. Tool retorna mensagem positiva ("Próxima fala virá quando devolverem... — não escreva mais texto neste turno") — guia o LLM, mas não confia só nisso.
3. Após `graph.ainvoke()`, **coordenador refaz fetch do atendimento** e checa `ia_pausada`. Se true, descarta qualquer texto que tenha sido emitido — **mesmo que a IA tenha seguido escrevendo após `escalar` por desobediência**.
4. Card no grupo de Coordenação é enfileirado como **job ARQ** `enviar_card` (com `tipo`, `05 §6`); o worker chama Evolution direto (bypass de humanização — `mvp/05 §2.3`).

### 3.5 Regra de stop após `escalar`

Conforme `mvp/03 §5.3`: "ao chamar `escalar`, parar — não tentar despedir-se nem comentar a escalada".

Reforço em **3 camadas**:
1. **Prompt** (`regras.md.j2`): "Após chamar `escalar`, sua próxima fala virá quando devolverem para você. Não escreva mais texto nesse turno."
2. **Tool retorno**: string indica claramente que turno encerrou.
3. **Coordenador**: refetch + `if atendimento.ia_pausada: descartar texto` (cinto-suspensório).

A camada 3 é a que importa em produção; as outras existem para reduzir tokens desperdiçados. Linguagem na camada 1 trocada de "PARE" (anti-padrão Sonnet 4.6) para forma positiva.

**`escalar` em paralelo com outra tool (edge case, cruzamento 2026-05-24).** A doc oficial nota que tool calls de um turno são *unordered* e podem vir em lote — nada impede o LLM de emitir `escalar` + `registrar_extracao` no mesmo turno. As 3 camadas cobrem o **texto** (camada 3 descarta), mas as outras tool calls do lote **já rodaram**; o estado final ainda fica coerente (`ia_pausada=true`), então é tolerável. Mitigação por prompt (`regras.md`): "só agrupe tool calls independentes entre si" (recomendação literal da doc). **Não** usar `disable_parallel_tool_use` — `enviar_midia` múltipla por turno depende do paralelo (`§3.3`).

### 3.6 Motivos AUP — fluxo distinto

Motivos da família AUP (`disclosure_*`, `jailbreak_attempt`, `pedido_explicito_repetido`, `prova_humanidade_persistente`, `cross_modelo_fishing`) **sempre escalam para Fernando**, nunca para modelo. Card no grupo deve incluir:

- Texto literal da última N=3 mensagens do cliente (para auditoria).
- `motivo` exato.
- Sugestão de ação ("decidir se devolve para IA ou descarta atendimento").

`abrir_handoff` em `dominio/escaladas/service.py` **deriva `responsavel` de `motivo`** (tabela `RESP[motivo]`): AUP-família + `politica_nova_necessaria`/`exaustao_iteracoes`/`timeout_grafo`/`modelo_recusou` → Fernando; `fora_de_oferta`/`horario_indisponivel`/`reagendamento_pos_bloqueio` → modelo; `outro` → Fernando (default seguro). Não há `responsavel` vindo da tool para contradizer (Q10, `§3.4`).

**Bucket de métrica (branch 19, `08 §3.2`):** AUP-família = bucket **defesa** (desejável; spike = ataque); operacionais (`fora_de_oferta`, `horario_indisponivel`, `politica_nova_necessaria`, `reagendamento_pos_bloqueio`, `exaustao_iteracoes`, `timeout_grafo`) = bucket **capacidade** (é o que o gate de qualidade mede). `modelo_recusou` = bucket **defesa** (filtro de safety da API, não falha de capacidade do agente — não deve reprovar o gate de qualidade, mas spike merece investigação no domínio adulto). `abrir_handoff` emite `agente_escalada_total{bucket, motivo}`.

Detalhes em `10-persona-jailbreak.md §2-§4`.

## 4. Registro centralizado das tools

```python
# api/src/barra/agente/ferramentas/__init__.py
from .leitura import consultar_agenda
from .extracao import registrar_extracao
from .pix import pedir_pix_deslocamento
from .midia import enviar_midia
from .escalada import escalar

TOOLS = [
    consultar_agenda,        # leitura (única)
    registrar_extracao,      # escrita
    pedir_pix_deslocamento,
    enviar_midia,
    escalar,
]  # 5 tools P0 (1 leitura + 4 escrita) — grilling 2026-05-23
```

Ordem importa para o LLM (lista chega na ordem em `tools` da request); leitura primeiro, escrita depois — heurística de prompt engineering para favorecer chamadas seguras antes. `TOOLS` é constante de módulo congelada, ordem fixa e byte-idêntica entre todas as modelos (invariante de prefixo do cache, `agente/CLAUDE.md`).

O breakpoint `cache_control: {"type": "ephemeral"}` pousa na **última** tool do array (`escalar`): cacheia todo o prefixo de definições, da primeira tool até ela (configurado no caminho do `bind_tools`, ver `03`). Corolário do invariante, confirmado pela doc oficial: **qualquer** edição em **qualquer** tool invalida o cache **inteiro** (`tools` → `system` → `messages`), não só a parte alterada — por isso a ordem byte-idêntica entre modelos não é cosmética, é o que mantém o cache hit.

## 5. Migration auxiliar para `tool_calls`

```sql
-- infra/sql/0012_tool_calls.sql
CREATE TABLE barravips.tool_calls (
  turno_id    uuid       NOT NULL,
  tool_name   text       NOT NULL,
  call_idx    smallint   NOT NULL,
  payload     jsonb      NOT NULL,
  resultado   jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (turno_id, tool_name, call_idx)
);

CREATE INDEX tool_calls_turno_idx ON barravips.tool_calls (turno_id);

-- TTL via cron diário (ARQ): DELETE WHERE created_at < now() - interval '7 days'

ALTER TABLE barravips.tool_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.tool_calls FORCE ROW LEVEL SECURITY;

CREATE POLICY fernando_full_access ON barravips.tool_calls
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON barravips.tool_calls TO authenticated;
GRANT ALL PRIVILEGES ON barravips.tool_calls TO service_role;
```

## 6. Tratamento de erro de tool

LangGraph encapsula exceções de tool em `ToolMessage` com `status="error"`. A doc oficial de tool use é explícita: erro de execução deve voltar com **`is_error: true`** (= `status="error"` no `ToolMessage`) e a mensagem deve ser **instrutiva** ("o que deu errado + o que tentar", não `"failed"`). Daí a regra fechada (cruzamento com a doc oficial, 2026-05-24) — separamos por *quem pode agir*, não por estilo:

- **Erro recuperável pelo LLM** (validação Pydantic, param faltando, ou config ausente cuja saída é instruir `escalar` — ex.: chave Pix não cadastrada) → retorna string `"ERRO: ..."` instrutiva; o LLM reformula ou escala no mesmo loop (a API tenta 2-3x antes de desistir). Sai como `status="success"` **de propósito** — não é falha de sistema, é o loop funcionando.
- **Erro de infra sem ação do LLM** (DB indisponível, exceção inesperada) → **levanta exceção tipada**; o `handle_tool_errors` do `ToolNode` (langgraph 1.x) formata com `status="error"`/`is_error=true`. Coordenador captura e `escala_por_exaustao` se persiste.
- **Erro de rede** → não acontece nas tools do P0 (acesso só a Postgres/Redis locais; o envio externo via Evolution roda em workers, fora do loop de tools).

A distinção importa para **observabilidade** (`08`): tratar todo erro como `"ERRO:"`-string mascararia falha de infra como sucesso. Com a separação acima, `status="error"` conta como falha real; `"ERRO:"`-string conta como round-trip de reformulação — buckets distintos nas métricas. (Resolve a "Nota (ponto baixo)" que aqui ficava em aberto: a doc dá o veredito, não é mais decisão de estilo.)

## 7. Strict tool use (validação garantida de schema)

Tools de **enum/tipo crítico** entram com `strict: true` na `ToolParam` — o *grammar-constrained sampling* da Anthropic garante que o `name` e o `input` da tool batem com o JSON Schema (sem `"2"` onde se espera `2`, sem enum fora da lista). Alvos no P0:

| Tool | Por que strict |
|------|----------------|
| `escalar` | `motivo` é enum fechado e é a **chave de roteamento + métrica** (`§3.4/§3.6`); valor inválido erra o destino do handoff. |
| `registrar_extracao` | vários `Literal` (`intencao`, `urgencia`, `motivo_perda_candidato`, …) e `Decimal` (`valor_acordado`); valor malformado **dispara transição de estado errada**. |

`consultar_agenda`, `pedir_pix_deslocamento` e `enviar_midia` ganham pouco (sem param, ou só `tag`/`tipo` já cobertos por `Literal`) — manter sem strict para não pagar latência de compilação à toa.

**Como aplicar (verificado no SDK instalado — `anthropic 0.97.0`):**
- `anthropic.types.ToolParam` **expõe `strict: bool`** (*"When true, guarantees schema validation on tool names and inputs"*) — verificado no `anthropic 0.97`. O chat roda via **`ChatAnthropic` (langchain-anthropic 1.x)** (`nos/llm.py`; o raw SDK 0.97 fica só para vision/STT), então o `strict` entra pelo caminho do langchain, que encaminha `strict` no `ToolParam` do mesmo endpoint. Marcar **por-tool** (`STRICT_TOOLS = {"escalar", "registrar_extracao"}`), não global: `bind_tools(strict=True)` ligaria strict em todas e pagaria latência de grammar nas 3 que não precisam. ⚠️ `langchain-anthropic` ainda **não está no `uv.lock`** (decisão "SDK hybrid" pendente) — ao adicioná-lo, confirmar que a versão propaga `strict` por-tool até o `ToolParam`.
- **Status (GA — doc oficial `eferencia/structuredOUT.md`, auditoria 2026-05-24):** Structured Outputs (JSON outputs + strict tool use) são **GA, sem beta header**. O header antigo `structured-outputs-2025-11-13` ainda funciona num período de transição, mas é dispensável — não passar `betas=[...]` para isto. **Confirmar suporte do modelo** mesmo assim (Opus 4.7 / Sonnet 4.6 — ambos suportados).
- ⚠️ **Incompatível com forced tool use neste projeto.** A doc oferece o combo "garantia de chamada" `tool_choice:{"type":"any"}` + strict, mas o chat roda com `effort` (extended thinking), e `tool_choice` `any`/`tool` **dá erro com extended thinking** — só `auto`/`none` são compatíveis. Strict garante a *forma* do input; a *decisão de chamar* segue por `tool_choice:auto` + prompt. Não "reforçar" com `any`. (Bônus: mudar `tool_choice` invalida o messages-cache — outro motivo para deixá-lo fixo em `auto`.)
- **Higiene de schema:** strict compila o JSON Schema numa grammar; os schemas nested (`ExtracaoPayload`, `EscaladaPayload`) precisam de `additionalProperties: false` em **todos os níveis** — em Pydantic v2, `model_config = ConfigDict(extra="forbid")` em cada (sub)modelo, senão o compilador rejeita ou o cache de grammar não estabiliza. Validar os schemas gerados pelo Pydantic contra o compilador antes de confiar. ⚠️ Pydantic emite `Decimal`/`date`/`time` como `string`+`format`; conferir que a grammar do strict aceita os `format` usados (a doc usa `format: date`). Os SDKs nativos (Python/TS/Ruby/PHP) **transformam o schema automaticamente** (injetam `additionalProperties:false`, removem constraints não suportados, validam a resposta contra o schema original); como rodamos strict **via `langchain-anthropic`** (wrapper), confirmar que ele aplica a mesma transformação até o `ToolParam` — não assumir.
- **Limites de complexidade (doc oficial §Schema complexity limits):** somados em **todos** os schemas `strict` de uma request — strict tools ≤ **20**, optional params ≤ **24**, **parâmetros com union type ≤ 16** (cada `X | None`/`anyOf` conta; são exponencialmente caros de compilar). No P0 só 2 tools strict; `registrar_extracao` (~15 campos) é o único que merece contagem: manter `Optional`/`X | None` abaixo de 16/24 (preferir `required` + default explícito a opcional). Estouro → 400 `"Schema is too complex for compilation"` ou timeout de compilação (180 s).

**Trade-offs:** ~100–300 ms de overhead de compilação da grammar na 1ª chamada (cacheado ~24 h pela Anthropic); em troca, elimina round-trips de reformulação quando o LLM erra o tipo. **Defesa-em-profundidade:** strict é GA, mas a Anthropic garante só *forma*, não *correção* — manter a validação Pydantic (`§6`) e a guarda do piso de desconto (`§3.1`) como rede; nenhum dos dois é substituído por strict.

> **Nota (ponto baixo — `payload` aninhado).** `escalar` (3 campos) e `pedir_pix` embrulham args num único `payload: BaseModel`. A Anthropic recomenda *"explicit parameters"*; args de topo (`motivo, resumo_operacional, acao_esperada`) tendem a ter aderência marginalmente melhor que um objeto aninhado. Com `strict: true` ligado o ganho do achatamento encolhe — tratar como ajuste fino a validar nas evals (`08`), não como bug. `registrar_extracao` (~15 campos) justifica o agrupamento.

> **Guarda de privacidade (retenção de schema, cruzamento 2026-05-24).** A grammar compilada do strict é cacheada **~24h pela Anthropic fora das proteções de prompt/resposta** — então **nenhum dado de cliente pode entrar em nome de campo, `enum`, `const` ou `pattern`** de tool. Hoje isso vale por design: os enums são taxonomias fixas (`motivo`, `motivo_perda_candidato`, `tipo_local`, …) e o dado do cliente vive no message content (BP4/BP2, `02 §5`/`03 §3.2`), que **é** protegido. Como `strict` está ligado justo nas duas tools com mais enums (`§7`), elevamos a regra a invariante: **dado sensível só no prompt, jamais no schema** — corolário direto da decisão "dado vem no contexto, não em tool de leitura" (`§1`).
