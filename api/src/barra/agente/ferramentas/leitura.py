"""Tools de leitura do agente. P0 tem só consultar_agenda (04 §2.1, §2.2)."""

from datetime import date

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from ..contexto import ContextAgente


@tool
async def consultar_agenda(
    data_inicio: str,
    data_fim: str,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Consulta os bloqueios (horários OCUPADOS) da modelo entre data_inicio e data_fim.

    As próximas 48h já estão no contexto do turno (BP4, 02 §5) — use esta tool
    APENAS para janelas além disso (ex.: "tem horário sábado que vem?").

    Args:
        data_inicio: data inicial inclusiva, formato YYYY-MM-DD.
        data_fim: data final inclusiva, formato YYYY-MM-DD. Máximo 14 dias após data_inicio.

    Returns:
        Markdown com os bloqueios ativos no período (o que NÃO está listado está livre).
    """
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    di = date.fromisoformat(data_inicio)
    df = date.fromisoformat(data_fim)
    if (df - di).days > 14:
        return "ERRO: janela máxima é 14 dias. Refine sua consulta."

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT inicio, fim, estado
              FROM barravips.bloqueios
             WHERE modelo_id = %s
               AND estado IN ('bloqueado', 'em_atendimento')
               AND inicio::date BETWEEN %s AND %s
             ORDER BY inicio
            """,
            (modelo_id, di, df),
        )
        rows = await res.fetchall()
    if not rows:
        return f"Sem bloqueios entre {di} e {df}. Disponibilidade total."
    linhas = [f"- {r['inicio']:%a %d/%m %H:%M} - {r['fim']:%H:%M} ({r['estado']})" for r in rows]
    return "Bloqueios:\n" + "\n".join(linhas)
