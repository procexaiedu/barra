# 04 — Catálogo de Tools

> Contratos completos das 8 tools do P0: leitura, extração, escrita operacional. Inclui Pydantic schemas, idempotência e comportamento de borda.

## 1. Visão geral

| Tool | Tipo | Idempotência | Quem chama | Efeito colateral |
|------|------|--------------|------------|-------------------|
| `consultar_agenda` | leitura | n/a | IA | nenhum |
| `consultar_cliente` | leitura | n/a | IA | nenhum |
| `consultar_faq` | leitura | n/a | IA | nenhum |
| `consultar_pix_status` | leitura | n/a | IA | nenhum |
| `consultar_midia` | leitura | n/a | IA | nenhum |
| `registrar_extracao` | escrita | UPSERT por `(turno_id, "registrar_extracao", 0)` | IA, 1x por turno | atualiza `atendimentos.*` + transição de estado se aplicável |
| `pedir_pix_deslocamento` | escrita | UPSERT por `(turno_id, "pedir_pix_deslocamento", 0)` | IA | `pix_status='aguardando'`, atendimento → `Aguardando_confirmacao`; envia mensagem com chave Pix |
| `enviar_midia` | escrita | UPSERT por `(turno_id, "enviar_midia", call_idx)` | IA, várias por turno | anexa mídia à resposta do turno; sem efeito imediato no DB |
| `escalar` | escrita | UPSERT por `(turno_id, "escalar", 0)` | IA, 1x por turno | abre handoff, `ia_pausada=true`, card no grupo |

Todas as tools são **`async`**. Acessam `db_pool` e `redis` via `RunnableConfig.configurable` (ver `02 §6`).

## 2. Tools de leitura

### 2.1 `consultar_agenda(data_inicio, data_fim)`

```python
# api/src/barra/agente/ferramentas/leitura.py
from datetime import date
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

@tool
async def consultar_agenda(
    data_inicio: str,
    data_fim: str,
    config: RunnableConfig,
) -> str:
    """Consulta bloqueios e janelas livres da modelo entre data_inicio e data_fim.

    Args:
        data_inicio: data inicial inclusiva, formato YYYY-MM-DD.
        data_fim: data final inclusiva, formato YYYY-MM-DD. Máximo 14 dias após data_inicio.

    Returns:
        Markdown com bloqueios ativos. Use para responder dúvidas de disponibilidade.
    """
    pool = config["configurable"]["db_pool"]
    modelo_id = config["configurable"]["modelo_id"]
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

### 2.2 `consultar_cliente()`

```python
@tool
async def consultar_cliente(config: RunnableConfig) -> str:
    """Consulta histórico do cliente NESTA CONVERSA com a modelo atual.

    Use quando precisar saber se cliente é novo/recorrente, motivo da última perda,
    ou observações operacionais. Sem parâmetros — escopo (cliente, modelo) já está
    no contexto do turno.

    Returns:
        Resumo curto. Nunca inclui histórico do cliente com OUTRAS modelos.
    """
    pool = config["configurable"]["db_pool"]
    cliente_id = config["configurable"]["cliente_id"]
    modelo_id = config["configurable"]["modelo_id"]

    async with pool.connection() as conn:
        # 1. consulta da conversa (par cliente, modelo)
        res = await conn.execute(
            """
            SELECT c.recorrente,
                   c.observacoes_internas,
                   c.ultimo_motivo_perda,
                   cl.nome AS cliente_nome
              FROM barravips.conversas c
              JOIN barravips.clientes cl ON cl.id = c.cliente_id
             WHERE c.cliente_id = %s AND c.modelo_id = %s
            """,
            (cliente_id, modelo_id),
        )
        conv = await res.fetchone()
        if not conv:
            return "Cliente novo nesta conversa."

        # 2. atendimentos anteriores DESTA conversa (não inclui de outras modelos)
        res = await conn.execute(
            """
            SELECT estado, valor_final, motivo_perda, created_at
              FROM barravips.atendimentos
             WHERE cliente_id = %s AND modelo_id = %s
               AND estado IN ('Fechado', 'Perdido')
             ORDER BY created_at DESC
             LIMIT 5
            """,
            (cliente_id, modelo_id),
        )
        anteriores = await res.fetchall()

    linhas = []
    linhas.append(f"Recorrente: {'sim' if conv['recorrente'] else 'não'}.")
    if conv["cliente_nome"]:
        linhas.append(f"Nome: {conv['cliente_nome']}.")
    if conv["ultimo_motivo_perda"]:
        linhas.append(f"Última perda nesta conversa: {conv['ultimo_motivo_perda']}.")
    if conv["observacoes_internas"]:
        linhas.append(f"Observações: {conv['observacoes_internas']}.")
    if anteriores:
        resumo_ant = ", ".join(
            f"{a['estado']}{f' R$ {a[\"valor_final\"]}' if a['valor_final'] else ''}"
            for a in anteriores
        )
        linhas.append(f"Atendimentos anteriores ({len(anteriores)}): {resumo_ant}.")
    return " ".join(linhas)
```

**Importante:** `cliente_id` e `modelo_id` saem do `config`, não de parâmetro do LLM. Tool sem args evita classe inteira de bugs ("LLM passa telefone errado") e simplifica idempotência. Auditoria de "que cliente foi consultado" sai do `config` no trace LangSmith — não precisa do parâmetro de fachada.

### 2.3 `consultar_faq(query)`

```python
@tool
async def consultar_faq(query: str, config: RunnableConfig) -> str:
    """Busca em FAQ da modelo (global + específica).

    Use quando precisar de resposta autorizada para algo que não está no FAQ pré-carregado
    no system prompt (FAQ pré-carregado tem só os top items; tool acessa todos).

    Args:
        query: termo ou pergunta curta para casar com FAQ.

    Returns:
        Top 3 resultados em markdown ou 'sem resposta autorizada' se nada casar.
    """
    pool = config["configurable"]["db_pool"]
    modelo_id = config["configurable"]["modelo_id"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT pergunta, resposta
              FROM barravips.modelo_faq
             WHERE (modelo_id IS NULL OR modelo_id = %s)
               AND (pergunta ILIKE %s OR resposta ILIKE %s OR %s = ANY(tags))
             LIMIT 3
            """,
            (modelo_id, f"%{query}%", f"%{query}%", query.lower()),
        )
        rows = await res.fetchall()
    if not rows:
        return "Sem resposta autorizada na FAQ. Considere escalar para Fernando."
    return "\n\n".join(f"**{r['pergunta']}**\n{r['resposta']}" for r in rows)
```

### 2.4 `consultar_pix_status(atendimento_id?)`

```python
@tool
async def consultar_pix_status(config: RunnableConfig) -> str:
    """Retorna status do Pix de deslocamento do atendimento corrente.

    Returns: um de: nao_solicitado, aguardando, enviado, em_revisao, validado, invalido.
    """
    pool = config["configurable"]["db_pool"]
    atendimento_id = config["configurable"]["atendimento_id"]

    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT pix_status FROM barravips.atendimentos WHERE id = %s",
            (atendimento_id,),
        )
        row = await res.fetchone()
    return f"pix_status={row['pix_status']}" if row else "atendimento não encontrado"
```

Nota: a IA raramente precisa chamar — `pix_status` já está no contexto dinâmico (`02 §5`). Tool serve para casos em que dúvida pontual surge.

### 2.5 `consultar_midia(tag)`

```python
@tool
async def consultar_midia(tag: str, config: RunnableConfig) -> str:
    """Lista mídias pré-aprovadas da modelo para uma tag.

    Args:
        tag: uma de: apresentacao, corpo, lifestyle, evento.

    Returns:
        Lista markdown de [{midia_id, tipo, descricao_curta}]. Use o midia_id na tool enviar_midia.
    """
    tags_validas = {"apresentacao", "corpo", "lifestyle", "evento"}
    if tag not in tags_validas:
        return f"ERRO: tag inválida. Use uma de: {', '.join(tags_validas)}."

    pool = config["configurable"]["db_pool"]
    modelo_id = config["configurable"]["modelo_id"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT id, tipo, COALESCE(descricao, '') AS descricao
              FROM barravips.modelo_midia
             WHERE modelo_id = %s AND tag = %s AND aprovada = true
             ORDER BY created_at
             LIMIT 10
            """,
            (modelo_id, tag),
        )
        rows = await res.fetchall()
    if not rows:
        return f"Nenhuma mídia disponível para tag '{tag}'."
    linhas = [f"- {r['id']} ({r['tipo']}): {r['descricao'] or 'sem descrição'}" for r in rows]
    return "\n".join(linhas)
```

> **Schema TODO:** `modelo_midia.descricao` ainda não existe no schema. Adicionar via `infra/sql/0012_modelo_midia_descricao.sql` (M1 do roteiro).

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
    proxima_acao_esperada: str = Field(min_length=3, max_length=240)


@tool
async def registrar_extracao(
    payload: ExtracaoPayload,
    config: RunnableConfig,
) -> str:
    """Registre o snapshot do que aprendeu nesta conversa. Chame UMA vez por turno, perto do fim.

    Esta tool dispara transições de estado:
    - intencao=curiosidade/cotacao/agendamento + estado=Novo → Triagem
    - intencao=agendamento + dados mínimos (horario_desejado, tipo_atendimento) + estado=Triagem → Qualificado
    - tipo_atendimento + horario_desejado + estado=Qualificado → Aguardando_confirmacao
      (interno: cria bloqueio prévio; externo: nota — pedir_pix_deslocamento ainda é tool separada)

    O campo proxima_acao_esperada (obrigatório) é exibido no painel para Fernando.
    """
    pool = config["configurable"]["db_pool"]
    atendimento_id = config["configurable"]["atendimento_id"]
    turno_id = config["configurable"]["turno_id"]

    async with pool.connection() as conn:
        resultado = await _executar_idempotente(
            conn, turno_id, "registrar_extracao", 0,
            payload=payload.model_dump(mode="json"),
            executor=lambda c, p: _aplicar_extracao(c, atendimento_id, p),
        )
    return resultado["mensagem"]


async def _aplicar_extracao(conn, atendimento_id: str, payload: dict) -> dict:
    """Faz UPSERT em atendimentos e dispara transição de estado."""
    # 1. UPDATE com COALESCE — só sobrescreve campos não-nulos
    sets = []
    valores = []
    for campo in ("intencao", "urgencia", "tipo_atendimento", "data_desejada",
                  "horario_desejado", "duracao_horas", "endereco", "bairro",
                  "tipo_local", "forma_pagamento", "valor_acordado",
                  "motivo_perda_candidato", "proxima_acao_esperada"):
        if payload.get(campo) is not None:
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
                await _criar_bloqueio_previo(conn, atendimento)

    await _evento(conn, atendimento_id, "extracao_registrada",
                  origem="agente", autor="IA",
                  payload=payload)
    return {"mensagem": "Extração registrada.", "novo_estado": novo_estado}


async def _decidir_transicao(conn, atendimento_id: str) -> str | None:
    """Aplica a tabela de mvp/04 §8.2."""
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
    if a["estado"] == "Qualificado" and a["tipo_atendimento"] is not None \
            and a["horario_desejado"] is not None:
        return "Aguardando_confirmacao"
    return None
```

**Notas:**
- **Mover `_aplicar_extracao` e `_decidir_transicao` para `dominio/atendimentos/service.py:registrar_extracao_ia(conn, atendimento_id, payload)`.** A tool em `agente/ferramentas/extracao.py` deve ficar como wrapper de ~10 linhas que chama o serviço de domínio. Justificativa: regra de transição de estado é domain logic, não tool logic — pertence ao mesmo módulo onde os outros estados são manipulados (`aplicar_comando`, `_atualizar_pix`, etc.).
- Bloqueio prévio (interno) é criado em `_criar_bloqueio_previo`; reaproveita `dominio/agenda/service.py`.

### 3.2 `pedir_pix_deslocamento()`

```python
# api/src/barra/agente/ferramentas/pix.py
@tool
async def pedir_pix_deslocamento(config: RunnableConfig) -> str:
    """Solicita Pix de R$100 para deslocamento (saída externa).

    Sem parâmetros — valor é fixo R$100 (MVP), chave/titular vêm do cadastro da modelo.
    Após chamada: pix_status=aguardando, atendimento → Aguardando_confirmacao,
    e a humanização envia mensagem ao cliente com a chave Pix.

    Use APENAS para atendimento externo após acordar horário e endereço.
    Use APENAS UMA vez por atendimento (segunda chamada é idempotente, não duplica mensagem).
    """
    pool = config["configurable"]["db_pool"]
    atendimento_id = config["configurable"]["atendimento_id"]
    modelo_id = config["configurable"]["modelo_id"]
    turno_id = config["configurable"]["turno_id"]

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
    # Retorno guia o LLM a escrever a mensagem ao cliente com a chave
    return (
        f"Pix solicitado: R$ 100 para chave {m['chave_pix']} (titular {m['titular_chave']}). "
        "Escreva mensagem ao cliente pedindo o Pix com essas informações."
    )


async def _aplicar_pedido_pix(conn, atendimento_id: str, payload: dict) -> dict:
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET pix_status = 'aguardando',
               estado = 'Aguardando_confirmacao',
               fonte_decisao_ultima_transicao = 'extracao_ia'
         WHERE id = %s AND pix_status IN ('nao_solicitado', 'invalido')
        """,
        (atendimento_id,),
    )
    await _evento(conn, atendimento_id, "pix_solicitado", origem="agente", autor="IA", payload=payload)
    return {"mensagem": "Pix solicitado."}
```

**Observação importante:** a tool **não envia mensagem** ao cliente — apenas atualiza estado e retorna texto guia. A IA escreve a mensagem com a chave/titular no AIMessage final do turno. Isso evita acoplamento entre tool e Evolution.

### 3.3 `enviar_midia(midia_id, legenda?)`

```python
# api/src/barra/agente/ferramentas/midia.py
from uuid import UUID

@tool
async def enviar_midia(
    midia_id: str,
    legenda: str | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """Anexa uma mídia pré-aprovada à resposta do turno corrente.

    Args:
        midia_id: UUID retornado por consultar_midia.
        legenda: opcional, texto curto que aparece junto da mídia no WhatsApp.

    Returns: confirmação para a IA.
    Pode ser chamada múltiplas vezes no mesmo turno; mídias são enviadas após o texto.
    """
    pool = config["configurable"]["db_pool"]
    modelo_id = config["configurable"]["modelo_id"]
    turno_id = config["configurable"]["turno_id"]

    try:
        midia_uuid = UUID(midia_id)
    except ValueError:
        return "ERRO: midia_id inválido. Use o ID retornado por consultar_midia."

    async with pool.connection() as conn:
        # validação: mídia pertence à modelo e é aprovada
        res = await conn.execute(
            "SELECT id, tipo, object_key FROM barravips.modelo_midia WHERE id = %s AND modelo_id = %s AND aprovada = true",
            (midia_uuid, modelo_id),
        )
        m = await res.fetchone()
        if not m:
            return "ERRO: mídia não encontrada ou não autorizada."

        # call_idx = quantas chamadas anteriores houve
        res = await conn.execute(
            "SELECT COUNT(*) AS c FROM barravips.tool_calls WHERE turno_id = %s AND tool_name = 'enviar_midia'",
            (turno_id,),
        )
        call_idx = (await res.fetchone())["c"]

        await _executar_idempotente(
            conn, turno_id, "enviar_midia", call_idx,
            payload={"midia_id": str(midia_uuid), "legenda": legenda or ""},
            executor=lambda c, p: {"midia_id": p["midia_id"], "legenda": p["legenda"]},
        )

    return f"Mídia anexada (será enviada após o texto). midia_id={midia_id}"
```

Coordenador, ao processar resposta final, lê `tool_calls` do `turno_id` para extrair lista de mídias a despachar:

```sql
SELECT payload->>'midia_id' AS midia_id, payload->>'legenda' AS legenda
  FROM barravips.tool_calls
 WHERE turno_id = %s AND tool_name = 'enviar_midia'
 ORDER BY call_idx;
```

### 3.4 `escalar(responsavel, motivo, resumo_operacional, acao_esperada)`

```python
# api/src/barra/agente/ferramentas/escalada.py
from typing import Literal
from pydantic import BaseModel, Field

class EscaladaPayload(BaseModel):
    responsavel: Literal["Fernando", "modelo"]
    motivo: Literal[
        # Operacionais
        "fora_de_oferta",
        "horario_indisponivel",
        "politica_nova_necessaria",
        "cliente_chegou_interno",
        "exaustao_iteracoes",
        "timeout_grafo",
        # AUP / persona / jailbreak (cf. 10-persona-jailbreak.md)
        "disclosure_insistente",
        "disclosure_explicito",
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
    payload: EscaladaPayload,
    config: RunnableConfig,
) -> str:
    """Escale o atendimento para Fernando (decisão sensível) ou modelo (ação operacional).

    Após chamar, sua próxima fala virá quando Fernando devolver para você
    explicitamente, ou quando a modelo registrar finalizado pelo grupo. Não
    escreva mais texto nesse turno.

    Args:
        payload.responsavel: 'Fernando' (risco/política/AUP) ou 'modelo' (operacional).
        payload.motivo: enum fechado — ver EscaladaPayload em §3.4. Categorias:
          - operacionais (fora_de_oferta, horario_indisponivel, ...)
          - AUP / persona (disclosure_insistente, jailbreak_attempt, ...)
        payload.resumo_operacional: 1-3 frases descrevendo o que aconteceu na conversa.
                                    Para AUP, incluir TEXTO LITERAL da pergunta do cliente.
        payload.acao_esperada: o que Fernando/modelo devem decidir/fazer.
    """
    pool = config["configurable"]["db_pool"]
    atendimento_id = config["configurable"]["atendimento_id"]
    turno_id = config["configurable"]["turno_id"]

    from barra.dominio.escaladas.service import abrir_handoff

    async with pool.connection() as conn:
        resultado = await _executar_idempotente(
            conn, turno_id, "escalar", 0,
            payload=payload.model_dump(),
            executor=lambda c, p: _executar_handoff(c, atendimento_id, p),
        )
    # Enfileira card no grupo (despachado direto pelo Evolution; bypass da humanização)
    redis = config["configurable"]["redis"]
    await redis.xadd("evolution:card_grupo", {"escalada_id": str(resultado["escalada_id"])})

    return f"Escalada aberta para {payload.responsavel}. Próxima fala virá quando devolverem para você — não escreva mais texto neste turno."


async def _executar_handoff(conn, atendimento_id: str, payload: dict) -> dict:
    """Wraps abrir_handoff e retorna escalada_id."""
    from barra.dominio.escaladas.service import abrir_handoff
    await abrir_handoff(
        conn,
        atendimento_id=UUID(atendimento_id),
        responsavel=payload["responsavel"],
        motivo=payload["motivo"],
        resumo_operacional=payload["resumo_operacional"],
        acao_esperada=payload["acao_esperada"],
        origem="agente",
        autor="IA",
    )
    res = await conn.execute(
        "SELECT id FROM barravips.escaladas WHERE atendimento_id = %s ORDER BY aberta_em DESC LIMIT 1",
        (atendimento_id,),
    )
    return {"escalada_id": (await res.fetchone())["id"]}
```

**Comportamento crítico:**

1. Tool grava direto via `dominio.escaladas.service.abrir_handoff` — `ia_pausada=true` é setado dentro da transação.
2. Tool retorna mensagem positiva ("Próxima fala virá quando devolverem... — não escreva mais texto neste turno") — guia o LLM, mas não confia só nisso.
3. Após `graph.ainvoke()`, **coordenador refaz fetch do atendimento** e checa `ia_pausada`. Se true, descarta qualquer texto que tenha sido emitido — **mesmo que a IA tenha seguido escrevendo após `escalar` por desobediência**.
4. Card no grupo de Coordenação é enfileirado via Redis stream `evolution:card_grupo`; worker dedicado consome e chama Evolution direto (bypass de humanização — `mvp/05 §2.3`).

### 3.5 Regra de stop após `escalar`

Conforme `mvp/03 §5.3`: "ao chamar `escalar`, parar — não tentar despedir-se nem comentar a escalada".

Reforço em **3 camadas**:
1. **Prompt** (`regras.md.j2`): "Após chamar `escalar`, sua próxima fala virá quando devolverem para você. Não escreva mais texto nesse turno."
2. **Tool retorno**: string indica claramente que turno encerrou.
3. **Coordenador**: refetch + `if atendimento.ia_pausada: descartar texto` (cinto-suspensório).

A camada 3 é a que importa em produção; as outras existem para reduzir tokens desperdiçados. Linguagem na camada 1 trocada de "PARE" (anti-padrão Sonnet 4.6) para forma positiva.

### 3.6 Motivos AUP — fluxo distinto

Motivos da família AUP (`disclosure_*`, `jailbreak_attempt`, `pedido_explicito_repetido`, `prova_humanidade_persistente`, `cross_modelo_fishing`) **sempre escalam para Fernando**, nunca para modelo. Card no grupo deve incluir:

- Texto literal da última N=3 mensagens do cliente (para auditoria).
- `motivo` exato.
- Sugestão de ação ("decidir se devolve para IA ou descarta atendimento").

`abrir_handoff` em `dominio/escaladas/service.py` valida: se `motivo` é AUP-família, força `responsavel="Fernando"` mesmo se tool passou "modelo".

Detalhes em `10-persona-jailbreak.md §2-§4`.

## 4. Registro centralizado das tools

```python
# api/src/barra/agente/ferramentas/__init__.py
from .leitura import (
    consultar_agenda,
    consultar_cliente,
    consultar_faq,
    consultar_pix_status,
    consultar_midia,
)
from .extracao import registrar_extracao
from .pix import pedir_pix_deslocamento
from .midia import enviar_midia
from .escalada import escalar

TOOLS = [
    consultar_agenda,
    consultar_cliente,
    consultar_faq,
    consultar_pix_status,
    consultar_midia,
    registrar_extracao,
    pedir_pix_deslocamento,
    enviar_midia,
    escalar,
]
```

Ordem importa para o LLM (lista chega na ordem em `tools` da request); leitura primeiro, escrita depois — heurística de prompt engineering para favorecer chamadas seguras antes.

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

LangGraph encapsula exceções de tool em `ToolMessage` com `status="error"`. Padrão para tools:

- **Validação de entrada** (Pydantic) → exceção; LangGraph devolve para o LLM como texto e ele reformula. Caso comum, queremos.
- **Erro de DB** → log + exceção; coordenador captura e escala_por_exaustao se persiste.
- **Erro de rede** (consultar_midia) → não acontece no P0 (tudo Postgres local).

Tools nunca devem retornar texto enganoso; em caso de erro, retornam string começando com `"ERRO: ..."` para o LLM tratar.
