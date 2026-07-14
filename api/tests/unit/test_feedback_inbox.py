"""Ingestão automática do rig de feedback (issue #93): gate + payload + emissor best-effort.

Cobre o Seam puro (`montar_inbox_payload`), o gate do webhook (`_eh_grupo_feedback`) e o no-op do
emissor com tracing off (o caminho de pytest, sem chaves Langfuse). A emissão real contra o
Langfuse é exercitada ao vivo — aqui garantimos que ela NUNCA levanta com tracing desligado.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from barra.core.feedback_inbox import (
    emitir_feedback_inbox,
    montar_inbox_payload,
    montar_rodape_issue,
    parse_rodape_issue,
)
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


class _FakeArq:
    """Captura os enqueue_job do ack — devolve truthy como o ARQ real no sucesso."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def enqueue_job(self, name: str, **kwargs: object) -> object:
        self.calls.append((name, kwargs))
        return object()

    async def aclose(self) -> None:  # o lifespan da app chama no shutdown
        return None


def _fake_request(*, feedback_rig_ack: bool = False, arq: object = None) -> SimpleNamespace:
    settings = SimpleNamespace(
        feedback_rig_ack=feedback_rig_ack, feedback_rig_grupo_jid=JID_FEEDBACK
    )
    state = SimpleNamespace(settings=settings, arq=arq)
    return SimpleNamespace(app=SimpleNamespace(state=state))


@pytest.mark.asyncio
async def test_capturar_curto_circuita_sem_levantar(monkeypatch: pytest.MonkeyPatch) -> None:
    # A captura devolve o envelope de ack mesmo com tracing off (trace_id vira ""); ack desligado.
    monkeypatch.setattr("barra.core.tracing.langfuse_handler", lambda: None)
    resposta = await _capturar_feedback_rig(
        _fake_request(), _msg(tipo="imagem", texto="", media_base64="Zm9v")
    )
    assert resposta == {"status": "feedback_rig", "trace_id": ""}


@pytest.mark.asyncio
async def test_ack_arma_debounce_coalescido_por_grupo(monkeypatch: pytest.MonkeyPatch) -> None:
    # Feedback com substância + ack ligado → agenda 1 job deferido, coalescido por grupo, citando a msg.
    monkeypatch.setattr("barra.core.tracing.langfuse_handler", lambda: None)
    arq = _FakeArq()
    await _capturar_feedback_rig(
        _fake_request(feedback_rig_ack=True, arq=arq),
        _msg(texto="esse horário a IA inventou de novo, tá bugado"),
    )
    assert len(arq.calls) == 1
    name, kwargs = arq.calls[0]
    assert name == "enviar_ack_feedback_rig"
    assert kwargs["_job_id"] == f"ack_fb:{JID_FEEDBACK}"  # SET NX first-wins coalesce a rajada
    assert kwargs["quoted_message_id"] == "ABC123"


@pytest.mark.asyncio
async def test_ack_nao_arma_para_ruido_curto(monkeypatch: pytest.MonkeyPatch) -> None:
    # 'blz' não tem substância → nenhum ack (mesmo com o trace capturado indiscriminadamente).
    monkeypatch.setattr("barra.core.tracing.langfuse_handler", lambda: None)
    arq = _FakeArq()
    await _capturar_feedback_rig(_fake_request(feedback_rig_ack=True, arq=arq), _msg(texto="blz"))
    assert arq.calls == []


@pytest.mark.asyncio
async def test_ack_desligado_por_padrao_nao_arma(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gate `feedback_rig_ack=False` (default) → captura o trace mas não agenda ack.
    monkeypatch.setattr("barra.core.tracing.langfuse_handler", lambda: None)
    arq = _FakeArq()
    await _capturar_feedback_rig(
        _fake_request(feedback_rig_ack=False, arq=arq),
        _msg(texto="feedback longo o suficiente pra armar o ack"),
    )
    assert arq.calls == []


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


# ---- Fase B: rodapé da issue + webhook do GitHub (aviso de "desenvolvido") --------------------


def test_parse_rodape_roundtrip_e_malformado() -> None:
    rodape = montar_rodape_issue(
        message_id="ABC123", remote_jid=JID_FEEDBACK, texto="linha 1\nlinha 2 > x"
    )
    meta = parse_rodape_issue(f"corpo da issue\n\n{rodape}")
    # texto saneado: uma linha, sem '>'.
    assert meta == {
        "message_id": "ABC123",
        "remote_jid": JID_FEEDBACK,
        "texto": "linha 1 linha 2 x",
    }
    assert parse_rodape_issue("sem rodape nenhum") is None
    assert parse_rodape_issue("<!-- feedback-rig: {json quebrado -->") is None
    assert parse_rodape_issue(None) is None


def _assinar(secret: str, corpo: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), corpo, hashlib.sha256).hexdigest()


def test_github_webhook_issue_fechada_com_rodape_enfileira(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from barra.main import app

    settings = app.state.settings
    monkeypatch.setattr(settings, "github_webhook_secret", "s3cr3t")
    monkeypatch.setattr(settings, "feedback_rig_grupo_jid", JID_FEEDBACK)
    monkeypatch.setattr(settings, "evolution_instancia", "lucia")

    rodape = montar_rodape_issue(
        message_id="ABC123", remote_jid=JID_FEEDBACK, texto="o horario bugou"
    )
    corpo = json.dumps(
        {"action": "closed", "issue": {"number": 42, "body": f"fix\n{rodape}"}}
    ).encode()
    arq = _FakeArq()
    with TestClient(app) as client:
        app.state.db_pool = _FakePoolFB()
        app.state.arq = arq
        response = client.post(
            "/webhook/github",
            content=corpo,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": _assinar("s3cr3t", corpo),
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "aviso_desenvolvido"
    assert len(arq.calls) == 1
    name, kwargs = arq.calls[0]
    assert name == "enviar_aviso_desenvolvido"
    assert kwargs["quoted_message_id"] == "ABC123"
    assert kwargs["_job_id"] == "dev_fb:ABC123"  # idempotência por message_id


def test_github_webhook_assinatura_invalida_401(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from barra.main import app

    monkeypatch.setattr(app.state.settings, "github_webhook_secret", "s3cr3t")
    corpo = json.dumps({"action": "closed", "issue": {"body": ""}}).encode()
    arq = _FakeArq()
    with TestClient(app) as client:
        app.state.db_pool = _FakePoolFB()
        app.state.arq = arq
        response = client.post(
            "/webhook/github",
            content=corpo,
            headers={"X-GitHub-Event": "issues", "X-Hub-Signature-256": "sha256=deadbeef"},
        )

    assert response.status_code == 401
    assert arq.calls == []  # não enfileira nada sem assinatura válida


def test_github_webhook_desligado_sem_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from barra.main import app

    monkeypatch.setattr(app.state.settings, "github_webhook_secret", None)
    arq = _FakeArq()
    with TestClient(app) as client:
        app.state.db_pool = _FakePoolFB()
        app.state.arq = arq
        response = client.post(
            "/webhook/github", content=b"{}", headers={"X-GitHub-Event": "issues"}
        )

    assert response.status_code == 200
    assert response.json()["status"] == "github_webhook_off"
    assert arq.calls == []
