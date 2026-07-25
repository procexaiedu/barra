"""Janelas livres pré-computadas (#41, 24/07).

Aritmética pura: recorta as sessões de Disponibilidade e desconta os bloqueios alargados pelo
buffer. Os casos cobrem o que o `<agenda>` não sabia dizer — o dia livre ANTES do primeiro
compromisso, que é o que a IA não enxergou no #41.
"""

from datetime import date, datetime, time, timedelta
from typing import Any

from barra.agente.nos._janelas_livres import janelas_livres
from barra.dominio.modelos.disponibilidade import BRT

_BUFFER = 30


def _regras_todo_dia(hora_inicio: time, hora_fim: time) -> list[dict[str, Any]]:
    return [
        {
            "data_inicio": date(2026, 1, 1),
            "data_fim": None,
            "dia_semana": dow,
            "hora_inicio": hora_inicio,
            "hora_fim": hora_fim,
        }
        for dow in range(7)
    ]


def _bloqueio(inicio: datetime, horas: int) -> dict[str, Any]:
    return {"inicio": inicio, "fim": inicio + timedelta(hours=horas)}


def _em(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 7, 24, hora, minuto, tzinfo=BRT) + timedelta(days=dia)


def test_dia_livre_antes_do_bloqueio_aparece() -> None:
    # O caso do #41: expediente 10:00-04:00, único compromisso das 16 às 17. O contexto antigo só
    # tinha o 17:30 (proximo_livre do bloqueio) e a IA o vendeu como o horário do dia; a manhã
    # inteira estava vaga e agora sai explícita.
    regras = _regras_todo_dia(time(10, 0), time(4, 0))
    livres = janelas_livres(_em(0, 5), _em(1, 5), [_bloqueio(_em(0, 16), 1)], regras, _BUFFER)
    assert livres[0] == (_em(0, 10), _em(0, 15, 30))
    assert livres[1] == (_em(0, 17, 30), _em(1, 4))


def test_bloqueio_desconta_o_buffer_dos_dois_lados() -> None:
    # ADR 0025: gap >= buffer dos dois lados. Bloqueio 14-15 num expediente 10-18 corta 13:30-15:30.
    regras = _regras_todo_dia(time(10, 0), time(18, 0))
    livres = janelas_livres(_em(0, 10), _em(0, 18), [_bloqueio(_em(0, 14), 1)], regras, _BUFFER)
    assert livres == [(_em(0, 10), _em(0, 13, 30)), (_em(0, 15, 30), _em(0, 18))]


def test_fresta_curta_demais_nao_vira_oferta() -> None:
    # Entre dois bloqueios sobram 13:30-14:30 (1h)... mas com buffer sobra menos que o mínimo.
    regras = _regras_todo_dia(time(10, 0), time(18, 0))
    blocos = [_bloqueio(_em(0, 12), 2), _bloqueio(_em(0, 15), 2)]
    livres = janelas_livres(_em(0, 10), _em(0, 18), blocos, regras, _BUFFER)
    # 14:30-14:30 (fim 14:00 + buffer vs inicio 15:00 - buffer): fresta nula, some.
    assert livres == [(_em(0, 10), _em(0, 11, 30))]


def test_inicio_sobe_pra_meia_hora() -> None:
    # `inicio` no meio do expediente e fora da meia-hora: a janela começa no próximo :00/:30.
    regras = _regras_todo_dia(time(10, 0), time(18, 0))
    livres = janelas_livres(_em(0, 12, 13), _em(0, 18), [], regras, _BUFFER)
    assert livres == [(_em(0, 12, 30), _em(0, 18))]


def test_fora_do_expediente_comeca_na_abertura() -> None:
    # Cliente chegando 04:54 (o #41): a 1ª janela é a abertura do expediente, não o "agora".
    regras = _regras_todo_dia(time(10, 0), time(4, 0))
    livres = janelas_livres(_em(0, 4, 54), _em(0, 23), [], regras, _BUFFER)
    assert livres == [(_em(0, 10), _em(0, 23))]


def test_sem_disponibilidade_cadastrada_e_a_faixa_inteira() -> None:
    # Sem regra = reservável sempre (CONTEXT.md): a janela é a faixa pedida, menos os bloqueios.
    livres = janelas_livres(_em(0, 10), _em(0, 20), [_bloqueio(_em(0, 14), 1)], [], _BUFFER)
    assert livres == [(_em(0, 10), _em(0, 13, 30)), (_em(0, 15, 30), _em(0, 20))]


def test_dia_todo_ocupado_nao_tem_janela() -> None:
    regras = _regras_todo_dia(time(10, 0), time(18, 0))
    livres = janelas_livres(_em(0, 10), _em(0, 18), [_bloqueio(_em(0, 9), 10)], regras, _BUFFER)
    assert livres == []
