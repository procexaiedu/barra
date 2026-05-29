# 06 — Pipelines de Mídia

> Transcrição de áudio do cliente, OCR/vision para Pix, política de imagem fora-fluxo. Tudo roda em ARQ workers, fora do agente.

## 0. Emendas da sabatina 2026-05-23

> Estas decisões **substituem** os trechos correspondentes abaixo (os blocos de código antigos
> permanecem como referência histórica até o PR de implementação reescrevê-los). O doc 06 estava
> quase 100% não implementado e contradizia `schema 0001`, `settings.py` e `escaladas/service.py`.

1. **Webhook fino (§1.1, §2.1, §5, §6).** O webhook persiste a mensagem com `atendimento_id=NULL` e **só enfileira**; o coordenador (`processar_turno`, `07 §3`) resolve/cria o atendimento sob `lock:conv` e faz back-fill das órfãs. A criação eager atual (`webhook/routes.py:garantir_atendimento_aberto`) é legado pré-coordenador e será removida.
2. **Download de mídia 1x no webhook (§1.1, §1.2, §2.2).** O webhook baixa de `media_url` e sobe pro MinIO na ingestão (já é o comportamento atual), setando `media_object_key` na msg órfã. Os workers recebem `media_object_key` e **leem do MinIO** — não re-baixam de `media_url` (URL da Evolution expira entre ingestão e execução). Assinaturas mudam de `media_url=` → `media_object_key=`. Object key: `conversas/{conversa_id}/mensagens/{evolution_message_id}{ext}` (sem `atendimento_id`, NULL; sem key `comprovantes/` separada).
3. **STT dedicado direto (§1.3).** Transcrição via endpoint dedicado direto: OpenAI `gpt-4o-mini-transcribe`/`whisper-1` ou Groq `whisper-large-v3-turbo`, isolado em `workers/media.py`. Settings: `openai_api_key` + `openai_model_audio_transcribe`; aposentar `openrouter_model_audio_transcribe`. **Correção (auditoria 2026-05-23):** a justificativa antiga "OpenRouter é chat-completions, não transcreve" está **desatualizada** — o OpenRouter lançou `/audio/transcriptions` em 01/05/2026. Mantemos o STT **direto** mesmo assim, mas pelo motivo certo: **menor latência e um ponto de falha a menos** (o hop do OpenRouter não compensa num STT crítico de baixa latência sob o orçamento de 8s).
4. **Vision Pix via OpenRouter (§2.3).** `llm_vision_provider="openrouter"` manda. Usar cliente OpenAI-compatível → OpenRouter com `response_format` json_schema (ou tool-use) e validação `ExtracaoPix` com Pydantic manual; modelo subjacente `claude-sonnet-4.6`/`gemini-2.5-flash`. **Sai** `messages.parse()`/`thinking-disabled` (Anthropic-native). Mantém `openrouter_model_vision_pix`.
   - **Ressalvas verificadas (auditoria 2026-05-23):** (a) ligar **`provider: {"require_parameters": true}`** no request — sem isso o roteamento dinâmico do OpenRouter pode cair num provider que **ignora o json_schema** (risco real num fluxo de pagamento). (b) **Achatar o `ExtracaoPix`** (evitar `$ref`/`anyOf`/nullable aninhado que o Pydantic gera p/ `X | None`) — esses degradam quando roteados pro Gemini via OpenRouter; ou fixar Claude como subjacente. (c) **A decisão merece revisão:** a Anthropic lançou **Structured Outputs GA com constrained decoding** (`messages.parse(output_format=)`, gramática que o modelo não consegue violar), enquanto **Claude via OpenRouter usa JSON prompt-based** (garantia mais fraca). Para validação de pagamento, crítica e de baixo volume, provider único nativo (Anthropic) é mais robusto e tem menos latência — a "flexibilidade de trocar modelo" do OpenRouter raramente é exercida. Manter OpenRouter é defensável (testar gemini-flash barato no OCR), mas como **escolha consciente de flexibilidade**, não de robustez.
5. **`_atualizar_pix` reescrito (§2.2; ver `07 §5`) — ✅ implementado.** `validado` E `em_revisao` → `Confirmado` + `ia_pausada=true` (motivo `modelo_em_atendimento`). O branch `invalido` **permanece na porta** (o painel `pix/routes.py:/rejeitar` já o chama) mas vira **não-revertente**: grava só `pix_status='invalido'` + evento, **sem reverter estado nem despausar a IA** — a modelo já agiu sobre o card de `em_revisao`; o veredito é registro financeiro/auditoria e o `decisao_final` é gravado pela própria rota. (Correção da Q5: durante a sabatina supus o fluxo de revisão do painel como greenfield; ele **já existe** — remover o branch quebraria `/rejeitar` + `test_operacional`.) Feito em `escaladas/service.py` + `tests/test_operacional.py`.
6. **Valor Pix em settings (§2.2).** `settings.pix_deslocamento_valor` (default `100.00`), não hardcoded. Comparar `valor >= esperado` = OK; só underpay/implausível → `em_revisao`. Coluna `modelos.valor_deslocamento` só se precisar variar por modelo.
7. **Falha de transcrição sem enum (§1.5).** `audio_falha` **não existe** no `tipo_evento_enum`. Falha = métrica (`TRANSCRICAO_RESULTADO{erro_provider|timeout}`) + Sentry + log; rastro humano = gravar `mensagens.conteudo='[áudio que não consegui ouvir]'` na falha esgotada (sai de pendente, aparece na janela). Remover o `eventos tipo='audio_falha'`.
8. **Porta única p/ foto_portaria e aviso_saída (§4, §5).** Substituir o SQL cru no worker por função de serviço. `foto_portaria`: cria escalada `responsavel=modelo` + transição `Em_execucao` + bloqueio `em_atendimento` + `foto_portaria_em`, atômico (a escalada hospeda o `card_message_id`). `aviso_saida`: helper leve (seta `aviso_saida_em` guardado por `IS NULL`, sem escalada).
9. **Idempotência de card por owner (§2.5, §4, §5).** O job `enviar_card` envia só se `card_message_id IS NULL` no owner e grava após enviar: `escaladas.card_message_id` (handoffs, incl. chegada) e `comprovantes_pix.card_message_id` (pix). `aviso_saida` (sem owner) → `SETNX card:aviso_saida:{atendimento_id}`. A coluna `comprovantes_pix.card_message_id` vai em migration de **nome timestamp** (`YYYYMMDDHHMMSS_comprovante_pix_card.sql`) — o "0014" do doc colide com `0014_seed_eduardo.sql` e migrations aplicadas são imutáveis.
10. **Aviso de saída detectado pelo agente (§5).** Remover a regex `PADROES_AVISO_SAIDA`. A IA, no turno (que roda mesmo, pois aviso não pausa), seta `aviso_saida_em` + emite o card pela função-porta idempotente. Mais preciso que a heurística. Risco aceito: turno falho/áudio não-transcrito perde → cai no timeout de 24h.
11. **Drop da checagem de timestamp do Pix no MVP (§2.2, §2.3).** Recibo BR mostra horário local (UTC-3) e a vision rotula errado → skew ~3h falsa-marca quase tudo; sendo não-bloqueante, só gerava ruído. Manter plausibilidade + valor + chave + titular. Remover a comparação de timestamp e a instrução de timestamp do prompt. Reintroduzir com TZ correto se aparecer fraude de reuso.
12. **Defaults ratificados (§2.4, §3).** Imagem fora-fluxo com legenda → dispara turno (IA cega responde à legenda); pura → silêncio. Titular: mismatch → `em_revisao` (normalizar acentos/caixa; nome mascarado `J*** S***` não flaga por titular). `_atualizar_pix` mantém guard defensivo `tipo_atendimento=='externo'` ao setar `Confirmado`. Pix não-solicitado (`pix_status≠'aguardando'`) → tratado como imagem fora-fluxo (edge sem tratamento especial no MVP).

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
        # busca conversa_id para sinalizar canal.
        # CRÍTICO: o canal é keyed por conversa_id, NÃO atendimento_id. No momento da transcrição
        # a mensagem ainda é órfã (atendimento_id=NULL — webhook não cria atendimento, 1.4); só o
        # coordenador resolve/cria depois. conversa_id está setado desde o persist e nunca é NULL.
        # Keyar por atendimento_id geraria corrida: sinal perdido → coordenador timeout 8s → canned
        # mesmo com transcrição OK (bug corrigido na grilling 2026-05-23).
        res = await conn.execute(
            "SELECT conversa_id FROM barravips.mensagens WHERE id = %s",
            (mensagem_id,),
        )
        conversa_id = (await res.fetchone())["conversa_id"]

    # 4. sinaliza para coordenador via canal Redis (keyed por conversa_id)
    await redis.lpush(
        f"transcricao:{conversa_id}",
        json.dumps({"mensagem_id": mensagem_id, "ok": True}),
    )
    await redis.expire(f"transcricao:{conversa_id}", 30)
```

### 1.3 Provider — OpenAI Whisper API direto

**Anthropic não transcreve áudio** (não há endpoint de speech-to-text na Messages API). Alternativas:

| Opção | Provider | Custo (PT-BR ~10s áudio) | Qualidade PT-BR | Decisão MVP |
|-------|----------|--------------------------|-----------------|-------------|
| `whisper-1` | OpenAI direto | ~$0.001 | excelente, well-known | **escolhida** |
| `gemini-2.5-flash` (audio) | Google direto | ~$0.0005 | boa, menos testado | trocar se custo dor |
| AssemblyAI / Deepgram | Self-hosted ou managed | varia | muito boa, latência baixa | overkill MVP |

**Justificativa Whisper-1:** mantemos consistência (uma única chamada de áudio), custo desprezível no volume P0 (~50-100 áudios/dia × $0.001 = $3/mês), qualidade conhecida em PT-BR, SDK oficial estável.

> **Reavaliar o modelo (auditoria 2026-05-23):** `gpt-4o-mini-transcribe` custa ~metade do `whisper-1` e **alucina menos em áudio curto/silêncio** — exatamente o perfil de áudio de WhatsApp. Groq `whisper-large-v3-turbo` é ~4-5× mais rápido (encaixa melhor no orçamento de 8s). **Bloqueio de migração a registrar:** `response_format="verbose_json"` e o campo **`.duration` só existem no `whisper-1`** — `gpt-4o-transcribe`/`mini` só aceitam `json`/`text` e **não retornam duração**. Se migrar, calcular a duração localmente (header opus, ex. `mutagen`/`ffprobe`) antes de enviar, em vez de depender de `_transcrever_whisper` retornar `duracao_s`. Manter `openai_model_audio_transcribe` configurável e fazer A/B PT-BR antes de fixar.

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
async def aguardar_transcricoes(redis: Redis, conversa_id: str, timeout: int = 8) -> bool:
    """BLPOP no canal de transcrição (keyed por conversa_id — ver §1.2).

    Retorna True se transcrição chegou; False se timeout.
    Permite múltiplos áudios consecutivos: o coordenador faz BLPOP até esvaziar
    a fila e checa se alguma mensagem ainda tem conteudo='' antes de prosseguir.
    """
    chave = f"transcricao:{conversa_id}"
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        restante = max(1, int(deadline - asyncio.get_event_loop().time()))
        res = await redis.blpop(chave, timeout=restante)
        if res is None:
            break
    # checa se ainda há áudio órfão da conversa sem conteúdo
    return await _todos_audios_transcritos(conversa_id)
```

Se a transcrição falhar (timeout do BLPOP ou `{"ok": false}` do worker) **e o áudio for a mensagem que disparou o turno**, o coordenador **não invoca o LLM**: responde com mensagem fixa canned (pool de variações, ex.: "amor, não consegui ouvir teu áudio agora, me manda por escrito?") e encerra o turno. Áudios falhos de turnos anteriores entram na sliding window só como contexto (`02 §4.2`, placeholder `[áudio que não consegui ouvir]`).

### 1.5 Falha de transcrição

- Provider erro 5xx → retry ARQ (max 3); após esgotar, registra Sentry + sinaliza canal com `{"ok": false}`. Coordenador detecta e responde canned (`§1.4`), sem invocar o LLM.
- Áudio corrompido / inválido → registra `eventos` com `tipo='audio_falha'` e responde canned.

## 2. OCR/Vision para Pix

### 2.1 Roteamento de imagem sob lock (branch 14)

O webhook **não roteia imagem synchronamente** — leitura de estado defasada vs turno de texto em voo poderia descartar um comprovante em silêncio (IA é cega a imagem). Ele só persiste a imagem e enfileira `rotear_imagem`; esse worker adquire `lock:conv`, lê o estado **consistente** e despacha (Pix / foto-portaria / fora-fluxo):

```python
# webhook/routes.py — imagem (só enfileira; NÃO roteia, NÃO cria atendimento)
if msg.tipo == "imagem":
    await arq_pool.enqueue_job("rotear_imagem", mensagem_id=str(mensagem_persistida_id),
                               conversa_id=str(conversa_id), media_url=msg.media_url,
                               caption=msg.caption)

# workers/media.py:rotear_imagem — decisão sob lock:conv (estado consistente)
async def rotear_imagem(ctx, *, mensagem_id, conversa_id, media_url, caption):
    redis, pool = ctx["redis"], ctx["db_pool"]
    try:
        async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15):
            async with pool.connection() as conn:
                a = await resolver_atendimento_existente(conn, UUID(conversa_id))  # só LÊ (não cria)
            estado = a and a["estado"]
            if estado == "Aguardando_confirmacao" and a["pix_status"] == "aguardando":
                await arq_pool.enqueue_job("validar_pix", mensagem_id=mensagem_id,
                                           atendimento_id=str(a["id"]), media_url=media_url)
            elif estado == "Aguardando_confirmacao" and a["tipo_atendimento"] == "interno":
                await _handoff_foto_portaria(...)  # foto de portaria → handoff implícito (mvp/04 §2.1)
            elif caption:
                # fora-fluxo COM legenda: dispara turno (IA responde à legenda, ignora a foto)
                await enfileirar_turno(redis, conversa_id, ...)
            # fora-fluxo PURA (sem legenda): nada — IA cega fica calada (06 §3)
    except LockBusy:
        # turno de texto em voo: re-enfileira com delay curto (mídia não é latency-critical)
        await arq_pool.enqueue_job("rotear_imagem", mensagem_id=mensagem_id, conversa_id=conversa_id,
                                   media_url=media_url, caption=caption, _defer_by=timedelta(seconds=3))
```

> A decisão de roteamento fica serializada com os turnos de texto, eliminando o misroute/descarte silencioso de comprovante. O `validar_pix` em si continua fora do lock (vision é lento; a pausa concorrente que ele gera é pega pelo gate em `prepare_context`, `03 §7`).

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

    # 1. baixa imagem, detecta o mime REAL (não assume jpeg — WhatsApp manda png/webp) e sobe MinIO
    async with httpx.AsyncClient(timeout=30) as http:
        bytes_img = (await http.get(media_url)).content
    media_type = _detectar_mime_imagem(bytes_img)  # magic bytes -> image/{jpeg,png,webp,gif}
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[media_type]
    object_key = f"comprovantes/{atendimento_id}/{mensagem_id}{ext}"
    minio.put_object(settings.minio_bucket_media, object_key, io.BytesIO(bytes_img), len(bytes_img), content_type=media_type)

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

    # 2. chama vision via OpenRouter (cliente OpenAI-compat, response_format json_schema — §0 item 4, §2.3)
    extracao = await _extrair_pix_via_vision(
        bytes_img,
        media_type=media_type,
        client=ctx["vision_client"],
        modelo=settings.openrouter_model_vision_pix,
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
        # O fluxo NUNCA trava por Pix (01 §6.1): validado E duvidoso ("em_revisao") levam
        # o atendimento a Confirmado + ia_pausada=true (motivo modelo_em_atendimento).
        # A duvidez é informativa — vai no card à modelo e numa fila de revisão de Fernando,
        # sem pausar esperando decisão dele.
        from barra.dominio.escaladas.service import aplicar_comando
        await aplicar_comando(
            conn,
            origem="pipeline_pix",
            autor="sistema",
            atendimento_id=UUID(atendimento_id),
            comando="atualizar_pix",
            payload={"decisao": decisao_pipeline, "motivo": motivo_em_revisao},
        )

    # 6. enfileira card como job ARQ (05 §6) — redis aqui é a ArqRedis (enqueue_job)
    await redis.enqueue_job(
        "enviar_card",
        tipo="pix_validado" if decisao_pipeline == "validado" else "pix_em_revisao",
        atendimento_id=atendimento_id,
        decisao=decisao_pipeline,
        _job_id=f"card:pix:{atendimento_id}",
    )
```

### 2.3 Prompt de extração — OpenRouter (OpenAI-compat) + `response_format` json_schema

> **Histórico (superado pela emenda §0 item 4).** O bloco abaixo era a versão Anthropic-native (`messages.parse()` + `output_format=ExtracaoPix`); o código real (`workers/pix.py`) usa **OpenRouter** com cliente OpenAI-compat e `response_format` json_schema + validação `ExtracaoPix` por Pydantic manual (sai `messages.parse()`/`thinking-disabled`; o bloco de imagem vira o formato OpenAI `image_url` `data:{media_type};base64,…` — ver a nota de ordem image-then-text abaixo). Mantido como referência da intenção de extração estruturada.

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
    media_type: str,
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
            # imagem ANTES do texto: best practice oficial de vision (cruzamento vision.md 2026-05-24)
            "content": [
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": media_type,  # mime REAL detectado em validar_pix, não jpeg fixo
                    "data": b64,
                }},
                {"type": "text", "text": PROMPT_PIX},
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

> **Ordem image-then-text + mime real (cruzamento vision.md 2026-05-24).** Dois ajustes vindos da doc oficial de vision: (a) a imagem vai **antes** do `PROMPT_PIX` no `content` — *"Claude works best when images come before text"*; em OCR de comprovante (texto fino: valor, chave) a ordem importa. (b) `media_type` é o **mime real** detectado por magic bytes em `validar_pix` (§2.2, helper `_detectar_mime_imagem` em §2.4), não `image/jpeg` fixo — o WhatsApp entrega png/webp e rotular um png como jpeg degrada/quebra a leitura (`pix/routes.py:170-171` já contornava png na mão). Ambos valem também na reescrita OpenRouter, onde o bloco de imagem muda para o formato OpenAI `image_url` (`data:{media_type};base64,…`).

> **Por que Sonnet 4.6 para vision Pix:** comprovante Pix tem layout variado (Itaú, Nubank, BB, Inter, recibos PDF screenshots, etc.). Sonnet tem precisão visual alta e o custo absoluto é desprezível (~50 comprovantes/dia × $0.005 = $7/mês).

> **Por que `thinking: disabled`:** turno de extração tem schema rígido, sem ambiguidade reasoning-heavy. Adaptive thinking aqui só adiciona latência sem ganho de qualidade.

> **Lifecycle do cliente de vision no worker (`§0` item 4 — OpenRouter):** instanciar um cliente OpenAI-compatível apontado para OpenRouter no `startup` e injetar via `ctx["vision_client"]` (já em `07 §2`). Reutilizar entre invocações. _(O bloco de código acima — `ctx["anthropic_client"]`, Anthropic-native — é referência histórica superada pela emenda do `§0`.)_

> **Imagem: base64 inline vs presigned URL (auditoria 2026-05-23).** A imagem já está no MinIO (`object_key`); se o MinIO tiver URL pública alcançável pelo provider (atrás do Traefik), passar uma **presigned URL** (`{"type":"image_url","image_url":{"url": ...}}`, TTL curto) é mais eficiente que base64 inline (payload ~33% menor, menos memória no worker). Se o MinIO for interno sem ingress, base64 segue sendo o caminho. Custo de tokens de imagem é igual nos dois.

> **Structured Outputs é GA (doc oficial `claudedocs/structuredOUT.md`; auditoria 2026-05-24).** Se voltar ao Anthropic-native (ver `§0` item 4 ressalva c), `messages.parse(output_format=)` **não exige beta header** — Structured Outputs foi promovido a GA (o param raw migrou para `output_config.format`; o header antigo `structured-outputs-2025-11-13` ainda funciona em transição, mas é dispensável). O `output_format` do `client.messages.parse()` **continua válido** no SDK Python — ele o traduz internamente para `output_config.format`; modelos suportados incluem Sonnet 4.6. O SDK também **transforma o schema automaticamente**: remove constraints não suportados (`minimum`/`maximum`/`minLength`…), anexa-os à `description`, injeta `additionalProperties:false` e **valida a resposta contra o schema original**. Por isso a ausência de constraints numéricos no schema é irrelevante aqui — o valor do Pix é validado em `settings` (`>= ok`), não pelo schema. **Incompatível** com message prefilling e citations (irrelevante no Pix).

### 2.4 Helpers (mime + comparação tolerante)

```python
def _detectar_mime_imagem(dados: bytes) -> str:
    """Mime por magic bytes — não confia na extensão/URL da Evolution. Default jpeg.
    Cobre os 4 formatos que o vision aceita (JPEG/PNG/WebP/GIF — vision.md FAQ)."""
    if dados[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    if dados[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


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

O job ARQ `enviar_card` (ver `05 §6`) é enfileirado com o `tipo` e dispatcha por `tipo`:

- **`tipo="pix_validado"`:** card "saída confirmada — #N, [endereço], horário X, valor combinado Y, R$100 deslocamento OK".
- **`tipo="pix_em_revisao"`:** **mesma** "saída confirmada" (o atendimento já está `Confirmado` — o fluxo não trava), mas o card **sinaliza a duvidez à modelo** ("comprovante recebido, mas confira antes de sair: [motivo]") com a imagem anexada, para ela decidir antes de pedir o Uber. Em paralelo, o caso entra na **fila de revisão de Fernando** no painel (assíncrona); não há aprovação/recusa bloqueante.

Renderização em Jinja2; idempotência via `escaladas.card_message_id` (no caso de validado, sem `escalada` — usa coluna `comprovantes_pix.card_message_id` que precisa ser adicionada via migration).

> **Schema TODO:** adicionar `comprovantes_pix.card_message_id text` em `infra/sql/0014_comprovante_pix_card.sql` (numeração alinhada com `09`).

## 3. Imagem fora-fluxo

Imagens em estados que não são `Aguardando_confirmacao` interno nem externo com Pix solicitado. **A IA é cega a imagens no chat (sem vision no P0, decisão grilling 2026-05-22).** Comportamento:

```python
if msg.tipo == "imagem" and não_é_foto_portaria_nem_comprovante:
    # 1. persiste em mensagens (já feito antes, com tipo='imagem' e media_object_key)
    # 2. NÃO escala
    # 3. imagem PURA (sem legenda): NÃO enfileira turno — a IA não responde
    # 4. imagem COM legenda: enfileira turno; a IA responde à legenda (texto), ignora a foto
    if msg.caption:
        await enfileirar_turno(redis, conversa_id, msg.evolution_message_id)
```

> **Por que não responder a imagem pura:** ligar vision no chat é tecnicamente possível (já usamos no `validar_pix`), mas em conteúdo íntimo/explícito — provável neste domínio — o modelo tende a **recusar** comentar, e a recusa quebra a persona pior que o silêncio. Por isso a IA simplesmente não reage a imagem sem texto.

Em `02 §4.2`, `traduzir_mensagens` trata `tipo='imagem'` na sliding window de turnos **futuros** (disparados por texto) como placeholder discreto `[imagem]` — ou a própria legenda, se houver — contexto sem instigar comentário.

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
        # 4. card no grupo (job ARQ — 05 §6)
    await redis.enqueue_job(
        "enviar_card",
        tipo="chegada",
        atendimento_id=str(atendimento_id),
        media_object_key=media_object_key,
        _job_id=f"card:chegada:{atendimento_id}",
    )
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
    await redis.enqueue_job(
        "enviar_card",
        tipo="aviso_saida",
        atendimento_id=str(atendimento_id),
        _job_id=f"card:aviso_saida:{atendimento_id}",
    )
    # NÃO PARA o turno — IA segue respondendo
```

Card "cliente saiu de casa — #N" curto. IA segue conduzindo a conversa textualmente.

## 6. Fluxo de mensagem entrante completo (referência)

```
Webhook recebe mensagem do cliente
├─ persiste mensagem (atendimento_id=NULL); webhook NÃO cria atendimento nem roteia imagem
├─ se tipo='audio':
│    enqueue transcrever_audio + enqueue processar_turno(aguardar_transcricao=True)
├─ se tipo='imagem':
│    enqueue rotear_imagem(conversa_id) — decide sob lock:conv (branch 14, 06 §2.1):
│      Aguardando_confirmacao + pix_status='aguardando' → enqueue validar_pix
│      Aguardando_confirmacao + interno → handoff foto portaria
│      fora-fluxo → com legenda enqueue processar_turno; sem legenda nada (IA calada)
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
