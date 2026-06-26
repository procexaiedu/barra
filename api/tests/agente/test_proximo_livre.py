"""Pré-cálculo do slot adjacente após um bloqueio (`agente/nos/_proximo_livre.py`).

DB-free: exercita a aritmética pura (buffer + arredondamento social), o pula-bloqueio e o gate
de Disponibilidade (via `regras_cobrem`). Datas ancoradas numa segunda-feira (2026-06-15, DOW
Postgres = 1) para casar com as regras de disponibilidade.
"""

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from barra.agente.nos._proximo_livre import _arredonda_meia_hora_acima, proximo_livre
from barra.dominio.modelos.disponibilidade import regras_cobrem

BRT = ZoneInfo("America/Sao_Paulo")

# Segunda-feira; DOW Postgres = 1.
SEG = date(2026, 6, 15)
TER = date(2026, 6, 16)


def _dt(d: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=BRT)


def _bloco(inicio: datetime, fim: datetime) -> dict[str, Any]:
    return {"inicio": inicio, "fim": fim}


def _regra_seg(hi: time, hf: time) -> dict[str, Any]:
    return {
        "data_inicio": date(2026, 6, 1),
        "data_fim": None,
        "dia_semana": 1,  # segunda (DOW Postgres)
        "hora_inicio": hi,
        "hora_fim": hf,
    }


# --- Arredondamento puro ---------------------------------------------------


def test_arredonda_sobe_para_meia_hora() -> None:
    assert _arredonda_meia_hora_acima(_dt(SEG, 23, 17)) == _dt(SEG, 23, 30)


def test_arredonda_sobe_para_hora_cheia() -> None:
    assert _arredonda_meia_hora_acima(_dt(SEG, 22, 47)) == _dt(SEG, 23, 0)


def test_arredonda_mantem_quando_ja_na_meia_hora() -> None:
    assert _arredonda_meia_hora_acima(_dt(SEG, 22, 30)) == _dt(SEG, 22, 30)


def test_arredonda_sobe_quando_tem_segundos_na_borda() -> None:
    assert _arredonda_meia_hora_acima(_dt(SEG, 22, 30, 5)) == _dt(SEG, 23, 0)


# --- proximo_livre: buffer + arredondamento --------------------------------


def test_buffer_mais_arredondamento_sem_regras() -> None:
    # fim 22:47 + 30min = 23:17 -> arredonda 23:30. Sem regras = sempre disponível.
    fim = _dt(SEG, 22, 47)
    assert proximo_livre(fim, [], [], 30) == _dt(SEG, 23, 30)


def test_buffer_em_hora_cheia_cai_na_meia() -> None:
    # fim 22:00 + 30min = 22:30 (já redondo).
    assert proximo_livre(_dt(SEG, 22, 0), [], [], 30) == _dt(SEG, 22, 30)


# --- proximo_livre: lead_min separa offset-de-agora do gap (emenda ADR 0025) ----


def test_lead_min_zero_oferece_agora_arredondado() -> None:
    # Emenda 2026-06-26: horario_minimo dos tipos sem deslocamento usa lead_min=0 -> offset de AGORA
    # = ~0 (recebe já), só o arredondamento social. fim(=agora) 20:10 -> 20:30 (não 20:40 do buffer).
    assert proximo_livre(_dt(SEG, 20, 10), [], [], 30, lead_min=0) == _dt(SEG, 20, 30)


def test_lead_min_default_mantem_buffer() -> None:
    # Sem lead_min (proximo_livre por-bloqueio): offset = buffer_min, comportamento intacto.
    # fim 20:10 + 30 = 20:40 -> arredonda social pra cima = 21:00.
    assert proximo_livre(_dt(SEG, 20, 10), [], [], 30) == _dt(SEG, 21, 0)


def test_lead_min_zero_ainda_respeita_gap_do_vizinho() -> None:
    # O lead encurta SÓ o offset-de-agora; o gap em torno dos vizinhos segue buffer_min (30).
    # cand 20:30 (lead 0) com bloco 20:45-22:00 -> gap 15min < 30 -> pula o bloco -> 22:00+30 = 22:30.
    blocos = [_bloco(_dt(SEG, 20, 45), _dt(SEG, 22, 0))]
    assert proximo_livre(_dt(SEG, 20, 10), blocos, [], 30, lead_min=0) == _dt(SEG, 22, 30)


# --- proximo_livre: pula bloqueios seguintes -------------------------------


def test_pula_bloqueio_seguinte() -> None:
    # fim 22:00 -> cand 22:30; mas há bloco 22:30-23:30 -> pula p/ 23:30+30 = 00:00 do dia seguinte.
    fim = _dt(SEG, 22, 0)
    blocos = [_bloco(fim, fim), _bloco(_dt(SEG, 22, 30), _dt(SEG, 23, 30))]
    assert proximo_livre(fim, blocos, [], 30) == _dt(TER, 0, 0)


def test_pula_cadeia_de_bloqueios_consecutivos() -> None:
    # 22:30-23:30 e 00:00-01:00: do fim 22:00 pula os dois -> 01:00+30 = 01:30.
    fim = _dt(SEG, 22, 0)
    blocos = [
        _bloco(_dt(SEG, 22, 30), _dt(SEG, 23, 30)),
        _bloco(_dt(TER, 0, 0), _dt(TER, 1, 0)),
    ]
    assert proximo_livre(fim, blocos, [], 30) == _dt(TER, 1, 30)


def test_pula_quando_cand_cai_no_buffer_antes_do_proximo_bloco() -> None:
    # ADR 0025: cand 22:30 com bloco seguinte 22:45-24:00 -> gap 15min < buffer 30 -> a reserva
    # rejeitaria. Pula o bloco -> 24:00+30 = 00:30 (TER). (Antes oferecia 22:30 e a reserva falhava.)
    fim = _dt(SEG, 22, 0)
    blocos = [_bloco(_dt(SEG, 22, 45), _dt(TER, 0, 0))]
    assert proximo_livre(fim, blocos, [], 30) == _dt(TER, 0, 30)


def test_gap_exatamente_buffer_e_reservavel() -> None:
    # gap == buffer (30min): cand 22:30 com bloco 23:00-24:00 -> reservável (gap >= buffer). O `>`
    # estrito não pula. Espelha `i2 < new.fim + buffer` (23:00 < 23:00 é falso) do gate da reserva.
    fim = _dt(SEG, 22, 0)
    blocos = [_bloco(_dt(SEG, 23, 0), _dt(TER, 0, 0))]
    assert proximo_livre(fim, blocos, [], 30) == _dt(SEG, 22, 30)


# --- proximo_livre: gate de Disponibilidade --------------------------------


def test_dentro_da_disponibilidade_retorna_slot() -> None:
    fim = _dt(SEG, 21, 0)  # cand 21:30
    regras = [_regra_seg(time(14, 0), time(23, 0))]
    assert proximo_livre(fim, [], regras, 30) == _dt(SEG, 21, 30)


def test_fora_da_disponibilidade_retorna_none() -> None:
    # cand 23:30 cai fora da janela seg 14:00-23:00 -> omite a sugestão.
    fim = _dt(SEG, 23, 0)
    regras = [_regra_seg(time(14, 0), time(23, 0))]
    assert proximo_livre(fim, [], regras, 30) is None


def test_disponibilidade_que_cruza_meia_noite() -> None:
    # Janela seg 22:00-02:00 (cruza a meia-noite): cand 00:30 (TER) é coberto pelo transbordo.
    fim = _dt(SEG, 23, 50)  # +30 = 00:20 -> arredonda 00:30
    regras = [_regra_seg(time(22, 0), time(2, 0))]
    assert proximo_livre(fim, [], regras, 30) == _dt(TER, 0, 30)


# --- regras_cobrem: paridade da parte pura ---------------------------------


def test_regras_cobrem_vazio_sempre_disponivel() -> None:
    assert regras_cobrem([], _dt(SEG, 3, 0)) is True


def test_regras_cobrem_dentro_e_fora() -> None:
    regras = [_regra_seg(time(14, 0), time(18, 0))]
    assert regras_cobrem(regras, _dt(SEG, 15, 0)) is True
    assert regras_cobrem(regras, _dt(SEG, 21, 0)) is False
