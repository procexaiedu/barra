"""Âncora anti-vácuo do bloco geral entregue ao agente.

Garante que `render_prefixo_geral` (BP_GERAL = persona + regras) não vem vazio/quebrado e que
a conduta chega ao prompt. Sem banco e sem API: roda no `make test` padrão, é gate de PR de verdade.
"""

from barra.agente.persona import render_prefixo_geral


def test_ancora_anti_vacuo() -> None:
    """Prova que o prompt entregue não veio vazio/quebrado e que persona+regras chegaram ao bloco."""
    prompt = render_prefixo_geral()
    assert prompt.strip()
    assert "<persona>" in prompt
    assert "<conduta>" in prompt
