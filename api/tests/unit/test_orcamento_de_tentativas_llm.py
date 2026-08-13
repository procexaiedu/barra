"""O par `llm_timeout_s` x `max_retries` tem de caber dentro do `turno_timeout_s`.

A r3 baixou o timeout por chamada para 40s contra um teto de turno de 60s justamente para a chamada
pendurada morrer DENTRO do grafo (onde o guard tem fallback determinístico) e não por fora, no
`asyncio.wait_for` do coordenador — que é terminal: `timeout_grafo` -> handoff, cliente sem bolha.

A desigualdade valia para UMA tentativa. O cliente OpenAI retenta timeout de httpx por conta
própria, e `max_retries=2` fixo multiplicava o pior caso por três (3 x 40s = 120s > 60s), desfazendo
em silêncio o invariante que o fix acabara de estabelecer (revisão LangGraph, loop-massa r3).

Sem DB, sem crédito: só a conta e a fiação da factory.
"""

import pytest

from barra.core.llm import criar_chat_deepseek, tentativas_que_cabem_no_turno
from barra.settings import Settings


def _settings(llm_s: float, turno_s: float) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        deepseek_api_key="x",
        llm_timeout_s=llm_s,
        turno_timeout_s=turno_s,
    )


def test_o_default_de_prod_so_comporta_uma_tentativa() -> None:
    """40 < 60 deixa 20s de folga — que não dá para uma segunda chamada de 40s."""
    s = Settings(_env_file=None, deepseek_api_key="x")  # type: ignore[call-arg]
    assert (s.llm_timeout_s, s.turno_timeout_s) == (40.0, 60.0)
    assert tentativas_que_cabem_no_turno(s) == 0


@pytest.mark.parametrize(
    ("llm_s", "turno_s", "esperado"),
    [
        (40.0, 60.0, 0),  # prod
        (60.0, 60.0, 0),  # o estado até 12/08: nem a primeira cabia
        (20.0, 60.0, 1),  # baixar o timeout devolve UMA retentativa sozinho
        (10.0, 60.0, 2),  # e o teto histórico segura o resto
        (5.0, 60.0, 2),
    ],
)
def test_as_tentativas_saem_da_conta_e_nunca_passam_do_teto(
    llm_s: float, turno_s: float, esperado: int
) -> None:
    assert tentativas_que_cabem_no_turno(_settings(llm_s, turno_s)) == esperado


@pytest.mark.parametrize(
    ("llm_s", "turno_s"),
    [(40.0, 60.0), (60.0, 60.0), (20.0, 60.0), (10.0, 60.0), (5.0, 60.0), (30.0, 45.0)],
)
def test_o_pior_caso_cabe_sempre_no_teto_do_turno(llm_s: float, turno_s: float) -> None:
    """O invariante em si, e não o número: nenhuma configuração pode deixar o pior caso de um
    `ainvoke` passar do teto do turno."""
    s = _settings(llm_s, turno_s)
    tentativas = 1 + tentativas_que_cabem_no_turno(s)
    assert tentativas * s.llm_timeout_s < s.turno_timeout_s or tentativas == 1


def test_a_factory_usa_o_orcamento_nos_dois_ramos() -> None:
    """Chat #1 roda thinking (subclasse própria) e extração/judge rodam disabled — os dois liam o
    mesmo `2` fixo, então os dois precisam da mesma conta."""
    s = _settings(40.0, 60.0)
    assert criar_chat_deepseek(s).max_retries == 0
    assert criar_chat_deepseek(s, thinking="low").max_retries == 0
    folgado = _settings(10.0, 60.0)
    assert criar_chat_deepseek(folgado).max_retries == 2
