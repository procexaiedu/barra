"""Render do card de comprovante Pix do remoto (ADR 0029). DB-free: só o template.

O Pix do remoto antecipa o VALOR DA CHAMADA, não deslocamento: o card nunca fala de
saída/Uber nem carrega 📍 endereço, e segue o léxico ✅/⚠️ do CARDS.md.
"""

from datetime import datetime
from decimal import Decimal

from barra.workers._cards import render_card


def test_pix_remoto_validado() -> None:
    texto = render_card(
        "pix_remoto",
        numero_curto=51,
        cliente_nome="Bia",
        endereco="Rua X, 100",  # presente no contexto, mas o template do remoto NÃO exibe
        horario=datetime(2026, 6, 22, 20, 30),
        valor_acordado=Decimal("300.00"),
        valor_extraido=Decimal("300.00"),
        decisao="validado",
        motivo_em_revisao=None,
    )
    assert texto.startswith("✅ *Pix da vídeo chamada* · Bia · #51")
    assert "🕒 20:30" in texto
    assert "💰 Combinado" in texto
    assert "💸 Recebido" in texto
    assert "👉 Pix ok, chamada de pé pro horário" in texto
    assert "📍" not in texto
    assert "Uber" not in texto
    assert "aída" not in texto  # "Saída"/"saída" — card do remoto não fala de saída


def test_pix_remoto_duvidoso() -> None:
    texto = render_card(
        "pix_remoto",
        numero_curto=51,
        cliente_nome="Bia",
        endereco=None,
        horario=None,
        valor_acordado=Decimal("300.00"),
        valor_extraido=Decimal("150.00"),
        decisao="em_revisao",
        motivo_em_revisao="valor extraido 150.00 < esperado R$300.00",
    )
    assert texto.startswith("⚠️ *Pix duvidoso (vídeo chamada)* · Bia · #51")
    assert "valor extraido 150.00" in texto
    assert "👉 Você decide se faz a chamada — o Fernando confere depois, sem travar" in texto
    assert "Uber" not in texto
