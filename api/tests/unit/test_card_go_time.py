"""Render do card "go-time" vídeo chamada (🎥) — ADR 0021. DB-free: só o template. É momento
"chegou a hora" (como 🚪/✅), NÃO Handoff: cabeçalho próprio + 👉 (sua vez), nunca o 🔔 genérico.
"""

from datetime import datetime

from barra.workers._cards import render_card


def test_video_chamada_cabecalho_proprio_e_acao() -> None:
    texto = render_card(
        "video_chamada",
        numero_curto=51,
        cliente_nome="Bia",
        endereco=None,
        horario=datetime(2026, 6, 22, 20, 30),
    )
    assert texto.startswith("🎥 *Hora da vídeo chamada* · Bia · #51")
    assert "🕒 20:30" in texto
    assert "👉 Hora de chamar o cliente no vídeo" in texto
    # Remoto não tem local físico (nunca 📍) nem é Handoff.
    assert "📍" not in texto
    assert "🔔" not in texto


def test_video_chamada_exibe_status_do_pix() -> None:
    # ADR 0029: o go-time informa o Pix antecipado — a modelo decide a chamada informada;
    # o Pix nunca gateia a transição (o card sai mesmo sem comprovante).
    base = dict(numero_curto=51, cliente_nome="Bia", endereco=None, horario=None)
    assert "💸 Pix recebido" in render_card("video_chamada", pix_status="validado", **base)
    assert "⚠️ Pix duvidoso" in render_card("video_chamada", pix_status="em_revisao", **base)
    assert "❗ Pix não recebido" in render_card("video_chamada", pix_status="aguardando", **base)
    # Sem solicitação (ex.: remoto legado sem valor acordado): nenhuma linha de Pix.
    texto = render_card("video_chamada", pix_status="nao_solicitado", **base)
    assert "Pix" not in texto
