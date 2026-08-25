"""A rotina diaria da manha do Agente financeiro (spec 0005, ticket 10).

A SEGUNDA porta do modulo — a que nasce de **relogio** em vez de mensagem. A spec ja previa a
excecao: "a rotina diaria de fechamento/cobranca e a excecao natural (nasce de relogio, nao de
mensagem): vive como worker de cron no padrao dos ja existentes, mas o que ela decide/posta reusa
as mesmas funcoes de dominio da porta". E o que este arquivo faz: decide por UM grupo, com as
mesmas leituras e o mesmo motor de Fechamento que `processar_mensagem_do_grupo` usa, e devolve o
que fez. Quem varre a lista de grupos e fala com a rede e o worker (`workers/rotina_financeira`).

Tres coisas que ela deliberadamente NAO faz:

* **Nao resolve pendencia.** A rotina so pergunta. Quem responde entra pela porta unica como
  qualquer mensagem do grupo — "Pix" as 9h da manha e absorvido pelo mesmo caminho que o "Sim" as
  20h de ontem, e e por isso que este arquivo nao tem nenhuma regra de pagamento dentro. Vale
  igual para a **Ficha sem desfecho** (ticket 10): a rotina pergunta "rolou?", e quem promove a
  ficha a Venda registrada e a porta unica quando a resposta chegar (ticket 07). A rotina nunca
  escreve na ficha — nem para marcar que cobrou, porque "ja cobrei esta ficha" e a reserva do dia
  que ela ja grava, e um segundo carimbo seria um segundo estado a reconciliar.
* **Nao inventa um segundo saldo.** O numero que ela posta vem de `fechamento_da_modelo`, a mesma
  funcao do comando "fechamento". Dois caminhos ate o saldo seriam dois jeitos de a conta
  divergir — e o saldo e justamente o unico numero que o gestor confere de cabeca.
* **Nao guarda estado proprio.** "Ja falei hoje?" e a linha `de_mim` que ela mesma gravou no log
  de origem, com `chave_dedup` deterministica (`rotina:<grupo>:<dia BRT>`). Sem tabela de
  execucoes: o que o modulo precisa lembrar da rotina e exatamente o que ela DISSE, e isso ja tem
  lugar — e de quebra e o contexto que faz a resposta do humano achar a venda certa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection

from barra.agente_financeiro.porta import EnviarNoGrupo, fechamento_da_modelo
from barra.core.metrics import GRUPO_FINANCEIRO_ROTINA
from barra.dominio.grupo_financeiro.modelos import GrupoFinanceiro, dia_brt
from barra.dominio.grupo_financeiro.pendencia import Pendencia
from barra.dominio.grupo_financeiro.repo import (
    fichas_abertas_da_modelo,
    grupos_financeiros_ativos,
    movimento_do_grupo,
    reservar_fala_da_rotina,
    vendas_sem_forma_de_pagamento,
)
from barra.dominio.grupo_financeiro.rotina import (
    chave_da_fala_do_dia,
    fichas_sem_desfecho,
    montar_cobranca_da_manha,
)

_logger = logging.getLogger(__name__)

JANELA_DO_MOVIMENTO = timedelta(days=1)
"""O que conta como "o grupo se mexeu". Um dia corrido ate a hora do cron — a mesma janela do
digest diario da casa, e a que faz "ontem" na fala da rotina ser verdade."""

StatusDaRotina = Literal["cobrou", "silencio", "ja_falou"]
"""`silencio` e o desfecho NORMAL (grupo sem pendencia nem movimento); `ja_falou` e o segundo
disparo do mesmo dia batendo na chave — os dois sao sucesso, e nenhum dos dois fala."""


@dataclass(frozen=True)
class ResultadoDaRotina:
    """O que a rotina fez com UM grupo hoje — o observavel do ticket, como `ResultadoDaPorta`."""

    grupo_id: UUID
    modelo_id: UUID
    status: StatusDaRotina
    fala: str | None = None
    mensagem_id: UUID | None = None
    """A linha que a fala deixou no log de origem (a reserva do dia). `None` quando calou."""
    pendencias: tuple[Pendencia, ...] = ()
    """As pendencias vivas da modelo no momento da rotina — o que o painel (11) mostra e o que a
    cobranca acabou de citar. Continuam abertas: cobrar nao resolve nada."""
    fichas: tuple[UUID, ...] = ()
    """As Fichas de agendamento sem desfecho que esta cobranca citou (ticket 10).

    Campo NOVO ao lado dos antigos, nunca no lugar de nenhum. Ele existe porque a ficha e o unico
    item da cobranca que NAO e derivado de uma venda: `pendencias` sao coluna nula de venda, e uma
    ficha aberta nao tem venda nenhuma — sem esta tupla, o que a rotina cobrou nao teria como ser
    observado (nem por um teste, nem pelo worker, nem pelo painel) a nao ser lendo o texto da
    fala. Sao ids das fichas VIVAS que a linha citou; cobrar nao muda o estado de nenhuma."""


async def cobrar_pendencias_do_grupo(
    conn: AsyncConnection[Any],
    grupo: GrupoFinanceiro,
    *,
    agora: datetime,
    enviar: EnviarNoGrupo | None = None,
) -> ResultadoDaRotina:
    """Decide e posta a cobranca consolidada deste grupo hoje. No maximo UMA mensagem.

    `agora` e injetado (nunca `now()` aqui dentro) pelo mesmo motivo dos outros workers de
    relogio da casa: o dia da rotina, a janela do movimento e o "ontem" da fala saem todos dele,
    e um teste que precisa esperar amanhecer nao e um teste.

    Falha de entrega NAO e absorvida: sobe para o worker, que loga e conta a falha por grupo sem
    abortar o lote. A reserva do dia ja esta gravada, entao o grupo fica calado hoje — e a
    pendencia, que e derivada do estado da venda, volta na cobranca de amanha inteira.
    """
    dia = dia_brt(agora)
    extrato = await fechamento_da_modelo(conn, grupo.modelo_id)
    a_cobrar = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)
    movimento = await movimento_do_grupo(conn, grupo.id, desde=agora - JANELA_DO_MOVIMENTO)
    # As fichas abertas sao as DA MODELO, nunca as do grupo (ADR-0046 §2): o card pode ter caido
    # no Grupo de fichas, e ela paga no grupo dela. Mesma leitura que a porta unica ja faz quando
    # a modelo escreve — uma consulta indexada, e o criterio de quais viram cobranca (as que
    # venceram) mora no dominio, nao aqui.
    fichas = await fichas_abertas_da_modelo(conn, grupo.modelo_id)
    sem_desfecho = fichas_sem_desfecho(fichas, hoje=dia)

    fala = montar_cobranca_da_manha(
        extrato=extrato, a_cobrar=a_cobrar, movimento=movimento, hoje=dia, fichas=fichas
    )
    if fala is None:
        # O default do modulo. Grupo sem pendencia acionavel e sem dinheiro na janela nao recebe
        # "bom dia" — o agente mora num grupo habitado e so fala quando tem o que cobrar.
        GRUPO_FINANCEIRO_ROTINA.labels("silencio").inc()
        return ResultadoDaRotina(grupo.id, grupo.modelo_id, "silencio")

    mensagem_id = await reservar_fala_da_rotina(
        conn, grupo.id, chave=chave_da_fala_do_dia(grupo.id, dia), texto=fala, em=agora
    )
    if mensagem_id is None:
        GRUPO_FINANCEIRO_ROTINA.labels("ja_falou").inc()
        _logger.info(
            "grupo_financeiro_rotina_ja_falou grupo_id=%s dia=%s", grupo.id, f"{dia:%Y-%m-%d}"
        )
        return ResultadoDaRotina(grupo.id, grupo.modelo_id, "ja_falou")

    if enviar is not None:
        await enviar(fala)

    GRUPO_FINANCEIRO_ROTINA.labels("cobrou").inc()
    _logger.info(
        "grupo_financeiro_rotina_cobrou grupo_id=%s modelo_id=%s dia=%s pendencias=%d "
        "fichas=%d a_comprovar=%s sem_forma=%s",
        grupo.id,
        grupo.modelo_id,
        f"{dia:%Y-%m-%d}",
        len(extrato.pendencias),
        len(sem_desfecho),
        extrato.a_comprovar,
        extrato.sem_forma,
    )
    return ResultadoDaRotina(
        grupo_id=grupo.id,
        modelo_id=grupo.modelo_id,
        status="cobrou",
        fala=fala,
        mensagem_id=mensagem_id,
        pendencias=extrato.pendencias,
        fichas=tuple(ficha.id for ficha in sem_desfecho),
    )


async def grupos_da_rotina(conn: AsyncConnection[Any]) -> list[GrupoFinanceiro]:
    """Os grupos que a rotina visita. Exposto aqui para o worker nao importar o repo direto."""
    return await grupos_financeiros_ativos(conn)
