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
    caption: str | None = None


@dataclass(frozen=True)
class ComandoGrupo:
    comando: Literal[
        "devolver_para_ia", "registrar_fechado", "registrar_perdido", "comando_invalido"
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
    if not message_id or not remote_jid:
        return None
    texto = _texto(message) or str(data.get("text") or data.get("body") or "")
    tipo = "texto"
    media_url = None
    caption: str | None = None
    if "audioMessage" in message:
        tipo = "audio"
        media_url = message["audioMessage"].get("url")
    elif "imageMessage" in message:
        tipo = "imagem"
        media_url = message["imageMessage"].get("url")
        raw_caption = message["imageMessage"].get("caption")
        caption = str(raw_caption).strip() or None if raw_caption else None
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
        caption=caption,
    )


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

    # Resposta ao card de Lembrete de fechamento (ADR-0009): citando o card, um valor "pelado"
    # (sem palavra-chave) fecha o atendimento. Prefixos conhecidos seguem o fluxo normal abaixo.
    if (
        aguardando_valor
        and numero is not None
        and not lower.startswith(("ia assume", "finalizado", "fechado", "perdido"))
    ):
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

    if lower.startswith("finalizado") or lower.startswith("fechado"):
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


def _motivo_perda(texto: str) -> str | None:
    for motivo in ["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"]:
        if motivo in texto:
            return motivo
    return None


def _invalido(erro: str) -> ComandoGrupo:
    return ComandoGrupo("comando_invalido", None, {"motivo": erro}, erro)
