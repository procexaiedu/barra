"""`_reagendamento_pos_bloqueio`, ramo do PALPITE (`horario_evidenciado=false` na reserva).

Regressões da revisão de domínio da rodada 1 do loop de massa (12/08/2026):
  - achado 2: mudança só de DATA sem hora evidenciada era "descarta" — a data que o CLIENTE
    falou ("melhor amanhã") sumia e a reserva ficava no dia velho com ele certo de que remarcou.
    Data não tem marca de proveniência; agora escala ("mudanca").
  - achado 3: o "realoca" do palpite ignorava `_modelo_ainda_nao_acionada` — com Pix andando ou
    aviso de saída, a hora nova movia a reserva em silêncio, sem card novo. Agora escala.
  - achado 1 (REFUTADO, vira regressão): retração do cliente (`limpar=['horario_desejado']`)
    devolve "mudanca" ANTES do ramo do palpite — nunca "descarta" (que deixaria bloqueio órfão).

Sem DB: conn fake devolve a row do SELECT; a assinatura pede só (conn, id, payload, kw).
"""

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

from barra.dominio.atendimentos.service import _reagendamento_pos_bloqueio

_AID = UUID("00000000-0000-0000-0000-00000000d001")


def _conn(row: dict[str, Any] | None) -> AsyncMock:
    conn = AsyncMock()
    res = AsyncMock()
    res.fetchone = AsyncMock(return_value=row)
    conn.execute = AsyncMock(return_value=res)
    return conn


def _row_palpite(**sobrescreve: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "estado": "Aguardando_confirmacao",
        "bloqueio_id": UUID("00000000-0000-0000-0000-00000000d002"),
        "horario_desejado": "21:00:00",
        "data_desejada": None,
        "horario_evidenciado": False,
        "aviso_saida_em": None,
        "pix_status": "nao_solicitado",
        # A guarda le a conversa para checar a proveniencia da hora nova (`_hora_saiu_da_boca_dela`,
        # 14/08). None = sem historico persistido: sobra so a fala do turno, que estes casos nao
        # passam — o ramo do PALPITE que este arquivo pina segue decidido pelos mesmos criterios.
        "conversa_id": None,
    }
    base.update(sobrescreve)
    return base


async def test_hora_evidenciada_realoca_quando_modelo_nao_acionada() -> None:
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite()), _AID, {"horario_desejado": "18:00"}, evidenciado_no_turno=True
    )
    assert veredito == "realoca"


async def test_hora_evidenciada_com_pix_andando_escala() -> None:
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite(pix_status="aguardando")),
        _AID,
        {"horario_desejado": "18:00"},
        evidenciado_no_turno=True,
    )
    assert veredito == "mudanca"


async def test_hora_evidenciada_com_aviso_de_saida_escala() -> None:
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite(aviso_saida_em="2026-08-12T20:00:00+00:00")),
        _AID,
        {"horario_desejado": "18:00"},
        evidenciado_no_turno=True,
    )
    assert veredito == "mudanca"


async def test_data_nova_sem_hora_evidenciada_realoca_com_modelo_nao_acionada() -> None:
    """O achado 2 da r1 continua valendo no que ele protege: "melhor amanhã" (sem hora) sobre
    reserva-palpite NÃO é ruído da IA e NUNCA é "descarta" — a data dele não pode sumir deixando a
    reserva no dia velho. O que muda (prova r3, `explorador_ambiguo_a` t7) é o destino: enquanto a
    modelo não foi acionada, mover a reserva pro dia dele é ajuste de agenda, não evento que mereça
    acordar ninguém. Escalar ali pausava a IA no ponto de fechar."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite()), _AID, {"data_desejada": "2026-08-13"}, evidenciado_no_turno=False
    )
    assert veredito == "realoca"


async def test_data_nova_sem_hora_evidenciada_escala_com_modelo_acionada() -> None:
    """Acionada a modelo (Pix andando), a data nova volta a ser evento dela: escala."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite(pix_status="aguardando")),
        _AID,
        {"data_desejada": "2026-08-13"},
        evidenciado_no_turno=False,
    )
    assert veredito == "mudanca"


async def test_so_hora_sem_evidencia_descarta() -> None:
    """Eco/palpite trocando o próprio palpite: não move agenda nem acorda a modelo."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite()), _AID, {"horario_desejado": "18:00"}, evidenciado_no_turno=False
    )
    assert veredito == "descarta"


async def test_retracao_por_limpar_libera_a_reserva_com_modelo_nao_acionada() -> None:
    """Achado 1 da r1 (refutado) pinado como regressão: recuo NUNCA vira "descarta" — zerar o
    snapshot sem tratar o bloqueio o deixaria órfão travando a agenda.

    Prova r3 (`remarcacao` t6, "hoje não consigo mais, marco outro dia"): com a modelo ainda não
    acionada o destino certo não é escalar (que pausava a IA e matava o t7 "amanhã 21h" no vazio) —
    é "libera": solta a reserva EXPLICITAMENTE (sem órfão) e devolve a conversa pra combinar o
    novo dia."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite()), _AID, {"limpar": ["horario_desejado"]}, evidenciado_no_turno=False
    )
    assert veredito == "libera"


async def test_retracao_por_limpar_sobre_hora_combinada_tambem_libera() -> None:
    """O recuo vale igual quando a hora reservada foi cravada por ele (`horario_evidenciado`):
    é a mesma remarcação segura da decisão de 12/08, no eixo do recuo."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite(horario_evidenciado=True)),
        _AID,
        {"limpar": ["data_desejada", "horario_desejado"]},
        evidenciado_no_turno=False,
    )
    assert veredito == "libera"


async def test_retracao_por_limpar_escala_com_modelo_acionada() -> None:
    """Com aviso de saída dado, a modelo já se organizou pela hora do card: o recuo é evento dela."""
    veredito = await _reagendamento_pos_bloqueio(
        _conn(_row_palpite(aviso_saida_em="2026-08-12T20:00:00+00:00")),
        _AID,
        {"limpar": ["horario_desejado"]},
        evidenciado_no_turno=False,
    )
    assert veredito == "mudanca"
