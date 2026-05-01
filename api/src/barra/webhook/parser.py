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


@dataclass(frozen=True)
class ComandoGrupo:
    comando: Literal["devolver_para_ia", "registrar_fechado", "registrar_perdido", "comando_invalido"]
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
    if not message_id or not remote_jid:
        return None
    texto = _texto(message) or str(data.get("text") or data.get("body") or "")
    tipo = "texto"
    media_url = None
    if "audioMessage" in message:
        tipo = "audio"
        media_url = message["audioMessage"].get("url")
    elif "imageMessage" in message:
        tipo = "imagem"
        media_url = message["imageMessage"].get("url")
    quoted = _quoted_id(message)
    return MensagemEvolution(
        evolution_message_id=str(message_id),
        instance_id=str(payload.get("instance") or data.get("instanceId") or ""),
        remote_jid=str(remote_jid),
        sender_jid=key.get("participant") or data.get("sender") or data.get("participant"),
        from_me=bool(key.get("fromMe") or data.get("fromMe")),
        texto=texto.strip(),
        tipo=tipo,  # type: ignore[arg-type]
        media_url=media_url,
        quoted_message_id=quoted,
    )


def parse_comando_grupo(texto: str, quoted_numero_curto: int | None = None) -> ComandoGrupo | None:
    raw = " ".join(texto.strip().split())
    if not raw:
        return None
    numero = _numero_curto(raw) or quoted_numero_curto
    lower = raw.lower()

    if lower.startswith("ia assume"):
        if numero is None:
            return _invalido("Informe #N do atendimento.")
        return ComandoGrupo("devolver_para_ia", numero, {})

    if lower.startswith("finalizado") or lower.startswith("fechado"):
        if numero is None:
            return _invalido("Informe #N do atendimento.")
        valor = _valor(raw)
        if valor is None:
            return ComandoGrupo(
                "comando_invalido",
                numero,
                {"motivo": "valor_final_obrigatorio"},
                "Valor final obrigatorio.",
            )
        return ComandoGrupo("registrar_fechado", numero, {"valor_final": valor})

    if lower.startswith("perdido"):
        if numero is None:
            return _invalido("Informe #N do atendimento.")
        motivo = _motivo_perda(lower)
        if motivo is None:
            return ComandoGrupo(
                "comando_invalido",
                numero,
                {"motivo": "motivo_perda_obrigatorio"},
                "Motivo obrigatorio.",
            )
        return ComandoGrupo("registrar_perdido", numero, {"motivo": motivo})

    return None


def _texto(message: dict[str, Any]) -> str | None:
    if "conversation" in message:
        return str(message["conversation"])
    ext = message.get("extendedTextMessage")
    if isinstance(ext, dict) and ext.get("text"):
        return str(ext["text"])
    return None


def _quoted_id(message: dict[str, Any]) -> str | None:
    ext = message.get("extendedTextMessage")
    ctx = ext.get("contextInfo") if isinstance(ext, dict) else None
    stanza = ctx.get("stanzaId") if isinstance(ctx, dict) else None
    return str(stanza) if stanza else None


def _numero_curto(texto: str) -> int | None:
    match = re.search(r"#(\d+)\b", texto)
    return int(match.group(1)) if match else None


def _valor(texto: str) -> Decimal | None:
    sem_numero = re.sub(r"#\d+\b", "", texto, count=1)
    match = re.search(r"(?:r\$\s*)?(\d+(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+k)\b", sem_numero, re.I)
    if not match:
        return None
    token = match.group(1).lower()
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


def _motivo_perda(texto: str) -> str | None:
    for motivo in ["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"]:
        if motivo in texto:
            return motivo
    return None


def _invalido(erro: str) -> ComandoGrupo:
    return ComandoGrupo("comando_invalido", None, {"motivo": erro}, erro)
