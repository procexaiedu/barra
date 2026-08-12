"""A virada da madrugada como HOJE para a escada de desconto (correção 12/08).

`_quando_do_encontro` (rótulo humano) já tratava a madrugada da mesma noite de trabalho como "ainda
hoje" desde 11/08, mas `_encontro_do_turno` (que decide o REGIME de preço) ainda classificava o
encontro às 00:30 marcado às 23:39 como `outro_dia` — pela data de calendário pura. O efeito era
dinheiro: `outro_dia` abre a escada de DUAS rodadas (degrau + piso), enquanto `hoje` abre UMA (o
piso). O mesmo encontro a 51 minutos ganhava desconto de dois estágios.

A correção extrai o critério da virada num helper único (`_e_ainda_hoje`) e faz os DOIS leitores —
o rótulo humano e o regime da escada — decidirem por ele, para não divergirem na meia-noite.

MUDANÇA DE COMPORTAMENTO (flag de eval): a madrugada-que-já-vem passou de `outro_dia` para `hoje`
no regime de desconto. Estes testes fixam o novo contrato.
"""

from datetime import date, datetime, time

from barra.agente.nos.prepare_context import _e_ainda_hoje, _encontro_do_turno, _quando_do_encontro

_HOJE = date(2026, 8, 11)
_AMANHA = date(2026, 8, 12)
_NOITE = datetime(2026, 8, 11, 23, 39)  # BRT naive, como `data_atual` deriva
_MADRUGADA = time(0, 30)
_TARDE = time(15, 0)


def test_e_ainda_hoje_reconhece_a_virada_da_mesma_noite() -> None:
    # 23:39 agora, encontro amanhã 00:30 → mesma noite de trabalho.
    assert _e_ainda_hoje(_AMANHA, _HOJE, _MADRUGADA, _NOITE) is True


def test_e_ainda_hoje_e_falso_para_encontro_de_verdade_no_dia_seguinte() -> None:
    # Amanhã à tarde não é a virada — é outro dia de fato.
    assert _e_ainda_hoje(_AMANHA, _HOJE, _TARDE, _NOITE) is False


def test_e_ainda_hoje_exige_que_seja_noite_agora() -> None:
    # Encontro amanhã 00:30, mas agora são 10h da manhã: não é a virada desta noite.
    manha = datetime(2026, 8, 11, 10, 0)
    assert _e_ainda_hoje(_AMANHA, _HOJE, _MADRUGADA, manha) is False


def test_e_ainda_hoje_falso_sem_hora_ou_sem_data() -> None:
    assert _e_ainda_hoje(_AMANHA, _HOJE, None, _NOITE) is False
    assert _e_ainda_hoje(None, _HOJE, _MADRUGADA, _NOITE) is False
    assert _e_ainda_hoje(_AMANHA, _HOJE, _MADRUGADA, None) is False


def test_encontro_do_turno_trata_a_madrugada_como_hoje() -> None:
    # O NÚCLEO da correção: regime de HOJE (uma rodada), não outro_dia (duas).
    assert (
        _encontro_do_turno(
            _AMANHA,
            _HOJE,
            estado="Qualificado",
            confirmou_hoje=False,
            horario_desejado=_MADRUGADA,
            agora=_NOITE,
        )
        == "hoje"
    )


def test_encontro_do_turno_mantem_outro_dia_para_o_dia_seguinte_de_verdade() -> None:
    assert (
        _encontro_do_turno(
            _AMANHA,
            _HOJE,
            estado="Qualificado",
            confirmou_hoje=False,
            horario_desejado=_TARDE,
            agora=_NOITE,
        )
        == "outro_dia"
    )


def test_encontro_do_turno_sem_hora_ou_relogio_cai_no_calendario() -> None:
    # Sem `horario_desejado`/`agora` (defaults) a virada não é reconhecível: outro_dia, como antes.
    assert (
        _encontro_do_turno(_AMANHA, _HOJE, estado="Qualificado", confirmou_hoje=False)
        == "outro_dia"
    )


def test_encontro_do_turno_mesmo_dia_continua_hoje() -> None:
    assert (
        _encontro_do_turno(
            _HOJE,
            _HOJE,
            estado="Qualificado",
            confirmou_hoje=False,
            horario_desejado=_TARDE,
            agora=_NOITE,
        )
        == "hoje"
    )


def test_rotulo_humano_e_regime_leem_o_mesmo_helper() -> None:
    # A garantia da unificação: para o mesmo encontro de madrugada, o rótulo diz "ainda hoje" e o
    # regime diz "hoje" — os dois derivam de `_e_ainda_hoje`, sem divergir.
    assert _quando_do_encontro(_AMANHA, _HOJE, _MADRUGADA, _NOITE) == "ainda hoje (madrugada)"
    assert (
        _encontro_do_turno(
            _AMANHA,
            _HOJE,
            estado="Qualificado",
            confirmou_hoje=False,
            horario_desejado=_MADRUGADA,
            agora=_NOITE,
        )
        == "hoje"
    )
