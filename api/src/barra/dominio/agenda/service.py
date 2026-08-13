"""Orquestracao de agenda: reserva previa de slot por atendimento (04 §3.1 branch 13).

`criar_bloqueio_previo` roda SEMPRE na transacao do chamador (a tool de escrita ja abre
uma via `_executar_idempotente`): snapshot + transicao + bloqueio precisam ser atomicos,
porque o advisory lock + a EXCLUDE de `bloqueios` nao toleram janela entre commit e lock.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

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


def antecedencia_min_por_tipo(tipo_atendimento: str | None) -> int:
    """Piso de antecedencia (ADR 0025 + emenda 2026-06-26) para um tipo de atendimento, em minutos.

    FONTE UNICA da regua, por decisao da prova r3 (`diagnostico_externo_a.md`, Q2). A mesma conta
    vivia em DOIS sitios — o gate de `criar_bloqueio_previo` (abaixo) e o `<horario_minimo>` que o
    `prepare_context` publica no prompt — cada um lendo o `tipo_atendimento` de uma EPOCA diferente
    do turno. Com `interno` no snapshot do inicio do turno o prompt anunciava 21:00 como piso; com
    `externo` extraido no MESMO turno a reserva exigia 21:11 e recusava a hora que a propria IA
    tinha acabado de ofertar (`AntecedenciaInsuficiente`), matando o turno.

    A regua de NEGOCIO nao muda: sem deslocamento da modelo (interno/remoto) ela recebe agora como
    o humano (`agenda_antecedencia_sem_deslocamento_min`, ~0); externo-Uber e tipo AINDA NAO
    definido (None) pagam o `agenda_buffer_min` — o conservador, porque so ele sobrevive a um flip
    de tipo. Muda so quem consulta: os dois lados chamam esta funcao.
    """
    s = get_settings()
    return (
        s.agenda_antecedencia_sem_deslocamento_min
        if tipo_atendimento in ("interno", "remoto")
        else s.agenda_buffer_min
    )


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


async def criar_bloqueio_previo(
    conn: AsyncConnection[Any],
    *,
    atendimento: dict[str, Any],
    agora: datetime | None = None,
) -> None:
    """Reserva o slot previo do atendimento (estado `bloqueado`, origem `ia`) e fecha a FK circular.

    inicio = (data_desejada ou hoje BRT) + horario_desejado; fim = inicio + (duracao_horas ou
    DURACAO_PADRAO_HORAS). Buffer de preparo/intervalo (ADR 0025 + emenda 2026-06-26) e regra DURA:
    antecedencia minima por DESLOCAMENTO (sem deslocamento da modelo -> `agenda_antecedencia_sem_
    deslocamento_min`, ~0; externo-Uber -> `agenda_buffer_min`; inicio < now + antecedencia ->
    `AntecedenciaInsuficiente`) e gap entre atendimentos (vizinho ativo dentro de `agenda_buffer_min`
    -> `ConflitoAgenda`, todos os tipos). Serializa o booking por modelo
    com `pg_advisory_xact_lock` (mesmo padrao do trigger gen_numero_curto, 0001_schema_inicial.sql:193);
    a EXCLUDE `bloqueios_sem_sobreposicao` (0001:515) e o backstop de sobreposicao real. Cada erro
    recuperavel reverte o turno e a tool reoferta (ConflitoAgenda) ou ancora no horario_minimo
    (AntecedenciaInsuficiente).
    """
    modelo_id = atendimento["modelo_id"]
    # Um unico `agora` p/ todo o booking: o default de data, o roll cross-midnight e o guard de
    # antecedencia leem o mesmo instante (sem o risco de `.date()` e o roll caírem em lados
    # opostos da meia-noite por dois now() distintos). `agora` injetado (harness fiel/replay, clock
    # injection — casa com ContextAgente.agora_utc) torna o booking deterministico; None (prod) le o
    # relogio real. Normalizado p/ BRT — a aritmetica de data/sessao abaixo assume BRT.
    agora = datetime.now(BRT) if agora is None else agora.astimezone(BRT)
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

    # Antecedencia minima (ADR 0025 + emenda 2026-06-26): a IA nunca reserva dentro da antecedencia
    # a partir de agora. Casa com o <horario_minimo> do contexto (arredonda_acima(now + antecedencia));
    # aqui o teto e cru, pois qualquer inicio >= horario_minimo ja o satisfaz. Por DESLOCAMENTO: quem
    # NAO se desloca (interno, remoto) recebe agora como o humano (antecedencia ~0); o
    # externo-Uber (modelo se desloca + Pix) mantem o piso = agenda_buffer_min.
    # O gap entre atendimentos (existe_vizinho_no_buffer, abaixo) segue agenda_buffer_min p/ todos.
    s = get_settings()
    buffer = s.agenda_buffer_min
    # FONTE UNICA com o `<horario_minimo>` do prompt (`antecedencia_min_por_tipo`, acima): sao a
    # MESMA regua, e as duas copias divergiam pelo tipo de epocas diferentes do turno (prova r3).
    antecedencia = antecedencia_min_por_tipo(atendimento.get("tipo_atendimento"))
    if inicio < agora + timedelta(minutes=antecedencia):
        raise AntecedenciaInsuficiente(
            "Inicio dentro da antecedencia minima a partir de agora (now + antecedencia)."
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


async def realocar_bloqueio_previo(
    conn: AsyncConnection[Any],
    *,
    atendimento: dict[str, Any],
    agora: datetime | None = None,
) -> None:
    """Move a reserva previa para o horario JA gravado no snapshot: cancela a antiga e recria.

    Existe para um caso so, e estreito (ver `_reagendamento_pos_bloqueio`): o slot reservado veio de
    um PALPITE (o fallback de tempo imediato, ou a hora que a IA ofereceu e ele nao respondeu) e o
    cliente acabou de cravar a hora dele. Nao e reagendamento — e o primeiro agendamento de fato.

    `cancelado` (e nao DELETE) porque a EXCLUDE `bloqueios_sem_sobreposicao` so conta os estados
    ATIVOS: o slot velho e liberado e o historico do painel preserva o rastro. A recriacao passa por
    `criar_bloqueio_previo` inteiro de proposito — disponibilidade, antecedencia, gap e EXCLUDE
    valem para a hora nova como valeriam para qualquer outra. Se alguma barrar, a excecao propaga
    (recuperavel): a transacao do turno reverte, o bloqueio antigo continua de pe e a IA reoferta.
    """
    await liberar_bloqueio_previo(conn, atendimento_id=atendimento["id"])
    await criar_bloqueio_previo(conn, atendimento=atendimento, agora=agora)


async def liberar_bloqueio_previo(
    conn: AsyncConnection[Any],
    *,
    atendimento_id: UUID | str,
) -> None:
    """Solta a reserva previa e devolve o slot para a agenda — sem recriar nada.

    Metade "cancela" da `realocar_bloqueio_previo` (que e liberar + criar), exposta sozinha para a
    REMARCACAO ABERTA: o cliente desmarca sem dizer quando remarca ("hoje nao consigo mais, marco
    outro dia") e o horario sai do snapshot pelo `limpar`. Zerar o snapshot deixando o bloqueio de
    pe seria o bloqueio ORFAO travando a agenda da modelo com um encontro que ninguem tem — o medo
    que ate 12/08 fazia essa fala escalar e pausar a IA no turno do fechamento
    (`_reagendamento_pos_bloqueio`, prova r3 do loop de massa).

    `cancelado` (e nao DELETE) pelo mesmo motivo da realocacao: a EXCLUDE
    `bloqueios_sem_sobreposicao` so conta os estados ATIVOS, entao o slot fica livre na hora e o
    historico do painel preserva o rastro. Idempotente: sem bloqueio ativo, os dois UPDATEs nao
    acham linha e a chamada e no-op."""
    await conn.execute(
        "UPDATE barravips.bloqueios SET estado = 'cancelado', updated_at = now() "
        "WHERE id = (SELECT bloqueio_id FROM barravips.atendimentos WHERE id = %s) "
        "AND estado = 'bloqueado'",
        (atendimento_id,),
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = NULL WHERE id = %s",
        (atendimento_id,),
    )
