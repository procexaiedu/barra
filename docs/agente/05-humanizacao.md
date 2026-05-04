# 05 — Humanização de Envio

> Pipeline de envio de chunks ao Evolution: split por linha em branco, presence composing, jitter, dedupe, cancel-on-new-message, ordem texto→mídia, persistência da resposta da IA.

## 1. Visão de 30 segundos

```
Coordenador (workers/coordenador.py:processar_turno)
  ├─ extrai resposta = AIMessage final do grafo + lista de mídias do turno
  ├─ split do texto por \n\n → chunks de texto
  ├─ obtém lista de {midia_id, legenda} consultando barravips.tool_calls do turno
  ├─ registra `chunks_pendentes:{turno_id}` no Redis (set com IDs dos chunks)
  ├─ enfileira jobs ARQ na ordem: chunk_0, chunk_1, ..., midia_0, midia_1, ...
  └─ libera lock

Worker `enviar_chunk(turno_id, chunk_idx, conteudo)`:
  1. checa `chunks_pendentes:{turno_id}` ainda contém este chunk (cancel-on-new-message)
  2. checa dedupe key `dedup:envio:{conversa_id}:{turno_id}:{chunk_idx}` (SET NX)
  3. presence composing 0.8-2.0s proporcional ao tamanho
  4. envia ao Evolution; recebe evolution_message_id
  5. INSERT em mensagens (direcao='ia', evolution_message_id real)
  6. pausa 0.4-1.2s (jitter)
```

## 2. Split em chunks

A IA é instruída no prompt (regras.md.j2) a separar pensamentos com **linha em branco**. O coordenador faz:

```python
# api/src/barra/workers/coordenador.py
import re

def chunk_texto(texto: str) -> list[str]:
    """Divide o texto em mensagens WhatsApp separadas.

    Regras:
    - separa por \\n\\n (uma ou mais linhas em branco);
    - colapsa espaços em branco internos a 1 espaço;
    - descarta chunks vazios após strip;
    - se chunk único > 600 chars, divide em sentences via regex.
    """
    blocos = re.split(r"\n\s*\n", texto.strip())
    out: list[str] = []
    for b in blocos:
        b = " ".join(b.split())
        if not b:
            continue
        if len(b) > 600:
            # heurística de fallback: split em "! ", "? ", ". " mantendo pontuação
            partes = re.split(r"(?<=[.!?])\s+", b)
            atual = ""
            for p in partes:
                if len(atual) + len(p) + 1 > 600:
                    out.append(atual.strip())
                    atual = p
                else:
                    atual = f"{atual} {p}".strip()
            if atual:
                out.append(atual)
        else:
            out.append(b)
    return out
```

**Regras de produto:**
- Cap superior 600 chars/chunk vem da observação prática: WhatsApp aceita até ~4096, mas mensagens >600 chars passam a parecer artificiais.
- Fallback de sentence-split só dispara se LLM não respeitou o `\n\n` instruído.

## 3. Cancel-on-new-message

Quando cliente envia nova mensagem antes de IA terminar de enviar chunks anteriores, **chunks pendentes do turno antigo são abortados**.

### 3.1 Protocolo

```python
# Coordenador, antes de enfileirar chunks de turno NOVO:
async def cancelar_turno_anterior(redis: Redis, conversa_id: UUID) -> None:
    chave_turno_atual = f"turno_atual:{conversa_id}"
    turno_anterior = await redis.get(chave_turno_atual)
    if turno_anterior:
        # remove a key — workers vão detectar ausência e abortar
        await redis.delete(f"chunks_pendentes:{turno_anterior}")

# ao enfileirar chunks do turno corrente:
async def registrar_chunks_pendentes(
    redis: Redis,
    turno_id: UUID,
    chunks: list[str],
    midias: list[dict],
) -> None:
    chave = f"chunks_pendentes:{turno_id}"
    ids = [f"chunk:{i}" for i in range(len(chunks))]
    ids += [f"midia:{i}" for i in range(len(midias))]
    if ids:
        await redis.sadd(chave, *ids)
        await redis.expire(chave, 600)  # 10min TTL
```

```python
# Worker enviar_chunk, antes de enviar:
async def enviar_chunk(ctx, *, conversa_id: str, turno_id: str, chunk_idx: int, conteudo: str) -> None:
    redis = ctx["redis"]
    chave_pendentes = f"chunks_pendentes:{turno_id}"
    is_pendente = await redis.sismember(chave_pendentes, f"chunk:{chunk_idx}")
    if not is_pendente:
        logger.info("chunk_cancelado", turno_id=turno_id, chunk_idx=chunk_idx)
        return
    # ... segue para presence + send
    await redis.srem(chave_pendentes, f"chunk:{chunk_idx}")
```

### 3.2 Trade-off

Mensagem que estava em "presence composing" no Evolution não tem como ser cancelada do lado do servidor — typing indicator se mantém pelo TTL definido (~3s) mas o cliente não recebe a mensagem se o worker abortar antes de chamar `sendText`.

Em prática:
- Janela típica entre IA decidir resposta e cliente enviar nova mensagem: 1-3s. Cancel funciona em ~80% dos casos.
- Se o primeiro chunk já foi enviado mas o segundo pendente, segundo é abortado — natural.
- Se ambos foram enviados antes da nova mensagem chegar, próximo turno tem que lidar contextualmente.

## 4. Presence composing e timing

### 4.1 Cadência (decisão QA 2026-05-02)

```python
import random

def calcular_typing_ms(texto: str) -> int:
    """0.8s base + 30-60 cps simulados, com cap em 2.0s."""
    chars = len(texto)
    cps = random.uniform(30, 60)  # caracteres por segundo
    duracao = max(0.8, min(2.0, 0.8 + chars / cps))
    return int(duracao * 1000)


def calcular_pausa_ms() -> int:
    """Pausa entre chunks: 400-1200ms uniform."""
    return random.randint(400, 1200)
```

### 4.2 Sequência por chunk

```python
async def enviar_chunk(ctx, *, conversa_id: str, turno_id: str, chunk_idx: int, conteudo: str) -> None:
    # ... (cancel check acima)
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    evolution = ctx["evolution"]

    # dedupe (ARQ pode retentar)
    dedup_key = f"dedup:envio:{conversa_id}:{turno_id}:{chunk_idx}"
    if not await redis.set(dedup_key, "1", nx=True, ex=300):
        logger.info("envio_duplicado_ignorado", **locals())
        return

    # busca metadados da conversa
    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT evolution_chat_id, modelo_id FROM barravips.conversas WHERE id = %s",
            (conversa_id,),
        )
        conv = await res.fetchone()
        res = await conn.execute(
            "SELECT evolution_instance_id FROM barravips.modelos WHERE id = %s",
            (conv["modelo_id"],),
        )
        modelo = await res.fetchone()

    # 1. presence composing
    typing_ms = calcular_typing_ms(conteudo)
    await evolution.set_presence(
        instance=modelo["evolution_instance_id"],
        chat_id=conv["evolution_chat_id"],
        presence="composing",
        delay=typing_ms,
    )
    await asyncio.sleep(typing_ms / 1000)

    # 2. envia
    resp = await evolution.send_text(
        instance=modelo["evolution_instance_id"],
        chat_id=conv["evolution_chat_id"],
        text=conteudo,
    )
    evolution_message_id = resp["key"]["id"]

    # 3. persiste em mensagens
    async with pool.connection() as conn, conn.transaction():
        atendimento_id = await _resolver_atendimento(conn, conversa_id)
        await conn.execute(
            """
            INSERT INTO barravips.mensagens
              (conversa_id, atendimento_id, direcao, tipo, conteudo, evolution_message_id)
            VALUES (%s, %s, 'ia', 'texto', %s, %s)
            ON CONFLICT (evolution_message_id) DO NOTHING
            """,
            (conversa_id, atendimento_id, conteudo, evolution_message_id),
        )

    # 4. pausa
    await asyncio.sleep(calcular_pausa_ms() / 1000)
```

### 4.3 Fila idempotente do Evolution

ARQ entrega at-least-once. O `dedup_key` em Redis (TTL 300s) garante que retries do ARQ não enviem duplicado para o cliente. Já a cláusula `ON CONFLICT (evolution_message_id) DO NOTHING` em `mensagens` cobre dupla persistência.

## 5. Mídia: depois do texto

```python
# api/src/barra/workers/envio.py
async def enviar_midia(
    ctx,
    *,
    conversa_id: str,
    turno_id: str,
    midia_idx: int,
    midia_id: str,
    legenda: str,
) -> None:
    redis = ctx["redis"]
    chave_pendentes = f"chunks_pendentes:{turno_id}"
    if not await redis.sismember(chave_pendentes, f"midia:{midia_idx}"):
        logger.info("midia_cancelada", **locals())
        return

    pool = ctx["db_pool"]
    minio = ctx["minio"]
    evolution = ctx["evolution"]

    dedup_key = f"dedup:envio:{conversa_id}:{turno_id}:midia:{midia_idx}"
    if not await redis.set(dedup_key, "1", nx=True, ex=300):
        return

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT m.tipo, m.bucket, m.object_key, c.evolution_chat_id, mo.evolution_instance_id
              FROM barravips.modelo_midia m
              JOIN barravips.conversas c ON c.id = %s
              JOIN barravips.modelos mo ON mo.id = c.modelo_id
             WHERE m.id = %s
            """,
            (conversa_id, midia_id),
        )
        m = await res.fetchone()
    if not m:
        logger.error("midia_nao_encontrada", midia_id=midia_id)
        return

    # presence "recording" para vídeo, "composing" para foto
    presence = "recording" if m["tipo"] == "video" else "composing"
    await evolution.set_presence(
        instance=m["evolution_instance_id"],
        chat_id=m["evolution_chat_id"],
        presence=presence,
        delay=1500,
    )
    await asyncio.sleep(1.5)

    # TTL de 30min: cobre retries do ARQ (default 5 tentativas com backoff exponencial,
    # potencialmente >5min entre primeira e última). Se mesmo assim expirar, regenerar
    # no retry — não cachear a URL no payload do job.
    url_assinada = minio.presigned_get_object(m["bucket"], m["object_key"], expires=timedelta(minutes=30))
    resp = await evolution.send_media(
        instance=m["evolution_instance_id"],
        chat_id=m["evolution_chat_id"],
        url=url_assinada,
        caption=legenda or None,
        media_type=m["tipo"],
    )

    async with pool.connection() as conn, conn.transaction():
        atendimento_id = await _resolver_atendimento(conn, conversa_id)
        await conn.execute(
            """
            INSERT INTO barravips.mensagens
              (conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id)
            VALUES (%s, %s, 'ia', %s, %s, %s, %s)
            ON CONFLICT (evolution_message_id) DO NOTHING
            """,
            (conversa_id, atendimento_id, m["tipo"], legenda or "", m["object_key"], resp["key"]["id"]),
        )

    await asyncio.sleep(0.6)
```

## 6. Cards no grupo de Coordenação (não passam por humanização)

`mvp/05 §2.3`: cards de handoff e confirmações são enviados **direto pelo Evolution sem passar pela Humanização**.

**Decisão de design (revisão 1.1):** **um único stream Redis `evolution:card`** com `tipo` no payload, em vez de N streams (`evolution:card_grupo`, `..._pix`, `..._chegada`, `..._aviso_saida`). Reduz consumers, simplifica retry/dedupe e centraliza render.

```python
# Triggers enviam para o stream único:
await redis.xadd("evolution:card", {
    "tipo": "escalada",     # | "pix_validado" | "pix_em_revisao" | "chegada" | "aviso_saida"
    "atendimento_id": str(atendimento_id),
    # campos específicos por tipo (escalada_id, media_object_key, etc.)
    "escalada_id": str(escalada_id),
})
```

Worker consumer único `consumer_card_grupo` faz dispatch interno por `tipo`:

Implementação detalhada do dispatch:

```python
# api/src/barra/workers/envio.py — função separada
async def enviar_card_grupo(ctx, *, escalada_id: str) -> None:
    pool = ctx["db_pool"]
    evolution = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT e.*, a.numero_curto, a.estado, a.tipo_atendimento, a.pix_status,
                   c.telefone, mo.coordenacao_chat_id, mo.evolution_instance_id, cl.nome
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.modelos mo ON mo.id = a.modelo_id
              JOIN barravips.clientes cl ON cl.id = a.cliente_id
              JOIN barravips.conversas c ON c.id = a.conversa_id
             WHERE e.id = %s
            """,
            (escalada_id,),
        )
        e = await res.fetchone()
    if not e or e["card_message_id"]:
        return

    texto = render_card(e)  # Jinja2: contexto da escalada
    resp = await evolution.send_text(
        instance=e["evolution_instance_id"],
        chat_id=e["coordenacao_chat_id"],
        text=texto,
    )
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
            (resp["key"]["id"], escalada_id),
        )
```

Card NÃO entra em `mensagens` (apenas `escaladas.card_message_id`); auditoria via `eventos`.

Trigger: tool `escalar` faz `XADD evolution:card {tipo: "escalada", escalada_id, atendimento_id}`; worker único `consumer_card_grupo` faz `XREAD` no stream `evolution:card`, despacha por `tipo` e chama o renderer apropriado (`enviar_card_grupo`, `enviar_card_pix`, `enviar_card_chegada`, `enviar_card_aviso_saida`). Pipeline Pix e foto de portaria publicam no mesmo stream com `tipo` correspondente.

## 7. Falha de envio

ARQ retry default: 5 tentativas com backoff exponencial. Em cada tentativa, `dedup_key` (Redis) garante que se a tentativa N entregou ao Evolution mas falhou ao escrever em `mensagens`, a N+1 não duplica no cliente — só completa a persistência.

Se 5 tentativas falharem: registra em Sentry, deixa o turno "incompleto". Próxima mensagem do cliente dispara novo turno; histórico LangGraph não tem o AIMessage que não chegou. Aceito como falha rara.

## 8. Persistência: tudo só após confirmação

`mvp/02 §2.2` exige registrar tudo, mas a persistência da mensagem da IA acontece **APÓS** o `send_text` retornar com sucesso. Justificativa:

- Mensagem persistida sem ser enviada ao cliente → IA acha que disse algo que cliente não viu → confunde turnos seguintes.
- Falha de envio é incidente (Sentry), não rotina.

`mensagens` é fonte de verdade para histórico do prompt. Se chunk N+1 falhar mas chunk N entregou, histórico fica com chunk N — coerente com o que o cliente recebeu.

## 9. Métricas

```python
ENVIO_DURACAO = Histogram("agente_envio_chunk_duracao_seconds", ["tipo"])
ENVIO_RESULTADO = Counter("agente_envio_resultado_total", ["resultado"])
  # resultado ∈ {ok, cancelado, falha_evolution, dedupe_hit}
ENVIO_RETRIES = Counter("agente_envio_retries_total")
```
