# 06 — Pipelines de Mídia

> Transcrição de áudio do cliente, OCR/vision para Pix, política de imagem fora-fluxo. Tudo roda em ARQ workers, fora do agente.

## 1. Transcrição de áudio

### 1.1 Trigger

Webhook recebe mensagem `tipo='audio'` do cliente:

```python
# api/src/barra/webhook/routes.py — trecho a adicionar após persistir mensagem
if msg.tipo == "audio":
    # baixa do Evolution e sobe pro MinIO antes de transcrever (auditoria)
    await arq_pool.enqueue_job(
        "transcrever_audio",
        mensagem_id=str(mensagem_persistida_id),
        media_url=msg.media_url,
        evolution_message_id=msg.evolution_message_id,
    )
    await enfileirar_turno(redis, conversa_id, msg.evolution_message_id, aguardar_transcricao=True)
else:
    await enfileirar_turno(redis, conversa_id, msg.evolution_message_id)
```

### 1.2 Worker

```python
# api/src/barra/workers/media.py
import io
import httpx
from openai import AsyncOpenAI

async def transcrever_audio(
    ctx,
    *,
    mensagem_id: str,
    media_url: str,
    evolution_message_id: str,
) -> None:
    pool = ctx["db_pool"]
    redis = ctx["redis"]
    minio = ctx["minio"]
    settings = ctx["settings"]

    # 1. baixa do Evolution e sobe pro MinIO
    async with httpx.AsyncClient(timeout=30) as http:
        bytes_audio = (await http.get(media_url)).content
    object_key = f"client_media/{evolution_message_id}.ogg"
    minio.put_object(
        bucket_name=settings.minio_bucket_media,
        object_name=object_key,
        data=io.BytesIO(bytes_audio),
        length=len(bytes_audio),
        content_type="audio/ogg",
    )
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE barravips.mensagens SET media_object_key = %s WHERE id = %s",
            (object_key, mensagem_id),
        )

    # 2. transcreve via OpenAI Whisper API (direto, não OpenRouter)
    transcricao, duracao_s = await _transcrever_whisper(
        bytes_audio,
        api_key=settings.openai_api_key.get_secret_value(),
        modelo=settings.openai_model_audio_transcribe,  # default "whisper-1"
    )

    # 3. atualiza mensagens.conteudo
    nota = f"\n_(originalmente áudio, {round(duracao_s)}s)_"
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE barravips.mensagens SET conteudo = %s WHERE id = %s",
            (transcricao + nota, mensagem_id),
        )
        # busca atendimento_id para sinalizar canal
        res = await conn.execute(
            "SELECT atendimento_id FROM barravips.mensagens WHERE id = %s",
            (mensagem_id,),
        )
        atendimento_id = (await res.fetchone())["atendimento_id"]

    # 4. sinaliza para coordenador via canal Redis
    if atendimento_id:
        await redis.lpush(
            f"transcricao:{atendimento_id}",
            json.dumps({"mensagem_id": mensagem_id, "ok": True}),
        )
        await redis.expire(f"transcricao:{atendimento_id}", 30)
```

### 1.3 Provider — OpenAI Whisper API direto

**Anthropic não transcreve áudio** (não há endpoint de speech-to-text na Messages API). Alternativas:

| Opção | Provider | Custo (PT-BR ~10s áudio) | Qualidade PT-BR | Decisão MVP |
|-------|----------|--------------------------|-----------------|-------------|
| `whisper-1` | OpenAI direto | ~$0.001 | excelente, well-known | **escolhida** |
| `gemini-2.5-flash` (audio) | Google direto | ~$0.0005 | boa, menos testado | trocar se custo dor |
| AssemblyAI / Deepgram | Self-hosted ou managed | varia | muito boa, latência baixa | overkill MVP |

**Justificativa Whisper-1:** mantemos consistência (uma única chamada de áudio), custo desprezível no volume P0 (~50-100 áudios/dia × $0.001 = $3/mês), qualidade conhecida em PT-BR, SDK oficial estável.

**Trade-off aceito:** segundo provider externo (além de Anthropic). Confinado a `workers/media.py` — nada do agente conversacional toca isso.

```python
async def _transcrever_whisper(
    audio_bytes: bytes,
    *,
    api_key: str,
    modelo: str = "whisper-1",
) -> tuple[str, float]:
    """Transcreve via OpenAI API direto. Retorna (texto, duracao_segundos)."""
    client = AsyncOpenAI(api_key=api_key, timeout=60.0, max_retries=3)
    resposta = await client.audio.transcriptions.create(
        file=("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg"),
        model=modelo,
        language="pt",
        response_format="verbose_json",
    )
    return resposta.text.strip(), resposta.duration or 0.0
```

**Métricas:** `agente_transcricao_duracao_seconds`, `agente_transcricao_resultado_total{resultado ∈ ok|timeout|erro_provider}`.

### 1.4 Canal Redis e timeout

Coordenador, após adquirir lock e antes de invocar grafo:

```python
async def aguardar_transcricoes(redis: Redis, atendimento_id: str, timeout: int = 8) -> bool:
    """BLPOP no canal de transcrição.

    Retorna True se transcrição chegou; False se timeout.
    Permite múltiplos áudios consecutivos: o coordenador faz BLPOP até esvaziar
    a fila e checa se alguma mensagem ainda tem conteudo='' antes de prosseguir.
    """
    chave = f"transcricao:{atendimento_id}"
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        restante = max(1, int(deadline - asyncio.get_event_loop().time()))
        res = await redis.blpop(chave, timeout=restante)
        if res is None:
            break
    # checa se ainda há áudio sem conteúdo
    return await _todos_audios_transcritos(atendimento_id)
```

Se timeout, mensagens com `conteudo=''` e `tipo='audio'` viram placeholder na sliding window:

```python
# Em traduzir_mensagens (02 §4.2)
if linha["tipo"] == "audio" and not linha["conteudo"]:
    return HumanMessage(content="[áudio não transcrito]")
```

### 1.5 Falha de transcrição

- Provider erro 5xx → retry ARQ (max 3); após esgotar, registra Sentry + sinaliza canal com `{"ok": false}`. Coordenador vê e prossegue com placeholder.
- Áudio corrompido / inválido → registra `eventos` com `tipo='audio_falha'` e prossegue.

## 2. OCR/Vision para Pix

### 2.1 Trigger

Webhook recebe imagem em atendimento com `pix_status='aguardando'` (externo):

```python
if msg.tipo == "imagem":
    if atendimento_estado == "Aguardando_confirmacao" and pix_status_corrente == "aguardando":
        await arq_pool.enqueue_job(
            "validar_pix",
            mensagem_id=str(mensagem_persistida_id),
            atendimento_id=str(atendimento_id),
            media_url=msg.media_url,
        )
        # NÃO enfileira turno — pipeline cuida sozinho de pausar IA conforme decisão
        return {"status": "pix_em_validacao"}

    elif atendimento_estado == "Aguardando_confirmacao" and tipo_atendimento_corrente == "interno":
        # Foto de portaria → handoff implícito (mvp/04 §2.1)
        await _handoff_foto_portaria(...)
        return {"status": "foto_portaria"}

    else:
        # Imagem fora de fluxo → §3 abaixo
        # NÃO enfileira validar_pix; deixa turno normal seguir
        await enfileirar_turno(redis, conversa_id, msg.evolution_message_id)
```

### 2.2 Worker `validar_pix`

```python
# api/src/barra/workers/pix.py
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime

class ExtracaoPix(BaseModel):
    """Schema de saída do LLM vision."""
    valor: Decimal | None = Field(None, description="Valor pago em BRL, com 2 decimais.")
    chave_pix_destinatario: str | None = Field(None, description="Chave Pix do beneficiário (CPF, email, telefone, aleatória).")
    titular_destinatario: str | None = Field(None, description="Nome do beneficiário.")
    timestamp: datetime | None = Field(None, description="Data/hora do pagamento extraída do comprovante.")
    banco_origem: str | None = None
    plausibilidade_visual: bool = Field(description="True se imagem parece comprovante real; False se suspeita (manipulada, screenshot de outro app, etc).")
    motivo_se_implausivel: str | None = None


async def validar_pix(
    ctx,
    *,
    mensagem_id: str,
    atendimento_id: str,
    media_url: str,
) -> None:
    pool = ctx["db_pool"]
    redis = ctx["redis"]
    minio = ctx["minio"]
    settings = ctx["settings"]

    # 1. baixa imagem e sobe MinIO
    async with httpx.AsyncClient(timeout=30) as http:
        bytes_img = (await http.get(media_url)).content
    object_key = f"comprovantes/{atendimento_id}/{mensagem_id}.jpg"
    minio.put_object(settings.minio_bucket_media, object_key, io.BytesIO(bytes_img), len(bytes_img), content_type="image/jpeg")

    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE barravips.mensagens SET media_object_key = %s WHERE id = %s",
            (object_key, mensagem_id),
        )
        # busca expectativas (chave/titular/valor) da modelo
        res = await conn.execute(
            """
            SELECT mo.chave_pix, mo.titular_chave
              FROM barravips.atendimentos a
              JOIN barravips.modelos mo ON mo.id = a.modelo_id
             WHERE a.id = %s
            """,
            (atendimento_id,),
        )
        esperado = await res.fetchone()

    # 2. chama vision via Anthropic (Sonnet 4.6 com structured output)
    extracao = await _extrair_pix_via_vision(
        bytes_img,
        client=ctx["anthropic_client"],
        modelo=settings.anthropic_model_vision_pix,
    )

    # 3. compara com esperado
    motivo_em_revisao: str | None = None
    if not extracao.plausibilidade_visual:
        motivo_em_revisao = f"plausibilidade visual: {extracao.motivo_se_implausivel or 'imagem suspeita'}"
    elif extracao.valor != Decimal("100.00"):
        motivo_em_revisao = f"valor extraído {extracao.valor} != esperado R$100"
    elif esperado["chave_pix"] and extracao.chave_pix_destinatario \
         and not _chaves_compativeis(extracao.chave_pix_destinatario, esperado["chave_pix"]):
        motivo_em_revisao = f"chave divergente: extraída {extracao.chave_pix_destinatario}, esperada {esperado['chave_pix']}"
    elif esperado["titular_chave"] and extracao.titular_destinatario \
         and not _titulares_compativeis(extracao.titular_destinatario, esperado["titular_chave"]):
        motivo_em_revisao = f"titular divergente: extraído {extracao.titular_destinatario}"
    elif extracao.timestamp and (datetime.now(tz=timezone.utc) - extracao.timestamp).total_seconds() > 3600:
        motivo_em_revisao = f"timestamp >1h atrás: {extracao.timestamp}"

    decisao_pipeline = "validado" if motivo_em_revisao is None else "em_revisao"

    # 4. persiste comprovante
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO barravips.comprovantes_pix
              (atendimento_id, mensagem_id, valor_extraido, chave_extraida, titular_extraido,
               timestamp_extraido, decisao_pipeline, motivo_em_revisao)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (atendimento_id, mensagem_id, extracao.valor, extracao.chave_pix_destinatario,
             extracao.titular_destinatario, extracao.timestamp, decisao_pipeline, motivo_em_revisao),
        )

        # 5. aplica via porta única (escaladas.service.aplicar_comando)
        from barra.dominio.escaladas.service import aplicar_comando
        await aplicar_comando(
            conn,
            origem="pipeline_pix",
            autor="sistema",
            atendimento_id=UUID(atendimento_id),
            comando="atualizar_pix",
            payload={"decisao": decisao_pipeline, "motivo": motivo_em_revisao},
        )

    # 6. enfileira card no stream unificado (05 §6)
    await redis.xadd("evolution:card", {
        "tipo": "pix_validado" if decisao_pipeline == "validado" else "pix_em_revisao",
        "atendimento_id": atendimento_id,
        "decisao": decisao_pipeline,
    })
```

### 2.3 Prompt de extração — Anthropic Sonnet 4.6 + `messages.parse()`

`client.messages.parse()` valida automaticamente a resposta contra o Pydantic schema (`output_format=ExtracaoPix`). Sem prompt do tipo "responda apenas em JSON" — schema é enforçado pela API.

```python
PROMPT_PIX = """Você é um extrator de dados de comprovantes Pix brasileiros.

Analise a imagem do comprovante. Para cada campo:
- Deixe NULL se não estiver legível ou não aparecer.
- plausibilidade_visual=false se: imagem foi claramente editada, screenshot de outro app que não é banco/Pix, recibo manuscrito, montagem digital evidente.
- timestamp em UTC ISO 8601.
- valor SEMPRE com 2 casas decimais (Decimal).
"""


async def _extrair_pix_via_vision(
    bytes_img: bytes,
    *,
    client: AsyncAnthropic,
    modelo: str,
) -> ExtracaoPix:
    """Extrai dados estruturados via Anthropic vision + structured output."""
    import base64
    b64 = base64.standard_b64encode(bytes_img).decode("ascii")

    resposta = await client.messages.parse(
        model=modelo,
        max_tokens=800,
        output_format=ExtracaoPix,  # Pydantic — validação automática
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_PIX},
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                }},
            ],
        }],
        # Sem thinking aqui — extração estruturada é objetiva, sem ganho real.
        thinking={"type": "disabled"},
    )
    # `parsed_output` é populado se schema validou; None se a Anthropic recusou.
    if resposta.parsed_output is None:
        raise ValueError(f"vision recusou ou schema inválido: stop_reason={resposta.stop_reason}")
    return resposta.parsed_output
```

> **Por que Sonnet 4.6 (não Haiku) para vision Pix:** comprovante Pix tem layout variado (Itaú, Nubank, BB, Inter, recibos PDF screenshots, etc.). Sonnet tem precisão visual marcadamente melhor. Custo absoluto desprezível (~50 comprovantes/dia × $0.005 = $7/mês). Se M6 mostrar Haiku acerta ≥95% no eval de 10 fixtures, considerar trocar.

> **Por que `thinking: disabled`:** turno de extração tem schema rígido, sem ambiguidade reasoning-heavy. Adaptive thinking aqui só adiciona latência sem ganho de qualidade.

> **Lifecycle do `anthropic_client` no worker:** instanciar em `WorkerSettings.on_startup` e injetar via `ctx["anthropic_client"]`. Reutilizar conexão entre invocações. Adicionar em `07 §2`.

### 2.4 Comparação tolerante

```python
def _chaves_compativeis(extraida: str, esperada: str) -> bool:
    """Compara chaves Pix com tolerância (espaços, ponto, hífen)."""
    norm = lambda s: re.sub(r"[\s.\-+()/]", "", s).lower()
    return norm(extraida) == norm(esperada)


def _titulares_compativeis(extraido: str, esperado: str) -> bool:
    """Aceita match parcial (primeiro nome igual + mesmo último sobrenome)."""
    e_tokens = extraido.lower().split()
    es_tokens = esperado.lower().split()
    if not e_tokens or not es_tokens:
        return False
    return e_tokens[0] == es_tokens[0] and e_tokens[-1] == es_tokens[-1]
```

### 2.5 Cards no grupo após validação

Worker único `consumer_card_grupo` consome `XREAD evolution:card` (stream unificado, ver `05 §6`) e dispatcha por `tipo`:

- **`tipo="pix_validado"`:** card "saída confirmada — #N, [endereço], horário X, valor combinado Y, R$100 deslocamento OK".
- **`tipo="pix_em_revisao"`:** card "Pix em revisão — #N, [motivo]" com a imagem anexada e botões implícitos no painel para Fernando validar/recusar.

Renderização em Jinja2; idempotência via `escaladas.card_message_id` (no caso de validado, sem `escalada` — usa coluna `comprovantes_pix.card_message_id` que precisa ser adicionada via migration).

> **Schema TODO:** adicionar `comprovantes_pix.card_message_id text` em `infra/sql/0013_comprovante_pix_card.sql` (M3).

## 3. Imagem fora-fluxo

Imagens em estados que não são `Aguardando_confirmacao` interno nem externo com Pix solicitado:

```python
if msg.tipo == "imagem" and não_é_foto_portaria_nem_comprovante:
    # 1. persiste em mensagens (ja feito anteriormente, com tipo='imagem' e media_object_key)
    # 2. NÃO escala
    # 3. Enfileira turno normal — IA recebe sliding window com placeholder textual
    await enfileirar_turno(redis, conversa_id, msg.evolution_message_id)
```

Em `02 §4.2`, `traduzir_mensagens` converte mensagens com `tipo='imagem'` em:

```
HumanMessage("[cliente enviou imagem; conteúdo não interpretado]")
```

IA não tem visão sobre o conteúdo. Resposta segue conforme contexto textual da conversa. Se o cliente enviar selfie em fase de Triagem, a IA verá apenas que houve imagem e seguirá a lógica conversacional (provavelmente perguntar algo).

## 4. Foto de portaria (handoff implícito interno)

Webhook detecta imagem em `Aguardando_confirmacao` interno → handoff implícito (`mvp/04 §2.1`):

```python
async def _handoff_foto_portaria(conn, atendimento_id, mensagem_id, media_object_key):
    """Três efeitos atômicos."""
    async with conn.transaction():
        # 1. UPDATE atendimento: estado = Em_execucao, ia_pausada=true, motivo=modelo_em_atendimento
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET estado = 'Em_execucao',
                   ia_pausada = true,
                   ia_pausada_motivo = 'modelo_em_atendimento',
                   responsavel_atual = 'modelo',
                   foto_portaria_em = now(),
                   fonte_decisao_ultima_transicao = 'webhook_imagem'
             WHERE id = %s
            """,
            (atendimento_id,),
        )
        # 2. atualiza bloqueio vinculado para em_atendimento
        await conn.execute(
            """
            UPDATE barravips.bloqueios
               SET estado = 'em_atendimento'
             WHERE atendimento_id = %s AND estado = 'bloqueado'
            """,
            (atendimento_id,),
        )
        # 3. eventos
        await conn.execute(
            """
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            VALUES (%s, 'transicao_estado', 'agente', 'sistema', %s)
            """,
            (atendimento_id, json.dumps({"de": "Aguardando_confirmacao", "para": "Em_execucao", "gatilho": "foto_portaria"})),
        )
        # 4. card no grupo (stream unificado — 05 §6)
    await redis.xadd("evolution:card", {
        "tipo": "chegada",
        "atendimento_id": str(atendimento_id),
        "media_object_key": media_object_key,
    })
```

Card "cliente chegou — #N, endereço X, horário Y" com a imagem anexada.

> **Sem vision automática sobre a foto** (`mvp/02 §3.2`).

## 5. Aviso de saída do cliente (interno)

`mvp/04 §2.1`: cliente avisa "saí" em texto. Não é handoff — apenas card simples no grupo e IA continua conduzindo.

Detecção heurística via regex no webhook:

```python
PADROES_AVISO_SAIDA = [
    r"\b(sai|saí|saindo|to indo|estou indo|tô indo)\b",
    r"\b(j[aá] saí|chego em)\b",
]

def detectar_aviso_saida(texto: str) -> bool:
    return any(re.search(p, texto.lower()) for p in PADROES_AVISO_SAIDA)
```

Quando detectado em `Aguardando_confirmacao` interno, antes de enfileirar turno:

```python
if atendimento_estado == "Aguardando_confirmacao" and tipo_atendimento == "interno" \
        and msg.tipo == "texto" and detectar_aviso_saida(msg.texto):
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE barravips.atendimentos SET aviso_saida_em = now() WHERE id = %s AND aviso_saida_em IS NULL",
            (atendimento_id,),
        )
    await redis.xadd("evolution:card", {
        "tipo": "aviso_saida",
        "atendimento_id": str(atendimento_id),
    })
    # NÃO PARA o turno — IA segue respondendo
```

Card "cliente saiu de casa — #N" curto. IA segue conduzindo a conversa textualmente.

## 6. Fluxo de mensagem entrante completo (referência)

```
Webhook recebe mensagem do cliente
├─ persiste mensagem (atendimento_id=NULL)
├─ resolve atendimento (refetch após persistir; necessário para próximas branches)
├─ se tipo='audio':
│    enqueue transcrever_audio + enqueue processar_turno(aguardar_transcricao=True)
├─ se tipo='imagem':
│    se Aguardando_confirmacao + pix_status='aguardando': enqueue validar_pix; NÃO enqueue turno
│    se Aguardando_confirmacao + interno: handoff foto portaria; NÃO enqueue turno
│    else: enqueue processar_turno (imagem vira placeholder)
├─ se tipo='texto':
│    se aviso_saida em interno: marca aviso + card simples; enqueue processar_turno (segue normal)
│    else: enqueue processar_turno
└─ retorna 200 ao Evolution
```

## 7. Métricas

```python
TRANSCRICAO_DURACAO = Histogram("agente_transcricao_duracao_seconds")
TRANSCRICAO_RESULTADO = Counter("agente_transcricao_resultado_total", ["resultado"])
PIX_VALIDACAO_DURACAO = Histogram("agente_pix_validacao_duracao_seconds")
PIX_VALIDACAO_DECISAO = Counter("agente_pix_validacao_decisao_total", ["decisao"])
  # decisao ∈ {validado, em_revisao}
PIX_DIVERGENCIA = Counter("agente_pix_divergencia_total", ["motivo"])
  # motivo ∈ {plausibilidade, valor, chave, titular, timestamp}
```
