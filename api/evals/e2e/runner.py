"""Loop e2e: o agente conduz uma conversa multi-turn contra um cliente simulado.

Reusa `evals.harness` (seed no DB real + `ainvoke` por turno; ROLLBACK e do caller). A cada
iteracao: insere a msg do cliente, roda UM turno do grafo, le o estado pos-turno e deixa o
cliente reagir ao texto da IA. O grafo nao tem checkpointer (P0): cada turno re-le a janela de
`barravips.mensagens`, entao chamar o grafo varias vezes na MESMA conn "lembra" os turnos.

Para quando: (a) atinge a linha de chegada (`Aguardando_confirmacao`/`Confirmado`); (b) a IA
pausa (handoff/escala — `ia_pausada`); (c) o cliente encerra (sumiu/combinou); (d) estoura
`max_turnos`.

⚠️ §0: com o graph REAL isto gasta credito (1 ainvoke/turno) e exige TEST_DATABASE_URL. A
validacao offline injeta um chat FAKE no graph + ClienteRoteirizado — ver tests/agente/
test_e2e_conducao.py.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection

from evals.harness import Cenario, ResultadoTurno, rodar_turno, seedar

from .cliente import ClienteSimulado
from .perfil import ESTADOS_CONDUZIDOS, PerfilCaso, perfil_para_fixture
from .persistencia import gravar_resposta_ia


@dataclass
class ResultadoE2E:
    """O que uma corrida e2e produziu — insumo de `avaliacao.avaliar_e2e`."""

    perfil_nome: str
    trajetoria: list[dict[str, Any]]  # estado_final {estado, pix_status, ia_pausada} por turno
    turnos: list[ResultadoTurno] = field(default_factory=list)  # resultado bruto (auditoria)
    turnos_cliente: list[str] = field(default_factory=list)  # fala do cliente que gerou turnos[i]
    desfecho_conducao: str = "max_turnos"  # conduziu | pausou_handoff | cliente_sumiu | max_turnos
    estado_final: str | None = None
    desfecho_real: str | None = None  # rotulo do corpus (comparacao)
    cenario: Cenario | None = (
        None  # cenario seedado (atendimento_id p/ pos-eventos, ex.: foto portaria)
    )

    @property
    def n_turnos(self) -> int:
        return len(self.turnos)

    @property
    def custo_brl(self) -> float:
        return sum(t.metricas.custo_brl for t in self.turnos)

    @property
    def conduziu(self) -> bool:
        return self.estado_final in ESTADOS_CONDUZIDOS


def _estado(r: ResultadoTurno) -> str | None:
    return (r.estado_final or {}).get("estado")


def _pausada(r: ResultadoTurno) -> bool:
    return bool((r.estado_final or {}).get("ia_pausada"))


async def rodar_e2e(
    conn: AsyncConnection[dict[str, Any]],
    perfil: PerfilCaso,
    cliente: ClienteSimulado,
    *,
    graph: Any | None = None,
    max_turnos: int = 12,
    cen: Cenario | None = None,
    pos_turno: Callable[[AsyncConnection[dict[str, Any]], Cenario, ResultadoTurno], Awaitable[None]]
    | None = None,
    trace_tag: str = "e2e",
    escopar_trace: bool = False,
) -> ResultadoE2E:
    """Conduz o caso `perfil` ate um desfecho de conducao. ROLLBACK e responsabilidade do caller.

    `cen` externo pula o seed efemero (a corrida persistente passa o caso da modelo sandbox).
    `pos_turno` roda apos cada turno (a persistencia grava a bolha da IA e COMMITA). `trace_tag`/
    `escopar_trace` propagam o trace Langfuse + score ao `rodar_turno`.
    """
    if cen is None:
        cen = await seedar(conn, perfil_para_fixture(perfil))
    res = ResultadoE2E(
        perfil_nome=perfil.nome, trajetoria=[], desfecho_real=perfil.desfecho_real, cenario=cen
    )

    turno_cliente: str | None = perfil.abertura
    for _ in range(max_turnos):
        assert turno_cliente is not None
        res.turnos_cliente.append(turno_cliente)  # paralelo a res.turnos (mesmo indice)
        r = await rodar_turno(
            conn,
            cen,
            turno_cliente=turno_cliente,
            graph=graph,
            trace_tag=trace_tag,
            escopar_trace=escopar_trace,
        )
        res.turnos.append(r)
        res.trajetoria.append(r.estado_final)
        if pos_turno is not None:
            await pos_turno(conn, cen, r)
        else:
            # Janela FIEL: sem o worker de envio (so roda em prod), a bolha da IA nao entra em
            # `mensagens` sozinha -> o proximo turno nao a veria e o agente correria AMNESICO
            # (re-cumprimenta/re-cota a cada turno). Grava na MESMA transacao efemera (ROLLBACK do
            # caller descarta). gravar_resposta_ia pula texto vazio (turno sem fala / pausa).
            await gravar_resposta_ia(conn, cen, r.texto)

        if _estado(r) in ESTADOS_CONDUZIDOS:
            res.desfecho_conducao = "conduziu"
            break
        if _pausada(r):
            res.desfecho_conducao = "pausou_handoff"
            break

        reacao = await cliente.responder(texto_ia=r.texto)
        if reacao.encerrou or not reacao.texto:
            res.desfecho_conducao = "cliente_sumiu"
            break
        turno_cliente = reacao.texto

    res.estado_final = _estado(res.turnos[-1]) if res.turnos else None
    return res
