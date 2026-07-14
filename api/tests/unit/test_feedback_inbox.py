"""Ingestão automática do rig de feedback (issue #93): gate + payload + emissor best-effort.

Cobre o Seam puro (`montar_inbox_payload`), o gate do webhook (`_eh_grupo_feedback`) e o no-op do
emissor com tracing off (o caminho de pytest, sem chaves Langfuse). A emissão real contra o
Langfuse é exercitada ao vivo — aqui garantimos que ela NUNCA levanta com tracing desligado.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from barra.core.feedback_inbox import emitir_feedback_inbox, montar_inbox_payload
from barra.webhook.parser import MensagemEvolution
from barra.webhook.routes import _capturar_feedback_rig, _eh_grupo_feedback

JID_FEEDBACK = "120363426757729499@g.us"


def _msg(
    *,
    remote_jid: str = JID_FEEDBACK,
    from_me: bool = False,
    tipo: str = "texto",
    texto: str = "esse horário a IA inventou",
    media_base64: str | None = None,
    media_mimetype: str | None = None,
) -> MensagemEvolution:
    return MensagemEvolution(
        evolution_message_id="ABC123",
        instance_id="procex-teste",
        remote_jid=remote_jid,
        sender_jid="5511999999999@s.whatsapp.net",
        from_me=from_me,
        texto=texto,
        tipo=tipo,  # type: ignore[arg-type]
        media_url=None,
        quoted_message_id=None,
        media_base64=media_base64,
        media_mimetype=media_mimetype,
    )


def test_gate_respeita_jid_e_ignora_fromme() -> None:
    cfg = SimpleNamespace(feedback_rig_grupo_jid=JID_FEEDBACK)
    assert _eh_grupo_feedback(_msg(), cfg) is True
    # fromMe = eco do reply-marcador postado pela própria IA → não recaptura (senão faz loop).
    assert _eh_grupo_feedback(_msg(from_me=True), cfg) is False
    # Outro JID (grupo de teste, cliente) não é o inbox de feedback.
    assert _eh_grupo_feedback(_msg(remote_jid="120363423572479616@g.us"), cfg) is False
    # Gate desligado (default) = inerte, mesmo no JID certo.
    assert _eh_grupo_feedback(_msg(), SimpleNamespace(feedback_rig_grupo_jid=None)) is False


def test_montar_payload_carrega_texto_e_midia() -> None:
    payload = montar_inbox_payload(
        message_id="ABC123",
        remote_jid=JID_FEEDBACK,
        autor="5511999999999@s.whatsapp.net",
        tipo="audio",
        texto="",
        caption=None,
        media_base64="Zm9v",
        media_mimetype="audio/ogg",
    )
    assert payload["message_id"] == "ABC123"
    assert payload["tipo"] == "audio"
    assert payload["media_base64"] == "Zm9v"  # base64 vai inteiro (STT roda dev-time na skill)
    assert payload["media_mimetype"] == "audio/ogg"
    # O ts do feedback NÃO viaja no payload — é o timestamp do trace no Langfuse.
    assert "ts" not in payload


def test_emitir_no_op_com_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    # Handler Langfuse None (tracing off) → emissão é no-op silencioso, jamais levanta. Forçamos o
    # None em vez de assumir a suíte: outro teste pode ter ligado o handler (global de módulo).
    monkeypatch.setattr("barra.core.tracing.langfuse_handler", lambda: None)
    payload = montar_inbox_payload(
        message_id="ABC123",
        remote_jid=JID_FEEDBACK,
        autor=None,
        tipo="texto",
        texto="oi",
        caption=None,
        media_base64=None,
        media_mimetype=None,
    )
    assert emitir_feedback_inbox(payload, message_id="ABC123") is None


def test_capturar_curto_circuita_sem_levantar(monkeypatch: pytest.MonkeyPatch) -> None:
    # A captura devolve o envelope de ack mesmo com tracing off (trace_id vira "").
    monkeypatch.setattr("barra.core.tracing.langfuse_handler", lambda: None)
    resposta = _capturar_feedback_rig(_msg(tipo="imagem", texto="", media_base64="Zm9v"))
    assert resposta == {"status": "feedback_rig", "trace_id": ""}


class _FakePoolFB:
    """Pool mínimo só para o handler não abortar em 503 — o branch de feedback retorna antes de usá-lo."""

    async def close(self) -> None:
        return None


def test_webhook_captura_feedback_antes_do_jid_permitido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão de ordem: o grupo de feedback é capturado ANTES do gate `jid_permitido`.

    Em prod o `jid_permitido` restringe o agente aos grupos de teste (Playground/Coordenação) e NÃO
    inclui o grupo de feedback; se o gate rodasse primeiro, a mensagem cairia em `JidNaoPermitido` e
    a ingestão nunca dispararia. Este teste fixa o grupo de feedback fora do allowlist e prova que
    ele ainda é capturado.
    """
    from fastapi.testclient import TestClient

    from barra.main import app

    monkeypatch.setattr("barra.core.tracing.langfuse_handler", lambda: None)
    settings = app.state.settings
    monkeypatch.setattr(settings, "evolution_webhook_token", "")
    monkeypatch.setattr(
        settings, "jid_permitido", ["120363000000000000@g.us"]
    )  # NÃO inclui o feedback
    monkeypatch.setattr(settings, "feedback_rig_grupo_jid", JID_FEEDBACK)

    payload = {
        "instance": "lucia",
        "data": {
            "key": {"id": "FB-REGRESSAO-1", "remoteJid": JID_FEEDBACK},
            "message": {"conversation": "esse horário a IA inventou"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = _FakePoolFB()
        response = client.post("/webhook/evolution", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "feedback_rig"
