"""`contem_pedido_de_infos` (_disciplina): a porta do PITCH — "como funciona?", "me passa as infos".

O detector nasceu sem teste nenhum e a lacuna apareceu no loop-massa r2: "Gostaria de informações
sobre seu atendimento" — a abertura mais comum do lead que vem do site — NÃO casava, embora o
próprio conjunto já liste `quero|queria` + `informacoes`. É inconsistência interna do conjunto
fechado, não recorte: "gostaria" é o mesmo verbo em outro modo.

Ele só acende o ponteiro condicional de pitch no `<proximo_passo>` (prepare_context), nunca um
guard — o falso-positivo custa uma cauda a mais no prompt, não uma fala barrada.
"""

import pytest

from barra.agente._disciplina import contem_pedido_de_infos


@pytest.mark.parametrize(
    "fala",
    [
        "gostaria de informações",
        "Gostaria de mais informações amor",
        "gostaria de saber mais",
        # as formas que já casavam continuam casando
        "quero informações",
        "queria as infos",
        "como funciona?",
        "me passa mais detalhes",
        "quais são seus serviços",
    ],
)
def test_pedido_de_apresentacao_e_detectado(fala: str) -> None:
    assert contem_pedido_de_infos(fala)


@pytest.mark.parametrize(
    "fala",
    [
        "gostaria de marcar amanhã",  # "gostaria" sozinho não é pedido de apresentação
        "gostaria de te ver hoje",
        "quanto custa?",  # vocabulário de preço tem trilho próprio (<cotacao>)
        "qual o valor amor",
        "tudo bem?",
    ],
)
def test_fora_da_familia_nao_acende_o_pitch(fala: str) -> None:
    assert not contem_pedido_de_infos(fala)


@pytest.mark.parametrize(
    "fala",
    [
        "Olá, Júlia. Peguei seu contato no site. Gostaria de informações sobre seu atendimento",
        "Oi, vi seu anúncio no site. Gostaria de mais detalhes",
    ],
)
def test_ancora_do_site_veta_o_pitch(fala: str) -> None:
    """REVERSÃO DELIBERADA do pino da r2 (campanha 13/08): o template do site casava o detector e
    o <proximo_passo> injetava "apresente completo de uma vez" — o oposto do que a <abertura>
    (regras.md.j2) manda para a MESMA âncora ("só cumprimente e deixe ele falar"). As duas
    instruções conviviam no mesmo prompt em praticamente todo lead de site; a <abertura> vence
    porque é a conduta validada (o vendedor real faz o mesmo e o cliente volta). O que ele
    DIGITOU sem a âncora segue acendendo o pitch (testes positivos acima)."""
    assert not contem_pedido_de_infos(fala)
