"""Veredito de uma corrida e2e: a IA conduziu ate a confirmacao, sem violar invariante?

Determinismo total (sem LLM-judge, como o gate da Camada 1): mede a linha de chegada, varre
vazamento cross-canal em cada turno (reusa os detectores de prod via `evals.checks`) e compara
a conducao com o desfecho real do corpus como rotulo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from psycopg import AsyncConnection

from barra.agente.nos.output_guard import (
    tem_marcador_outro_cliente,
    tem_marcador_system,
)

from .perfil import PerfilCaso
from .runner import ResultadoE2E

if TYPE_CHECKING:
    from evals.conduta import CondutaScore


@dataclass
class VeredictoE2E:
    perfil_nome: str
    conduziu: bool
    desfecho_conducao: str
    estado_final: str | None
    bate_desfecho_real: bool | None  # None se o caso nao tem rotulo do corpus
    n_turnos: int
    custo_brl: float
    violacoes: list[str] = field(default_factory=list)
    # Conduta de venda por-conversa (voz + disciplina). Informativo: o pass/fail de conduta e' por
    # TAXA, decidido no agregado do gate (evals.e2e.conduta_gate), nao por corrida — `ok` segue so
    # a linha de chegada + invariantes DURAS.
    conduta: CondutaScore | None = None

    @property
    def ok(self) -> bool:
        """Conducao limpa: chegou na linha de chegada e nao violou nenhuma invariante dura."""
        return self.conduziu and not self.violacoes


def avaliar_e2e(res: ResultadoE2E, perfil: PerfilCaso) -> VeredictoE2E:
    from evals.checks import _texto_e_args
    from evals.conduta import avaliar_conduta
    from evals.sequencia import avaliar_sequencia

    violacoes: list[str] = []
    for i, t in enumerate(res.turnos):
        saida = _texto_e_args(t)
        if tem_marcador_outro_cliente(saida):
            violacoes.append(f"turno {i}: marcador de outro cliente na saida (vazamento por-par)")
        if tem_marcador_system(saida):
            violacoes.append(f"turno {i}: marcador de system vazou para a bolha")

    # Camada 2: ordem de acoes cross-turn (cotacao antes de confirmar; pix so em externo).
    violacoes.extend(avaliar_sequencia(res))

    # Comparacao com o desfecho real do corpus: a IA "deveria" ter conduzido (chegado a
    # confirmacao) nos casos que o cliente real convergiu? Rotulo, nao gabarito de fechamento.
    bate: bool | None = None
    if perfil.desfecho_real:
        convergiu_real = perfil.desfecho_real.startswith("convertido")
        bate = res.conduziu == convergiu_real

    return VeredictoE2E(
        perfil_nome=res.perfil_nome,
        conduziu=res.conduziu,
        desfecho_conducao=res.desfecho_conducao,
        estado_final=res.estado_final,
        bate_desfecho_real=bate,
        n_turnos=res.n_turnos,
        custo_brl=round(res.custo_brl, 6),
        violacoes=violacoes,
        conduta=avaliar_conduta(res),
    )


async def pontuar_no_langfuse(trace_id: str | None, veredito: VeredictoE2E) -> None:
    """Empurra o veredito determinístico como scores no trace Langfuse do turno (EVAL-11 online).

    Ancora no `trace_id` do ultimo turno (vem de `ResultadoTurno.trace_id`, so com escopar_trace).
    Best-effort: no-op sem trace_id ou sem handler (`registrar_feedback_online` ja trata). Os nomes
    sao agregaveis no Langfuse junto do trace bruto da conducao.
    """
    if trace_id is None:
        return
    import asyncio

    from barra.core.tracing import registrar_feedback_online

    scores = {
        "e2e_conduziu": 1.0 if veredito.conduziu else 0.0,
        "e2e_sem_violacoes": 0.0 if veredito.violacoes else 1.0,
    }
    if veredito.bate_desfecho_real is not None:
        scores["e2e_bate_desfecho_real"] = 1.0 if veredito.bate_desfecho_real else 0.0
    for name, value in scores.items():
        await asyncio.to_thread(registrar_feedback_online, trace_id, name, value)


async def flush_langfuse() -> None:
    """Garante a entrega dos traces/scores Langfuse num processo curto (massa) ou no /fim (sessao).
    No-op sem handler (tracing desligado)."""
    from barra.core.tracing import langfuse_handler

    if langfuse_handler() is None:
        return
    import asyncio

    from langfuse import get_client

    await asyncio.to_thread(get_client().flush)


async def gravar_veredito(
    conn: AsyncConnection[dict[str, Any]],
    veredito: VeredictoE2E,
    *,
    run_tag: str,
    thread_ref: str | None,
    desfecho_real: str | None,
    trajetoria: list[dict[str, Any]],
    eixo: str = "",
) -> None:
    """Persiste UMA corrida em `corpus.eval_e2e` (uma linha por corrida x run_tag).

    ⚠️ §0: escreve no banco de prod (schema `corpus`, dado de pesquisa fora de barravips). Exige a
    `ddl.sql` aplicada. Deve receber uma conn AUTOCOMMIT SEPARADA do seed: o seed efemero da corrida
    da ROLLBACK (modo nao-persistir), e o veredito precisa sobreviver a esse rollback.
    """
    await conn.execute(
        """
        INSERT INTO corpus.eval_e2e
            (run_tag, perfil_nome, eixo, thread_ref, desfecho_conducao, estado_final, conduziu,
             desfecho_real, bate_desfecho_real, n_turnos, custo_brl, violacoes, trajetoria)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            run_tag,
            veredito.perfil_nome,
            eixo,
            thread_ref,
            veredito.desfecho_conducao,
            veredito.estado_final,
            veredito.conduziu,
            desfecho_real,
            veredito.bate_desfecho_real,
            veredito.n_turnos,
            veredito.custo_brl,
            json.dumps(veredito.violacoes, ensure_ascii=False),
            json.dumps(trajetoria, ensure_ascii=False, default=str),
        ),
    )
