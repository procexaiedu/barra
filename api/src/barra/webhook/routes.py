import asyncio
import base64
import binascii
import hmac
import io
import logging
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, Request

from barra.core.errors import ErroDominio, JidNaoPermitido
from barra.core.evolution import EvolutionClient, envio_existe
from barra.core.metrics import COMANDOS_GRUPO, WEBHOOK_ERRORS
from barra.core.tracing import sentry_sdk
from barra.dominio.atendimentos.service import garantir_conversa, listar_pendencias_modelo
from barra.dominio.escaladas.service import Autor, aplicar_comando
from barra.webhook.despacho import enfileirar_turno
from barra.webhook.parser import MensagemEvolution, extrair_mensagem, parse_comando_grupo
from barra.webhook.reset_teste import limpar_redis_modelo, resetar_modelo
from barra.webhook.respostas import texto_confirmacao, texto_erro_comando, texto_erro_dominio
from barra.workers._cards import render_card

router = APIRouter()

_logger = logging.getLogger(__name__)

# Teto de downloads de mídia concorrentes no processo da API. O download roda inline no
# handler do webhook (antes de tocar o pool), então um burst de webhooks de mídia abriria N
# streams de até midia_max_bytes/30s cada, prendendo slots de request e saturando banda de
# entrada. Sem semáforo não há teto. Valor conservador; downloads excedentes são recusados
# (fail-fast: vira tipo='texto', webhook segue 200) em vez de enfileirados, p/ não acumular
# coroutines pendentes sob ataque.
_MAX_DOWNLOADS_MIDIA = 4
_SEM_DOWNLOAD_MIDIA = asyncio.Semaphore(_MAX_DOWNLOADS_MIDIA)

_MIME_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
}


def _host_permitido(url: str, base_url: str) -> bool:
    """A mídia só pode vir do mesmo host da Evolution (anti-SSRF). Sem base_url
    configurada não há allowlist para validar → recusa (fail-closed)."""
    if not base_url:
        return False
    alvo = urlsplit(url).hostname
    permitido = urlsplit(base_url).hostname
    if not alvo or not permitido:
        return False
    return alvo.lower() == permitido.lower()


async def _baixar_midia(url: str, base_url: str, max_bytes: int) -> tuple[bytes, str] | None:
    # Loga só o host: a media_url da Evolution carrega path/token da mídia do cliente (PII);
    # tracing.py já a trata como PII no Sentry, então não pode vazar pelo logger da aplicação.
    if not _host_permitido(url, base_url):
        _logger.warning("download_midia_host_negado host=%s", urlsplit(url).hostname)
        return None
    # Teto de concorrência (anti-DoS): recusa cedo se já há _MAX_DOWNLOADS_MIDIA em voo,
    # em vez de enfileirar espera ilimitada sob burst.
    if _SEM_DOWNLOAD_MIDIA.locked():
        _logger.warning("download_midia_concorrencia_excedida host=%s", urlsplit(url).hostname)
        return None
    try:
        async with _SEM_DOWNLOAD_MIDIA:
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream("GET", url, follow_redirects=False) as resp:
                    resp.raise_for_status()
                    ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            _logger.warning(
                                "download_midia_excede_limite host=%s limite=%d",
                                urlsplit(url).hostname,
                                max_bytes,
                            )
                            return None
            return bytes(buf), ct
    except Exception as exc:
        _logger.warning(
            "falha_download_midia host=%s erro=%s", urlsplit(url).hostname, type(exc).__name__
        )
        return None


def _decodificar_base64(b64: str, mimetype: str | None, max_bytes: int) -> tuple[bytes, str] | None:
    """Decodifica a mídia base64 inline da Evolution (WEBHOOK_BASE64). Aplica o mesmo teto de
    bytes do download e devolve (bytes, content_type) no formato de `_baixar_midia`."""
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        _logger.warning("midia_base64_invalida")
        return None
    if len(raw) > max_bytes:
        _logger.warning("midia_base64_excede_limite limite=%d", max_bytes)
        return None
    ct = (mimetype or "").split(";")[0].strip().lower()
    return raw, ct


async def _upload_minio(minio: Any, bucket: str, key: str, data: bytes, content_type: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: minio.put_object(
            bucket, key, io.BytesIO(data), len(data), content_type=content_type
        ),
    )


@router.post("/evolution")
async def evolution_webhook(
    request: Request,
    x_webhook_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    settings = request.app.state.settings
    provided = x_webhook_token or (
        authorization.removeprefix("Bearer ").strip() if authorization else None
    )
    if settings.evolution_webhook_token and (
        provided is None or not hmac.compare_digest(provided, settings.evolution_webhook_token)
    ):
        WEBHOOK_ERRORS.labels("auth").inc()
        raise ErroDominio("WEBHOOK_NAO_AUTORIZADO", "Webhook nao autorizado.", status_code=401)

    # Teto de corpo: payload legitimo da Evolution e pequeno (midia vem por URL, nao inline).
    # Rejeita cedo pelo Content-Length para nao bufferizar JSON gigante em memoria (DoS).
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > settings.webhook_max_body_bytes
    ):
        WEBHOOK_ERRORS.labels("payload_grande").inc()
        raise ErroDominio("PAYLOAD_GRANDE", "Payload excede o limite.", status_code=413)

    payload = await request.json()

    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ErroDominio("BANCO_INDISPONIVEL", "Banco indisponivel.", status_code=503)

    evento = _evento_normalizado(payload)
    if evento in {"connection.update", "qrcode.updated", "application.startup"}:
        async with pool.connection() as conn:
            return await _processar_evento_instancia(conn, payload, evento)

    msg = extrair_mensagem(payload)
    if msg is None:
        return {"status": "ignored"}
    if settings.jid_permitido and msg.remote_jid not in settings.jid_permitido:
        raise JidNaoPermitido()

    # Comando de TESTE `#reset` (gate: settings.reset_teste_instances): zera o estado
    # transacional da modelo p/ recomeçar um teste do zero. Não persiste a mensagem.
    if _eh_reset_teste(msg, settings):
        return await _processar_reset_teste(pool, request, msg)

    minio = getattr(request.app.state, "minio", None)

    # Obter os bytes da mídia antes de abrir conexão, para não segurar o pool durante I/O.
    # Com WEBHOOK_BASE64 a Evolution entrega a mídia DECIFRADA inline (sem rede); a `media_url`
    # aponta pro CDN cifrado do WhatsApp (mmg.whatsapp.net), inútil sem a mediaKey e barrado pelo
    # allowlist anti-SSRF. Sem base64, cai no download host-locked (defesa em profundidade).
    midia: tuple[bytes, str] | None = None
    if msg.tipo != "texto" and minio is not None:
        if msg.media_base64:
            midia = _decodificar_base64(
                msg.media_base64, msg.media_mimetype, settings.midia_max_bytes
            )
        elif msg.media_url:
            midia = await _baixar_midia(
                msg.media_url, settings.evolution_base_url, settings.midia_max_bytes
            )

    async with pool.connection() as conn:
        if await _mensagem_ja_persistida(conn, msg.evolution_message_id):
            return {"status": "duplicate"}
        if await _eh_grupo_coordenacao(conn, settings, msg):
            return await _processar_grupo(conn, request, msg)
        # Defesa em profundidade para mensagens de cliente: a instance precisa
        # estar cadastrada em barravips.modelos.evolution_instance_id, já que
        # o desenho do produto é 'uma instância Evolution por modelo'. Grupos
        # de coordenação usam a instance da modelo dona do grupo e já têm
        # filtragem própria por JID.
        if not await _instance_cadastrada(conn, msg.instance_id):
            WEBHOOK_ERRORS.labels("instance").inc()
            _logger.warning(
                "webhook_instance_desconhecida instance=%s",
                msg.instance_id,
            )
            return {"status": "unknown_instance"}
        conversa_id = await _persistir_cliente(conn, msg, minio, settings.minio_bucket_media, midia)

    # Webhook fino (01 §4.1 / 06 §0.1): a mensagem foi persistida orfa (atendimento_id=NULL);
    # quem resolve/cria o atendimento e roda o turno e o coordenador. So enfileira.
    arq = getattr(request.app.state, "arq", None)
    if arq is not None:
        # OBS-07: request-id da requisicao (setado pelo middleware) viaja ate o worker.
        request_id = getattr(request.state, "request_id", None)
        if msg.tipo == "texto":
            await enfileirar_turno(
                arq, conversa_id, msg.evolution_message_id, request_id=request_id
            )
        elif msg.tipo == "imagem":
            # 06 §2.1: nao roteia sincronamente — rotear_imagem decide sob lock:conv.
            await arq.enqueue_job(
                "rotear_imagem",
                mensagem_id=msg.evolution_message_id,
                conversa_id=str(conversa_id),
                media_url=msg.media_url,
                caption=msg.caption,
                _job_id=f"rotear:{msg.evolution_message_id}",
            )
        elif msg.tipo == "audio":
            # 06 §1.1: dispara transcricao em paralelo e ja enfileira o turno com
            # aguardar_transcricao=True; o coordenador faz BLPOP no canal `transcricao:{conversa_id}`
            # (06 §1.4) antes de montar a janela. O mensagem_id e o UUID interno (precisa ser
            # consultado, ja que _persistir_cliente devolve apenas conversa_id).
            mensagem_id = await _resolver_mensagem_id(pool, msg.evolution_message_id)
            if mensagem_id is not None:
                await arq.enqueue_job(
                    "transcrever_audio",
                    mensagem_id=str(mensagem_id),
                    evolution_message_id=msg.evolution_message_id,
                    _job_id=f"transcricao:{msg.evolution_message_id}",
                )
            await enfileirar_turno(
                arq,
                conversa_id,
                msg.evolution_message_id,
                aguardar_transcricao=True,
                request_id=request_id,
            )
    return {"status": "received"}


async def _resolver_mensagem_id(pool: Any, evolution_message_id: str) -> UUID | None:
    """Le `mensagens.id` (UUID interno) pelo `evolution_message_id` recem-persistido."""
    async with pool.connection() as conn:
        row = await _one(
            conn,
            "SELECT id FROM barravips.mensagens WHERE evolution_message_id = %s",
            (evolution_message_id,),
        )
    return row["id"] if row else None


def _evento_normalizado(payload: dict[str, Any]) -> str | None:
    """Normaliza CONNECTION_UPDATE/connection.update etc para a forma com
    pontos em minúsculas."""
    raw = payload.get("event")
    if not isinstance(raw, str) or not raw:
        return None
    return raw.replace("_", ".").lower()


def _extrair_state(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict):
        state = data.get("state")
        if isinstance(state, str):
            return state
    return None


def _extrair_instance_id(payload: dict[str, Any]) -> str | None:
    for chave in ("instance", "instanceName"):
        valor = payload.get(chave)
        if isinstance(valor, str) and valor:
            return valor
    data = payload.get("data")
    if isinstance(data, dict):
        for chave in ("instance", "instanceName"):
            valor = data.get(chave)
            if isinstance(valor, str) and valor:
                return valor
    return None


async def _processar_evento_instancia(
    conn: Any, payload: dict[str, Any], evento: str | None
) -> dict[str, str]:
    instance_id = _extrair_instance_id(payload)
    if not instance_id:
        return {"status": "ignored"}

    if evento == "qrcode.updated":
        # QR já é entregue ao painel via REST (POST /conectar-whatsapp).
        # Este evento serve apenas para auditoria leve.
        _logger.info("evolution_qrcode_updated instance=%s", instance_id)
        return {"status": "qrcode_logged"}

    if evento == "application.startup":
        _logger.info("evolution_application_startup instance=%s", instance_id)
        return {"status": "startup_logged"}

    # evento == 'connection.update'
    state = _extrair_state(payload)
    if state == "open":
        await conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_status = 'conectado',
                   evolution_pareado_em = now()
             WHERE evolution_instance_id = %s
            """,
            (instance_id,),
        )
        return {"status": "connection_open"}
    if state == "close":
        # Não zeramos evolution_instance_id — apenas marcamos desconectado.
        # Limpeza completa só acontece em /desparear-whatsapp.
        await conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_status = 'desconectado'
             WHERE evolution_instance_id = %s
            """,
            (instance_id,),
        )
        return {"status": "connection_close"}
    if state == "connecting":
        await conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_status = 'pareando'
             WHERE evolution_instance_id = %s
               AND evolution_status <> 'conectado'
            """,
            (instance_id,),
        )
        return {"status": "connection_connecting"}
    return {"status": "ignored"}


async def _instance_cadastrada(conn: Any, instance_id: str | None) -> bool:
    if not instance_id:
        return False
    row = await _one(
        conn,
        "SELECT 1 FROM barravips.modelos WHERE evolution_instance_id = %s LIMIT 1",
        (instance_id,),
    )
    return row is not None


async def _eh_grupo_coordenacao(conn: Any, settings: Any, msg: MensagemEvolution) -> bool:
    """Reconhece se a mensagem veio de um grupo de Coordenação por modelo.

    Cada modelo tem o SEU grupo (`barravips.modelos.coordenacao_chat_id`), então o
    reconhecimento é por banco (índice parcial `modelos_coordenacao_chat_idx`), nunca
    por um JID único global — senão só uma modelo teria os comandos de grupo
    (`ia assume`, `finalizado`, `perdido`) processados, e as respostas nos grupos das
    demais cairiam no ramo de cliente. O escopo por modelo/instance é garantido depois
    em `_processar_grupo` (`_modelo_por_instance`).

    `settings.evolution_grupo_coordenacao_jid` segue como atalho opcional de teste
    (Fase 1.5): quando definido e batendo, dispensa a ida ao banco.
    """
    jid = settings.evolution_grupo_coordenacao_jid
    if jid and msg.remote_jid == jid:
        return True
    if not msg.remote_jid.endswith("@g.us"):
        return False
    row = await _one(
        conn,
        "SELECT 1 FROM barravips.modelos WHERE coordenacao_chat_id = %s LIMIT 1",
        (msg.remote_jid,),
    )
    return row is not None


async def _processar_grupo(conn: Any, request: Request, msg: MensagemEvolution) -> dict[str, str]:
    settings = request.app.state.settings
    if await envio_existe(conn, msg.evolution_message_id):
        return {"status": "outbound_ignored"}
    autor = _autor_grupo(settings.evolution_fernando_jids, msg)
    if autor is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        return {"status": "ignored"}

    quoted_numero: int | None = None
    aguardando_valor = False
    if msg.quoted_message_id:
        quoted_numero, aguardando_valor = await _resolver_card(conn, msg.quoted_message_id)
    comando = parse_comando_grupo(msg.texto, quoted_numero, aguardando_valor=aguardando_valor)
    if comando is None:
        return {"status": "ignored"}

    # Digest de pendencias (UX §6.4): comando sem `#N`, so leitura — lista o que aguarda a modelo
    # dona do grupo. Antes do gate de `#N` obrigatorio, que nao se aplica aqui.
    if comando.comando == "listar_pendencias":
        return await _responder_pendencias(settings, conn, msg)

    # Sem #N nao da pra escopar o atendimento (o parser ja marcou comando_invalido). Responde com
    # recuperacao (§6.2) e para — fora de resposta-quote a um card, o #N e obrigatorio.
    if comando.numero_curto is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        await _responder_grupo(settings, conn, msg, texto_erro_comando("numero_curto_ausente"))
        return {"status": "invalid"}

    # numero_curto e UNIQUE por (modelo_id, numero_curto), nao global: dois grupos de Coordenacao
    # distintos podem ter o mesmo #N. Escopar pela modelo dona da instance evita afetar o
    # atendimento de outra modelo (isolamento cross-modelo).
    modelo_id = await _modelo_por_instance(conn, msg.instance_id)
    if modelo_id is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        _logger.warning("comando_grupo_modelo_nao_resolvida instance=%s", msg.instance_id)
        return {"status": "unknown_instance"}
    atendimento_id = await _atendimento_por_numero(conn, comando.numero_curto, modelo_id)
    if atendimento_id is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        await _responder_grupo(
            settings, conn, msg, texto_erro_comando("atendimento_nao_encontrado")
        )
        return {"status": "invalid"}

    try:
        await aplicar_comando(
            conn,
            origem="grupo_coordenacao",
            autor=autor,
            atendimento_id=atendimento_id,
            comando=comando.comando,
            payload=comando.payload
            | {"texto": msg.texto, "evolution_message_id": msg.evolution_message_id},
        )
    except ErroDominio as exc:
        # Comando humano malformado/conflitante (ex.: `finalizado` em atendimento ja finalizado ->
        # ConflitoEstado 409; motivo `outro` sem observacao -> EntradaInvalida 422). Reprocessar nao
        # corrige, e mensagens de grupo nao sao persistidas em `mensagens` (sem dedupe inbound),
        # entao um nao-2xx faria a Evolution reentregar e reprocessar em loop. Damos ack (200),
        # registramos e respondemos com recuperacao (§6.2).
        COMANDOS_GRUPO.labels("invalido").inc()
        _logger.info(
            "comando_grupo_erro codigo=%s atendimento=%s msg=%s",
            exc.code,
            atendimento_id,
            exc.message,
        )
        await _responder_grupo(settings, conn, msg, texto_erro_dominio(exc.code))
        return {"status": "command_error"}

    # comando_invalido com #N valido (valor ambiguo / sem valor / sem motivo): aplicar_comando so
    # registrou o evento de auditoria, nao transicionou. Responde com recuperacao (§6.2).
    if comando.comando == "comando_invalido":
        COMANDOS_GRUPO.labels("invalido").inc()
        await _responder_grupo(
            settings, conn, msg, texto_erro_comando(comando.payload.get("motivo"))
        )
        return {"status": "invalid"}

    # Sucesso: eco de confirmacao curto (§6.1) — nunca sucesso silencioso (CONTEXT "Registro de
    # resultado"; o undo e o "Corrigir" no painel, nao um dialogo bloqueante).
    COMANDOS_GRUPO.labels("valido").inc()
    await _responder_grupo(
        settings,
        conn,
        msg,
        texto_confirmacao(comando.comando, comando.payload, comando.numero_curto),
        tipo="confirmacao",
    )
    return {"status": "processed"}


async def _responder_pendencias(settings: Any, conn: Any, msg: MensagemEvolution) -> dict[str, str]:
    """Monta e envia o digest de pendencias (UX §6.4) no grupo da modelo dona da instance.

    Escopa por modelo (isolamento por par): a query so ve atendimentos dessa modelo. A tolerancia
    do `falta_valor` espelha o Lembrete de fechamento (mesmo gatilho). Envio best-effort via
    `_responder_grupo` (tipo='card')."""
    modelo_id = await _modelo_por_instance(conn, msg.instance_id)
    if modelo_id is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        _logger.warning("digest_pendencias_modelo_nao_resolvida instance=%s", msg.instance_id)
        return {"status": "unknown_instance"}
    pendencias = await listar_pendencias_modelo(
        conn, modelo_id, tolerancia_min=settings.lembrete_valor_tolerancia_min
    )
    COMANDOS_GRUPO.labels("digest").inc()
    texto = render_card("pendencias", pendencias=pendencias)
    await _responder_grupo(settings, conn, msg, texto, tipo="card")
    return {"status": "digest"}


async def _responder_grupo(
    settings: Any,
    conn: Any,
    msg: MensagemEvolution,
    texto: str,
    tipo: str = "erro_comando",
) -> None:
    """Envia uma resposta curta (confirmacao §6.1 / erro §6.2) de volta ao grupo de Coordenacao,
    no mesmo canal de onde o comando veio (instance da modelo + JID do grupo).

    Best-effort: o comando ja foi aplicado (ou rejeitado) e committado; uma falha de envio NAO pode
    quebrar o ack 200 do webhook (um nao-2xx faria a Evolution reentregar e reaplicar). Sem
    `evolution_base_url` (testes / Evolution off) vira no-op. A transacao garante que o
    `envios_evolution` do eco committe — e o proximo webhook desse proprio eco (fromMe) cai no
    `envio_existe` (outbound_ignored), sem loop."""
    try:
        async with conn.transaction():
            await EvolutionClient(settings).enviar_texto(
                conn=conn,
                instance_id=msg.instance_id,
                remote_jid=msg.remote_jid,
                texto=texto,
                contexto="grupo_coordenacao",
                tipo=tipo,
            )
    except Exception:
        _logger.warning(
            "resposta_grupo_falhou tipo=%s msg=%s", tipo, msg.evolution_message_id, exc_info=True
        )


async def _persistir_cliente(
    conn: Any,
    msg: MensagemEvolution,
    minio: Any,
    bucket: str,
    midia: tuple[bytes, str] | None,
) -> UUID:
    """Persiste a mensagem do cliente como orfa (atendimento_id=NULL) e devolve o conversa_id.

    Webhook fino (06 §0.1): faz upsert apenas da CONVERSA do par; quem resolve/cria o
    atendimento e cobre as orfas e o coordenador (`processar_turno`), sob `lock:conv`.
    """
    async with conn.transaction():
        modelo = await _one(
            conn,
            "SELECT id FROM barravips.modelos WHERE evolution_instance_id = %s",
            (msg.instance_id,),
        )
        if modelo is None:
            raise ErroDominio("MODELO_NAO_RESOLVIDA", "Modelo nao resolvida.", status_code=404)
        telefone = msg.remote_jid.split("@", 1)[0]
        cliente = await _one(
            conn,
            """
            INSERT INTO barravips.clientes (telefone, primeiro_contato_modelo_id)
            VALUES (%s, %s)
            ON CONFLICT (telefone) DO UPDATE SET telefone = EXCLUDED.telefone
            RETURNING *
            """,
            (telefone, modelo["id"]),
        )
        assert cliente is not None
        conversa_id = await garantir_conversa(
            conn,
            cliente_id=cliente["id"],
            modelo_id=modelo["id"],
            evolution_chat_id=msg.remote_jid,
        )

        # Fazer upload da mídia para MinIO e obter a key permanente. Sem atendimento, a key
        # deriva da conversa (06 §0.1 #2). Se falhar, gravar como tipo='texto' p/ satisfazer
        # a constraint de DB.
        media_key: str | None = None
        tipo_db = msg.tipo
        if msg.tipo != "texto" and midia is not None and minio is not None:
            data, ct = midia
            ext = _MIME_EXT.get(ct, ".jpg" if msg.tipo == "imagem" else ".ogg")
            key = f"conversas/{conversa_id}/mensagens/{msg.evolution_message_id}{ext}"
            try:
                await _upload_minio(minio, bucket, key, data, ct or "application/octet-stream")
                media_key = key
            except Exception as exc:
                # REL-06: falha de upload nao pode ser silenciosa. A midia vira 'texto' abaixo
                # (constraint de DB), mas a operacao precisa ver -- para Pix, `validar_pix` marca
                # em_revisao e o atendimento avanca em vez de virar Perdido no timeout-24h.
                _logger.warning("falha_upload_minio key=%s erro=%s", key, exc)
                WEBHOOK_ERRORS.labels("midia_upload").inc()
                if sentry_sdk is not None:
                    sentry_sdk.capture_exception(exc)

        # Constraint: tipo != 'texto' requer media_object_key NOT NULL.
        if msg.tipo != "texto" and media_key is None:
            tipo_db = "texto"
            _logger.warning(
                "midia_sem_upload_salva_como_texto evolution_id=%s tipo_original=%s",
                msg.evolution_message_id,
                msg.tipo,
            )

        # atendimento_id=NULL: orfa intencional, coberta depois pelo coordenador (07 §3.2).
        await conn.execute(
            """
            INSERT INTO barravips.mensagens (
              conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id
            )
            VALUES (%s, %s, 'cliente', %s, %s, %s, %s)
            ON CONFLICT (evolution_message_id) DO NOTHING
            """,
            (
                conversa_id,
                None,
                tipo_db,
                msg.texto,
                media_key,
                msg.evolution_message_id,
            ),
        )
    return conversa_id


async def _mensagem_ja_persistida(conn: Any, evolution_message_id: str) -> bool:
    row = await _one(
        conn,
        "SELECT 1 FROM barravips.mensagens WHERE evolution_message_id = %s",
        (evolution_message_id,),
    )
    return row is not None


async def _resolver_card(conn: Any, card_message_id: str) -> tuple[int | None, bool]:
    """Resolve um card citado -> (numero_curto, é_card_de_Lembrete_de_fechamento).

    Olha primeiro `envios_evolution` (cobre o card do Lembrete de fechamento e qualquer outbound
    backend ligado a atendimento; ADR-0009); cai para `escaladas.card_message_id` (handoffs)."""
    row = await _one(
        conn,
        """
        SELECT a.numero_curto, (e.payload->>'card_kind' = 'lembrete_valor') AS lembrete
          FROM barravips.envios_evolution e
          JOIN barravips.atendimentos a ON a.id = e.atendimento_id
         WHERE e.evolution_message_id = %s
        """,
        (card_message_id,),
    )
    if row is not None:
        return row["numero_curto"], bool(row["lembrete"])
    return await _numero_por_card(conn, card_message_id), False


async def _numero_por_card(conn: Any, card_message_id: str | None) -> int | None:
    if not card_message_id:
        return None
    row = await _one(
        conn,
        """
        SELECT a.numero_curto
          FROM barravips.escaladas e
          JOIN barravips.atendimentos a ON a.id = e.atendimento_id
         WHERE e.card_message_id = %s
        """,
        (card_message_id,),
    )
    return row["numero_curto"] if row else None


async def _modelo_por_instance(conn: Any, instance_id: str | None) -> Any | None:
    if not instance_id:
        return None
    row = await _one(
        conn,
        "SELECT id FROM barravips.modelos WHERE evolution_instance_id = %s",
        (instance_id,),
    )
    return row["id"] if row else None


async def _atendimento_por_numero(conn: Any, numero_curto: int, modelo_id: Any) -> Any | None:
    row = await _one(
        conn,
        """
        SELECT id FROM barravips.atendimentos
         WHERE numero_curto = %s AND modelo_id = %s AND estado NOT IN ('Fechado', 'Perdido')
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        (numero_curto, modelo_id),
    )
    return row["id"] if row else None


async def _one(conn: Any, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return cast(dict[str, Any] | None, await result.fetchone())


def _autor_grupo(fernando_jids: list[str], msg: MensagemEvolution) -> Autor | None:
    if msg.sender_jid and msg.sender_jid in fernando_jids:
        return "Fernando"
    if msg.from_me:
        return "modelo"
    return None


def _eh_reset_teste(msg: MensagemEvolution, settings: Any) -> bool:
    """Comando de TESTE `#reset`: zera o estado da modelo p/ recomeçar do zero. Gate por
    instância em `settings.reset_teste_instances` (vazio por padrão = desligado), então em
    produção real é inerte e o texto seguiria como mensagem normal de cliente."""
    return (
        msg.tipo == "texto"
        and msg.texto.strip().lower() == "#reset"
        and msg.instance_id in settings.reset_teste_instances
    )


async def _processar_reset_teste(
    pool: Any, request: Request, msg: MensagemEvolution
) -> dict[str, str]:
    """Zera o estado transacional da modelo, limpa o Redis e confirma no grupo. Não persiste
    a mensagem `#reset`. Reusa o mesmo wipe do `scripts/reset_agente.py` (`reset_teste`)."""
    settings = request.app.state.settings
    async with pool.connection() as conn:
        resultado = await resetar_modelo(conn, msg.instance_id)
    if resultado is None:
        return {"status": "reset_instancia_desconhecida"}

    # Redis fora da transação do banco: falha de limpeza não desfaz o wipe (ids viram lixo inerte).
    arq = getattr(request.app.state, "arq", None)
    try:
        await limpar_redis_modelo(arq, resultado["conversa_ids"], resultado["atendimento_ids"])
    except Exception:
        _logger.warning("reset_teste_redis_falhou instance=%s", msg.instance_id)

    # Confirmação no grupo (best-effort, conexão nova: o wipe já commitou).
    try:
        async with pool.connection() as conn_conf:
            await EvolutionClient(settings).enviar_texto(
                conn=conn_conf,
                instance_id=msg.instance_id,
                remote_jid=msg.remote_jid,
                texto="✅ Atendimento resetado. Pode começar do zero.",
                contexto="conversa_cliente",
                tipo="confirmacao",
            )
    except Exception:
        _logger.warning("reset_teste_confirmacao_falhou instance=%s", msg.instance_id)

    _logger.info(
        "reset_teste_aplicado instance=%s contagens=%s", msg.instance_id, resultado["contagens"]
    )
    return {"status": "reset"}
