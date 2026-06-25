"""Aceite M0-T2 — render dos prompts BP1 (persona + regras) via Jinja."""

from datetime import UTC, datetime

from barra.agente.persona import render_contexto_dinamico, render_persona


def test_render_persona_nao_vazio_e_estavel() -> None:
    a = render_persona()
    b = render_persona()
    assert a.strip()  # não-vazio
    assert a == b  # idêntico em 2 chamadas (prefixo estável p/ cache global)


def test_render_persona_inclui_persona_e_regras() -> None:
    txt = render_persona()
    assert "<persona>" in txt  # BP1 = persona...
    assert "<conduta>" in txt  # ...+ regras


def test_contexto_dinamico_renderiza_agenda_em_brt() -> None:
    """Regressão do bug de fuso (memória `bug_horario_minimo_render_utc`).

    `horario_minimo` e os campos de `bloqueio` chegam aware-UTC (psycopg/proximo_livre); o template
    deve renderizá-los em horário de Brasília via o filtro `|brt`. Sem a conversão a IA recebe o
    piso/ocupado +3h e recusa horários válidos da tarde. As datas são de jun/2026 (sem DST: -3h)."""
    txt = render_contexto_dinamico(
        numero_curto=1,
        estado="Qualificado",
        pix_status="—",
        proximo_passo="combinar horário",
        horario_minimo=datetime(2026, 6, 25, 21, 0, tzinfo=UTC),  # 18:00 BRT
        bloqueios=[
            {
                "inicio": datetime(2026, 6, 26, 1, 30, tzinfo=UTC),  # 22:30 BRT, vira o dia (25/06)
                "fim": datetime(2026, 6, 26, 2, 30, tzinfo=UTC),  # 23:30 BRT
                "proximo_livre": datetime(2026, 6, 26, 3, 0, tzinfo=UTC),  # 00:00 BRT
            }
        ],
    )
    # horario_minimo em BRT, nunca na hora UTC crua
    assert "18:00" in txt and "21:00" not in txt
    # bloqueio: hora E dia convertidos (01:30Z do 26/06 -> 22:30 BRT do 25/06)
    assert "25/06 22:30" in txt and "26/06 01:30" not in txt
    assert 'fim="23:30"' in txt
