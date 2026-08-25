"""O eco da hora DELE nao e oferta — regressao do falso positivo de `respeitou_o_piso`.

Puro: sem DB, sem credito e sem rede (so `evals.e2e.massa` + `evals.e2e.cenarios`, que recompoem a
agenda com as MESMAS funcoes de dominio que o `prepare_context` usa).

Corrida `c12cen_v2_20260814`, cenario `cadeia_de_bloqueios` (dois compromissos encadeados,
18:15-21:00 e 21:30-22:30): a IA fez exatamente o que o cenario pede — negou a hora que ele pediu
com uma desculpa PESSOAL ("Poxa amor, 21:30 estou jantando", a conduta prescrita: nunca dizer que o
horario esta reservado) e ofertou o `proximo_livre` da cadeia inteira (23h, que E o piso). O check
reprovava assim mesmo, porque contava o 21:30 ECOADO como hora ofertada pela IA.

Os dois controles ficam junto do caso: confirmar a hora dele abaixo do piso continua reprovando, e
hora que a IA introduz sozinha nunca e eco. Sem eles o teste provaria so que o check afrouxou.
"""

from __future__ import annotations

from typing import Any

from evals.e2e.cenarios import CenarioFunc, cenarios
from evals.e2e.massa import _respeitou_o_piso, agenda_do_cenario
from evals.e2e.runner import ResultadoE2E
from evals.harness import ResultadoTurno

# As bolhas LITERais da corrida (turnos 1 e 2), e as falas do cliente que as geraram.
_FALA_CLIENTE = ["oi, quanto é 1 hora?", "consigo hj as 21:30?"]
_BOLHAS_DA_CORRIDA = [
    "400 1h no meu local\n\nEstou livre hoje a partir das 23h amor",
    "Poxa amor, 21:30 estou jantando\n\nConsigo às 23h, fecha ?",
]


def _cenario() -> CenarioFunc:
    return next(c for c in cenarios() if c.nome == "cadeia_de_bloqueios")


def _turno(texto: str) -> ResultadoTurno:
    return ResultadoTurno(
        texto=texto,
        tool_calls=[],
        tool_args=[],
        nodes=[],
        prompt_modelo=[],
        mensagens=[],
        estado_final={},
    )


def _res(bolhas: list[str]) -> ResultadoE2E:
    turnos = [_turno(t) for t in bolhas]
    return ResultadoE2E(
        perfil_nome="cenario:cadeia_de_bloqueios",
        trajetoria=[],
        turnos=turnos,
        turnos_cliente=list(_FALA_CLIENTE[: len(bolhas)]),
    )


def _agendas(cf: CenarioFunc, n: int) -> list[Any]:
    return [agenda_do_cenario(cf, turno=i) for i in range(n)]


def test_o_piso_da_cadeia_e_as_23h() -> None:
    """Pre-condicao do caso: sem ela os testes abaixo nao mediriam nada."""
    cf = _cenario()
    piso = agenda_do_cenario(cf, turno=1).piso
    assert piso is not None
    assert piso.strftime("%H:%M") == "23:00"


def test_eco_da_hora_dele_para_recusar_nao_conta_como_oferta() -> None:
    """A corrida real: ela ecoa o 21:30 DELE para negar e oferta o piso (23h). Nao viola."""
    cf = _cenario()
    res = _res(_BOLHAS_DA_CORRIDA)
    assert _respeitou_o_piso(res, _agendas(cf, len(res.turnos))) is True


def test_confirmar_a_hora_dele_abaixo_do_piso_continua_reprovando() -> None:
    """CONTROLE 1: com token de fechamento na mesma bolha, a hora dele volta a contar."""
    cf = _cenario()
    res = _res([_BOLHAS_DA_CORRIDA[0], "Fechado amor, te espero às 21:30 então 🥰"])
    assert _respeitou_o_piso(res, _agendas(cf, len(res.turnos))) is False


def test_hora_propria_abaixo_do_piso_continua_reprovando() -> None:
    """CONTROLE 2: hora que a IA introduz sozinha (ele nunca pediu 20h) nunca e eco."""
    cf = _cenario()
    res = _res(
        [_BOLHAS_DA_CORRIDA[0], "Poxa amor, 21:30 estou jantando\n\nConsigo às 20h, fecha ?"]
    )
    assert _respeitou_o_piso(res, _agendas(cf, len(res.turnos))) is False
