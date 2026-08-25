"""`_reagendamento_pos_bloqueio`, prova de PROVENIENCIA da hora nova ("A BOCA DELA", 14/08).

Corrida `c12_tardio` (16 conversas): a guarda produziu 2 dos 6 handoffs, os dois indevidos —
ela pausava a IA quando a hora nova tinha saido da boca da PROPRIA IA:

  - caso (a), `eb04:154412781666344` t27: a IA reofertou "Consigo te receber a partir das 10:30,
    fecha ?" sobre uma reserva de 10:00 e o cliente aceitou ("E o horario, 10:30 entao ?"). O
    `aviso_saida_em` estava carimbado desde o t17 — pelo CLIENTE ("cheguei aqui na sunny") —, entao
    `_modelo_ainda_nao_acionada` era False e o aceite virou "mudanca";
  - caso (b), `eb02:1460423151841` t12: o snapshot tinha 19:00 (extracao leu "umas 10 hrs no
    maximo" como prazo) contra os 10h da conversa inteira e da bolha dela ("Entao fica 10h amor").
    A extracao se corrigiu para 10:00 e, como o 19:00 errado estava carimbado como evidenciado por
    ELE e a fala do turno ("Calma ai") nao tinha hora, virou "mudanca".

O CONTROLE NEGATIVO (`test_recuo_com_pix_andando_continua_escalando`) e o terceiro handoff da mesma
corrida, esse LEGITIMO: `eb02:103173956083798` t11, cliente desmarcando de vez com Pix em
`aguardando`. Ele continua escalando — inclusive com a hora antiga na boca dela, que e o jeito de
essa correcao o desarmar por acidente.

Sem DB: conn fake devolve a row do SELECT de atendimentos e as bolhas do SELECT de mensagens.
"""

from datetime import date, time
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

from barra.dominio.atendimentos.service import (
    _reagendamento_pos_bloqueio,
    horarios_ditos_na_fala,
)

_AID = UUID("00000000-0000-0000-0000-00000000e001")
_CID = UUID("00000000-0000-0000-0000-00000000e0c1")


def _conn(row: dict[str, Any], bolhas: list[str] | None = None) -> AsyncMock:
    """Fake que distingue as duas leituras da guarda: o atendimento (fetchone) e as falas dela
    (fetchall, ordem DESC = mais recente primeiro, como a query real)."""
    conn = AsyncMock()

    async def execute(query: str, params: Any = None) -> AsyncMock:
        res = AsyncMock()
        if "FROM barravips.mensagens" in query:
            # Respeita o LIMIT da query real (params = (conversa_id, limite)) — e ele que pina a
            # janela da rajada; um fake que devolvesse tudo faria o teste da janela passar por acaso.
            limite = params[1] if params and len(params) > 1 else None
            res.fetchall = AsyncMock(
                return_value=[{"conteudo": b} for b in (bolhas or [])[:limite]]
            )
            res.fetchone = AsyncMock(return_value=None)
        else:
            res.fetchone = AsyncMock(return_value=row)
            res.fetchall = AsyncMock(return_value=[row])
        return res

    conn.execute = AsyncMock(side_effect=execute)
    return conn


def _row(**sobrescreve: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "estado": "Aguardando_confirmacao",
        "bloqueio_id": UUID("00000000-0000-0000-0000-00000000e002"),
        "horario_desejado": time(10, 0),
        "data_desejada": date(2026, 8, 14),
        "horario_evidenciado": True,
        "aviso_saida_em": None,
        "pix_status": "nao_solicitado",
        "conversa_id": _CID,
    }
    base.update(sobrescreve)
    return base


# --- caso (a): a re-oferta DELA que ele aceitou ------------------------------------------------


async def test_reoferta_dela_aceita_por_ele_realoca_mesmo_com_aviso_de_saida() -> None:
    """O caso vivo: 10:30 na bolha dela do turno anterior, ele aceita, `aviso_saida_em` carimbado
    pela chegada DELE. Antes: "mudanca" (IA pausada no turno do fechamento)."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(
            _row(aviso_saida_em="2026-08-14T13:00:00+00:00"),
            ["Consigo te receber a partir das 10:30, fecha ?", "To na rua Latino Coelho, 421"],
        ),
        _AID,
        {"horario_desejado": "10:30:00", "data_desejada": "2026-08-14"},
        evidenciado_no_turno=True,
    )
    assert veredito == "realoca"


async def test_reoferta_dela_na_bolha_DESTE_turno_tambem_realoca() -> None:
    """A bolha deste turno ainda nao esta em `mensagens` — chega pelo State, como no valor
    fantasma. Sem ela a proveniencia so enxergaria o turno anterior."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row(pix_status="aguardando"), []),
        _AID,
        {"horario_desejado": "10:30:00"},
        evidenciado_no_turno=True,
        fala_da_ia_no_turno="Consigo as 10:30 entao amor\n\nTe espero",
    )
    assert veredito == "realoca"


# --- caso (b): a extracao corrigindo o proprio erro ---------------------------------------------


async def test_correcao_da_propria_extracao_descarta_em_vez_de_escalar() -> None:
    """19:00 no snapshot, 10h em toda a conversa e na bolha dela; a extracao se corrige e a fala do
    turno nao tem hora. Antes: "mudanca". Agora: ruido dela — descarta, sem acordar ninguem."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(
            _row(horario_desejado=time(19, 0), pix_status="aguardando"),
            ["chave pix: pix-teste@example.invalid", "Entao fica 10h amor"],
        ),
        _AID,
        {"horario_desejado": "10:00:00", "data_desejada": "2026-08-14"},
        evidenciado_no_turno=False,
    )
    assert veredito == "descarta"


# --- o que NAO pode mudar ----------------------------------------------------------------------


async def test_recuo_com_pix_andando_continua_escalando() -> None:
    """CONTROLE NEGATIVO (handoff legitimo da mesma corrida): o cliente desmarca de vez, com Pix em
    `aguardando`. `limpar` e julgado ANTES da proveniencia — desmarcar nao e dizer hora nenhuma —,
    entao nem a hora antiga viva na boca dela desarma a escalada."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(
            _row(horario_desejado=time(16, 0), pix_status="aguardando"),
            ["Combinado, te espero as 16h"],
        ),
        _AID,
        {"limpar": ["data_desejada", "horario_desejado"], "horario_desejado": "16:00:00"},
        evidenciado_no_turno=False,
    )
    assert veredito == "mudanca"


async def test_hora_que_so_ele_disse_com_modelo_acionada_continua_escalando() -> None:
    """Reagendamento de verdade: a hora nova nao esta em nenhuma bolha dela. Segue "mudanca" —
    e a REMARCACAO SEGURA (12/08) que decide, como antes."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row(pix_status="aguardando"), ["Consigo te receber as 10h, fecha ?"]),
        _AID,
        {"horario_desejado": "22:00:00"},
        evidenciado_no_turno=True,
    )
    assert veredito == "mudanca"


async def test_hora_que_ela_RECUSOU_nao_e_proveniencia() -> None:
    """ "as 22h nao consigo" cita a hora para nega-la. Legitima-la aqui seria a guarda lendo a
    recusa como oferta — o erro que `horas_recusadas_na_fala` ja documenta do outro lado."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row(pix_status="aguardando"), ["Poxa amor, as 22h nao consigo"]),
        _AID,
        {"horario_desejado": "22:00:00"},
        evidenciado_no_turno=True,
    )
    assert veredito == "mudanca"


async def test_data_nova_nao_entra_pela_porta_da_hora() -> None:
    """Ela citar "10h" nao autoriza mover o DIA: com a data diferente, o veredito continua saindo
    dos ramos de sempre (aqui, modelo acionada -> "mudanca")."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row(pix_status="aguardando"), ["Entao fica 10h amor"]),
        _AID,
        {"horario_desejado": "10:00:00", "data_desejada": "2026-08-15"},
        evidenciado_no_turno=False,
    )
    assert veredito == "mudanca"


async def test_hora_dita_ha_muitos_turnos_nao_conta() -> None:
    """A janela e a RAJADA (`_JANELA_BOLHAS_DA_RAJADA`): a hora ofertada e nunca aceita expira
    quando ela reoferta de novo. Aqui as 4 bolhas recentes falam de 22h e o 10:30 caiu fora da
    janela (o fake corta pelo LIMIT da query, como o banco)."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(
            _row(pix_status="aguardando"),
            [
                "Te espero as 22h",
                "Me manda o endereco",
                "Bom dia amor",
                "Oii",
                "Consigo as 10:30, fecha ?",
            ],
        ),
        _AID,
        {"horario_desejado": "10:30:00"},
        evidenciado_no_turno=True,
    )
    assert veredito == "mudanca"


# --- o scanner puro ----------------------------------------------------------------------------


def test_horarios_ditos_le_minuto_e_hora_cheia() -> None:
    assert horarios_ditos_na_fala("Consigo te receber a partir das 10:30, fecha ?") == {
        time(10, 30)
    }
    assert horarios_ditos_na_fala("Entao fica 10h amor") == {time(10, 0)}
    assert horarios_ditos_na_fala("Te espero as 22h") == {time(22, 0)}
    assert horarios_ditos_na_fala("Consigo as 18h30 amor") == {time(18, 30)}


def test_horarios_ditos_veta_preco_e_recusa() -> None:
    # linha de tabela: "1h" e duracao vendida, nao 01:00.
    assert horarios_ditos_na_fala("Fica 400 1h no meu local amor") == set()
    assert horarios_ditos_na_fala("A 2h fica 700") == set()
    # recusa nao oferta.
    assert horarios_ditos_na_fala("Poxa amor, 9h nao consigo") == set()
    # a oferta da bolha seguinte sobrevive a recusa da anterior (bolhas separadas por \n\n).
    assert horarios_ditos_na_fala("Poxa amor, 9h nao consigo\n\nPode ser as 10h ?") == {time(10, 0)}
