"""Tool de escrita `pedir_pix_deslocamento` (04 §3.2).

Solicita o Pix de deslocamento do fluxo externo: move o atendimento para
`Aguardando_confirmacao` com `pix_status='aguardando'` e RESERVA o slot (bloqueio prévio).
A chave/titular/valor são persistidos no payload de `tool_calls` e anexados pela humanização
(M4) — a tool NÃO chama Evolution e NÃO escreve a chave no retorno, mantendo o string crítico
(chave de 32+ chars) fora do LLM. Invariante: externo em Aguardando_confirmacao ⟹ Pix
solicitado (01 §6.1).
"""

import json
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from psycopg import AsyncConnection

from barra.dominio.agenda.service import ConflitoAgenda, criar_bloqueio_previo

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente

VALOR_PIX_DESLOCAMENTO = 100  # R$ fixo do MVP (CONTEXT.md "Pix de deslocamento")


@tool
async def pedir_pix_deslocamento(runtime: ToolRuntime[ContextAgente]) -> str:
    """Solicita Pix de R$100 para deslocamento (saída externa).

    Sem parâmetros — valor é fixo R$100 (MVP), chave/titular vêm do cadastro da modelo.
    Após chamada: pix_status=aguardando, atendimento → Aguardando_confirmacao,
    cria bloqueio prévio do horário (reserva o slot). A humanização ANEXA a
    chave/titular/valor exatos à sua mensagem — você NÃO redigita a chave (string crítico).

    Escreva só o pedido no seu tom ("pra garantir teu horário, manda o pixzinho do deslocamento").
    Use APENAS para atendimento externo após acordar horário e endereço.
    Use APENAS UMA vez por atendimento (segunda chamada é idempotente, não duplica mensagem).
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    modelo_id = runtime.context.modelo_id
    turno_id = runtime.context.turno_id

    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT chave_pix, titular_chave FROM barravips.modelos WHERE id = %s",
            (modelo_id,),
        )
        m = await res.fetchone()
        if m is None or not m["chave_pix"] or not m["titular_chave"]:
            return "ERRO: modelo não tem chave Pix cadastrada. Escale para Fernando."

        try:
            await _executar_idempotente(
                conn,
                turno_id,
                "pedir_pix_deslocamento",
                0,
                payload={
                    "valor": VALOR_PIX_DESLOCAMENTO,
                    "chave": m["chave_pix"],
                    "titular": m["titular_chave"],
                },
                executor=lambda c, p: _aplicar_pedido_pix(c, atendimento_id, p),
            )
        except ConflitoAgenda:
            # Branch 13 (04 §6): a RESERVA do slot falhou (outro cliente já o tomou). O turno
            # inteiro reverteu (pix_status volta a nao_solicitado) — instrua a IA a re-ofertar.
            return (
                "ERRO: o horário combinado acabou de ser reservado por outra conversa. "
                "Ofereça outro horário ao cliente antes de pedir o Pix de novo."
            )

    # Retorno NÃO inclui a chave — a humanização a anexa deterministicamente após o texto da IA.
    return (
        "Pix de R$ 100 solicitado e slot reservado. Escreva o pedido no seu tom, "
        "SEM digitar a chave — o sistema anexa chave/titular/valor exatos após sua mensagem."
    )


async def _aplicar_pedido_pix(
    conn: AsyncConnection[Any], atendimento_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    # Guarda WHERE pix_status='nao_solicitado': idempotência de estado (não re-transiciona um
    # atendimento que já saiu de nao_solicitado). A idempotência por turno fica no tool_calls.
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET pix_status = 'aguardando',
               estado = 'Aguardando_confirmacao',
               fonte_decisao_ultima_transicao = 'extracao_ia'
         WHERE id = %s AND pix_status = 'nao_solicitado'
        """,
        (atendimento_id,),
    )
    # Bloqueio prévio do externo nasce AQUI (simétrico ao interno em registrar_extracao):
    # reserva o slot ao entrar em Aguardando_confirmacao e fecha a janela de double-booking.
    res = await conn.execute(
        """
        SELECT id, modelo_id, data_desejada, horario_desejado, duracao_horas
          FROM barravips.atendimentos
         WHERE id = %s
        """,
        (atendimento_id,),
    )
    atendimento = await res.fetchone()
    assert atendimento is not None
    await criar_bloqueio_previo(conn, atendimento=atendimento)

    await conn.execute(
        """
        INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
        VALUES (%s, 'pix_solicitado', 'agente', 'IA', %s::jsonb)
        """,
        (atendimento_id, json.dumps(payload, default=str)),
    )
    return {"mensagem": "Pix solicitado."}
