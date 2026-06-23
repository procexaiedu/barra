"""Render dos cards "go-time" pickup (🤝) / vídeo chamada (🎥) — ADR 0020/0021. DB-free: só o
template. São momentos "chegou a hora" (como 🚪/✅), NÃO Handoff: cabeçalho próprio + 👉 (sua vez),
nunca o 🔔 genérico.
"""

from datetime import datetime

from barra.workers._cards import render_card


def test_cliente_busca_cabecalho_proprio_e_acao() -> None:
    texto = render_card(
        "cliente_busca",
        numero_curto=42,
        cliente_nome="João",
        endereco="Rua X, ponto combinado",
        horario=datetime(2026, 6, 22, 22, 0),
    )
    assert texto.startswith("🤝 *Cliente vem te buscar* · João · #42")
    assert "📍 Rua X, ponto combinado" in texto
    assert "🕒 22:00" in texto
    assert "👉 Fica pronta, o cliente vem te buscar" in texto
    # NÃO é Handoff: nada de 🔔 nem do sufixo "IA assume" do template genérico.
    assert "🔔" not in texto
    assert "IA assume" not in texto


def test_cliente_busca_sem_endereco_omite_linha() -> None:
    # Pickup costuma passar o ponto de encontro por texto (endereco NULL): a linha 📍 some.
    texto = render_card(
        "cliente_busca", numero_curto=7, cliente_nome="Ana", endereco=None, horario=None
    )
    assert "📍" not in texto
    assert "🕒" not in texto
    assert "🤝 *Cliente vem te buscar* · Ana · #7" in texto
    assert "👉 Fica pronta, o cliente vem te buscar" in texto


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
