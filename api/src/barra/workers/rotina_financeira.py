"""Cron da rotina diaria da manha do Agente financeiro (spec 0005, ticket 10).

Uma vez por dia, na janela da manha, o worker visita cada Grupo financeiro ativo e deixa o modulo
decidir o que dizer ali (`agente_financeiro.rotina`). O worker nao tem regra de negocio nenhuma:
ele e o relogio, a lista e a rede — quem decide se fala, o que fala e se ja falou hoje e o
modulo, com as mesmas leituras da porta unica.

Padrao dos workers de relogio da casa (`lembrete_valor`, `digest_semanal`): flag de kill-switch,
`agora` injetavel, best-effort por alvo (falha de um grupo nao aborta o lote) e contagem do que
foi feito no retorno.

Divisao de responsabilidade com o modulo: **a HORA e da agenda** (o cron roda 11:00 UTC = 08:00
BRT, a janela da manha do grupo), **o "uma vez por dia" e do banco** (a chave de idempotencia que
o modulo grava no log de origem). Nao ha guarda de horario no codigo de proposito: um segundo
disparo em qualquer hora do mesmo dia vira `ja_falou` sozinho, e uma chamada manual fora da manha
(um replay, uma investigacao) tem que poder acontecer sem o modulo fingir que nao e dia.

**A instancia e a da ProceX, nunca a da modelo.** O Agente financeiro fala pelo numero proprio da
ProceX (o mesmo do myEYE) em todos os grupos. Ela vem de `settings.grupo_financeiro_instancia`, e
VAZIA significa rotina desligada: mandar pela instancia de uma modelo faria a cobranca chegar ao
grupo assinada por outra pessoa. O webhook usa a MESMA variavel pelo mesmo motivo — a instancia
que entregou o evento NAO serve, porque a modelo esta no grupo e o WhatsApp dela e outra instancia
apontando para o mesmo webhook (`webhook/routes._e_a_instancia_da_procex`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

from barra.agente_financeiro.porta import EnviarNoGrupo
from barra.agente_financeiro.rotina import cobrar_pendencias_do_grupo, grupos_da_rotina
from barra.core.evolution import EvolutionClient
from barra.core.metrics import GRUPO_FINANCEIRO_ROTINA
from barra.dominio.grupo_financeiro.modelos import GrupoFinanceiro
from barra.settings import Settings

logger = logging.getLogger(__name__)


async def cobrar_pendencias_da_manha(
    conn: AsyncConnection[Any],
    evolution: EvolutionClient,
    settings: Settings,
    *,
    agora: datetime | None = None,
) -> int:
    """Roda a rotina em todos os Grupos financeiros ativos. Devolve quantos foram cobrados.

    Grupo que ficou em silencio (nada pendente, nada movimentado) e grupo que ja tinha sido
    cobrado hoje NAO contam: o retorno e "quantas mensagens sairam", que e o numero que se olha
    quando se pergunta se a rotina esta viva.
    """
    # A rotina da manhã EXISTE para falar (cobra pendência e posta o saldo). No modo só
    # escuta ela não tem uma versão muda que faça sentido: rodá-la sem boca gastaria as
    # leituras e ainda queimaria a reserva do dia do grupo (`reservar_fala_da_rotina`),
    # que existe para não cobrar duas vezes — e aí a cobrança de verdade, no dia em que a
    # boca ligar, encontraria o dia já gasto e ficaria calada.
    if not settings.grupo_financeiro_responde:
        return 0
    if not settings.grupo_financeiro_rotina_ativa or not settings.grupo_financeiro_instancia:
        return 0

    momento = agora or datetime.now(UTC)
    cobrados = 0
    for grupo in await grupos_da_rotina(conn):
        try:
            resultado = await cobrar_pendencias_do_grupo(
                conn,
                grupo,
                agora=momento,
                enviar=_falar_no_grupo(evolution, settings, grupo),
            )
        except Exception:
            # Evolution fora, grupo que sumiu do WhatsApp, timeout. O dia deste grupo ja esta
            # reservado (ver `reservar_fala_da_rotina`): ele fica calado hoje e a pendencia volta
            # amanha. O que nao pode acontecer e um grupo derrubar a cobranca dos outros.
            GRUPO_FINANCEIRO_ROTINA.labels("falha").inc()
            logger.exception("grupo_financeiro_rotina_falha grupo_id=%s", grupo.id)
            continue
        if resultado.status == "cobrou":
            cobrados += 1
    return cobrados


def _falar_no_grupo(
    evolution: EvolutionClient, settings: Settings, grupo: GrupoFinanceiro
) -> EnviarNoGrupo:
    """Entregador da fala da rotina — o gemeo de `_falar_no_grupo_financeiro` do webhook.

    `enviar_texto_avulso` pelo mesmo motivo de la: `envios_evolution` so aceita
    `conversa_cliente`/`grupo_coordenacao` como contexto, e o Grupo financeiro nao e nenhum dos
    dois. Sem quote: a cobranca da manha nao responde mensagem nenhuma — ela abre o dia, e por
    isso o `citar` que a porta oferece e ignorado aqui (a rotina nunca o preenche).
    """

    async def enviar(texto: str, *, citar: str | None = None) -> None:
        await evolution.enviar_texto_avulso(
            instance_id=settings.grupo_financeiro_instancia,
            remote_jid=grupo.jid,
            texto=texto,
            quoted_message_id=citar,
        )

    return enviar
