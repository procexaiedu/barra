"""Replay contra o banco: reconstrucao da entrada e trajetoria de estados.

Duas coisas, ambas com o Postgres real:

1. **Reconstrucao da entrada** (`reconstruir_turnos`) — dado um Atendimento, devolve para cada
   turno a tripla que o extrator leu: conversa ate o instante, snapshot no instante e `agora`. O
   snapshot vem de aplicar EM ORDEM os payloads das extracoes registradas em `eventos`, nunca do
   estado atual do Atendimento (esse e o resultado final e nao reproduz turno intermediario). Os
   turnos DECISIVOS — aqueles em que um campo aparece ou muda — sao os que valem rotulagem.

2. **Trajetoria** (`rodar_trajetoria`) — roda o extrator turno a turno sobre um Atendimento
   SEMEADO e aplica cada payload pelo dominio de verdade (`registrar_extracao_ia`), colhendo a
   sequencia de estados. E o nivel de impacto: nao ha copia da FSM aqui, a maquina de estados e a
   de producao.

Fidelidade e limite: a entrada so fica plenamente fiel depois da janela dedicada da extracao. O
que a conversa e o snapshot reconstroem e o que o extrator le HOJE; a agenda/bloqueios/janelas
livres do instante nao sao reconstruiveis (mudaram desde entao) — e por isso nao entram na janela
dedicada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

# `_JANELA_MENSAGENS`: a mesma janela deslizante do prepare_context — a conversa reconstruida e a
# que o turno viu, nao a thread inteira.
from barra.agente.nos.prepare_context import _JANELA_MENSAGENS
from barra.dominio.agenda.service import (
    AntecedenciaInsuficiente,
    ConflitoAgenda,
    ForaDisponibilidade,
    HorarioNaoDefinido,
)
from barra.dominio.atendimentos.service import (
    CotacaoAusente,
    ParPrecoDuracaoInvalido,
    registrar_extracao_ia,
)
from evals.harness import seedar

from .extrator import Extrator, Variante, normalizar_payload
from .golden import Fala, ItemGolden, TrajetoriaGolden
from .janela import aplicar_payload, detectores_do_turno, montar_janela
from .metricas import ResultadoTrajetoria

# Erros RECUPERAVEIS do dominio: em prod viram ToolMessage de erro e o turno segue sem gravar.
# No replay significam a mesma coisa — a transacao reverteu, o estado nao mudou.
_ERROS_RECUPERAVEIS = (
    ConflitoAgenda,
    ForaDisponibilidade,
    AntecedenciaInsuficiente,
    HorarioNaoDefinido,
    ParPrecoDuracaoInvalido,
    CotacaoAusente,
)


@dataclass(frozen=True)
class TurnoReconstruido:
    """Um turno de extracao do Atendimento, com a entrada que o extrator leu."""

    ordem: int
    agora: datetime
    conversa: list[Fala]
    registrado: dict[str, Any]
    gravado: dict[str, Any]
    decisivo: bool


async def reconstruir_turnos(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: str | UUID
) -> list[TurnoReconstruido]:
    """Reconstroi a entrada de cada turno de extracao do Atendimento, em ordem."""
    res = await conn.execute(
        "SELECT cliente_id, modelo_id FROM barravips.atendimentos WHERE id = %s",
        (str(atendimento_id),),
    )
    alvo = await res.fetchone()
    if alvo is None:
        return []

    res = await conn.execute(
        """
        SELECT m.direcao::text AS direcao, m.conteudo, m.created_at
          FROM barravips.mensagens m
          JOIN barravips.conversas c ON c.id = m.conversa_id
         WHERE c.cliente_id = %s AND c.modelo_id = %s
         ORDER BY m.created_at, m.id
        """,
        (alvo["cliente_id"], alvo["modelo_id"]),
    )
    mensagens = await res.fetchall()

    res = await conn.execute(
        """
        SELECT payload, created_at FROM barravips.eventos
         WHERE atendimento_id = %s AND tipo = 'extracao_registrada'
         ORDER BY created_at, id
        """,
        (str(atendimento_id),),
    )
    extracoes = await res.fetchall()

    turnos: list[TurnoReconstruido] = []
    snapshot: dict[str, Any] = {}
    for ordem, extracao in enumerate(extracoes, start=1):
        agora = extracao["created_at"]
        # A janela do turno e a que existia ANTES da fala da IA daquele turno: o `enviar_turno`
        # persiste a resposta depois de o evento ser gravado, entao o corte por `created_at` a
        # deixa de fora naturalmente.
        conversa = [
            Fala(
                de="cliente" if linha["direcao"] == "cliente" else "ia",
                texto=linha["conteudo"] or "",
            )
            for linha in mensagens
            if linha["created_at"] <= agora
        ][-_JANELA_MENSAGENS:]
        payload = dict(extracao["payload"] or {})
        item = ItemGolden(
            id=f"t{ordem}",
            atendimento=0,
            descricao="",
            agora=agora,
            conversa=conversa,
            registrado=snapshot,
            gravado=payload,
            rotulo={},
        )
        evidenciado, recuo = detectores_do_turno(item)
        depois = aplicar_payload(snapshot, payload, horario_evidenciado=evidenciado, recuo=recuo)
        turnos.append(
            TurnoReconstruido(
                ordem=ordem,
                agora=agora,
                conversa=conversa,
                registrado=snapshot,
                gravado=payload,
                decisivo=depois != snapshot,
            )
        )
        snapshot = depois
    return turnos


async def rodar_trajetoria(
    conn: AsyncConnection[dict[str, Any]],
    trajetoria: TrajetoriaGolden,
    extrator: Extrator,
    *,
    variante: Variante,
) -> ResultadoTrajetoria:
    """Roda o extrator turno a turno sobre um Atendimento semeado e colhe a sequencia de estados.

    Cada payload passa pelo dominio (`registrar_extracao_ia`) com o relogio do turno injetado
    (`agora`) e os detectores deterministicos do turno — o mesmo contrato do no `extrair`. Erro
    recuperavel do dominio nao interrompe o replay: a transacao daquele turno reverte e o estado
    segue o que era, como em prod. A `conn` e a mesma do seed (ROLLBACK e do caller).
    """
    cenario = await seedar(conn, {"cenario": trajetoria.cenario, "historico": []})
    estados: list[str] = []
    for turno in trajetoria.turnos:
        janela = montar_janela(turno, bloco_estado=variante.bloco_estado)
        payload = normalizar_payload(await extrator(turno, janela))
        evidenciado, recuo = detectores_do_turno(turno)
        try:
            # Savepoint por turno: sem ele um erro recuperavel aborta a transacao inteira do seed.
            async with conn.transaction():
                await registrar_extracao_ia(
                    conn,
                    str(cenario.atendimento_id),
                    payload,
                    agora=turno.agora,
                    horario_evidenciado=evidenciado,
                    recuo_detectado=recuo,
                    # Guarda do valor fantasma: o cenario e semeado SEM historico em `mensagens`,
                    # entao o dominio nao enxergaria nenhuma fala da IA e descartaria todo valor
                    # fora da tabela (o degrau legitimo da escada, inclusive). As falas da IA da
                    # trajetoria fazem o papel do historico persistido que prod tem.
                    fala_da_ia_no_turno="\n\n".join(
                        f.texto for f in turno.conversa if f.de == "ia"
                    ),
                )
        except _ERROS_RECUPERAVEIS:
            pass
        res = await conn.execute(
            "SELECT estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
            (cenario.atendimento_id,),
        )
        linha = await res.fetchone()
        estados.append(str(linha["estado"]) if linha else "?")
    return ResultadoTrajetoria(
        id=trajetoria.id, prevista=estados, rotulada=list(trajetoria.estados)
    )
