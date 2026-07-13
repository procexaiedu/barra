"""Cliente HTTP Evolution GO (whatsmeow) e registro transacional de outbound.

Migrado da Evolution v2/v3 (Baileys) para a Evolution GO (`evogo.procexai.tech`). Diferenças
estruturais que moldam este módulo:

- **Auth por instância**: os endpoints de operação (`/send/*`, `/message/*`, `/group/*`) NÃO
  levam a instância no path nem no body — a instância é resolvida pelo **token próprio dela** no
  header `apikey`. A GLOBAL_API_KEY só serve para gestão (`/instance/all`, `/instance/create`).
  Guardamos o nome da instância em `modelos.evolution_instance_id` (identidade estável, também
  usada no webhook); o token é resolvido em runtime via `GET /instance/all` e cacheado
  (`_resolver_token`), invalidado no 401. Assim não guardamos segredo por modelo no nosso banco.
- **Endpoints**: `sendText/{inst}`→`/send/text`; `sendMedia`(base64)→`/send/media`(URL);
  `markMessageAsRead`→`/message/markread {number,id[]}`; `sendPresence`→`/message/presence`;
  `findGroupInfos`→`/group/info {groupJid}`; o webhook é setado no `/instance/connect`
  (`webhookUrl`+`subscribe[]`) — não há `/webhook/set`.
- **Respostas em PascalCase**: `/instance/qr` (`data.Qrcode`), `/instance/status`
  (`data.Connected`/`data.LoggedIn`) e `/group/info` (`Participants[].JID/PhoneNumber`) vêm com
  inicial maiúscula; `/instance/all` é a exceção (minúsculo). Normalizamos aqui, na fronteira,
  para os shapes que os callers (`_extrair_qr_code`, `_extrair_membros`) já consomem.
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Any
from uuid import UUID

import httpx
from psycopg import AsyncConnection

from barra.core.errors import ErroDominio
from barra.core.metrics import ENVIOS_EVOLUTION
from barra.settings import Settings

_logger = logging.getLogger(__name__)

# Eventos assinados no /instance/connect. Nomes reais (UPPER_SNAKE) vistos no campo `events` do
# GET /instance/all da EvoGo — o payload do webhook usa CamelCase (`Message`), mas o SUBSCRIBE é
# UPPER_SNAKE. Barra precisa de: MESSAGE (inbound), SEND_MESSAGE (eco fromMe p/ dedupe/modelo
# manual), CONNECTION (pareamento) e QRCODE (QR rotacionado).
_EVENTOS_WEBHOOK = ["MESSAGE", "SEND_MESSAGE", "CONNECTION", "QRCODE"]

# Marker `[quote]`/`[quote: trecho]` da humanização (workers/_chunking). É instrução
# INTERNA — o chunk o extrai do prefixo da bolha e nunca deve sobrar no texto enviado.
# Um `[quote]` visível entrega na hora que do outro lado é uma IA, não a modelo.
_MARKER_QUOTE = re.compile(r"\[quote\b[^\]]*\]", re.IGNORECASE)
_ESPACO_HORIZONTAL = re.compile(r"[ \t]{2,}")

# Cache nome→token da instância (EvoGo escopa operação pelo token no header `apikey`). Módulo-level
# porque `EvolutionClient` é instanciado por request/worker: uma resolução serve todo o processo.
# Chaveado por (base_url, nome) p/ isolar ambientes/testes. Invalidado no 401 (token rotacionado).
_TOKEN_CACHE: dict[tuple[str, str], str] = {}
_TOKEN_LOCK = asyncio.Lock()


def limpar_cache_tokens() -> None:
    """Zera o cache de tokens de instância (usado por testes; em prod o 401 já invalida)."""
    _TOKEN_CACHE.clear()


def _remover_markers_quote(texto: str) -> str:
    """Rede de segurança final: remove qualquer marker `[quote...]` residual em QUALQUER
    posição antes de mandar ao cliente. O chunk já tira o marker no prefixo correto; isto
    cobre os erros de formatação do LLM (marker no meio da linha, sem linha em branco antes,
    variação de sintaxe) que escapariam do chunk. Preserva `\\n`; colapsa só o espaço
    horizontal que a remoção deixa para trás."""
    if not _MARKER_QUOTE.search(texto):
        return texto
    _logger.warning("marker [quote] residual removido antes do envio (chunk nao pegou)")
    limpo = _ESPACO_HORIZONTAL.sub(" ", _MARKER_QUOTE.sub("", texto))
    return "\n".join(linha.strip() for linha in limpo.split("\n")).strip()


def _numero_destino(remote_jid: str) -> str:
    """Normaliza o `number` que a EvoGo espera nos endpoints de operação. Grupo (`@g.us`) vai
    inteiro (a EvoGo roteia pelo JID de grupo); 1:1 vira só os dígitos do telefone (sem
    `@servidor` nem sufixo `:device`), como o padrão de envio validado da EvoGo."""
    if remote_jid.endswith("@g.us"):
        return remote_jid
    return remote_jid.split("@", 1)[0].split(":", 1)[0]


def _quoted_body(quoted_message_id: str) -> dict[str, Any]:
    """Bloco `quoted` do /send da EvoGo. Diferente da v2 (que ecoava o texto citado porque não
    fazia lookup): a EvoGo (whatsmeow, DATABASE_SAVE_MESSAGES=true) resolve a citação pelo id
    guardado, então basta o `messageId` — o balão renderiza o snippet real sozinho."""
    return {"messageId": quoted_message_id}


class EvolutionClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _base(self) -> str:
        return self.settings.evolution_base_url.rstrip("/")

    async def _resolver_token(self, instance_id: str, *, forcar: bool = False) -> str:
        """Resolve o token da instância (nome→token) via GET /instance/all (global key), cacheado.
        `forcar=True` ignora o cache (revalidação pós-401). Levanta ErroDominio quando a instância
        não existe na EvoGo."""
        chave = (self._base(), instance_id)
        if not forcar and chave in _TOKEN_CACHE:
            return _TOKEN_CACHE[chave]
        async with _TOKEN_LOCK:
            if not forcar and chave in _TOKEN_CACHE:
                return _TOKEN_CACHE[chave]
            url = f"{self._base()}/instance/all"
            headers = {"apikey": self.settings.evolution_api_key}
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
            # Direto da EvoGo o corpo é {data: [ {name, token, ...} ], message}.
            instancias = data.get("data") if isinstance(data, dict) else data
            if isinstance(instancias, list):
                for item in instancias:
                    if isinstance(item, dict) and item.get("name") == instance_id:
                        token = item.get("token")
                        if isinstance(token, str) and token:
                            _TOKEN_CACHE[chave] = token
                            return token
            raise ErroDominio(
                "EVOLUTION_INSTANCIA_NAO_EXISTE",
                f"Instancia '{instance_id}' nao encontrada na Evolution GO.",
                status_code=502,
            )

    async def _headers_instancia(self, instance_id: str) -> dict[str, str]:
        return {"apikey": await self._resolver_token(instance_id)}

    async def _post_operacao(
        self, instance_id: str, path: str, body: dict[str, Any], *, timeout_s: float
    ) -> httpx.Response:
        """POST num endpoint de operação escopado pelo token da instância. No 401 (token
        rotacionado/inválido em cache) re-resolve o token uma vez e repete."""
        url = f"{self._base()}{path}"
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                url, json=body, headers=await self._headers_instancia(instance_id)
            )
            if response.status_code == 401:
                token = await self._resolver_token(instance_id, forcar=True)
                response = await client.post(url, json=body, headers={"apikey": token})
        response.raise_for_status()
        return response

    async def enviar_texto(
        self,
        *,
        conn: AsyncConnection[Any],
        instance_id: str,
        remote_jid: str,
        texto: str,
        contexto: str,
        tipo: str,
        atendimento_id: UUID | None = None,
        conversa_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        quoted_message_id: str | None = None,
        quoted_text: str | None = None,
    ) -> str:
        if not self.settings.evolution_base_url:
            raise ErroDominio(
                "EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503
            )

        body: dict[str, Any] = {
            "number": _numero_destino(remote_jid),
            "text": _remover_markers_quote(texto),
        }
        if quoted_message_id:
            body["quoted"] = _quoted_body(quoted_message_id)
        response = await self._post_operacao(instance_id, "/send/text", body, timeout_s=20)
        data = response.json()

        evolution_message_id = _extrair_message_id(data)
        if not evolution_message_id:
            ENVIOS_EVOLUTION.labels("falha").inc()
            raise ErroDominio(
                "EVOLUTION_RESPOSTA_INVALIDA", "Evolution nao retornou id.", status_code=502
            )

        await registrar_envio(
            conn,
            evolution_message_id=evolution_message_id,
            instance_id=instance_id,
            remote_jid=remote_jid,
            contexto=contexto,
            tipo=tipo,
            atendimento_id=atendimento_id,
            conversa_id=conversa_id,
            # Marcador do caller (ex.: {"card_kind": ...}) MESCLA sobre a resposta da Evolution,
            # nao a substitui: a auditoria preserva o payload completo (texto reconstrutivel) e
            # ainda carrega o marcador queryavel. `payload or data` puro perdia o `data` (#7).
            payload={**data, **payload} if payload else data,
        )
        ENVIOS_EVOLUTION.labels("sucesso").inc()
        return evolution_message_id

    async def enviar_midia(
        self,
        *,
        conn: AsyncConnection[Any],
        instance_id: str,
        remote_jid: str,
        url: str,
        caption: str | None,
        media_type: str,
        contexto: str,
        tipo: str,
        view_once: bool = False,
        atendimento_id: UUID | None = None,
        conversa_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        quoted_message_id: str | None = None,
        quoted_text: str | None = None,
    ) -> str:
        """Espelha enviar_texto para mídia: POST /send/media → registra em envios_evolution →
        devolve evolution_message_id. A EvoGo baixa a `url` (pública, ex.: MinIO) e sobe pro
        WhatsApp — o mesmo trilho por-URL que a barra já usa (nunca base64 cru no campo `url`).

        `media_type` do domínio ('foto'/'video'/'audio', midia_tipo_enum) é traduzido para o
        `type` que a EvoGo aceita (image/video/audio): 'foto'→'image'; os demais passam intactos.

        `view_once` (Mídia exclusiva, 01 §6.13) NÃO é suportado pelo /send/media da EvoGo (o body
        não expõe o campo) — mantido na assinatura por compat dos callers, mas o campo é sempre
        omitido (a mídia vai normal, mesmo comportamento do toggle-off na v2). `quoted_text` idem:
        a EvoGo resolve a citação pelo id (não precisa do texto ecoado)."""
        if not self.settings.evolution_base_url:
            raise ErroDominio(
                "EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503
            )

        media_type_evo = "image" if media_type == "foto" else media_type
        body: dict[str, Any] = {
            "number": _numero_destino(remote_jid),
            "type": media_type_evo,
            "url": url,
        }
        if caption:
            body["caption"] = _remover_markers_quote(caption)
        if quoted_message_id:
            body["quoted"] = _quoted_body(quoted_message_id)
        response = await self._post_operacao(instance_id, "/send/media", body, timeout_s=30)
        data = response.json()

        evolution_message_id = _extrair_message_id(data)
        if not evolution_message_id:
            ENVIOS_EVOLUTION.labels("falha").inc()
            raise ErroDominio(
                "EVOLUTION_RESPOSTA_INVALIDA", "Evolution nao retornou id.", status_code=502
            )

        await registrar_envio(
            conn,
            evolution_message_id=evolution_message_id,
            instance_id=instance_id,
            remote_jid=remote_jid,
            contexto=contexto,
            tipo=tipo,
            atendimento_id=atendimento_id,
            conversa_id=conversa_id,
            payload={**data, **payload} if payload else data,
        )
        ENVIOS_EVOLUTION.labels("sucesso").inc()
        return evolution_message_id

    async def enviar_texto_sem_registro(
        self, *, instance_id: str, remote_jid: str, texto: str
    ) -> None:
        """Envio de texto que NÃO grava em envios_evolution — para canais de infra (relay de
        alertas DEV, `api/alertas.py`), que não são evento operacional de atendimento. Levanta em
        falha (o caller decide o status HTTP)."""
        if not self.settings.evolution_base_url:
            raise ErroDominio(
                "EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503
            )
        body = {"number": _numero_destino(remote_jid), "text": texto}
        await self._post_operacao(instance_id, "/send/text", body, timeout_s=15)

    async def marcar_lida(
        self,
        *,
        instance_id: str,
        remote_jid: str,
        message_ids: list[str],
    ) -> None:
        """Read receipt das mensagens do cliente (humano lê antes de responder, 05 §4.2).
        NÃO entra em envios_evolution — é recibo de leitura, não outbound de mensagem.
        EvoGo: POST /message/markread com `{number, id: [...]}`."""
        if not self.settings.evolution_base_url:
            raise ErroDominio(
                "EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503
            )
        body = {"number": _numero_destino(remote_jid), "id": message_ids}
        await self._post_operacao(instance_id, "/message/markread", body, timeout_s=15)

    async def set_presence(
        self,
        *,
        instance_id: str,
        remote_jid: str,
        presence: str,
        delay_ms: int,
    ) -> None:
        """Indicador "digitando…"/"gravando…" antes do envio (05 §4). Best-effort: falha de rede
        loga e segue, nunca estoura o turno de envio. Não grava nada.

        EvoGo: POST /message/presence `{number, state, isAudio}`. O `presence` do domínio
        ('composing'/'recording') vira `state='composing'` com `isAudio=True` para gravação de
        áudio; 'paused'/desconhecido vira `state='paused'`. A EvoGo não tem `delay` na presença —
        `delay_ms` é ignorado (mantido na assinatura por compat)."""
        if not self.settings.evolution_base_url:
            return
        gravando = presence in ("recording", "audio")
        state = "composing" if presence in ("composing", "recording", "audio") else "paused"
        body = {"number": _numero_destino(remote_jid), "state": state, "isAudio": gravando}
        try:
            await self._post_operacao(instance_id, "/message/presence", body, timeout_s=10)
        except (httpx.HTTPError, ErroDominio) as exc:
            _logger.warning("evolution_set_presence_falhou instance=%s erro=%s", instance_id, exc)

    async def conectar_instancia(self, instance_id: str) -> dict[str, Any]:
        """POST /instance/connect (seta webhook + subscribe) e busca o QR em GET /instance/qr.
        Retorna `{qrcode, code}` normalizado (a EvoGo devolve `data.Qrcode`/`data.Code` em
        PascalCase) — o shape que `_extrair_qr_code` consome."""
        if not self.settings.evolution_base_url:
            return {"status": "not_configured", "instance_id": instance_id}
        await self._connect(instance_id, immediate=True)
        return await self._buscar_qr(instance_id)

    async def _connect(self, instance_id: str, *, immediate: bool) -> None:
        """POST /instance/connect com webhook + subscribe. `immediate=True` força uma nova sessão
        (pareamento); `False` só reafirma o webhook numa instância já existente (definir_webhook)."""
        body: dict[str, Any] = {"immediate": immediate, "subscribe": _EVENTOS_WEBHOOK}
        callback = self._webhook_url()
        if callback:
            body["webhookUrl"] = callback
        url = f"{self._base()}/instance/connect"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url, json=body, headers=await self._headers_instancia(instance_id)
            )
            if response.status_code == 401:
                token = await self._resolver_token(instance_id, forcar=True)
                response = await client.post(url, json=body, headers={"apikey": token})
        response.raise_for_status()

    async def _buscar_qr(self, instance_id: str) -> dict[str, Any]:
        url = f"{self._base()}/instance/qr"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=await self._headers_instancia(instance_id))
        response.raise_for_status()
        data = response.json()
        payload = data.get("data") if isinstance(data, dict) else None
        inner = payload if isinstance(payload, dict) else data if isinstance(data, dict) else {}
        # PascalCase (gotcha EvoGo): `Qrcode` é o data URL do PNG; `Code` é o texto cru do QR.
        qrcode = inner.get("Qrcode") or inner.get("qrcode") or inner.get("base64")
        code = inner.get("Code") or inner.get("code")
        return {"qrcode": qrcode, "code": code, "instance_id": instance_id}

    async def criar_instancia(
        self,
        instance_id: str,
        *,
        numero: str | None = None,
    ) -> dict[str, Any]:
        """POST /instance/create (global key). A EvoGo EXIGE o campo `token` (a apikey da própria
        instância) — geramos um UUID; ele é depois lido de volta via /instance/all na resolução.
        NÃO devolve QR (isso é o /instance/connect + /instance/qr) → o caller cai no
        conectar_instancia para o pareamento. `numero` é aceito por compat mas não usado no create
        da EvoGo (o número entra no pareamento). Instância já existente é idempotente (o connect
        seguinte usa o token já cadastrado)."""
        if not self.settings.evolution_base_url:
            return {"status": "not_configured", "instance_id": instance_id}
        url = f"{self._base()}/instance/create"
        headers = {"apikey": self.settings.evolution_api_key}
        body: dict[str, Any] = {"name": instance_id, "token": str(uuid.uuid4())}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=body, headers=headers)
        if response.status_code == 401:
            _logger.error(
                "evolution_instance_create_sem_permissao instance=%s body=%s",
                instance_id,
                response.text[:300],
            )
            raise ErroDominio(
                "EVOLUTION_CHAVE_SEM_CREATE",
                "A GLOBAL_API_KEY da Evolution GO nao tem permissao para criar instancias "
                "(401). Confirme EVOLUTION_API_KEY.",
                status_code=502,
            )
        # Instância já existe → idempotente: o connect seguinte resolve o token existente via
        # /instance/all e recupera o QR. A EvoGo sinaliza "já existe" de forma inconsistente: além
        # dos 400/403/409 clássicos, o /instance/create devolve **HTTP 500** com corpo
        # `{"error":"instance already exists"}` (verificado ao vivo 12/07). Por isso casamos tanto
        # os códigos conhecidos quanto a mensagem no corpo — sem tratar QUALQUER 500 como exists
        # (mascararia erro real), só o que a EvoGo marca explicitamente como duplicado.
        ja_existe = response.status_code in {400, 403, 409} or (
            not response.is_success and "already exists" in response.text.lower()
        )
        if ja_existe:
            _logger.info(
                "evolution_instance_create_ja_existe instance=%s status=%s",
                instance_id,
                response.status_code,
            )
            return {"status": "exists", "instance_id": instance_id}
        response.raise_for_status()
        return {"status": "created", "instance_id": instance_id}

    async def definir_webhook(self, instance_id: str) -> bool:
        """Reafirma o webhook numa instância já existente. Na EvoGo não há `/webhook/set` — o
        webhook vive no /instance/connect; reemitimos o connect com `immediate=False` (sem forçar
        nova sessão) só para (re)gravar `webhookUrl`+`subscribe`. Best-effort: loga e segue em
        falha; o pareamento não deve travar por causa do webhook. Devolve False sem callback."""
        if not self.settings.evolution_base_url or not self._webhook_url():
            return False
        try:
            await self._connect(instance_id, immediate=False)
            return True
        except (httpx.HTTPError, ErroDominio) as exc:
            _logger.warning("evolution_webhook_set_falhou instance=%s erro=%s", instance_id, exc)
            return False

    async def estado_conexao(self, instance_id: str) -> str:
        """GET /instance/status (token da instância). Retorna 'open' | 'connecting' | 'close' |
        'unknown'. A EvoGo devolve PascalCase `data.Connected`/`data.LoggedIn`: conectado+logado →
        'open'; conectado sem login → 'connecting'; senão 'close'. Instância inexistente →
        'unknown' (callers que só querem checar status sem se preocupar com criação)."""
        if not self.settings.evolution_base_url:
            return "unknown"
        url = f"{self._base()}/instance/status"
        try:
            headers = await self._headers_instancia(instance_id)
        except ErroDominio:
            return "unknown"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 404:
            return "unknown"
        response.raise_for_status()
        data = response.json()
        inner = data.get("data") if isinstance(data, dict) else None
        if not isinstance(inner, dict):
            return "unknown"
        connected = bool(inner.get("Connected") or inner.get("connected"))
        logged_in = bool(inner.get("LoggedIn") or inner.get("loggedIn"))
        if connected and logged_in:
            return "open"
        if connected:
            return "connecting"
        return "close"

    async def logout_instancia(self, instance_id: str) -> bool:
        """DELETE /instance/logout (token da instância). Encerra a sessão WhatsApp mantendo a
        instância cadastrada. Best-effort: log e segue em falha (o caller já vai zerar nosso
        estado local independentemente)."""
        if not self.settings.evolution_base_url:
            return False
        url = f"{self._base()}/instance/logout"
        try:
            headers = await self._headers_instancia(instance_id)
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.delete(url, headers=headers)
            if response.status_code in {200, 201, 204, 404}:
                return True
            _logger.warning(
                "evolution_logout_inesperado instance=%s status=%s body=%s",
                instance_id,
                response.status_code,
                response.text[:200],
            )
            return False
        except (httpx.HTTPError, ErroDominio) as exc:
            _logger.warning("evolution_logout_falhou instance=%s erro=%s", instance_id, exc)
            return False

    def _webhook_url(self) -> str | None:
        """URL do nosso /webhook/evolution para a EvoGo postar, com o token embutido em `?token=`.
        A EvoGo não repassa header de auth no webhook (o /instance/connect não tem campo de
        headers), então carregamos o token na query — o único canal que a rota já aceita
        (`request.query_params['token']`). None quando não há callback configurado (dev sem
        tunnel): o polling do painel + auto-cure no GET /whatsapp/status converge sem callback."""
        callback = self.settings.evolution_webhook_callback_url
        if not callback:
            return None
        token = self.settings.evolution_webhook_token
        if token:
            sep = "&" if "?" in callback else "?"
            return f"{callback}{sep}token={token}"
        return callback

    async def buscar_grupo_info(self, instance_id: str, group_jid: str) -> dict[str, Any]:
        """POST /group/info `{groupJid}` (token da instância). Normaliza a resposta PascalCase da
        EvoGo (`Participants[].{JID,PhoneNumber,LID}`) para `{participants: [{id: <jid>}]}` — o
        shape que `_extrair_membros` consome."""
        if not self.settings.evolution_base_url:
            return {"status": "not_configured", "participants": []}
        response = await self._post_operacao(
            instance_id, "/group/info", {"groupJid": group_jid}, timeout_s=20
        )
        data = response.json()
        inner = data.get("data") if isinstance(data, dict) else data
        fonte = inner if isinstance(inner, dict) else {}
        brutos = (
            fonte.get("Participants")
            or fonte.get("participants")
            or (data.get("Participants") if isinstance(data, dict) else None)
            or []
        )
        participants: list[dict[str, str]] = []
        if isinstance(brutos, list):
            for p in brutos:
                if not isinstance(p, dict):
                    continue
                # PREFERE PhoneNumber (o telefone E.164 real, `@s.whatsapp.net`): na EvoGo o `JID`
                # do participante costuma vir como o `@lid` (verificado ao vivo), e a verificação
                # de Coordenação casa por DÍGITOS DO TELEFONE — o LID falharia. JID só como fallback.
                escolhido: str | None = None
                for cand in (p.get("PhoneNumber"), p.get("phoneNumber"), p.get("JID"), p.get("id")):
                    if isinstance(cand, str) and cand:
                        escolhido = cand
                        break
                if escolhido:
                    if "@" not in escolhido:
                        escolhido = f"{escolhido}@s.whatsapp.net"
                    participants.append({"id": escolhido})
        return {"participants": participants}


async def registrar_envio(
    conn: AsyncConnection[Any],
    *,
    evolution_message_id: str,
    instance_id: str,
    remote_jid: str,
    contexto: str,
    tipo: str,
    atendimento_id: UUID | None,
    conversa_id: UUID | None,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO barravips.envios_evolution (
          evolution_message_id, instance_id, remote_jid, contexto, tipo,
          atendimento_id, conversa_id, payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (evolution_message_id) DO NOTHING
        """,
        (
            evolution_message_id,
            instance_id,
            remote_jid,
            contexto,
            tipo,
            atendimento_id,
            conversa_id,
            json.dumps(payload, default=str),
        ),
    )


async def envio_existe(conn: AsyncConnection[Any], evolution_message_id: str) -> bool:
    result = await conn.execute(
        "SELECT 1 FROM barravips.envios_evolution WHERE evolution_message_id = %s",
        (evolution_message_id,),
    )
    return await result.fetchone() is not None


def _extrair_message_id(data: dict[str, Any]) -> str | None:
    """Extrai o id da mensagem enviada da resposta da EvoGo. O /send/* devolve `gin.H` (map não
    tipado no swagger), então varremos os shapes conhecidos, incluindo PascalCase (whatsmeow) e o
    `key.id` legado. Aninhamento em `data` também é coberto (algumas respostas envelopam)."""
    if not isinstance(data, dict):
        return None
    key = data.get("key") or data.get("Key")
    if isinstance(key, dict):
        value = key.get("id") or key.get("ID") or key.get("Id")
        if value:
            return str(value)
    for chave in ("id", "ID", "Id", "messageId", "MessageID", "message_id", "evolution_message_id"):
        value = data.get(chave)
        if value:
            return str(value)
    info = data.get("Info") or data.get("info")
    if isinstance(info, dict):
        value = info.get("ID") or info.get("id")
        if value:
            return str(value)
    inner = data.get("data") or data.get("Data")
    if isinstance(inner, dict) and inner is not data:
        return _extrair_message_id(inner)
    return None
