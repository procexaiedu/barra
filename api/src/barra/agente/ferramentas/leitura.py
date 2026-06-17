"""Tools de leitura do agente. P0 tem só consultar_agenda (04 §2.1, §2.2)."""

from datetime import date

from langchain_core.tools import ToolException, tool
from langgraph.prebuilt import ToolRuntime

from barra.core.metrics import AGENTE_TOOL_ERRO_RECUPERAVEL

from ..contexto import ContextAgente

# AGT-07: teto de itens no retorno da agenda. A janela ja e capada por 14 dias, mas um periodo
# denso poderia devolver dezenas de bloqueios e inflar o contexto/tokens do turno.
_MAX_BLOQUEIOS = 50


@tool
async def consultar_agenda(
    data_inicio: date,
    data_fim: date,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Consulta os bloqueios (horários OCUPADOS) da modelo entre data_inicio e data_fim.

    As próximas 48h já estão no seu contexto; responda direto sobre elas SEM esta tool. Use-a
    APENAS quando o cliente perguntar por um dia além das próximas 48h (ex.: "tem horário sábado
    que vem?").

    Args:
        data_inicio: data inicial inclusiva, formato YYYY-MM-DD. Comece a partir do dia
          consultado (além das próximas 48h), não a partir de hoje.
        data_fim: data final inclusiva, formato YYYY-MM-DD. Máximo 14 dias após data_inicio.

    Returns:
        Uma linha por horário OCUPADO (dia e hora), ou a frase de que não há horário
        ocupado no período — o que não aparece está livre. Se o horário que o cliente pediu
        cair num bloqueio, siga sua conduta de indisponibilidade (nas suas regras).
    """
    # `format: "date"` no schema (params tipados `date`): o parse/validacao do YYYY-MM-DD roda na
    # camada de args (data invalida vira ToolMessage de erro do ToolNode, com o detalhe pydantic).
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    di, df = data_inicio, data_fim
    if (df - di).days > 14:
        AGENTE_TOOL_ERRO_RECUPERAVEL.labels("consultar_agenda", "janela_excedida").inc()
        raise ToolException("ERRO: janela máxima é 14 dias. Refine sua consulta.")

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT inicio, fim
              FROM barravips.bloqueios
             WHERE modelo_id = %s
               AND estado IN ('bloqueado', 'em_atendimento')
               AND inicio::date BETWEEN %s AND %s
             ORDER BY inicio
             LIMIT %s
            """,
            (modelo_id, di, df, _MAX_BLOQUEIOS + 1),
        )
        rows = await res.fetchall()
    if not rows:
        return f"Sem bloqueios entre {di} e {df}. Nenhum horário ocupado nesse período."
    # AGT-07: corta no teto e sinaliza o truncamento (pega 1 a mais p/ detectar sem COUNT).
    truncado = len(rows) > _MAX_BLOQUEIOS
    linhas = [
        f"- {r['inicio']:%a %d/%m %H:%M} - {r['fim']:%H:%M} (ocupado)"
        for r in rows[:_MAX_BLOQUEIOS]
    ]
    texto = "Bloqueios:\n" + "\n".join(linhas)
    if truncado:
        texto += (
            f"\n(Mostrando os primeiros {_MAX_BLOQUEIOS} horários ocupados; há mais nesse "
            "período — consulte um intervalo menor para ver o resto.)"
        )
    return texto
