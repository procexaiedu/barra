"""Aceite M0-T2 — render dos prompts BP1 (persona + regras) via Jinja."""

from barra.agente.persona import render_persona


def test_render_persona_nao_vazio_e_estavel() -> None:
    a = render_persona()
    b = render_persona()
    assert a.strip()  # não-vazio
    assert a == b  # idêntico em 2 chamadas (prefixo estável p/ cache global)


def test_render_persona_inclui_persona_e_regras() -> None:
    txt = render_persona()
    assert "<persona>" in txt  # BP1 = persona...
    assert "<conduta>" in txt  # ...+ regras
