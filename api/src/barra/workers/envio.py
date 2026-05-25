"""Job de envio Evolution com registro em envios_evolution."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.errors import ErroDominio
from barra.core.evolution import EvolutionClient
from barra.dominio.escaladas.modelos import TipoEscalada, rotulo_tipo_escalada
from barra.workers._cards import render_card


async def enviar_texto_job(
    conn: AsyncConnection[Any],
    client: EvolutionClient,
    *,
    instance_id: str,
    remote_jid: str,
    texto: str,
    contexto: str,
    tipo: str,
    payload: dict[str, Any] | None = None,
) -> str:
    if not instance_id:
        raise ErroDominio("EVOLUTION_NAO_PAREADA", "Evolution nao pareada.", status_code=409)
    return await client.enviar_texto(
        conn=conn,
        instance_id=instance_id,
        remote_jid=remote_jid,
        texto=texto,
        contexto=contexto,
        tipo=tipo,
        payload=payload or {},
    )


# --- Cards no grupo de Coordenação (05 §6) ----------------------------------
# Cards são jobs ARQ diretos, enviados pelo EvolutionClient SEM passar pela humanização.
# Uma função `enviar_card` única despacha por `tipo`; cada renderer é idempotente por owner
# (06 §9): só envia se o card ainda não foi enviado e grava o id no próprio dono.


async def _card_escalada(ctx: dict[str, Any], *, escalada_id: str, **_: Any) -> None:
    """Card de handoff no grupo de Coordenação (05 §6).

    Idempotência por owner: só envia se `escaladas.card_message_id IS NULL`. O POST
    (→ envios_evolution, via `enviar_texto`) e a gravação do `card_message_id` vivem na
    MESMA transação — o retry do ARQ relê a coluna e não reenvia.
    """
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT e.tipo::text AS tipo, e.resumo_operacional, e.acao_esperada,
                   e.card_message_id, a.numero_curto, cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.modelos mo ON mo.id = a.modelo_id
              JOIN barravips.clientes cl ON cl.id = a.cliente_id
             WHERE e.id = %s
            """,
            (UUID(escalada_id),),
        )
        e = await res.fetchone()
        if not e or e["card_message_id"]:
            return  # idempotência por owner: card já enviado

        rotulo = rotulo_tipo_escalada(TipoEscalada(e["tipo"])) if e["tipo"] else "Handoff"
        texto = render_card(
            "escalada",
            numero_curto=e["numero_curto"],
            cliente_nome=e["cliente_nome"] or "cliente",
            tipo_rotulo=rotulo,
            resumo_operacional=e["resumo_operacional"],
            acao_esperada=e["acao_esperada"],
        )
        async with conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=e["evolution_instance_id"],
                remote_jid=e["coordenacao_chat_id"],
                texto=texto,
                contexto="coordenacao",
                tipo="card_escalada",
            )
            await conn.execute(
                "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
                (mid, UUID(escalada_id)),
            )


async def _card_pix(ctx: dict[str, Any], **_: Any) -> None:
    # TODO(M5c): card "saída confirmada" (pix_validado / pix_em_revisao com sinalização da
    # duvidez); idempotência por `comprovantes_pix.card_message_id` (06 §2.5, §9).
    raise NotImplementedError("card de Pix será preenchido no M5c")


async def _card_chegada(ctx: dict[str, Any], **_: Any) -> None:
    # TODO(M5d): card "cliente chegou" (foto de portaria), imagem anexada; idempotência por
    # `escaladas.card_message_id` (06 §4, §9).
    raise NotImplementedError("card de chegada será preenchido no M5d")


async def _card_aviso_saida(ctx: dict[str, Any], **_: Any) -> None:
    # TODO(M5d): card "cliente saiu de casa"; sem owner → idempotência por SETNX
    # `card:aviso_saida:{atendimento_id}` (06 §5, §9).
    raise NotImplementedError("card de aviso de saída será preenchido no M5d")


async def _card_loc_pin(ctx: dict[str, Any], **_: Any) -> None:
    # TODO(M3d): pin de localização do endereço, enfileirado após `registrar_extracao` (09 §4.3).
    raise NotImplementedError("card de pin de localização será preenchido no M3d")


_RENDER_CARD: dict[str, Callable[..., Awaitable[None]]] = {
    "escalada": _card_escalada,
    "pix_validado": _card_pix,
    "pix_em_revisao": _card_pix,
    "chegada": _card_chegada,
    "aviso_saida": _card_aviso_saida,
    "loc_pin": _card_loc_pin,
}


async def enviar_card(ctx: dict[str, Any], *, tipo: str, **kw: Any) -> None:
    """Job ARQ: envia um card no grupo de Coordenação direto pelo Evolution, sem passar pela
    humanização (05 §6). Dispatch por `tipo`; cada renderer é idempotente por owner."""
    render = _RENDER_CARD[tipo]
    await render(ctx, **kw)
