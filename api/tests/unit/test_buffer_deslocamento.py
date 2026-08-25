"""Gap de deslocamento ao redor do bloqueio EXTERNO (emenda ADR 0025, 2026-08-14).

O pedido do dono: "cliente querendo ir logo quando ela sai de um serviço, sendo na casa de um
cliente (tem que ter um tempo de deslocamento até o lugar dela)". O gap entre atendimentos era um
número global de 30 min "para todos os tipos" — e a agenda nem sabia dizer se o compromisso
anterior tinha acontecido fora do local dela.

Aqui ficam as três provas que a emenda precisa sustentar:
  1. **assimetria** — o bloco externo alarga o gap dos DOIS lados dele (ida e volta), e só ele;
  2. **zona morta** — o horário publicado (`proximo_livre`/`horario_minimo`) é sempre reservável
     pela régua da reserva (`existe_vizinho_no_buffer`), inclusive na borda `cand == fim`;
  3. **compatibilidade** — bloqueio que não declara tipo se comporta exatamente como antes.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from barra.agente.nos._janelas_livres import janelas_livres
from barra.agente.nos._proximo_livre import proximo_livre
from barra.dominio.agenda.service import buffer_do_bloqueio_min
from barra.settings import get_settings

BRT = timezone(timedelta(hours=-3))
BUFFER = 30


def _dt(hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 8, 20, hora, minuto, tzinfo=BRT)


def _bloco(inicio: datetime, horas: float, tipo: str | None = None) -> dict[str, Any]:
    bloco: dict[str, Any] = {"inicio": inicio, "fim": inicio + timedelta(hours=horas)}
    if tipo is not None:
        bloco["tipo_atendimento"] = tipo
    return bloco


def _vizinho_no_buffer(inicio: datetime, fim: datetime, blocos: list[dict[str, Any]]) -> bool:
    """Régua da RESERVA em Python puro: o predicado do ADR 0025 (`new.inicio < f2 + buffer AND
    i2 < new.fim + buffer`), com o buffer POR VIZINHO. É o oráculo do `existe_vizinho_no_buffer`
    (que roda a mesma conta em SQL); True = a reserva RECUSA este intervalo, e nenhum horário
    publicado pelo pré-cálculo pode cair aqui."""
    for b in blocos:
        buffer = timedelta(minutes=buffer_do_bloqueio_min(b.get("tipo_atendimento")))
        if b["fim"] > inicio - buffer and b["inicio"] < fim + buffer:
            return True
    return False


# --- a régua em si -----------------------------------------------------------------------------


def test_so_o_externo_paga_o_buffer_maior() -> None:
    s = get_settings()
    assert buffer_do_bloqueio_min("externo") == s.agenda_buffer_externo_min
    assert buffer_do_bloqueio_min("interno") == s.agenda_buffer_min
    assert buffer_do_bloqueio_min("remoto") == s.agenda_buffer_min
    assert buffer_do_bloqueio_min(None) == s.agenda_buffer_min


def test_buffer_externo_e_maior_que_o_padrao() -> None:
    # O número é calibrável por env, mas a emenda não faz sentido se o externo não custar mais.
    s = get_settings()
    assert s.agenda_buffer_externo_min > s.agenda_buffer_min


def test_default_do_setting_novo_nao_muda_quem_nao_declara_tipo() -> None:
    # COMPATIBILIDADE (a garantia da emenda): sem tipo, o pré-cálculo devolve o mesmo de sempre —
    # fim + agenda_buffer_min, arredondado. Bloco declarado `interno` idem.
    fim = _dt(18, 30)
    sem_tipo = proximo_livre(fim, [_bloco(_dt(17, 30), 1)], [], BUFFER)
    interno = proximo_livre(fim, [_bloco(_dt(17, 30), 1, "interno")], [], BUFFER)
    assert sem_tipo == _dt(19, 0)
    assert interno == _dt(19, 0)


# --- 1. assimetria: o externo alarga os dois lados ----------------------------------------------


def test_volta_da_casa_do_cliente_empurra_o_proximo_horario() -> None:
    # O pedido do dono: ela termina um externo às 18:30 e o próximo cliente quer "ir logo".
    # Antes: 19:00 (fim + 30). Agora: 19:30 (fim + 60), o tempo de voltar.
    externo = _bloco(_dt(17, 30), 1, "externo")
    assert proximo_livre(externo["fim"], [externo], [], BUFFER) == _dt(19, 30)


def test_ida_ate_a_casa_do_cliente_tambem_conta() -> None:
    """O gap ANTES do externo cobre a ida — a viagem existe nas duas pontas.

    Ela sai de um interno às 18:00 e tem um externo às 19:00. Com o gap global de 30 min as 18:30
    passariam; com o buffer do externo valendo dos dois lados, o primeiro horário reservável já é
    depois do externo. Quem paga é o bloco EXTERNO, não o vizinho dele: assim a decisão sai do tipo
    de um bloqueio que JÁ existe — o único dado que o pré-cálculo do prompt (que só enxerga
    vizinhos) e o gate da reserva têm em comum.
    """
    interno = _bloco(_dt(17, 0), 1, "interno")
    externo = _bloco(_dt(19, 0), 1, "externo")
    blocos = [interno, externo]
    # 18:30 (fim do interno + 30) cai dentro do halo de ida do externo -> pulado.
    assert proximo_livre(interno["fim"], blocos, [], BUFFER) == _dt(21, 0)
    assert _vizinho_no_buffer(_dt(18, 30), _dt(19, 30), blocos)


def test_janela_livre_desconta_a_viagem_dos_dois_lados_do_externo() -> None:
    regras = [
        {
            "data_inicio": date(2026, 1, 1),
            "data_fim": None,
            "dia_semana": dow,
            "hora_inicio": time(10, 0),
            "hora_fim": time(23, 0),
        }
        for dow in range(7)
    ]
    externo = _bloco(_dt(15, 0), 1, "externo")
    livres = janelas_livres(_dt(10, 0), _dt(23, 0), [externo], regras, BUFFER)
    # Manhã fecha 60 min antes do externo (14:00, e não 14:30); tarde reabre 60 min depois (17:00).
    assert livres == [(_dt(10, 0), _dt(14, 0)), (_dt(17, 0), _dt(23, 0))]


# --- 2. zona morta: o que é publicado tem de ser reservável -------------------------------------


def test_horario_minimo_nao_cola_no_fim_de_um_bloqueio() -> None:
    """A zona morta: `proximo_livre` só testava "dentro do bloco ou no buffer ANTES dele".

    Bloqueio 17:30-18:30, `agora` 18:00, antecedência 30 -> o candidato caía exatamente em 18:30,
    o teste `cand < fim` era falso na borda e o piso publicado era o próprio 18:30 — que a reserva
    recusa (adjacência colada, ADR 0025). O sistema publicava um horário que ele mesmo rejeitava.
    """
    agora = _dt(18, 0)
    blocos = [_bloco(_dt(17, 30), 1)]
    piso = proximo_livre(agora, blocos, [], BUFFER, lead_min=BUFFER)
    assert piso == _dt(19, 0)
    assert not _vizinho_no_buffer(piso, piso + timedelta(hours=1), blocos)
    assert _vizinho_no_buffer(_dt(18, 30), _dt(19, 30), blocos)  # o valor antigo, irreservável


def test_todo_horario_publicado_e_reservavel_em_varias_bordas() -> None:
    """Propriedade, não exemplo: para uma grade de `agora` e de tipos, o que sai do pré-cálculo
    passa na régua da reserva. É o invariante que a zona morta violava em silêncio."""
    for tipo in (None, "interno", "remoto", "externo"):
        blocos = [_bloco(_dt(17, 30), 1, tipo)]
        for minuto in range(0, 120, 5):
            agora = _dt(17, 0) + timedelta(minutes=minuto)
            piso = proximo_livre(agora, blocos, [], BUFFER, lead_min=BUFFER)
            assert piso is not None
            assert not _vizinho_no_buffer(piso, piso + timedelta(hours=1), blocos), (
                f"tipo={tipo} agora={agora:%H:%M} publicou {piso:%H:%M}, que a reserva recusa"
            )


def test_zona_morta_do_externo_e_a_mais_larga() -> None:
    # Mesma borda, bloco externo: 18:30 e 19:00 são irreserváveis; o piso tem de ser 19:30.
    agora = _dt(18, 0)
    blocos = [_bloco(_dt(17, 30), 1, "externo")]
    assert proximo_livre(agora, blocos, [], BUFFER, lead_min=BUFFER) == _dt(19, 30)
    assert _vizinho_no_buffer(_dt(19, 0), _dt(20, 0), blocos)  # 19:00 ainda é a volta
