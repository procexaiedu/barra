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
