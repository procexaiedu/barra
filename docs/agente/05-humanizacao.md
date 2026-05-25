# 05 — Humanização de Envio

> Pipeline de envio de **um turno** ao Evolution: split por linha em branco, presence composing, jitter, dedupe, cancel-on-new-message, ordem texto→mídia, persistência da resposta da IA. **Um único job ARQ `enviar_turno` por turno** percorre todos os chunks e depois as mídias, em ordem (decisão grilling 2026-05-23).

## 1. Visão de 30 segundos

```
Coordenador (workers/coordenador.py:processar_turno)
  ├─ extrai resposta = AIMessage final do grafo + lista de mídias do turno (tool_calls)
  ├─ chunk_texto(texto) → chunks (preserva \n interno; cap ~6 bolhas)
  ├─ obtém [{midia_id, legenda}] de barravips.tool_calls do turno (ORDER BY call_idx)
  ├─ coleta msg_ids_cliente + chars_inbound das msgs do cliente da janela (p/ read receipt)
  ├─ turno_atual:{conversa_id} já aponta para turno_id (setado no passo 3 do processar_turno)
  ├─ determina critico (houve write tool COM EFEITO?) → passa critico=bool no payload do job
  └─ enqueue_job("enviar_turno", conversa_id, turno_id, chunks, midias,
                 msg_ids_cliente, chars_inbound, critico,
                 _job_id=f"turno_envio:{turno_id}")

Worker enviar_turno(conversa_id, turno_id, chunks, midias, msg_ids_cliente, chars_inbound, critico):
  0. read receipt: marca msgs do cliente como lidas + reading delay (~len do inbound) ← lê antes de digitar
  para cada chunk idx:
    1. cancel-on-new-message: se NÃO crítico e turno_atual:{conversa_id} != turno_id → break
    2. dedupe: se idx ∈ enviados:{turno_id} → continue (retry do job)
    3. presence composing ~0.8-2.0s
    4. EvolutionClient.enviar_texto → POST + registra envios_evolution → evolution_message_id
    5. INSERT em mensagens (direcao='ia', evolution_message_id real)
    6. sadd enviados:{turno_id} chunk:idx        ← MARK-AFTER-SEND
    7. pausa 0.4-1.2s (jitter)
  depois do texto, para cada mídia idx: mesma sequência (presence recording/composing, send_media)
  se o job esgotar as retries do ARQ e critico=true → escalar_por_exaustao (não só Sentry)
```

**Por que um único job, e não um job por chunk:** jobs ARQ separados rodam concorrentes
(`max_jobs`) e **não garantem ordem** — chunk_1 poderia chegar antes do chunk_0, quebrando a
ilusão de digitação sequencial e tornando o presence/typing sem sentido. Um job percorrendo o
turno em laço garante ordem e cadência por construção; o cancel e o dedupe são checados *entre*
chunks dentro do mesmo processo.

## 2. Split em chunks

A IA é instruída no prompt (`regras.md`) a separar pensamentos com **linha em branco**. O
chunking vive em `workers/_chunking.py` (consumido pelo coordenador):

```python
# api/src/barra/workers/_chunking.py
import re

from barra.core.metrics import CHUNK_OVERSIZE

MAX_CHARS = 600
MAX_CHUNKS = 6


def chunk_texto(texto: str) -> list[str]:
    """Divide o texto da IA em mensagens WhatsApp separadas.

    Regras:
    - separa por \\n\\n (uma ou mais linhas em branco) → uma mensagem por bloco;
    - dentro de um bloco, PRESERVA \\n simples (lista de horários, endereço continuam
      multi-linha): colapsa só espaços/tabs por linha e descarta linhas vazias;
    - se um bloco passa de ~600 chars, sub-divide por sentença ("! ", "? ", ". ");
      uma sentença única > 600 sai INTEIRA (o cap é alvo, não garantia) e incrementa
      CHUNK_OVERSIZE — sinal de prompt que ignorou o \\n\\n instruído, não de erro de envio;
    - cap final de MAX_CHUNKS bolhas: o excedente é FUNDIDO no último chunk (anti-spam de
      40 mensagens + mantém o turno abaixo do job_timeout de 90s).
    """
    blocos = re.split(r"\n\s*\n", texto.strip())
    out: list[str] = []
    for bruto in blocos:
        bloco = _normaliza_bloco(bruto)
        if not bloco:
            continue
        if len(bloco) <= MAX_CHARS:
            out.append(bloco)
        else:
            out.extend(_subdividir(bloco))
    return _cap_bolhas(out)


def _normaliza_bloco(bloco: str) -> str:
    """Colapsa espaços/tabs POR LINHA, preserva \\n simples, descarta linhas vazias."""
    linhas = [" ".join(linha.split()) for linha in bloco.split("\n")]
    return "\n".join(linha for linha in linhas if linha)


def _subdividir(bloco: str) -> list[str]:
    """Fallback só quando o LLM não respeitou o \\n\\n e o bloco passou de 600 chars."""
    out: list[str] = []
    atual = ""
    for p in re.split(r"(?<=[.!?])\s+", bloco):
        if len(p) > MAX_CHARS:
            # sentença única estoura o cap: emite inteira (não corta no meio da frase)
            if atual:
                out.append(atual)
                atual = ""
            out.append(p)
            CHUNK_OVERSIZE.inc()
        elif len(atual) + len(p) + 1 > MAX_CHARS:
            out.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    if atual:
        out.append(atual)
    return out


def _cap_bolhas(out: list[str]) -> list[str]:
    if len(out) <= MAX_CHUNKS:
        return out
    # funde o excedente no último chunk permitido — preserva conteúdo, não dropa
    return [*out[: MAX_CHUNKS - 1], "\n\n".join(out[MAX_CHUNKS - 1 :])]
```

**Regras de produto:**
- Cap superior ~600 chars/chunk é **alvo, não garantia**: mensagens >600 chars parecem
  artificiais, mas uma sentença única que estoura é enviada inteira (cortar no meio da frase
  pareceria *mais* robótico) e incrementa `CHUNK_OVERSIZE` para detectar regressão de prompt.
- O sentence-split só dispara se o LLM não respeitou o `\n\n` instruído.
- `\n` simples **dentro** de um bloco é preservado: lista de horários / endereço chegam como
  um humano mandaria, em linhas dentro de uma mesma mensagem.
- Cap de ~6 bolhas: uma persona casual não manda 40 mensagens seguidas, e o teto evita que o
  turno (job único) ultrapasse o `job_timeout`.

## 3. Cancel-on-new-message

Quando o cliente envia nova mensagem antes de a IA terminar de enviar os chunks anteriores, os
**chunks pendentes do turno antigo são abortados**. Com job único, o cancel é um `break` no laço.

> **Exceção — turno crítico (decisão grilling 2026-05-23):** turnos que commitaram efeito de
> *write tool* (`pedir_pix_deslocamento`, ou `registrar_extracao` que **causou transição**) são
> **não-canceláveis no turno inteiro** — todos os seus chunks sempre entregam, senão o efeito
> (slot reservado, Pix pedido) fica sem a mensagem correspondente ao cliente, criando dead-end
> (`02 §8.1`). Protege-se o **turno inteiro** (e não "o chunk do efeito") porque o texto que
> carrega a chave Pix / a confirmação é gerado livremente pelo LLM e pode estar em qualquer
> chunk — não dá para identificá-lo com segurança. Pior caso: entregar um chunk conversacional
> já obsoleto (barato) em vez de dropar o efeito (caro).

### 3.1 Protocolo

O cancel **não usa um set por chunk**. O coordenador já mantém `turno_atual:{conversa_id}`
apontando para o turno mais novo (`07 §3`, passo 3); cancelar = simplesmente iniciar um turno
mais novo, que sobrescreve essa chave. O job de envio compara, antes de cada chunk:

```python
# Coordenador (07 §3): a cada turno novo, ANTES de invocar o grafo
await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)
# (não há mais registrar_chunks_pendentes nem cancelar_turno_anterior baseados em set)

# Worker enviar_turno: antes de enviar cada chunk
turno_atual = await redis.get(f"turno_atual:{conversa_id}")
if not critico and turno_atual != turno_id:
    logger.info("turno_cancelado", turno_id=turno_id, idx=idx)
    ENVIO_RESULTADO.labels("cancelado").inc()
    break
```

Cancel é all-or-nothing no turno: quando dispara, aborta **todos** os chunks restantes (os já
enviados já chegaram). Para turno crítico, o check de `turno_atual` é ignorado e o laço entrega
tudo.

### 3.2 Trade-off

Mensagem que estava em "presence composing" no Evolution não tem como ser cancelada do lado do
servidor — o typing indicator se mantém pelo TTL (~3s), mas o cliente não recebe a mensagem se o
laço abortar antes de chamar `enviar_texto`.

Em prática:
- Janela típica entre IA decidir resposta e cliente enviar nova mensagem: 1-3s. Cancel funciona
  em ~80% dos casos.
- Se o primeiro chunk já foi enviado mas o segundo está pendente, o segundo é abortado — natural.
- Se ambos foram enviados antes da nova mensagem chegar, o próximo turno lida com isso
  contextualmente (o turno novo lê a janela inteira, incluindo o que já saiu).

## 4. Presence composing e timing

### 4.1 Cadência (decisão QA 2026-05-02, simplificada grilling 2026-05-23)

```python
import random


def calcular_typing_ms(_texto: str) -> int:
    """Typing 0.8-2.0s, plano.

    A fórmula anterior (0.8 + chars/cps) tinha o cap de 2.0s dominando para qualquer chunk
    acima de ~55 chars — o componente "caracteres por segundo" era cosmético. Mantemos o teto
    enxuto (numa conversa de venda a responsividade ajuda; o que vende humanização é o
    indicador "digitando…" aparecer, não a duração exata) e usamos random plano.
    """
    return random.randint(800, 2000)


def calcular_pausa_ms() -> int:
    """Pausa entre chunks: 400-1200ms uniform."""
    return random.randint(400, 1200)


def calcular_reading_delay_ms(chars_inbound: int) -> int:
    """Reading delay antes do PRIMEIRO 'composing': simula o tempo de ler o que o
    cliente mandou (humano lê → digita → responde). Proporcional ao tamanho do
    inbound do turno, com piso e teto enxutos — numa venda a responsividade ainda
    importa, então o delay é curto.
    """
    return min(500 + chars_inbound * 12, 3000)
```

> **Confiabilidade do `set_presence` (a confirmar na instância self-host).** O "digitando…" via
> `sendPresence` é notoriamente instável na Evolution/Baileys (issues
> [#1639](https://github.com/EvolutionAPI/evolution-api/issues/1639),
> [#1531](https://github.com/EvolutionAPI/evolution-api/issues/1531)) — pode simplesmente não
> renderizar. Como toda a humanização depende dele aparecer, **validar e2e antes de confiar**. A
> Evolution também aceita `delay` + `presence:"composing"` **inline** no próprio `sendText`/`sendMedia`
> (mostra o typing por `delay` ms e só então entrega): é o fallback caso o `sendPresence` separado
> não renderize — perde-se a janela de cancel entre presence e envio (a mensagem fica comprometida
> ao POST), mas o typing fica garantido.

### 4.2 Sequência por chunk (dentro de `enviar_turno`)

O envio reusa o `EvolutionClient` (POST + registro em `envios_evolution`) e **adicionalmente**
grava em `mensagens`. As duas tabelas têm papéis distintos:
- `envios_evolution` — auditoria de outbound + **desambiguação `fromMe`**: o webhook
  (`webhook/routes.py`) trata como nosso (e ignora) todo `evolution_message_id` que esteja
  nessa tabela; sem isso, o eco do próprio chunk da IA (que volta como `fromMe=true`) seria lido
  como a modelo digitando manualmente. **Obrigatório.**
- `mensagens` — histórico que o `prepare_context` lê na sliding window. Sem isso, a IA "esquece"
  o que disse. **Obrigatório.**

```python
# api/src/barra/workers/envio.py
async def enviar_turno(
    ctx,
    *,
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    midias: list[dict],
    msg_ids_cliente: list[str],   # evolution_message_id das msgs do cliente no turno
    chars_inbound: int,           # total de chars do inbound — alimenta o reading delay
    critico: bool = False,
) -> None:
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    evolution = ctx["evolution"]

    conv = await _carregar_destino(pool, conversa_id)  # evolution_chat_id, instance_id, atend.

    # 0. read receipt + reading delay (humano lê antes de digitar). markAsRead é idempotente,
    #    mas o membro "read" do set evita re-dormir o delay no retry do job. Roda ANTES do
    #    cancel: marcar lido é inócuo mesmo que o turno seja cancelado em seguida.
    if msg_ids_cliente and not await redis.sismember(f"enviados:{turno_id}", "read"):
        await evolution.marcar_lida(
            instance_id=conv["evolution_instance_id"],
            remote_jid=conv["evolution_chat_id"],
            message_ids=msg_ids_cliente,
        )
        await asyncio.sleep(calcular_reading_delay_ms(chars_inbound) / 1000)
        await redis.sadd(f"enviados:{turno_id}", "read")
        await redis.expire(f"enviados:{turno_id}", 600)

    for idx, conteudo in enumerate(chunks):
        # 1. cancel-on-new-message (turno crítico ignora)
        if not critico and await redis.get(f"turno_atual:{conversa_id}") != turno_id:
            ENVIO_RESULTADO.labels("cancelado").inc()
            return
        # 2. dedupe (retry do job inteiro re-percorre desde idx 0)
        if await redis.sismember(f"enviados:{turno_id}", f"chunk:{idx}"):
            continue

        # 3. presence composing
        typing_ms = calcular_typing_ms(conteudo)
        await evolution.set_presence(
            instance_id=conv["evolution_instance_id"],
            remote_jid=conv["evolution_chat_id"],
            presence="composing",
            delay_ms=typing_ms,
        )
        await asyncio.sleep(typing_ms / 1000)

        # 4 + 5. POST (→ envios_evolution) e persistência em mensagens
        async with pool.connection() as conn, conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                texto=conteudo,
                contexto="conversa_cliente",
                tipo="texto",
                atendimento_id=conv["atendimento_id"],
                conversa_id=UUID(conversa_id),
            )
            await conn.execute(
                """
                INSERT INTO barravips.mensagens
                  (conversa_id, atendimento_id, direcao, tipo, conteudo, evolution_message_id)
                VALUES (%s, %s, 'ia', 'texto', %s, %s)
                ON CONFLICT (evolution_message_id) DO NOTHING
                """,
                (conversa_id, conv["atendimento_id"], conteudo, mid),
            )

        # 6. MARK-AFTER-SEND: só agora idx conta como entregue
        await redis.sadd(f"enviados:{turno_id}", f"chunk:{idx}")
        await redis.expire(f"enviados:{turno_id}", 600)

        # 7. jitter
        await asyncio.sleep(calcular_pausa_ms() / 1000)

    await _enviar_midias(ctx, conversa_id, turno_id, midias, conv, critico)
```

### 4.3 Idempotência

ARQ entrega at-least-once e **retenta o job inteiro** em falha. A idempotência vem de duas redes:

- **`enviados:{turno_id}`** (set Redis, marcado **depois** de POST+INSERT — *mark-after-send*).
  No retry, o laço re-percorre desde o idx 0 e pula o que já entregou. **Não** marcamos antes do
  POST (*claim-before-send*): isso pularia para sempre um chunk que reivindicou a key e falhou o
  POST, perdendo a mensagem em silêncio.
- **`ON CONFLICT (evolution_message_id) DO NOTHING`** em `mensagens` e `envios_evolution` —
  segunda rede contra dupla persistência do mesmo `evolution_message_id`.

Risco residual: um *kill* de processo na janela de sub-segundo entre o POST retornar e o `sadd`
faz o retry reenviar (o Evolution não aceita id de idempotência fornecido por nós), gerando uma
mensagem duplicada rara. Aceito — duplicada é mais perdoável que mensagem perdida com o cliente
esperando. (Hardening futuro: confirmar se o `sendText` da Evolution v3 aceita id de cliente.)

## 5. Mídia: depois do texto

Mídia é uma **fase do mesmo job** `enviar_turno`, após todos os chunks de texto. A posição
relativa entre chamadas de `enviar_midia` e o texto não é capturada (o texto é o `AIMessage`
final; as mídias vêm das `tool_calls`), então a ordem é sempre texto→mídia; a **legenda** de
cada mídia carrega o contexto dela (caption), cobrindo a maioria dos casos ("aqui, olha 😏" +
foto). Interleaving real (texto→foto→texto) exigiria capturar a sequência de emissão — adiado
para depois do P0.

> **Mídia exclusiva (grilling 2026-05-23, `CONTEXT.md`).** A IA manda **fotos primeiro e vídeo depois** (`enviar_midia(tipo)`, `04 §3.3`); a legenda do vídeo carrega a narrativa de exclusividade ("gravando agora só pra vc"). O ideal é o vídeo ir como **visualização única (view-once)** para proteger o conteúdo, mas a doc oficial da Evolution v2 **não expõe `viewOnce`** no `sendMedia` (`01 §6.13`): no P0 o vídeo vai normal e o view-once é **pré-req a confirmar na instância self-host** — quando o campo passar, `_enviar_midias` envia `view_once=(m["tipo"]=="video")`.

```python
# api/src/barra/workers/envio.py
async def _enviar_midias(ctx, conversa_id, turno_id, midias, conv, critico):
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    evolution = ctx["evolution"]

    for idx, item in enumerate(midias):
        if not critico and await redis.get(f"turno_atual:{conversa_id}") != turno_id:
            ENVIO_RESULTADO.labels("cancelado").inc()
            return
        if await redis.sismember(f"enviados:{turno_id}", f"midia:{idx}"):
            continue

        async with pool.connection() as conn:
            res = await conn.execute(
                "SELECT tipo, bucket, object_key FROM barravips.modelo_midia WHERE id = %s",
                (item["midia_id"],),
            )
            m = await res.fetchone()
        if not m:
            logger.error("midia_nao_encontrada", midia_id=item["midia_id"])
            continue

        # presence "recording" para vídeo, "composing" para foto
        presence = "recording" if m["tipo"] == "video" else "composing"
        await evolution.set_presence(
            instance_id=conv["evolution_instance_id"],
            remote_jid=conv["evolution_chat_id"],
            presence=presence,
            delay_ms=1500,
        )
        await asyncio.sleep(1.5)

        # URL assinada regenerada NO job (TTL 30min) — nunca cachear no payload: os retries do
        # ARQ (backoff exponencial) podem ocorrer >5min depois.
        url = minio.presigned_get_object(m["bucket"], m["object_key"], expires=timedelta(minutes=30))
        async with pool.connection() as conn, conn.transaction():
            mid = await evolution.enviar_midia(
                conn=conn,
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                url=url,
                caption=item["legenda"] or None,
                media_type=m["tipo"],
                contexto="conversa_cliente",
                tipo=m["tipo"],
                # view-once p/ vídeo (Mídia exclusiva, 01 §6.13): efetivo só quando a Evolution
                # self-host expuser o campo no sendMedia (pré-req); ignorado até lá.
                view_once=(m["tipo"] == "video"),
                atendimento_id=conv["atendimento_id"],
                conversa_id=UUID(conversa_id),
            )
            await conn.execute(
                """
                INSERT INTO barravips.mensagens
                  (conversa_id, atendimento_id, direcao, tipo, conteudo,
                   media_object_key, evolution_message_id)
                VALUES (%s, %s, 'ia', %s, %s, %s, %s)
                ON CONFLICT (evolution_message_id) DO NOTHING
                """,
                (conversa_id, conv["atendimento_id"], m["tipo"], item["legenda"] or "",
                 m["object_key"], mid),
            )

        await redis.sadd(f"enviados:{turno_id}", f"midia:{idx}")
        await redis.expire(f"enviados:{turno_id}", 600)
        await asyncio.sleep(0.6)
```

`set_presence`, `enviar_midia` e `marcar_lida` são **métodos novos** de `core/evolution.py`
(`enviar_midia` espelha `enviar_texto`: POST → registra `envios_evolution` → devolve
`evolution_message_id`; `marcar_lida` faz `POST /chat/markMessageAsRead/{instance}` com
`read_messages=[{remoteJid, fromMe:false, id}]`, **não** entra em `envios_evolution` — é read
receipt, não outbound de mensagem; confirmar o casing `read_messages` vs `readMessages` na self-host).
O kwarg opcional `view_once` (Mídia exclusiva, `01 §6.13`) só tem efeito quando a versão
self-host da Evolution expõe o campo no `sendMedia` (pré-req); até lá é ignorado e o vídeo vai normal.

## 6. Cards no grupo de Coordenação (não passam por humanização)

`mvp/05 §2.3`: cards de handoff e confirmações são enviados **direto pelo Evolution sem passar
pela Humanização**.

**Decisão de design (grilling 2026-05-23):** cards são **jobs ARQ diretos**, não um stream
Redis. O ARQ já dá at-least-once, retry com backoff e dedupe por `_job_id` nativos — um stream
`evolution:card` com consumer `XREAD` próprio (a) não encaixa no modelo job/cron do ARQ (seria
uma task long-running) e (b) sem consumer group perderia o card num crash do consumer, e card é
sinal operacional crítico (a modelo não saberia que "o cliente chegou"). A centralização do
render é preservada por **uma função `enviar_card` única com dispatch por `tipo`**.

```python
# Triggers enfileiram o job diretamente:
await arq.enqueue_job(
    "enviar_card",
    tipo="escalada",          # | "pix_validado" | "pix_em_revisao" | "chegada" | "aviso_saida"
    atendimento_id=str(atendimento_id),
    escalada_id=str(escalada_id),     # campos específicos por tipo
    _job_id=f"card:escalada:{escalada_id}",   # dedupe nativo do ARQ
)
```

```python
# api/src/barra/workers/envio.py — dispatch único por tipo
_RENDER_CARD = {
    "escalada": _card_escalada,
    "pix_validado": _card_pix,
    "pix_em_revisao": _card_pix,
    "chegada": _card_chegada,
    "aviso_saida": _card_aviso_saida,
}


async def enviar_card(ctx, *, tipo: str, **kw) -> None:
    render = _RENDER_CARD[tipo]
    await render(ctx, **kw)
```

```python
async def _card_escalada(ctx, *, escalada_id: str, **_) -> None:
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
            return  # idempotência: card já enviado → o retry do ARQ não reenvia

        texto = render_card(e)  # Jinja2: contexto da escalada
        # POST (→ envios_evolution) e gravação de card_message_id na MESMA transação:
        # `enviar_texto` usa este `conn`, então o envio tem de viver dentro do `async with`.
        async with conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=e["evolution_instance_id"],
                remote_jid=e["coordenacao_chat_id"],
                texto=texto,
                contexto="coordenacao",
                tipo="card_escalada",
            )
            await conn.execute(
                "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
                (mid, escalada_id),
            )
```

Card entra em `envios_evolution` (via `enviar_texto`, necessário para a desambiguação `fromMe`
no grupo — ver `webhook/routes.py:_processar_grupo`) e em `escaladas.card_message_id`; **NÃO**
entra em `mensagens`. Auditoria adicional via `eventos`.

Pipeline de Pix e foto de portaria enfileiram `enviar_card` com o `tipo` correspondente.

## 7. Falha de envio

ARQ retry default: 5 tentativas com backoff exponencial sobre o job `enviar_turno`. O cursor
`enviados:{turno_id}` faz o retry **retomar de onde parou** (chunks já entregues são pulados);
o `dedup` via `ON CONFLICT` é a segunda rede.

Esgotadas as 5 tentativas, o tratamento depende de `critico`:

- **Turno crítico** (Pix pedido / slot reservado): o efeito já está no banco mas a mensagem pode
  não ter chegado — exatamente o dead-end que o conceito de crítico existe para evitar. Em vez de
  só registrar no Sentry, **escalar** (decisão grilling 2026-05-23):

  ```python
  # handler de falha final do job (ARQ on_job_failure ou checagem na última tentativa):
  if critico:
      await escalar_por_exaustao(
          pool, atendimento_id, turno_id, motivo="envio_exaurido_critico",
      )  # card na Coordenação + ia_pausada=true (07 §3.3)
      ENVIO_RESULTADO.labels("exaustao_critico").inc()
  ```

  **Sem rollback** do efeito: com `enviados`/`ON CONFLICT`, o chunk com a chave Pix pode já ter
  chegado; desfazer slot/Pix seria incoerente com o que o cliente viu. Escalar deixa um humano
  ler a conversa e ver o que de fato chegou. `critico` vem no **payload do job** (não do
  `turno_critico:{turno_id}` no Redis, cujo TTL pode expirar antes da última retry com backoff).

- **Turno conversacional:** registra em Sentry e deixa o turno "incompleto". A próxima mensagem
  do cliente dispara novo turno; o histórico LangGraph não tem o `AIMessage` que não chegou.
  Aceito como falha rara.

## 8. Persistência: tudo só após confirmação

`mvp/02 §2.2` exige registrar tudo, mas a persistência da mensagem da IA acontece **APÓS** o
`enviar_texto`/`enviar_midia` retornar com sucesso. Justificativa:

- Mensagem persistida sem ser enviada ao cliente → IA acha que disse algo que o cliente não viu
  → confunde turnos seguintes.
- Falha de envio é incidente (Sentry / escalada para crítico), não rotina.

`mensagens` é fonte de verdade para o histórico do prompt. Se o chunk N+1 falhar mas o chunk N
entregou, o histórico fica com o chunk N — coerente com o que o cliente recebeu.

## 9. Métricas

```python
# api/src/barra/core/metrics.py — adicionar
ENVIO_DURACAO = Histogram("agente_envio_turno_duracao_seconds")     # job enviar_turno inteiro
ENVIO_RESULTADO = Counter("agente_envio_resultado_total", ["resultado"])
  # resultado ∈ {ok, cancelado, dedupe_skip, falha_evolution, exaustao_critico}
CHUNK_OVERSIZE = Counter("agente_chunk_oversize_total")             # sentença única > 600 (§2)
ENVIO_RETRIES = Counter("agente_envio_retries_total")
```
