"""Loop e2e: o agente conduz uma conversa multi-turn contra um cliente simulado.

Roda pelo CAMINHO FIEL (`evals.harness_fiel.rodar_turno_auditado`): cada turno passa por
`processar_turno` (lock, gate de pausa, drain/coalescing, refusal) e `enviar_turno` (output-guard
final, chunking, gravacao da bolha da IA) — o mesmo encanamento do WhatsApp. O seed continua vindo
de `evals.harness` (DB real; ROLLBACK e do caller). A cada iteracao: insere a msg do cliente, roda
UM turno, le o estado pos-turno e deixa o cliente reagir ao texto da IA. O grafo nao tem
checkpointer (P0): cada turno re-le a janela de `barravips.mensagens`, entao chamar o grafo varias
vezes na MESMA conn "lembra" os turnos.

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

from evals.harness import Cenario, ResultadoTurno, seedar
from evals.harness_fiel import rodar_turno_auditado

from .cliente import ClienteSimulado
from .perfil import ESTADOS_CONDUZIDOS, PerfilCaso, perfil_para_fixture


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
) -> ResultadoE2E:
    """Conduz o caso `perfil` ate um desfecho de conducao. ROLLBACK e responsabilidade do caller.

    `cen` externo pula o seed efemero (a corrida persistente passa o caso da modelo sandbox).
    `pos_turno` roda apos cada turno (na corrida persistente, so o COMMIT — a bolha da IA ja foi
    gravada pelo `enviar_turno`). O trace Langfuse e o do coordenador (prod), com `trace_id`
    deterministico por turno; nao ha o que escopar por fora.
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
        # A bolha da IA e gravada em `mensagens` pelo proprio `enviar_turno` (caminho fiel), na
        # MESMA transacao efemera — junto com o backstop de carimbo da cotacao (ADR 0022). O patch
        # que o runner aplicava aqui (`gravar_resposta_ia`) virou DUPLICACAO: manter os dois
        # inseria a mesma fala duas vezes na janela do turno seguinte.
        r = await rodar_turno_auditado(conn, cen, turno_cliente, graph=graph)
        res.turnos.append(r)
        res.trajetoria.append(r.estado_final)
        if pos_turno is not None:
            await pos_turno(conn, cen, r)

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
