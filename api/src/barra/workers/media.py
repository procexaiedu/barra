"""Pipelines de midia (06 §1, §2).

- `limpar_midias_vencidas`: cron diario que apaga objetos MinIO de atendimentos terminais (>90d).
- `transcrever_audio`: STT via OpenRouter (06 §1.3). Le o objeto MinIO (gravado pelo webhook
  fino), transcreve, faz UPDATE em `mensagens.conteudo` e sinaliza o canal Redis
  `transcricao:{conversa_id}` para o coordenador acordar do BLPOP (06 §1.4).
- `rotear_imagem`: decide o destino de uma imagem entrante sob `lock:conv` (06 §2.1) — Pix,
  foto-portaria (handoff implicito), turno com legenda ou silencio.
"""

import asyncio
import base64
import json
import logging
from datetime import timedelta
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from openai import APIError, AsyncOpenAI
from psycopg import AsyncConnection

from barra.agente._custo import calcular_custo_stt_brl
from barra.core.metrics import (
    AGENTE_CUSTO_STT_BRL,
    JOBS,
    ROTEAR_IMAGEM_DECISAO,
    TRANSCRICAO_DURACAO,
    TRANSCRICAO_RESULTADO,
)
from barra.core.redis import LockBusy, adquirir_lock
from barra.workers.coordenador import resolver_atendimento_existente

try:
    from minio import Minio
except ModuleNotFoundError:  # pragma: no cover
    Minio = object  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


# Falhas na fase de download/transcricao que valem retry do ARQ. Esgotado o retry, grava placeholder
# em mensagens.conteudo (06 §1.5) — o `_falha_definitiva` chama-se a partir do `except` final.
_AUDIO_PLACEHOLDER = "[audio que nao consegui ouvir]"

# Modelo de STT quando `settings.openrouter_model_audio_transcribe` nao vem do Env (o compose
# repassa a var e ela chega VAZIA se o Portainer nao a define) — mesmo padrao do vision em pix.py.
# Gemini 3.1 Flash Lite escolhido por bancada com os 2 audios reais do piloto (24/07), 3 rodadas
# por modelo: R$0,0016/audio, 1,7s e saida IDENTICA nas 3 rodadas. Os dois eixos que decidiram:
#  - fidelidade em entidade nomeada: capta o vocativo "Tati" (o cliente chamando a modelo, que se
#    chama Tatiane) onde a familia 2.5 ouve "ta" — proxy do que mais importa em audio de venda
#    (nome, valor, horario). A referencia forte diverge no ponto (2.5-pro le "ta", 3.1-pro le
#    "Tati"), mas o contexto da conversa decide a favor de "Tati".
#  - ESTABILIDADE: 3.5-flash-lite devolveu 3 transcricoes DIFERENTES em 3 rodadas do mesmo audio
#    ("Claudi"/"Claudio I"/"Claudio ai") mesmo com temperature=0 — descartado apesar de barato.
# Descartados tambem: 3.5-flash e 3.6-flash (4,5s, ~R$0,033 — 20x mais caro por ganho nenhum),
# gpt-audio-mini e voxtral (recusam ogg/opus, 400 do provider).
_MODELO_STT_PADRAO = "google/gemini-3.1-flash-lite"

# O modelo de STT do OpenRouter e' um chat multimodal, nao um endpoint de transcricao: sem
# instrucao firme ele COMENTA o audio ("o audio diz que...") ou traduz. O marcador de silencio
# evita que ele invente fala onde nao ha (audio mudo/ruido) -- vira falha definitiva no caller.
_SEM_FALA = "(sem fala)"
_PROMPT_STT = (
    "Transcreva literalmente este audio em portugues do Brasil. "
    "Responda APENAS com a transcricao, sem aspas, sem comentarios, sem traduzir. "
    f"Se nao houver fala audivel, responda exatamente: {_SEM_FALA}"
)

# `format` do content part `input_audio`, derivado da extensao do objeto no MinIO (o WhatsApp
# manda ogg/opus; mp3/m4a aparecem em audio encaminhado). Desconhecido -> ogg, o caso dominante.
_FORMATO_AUDIO: dict[str, str] = {".ogg": "ogg", ".mp3": "mp3", ".m4a": "m4a", ".wav": "wav"}


def _formato_audio(object_key: str) -> str:
    _, _, ext = object_key.rpartition(".")
    return _FORMATO_AUDIO.get(f".{ext.lower()}", "ogg")


async def limpar_midias_vencidas(
    conn: AsyncConnection[Any],
    minio: Minio | None,
    *,
    bucket: str = "media",
) -> int:
    result = await conn.execute(
        """
        SELECT msg.media_object_key
          FROM barravips.mensagens msg
          JOIN barravips.atendimentos a ON a.id = msg.atendimento_id
         WHERE msg.media_object_key IS NOT NULL
           AND a.estado IN ('Fechado', 'Perdido')
           AND a.updated_at < now() - interval '90 days'
        """
    )
    rows = await result.fetchall()
    apagados = 0
    if minio is not None:
        for row in rows:
            minio.remove_object(bucket, row["media_object_key"])
            apagados += 1
    else:
        apagados = len(rows)
    JOBS.labels("limpeza_midia", "sucesso").inc()
    return apagados


async def _resolver_mensagem_uuid(
    conn: AsyncConnection[Any], evolution_message_id: str
) -> UUID | None:
    """Resolve o UUID interno de `mensagens.id` pelo `evolution_message_id`. O webhook enfileira
    `rotear_imagem` com o id da Evolution (string), mas `validar_pix`/`_handoff_foto_portaria`
    operam pelo UUID interno (FK + UUID() estrito)."""
    res = await conn.execute(
        "SELECT id FROM barravips.mensagens WHERE evolution_message_id = %s",
        (evolution_message_id,),
    )
    row = await res.fetchone()
    return row["id"] if row else None


async def rotear_imagem(
    ctx: dict[str, Any],
    *,
    mensagem_id: str,
    conversa_id: str,
    media_url: str | None = None,
    caption: str | None = None,
) -> None:
    """Decide o destino de uma imagem entrante sob `lock:conv` (06 §2.1).

    O webhook so persiste e enfileira; aqui adquirimos o lock para serializar com `processar_turno`
    e ler o estado consistente. Despacha entre validar_pix, foto-portaria (handoff implicito),
    turno (legenda dispara texto) ou silencio (imagem pura fora-fluxo: IA e cega).

    `LockBusy` (turno de texto em voo): re-enfileira a si mesmo com defer curto — midia nao e
    latency-critical e o turno solta o lock em segundos.
    """
    redis = ctx["redis"]
    pool = ctx["db_pool"]

    try:
        async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15):
            async with pool.connection() as conn:
                atendimento = await resolver_atendimento_existente(conn, UUID(conversa_id))
                # O webhook enfileira com o `evolution_message_id` (string); `validar_pix` e
                # `_handoff_foto_portaria` operam pelo UUID interno de `mensagens.id` (FK + UUID()
                # estrito). Resolve aqui para nao passar o id da Evolution adiante (ValueError).
                mensagem_uuid = await _resolver_mensagem_uuid(conn, mensagem_id)

            estado = atendimento["estado"] if atendimento else None
            pix_status = atendimento["pix_status"] if atendimento else None
            tipo_atendimento = atendimento["tipo_atendimento"] if atendimento else None

            if estado == "Aguardando_confirmacao" and pix_status == "aguardando":
                assert atendimento is not None  # estado != None implica atendimento
                if mensagem_uuid is None:
                    logger.error(
                        "rotear_imagem sem mensagem persistida evolution_id=%s", mensagem_id
                    )
                    return
                # `validar_pix` tem assinatura enxuta (06 §0 item 2: a midia ja esta no MinIO,
                # a URL da Evolution expira) e NAO aceita media_url — passa-lo aqui quebraria o
                # job com TypeError no ARQ real.
                await redis.enqueue_job(
                    "validar_pix",
                    mensagem_id=str(mensagem_uuid),
                    atendimento_id=str(atendimento["id"]),
                    _job_id=f"pix:{atendimento['id']}:{mensagem_id}",
                )
                ROTEAR_IMAGEM_DECISAO.labels("pix").inc()
                return

            if estado == "Aguardando_confirmacao" and tipo_atendimento == "interno":
                assert atendimento is not None
                if mensagem_uuid is None:
                    logger.error(
                        "rotear_imagem sem mensagem persistida evolution_id=%s", mensagem_id
                    )
                    return
                await _handoff_foto_portaria(
                    ctx,
                    conversa_id=conversa_id,
                    atendimento_id=str(atendimento["id"]),
                    mensagem_id=str(mensagem_uuid),
                )
                ROTEAR_IMAGEM_DECISAO.labels("foto_portaria").inc()
                return

            if atendimento is None and mensagem_uuid is not None:
                # Ressurreicao interna (ADR 0027): a foto chegou DEPOIS de o timeout (ADR 0024)
                # matar o #1 interno (Perdido/auto_timeout_interno) e cancelar o bloqueio —
                # `resolver_atendimento_existente` exclui terminais, entao nao ha atendimento
                # aberto. Tenta reconectar o interno morto cujo slot segue livre e dentro do
                # bloqueio.fim; orfanar a prova de chegada fisica seria errado.
                if await _ressurreicao_foto_portaria(
                    ctx, conversa_id=conversa_id, mensagem_id=str(mensagem_uuid)
                ):
                    ROTEAR_IMAGEM_DECISAO.labels("foto_portaria_ressurreicao").inc()
                    return

            if caption:
                # Imagem fora-fluxo COM legenda: dispara turno (IA cega responde a legenda; 06 §3).
                # Import tardio evita ciclo workers.media -> webhook.despacho -> webhook.parser.
                from barra.webhook.despacho import enfileirar_turno

                await enfileirar_turno(redis, UUID(conversa_id), mensagem_id)
                ROTEAR_IMAGEM_DECISAO.labels("fora_fluxo_legenda").inc()
                return

            # Imagem pura fora-fluxo: IA fica calada (06 §3).
            ROTEAR_IMAGEM_DECISAO.labels("silencio").inc()

    except LockBusy:
        await redis.enqueue_job(
            "rotear_imagem",
            mensagem_id=mensagem_id,
            conversa_id=conversa_id,
            media_url=media_url,
            caption=caption,
            _defer_by=timedelta(seconds=3),
        )
        ROTEAR_IMAGEM_DECISAO.labels("lock_busy").inc()


async def _handoff_foto_portaria(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    atendimento_id: str,
    mensagem_id: str,
) -> None:
    """Handoff implicito da foto de portaria (06 §4).

    Le `media_object_key` da mensagem entrante (usado pelo card 'chegada' para
    anexar a imagem), delega o SQL atomico (UPDATE atendimento + bloqueio +
    escalada owner + evento) a `dominio/atendimentos/service.py`, e enfileira
    o card. Idempotencia do card: `_job_id=card:chegada:{atendimento_id}`
    (SETNX nativo do ARQ); o renderer reverifica `escaladas.card_message_id`
    antes de POSTar (06 §9).
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]

    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT media_object_key FROM barravips.mensagens WHERE id = %s",
            (UUID(mensagem_id),),
        )
        row = await res.fetchone()
        media_object_key = row["media_object_key"] if row else None

        from barra.dominio.atendimentos.service import handoff_foto_portaria_ia

        await handoff_foto_portaria_ia(
            conn,
            atendimento_id=UUID(atendimento_id),
            mensagem_id=UUID(mensagem_id),
            media_object_key=media_object_key,
        )

    await redis.enqueue_job(
        "enviar_card",
        tipo="chegada",
        atendimento_id=atendimento_id,
        _job_id=f"card:chegada:{atendimento_id}",
    )
    del conversa_id  # reservado para futuro logging; assinatura espelha o stub original


async def _ressurreicao_foto_portaria(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    mensagem_id: str,
) -> bool:
    """Tenta ressuscitar um interno auto_timeout_interno pela foto tardia (ADR 0027).

    Le `media_object_key` da mensagem, delega o SQL atomico (candidato + 4 efeitos) ao
    servico de dominio e, se reconectou, enfileira o card 'chegada' (mesma idempotencia do
    handoff normal: `_job_id=card:chegada:{atendimento_id}`). Devolve True se ressuscitou,
    False se nao havia candidato (caller segue fora-fluxo: a volta vira novo #N).
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]

    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT media_object_key FROM barravips.mensagens WHERE id = %s",
            (UUID(mensagem_id),),
        )
        row = await res.fetchone()
        media_object_key = row["media_object_key"] if row else None

        from barra.dominio.atendimentos.service import ressuscitar_interno_foto_portaria

        atendimento_id = await ressuscitar_interno_foto_portaria(
            conn,
            conversa_id=UUID(conversa_id),
            mensagem_id=UUID(mensagem_id),
            media_object_key=media_object_key,
        )

    if atendimento_id is None:
        return False

    await redis.enqueue_job(
        "enviar_card",
        tipo="chegada",
        atendimento_id=str(atendimento_id),
        _job_id=f"card:chegada:{atendimento_id}",
    )
    return True


async def transcrever_audio(
    ctx: dict[str, Any],
    *,
    mensagem_id: str,
    evolution_message_id: str,
) -> None:
    """Transcreve um audio do cliente via OpenRouter (06 §1.3).

    Pre-requisitos: a mensagem `tipo='audio'` ja foi persistida pelo webhook fino, com
    `media_object_key` apontando para um objeto OGG no MinIO (`conversas/{conversa_id}/...`).
    Esse job NAO baixa novamente da Evolution (a URL expira; 06 §0 item 2) — le do MinIO.

    Fim do job:
      - sucesso -> UPDATE `mensagens.conteudo` com a transcricao + nota; LPUSH no canal
        `transcricao:{conversa_id}` com `{"ok": true, "mensagem_id": ...}` (EXPIRE 30s).
      - audio sem fala (ou modelo devolvendo vazio) -> falha definitiva, sem retry: nao ha
        transcricao a entregar e retentar so queimaria tokens no mesmo silencio.
      - falha -> deixa o ARQ retentar (APIError 5xx, rede). Esgotado, `_falha_definitiva` grava
        o placeholder e sinaliza `{"ok": false}` para o coordenador responder canned (06 §1.4).
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]
    minio = ctx.get("minio")
    settings = ctx["settings"]
    audio_client: AsyncOpenAI | None = ctx.get("audio_client")

    inicio = perf_counter()

    # 1. carrega o objeto de midia e a conversa.
    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT conversa_id, media_object_key
              FROM barravips.mensagens
             WHERE id = %s
            """,
            (mensagem_id,),
        )
        row = await res.fetchone()
    if row is None or row["media_object_key"] is None:
        logger.warning("transcricao_sem_objeto mensagem_id=%s", mensagem_id)
        TRANSCRICAO_RESULTADO.labels("sem_audio").inc()
        await _sinalizar_canal(
            redis, str(row["conversa_id"]) if row else None, mensagem_id, ok=False
        )
        return

    conversa_id = str(row["conversa_id"])
    object_key = row["media_object_key"]

    if minio is None or audio_client is None or not settings.openrouter_api_key:
        # ambiente sem provider configurado: assina falha definitiva, sem retry (06 §1.5).
        logger.error(
            "transcricao_sem_provider mensagem_id=%s minio=%s audio_client=%s",
            mensagem_id,
            minio is not None,
            audio_client is not None,
        )
        TRANSCRICAO_RESULTADO.labels("erro_provider").inc()
        await _falha_definitiva(pool, redis, mensagem_id=mensagem_id, conversa_id=conversa_id)
        TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
        return

    # 2. baixa o audio do MinIO. minio-py e sync; rode num executor pra nao bloquear o loop.
    try:
        audio_bytes = await asyncio.to_thread(
            _baixar_minio, minio, settings.minio_bucket_media, object_key
        )
    except Exception:
        logger.exception("transcricao_minio_erro mensagem_id=%s key=%s", mensagem_id, object_key)
        TRANSCRICAO_RESULTADO.labels("erro_provider").inc()
        TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
        # Retry ARQ; se esgotar, on_job_end NAO existe -> a logica de "esgotou" cai no caller
        # via try/except dele. Aqui re-lanca.
        raise

    # 3. transcreve. O OpenRouter nao tem /audio/transcriptions: manda-se o audio como content
    #    part `input_audio` (base64) num chat completions multimodal. O cliente foi criado com
    #    timeout=60 + max_retries=3 no startup; estouros finais (APIError 5xx persistente) sobem
    #    como excecao e o ARQ retenta o job inteiro.
    modelo_stt = settings.openrouter_model_audio_transcribe or _MODELO_STT_PADRAO
    # `cast`: o TypedDict do SDK tipa `input_audio.format` como Literal["wav","mp3"] (o que a
    # OpenAI aceita), mas o OpenRouter aceita ogg/opus — o formato do WhatsApp. O wire e' JSON:
    # o campo viaja igual; so a anotacao do SDK e' estreita demais para este provider.
    conteudo_stt = cast(
        Any,
        [
            {"type": "text", "text": _PROMPT_STT},
            {
                "type": "input_audio",
                "input_audio": {
                    "data": base64.standard_b64encode(audio_bytes).decode("ascii"),
                    "format": _formato_audio(object_key),
                },
            },
        ],
    )
    try:
        resposta = await audio_client.chat.completions.create(
            model=modelo_stt,
            messages=[{"role": "user", "content": conteudo_stt}],
            temperature=0,
        )
    except APIError:
        logger.exception("transcricao_provider_erro mensagem_id=%s", mensagem_id)
        TRANSCRICAO_RESULTADO.labels("erro_provider").inc()
        TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
        raise

    # CUSTO-02: observa o custo ANTES de checar o conteudo -- transcricao vazia tambem queimou
    # tokens. Label = nome do modelo de STT (mesmo criterio do chat/vision).
    AGENTE_CUSTO_STT_BRL.labels(modelo_stt).observe(
        calcular_custo_stt_brl(getattr(resposta, "usage", None), settings.usd_brl_cotacao)
    )
    escolhas = getattr(resposta, "choices", None) or []
    texto = (escolhas[0].message.content or "").strip() if escolhas else ""
    if not texto or _SEM_FALA in texto.lower():
        # Audio sem fala (ou modelo devolvendo vazio/recusa): nao ha transcricao a entregar --
        # mesmo desfecho do retry esgotado, canned "me manda por escrito" (06 §1.5).
        logger.warning("transcricao_vazia mensagem_id=%s modelo=%s", mensagem_id, modelo_stt)
        TRANSCRICAO_RESULTADO.labels("vazio").inc()
        await _falha_definitiva(pool, redis, mensagem_id=mensagem_id, conversa_id=conversa_id)
        TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
        return
    nota = "\n_(originalmente audio)_"

    # 4. UPDATE conteudo + sinaliza canal.
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE barravips.mensagens SET conteudo = %s WHERE id = %s",
            (texto + nota, mensagem_id),
        )

    await _sinalizar_canal(redis, conversa_id, mensagem_id, ok=True)
    TRANSCRICAO_RESULTADO.labels("ok").inc()
    TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
    logger.info(
        "transcricao_ok mensagem_id=%s modelo=%s chars=%d duracao_job=%.2fs",
        mensagem_id,
        modelo_stt,
        len(texto),
        perf_counter() - inicio,
    )


def _baixar_minio(minio: Minio, bucket: str, object_key: str) -> bytes:
    """Le um objeto MinIO inteiro em memoria. Audios de WhatsApp sao curtos (<1MB tipico)."""
    resp = minio.get_object(bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


async def _sinalizar_canal(
    redis: Any, conversa_id: str | None, mensagem_id: str, *, ok: bool
) -> None:
    """LPUSH + EXPIRE 30s no canal `transcricao:{conversa_id}` (06 §1.4).

    Sem conversa_id (mensagem nao encontrada), nao ha como acordar coordenador; logamos e
    saimos — esse caminho so existe defensivamente.
    """
    if not conversa_id:
        return
    chave = f"transcricao:{conversa_id}"
    await redis.lpush(chave, json.dumps({"mensagem_id": mensagem_id, "ok": ok}))
    await redis.expire(chave, 30)


async def _falha_definitiva(pool: Any, redis: Any, *, mensagem_id: str, conversa_id: str) -> None:
    """Grava placeholder em `mensagens.conteudo` e sinaliza `{"ok": false}` (06 §1.5).

    Chamado quando nao ha provider configurado (ambiente sem chave/cliente) ou no retry esgotado
    do ARQ. O canal entrega `ok=false` -> coordenador (06 §1.4) responde canned sem invocar LLM.
    """
    # Guard p/ nao sobrescrever transcricao que ja chegou via path feliz; webhook persiste
    # audio com conteudo='' (parser.py:41), entao incluir string vazia na guard.
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE barravips.mensagens
               SET conteudo = %s
             WHERE id = %s AND (conteudo IS NULL OR conteudo = '')
            """,
            (_AUDIO_PLACEHOLDER, mensagem_id),
        )
    await _sinalizar_canal(redis, conversa_id, mensagem_id, ok=False)


# Re-exporta pra o teste poder forcar o caminho de falha definitiva sem mockar AsyncOpenAI.
async def marcar_audio_falho(
    pool: Any, redis: Any, *, mensagem_id: UUID | str, conversa_id: UUID | str
) -> None:
    """Wrapper publico de _falha_definitiva (06 §1.5)."""
    await _falha_definitiva(pool, redis, mensagem_id=str(mensagem_id), conversa_id=str(conversa_id))
