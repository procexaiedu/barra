"""Fase 4 — render do card de digest de pendencias (UX §6.4). DB-free: so o template."""

from datetime import datetime

from barra.dominio.atendimentos.service import Pendencia
from barra.workers._cards import render_card


def test_pendencias_vazio_mostra_estado_tudo_em_dia() -> None:
    texto = render_card("pendencias", pendencias=[])
    assert "📋 *Pendências* · tudo em dia ✨" in texto
    assert "Nenhum card aguardando você agora." in texto
    # estado vazio nao tem rodape de acao (nao ha #N para citar)
    assert "👉" not in texto


def test_pendencias_lista_as_tres_categorias_com_emoji_e_copy() -> None:
    pendencias = [
        Pendencia(58, "Lia", "handoff", "Cliente pediu valor fora da tabela", None),
        Pendencia(42, "Marina", "falta_valor", None, datetime(2026, 6, 9, 14, 30)),
        Pendencia(51, "Bia", "pix", None, None),
    ]
    texto = render_card("pendencias", pendencias=pendencias)

    assert "📋 *Pendências* · 3 aguardando você" in texto
    assert "🔔 #58 Lia — handoff: Cliente pediu valor fora da tabela" in texto
    assert "💵 #42 Marina — falta o valor (encerrou 14:30)" in texto
    assert "⚠️ #51 Bia — Pix a conferir" in texto
    # rodape cita o primeiro #N como exemplo de comando
    assert "👉 responda no número, ex.: *fechado #58 1500*" in texto


def test_pendencias_sem_linhas_em_branco_entre_itens() -> None:
    # trim_blocks/lstrip_blocks: os blocos de controle nao deixam linha vazia entre os itens.
    pendencias = [
        Pendencia(1, "A", "pix", None, None),
        Pendencia(2, "B", "pix", None, None),
    ]
    texto = render_card("pendencias", pendencias=pendencias)
    linhas = [ln for ln in texto.splitlines()]
    idx1 = next(i for i, ln in enumerate(linhas) if "#1" in ln)
    idx2 = next(i for i, ln in enumerate(linhas) if "#2" in ln)
    assert idx2 == idx1 + 1, f"itens devem ser consecutivos, sem linha em branco: {linhas!r}"
