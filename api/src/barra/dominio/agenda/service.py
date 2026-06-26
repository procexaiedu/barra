"""Orquestracao de agenda: reserva previa de slot por atendimento (04 §3.1 branch 13).

`criar_bloqueio_previo` roda SEMPRE na transacao do chamador (a tool de escrita ja abre
uma via `_executar_idempotente`): snapshot + transicao + bloqueio precisam ser atomicos,
porque o advisory lock + a EXCLUDE de `bloqueios` nao toleram janela entre commit e lock.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import AsyncConnection
from psycopg.errors import ExclusionViolation

from barra.dominio.modelos.disponibilidade import (
    carregar_regras_disponibilidade,
    fim_sessao,
    regras_cobrem,
)
from barra.settings import get_settings

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


class AntecedenciaInsuficiente(Exception):
    """Inicio do bloqueio cai dentro do buffer de preparo a partir de agora (inicio < now + buffer,
    ADR 0025). Erro RECUPERAVEL e DISTINTO de ConflitoAgenda: nao ha outro cliente a esconder — e
    tempo de preparo. A tool instrui a IA a ancorar no <horario_minimo> do contexto (sem inventar
    minutos). So a IA passa por aqui; o painel/Fernando nao tem antecedencia minima."""


async def existe_vizinho_no_buffer(
    conn: AsyncConnection[Any],
    *,
    modelo_id: Any,
    inicio: datetime,
    fim: datetime,
    buffer_min: int,
    excluir_id: Any | None = None,
) -> bool:
    """True se ha um bloqueio ATIVO da modelo a menos de `buffer_min` do intervalo [inicio, fim]
    (ADR 0025, gap >= buffer). Condicao do ADR: new.inicio < f2 + buffer AND i2 < new.fim + buffer.
    A EXCLUDE `bloqueios_sem_sobreposicao` so barra sobreposicao real ('[)'); a adjacencia colada
    (fim == inicio) e a quase-adjacencia caem aqui. `excluir_id` ignora o proprio bloqueio (PATCH).
    Reusado pela IA (`criar_bloqueio_previo`) e pelo painel (POST/PATCH /bloqueios)."""
    params: list[Any] = [modelo_id, inicio, buffer_min, fim, buffer_min]
    filtro_self = ""
    if excluir_id is not None:
        filtro_self = "AND id <> %s"
        params.append(excluir_id)
    res = await conn.execute(
        f"""
        SELECT 1
          FROM barravips.bloqueios
         WHERE modelo_id = %s
           AND estado IN ('bloqueado', 'em_atendimento')
           AND fim    > %s - make_interval(mins => %s)
           AND inicio < %s + make_interval(mins => %s)
           {filtro_self}
         LIMIT 1
        """,
        params,
    )
    return await res.fetchone() is not None


async def criar_bloqueio_previo(conn: AsyncConnection[Any], *, atendimento: dict[str, Any]) -> None:
    """Reserva o slot previo do atendimento (estado `bloqueado`, origem `ia`) e fecha a FK circular.

    inicio = (data_desejada ou hoje BRT) + horario_desejado; fim = inicio + (duracao_horas ou
    DURACAO_PADRAO_HORAS). Buffer de preparo/intervalo (ADR 0025, `agenda_buffer_min`) e regra DURA:
    antecedencia minima (inicio < now + buffer -> `AntecedenciaInsuficiente`) e gap entre
    atendimentos (vizinho ativo dentro do buffer -> `ConflitoAgenda`). Serializa o booking por modelo
    com `pg_advisory_xact_lock` (mesmo padrao do trigger gen_numero_curto, 0001_schema_inicial.sql:193);
    a EXCLUDE `bloqueios_sem_sobreposicao` (0001:515) e o backstop de sobreposicao real. Cada erro
    recuperavel reverte o turno e a tool reoferta (ConflitoAgenda) ou ancora no horario_minimo
    (AntecedenciaInsuficiente).
    """
    modelo_id = atendimento["modelo_id"]
    # Um unico `agora` p/ todo o booking: o default de data, o roll cross-midnight e o guard de
    # antecedencia leem o mesmo instante (sem o risco de `.date()` e o roll caírem em lados
    # opostos da meia-noite por dois now() distintos).
    agora = datetime.now(BRT)
    data = atendimento.get("data_desejada") or agora.date()
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

    # Regras de Disponibilidade lidas uma vez: servem ao gate de cobertura E ao fim_sessao do roll
    # cross-midnight abaixo (evita bater o banco duas vezes no mesmo turno).
    regras = await carregar_regras_disponibilidade(conn, modelo_id)

    # Roll cross-midnight (CONTEXT.md "Bloqueio"/borda da meia-noite): um horario combinado anterior a
    # `agora` no mesmo dia civil mas dentro da MESMA sessao de trabalho ainda aberta (janela que cruza
    # a meia-noite, ex.: 10:00-04:00) pertence ao DIA SEGUINTE — a extracao ancora "hoje" na data
    # enquanto o <horario_minimo> ja e do dia seguinte (00:30 as 23:55). So rola com cobertura da mesma
    # sessao (fim_sessao); horario genuinamente passado (22:00 as 23:55, fora da sessao) NAO rola e cai
    # no guard de antecedencia (ancora no horario_minimo). `data_rolada` persiste a data corrigida no
    # UPDATE da FK abaixo p/ o snapshot do atendimento nao divergir do bloqueio.
    data_rolada = False
    if inicio < agora:
        alvo = inicio + timedelta(days=1)
        fim_da_sessao = fim_sessao(regras, agora)
        if fim_da_sessao is not None:
            mesma_sessao = agora <= alvo <= fim_da_sessao
        elif not regras:
            # Modelo sem regras (disponivel sempre): sem fronteira de sessao, limita o roll ao rabo
            # tipico de cross-midnight (<= 6h apos agora) p/ nao rolar um horario realmente passado.
            mesma_sessao = agora <= alvo <= agora + timedelta(hours=6)
        else:
            # `agora` fora de qualquer janela: nao ha sessao aberta p/ continuar — nao rola.
            mesma_sessao = False
        if mesma_sessao:
            data, inicio, fim = alvo.date(), alvo, alvo + timedelta(hours=float(duracao))
            data_rolada = True

    # Trava dura (ADR 0005): a IA nunca cria bloqueio fora da Disponibilidade. Valida so o
    # INICIO (o fim pode estourar a janela — Pernoite); modelo sem regra e reservavel sempre.
    # O painel nao passa por aqui (POST/PATCH /bloqueios tem INSERT proprio com o override
    # confirmar_fora_disponibilidade, exclusivo de Fernando).
    if not regras_cobrem(regras, inicio):
        raise ForaDisponibilidade("Inicio do bloqueio fora da disponibilidade da modelo.")

    # Antecedencia minima (ADR 0025): a IA nunca reserva dentro do buffer de preparo a partir de
    # agora. Casa com o <horario_minimo> do contexto (arredonda_acima(now + buffer)); aqui o teto e
    # cru (now + buffer), pois qualquer inicio >= horario_minimo ja o satisfaz. Nao precisa do lock.
    buffer = get_settings().agenda_buffer_min
    if inicio < agora + timedelta(minutes=buffer):
        raise AntecedenciaInsuficiente(
            "Inicio dentro do buffer de preparo a partir de agora (now + buffer)."
        )

    # Advisory lock por modelo serializa o booking entre conversas distintas da MESMA modelo
    # ANTES do gap-check e do INSERT; a EXCLUDE pega o caso de duas transacoes que escaparem.
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))",
        (str(modelo_id),),
    )
    # Gap entre atendimentos (ADR 0025): vizinho ativo dentro do buffer -> rejeita (gap >= buffer).
    if await existe_vizinho_no_buffer(
        conn, modelo_id=modelo_id, inicio=inicio, fim=fim, buffer_min=buffer
    ):
        raise ConflitoAgenda("Vizinho ativo dentro do buffer de intervalo.")
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
        # agenda (que leem atendimentos.bloqueio_id) nunca tocam neste bloqueio. Quando o roll
        # cross-midnight corrigiu a data, persiste data_desejada junto p/ snapshot == bloqueio.
        if data_rolada:
            await conn.execute(
                "UPDATE barravips.atendimentos SET bloqueio_id = %s, data_desejada = %s "
                "WHERE id = %s",
                (row["id"], inicio.date(), atendimento["id"]),
            )
        else:
            await conn.execute(
                "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
                (row["id"], atendimento["id"]),
            )
    except ExclusionViolation as exc:
        raise ConflitoAgenda("Slot ja reservado por outra conversa.") from exc
