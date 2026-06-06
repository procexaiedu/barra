"""Saida de escala compartilhada pelas defesas do agente.

`intercept_disclosure` (jailbreak/disclosure/reincidencia) e `output_guard` (vazamento/AUP na
saida) abrem o MESMO handoff: comportamento atipico p/ Fernando, `ia_pausada=true`, autor=sistema,
e contabilizam `AGENTE_ESCALADA` no bucket `defesa`. Contrato unico aqui — a tool `escalar`
(ferramentas/escalada.py) NAO passa por aqui: ela deriva tipo/responsavel via `mapear_motivo`,
roda no executor idempotente e devolve o `escalada_id`.
"""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.metrics import AGENTE_ESCALADA
from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import abrir_handoff, mapear_bucket

ACAO_ASSUMIR = "Assumir a conversa com o cliente."


async def escalar_defesa(
    conn: AsyncConnection[Any],
    atendimento_id: str,
    *,
    resumo: str,
    observacao: str,
    metric_key: str | None = None,
) -> None:
    """Abre handoff p/ Fernando (ia_pausada=true) e conta a escalada no bucket `defesa`.

    `observacao` e o motivo persistido (granular: `output_leak_cross_modelo`, `jailbreak_attempt`).
    `metric_key` e o rotulo da metrica e cai em `observacao` quando nao informado — o output_guard
    usa um rotulo mais grosso (`output_leak`/`aup_saida`) que a observacao granular.
    """
    await abrir_handoff(
        conn,
        atendimento_id=UUID(atendimento_id),
        responsavel="Fernando",
        tipo=TipoEscalada.comportamento_atipico,
        resumo_operacional=resumo,
        acao_esperada=ACAO_ASSUMIR,
        origem="agente",
        autor="sistema",
        observacao=observacao,
    )
    chave = metric_key or observacao
    AGENTE_ESCALADA.labels(mapear_bucket(chave), chave).inc()
