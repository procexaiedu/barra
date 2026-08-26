import asyncio
import base64
import binascii
import hashlib
import hmac
import io
import json
import logging
import re
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, Request

from barra.agente_financeiro.comprovante import leitor_de_comprovante
from barra.agente_financeiro.leitura import leitor_de_intencao
from barra.agente_financeiro.porta import (
    EnviarNoGrupo,
    de_evolution,
    delecao_de_evolution,
    processar_delecao_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.agente_financeiro.transcricao import ouvinte_do_grupo
from barra.core.errors import ErroDominio, JidNaoPermitido
from barra.core.evolution import EvolutionClient, envio_existe
from barra.core.feedback_inbox import (
    emitir_feedback_inbox,
    montar_inbox_payload,
    parse_rodape_issue,
)
from barra.core.metrics import COMANDOS_GRUPO, WEBHOOK_DESCARTES, WEBHOOK_ERRORS
from barra.core.tracing import sentry_sdk
from barra.dominio.atendimentos.service import garantir_conversa, listar_pendencias_modelo
from barra.dominio.escaladas.service import Autor, aplicar_comando
from barra.webhook.despacho import enfileirar_turno
from barra.webhook.parser import (
    MensagemEvolution,
    _numero_curto,
    adaptar_webhook_go,
    extrair_delecao,
    extrair_mensagem,
    parse_comando_grupo,
)
from barra.webhook.reset_teste import limpar_redis_modelo, resetar_modelo
from barra.webhook.respostas import texto_confirmacao, texto_erro_comando, texto_erro_dominio
from barra.workers._cards import render_card

router = APIRouter()

_logger = logging.getLogger(__name__)

# ACK de registro do rig de feedback: janela de debounce e piso de substância (texto abaixo disso
# — 'blz', 'ok' — não arma o ack; mídia sempre arma). Ver `_capturar_feedback_rig`.
_ACK_DEBOUNCE_S = 120
_ACK_MIN_CHARS = 20

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

# evolution_message_id e o `key.id` da stanza WhatsApp -- 100% controlado pelo remetente do webhook
# (cf. bug Evolution #1916, ids anomalos). Ele entra cru no path da chave de objeto MinIO
# (`conversas/{conversa_id}/mensagens/{id}{ext}`); sem sanitizar, um id com `../` escaparia o
# prefixo da conversa e sobrescreveria a midia de OUTRO atendimento (o pipeline de Pix rele essa
# key e a manda a vision). Trocamos todo char fora de [A-Za-z0-9._-] por `_` -- mata `/` e portanto
# a travessia (chaves S3/MinIO sao planas: sem `/` nao ha como mudar de prefixo). IDs reais do
# WhatsApp sao alfanumericos -> passam intactos, nenhuma mensagem descartada. A COLUNA
# evolution_message_id segue com o id CRU (chave de dedupe `ON CONFLICT`); so o path e' sanitizado.
_ID_OBJETO_INSEGURO = re.compile(r"[^A-Za-z0-9._-]")


def _segmento_objeto_seguro(valor: str) -> str:
    seguro = _ID_OBJETO_INSEGURO.sub("_", valor)[:128]
    if seguro in ("", ".", ".."):
        seguro = "sem_id"
    elif seguro == valor:
        return seguro  # id ja seguro (caso comum: WhatsApp alfanumerico) -> intacto, sem hash
    # Sanitizou (ou degenerou): a substituicao e' many-to-one, entao ids distintos poderiam colapsar
    # na MESMA key e o 2o upload sobrescreveria a midia do 1o (ex.: comprovante de Pix) DENTRO da
    # mesma conversa. Anexa um hash curto do id CRU p/ reatar a injetividade (ids distintos -> keys
    # distintas), mantendo o determinismo por id (mesmo id -> mesma key, replay-safe).
    sufixo = hashlib.sha256(valor.encode()).hexdigest()[:8]
    return seguro[:119] + "_" + sufixo


def _host_permitido(url: str, base_url: str, hosts_extra: list[str] | None = None) -> bool:
    """A mídia só pode vir do host da Evolution ou de um host explicitamente permitido
    (anti-SSRF). Sem base_url nem hosts_extra não há allowlist → recusa (fail-closed). O
    `hosts_extra` cobre a Evolution GO, cuja mídia inbound (WEBHOOK_FILES) vem do MinIO dela, num
    host distinto do `evolution_base_url` — configurado em `settings.evolution_media_hosts`."""
    alvo = urlsplit(url).hostname
    if not alvo:
        return False
    alvo = alvo.lower()
    permitidos: set[str] = set()
    base_host = urlsplit(base_url).hostname if base_url else None
    if base_host:
        permitidos.add(base_host.lower())
    for h in hosts_extra or []:
        h = h.strip().lower()
        if h:
            permitidos.add(h)
    return alvo in permitidos


async def _baixar_midia(
    url: str, base_url: str, max_bytes: int, hosts_extra: list[str] | None = None
) -> tuple[bytes, str] | None:
    # Loga só o host: a media_url da Evolution carrega path/token da mídia do cliente (PII);
    # tracing.py já a trata como PII no Sentry, então não pode vazar pelo logger da aplicação.
    if not _host_permitido(url, base_url, hosts_extra):
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


# A EvoGo sobe a mídia decifrada no MinIO dela ANTES de disparar o webhook, mas por pouco (~50ms
# medidos em prod, 24/07). Uma segunda olhada depois desta espera cobre a corrida; no caso feliz o
# objeto já está lá e ela nunca acontece.
_ESPERA_MIDIA_EVOGO_S = 0.5


def _ler_midia_evogo(
    minio: Any, bucket: str, prefix: str, message_id: str, max_bytes: int
) -> tuple[bytes, str] | None:
    """Lê a mídia inbound já DECIFRADA do bucket da Evolution GO (sync — roda em executor).

    A EvoGo não entrega base64 inline nem URL baixável: ela decifra a mídia e a sobe no MinIO com
    key `<prefix><evolution_message_id>.<ext>`. A extensão varia (ogg/jpg/webp), então resolvemos
    por PREFIXO em vez de adivinhar. Devolve `(bytes, content_type)` como `_baixar_midia`.
    """
    objetos = list(minio.list_objects(bucket, prefix=f"{prefix}{message_id}.", recursive=True))
    if not objetos:
        return None
    obj = objetos[0]
    if obj.size is not None and obj.size > max_bytes:
        _logger.warning("midia_evogo_excede_limite key=%s limite=%d", obj.object_name, max_bytes)
        return None
    resp = minio.get_object(bucket, obj.object_name)
    try:
        # Lê no máximo max_bytes+1 (o extra denuncia o estouro): o `size` da listagem já barra o
        # caso normal, mas se ele vier ausente não podemos puxar um objeto gigante pra memória.
        dados = resp.read(max_bytes + 1)
        cabecalhos = getattr(resp, "headers", None) or {}
    finally:
        resp.close()
        resp.release_conn()
    if len(dados) > max_bytes:
        _logger.warning("midia_evogo_excede_limite key=%s limite=%d", obj.object_name, max_bytes)
        return None
    ct = (cabecalhos.get("content-type") or "").split(";")[0].strip().lower()
    return dados, ct


async def _buscar_midia_evogo(
    minio: Any, settings: Any, msg: MensagemEvolution
) -> tuple[bytes, str] | None:
    """Fallback de mídia inbound da Evolution GO: busca no bucket dela (ver `_ler_midia_evogo`)."""
    if _ID_OBJETO_INSEGURO.search(msg.evolution_message_id):
        # O id é 100% controlado pelo remetente e entra no prefixo da listagem; ids reais do
        # WhatsApp são alfanuméricos, então recusamos em vez de sanitizar (a key na EvoGo usa o
        # id CRU — um id sanitizado não acharia objeto nenhum).
        _logger.warning("midia_evogo_id_invalido tipo=%s", msg.tipo)
        return None
    for tentativa in (1, 2):
        try:
            midia = await asyncio.to_thread(
                _ler_midia_evogo,
                minio,
                settings.evogo_media_bucket,
                settings.evogo_media_prefix,
                msg.evolution_message_id,
                settings.midia_max_bytes,
            )
        except Exception as exc:
            # Bucket inexistente, credencial sem policy nele, MinIO fora: degrada para o
            # comportamento antigo (mensagem vira 'texto'). Nunca 500 no webhook — a Evolution
            # trata erro como falha de entrega e reenviaria em loop.
            _logger.warning("midia_evogo_erro erro=%s", type(exc).__name__)
            WEBHOOK_ERRORS.labels("midia_evogo").inc()
            return None
        if midia is not None:
            return midia
        if tentativa == 1:
            await asyncio.sleep(_ESPERA_MIDIA_EVOGO_S)
    _logger.warning(
        "midia_evogo_ausente evolution_id=%s tipo=%s", msg.evolution_message_id, msg.tipo
    )
    WEBHOOK_ERRORS.labels("midia_evogo").inc()
    return None


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
    # O token chega por header (`X-Webhook-Token` ou `Authorization: Bearer`) quando a Evolution
    # entrega direto na Barra. Com o webhook-router no meio (instancia -> router -> Barra) o header
    # de auth NAO e repassado e o modal do router so guarda Nome+URL (sem campo de header), entao
    # aceitamos o token tambem via `?token=` na query — o unico canal de credencial que o router
    # preserva. Tradeoff conhecido: a query entra no access log do uvicorn; aceitavel aqui porque o
    # token e interno (== EVOLUTION_API_KEY, ja em texto no env do stack) e o trafego e na rede
    # overlay privada do Swarm. O caminho limpo de longo prazo e o router repassar o header.
    provided = (
        x_webhook_token
        or (authorization.removeprefix("Bearer ").strip() if authorization else None)
        or request.query_params.get("token")
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
    # Evolution GO (whatsmeow): converte o envelope CamelCase (`data.Info`/`data.Message`,
    # `instanceName`, eventos `Message`/`Connection`) para o shape v2 que todo o resto do módulo
    # já parseia. Payload v2 (ou não-Go) passa reto — compat durante a transição.
    if isinstance(payload, dict):
        payload = adaptar_webhook_go(payload)

    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ErroDominio("BANCO_INDISPONIVEL", "Banco indisponivel.", status_code=503)

    evento = _evento_normalizado(payload)
    if evento in {"connection.update", "qrcode.updated", "application.startup"}:
        async with pool.connection() as conn:
            return await _processar_evento_instancia(conn, payload, evento)

    # Mensagem apagada para todos (spec 0005, ticket 05): o gesto com que o Grupo financeiro
    # corrige uma venda (apaga e reposta). Vem antes do `extrair_mensagem` porque ele devolve
    # None para `protocolMessage`/`messages.delete` — sem este ramo o evento morria no descarte
    # e a venda anunciada na mensagem apagada continuaria no extrato. Quem decide se o grupo
    # importa e a porta única (closed-world contra `grupos_financeiros`), como no ramo de
    # mensagem logo abaixo; delecao em qualquer outro chat segue o fluxo normal (e e ignorada).
    delecao = extrair_delecao(payload)
    if delecao is not None and delecao.remote_jid.endswith("@g.us"):
        async with pool.connection() as conn:
            resultado_delecao = await processar_delecao_do_grupo(
                conn, delecao_de_evolution(delecao)
            )
        if resultado_delecao.status != "grupo_nao_cadastrado":
            return {"status": f"grupo_financeiro_{resultado_delecao.status}"}

    msg = extrair_mensagem(payload)
    if msg is None:
        _registrar_descarte(payload)
        return {"status": "ignored"}

    # Ingestão do rig de feedback (gate: settings.feedback_rig_grupo_jid): a mensagem do grupo de
    # feedback vira inbox no Langfuse p/ a skill /processar-feedbacks. O grupo de feedback é um JID
    # interno de dev, fora do jid_permitido (flag de teste da Fase 1.5) — por isso captura ANTES do
    # gate, senão cairia em JidNaoPermitido. Curto-circuita antes do fluxo de cliente: não persiste,
    # não abre pool, não decodifica mídia (base64 já vem no msg).
    if _eh_grupo_feedback(msg, settings):
        return await _capturar_feedback_rig(request, msg)

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
                msg.media_url,
                settings.evolution_base_url,
                settings.midia_max_bytes,
                settings.evolution_media_hosts,
            )
        if midia is None and settings.evogo_media_bucket:
            # EvoGo: nenhum dos dois caminhos acima existe — nem base64 inline nem URL baixável.
            # A mídia decifrada mora no bucket dela; sem este fallback toda mídia inbound (áudio,
            # comprovante de Pix, Foto de portaria) degradava para 'texto' vazio.
            midia = await _buscar_midia_evogo(minio, settings, msg)

    async with pool.connection() as conn:
        if await _mensagem_ja_persistida(conn, msg.evolution_message_id):
            return {"status": "duplicate"}
        if await _eh_grupo_coordenacao(conn, settings, msg):
            return await _processar_grupo(conn, request, msg, midia)
        # Grupo que NAO e o de Coordenacao: descarta aqui, antes do ramo de cliente. Sem este
        # gate o fluxo seguia adiante e `_resolver_identidade_cliente` fazia
        # `remote_jid.split("@")[0]` no JID do grupo, gravando `120363…` em `clientes.telefone`
        # (coluna `text`, sem CHECK de digitos) — cliente-fantasma, e a IA passava a VENDER
        # dentro do grupo. Nao e hipotetico: a modelo opera no NUMERO PESSOAL dela, que ja vive
        # em grupo de familia e de amigas, e o `jid_permitido` (flag de teste da Fase 1.5) esta
        # vazio em prod, entao nada mais segurava.
        #
        # Mesmo criterio do ramo `@lid` sem `remoteJidAlt` logo abaixo, e pelo mesmo motivo:
        # identificador opaco nao e telefone, e a chave do Cliente e o E.164 (CONTEXT "Cliente").
        # Um grupo so entra pelo ramo de cima, batendo `modelos.coordenacao_chat_id` — ou pelo
        # ramo do Grupo financeiro logo abaixo, batendo `grupos_financeiros.jid` (spec 0005).
        # 200 (nao 4xx) para a Evolution dar ack e nao reentregar em loop.
        if msg.remote_jid.endswith("@g.us"):
            # Grupo financeiro (spec 0005): destino NOVO da rota compartilhada do numero ProceX
            # (o mesmo webhook-router que serve o myEYE). Quem decide se este grupo e um Grupo
            # financeiro e a PORTA UNICA — closed-world contra `grupos_financeiros`, nao um JID
            # em settings. O webhook segue fino: nao classifica, nao responde, nao persiste em
            # `mensagens` (o log de origem do modulo e outro). Grupo desconhecido pela porta cai
            # no descarte de sempre logo abaixo.
            # `midia` (os bytes ja decifrados, obtidos acima) entra junto porque a modelo responde
            # por AUDIO — "foi pix", "600", "é a Duda" chegam falados (spec 0005, ticket 06) — e
            # porque ela manda o COMPROVANTE do Pix em foto (ticket 07). A porta transcreve/le e
            # segue; sem bytes ou sem provider ela registra a mensagem e fica calada, nunca levanta
            # (levantar aqui viraria reentrega em loop da Evolution).
            if _e_a_instancia_da_procex(settings, msg):
                resultado_financeiro = await processar_mensagem_do_grupo(
                    conn,
                    de_evolution(msg, midia=midia),
                    # Modo só escuta (`grupo_financeiro_responde=False`, o default): a porta
                    # roda inteira e não diz nada. `enviar=None` não é um remendo — é o modo
                    # que o replay e o backfill já usam, e nele a porta também não grava a
                    # linha `de_mim`, então a trava de "já perguntei" não se auto-silencia
                    # por uma fala que ninguém leu.
                    enviar=(
                        _falar_no_grupo_financeiro(settings, msg)
                        if settings.grupo_financeiro_responde
                        else None
                    ),
                    transcrever=ouvinte_do_grupo(settings),
                    ler_comprovante=leitor_de_comprovante(settings),
                    ler_intencao=leitor_de_intencao(settings),
                )
                if resultado_financeiro.status != "grupo_nao_cadastrado":
                    return {"status": f"grupo_financeiro_{resultado_financeiro.status}"}
            WEBHOOK_DESCARTES.labels("grupo_nao_coordenacao").inc()
            _logger.info(
                "webhook_grupo_nao_coordenacao instance=%s remote_jid=%s",
                msg.instance_id,
                msg.remote_jid,
            )
            return {"status": "grupo_nao_coordenacao"}
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
        # WhatsApp LID: o cliente é identificado pelo telefone E.164, nunca pelo @lid (CONTEXT
        # "Cliente"). Resolve telefone + chat_id antes de persistir; sem E.164 confiável (@lid sem
        # remoteJidAlt) NÃO grava o LID — descarta com 200 (fail-closed) p/ a Evolution dar ack.
        identidade = _resolver_identidade_cliente(msg)
        if identidade is None:
            WEBHOOK_ERRORS.labels("lid_sem_telefone").inc()
            _logger.warning("webhook_lid_sem_telefone remote_jid=%s", msg.remote_jid)
            return {"status": "lid_sem_telefone"}
        telefone, chat_jid = identidade
        # fromMe no 1:1 é ambíguo (webhook/CLAUDE.md): eco do envio da própria IA (registrado em
        # envios_evolution pelo `enviar_turno`) OU a modelo digitando manualmente no mesmo número.
        # Eco → ignora; modelo manual → persiste com direcao='modelo_manual' (mvp/05 §4.2/§5.3;
        # `prepare_context` a traduz como AIMessage prefixada) e NÃO enfileira turno — a IA
        # absorve no contexto do próximo turno e aguarda a próxima mensagem DO CLIENTE.
        if msg.from_me:
            if await envio_existe(conn, msg.evolution_message_id):
                return {"status": "outbound_ignored"}
            await _persistir_cliente(
                conn,
                msg,
                minio,
                settings.minio_bucket_media,
                midia,
                telefone,
                chat_jid,
                direcao="modelo_manual",
            )
            return {"status": "modelo_manual"}
        conversa_id = await _persistir_cliente(
            conn, msg, minio, settings.minio_bucket_media, midia, telefone, chat_jid
        )

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


def _registrar_descarte(payload: dict[str, Any]) -> None:
    """Telemetria do descarte na borda (`extrair_mensagem` -> None).

    O ramo devolvia 200 'ignored' MUDO: tipo que o parser nao reconhece (pin sem coords, vCard,
    enquete, tipo novo do WhatsApp) sumia sem log nem metrica, e a operacao so via um "Mensagem
    nao suportada" no celular -- sem nada do lado de ca para dizer o que era (analise do #36,
    24/07). Registra so o NOME do campo (`locationMessage`, `contactMessage`...), nunca o
    conteudo: e telemetria de borda hostil, nao dump de payload de cliente.
    """
    data = payload.get("data")
    message = data.get("message") if isinstance(data, dict) else None
    chaves = sorted(k for k in message) if isinstance(message, dict) else []
    # Label de cardinalidade contida: o 1o campo `*Message` do payload nomeia o tipo.
    tipo = next((k for k in chaves if k.endswith("Message")), "sem_message")
    WEBHOOK_DESCARTES.labels(tipo).inc()
    _logger.info("webhook_mensagem_descartada tipo=%s campos=%s", tipo, ",".join(chaves))


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


def _falar_no_grupo_financeiro(settings: Any, msg: MensagemEvolution) -> EnviarNoGrupo:
    """Entregador do que a porta única do Agente financeiro decidir dizer (recibo, spec 0005).

    A porta decide o texto E o alvo do quote; a rede fica aqui.

    **A instância é a da ProceX, nunca a da modelo** — o mesmo invariante que o cron enuncia
    (`workers/rotina_financeira`). Não dá para confiar na instância que entregou o evento: a
    modelo é participante do próprio Grupo financeiro e o WhatsApp dela É uma instância Evolution
    apontando para este mesmo webhook, então o evento chega DUAS vezes e a corrida decide qual
    entrega vence o dedup. Se vencesse a dela, o recibo "✅ Registrei…" sairia assinado pelo
    número pessoal da modelo. `settings.grupo_financeiro_instancia` é a fonte; o fallback para
    `msg.instance_id` só existe para ambiente que ainda não a configurou (o ramo do webhook
    também deixa de filtrar as entregas espelhadas nesse caso — ver `_e_a_instancia_da_procex`).

    `enviar_texto_avulso` (e não `enviar_texto`) porque `envios_evolution` só aceita
    `conversa_cliente`/`grupo_coordenacao` como contexto: o grupo financeiro não é nenhum dos
    dois. `citar` vem da porta: o recibo cita o ANÚNCIO (que pode não ser a mensagem que entrou,
    quando o registro foi destravado por uma resposta), e é isso que dá ao grupo o gesto de
    corrigir respondendo (ticket 05). Falha de rede é absorvida pela porta — recibo perdido não
    desfaz venda.
    """
    instancia = settings.grupo_financeiro_instancia or msg.instance_id

    async def enviar(texto: str, *, citar: str | None = None) -> None:
        await EvolutionClient(settings).enviar_texto_avulso(
            instance_id=instancia,
            remote_jid=msg.remote_jid,
            texto=texto,
            quoted_message_id=citar or msg.evolution_message_id or None,
        )

    return enviar


def _e_a_instancia_da_procex(settings: Any, msg: MensagemEvolution) -> bool:
    """Esta entrega veio pela instância do Agente financeiro (a da ProceX)?

    O Grupo financeiro tem a modelo dentro (docs/dominio/grupo-financeiro.md) e o WhatsApp dela é
    uma instância Evolution cadastrada apontando para este webhook. Logo TODA mensagem do grupo
    chega duas vezes — pela ProceX e pela instância dela — com a mesma `chave_dedup`
    (`evo:<message_id>`), e quem processa é quem chega primeiro. Isso não é só desperdício:
    `fromMe` é relativo à instância que entregou, então na entrega da modelo as mensagens DELA
    ("foi pix", "600", o comprovante) chegam com `fromMe=true` e morrem como `eco_do_agente`,
    enquanto o recibo do próprio agente chega com `fromMe=false` e volta para o processamento —
    exatamente o que o corte de eco existe para impedir.

    Descartar a entrega espelhada resolve os três de uma vez. Fail-OPEN quando
    `grupo_financeiro_instancia` está vazia: sem ela não há como saber qual entrega é a boa, e
    desligar o módulo em silêncio seria pior — a mesma variável já é o kill-switch declarado da
    rotina da manhã, e prod a define.
    """
    instancia = settings.grupo_financeiro_instancia
    return not instancia or msg.instance_id == instancia


async def _processar_grupo(
    conn: Any, request: Request, msg: MensagemEvolution, midia: tuple[bytes, str] | None
) -> dict[str, str]:
    settings = request.app.state.settings
    if await envio_existe(conn, msg.evolution_message_id):
        return {"status": "outbound_ignored"}
    autor = _autor_grupo(settings.evolution_fernando_jids, msg)
    if autor is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        return {"status": "ignored"}

    # modelos.status <> 'ativa' e o kill-switch oficial da IA (CONTEXT.md "Modelo"). No caminho de
    # cliente ele ja bloqueia via ia_pausada (workers/coordenador.py); aqui e o unico ponto comum a
    # TODO comando/comprovante/digest de grupo, entao e o lugar certo pra garantir que nenhum envio
    # de saida (confirmacao/erro/card) saia em nome de uma instance pausada — inclusive quando o
    # grupo fisico e compartilhado com outro numero que nao deve responder por nos (ex.: lucia).
    # Instance desconhecida (status None) NAO bloqueia aqui — segue pro unknown_instance de sempre
    # mais adiante, que ja lida com esse caso.
    status_modelo = await _status_modelo_por_instance(conn, msg.instance_id)
    if status_modelo is not None and status_modelo != "ativa":
        COMANDOS_GRUPO.labels("modelo_pausada").inc()
        return {"status": "modelo_pausada"}

    quoted_numero: int | None = None
    aguardando_valor = False
    if msg.quoted_message_id:
        quoted_numero, aguardando_valor = await _resolver_card(conn, msg.quoted_message_id)

    # Comprovante de Pix como fechamento (auto-baixa): uma imagem no grupo respondendo o card (ou
    # com #N na legenda) fecha o atendimento pelo valor lido no comprovante — augmenta o
    # `fechado [valor]` de texto com OCR. Trilho proprio (o parser de texto nao le imagem).
    if msg.tipo == "imagem":
        return await _processar_comprovante_grupo(conn, request, msg, midia, autor, quoted_numero)

    comando = parse_comando_grupo(msg.texto, quoted_numero, aguardando_valor=aguardando_valor)
    if comando is None:
        return {"status": "ignored"}
    return await _despachar_comando_grupo(request, conn, msg, comando, autor)


async def _despachar_comando_grupo(
    request: Request, conn: Any, msg: MensagemEvolution, comando: Any, autor: Autor
) -> dict[str, str]:
    """Aplica um `ComandoGrupo` ja parseado (de texto OU de legenda de comprovante) e responde.

    Extraido de `_processar_grupo` para o caminho de imagem reusar quando a legenda ja traz um
    comando completo ("valor digitado vence": `fechado 1500` na legenda nao aciona OCR)."""
    settings = request.app.state.settings
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
            | {
                "texto": msg.texto or msg.caption or "",
                "evolution_message_id": msg.evolution_message_id,
            },
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


async def _processar_comprovante_grupo(
    conn: Any,
    request: Request,
    msg: MensagemEvolution,
    midia: tuple[bytes, str] | None,
    autor: Autor,
    quoted_numero: int | None,
) -> dict[str, str]:
    """Imagem no grupo de Coordenacao = comprovante de Pix -> auto-fechamento (auto-baixa).

    Ancora EXPLICITA (CONTEXT "Card"/"Registro de resultado"): so fecha com quote no card ou #N na
    legenda — nunca casa por horario/valor. "Valor digitado vence": se a legenda ja traz um comando
    COMPLETO (`fechado 1500`, `perdido sumiu`), segue o trilho de texto sem OCR. Senao, resolve o
    #N, sobe o comprovante ao MinIO e enfileira `fechar_via_comprovante` (OCR + fecha). Escopo: so
    Pix — dinheiro/cartao seguem no `fechado [valor]` manual.
    """
    settings = request.app.state.settings

    # "Valor digitado vence": legenda parseada SEM o caminho de "valor pelado" (aguardando_valor=
    # False) — assim "#42" na legenda e ancora, nao o valor 42. So delega quando ha um comando
    # completo; `fechado` sem valor cai no OCR (a foto tem o valor).
    comando = parse_comando_grupo(msg.caption or "", quoted_numero, aguardando_valor=False)
    if comando is not None and comando.comando in (
        "registrar_fechado",
        "registrar_perdido",
        "devolver_para_ia",
        "pausar_ia",
    ):
        return await _despachar_comando_grupo(request, conn, msg, comando, autor)

    numero = (_numero_curto(msg.caption) if msg.caption else None) or quoted_numero
    if numero is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        await _responder_grupo(settings, conn, msg, texto_erro_comando("numero_curto_ausente"))
        return {"status": "invalid"}

    modelo_id = await _modelo_por_instance(conn, msg.instance_id)
    if modelo_id is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        _logger.warning("comprovante_grupo_modelo_nao_resolvida instance=%s", msg.instance_id)
        return {"status": "unknown_instance"}
    atendimento_id = await _atendimento_por_numero(conn, numero, modelo_id)
    if atendimento_id is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        await _responder_grupo(
            settings, conn, msg, texto_erro_comando("atendimento_nao_encontrado")
        )
        return {"status": "invalid"}

    # Sem imagem utilizavel (falha de download/base64 ou MinIO off) nao ha o que ler: sem OCR nao
    # da pra fabricar o valor_final (constraint), entao pede o valor por texto (nao e uma "rede"
    # sobre valor lido — e a ausencia dele).
    minio = getattr(request.app.state, "minio", None)
    if midia is None or minio is None:
        await _responder_grupo(settings, conn, msg, texto_erro_comando("valor_final_obrigatorio"))
        return {"status": "invalid"}

    # Sobe o comprovante ao MinIO (o grupo nao persiste em `mensagens`; chave por atendimento). O
    # evolution_message_id vai sanitizado no path (mesmo cuidado anti-travessia do 1:1).
    data, ct = midia
    ext = _MIME_EXT.get(ct, ".jpg")
    key = (
        f"comprovantes_fechamento/{atendimento_id}/"
        f"{_segmento_objeto_seguro(msg.evolution_message_id)}{ext}"
    )
    try:
        await _upload_minio(
            minio, settings.minio_bucket_media, key, data, ct or "application/octet-stream"
        )
    except Exception as exc:
        _logger.warning("comprovante_upload_falhou key=%s erro=%s", key, type(exc).__name__)
        WEBHOOK_ERRORS.labels("midia_upload").inc()
        await _responder_grupo(settings, conn, msg, texto_erro_comando("valor_final_obrigatorio"))
        return {"status": "invalid"}

    # OCR + fechamento sao assincronos (OpenRouter nao pode segurar o webhook): o worker le o MinIO,
    # extrai o valor e fecha pela porta unica, respondendo o grupo. _job_id por evolution_message_id
    # dedup o evento duplicado do WhatsApp (multi-device).
    arq = getattr(request.app.state, "arq", None)
    if arq is not None:
        await arq.enqueue_job(
            "fechar_via_comprovante",
            atendimento_id=str(atendimento_id),
            object_key=key,
            evolution_message_id=msg.evolution_message_id,
            _job_id=f"fechar_comprovante:{msg.evolution_message_id}",
        )
    COMANDOS_GRUPO.labels("comprovante").inc()
    return {"status": "comprovante_enfileirado"}


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


def _resolver_identidade_cliente(msg: MensagemEvolution) -> tuple[str, str] | None:
    """(telefone E.164, evolution_chat_id) de uma mensagem 1:1 de cliente, ou None quando o
    telefone real nao esta disponivel.

    WhatsApp LID (CONTEXT "Cliente" = telefone E.164, unico; nunca o @lid): quando o
    `remoteJid` vem como `<id-opaco>@lid`, o split daria o LID — que nao casa o cliente entre
    contatos (recorrencia) nem com o numero. A Evolution entrega o E.164 real em `remoteJidAlt`
    (`<telefone>@s.whatsapp.net`); usamos ele tanto p/ telefone quanto p/ chat_id — responder
    para um `@lid` falha (Evolution #1585). Sem `remoteJidAlt` nao ha E.164 confiavel: devolve
    None (fail-closed — nunca grava LID como telefone). Para `remoteJid` que ja nao e `@lid`,
    mantem o comportamento atual (split direto).
    """
    if msg.remote_jid.endswith("@lid"):
        alt = msg.remote_jid_alt
        if not alt:
            return None
        # `<telefone>[:device]@s.whatsapp.net` -> so os digitos do numero; o chat_id e
        # reconstruido sem o device (responder com `:device` no JID e fragil).
        telefone = alt.split("@", 1)[0].split(":", 1)[0]
        if not telefone.isdigit():
            return None
        return telefone, f"{telefone}@s.whatsapp.net"
    return msg.remote_jid.split("@", 1)[0], msg.remote_jid


async def _persistir_cliente(
    conn: Any,
    msg: MensagemEvolution,
    minio: Any,
    bucket: str,
    midia: tuple[bytes, str] | None,
    telefone: str,
    chat_jid: str,
    direcao: str = "cliente",
) -> UUID:
    """Persiste a mensagem da conversa 1:1 como orfa (atendimento_id=NULL) e devolve o conversa_id.

    Webhook fino (06 §0.1): faz upsert apenas da CONVERSA do par; quem resolve/cria o
    atendimento e cobre as orfas e o coordenador (`processar_turno`), sob `lock:conv`.
    `direcao` e 'cliente' (inbound) ou 'modelo_manual' (fromMe digitado pela modelo).
    """
    async with conn.transaction():
        modelo = await _one(
            conn,
            "SELECT id FROM barravips.modelos WHERE evolution_instance_id = %s",
            (msg.instance_id,),
        )
        if modelo is None:
            raise ErroDominio("MODELO_NAO_RESOLVIDA", "Modelo nao resolvida.", status_code=404)
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
            evolution_chat_id=chat_jid,
        )

        # Fazer upload da mídia para MinIO e obter a key permanente. Sem atendimento, a key
        # deriva da conversa (06 §0.1 #2). Se falhar, gravar como tipo='texto' p/ satisfazer
        # a constraint de DB.
        media_key: str | None = None
        tipo_db = msg.tipo
        if msg.tipo != "texto" and midia is not None and minio is not None:
            data, ct = midia
            ext = _MIME_EXT.get(ct, ".jpg" if msg.tipo == "imagem" else ".ogg")
            key = f"conversas/{conversa_id}/mensagens/{_segmento_objeto_seguro(msg.evolution_message_id)}{ext}"
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
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (evolution_message_id) DO NOTHING
            """,
            (
                conversa_id,
                None,
                direcao,
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


async def _status_modelo_por_instance(conn: Any, instance_id: str | None) -> str | None:
    """`modelos.status` da instance, ou None se a instance nao resolve p/ nenhuma modelo (deixa o
    unknown_instance de cada handler tratar esse caso, sem mudar aquele comportamento)."""
    if not instance_id:
        return None
    row = await _one(
        conn,
        "SELECT status::text AS status FROM barravips.modelos WHERE evolution_instance_id = %s",
        (instance_id,),
    )
    return cast(str, row["status"]) if row else None


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


def _eh_grupo_feedback(msg: MensagemEvolution, settings: Any) -> bool:
    """Mensagem do grupo de feedback do rig (skill /processar-feedbacks). Gate por JID em
    `settings.feedback_rig_grupo_jid` (None por padrão = desligado). Só NÃO-fromMe: pega o
    comentário/áudio/print do Fernando e ignora o eco do reply-marcador postado pela própria IA
    (senão a captura entraria em loop consigo mesma)."""
    return (
        settings.feedback_rig_grupo_jid is not None
        and msg.remote_jid == settings.feedback_rig_grupo_jid
        and not msg.from_me
    )


def _feedback_tem_substancia(msg: MensagemEvolution) -> bool:
    """Só arma o ACK de registro para mensagem com substância — mídia (print/áudio de feedback) ou
    texto com um mínimo de caracteres. Evita responder a ruído de grupo ('blz', 'ok'). A captura do
    trace segue indiscriminada (é barata; a skill filtra o que vira issue)."""
    if msg.tipo != "texto":
        return True
    return len((msg.texto or "").strip()) >= _ACK_MIN_CHARS


async def _capturar_feedback_rig(request: Request, msg: MensagemEvolution) -> dict[str, str]:
    """Deposita a mensagem do grupo de feedback como inbox no Langfuse e curto-circuita — não
    persiste no banco, não abre pool, não decodifica mídia (o base64 já vem inline no `msg`) e não
    gasta LLM. O STT/vision do áudio/print roda dev-time na skill, não aqui. Se `feedback_rig_ack`
    estiver ligado, agenda um ACK de registro (debounce ~2 min, best-effort)."""
    payload = montar_inbox_payload(
        message_id=msg.evolution_message_id,
        remote_jid=msg.remote_jid,
        autor=msg.sender_jid,
        tipo=msg.tipo,
        texto=msg.texto,
        caption=msg.caption,
        media_base64=msg.media_base64,
        media_mimetype=msg.media_mimetype,
    )
    trace_id = emitir_feedback_inbox(payload, message_id=msg.evolution_message_id)
    _logger.info(
        "feedback_rig_capturado message_id=%s trace_id=%s", msg.evolution_message_id, trace_id
    )
    settings = request.app.state.settings
    arq = getattr(request.app.state, "arq", None)
    if settings.feedback_rig_ack and arq is not None and _feedback_tem_substancia(msg):
        # Debounce ~2 min coalescido por grupo (`_job_id` estático SET NX first-wins): o 1º feedback
        # da rajada agenda o ack citando a própria mensagem; os seguintes na janela não duplicam.
        try:
            await arq.enqueue_job(
                "enviar_ack_feedback_rig",
                remote_jid=msg.remote_jid,
                instance_id=msg.instance_id,
                quoted_message_id=msg.evolution_message_id,
                quoted_text=(msg.texto or msg.caption or ""),
                _job_id=f"ack_fb:{msg.remote_jid}",
                _defer_by=timedelta(seconds=_ACK_DEBOUNCE_S),
            )
        except Exception:
            _logger.warning("feedback_rig_ack_enqueue_falhou", exc_info=True)
    # trace_id None (tracing off/erro) vira "" na resposta HTTP; o valor real fica no log acima.
    return {"status": "feedback_rig", "trace_id": trace_id or ""}


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, str]:
    """Webhook do GitHub p/ o loop de 'desenvolvido' do rig de feedback. No fecho de uma issue que
    carrega o rodapé `feedback-rig`, a lucia responde citando a mensagem original do Rossi no grupo,
    fechando o loop. Gate: `github_webhook_secret` (None = desligado, eventos ignorados). Fora do
    fluxo de cliente; ferramenta de DEV. Idempotência: `_job_id=dev_fb:{message_id}` coalesce a
    reentrega comum do GitHub num aviso só."""
    settings = request.app.state.settings
    if not settings.github_webhook_secret:
        return {"status": "github_webhook_off"}

    raw = await request.body()
    esperado = (
        "sha256="
        + hmac.new(settings.github_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    )
    if not x_hub_signature_256 or not hmac.compare_digest(esperado, x_hub_signature_256):
        WEBHOOK_ERRORS.labels("github_auth").inc()
        raise ErroDominio("WEBHOOK_NAO_AUTORIZADO", "Assinatura invalida.", status_code=401)

    if x_github_event != "issues":
        return {"status": "ignored"}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"status": "ignored"}
    if payload.get("action") != "closed":
        return {"status": "ignored"}

    meta = parse_rodape_issue((payload.get("issue") or {}).get("body"))
    if meta is None:
        return {"status": "sem_rodape_feedback"}

    arq = getattr(request.app.state, "arq", None)
    if arq is not None:
        await arq.enqueue_job(
            "enviar_aviso_desenvolvido",
            remote_jid=meta["remote_jid"],
            instance_id=settings.evolution_instancia,
            quoted_message_id=meta["message_id"],
            quoted_text=meta["texto"],
            _job_id=f"dev_fb:{meta['message_id']}",
        )
    return {"status": "aviso_desenvolvido"}


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
