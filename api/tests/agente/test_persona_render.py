"""Aceite M0-T2 — render dos prompts BP1 (persona + regras) + BP2 (FAQ) via Jinja."""

from barra.agente.persona import carregar_faq, render_persona


def test_render_persona_nao_vazio_e_estavel() -> None:
    a = render_persona()
    b = render_persona()
    assert a.strip()  # não-vazio
    assert a == b  # idêntico em 2 chamadas (prefixo estável p/ cache global)


def test_render_persona_inclui_persona_e_regras() -> None:
    txt = render_persona()
    assert "<persona>" in txt  # BP1 = persona...
    assert "<conduta>" in txt  # ...+ regras


def test_desconto_desligado_diz_que_nao_concede() -> None:
    txt = render_persona(desconto_max_pct=0)
    assert "não concede desconto" in txt


def test_desconto_ligado_interpola_percentual() -> None:
    txt = render_persona(desconto_max_pct=0.15)
    assert "15%" in txt
    assert "não concede desconto" not in txt


def test_carregar_faq_nao_vazio_e_estavel() -> None:
    a = carregar_faq()
    assert a.strip()
    assert a == carregar_faq()
