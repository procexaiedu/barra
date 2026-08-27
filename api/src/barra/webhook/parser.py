"""Parser de payloads Evolution e comandos do grupo."""

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast


@dataclass(frozen=True)
class MensagemEvolution:
    evolution_message_id: str
    instance_id: str
    remote_jid: str
    sender_jid: str | None
    from_me: bool
    texto: str
    tipo: Literal["texto", "audio", "imagem"]
    media_url: str | None
    quoted_message_id: str | None
    # WhatsApp LID: quando o cliente fala via @lid o `remoteJid` vem `<id-opaco>@lid` e o
    # telefone E.164 real chega aqui como `<telefone>@s.whatsapp.net` (CONTEXT "Cliente":
    # a chave é o telefone, nunca o LID). Em mensagem de grupo/fromMe pode vir ausente.
    remote_jid_alt: str | None = None
    caption: str | None = None
    media_base64: str | None = None
    media_mimetype: str | None = None
    # Nome de exibição do autor (`pushName`). No 1:1 é redundante (o cliente é o telefone), mas em
    # GRUPO é o único rótulo humano de quem falou: o `participant` pode vir `@lid` opaco e o Grupo
    # financeiro (spec 0005) precisa saber que quem postou foi a Dani, o FEH ou a Parcerias.
    push_name: str | None = None


@dataclass(frozen=True)
class DelecaoEvolution:
    """Uma mensagem apagada para todos, como a plataforma conta (spec 0005, ticket 05).

    So tres campos porque delecao nao tem conteudo: QUAL mensagem morreu, em QUE chat e QUEM
    apagou. Nao e um `MensagemEvolution` de propósito — nao ha texto, tipo, midia nem quote, e
    fingir que ha faria todo leitor de mensagem ter que se defender de um texto vazio.
    """

    evolution_message_id: str
    remote_jid: str
    participant: str | None = None


@dataclass(frozen=True)
class ReacaoEvolution:
    """Uma reacao emoji sobre uma mensagem que ja existe — o ✅/❌ do telefonista (spec 0006).

    Irma de `DelecaoEvolution` e pelo mesmo motivo: nao ha conteudo novo, o dado util e QUAL
    mensagem recebeu QUAL emoji, de quem. `emoji` VAZIO nao e ausencia de dado: e a REMOCAO da
    reacao, que e como a plataforma avisa que o ✅ saiu (e o gesto que o ticket 08 exige desfazer).

    ⚠️ **A grafia do evento que produz este objeto ainda NAO foi capturada em producao** — ver
    `GRAFIA_DO_GESTO_CONFIRMADA` e `extrair_gesto`. O TIPO nao depende da grafia; o preenchimento
    dele, sim.
    """

    evolution_message_id: str
    """A mensagem ALVO da reacao — a que ja estava no grupo, nunca a reacao em si."""
    remote_jid: str
    emoji: str = ""
    participant: str | None = None
    from_me: bool = False


@dataclass(frozen=True)
class EdicaoEvolution:
    """Uma mensagem editada ("editada" do WhatsApp) — o quarto gesto do ADR-0044 §4.

    Chega pelo mesmo `protocolMessage` da revogacao, com outro `type`: e literalmente o ramo em que
    `extrair_delecao` desiste hoje ("protocolMessage de outros tipos (edicao...), que nao apagam
    nada"). O dado util e QUAL mensagem mudou e para QUAL texto.

    ⚠️ Mesma pendencia de grafia da `ReacaoEvolution`: o `type` numerico do edit e o lugar do texto
    novo no envelope da EvoGo nao foram vistos ao vivo.
    """

    evolution_message_id: str
    """A mensagem ALVO da edicao — a chave que ja esta no log de origem."""
    remote_jid: str
    texto: str = ""
    """O texto DEPOIS da edicao."""
    participant: str | None = None
    from_me: bool = False


@dataclass(frozen=True)
class ComandoGrupo:
    comando: Literal[
        "devolver_para_ia",
        "pausar_ia",
        "registrar_fechado",
        "registrar_perdido",
        "listar_pendencias",
        "comando_invalido",
    ]
    numero_curto: int | None
    payload: dict[str, Any]
    erro: str | None = None


# --- Adaptador Evolution GO (whatsmeow) -> shape v2 (Baileys) ---------------------------------
# A EvoGo NÃO é wire-compatible com a v2: eventos em CamelCase (`Message`/`SendMessage`/
# `Connection`/`QR`), instância em `instanceName`, envelope `data.Info.{Chat,ID,IsFromMe,Sender,
# SenderAlt}`. O CONTEÚDO (`data.Message.*`) é o MESMO formato WhatsApp da v2 (conversation,
# imageMessage…), então convertemos só o ENVELOPE para o shape v2 e reusamos `extrair_mensagem` +
# `_evento_normalizado` intactos (padrão adaptGoEvent). Payload que não é Go passa reto (compat
# durante a transição).


def _eh_payload_go(payload: dict[str, Any]) -> bool:
    data = payload.get("data")
    if isinstance(data, dict) and ("Info" in data or "Message" in data):
        return True
    if payload.get("instanceToken") is not None:
        return True
    if payload.get("instanceName") is not None and payload.get("instance") is None:
        return True
    ev = payload.get("event")
    return isinstance(ev, str) and bool(ev) and ev[:1].isupper()


def _estado_conexao_go(data: dict[str, Any]) -> str:
    """Deriva o `state` (open/close/connecting) do evento Connection da EvoGo. O shape exato do
    evento não é documentado; lemos os campos plausíveis (`state`/`status` string ou `Connected`
    bool) de forma defensiva."""
    for campo in ("state", "State", "status", "Status"):
        valor = data.get(campo)
        if isinstance(valor, str) and valor:
            low = valor.lower()
            if low in ("open", "connected", "online"):
                return "open"
            if low in ("close", "closed", "disconnected", "offline", "logged_out"):
                return "close"
            if low in ("connecting", "pairing"):
                return "connecting"
            return low
    if "Connected" in data or "connected" in data:
        return "open" if (data.get("Connected") or data.get("connected")) else "close"
    return "unknown"


def adaptar_webhook_go(payload: dict[str, Any]) -> dict[str, Any]:
    """Converte um webhook da Evolution GO no shape v2 que o resto do módulo já parseia. Não-Go
    (ou já v2) passa reto."""
    if not isinstance(payload, dict) or not _eh_payload_go(payload):
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    assert isinstance(data, dict)
    instance = payload.get("instanceName") or payload.get("instance")
    ev_raw = str(payload.get("event") or "")
    ev = ev_raw.replace("_", "").lower()
    adaptado: dict[str, Any] = {"instance": instance}

    if ev in ("message", "sendmessage"):
        info = data.get("Info") if isinstance(data.get("Info"), dict) else {}
        message = data.get("Message") if isinstance(data.get("Message"), dict) else {}
        assert isinstance(info, dict) and isinstance(message, dict)
        # Mídia inbound (WEBHOOK_FILES): a EvoGo anexa a mídia decifrada. O campo exato ainda não
        # foi capturado ao vivo; copiamos os candidatos conhecidos (base64 no nível de `data`) para
        # dentro da `message` p/ o `_media_base64`/download existentes acharem. Ver verificação viva.
        b64 = data.get("base64") or data.get("Base64")
        if isinstance(b64, str) and b64:
            message = {**message, "base64": b64}
        chat = info.get("Chat")
        sender = info.get("Sender")
        sender_alt = info.get("SenderAlt")
        # E.164 real (para o ramo @lid do webhook): o telefone verdadeiro é o JID `@s.whatsapp.net`
        # entre Sender/SenderAlt/Chat (SenderAlt costuma ser o `@lid`, invertido em relação à v2).
        real = next(
            (
                j
                for j in (sender, sender_alt, chat)
                if isinstance(j, str) and j.endswith("@s.whatsapp.net")
            ),
            None,
        )
        eh_lid = isinstance(chat, str) and chat.endswith("@lid")
        # `participant` alimenta `_autor_grupo` (reconhece Fernando por igualdade em fernando_jids,
        # que são JIDs `@s.whatsapp.net`). Se o `Sender` do grupo vier como `@lid`, a igualdade
        # falharia e o comando de Fernando (`ia assume`/`fechado`/`perdido`) seria descartado em
        # silêncio. Preferimos o JID `@s.whatsapp.net` real entre Sender/SenderAlt.
        participant_real = next(
            (
                j
                for j in (sender, sender_alt)
                if isinstance(j, str) and j.endswith("@s.whatsapp.net")
            ),
            sender,
        )
        adaptado["event"] = "messages.upsert"
        adaptado["data"] = {
            "pushName": info.get("PushName") or info.get("pushName"),
            "key": {
                "id": info.get("ID") or info.get("Id"),
                "remoteJid": chat,
                "fromMe": bool(info.get("IsFromMe")),
                "participant": participant_real,
                "remoteJidAlt": real if eh_lid else None,
            },
            "message": message,
        }
        return adaptado

    if ev == "connection":
        adaptado["event"] = "connection.update"
        adaptado["data"] = {"state": _estado_conexao_go(data)}
        return adaptado

    # A EvoGo não manda um `Connection` genérico na queda: manda eventos próprios — `Disconnected`
    # (socket caiu), `LoggedOut` (sessão morreu; `reason 403: primary device was logged out` exige
    # reparear) e `QRTimeout` (esgotou os 5 QRs). Sem esta tradução eles caíam no `extrair_mensagem`
    # → None (ignored) e o `evolution_status` da modelo ficava `conectado` com o número fora do ar.
    if ev in ("connected", "disconnected", "loggedout", "qrtimeout"):
        adaptado["event"] = "connection.update"
        adaptado["data"] = {"state": "open" if ev == "connected" else "close"}
        return adaptado

    if ev in ("qr", "qrcode"):
        adaptado["event"] = "qrcode.updated"
        adaptado["data"] = {}
        return adaptado

    # Evento Go sem tradução (Receipt, Presence, HistorySync…): repassa cru; o roteador do webhook
    # cai no `extrair_mensagem` que devolve None (ignored) — nunca vira turno fantasma.
    adaptado["event"] = ev_raw
    adaptado["data"] = data
    return adaptado


def extrair_delecao(payload: dict[str, Any]) -> DelecaoEvolution | None:
    """A plataforma esta avisando que uma mensagem foi APAGADA PARA TODOS? (spec 0005, ticket 05).

    Duas grafias chegam pelo mesmo webhook e as duas significam a mesma coisa:

    * evento proprio `messages.delete`, com a chave da mensagem morta no `data` (Evolution v2);
    * `messages.upsert` carregando um `protocolMessage` de tipo `REVOKE` — que e como a EvoGo
      (whatsmeow) entrega o revoke, ja normalizada por `adaptar_webhook_go`. Nesse formato o id
      que interessa e o do ALVO (`protocolMessage.key.id`), nunca o do envelope: o envelope e uma
      mensagem-de-sistema nova, com id proprio, que nunca virou nada no nosso banco.

    Hoje so o `extrair_mensagem` (que devolve `None` para protocolMessage) ficava entre esse
    evento e o lixo. Devolve `None` para todo o resto — inclusive para `protocolMessage` de outros
    tipos (edicao de mensagem, sincronizacao de estado), que nao apagam nada.
    """
    evento = str(payload.get("event") or "").replace("_", ".").lower()
    raw_data = payload.get("data")
    if isinstance(raw_data, list):
        # Algumas versoes entregam a delecao em lote; uma mensagem por evento e o caso normal e
        # a primeira e a que interessa (a porta e chamada uma vez por evento).
        raw_data = raw_data[0] if raw_data else None
    data = raw_data if isinstance(raw_data, dict) else {}
    raw_key = data.get("key")
    key = raw_key if isinstance(raw_key, dict) else {}

    remote_jid = key.get("remoteJid") or data.get("remoteJid")
    participante = key.get("participant") or data.get("participant")

    if evento in ("messages.delete", "message.delete", "messages.revoke"):
        alvo = key.get("id") or data.get("id") or data.get("keyId") or data.get("messageId")
    else:
        raw_message = data.get("message")
        message = raw_message if isinstance(raw_message, dict) else {}
        raw_protocolo = message.get("protocolMessage")
        protocolo = raw_protocolo if isinstance(raw_protocolo, dict) else {}
        tipo = protocolo.get("type", protocolo.get("Type"))
        if str(tipo).upper() not in ("REVOKE", "0"):
            return None
        raw_alvo = protocolo.get("key") or protocolo.get("Key")
        chave_alvo = raw_alvo if isinstance(raw_alvo, dict) else {}
        alvo = chave_alvo.get("id") or chave_alvo.get("ID")
        participante = key.get("participant") or participante

    if not alvo or not remote_jid:
        return None
    return DelecaoEvolution(
        evolution_message_id=str(alvo),
        remote_jid=str(remote_jid),
        participant=str(participante) if participante else None,
    )


_PROFUNDIDADE_DO_ESBOCO = 6
_ITENS_POR_NIVEL_NO_ESBOCO = 24
_STRING_INTEIRA_ATE = 48
_TEXTO_NO_ESBOCO = 8

_CHAVES_DE_TEXTO = frozenset(
    {"conversation", "caption", "body", "description", "title", "pushname", "matchedtext"}
)
"""Chaves cujo VALOR e fala de gente — cortadas curto mesmo sendo curtas.

`text` NAO esta aqui de proposito: e onde mora o emoji da reacao, e ele e o dado que a captura
existe para ver. Um emoji cabe nos 8 caracteres; uma frase, nao.
"""


def parece_gesto_em_grupo(payload: dict[str, Any]) -> bool:
    """O payload TEM cara de reacao/edicao vinda de um grupo?

    Deliberadamente frouxo na grafia e estrito no lugar. Frouxo porque a grafia e exatamente o que
    nao sabemos: casa por SUBSTRING sem caixa (`reaction`, `protocol`, `edit`), o que pega tanto
    `reactionMessage` (v2) quanto `ReactionMessage` (whatsmeow marshalado em CamelCase) quanto o
    nome que a EvoGo inventar. Estrito no lugar porque so `@g.us` interessa: e a mesma fronteira
    de `extrair_gesto`, e ela mantem a reacao do CLIENTE (chat 1:1 do agente de venda) fora daqui.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    assert isinstance(key, dict)
    remote_jid = key.get("remoteJid") or data.get("remoteJid")
    if not (isinstance(remote_jid, str) and remote_jid.endswith("@g.us")):
        return False
    message = data.get("message")
    if not isinstance(message, dict):
        return False
    return any(
        marca in nome.lower() for nome in message for marca in ("reaction", "protocol", "edit")
    )


def esboco_do_payload(valor: Any, *, chave: str = "", profundidade: int = 0) -> Any:
    """A FORMA do payload com os valores redigidos — para conferir grafia sem virar dump de PII.

    O que a captura precisa e a arvore de chaves e os IDS (para provar que o id do gesto e o do
    ALVO, e nao o do envelope); o que ela nao pode carregar e conteudo de mensagem e telefone.

    O corte e por CHAVE, nao por tamanho, e isso foi um bug pego no teste: cortar toda string curta
    em 8 mutilava os proprios ids que a captura existe para comparar (`ENVELOPE123` virava
    `ENVELOPE`). Entao: JID vira `<jid>` (e telefone da modelo e do telefonista), fala de gente
    (`_CHAVES_DE_TEXTO`) e cortada curto, string longa vira `<str:N>` e o resto — id, flag, enum —
    passa inteiro.

    Numero, booleano e `None` passam crus: sao flags (`fromMe`) e timestamps, e e por eles que se
    distingue a reacao POSTA da reacao RETIRADA.
    """
    if profundidade > _PROFUNDIDADE_DO_ESBOCO:
        return "<fundo>"
    if isinstance(valor, dict):
        return {
            str(k): esboco_do_payload(v, chave=str(k), profundidade=profundidade + 1)
            for k, v in list(valor.items())[:_ITENS_POR_NIVEL_NO_ESBOCO]
        }
    if isinstance(valor, list):
        return [
            esboco_do_payload(v, chave=chave, profundidade=profundidade + 1)
            for v in valor[:_ITENS_POR_NIVEL_NO_ESBOCO]
        ]
    if isinstance(valor, str):
        if "@" in valor:
            return "<jid>"
        if chave.lower() in _CHAVES_DE_TEXTO:
            return f"<str:{len(valor)}>" if len(valor) > _TEXTO_NO_ESBOCO else valor
        if len(valor) > _STRING_INTEIRA_ATE:
            return f"<str:{len(valor)}>"
        return valor
    return valor


GRAFIA_DO_GESTO_CONFIRMADA = False
"""O envelope real de REACAO e de EDICAO da EvoGo ja foi capturado em producao?

`False` = nao, e por isso `extrair_gesto` devolve `None` para tudo. A borda continua exatamente
como esta: reacao morre no gate explicito de `extrair_mensagem` e edicao morre no `extrair_delecao`
(que so aceita `REVOKE`) — o comportamento que o agente de venda depende e o que o ticket 08 manda
preservar para ele.

Nao e um flag de produto e nao vira `settings`: e a marca de que a leitura abaixo foi escrita
contra um payload **hipotetico**. Este projeto ja quebrou calado por contrato de evento inventado
(vault: `deepseek_json_object_e_thinking_grafia`, `extracao_fronteira_llm_tool_perde_turno`), e um
parser que "quase" acerta o envelope e pior que um que devolve None: ele entrega gesto com o id do
ENVELOPE no lugar do id do ALVO, e o ✅ passa a promover a ficha errada.

Como destravar (roteiro completo em `.scratch/agente-financeiro-v2/PAYLOAD-EVOGO.md`): capturar o
JSON cru dos dois gestos, colar no fixture do teste, conferir campo a campo o que esta escrito
abaixo, virar esta chave e tirar o `xfail`.
"""

# Tipos de `protocolMessage` que interessam. `REVOKE` ja e tratado por `extrair_delecao`; o edit e
# o que morre la hoje. Os nomes vem do proto do WhatsApp; o numero e a grafia que a EvoGo emite de
# fato NAO foram vistos ao vivo — e exatamente o que a captura tem que confirmar.
_TIPOS_DE_EDICAO_HIPOTETICOS = frozenset({"MESSAGE_EDIT", "EDIT", "14"})


def extrair_gesto(payload: dict[str, Any]) -> ReacaoEvolution | EdicaoEvolution | None:
    """A UNICA porta de entrada de reacao e de edicao no webhook — e hoje ela esta FECHADA.

    Devolve `None` enquanto `GRAFIA_DO_GESTO_CONFIRMADA` for `False`, que e o estado atual: o
    payload real da EvoGo para os dois gestos nao existe no repo e nao e adivinhavel. Toda a
    desserializacao mora AQUI, atras de uma funcao so, para que destravar seja mexer em um lugar —
    e para que o resto do modulo (o dominio do gesto em
    `dominio/grupo_financeiro/gesto.py`, ja escrito e testado) nunca dependa da grafia.

    Duas regras que NAO dependem do payload e ja valem:

    * **So grupo.** Gesto fora de um `@g.us` nao vira evento — e a fronteira que mantem a reacao
      como ruido para o agente de venda (spec 0006, historia 56). Quem decide se o grupo e um
      Grupo financeiro continua sendo a porta unica (closed-world contra `grupos_financeiros`),
      nunca este arquivo.
    * **O id e o do ALVO.** Como na revogacao, o envelope do gesto e uma mensagem de sistema com id
      proprio, que nunca virou nada no nosso banco. Ler o id errado nao levanta erro nenhum: so
      nao acha ficha, e o gesto some.
    """
    if not GRAFIA_DO_GESTO_CONFIRMADA:
        return None
    return _ler_gesto_hipotetico(payload)  # pragma: no cover - so roda com a grafia confirmada


def _ler_gesto_hipotetico(
    payload: dict[str, Any],
) -> ReacaoEvolution | EdicaoEvolution | None:  # pragma: no cover - ver GRAFIA_DO_GESTO_CONFIRMADA
    """A leitura escrita contra o envelope **HIPOTETICO**, para ser conferida contra o real.

    Premissas, todas por confirmar (uma linha por premissa, para a captura poder marcar cada uma):

    1. o gesto chega como `messages.upsert` depois de `adaptar_webhook_go`, com `data.key` e
       `data.message` — o mesmo caminho da revogacao;
    2. a reacao vem em `message.reactionMessage`, com o alvo em `.key.id` e o emoji em `.text`;
    3. reacao RETIRADA chega com `.text` vazio (e nao um evento proprio);
    4. a edicao vem em `message.protocolMessage` com `type` de edit e o texto novo em
       `editedMessage` (conversation / extendedTextMessage.text);
    5. o autor do gesto em grupo vem no `key.participant` do ENVELOPE.

    As chaves estao em lowerCamel porque e o shape v2 que o resto do arquivo ja parseia. A EvoGo
    entrega `data.Message` **sem traduzir** (`adaptar_webhook_go` so mexe no envelope), entao se o
    whatsmeow serializar em CamelCase (`ReactionMessage`, `Key`, `Text`) nada aqui casa — e o
    primeiro item a olhar no payload capturado.
    """
    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    raw_key = data.get("key")
    key = raw_key if isinstance(raw_key, dict) else {}
    remote_jid = key.get("remoteJid") or data.get("remoteJid")
    if not isinstance(remote_jid, str) or not remote_jid.endswith("@g.us"):
        return None
    raw_message = data.get("message")
    message = raw_message if isinstance(raw_message, dict) else {}
    participant = key.get("participant") or data.get("participant")
    autor = str(participant) if participant else None
    de_mim = bool(key.get("fromMe") or data.get("fromMe"))

    reacao = message.get("reactionMessage")
    if isinstance(reacao, dict):
        alvo = _id_do_alvo(reacao.get("key"))
        if not alvo:
            return None
        emoji = reacao.get("text")
        return ReacaoEvolution(
            evolution_message_id=alvo,
            remote_jid=remote_jid,
            emoji=str(emoji) if isinstance(emoji, str) else "",
            participant=autor,
            from_me=de_mim,
        )

    protocolo = message.get("protocolMessage")
    if isinstance(protocolo, dict):
        tipo = str(protocolo.get("type", protocolo.get("Type", ""))).upper()
        if tipo not in _TIPOS_DE_EDICAO_HIPOTETICOS:
            return None
        alvo = _id_do_alvo(protocolo.get("key") or protocolo.get("Key"))
        if not alvo:
            return None
        editada = protocolo.get("editedMessage")
        texto = _texto(editada) if isinstance(editada, dict) else None
        return EdicaoEvolution(
            evolution_message_id=alvo,
            remote_jid=remote_jid,
            texto=(texto or "").strip(),
            participant=autor,
            from_me=de_mim,
        )
    return None


def _id_do_alvo(chave: Any) -> str | None:
    """O id da mensagem TOCADA pelo gesto, nunca o do envelope."""
    if not isinstance(chave, dict):
        return None
    alvo = chave.get("id") or chave.get("ID")
    return str(alvo) if alvo else None


def extrair_mensagem(payload: dict[str, Any]) -> MensagemEvolution | None:
    raw_data = payload.get("data")
    data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else payload
    raw_key = data.get("key")
    key = cast(dict[str, Any], raw_key) if isinstance(raw_key, dict) else {}
    raw_message = data.get("message")
    message = cast(dict[str, Any], raw_message) if isinstance(raw_message, dict) else {}
    message_id = key.get("id") or data.get("id") or data.get("messageId")
    remote_jid = key.get("remoteJid") or data.get("remoteJid")
    remote_jid_alt = key.get("remoteJidAlt") or data.get("remoteJidAlt")
    if not message_id or not remote_jid:
        return None
    texto = _texto(message) or str(data.get("text") or data.get("body") or "")
    tipo = "texto"
    media_url = None
    media_mimetype: str | None = None
    caption: str | None = None
    if "audioMessage" in message:
        tipo = "audio"
        media_url = message["audioMessage"].get("url")
        media_mimetype = message["audioMessage"].get("mimetype")
    elif "imageMessage" in message:
        tipo = "imagem"
        media_url = message["imageMessage"].get("url")
        media_mimetype = message["imageMessage"].get("mimetype")
        raw_caption = message["imageMessage"].get("caption")
        caption = str(raw_caption).strip() or None if raw_caption else None
    elif not texto.strip() and (
        loc := message.get("locationMessage") or message.get("liveLocationMessage")
    ):
        # Pin de localizacao do WhatsApp: sem este ramo caia no gate de texto vazio (200
        # 'ignored') e o agente respondia AS CEGAS a fala adjacente — em prod inventou
        # distancia/ETA (trace dc0375ca, 22/07). Vira moldura de TEXTO na janela; a parte
        # ideal (geocode reverso + distancia ate o ponto da modelo) fica para issue propria.
        # `liveLocationMessage` (localizacao em tempo real) carrega as mesmas coords e cai aqui
        # tambem: a janela recebe a posicao do momento, sem acompanhar as atualizacoes.
        moldura = _moldura_localizacao(loc)
        if moldura:
            texto = moldura
    # WEBHOOK_BASE64 ligado: a Evolution entrega a midia ja DECIFRADA inline (a `url` aponta
    # pro CDN cifrado do WhatsApp, inutil sem a mediaKey). O campo varia por versao/tipo, entao
    # lemos os dois caminhos conhecidos: nivel da mensagem e dentro do *Message.
    # Reacao/sticker/protocolMessage (edicao, delete) e afins chegam SEM texto e sem midia
    # reconhecida. Sem este gate viravam um MensagemEvolution de texto vazio, persistido e
    # despachado como TURNO FANTASMA (chars_inbound=0) -- e o agente confabulava uma resposta a
    # um input que nunca existiu (ex.: "tudo bem e voce?" para uma reacao). Nao sao turnos de
    # conversa: descarta na borda (routes -> 200 'ignored'). `reactionMessage` e explicito porque
    # versoes da Evolution podem trazer o emoji em `.text` (nao-vazio) e ainda assim nao e turno.
    if "reactionMessage" in message or (tipo == "texto" and not texto.strip()):
        return None
    media_base64 = _media_base64(message)
    quoted = _quoted_id(message)
    return MensagemEvolution(
        evolution_message_id=str(message_id),
        instance_id=str(payload.get("instance") or data.get("instanceId") or ""),
        remote_jid=str(remote_jid),
        remote_jid_alt=str(remote_jid_alt) if remote_jid_alt else None,
        sender_jid=key.get("participant") or data.get("sender") or data.get("participant"),
        from_me=bool(key.get("fromMe") or data.get("fromMe")),
        texto=texto.strip(),
        tipo=tipo,  # type: ignore[arg-type]
        media_url=media_url,
        quoted_message_id=quoted,
        caption=caption,
        media_base64=media_base64,
        media_mimetype=media_mimetype,
        push_name=_texto_ou_none(data.get("pushName") or payload.get("pushName")),
    )


def _texto_ou_none(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    return valor.strip() or None


# Forgiveness de comando (UX §6.3): sinônimos determinísticos da modelo/Fernando além das palavras
# canônicas. Continua regex/prefixo puro — NLP livre ("acho que foi uns mil e quinhentos") é IA
# Admin (P1). A tolerância NÃO se estende ao conjunto de motivos de perda (mantém os 6 fixos; o
# erro 6.2 já os lista) nem afrouxa o `#N` obrigatório fora de resposta-quote ao lembrete.
_FECHAMENTO = ("finalizado", "fechado", "fechei", "fechamos")
_PERDA = ("perdido", "perdi", "nao rolou", "não rolou")
_PREFIXOS_COMANDO = ("ia assume", "ia pausa", *_FECHAMENTO, *_PERDA)

# Digest de pendencias (UX §6.4): comando sem `#N`, lido por igualdade exata (apos normalizar
# espacos/caixa) p/ nao colidir com "qual o status do #5". Sinonimos acentuado/sem acento.
_PENDENCIAS = frozenset({"pendencias", "pendências", "pendentes", "status"})


def parse_comando_grupo(
    texto: str,
    quoted_numero_curto: int | None = None,
    *,
    aguardando_valor: bool = False,
) -> ComandoGrupo | None:
    raw = " ".join(texto.strip().split())
    if not raw:
        return None
    numero = _numero_curto(raw) or quoted_numero_curto
    lower = raw.lower()

    # Digest sob demanda (UX §6.4): nao escopa um atendimento (sem `#N`); so lista as pendencias
    # da modelo dona do grupo. Igualdade exata para nao capturar frases que contenham a palavra.
    if lower in _PENDENCIAS:
        return ComandoGrupo("listar_pendencias", None, {})

    # Resposta ao card de Lembrete de fechamento (ADR-0009): citando o card, um valor "pelado"
    # (sem palavra-chave) fecha o atendimento. Prefixos conhecidos seguem o fluxo normal abaixo.
    if aguardando_valor and numero is not None and not lower.startswith(_PREFIXOS_COMANDO):
        valores = _valores(raw)
        if len(valores) == 1:
            return ComandoGrupo("registrar_fechado", numero, {"valor_final": valores[0]})
        if len(valores) > 1:
            return ComandoGrupo(
                "comando_invalido", numero, {"motivo": "valor_ambiguo"}, "Valor ambiguo."
            )

    if lower.startswith("ia assume"):
        if numero is None:
            return _invalido("Informe #N do atendimento.")
        return ComandoGrupo("devolver_para_ia", numero, {})

    # Handoff manual (ADR-0032, spec 0003): Fernando/modelo pausam a IA por decisao livre, sem
    # esperar um gatilho automatico do state machine. Mesma disciplina de "ia assume": quote de
    # card resolve o #N; fora de contexto de card, `#N` e obrigatorio.
    if lower.startswith("ia pausa"):
        if numero is None:
            return _invalido("Informe #N do atendimento.")
        return ComandoGrupo("pausar_ia", numero, {})

    if lower.startswith(_FECHAMENTO):
        if numero is None:
            return _invalido("Informe #N do atendimento.")
        valores = _valores(raw)
        if len(valores) > 1:
            return ComandoGrupo(
                "comando_invalido", numero, {"motivo": "valor_ambiguo"}, "Valor ambiguo."
            )
        if not valores:
            return ComandoGrupo(
                "comando_invalido",
                numero,
                {"motivo": "valor_final_obrigatorio"},
                "Valor final obrigatorio.",
            )
        return ComandoGrupo("registrar_fechado", numero, {"valor_final": valores[0]})

    if lower.startswith(_PERDA):
        if numero is None:
            return _invalido("Informe #N do atendimento.")
        motivo, observacao = _motivo_perda(raw)
        if motivo is None:
            return ComandoGrupo(
                "comando_invalido",
                numero,
                {"motivo": "motivo_perda_obrigatorio"},
                "Motivo obrigatorio.",
            )
        payload: dict[str, Any] = {"motivo": motivo}
        if observacao:
            payload["observacao"] = observacao
        return ComandoGrupo("registrar_perdido", numero, payload)

    return None


def _texto(message: dict[str, Any]) -> str | None:
    if "conversation" in message:
        return str(message["conversation"])
    ext = message.get("extendedTextMessage")
    if isinstance(ext, dict) and ext.get("text"):
        return str(ext["text"])
    return None


def _moldura_localizacao(loc: Any) -> str | None:
    """Pin de localizacao -> moldura de texto para a janela do agente.

    Coords sao coeridas a float (nunca a string crua do payload); nome/endereco do pin sao
    dado do cliente com o mesmo nivel de confianca de texto digitado. Sem coords validas
    devolve None e o evento segue o gate de texto vazio (ignored)."""
    if not isinstance(loc, dict):
        return None
    lat_raw, lon_raw = loc.get("degreesLatitude"), loc.get("degreesLongitude")
    if lat_raw is None or lon_raw is None:
        return None
    try:
        lat, lon = float(lat_raw), float(lon_raw)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    # name/address sao string controlada pelo CLIENTE dentro de uma moldura que o prompt trata
    # como confiavel: tira colchetes/angulares (nao fecham a moldura nem viram tag), colapsa
    # whitespace (\n fabricaria linha com cara de bloco interno) e trunca.
    partes = [
        " ".join(re.sub(r"[\[\]<>]", "", str(loc[c])).split())[:120]
        for c in ("name", "address")
        if loc.get(c)
    ]
    rotulo = " — ".join(p for p in partes if p)
    detalhe = f"{rotulo} · " if rotulo else ""
    # Rotulo neutro de proposito: um pin fromMe (modelo em atendimento manual) entra na janela
    # como fala DELA — "cliente enviou" mentiria; a direcao da mensagem ja diz quem mandou.
    return f"[pin de localização: {detalhe}lat {lat:.6f}, long {lon:.6f}]"


def _media_base64(message: dict[str, Any]) -> str | None:
    """Base64 decifrado entregue pela Evolution (WEBHOOK_BASE64). O campo varia entre versoes:
    no nivel da mensagem (`message.base64`) ou aninhado (`message.imageMessage.base64`). Le os
    dois e ignora vazio/nao-string."""
    candidatos: list[Any] = [message.get("base64")]
    for chave in ("imageMessage", "audioMessage"):
        sub = message.get(chave)
        if isinstance(sub, dict):
            candidatos.append(sub.get("base64"))
    for valor in candidatos:
        if isinstance(valor, str) and valor:
            return valor
    return None


def _quoted_id(message: dict[str, Any]) -> str | None:
    # O quote (contextInfo.stanzaId) vive DENTRO do *Message do tipo enviado: texto em
    # extendedTextMessage, mas uma IMAGEM citando um card o traz em imageMessage.contextInfo. A
    # modelo responde o card de fechamento COM a foto do comprovante (auto-baixa), entao ler so o
    # extendedTextMessage perderia a ancora #N. Le os containers conhecidos, na ordem.
    for chave in ("extendedTextMessage", "imageMessage", "audioMessage"):
        sub = message.get(chave)
        ctx = sub.get("contextInfo") if isinstance(sub, dict) else None
        stanza = ctx.get("stanzaId") if isinstance(ctx, dict) else None
        if stanza:
            return str(stanza)
    return None


def _numero_curto(texto: str) -> int | None:
    match = re.search(r"#(\d+)\b", texto)
    return int(match.group(1)) if match else None


_VALOR_RE = re.compile(r"(?:r\$\s*)?(\d+(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+k)\b", re.I)


def _token_para_decimal(token: str) -> Decimal | None:
    token = token.lower()
    if token.endswith("k"):
        try:
            return Decimal(token[:-1]) * Decimal("1000")
        except InvalidOperation:
            return None
    normalizado = token.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalizado)
    except InvalidOperation:
        return None


def _valores(texto: str) -> list[Decimal]:
    """Todos os candidatos a valor no texto (apos remover o #N). >1 = ambiguo: o comando
    nao deve chutar o primeiro (corromperia o Valor final / base de repasse em silencio)."""
    sem_numero = re.sub(r"#\d+\b", "", texto, count=1)
    out: list[Decimal] = []
    for match in _VALOR_RE.finditer(sem_numero):
        valor = _token_para_decimal(match.group(1))
        if valor is not None:
            out.append(valor)
    return out


# Motivos do enum + grafias que o proprio erro de recuperacao instrui ("preço" com cedilha) e
# "fora de area" como se digita (espacos, com/sem acento). Match por palavra inteira, no PRIMEIRO
# motivo que aparece no texto (leftmost) — nao na ordem da lista: "perdido outro cliente sumiu
# antes de fechar" e motivo `outro` com observacao, nunca `sumiu` (corrupcao silenciosa).
_MOTIVO_PERDA_RE = re.compile(
    r"\b(pre[cç]o|sumiu|risco|indisponibilidade|fora[ _]de[ _][aá]rea|outro)\b", re.I
)


def _motivo_perda(texto: str) -> tuple[str | None, str | None]:
    """(motivo canonico, observacao) do texto de um comando de perda.

    A observacao e o que sobra DEPOIS do motivo (sem o `#N`) — e a forma do mvp/05 §3.1
    (`perdido [motivo] [obs?] #N`) e a unica porta de `outro` via grupo (o servico exige
    observacao para `outro`; sem extrai-la aqui o comando era um beco sem saida)."""
    sem_numero = re.sub(r"#\d+\b", "", texto)
    match = _MOTIVO_PERDA_RE.search(sem_numero)
    if match is None:
        return None, None
    canonico = match.group(1).lower().replace("ç", "c").replace("á", "a").replace(" ", "_")
    observacao = sem_numero[match.end() :].strip(" .,:;!-—") or None
    return canonico, observacao


def _invalido(erro: str) -> ComandoGrupo:
    return ComandoGrupo("comando_invalido", None, {"motivo": erro}, erro)
