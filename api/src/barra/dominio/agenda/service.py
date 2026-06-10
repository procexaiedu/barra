"""Orquestracao de agenda: reserva previa de slot por atendimento (04 §3.1 branch 13).

`criar_bloqueio_previo` roda SEMPRE na transacao do chamador (a tool de escrita ja abre
uma via `_executar_idempotente`): snapshot + transicao + bloqueio precisam ser atomicos,
porque o advisory lock + a EXCLUDE de `bloqueios` nao toleram janela entre commit e lock.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import AsyncConnection
from psycopg.errors import ExclusionViolation

from barra.dominio.modelos.disponibilidade import modelo_disponivel_em

# Offset fixo -03:00 (espelha dominio/painel e dominio/dashboard); o horario_desejado do
# cliente e local (BRT). Combinar como aware evita o pitfall naive x aware (memoria de TZ).
BRT = timezone(timedelta(hours=-3))

# Fallback quando atendimento.duracao_horas e NULL: reserva 1h para o slot nao ficar vazio.
DURACAO_PADRAO_HORAS = 1


class ConflitoAgenda(Exception):
    """Slot ja reservado por outra conversa da mesma modelo (EXCLUDE de bloqueios)."""


class ForaDisponibilidade(Exception):
    """Inicio do bloqueio cai fora da Disponibilidade da modelo (ADR 0005: trava dura para a IA —
    'o sistema impede criar bloqueio fora dela'). Erro RECUPERAVEL: a tool de escrita instrui a IA
    a seguir a conduta de periodo de trabalho (revelar a volta e ancorar a 1a data disponivel).
    O override fora-da-disponibilidade e exclusivo do painel/Fernando (agenda/routes.py)."""


class HorarioNaoDefinido(Exception):
    """Reserva pedida sem `horario_desejado`: o chamador tentou reservar o slot antes de o horario
    combinado existir. Erro RECUPERAVEL -- a tool de escrita devolve instrucao p/ a IA confirmar o
    horario primeiro, nunca um crash de turno (o caminho interno ja so reserva com horario != None)."""


async def criar_bloqueio_previo(conn: AsyncConnection[Any], *, atendimento: dict[str, Any]) -> None:
    """Reserva o slot previo do atendimento (estado `bloqueado`, origem `ia`) e fecha a FK circular.

    inicio = (data_desejada ou hoje BRT) + horario_desejado; fim = inicio + (duracao_horas ou
    DURACAO_PADRAO_HORAS). Serializa o booking por modelo com `pg_advisory_xact_lock` (mesmo
    padrao do trigger gen_numero_curto, 0001_schema_inicial.sql:193); a EXCLUDE
    `bloqueios_sem_sobreposicao` (0001:515) e o backstop duro. Em sobreposicao levanta
    `ConflitoAgenda` -> o chamador reverte o turno e a tool reoferta outro horario.
    """
    modelo_id = atendimento["modelo_id"]
    data = atendimento.get("data_desejada") or datetime.now(BRT).date()
    horario = atendimento["horario_desejado"]
    if horario is None:
        # Sem horario combinado a reserva nao tem inicio (datetime.combine(data, None) estouraria
        # TypeError -> crash de turno). Precondicao do chamador: so reservar APOS o horario combinado.
        # Erro recuperavel: a tool de escrita captura e instrui a IA a confirmar o horario primeiro.
        raise HorarioNaoDefinido(
            "horario_desejado ausente: combine o horario antes de reservar o slot"
        )
    duracao = atendimento.get("duracao_horas") or DURACAO_PADRAO_HORAS
    inicio = datetime.combine(data, horario, tzinfo=BRT)
    fim = inicio + timedelta(hours=float(duracao))

    # Trava dura (ADR 0005): a IA nunca cria bloqueio fora da Disponibilidade. Valida so o
    # INICIO (o fim pode estourar a janela — Pernoite); modelo sem regra e reservavel sempre.
    # O painel nao passa por aqui (POST/PATCH /bloqueios tem INSERT proprio com o override
    # confirmar_fora_disponibilidade, exclusivo de Fernando).
    if not await modelo_disponivel_em(conn, modelo_id, inicio):
        raise ForaDisponibilidade("Inicio do bloqueio fora da disponibilidade da modelo.")

    # Advisory lock por modelo serializa o booking entre conversas distintas da MESMA modelo
    # ANTES do INSERT; a EXCLUDE pega o caso de duas transacoes que escaparem da serializacao.
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))",
        (str(modelo_id),),
    )
    try:
        res = await conn.execute(
            """
            INSERT INTO barravips.bloqueios (modelo_id, atendimento_id, inicio, fim, origem, estado)
            VALUES (%s, %s, %s, %s, 'ia', 'bloqueado')
            RETURNING id
            """,
            (modelo_id, atendimento["id"], inicio, fim),
        )
        row = await res.fetchone()
        assert row is not None
        # Back-link da FK circular: sem ele o trigger sync_bloqueio_estado e os crons de
        # agenda (que leem atendimentos.bloqueio_id) nunca tocam neste bloqueio.
        await conn.execute(
            "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
            (row["id"], atendimento["id"]),
        )
    except ExclusionViolation as exc:
        raise ConflitoAgenda("Slot ja reservado por outra conversa.") from exc
