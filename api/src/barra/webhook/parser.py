"""Parser de payloads Evolution e comandos do grupo."""

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


@dataclass(frozen=True)
class ComandoGrupo:
    comando: Literal[
        "devolver_para_ia",
        "registrar_fechado",
        "registrar_perdido",
        "listar_pendencias",
        "comando_invalido",
    ]
    numero_curto: int | None
    payload: dict[str, Any]
    erro: str | None = None


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
    )


# Forgiveness de comando (UX §6.3): sinônimos determinísticos da modelo/Fernando além das palavras
# canônicas. Continua regex/prefixo puro — NLP livre ("acho que foi uns mil e quinhentos") é IA
# Admin (P1). A tolerância NÃO se estende ao conjunto de motivos de perda (mantém os 6 fixos; o
# erro 6.2 já os lista) nem afrouxa o `#N` obrigatório fora de resposta-quote ao lembrete.
_FECHAMENTO = ("finalizado", "fechado", "fechei", "fechamos")
_PERDA = ("perdido", "perdi", "nao rolou", "não rolou")
_PREFIXOS_COMANDO = ("ia assume", *_FECHAMENTO, *_PERDA)

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
