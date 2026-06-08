"""F0.5 — gate determinístico de conteúdo da FAQ no prompt entregue.

Trava que os **itens críticos** da FAQ chegam ao bloco system geral que o agente recebe
(`render_prefixo_geral`, o BP_GERAL fundido persona+regras+FAQ — persona.py:93). Critério do
roadmap (F0.5): *edição que apaga um item crítico quebra o teste*. Não checa conduta ao vivo
(isso é F3.4, ★API); só garante que a fonte (`faq.md`) → conteúdo entregue não regride.

Sem banco e sem API: roda no `make test` padrão, então é gate de PR de verdade — não fica
pulado por falta de `TEST_DATABASE_URL` nem custa crédito.

Os marcadores são os fragmentos mínimos que identificam cada item. Apagar/reescrever o item
a ponto de sumir o fragmento deixa o teste vermelho.
"""

import pytest

from barra.agente.persona import render_prefixo_geral

# (id legível, fragmentos obrigatórios — TODOS precisam estar no prompt entregue).
_ITENS_CRITICOS: list[tuple[str, list[str]]] = [
    # Recusa de videochamada (faq.md): a IA não faz chamada de vídeo, oferece foto.
    ("recusa_videocall", ["video chamada eu nao faço"]),
    # Pix de R$100 do deslocamento é SEPARADO do valor do programa (ADR — externo).
    ("pix_100_separado", ["R$100", "deslocamento", "separado do valor do programa"]),
    # Taxa de 10% no cartão (ADR 0013).
    ("taxa_cartao_10", ["10%", "maquininha"]),
    # Cartão sem parcelamento — fechamento é valor único (ADR 0013).
    ("sem_parcelamento", ["não parcelo"]),
]


@pytest.mark.parametrize(
    "item_id, fragmentos", _ITENS_CRITICOS, ids=[i[0] for i in _ITENS_CRITICOS]
)
def test_item_critico_presente_no_prompt_entregue(item_id: str, fragmentos: list[str]) -> None:
    prompt = render_prefixo_geral()
    faltando = [f for f in fragmentos if f not in prompt]
    assert not faltando, f"item crítico '{item_id}' regrediu — fragmentos ausentes: {faltando}"


def test_ancora_anti_vacuo() -> None:
    """Prova que o prompt entregue não veio vazio/quebrado — senão um 'fragmento ausente'
    seria um falso-positivo silencioso (o item não some, o render é que falhou)."""
    prompt = render_prefixo_geral()
    assert prompt.strip()
    assert "<faq>" in prompt  # a seção FAQ chegou ao bloco geral
