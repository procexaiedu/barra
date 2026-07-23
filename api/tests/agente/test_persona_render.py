"""Aceite M0-T2 — render dos prompts BP1 (persona + regras) via Jinja."""

from datetime import UTC, datetime

from barra.agente.persona import render_contexto_dinamico, render_persona, render_reminder


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


def test_pix_deslocamento_so_no_externo() -> None:
    """Pix de deslocamento existe só quando a modelo se desloca (externo). Como `pix_status` é
    `NOT NULL DEFAULT 'nao_solicitado'`, o bloco renderizado sem filtro plantava um Pix pendente
    ("ainda não pedido") num atendimento interno — e o rótulo `pix_deslocamento` mente no remoto
    (lá o Pix antecipa o valor da chamada, ADR 0029, não o deslocamento). Só o externo mostra."""
    base = dict(
        numero_curto=1,
        estado="Qualificado",
        pix_status="ainda não pedido",
        proximo_passo="combinar horário",
    )
    assert "pix_deslocamento" in render_contexto_dinamico(tipo_atendimento="externo", **base)
    for tipo in ("interno", "remoto", None):
        assert "pix_deslocamento" not in render_contexto_dinamico(tipo_atendimento=tipo, **base)
    # variável ausente de todo (Undefined) também não renderiza nem quebra
    assert "pix_deslocamento" not in render_contexto_dinamico(**base)


def test_coerencia_thread_longa_no_reminder() -> None:
    """Fixes de coerência em thread longa (issue coerencia-thread-longa, cluster nao_contidos 23/07).

    O reminder anti-drift é o eco condensado que só dispara em thread longa (>=8 falas da IA), a
    condição exata dos dois incidentes. Ele deve carregar as duas âncoras: (a) não chutar bairro
    fora do cadastro (#1 Cambuí) e (b) a última correção/recusa do cliente manda (#2 BDSM)."""
    txt = render_reminder(fase="Triagem", nome="Tatiane")
    assert "bairro" in txt  # #1: não inventar bairro
    # #2: honrar a correção/recusa mais recente do cliente
    assert "recus" in txt and "tirou da mesa" in txt


def test_coerencia_thread_longa_no_canonico() -> None:
    """Site canônico (regras.md.j2, dentro de render_persona) das mesmas duas âncoras — dispara
    sempre, não só na thread longa (a disciplina multi-site do agente/CLAUDE.md: canônico define,
    reminder ecoa)."""
    txt = render_persona()
    # #1: bairro chutado não vira endereço novo (linha do degrau de endereço)
    assert "Cambuí" in txt and "bairro que ele chutar" in txt
    # #2: o que ele acabou de recusar manda, não reintroduzir ato tirado da mesa
    assert "tirou da mesa" in txt and "perdeu o fio" in txt
