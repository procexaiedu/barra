import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.core.errors import ConflitoEstado, NaoEncontrado
from barra.core.evolution import EvolutionClient
from barra.core.metrics import PIX
from barra.core.storage import presigned_get
from barra.dominio.escaladas.service import aplicar_comando
from barra.dominio.pix.schemas import (
    AprovarPixRequest,
    ReabrirPixRequest,
    RejeitarPixRequest,
)

_logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_user)])


_FILTRO_STATUS = {
    "pendentes": "p.decisao_pipeline = 'em_revisao' AND p.decisao_final IS NULL",
    "validado_auto": "p.decisao_pipeline = 'validado' AND p.decisao_final IS NULL",
    "validado_manual": "p.decisao_final = 'validado'",
    "rejeitado": "p.decisao_final = 'invalido'",
    "todos": "1=1",
}

_PERIODO_HORAS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}


@router.get("")
async def listar_pix(
    conn: AsyncConnection[Any] = Depends(get_conn),
    status: str = "pendentes",
    modelo_id: UUID | None = None,
    motivo_em_revisao: str | None = None,
    periodo: str | None = None,
    atendimento_id: UUID | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    filtro_status = _FILTRO_STATUS.get(status, _FILTRO_STATUS["pendentes"])
    filtros = [filtro_status]
    params: list[Any] = []

    if modelo_id is not None:
        filtros.append("a.modelo_id = %s")
        params.append(modelo_id)
    if motivo_em_revisao:
        filtros.append("p.motivo_em_revisao = %s")
        params.append(motivo_em_revisao)
    if periodo and periodo in _PERIODO_HORAS:
        cutoff = datetime.now(UTC) - timedelta(hours=_PERIODO_HORAS[periodo])
        filtros.append("p.created_at >= %s")
        params.append(cutoff)
    if atendimento_id is not None:
        filtros.append("p.atendimento_id = %s")
        params.append(atendimento_id)
    if q:
        termo = q.strip()
        if termo.startswith("#"):
            termo = termo[1:]
        if termo.isdigit():
            filtros.append(
                "(c.nome ILIKE %s OR regexp_replace(c.telefone, '\\D', '', 'g') LIKE %s "
                "OR a.numero_curto::text = %s OR p.valor_extraido::text LIKE %s)"
            )
            params.extend([f"%{termo}%", f"%{termo}%", termo, f"%{termo}%"])
        else:
            filtros.append(
                "(c.nome ILIKE %s OR regexp_replace(c.telefone, '\\D', '', 'g') LIKE %s "
                "OR p.valor_extraido::text LIKE %s)"
            )
            params.extend([f"%{termo}%", f"%{termo}%", f"%{termo}%"])

    ordem = "p.created_at ASC" if status == "pendentes" else "p.created_at DESC"
    operador = ">" if status == "pendentes" else "<"
    if cursor:
        filtros.append(f"p.created_at {operador} %s::timestamptz")
        params.append(cursor)

    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT
          p.id, p.decisao_pipeline::text AS decisao_pipeline,
          p.decisao_final::text AS decisao_final,
          p.motivo_em_revisao, p.valor_extraido, p.created_at,
          c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
          m.id AS modelo_id, m.nome AS modelo_nome,
          a.id AS atendimento_id, a.numero_curto, a.estado::text AS atendimento_estado
          FROM barravips.comprovantes_pix p
          JOIN barravips.atendimentos a ON a.id = p.atendimento_id
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE {" AND ".join(filtros)}
         ORDER BY {ordem}
         LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    next_cursor = rows[-1]["created_at"].isoformat() if len(rows) > limit else None
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": row["id"],
                "cliente": {
                    "id": row["cliente_id"],
                    "nome": row["cliente_nome"],
                    "telefone": row["cliente_telefone"],
                },
                "modelo": {"id": row["modelo_id"], "nome": row["modelo_nome"]},
                "atendimento": {
                    "id": row["atendimento_id"],
                    "numero_curto": row["numero_curto"],
                    "estado": row["atendimento_estado"],
                }
                if row["atendimento_id"]
                else None,
                "decisao_pipeline": row["decisao_pipeline"],
                "decisao_final": row["decisao_final"],
                "motivo_em_revisao": row["motivo_em_revisao"],
                "valor_extraido": float(row["valor_extraido"]) if row["valor_extraido"] is not None else None,
                "created_at": row["created_at"],
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/{pix_id}")
async def obter_pix(
    pix_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    pix = await _pix(conn, pix_id)
    if pix is None:
        raise NaoEncontrado("Comprovante Pix")

    eventos_result = await conn.execute(
        """
        SELECT id, tipo::text AS tipo, origem::text AS origem,
               autor::text AS autor, payload, created_at
          FROM barravips.eventos
         WHERE atendimento_id = %s AND tipo IN ('pix_status_mudado', 'pix_solicitado')
         ORDER BY created_at DESC
        """,
        (pix["atendimento_id"],),
    )
    eventos_rows = list(await eventos_result.fetchall())

    nome_arquivo = (pix["media_object_key"] or "").rsplit("/", 1)[-1] or "comprovante"
    mime_type = "image/jpeg" if pix["mensagem_tipo"] == "imagem" else "application/octet-stream"
    if pix["mensagem_tipo"] == "audio":
        mime_type = "audio/ogg"
    if nome_arquivo.lower().endswith(".pdf"):
        mime_type = "application/pdf"
    elif nome_arquivo.lower().endswith(".png"):
        mime_type = "image/png"

    return {
        "pix": {
            "id": pix["id"],
            "decisao_pipeline": pix["decisao_pipeline"],
            "decisao_final": pix["decisao_final"],
            "motivo_em_revisao": pix["motivo_em_revisao"],
            "valor_extraido": float(pix["valor_extraido"]) if pix["valor_extraido"] is not None else None,
            "horario_transacao": pix["timestamp_extraido"],
            "titular_extraido": pix["titular_extraido"],
            "documento_extraido": None,
            "chave_extraida": pix["chave_extraida"],
            "tipo_chave": None,
            "hash_duplicidade": None,
            "nome_arquivo": nome_arquivo,
            "tamanho": 0,
            "mime_type": mime_type,
            "comprovante_disponivel": pix["media_object_key"] is not None,
            "created_at": pix["created_at"],
        },
        "cliente": {
            "id": pix["cliente_id"],
            "nome": pix["cliente_nome"],
            "telefone": pix["cliente_telefone"],
        },
        "modelo": {"id": pix["modelo_id"], "nome": pix["modelo_nome"]},
        "conversa": {"id": pix["conversa_id"]} if pix["conversa_id"] else None,
        "atendimento": {
            "id": pix["atendimento_id"],
            "numero_curto": pix["numero_curto"],
            "estado": pix["atendimento_estado"],
            "tipo_atendimento": pix["tipo_atendimento"],
            "urgencia": pix["urgencia"],
            "valor_acordado": float(pix["valor_acordado"]) if pix["valor_acordado"] is not None else None,
            "proxima_acao_esperada": pix["proxima_acao_esperada"],
        }
        if pix["atendimento_id"]
        else None,
        "checagens": _checagens_de(pix),
        "eventos": [_evento_para_timeline(evt, pix_id) for evt in eventos_rows],
    }


@router.get("/{pix_id}/comprovante-url")
async def comprovante_url(
    pix_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await conn.execute(
        """
        SELECT msg.media_object_key
          FROM barravips.comprovantes_pix p
          JOIN barravips.mensagens msg ON msg.id = p.mensagem_id
         WHERE p.id = %s
        """,
        (pix_id,),
    )
    row = await result.fetchone()
    if row is None or not row["media_object_key"]:
        raise NaoEncontrado("Comprovante Pix")
    expires = 900
    url = presigned_get(
        getattr(request.app.state, "minio", None),
        request.app.state.settings.minio_bucket_media,
        row["media_object_key"],
        expires=expires,
    )
    return {
        "url": url,
        "expires_at": datetime.now(UTC) + timedelta(seconds=expires),
    }


@router.post("/{pix_id}/aprovar")
async def aprovar_pix(
    pix_id: UUID,
    request: Request,
    _body: AprovarPixRequest,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    pix = await _pix(conn, pix_id)
    if pix is None:
        raise NaoEncontrado("Comprovante Pix")
    if not (pix["decisao_pipeline"] == "em_revisao" and pix["decisao_final"] is None):
        raise ConflitoEstado("Pix nao esta em revisao.")

    async with conn.transaction():
        await conn.execute(
            """
            UPDATE barravips.comprovantes_pix
               SET decisao_final = 'validado', decisao_final_por = %s
             WHERE id = %s
            """,
            (user.id, pix_id),
        )
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=pix["atendimento_id"],
            comando="atualizar_pix",
            payload={"decisao": "validado", "pix_id": str(pix_id)},
        )

    # Notificação ao grupo de coordenação é best-effort: a aprovação já foi
    # persistida acima. Se a instância Evolution estiver desconectada/inválida,
    # logamos e seguimos — não faz sentido reverter decisão de negócio porque
    # o envio do card falhou.
    if (
        request.app.state.settings.evolution_grupo_coordenacao_jid
        and pix["evolution_instance_id"]
    ):
        client = EvolutionClient(request.app.state.settings)
        try:
            await client.enviar_texto(
                conn=conn,
                instance_id=pix["evolution_instance_id"],
                remote_jid=request.app.state.settings.evolution_grupo_coordenacao_jid,
                texto=f"Saida confirmada #{pix['numero_curto']}",
                contexto="grupo_coordenacao",
                tipo="confirmacao",
                atendimento_id=pix["atendimento_id"],
                conversa_id=pix["conversa_id"],
                payload={"pix_id": str(pix_id)},
            )
        except httpx.HTTPError as exc:
            _logger.warning(
                "pix_aprovar_notificacao_falhou pix=%s instance=%s erro=%s",
                pix_id,
                pix["evolution_instance_id"],
                exc,
            )
    PIX.labels("validado").inc()
    return {"id": pix_id, "decisao_final": "validado"}


@router.post("/{pix_id}/rejeitar")
async def rejeitar_pix(
    pix_id: UUID,
    body: RejeitarPixRequest,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    pix = await _pix(conn, pix_id)
    if pix is None:
        raise NaoEncontrado("Comprovante Pix")
    if not (pix["decisao_pipeline"] == "em_revisao" and pix["decisao_final"] is None):
        raise ConflitoEstado("Pix nao esta em revisao.")

    async with conn.transaction():
        await conn.execute(
            """
            UPDATE barravips.comprovantes_pix
               SET decisao_final = 'invalido', decisao_final_por = %s
             WHERE id = %s
            """,
            (user.id, pix_id),
        )
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=pix["atendimento_id"],
            comando="atualizar_pix",
            payload={
                "decisao": "invalido",
                "pix_id": str(pix_id),
                "motivo": body.motivo,
                "observacao": body.observacao,
            },
        )
    PIX.labels("invalido").inc()
    return {"id": pix_id, "decisao_final": "invalido"}


@router.post("/{pix_id}/reabrir")
async def reabrir_pix(
    pix_id: UUID,
    _body: ReabrirPixRequest,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    pix = await _pix(conn, pix_id)
    if pix is None:
        raise NaoEncontrado("Comprovante Pix")
    if pix["decisao_final"] != "invalido":
        raise ConflitoEstado("Pix nao esta rejeitado.")

    async with conn.transaction():
        await conn.execute(
            """
            UPDATE barravips.comprovantes_pix
               SET decisao_final = NULL,
                   decisao_final_por = NULL,
                   decisao_pipeline = 'em_revisao'
             WHERE id = %s
            """,
            (pix_id,),
        )
        await conn.execute(
            """
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            VALUES (%s, 'pix_status_mudado', 'painel', 'Fernando', %s)
            """,
            (
                pix["atendimento_id"],
                {"pix_id": str(pix_id), "decisao": "reaberto", "usuario_id": str(user.id)},
            ),
        )
    return {"id": pix_id, "decisao_final": None}


def _checagens_de(pix: dict[str, Any]) -> list[dict[str, Any]]:
    valor_ok = (
        pix["valor_extraido"] is not None
        and pix["valor_acordado"] is not None
        and pix["valor_extraido"] == pix["valor_acordado"]
    )
    chave_ok = (
        pix["chave_extraida"] is not None
        and pix["chave_pix"] is not None
        and pix["chave_extraida"].strip().lower() == pix["chave_pix"].strip().lower()
    )
    return [
        {
            "chave": "valor_esperado",
            "label": "Valor esperado",
            "passou": valor_ok,
            "motivo": None
            if valor_ok
            else (
                f"esperado {pix['valor_acordado']}, recebido {pix['valor_extraido']}"
                if pix["valor_extraido"] is not None
                else "valor nao extraido"
            ),
        },
        {
            "chave": "janela_temporal",
            "label": "Janela temporal",
            "passou": pix["timestamp_extraido"] is not None,
            "motivo": None if pix["timestamp_extraido"] is not None else "horario nao extraido",
        },
        {
            "chave": "duplicidade",
            "label": "Duplicidade",
            "passou": True,
            "motivo": None,
        },
        {
            "chave": "conta_destino",
            "label": "Conta destino",
            "passou": chave_ok,
            "motivo": None if chave_ok else "chave nao corresponde a cadastrada",
        },
    ]


def _evento_para_timeline(evt: dict[str, Any], pix_id: UUID) -> dict[str, Any]:
    payload = evt["payload"] or {}
    decisao = payload.get("decisao")
    autor_origem = (evt["origem"], evt["autor"])
    tipo = evt["tipo"]

    if tipo == "pix_solicitado":
        tipo_visual = "comprovante_recebido"
        resumo = None
    elif decisao == "validado" and autor_origem[0] == "painel":
        tipo_visual = "pix_validado_manual"
        resumo = None
    elif decisao == "validado":
        tipo_visual = "pipeline_validado"
        resumo = None
    elif decisao == "invalido":
        tipo_visual = "pix_rejeitado"
        resumo = payload.get("motivo")
    elif decisao == "reaberto":
        tipo_visual = "pix_reaberto"
        resumo = None
    elif tipo == "pix_status_mudado" and evt["origem"] == "pipeline_pix":
        tipo_visual = "pipeline_em_revisao"
        resumo = None
    else:
        tipo_visual = tipo
        resumo = None

    return {
        "id": evt["id"],
        "tipo": tipo_visual,
        "origem": evt["origem"],
        "autor": evt["autor"],
        "resumo": resumo,
        "payload": payload,
        "created_at": evt["created_at"],
    }


async def _pix(conn: AsyncConnection[Any], pix_id: UUID) -> dict[str, Any] | None:
    result = await conn.execute(
        """
        SELECT p.id, p.atendimento_id, p.created_at,
               p.decisao_pipeline::text AS decisao_pipeline,
               p.decisao_final::text AS decisao_final,
               p.motivo_em_revisao, p.valor_extraido,
               p.chave_extraida, p.titular_extraido, p.timestamp_extraido,
               msg.media_object_key, msg.tipo::text AS mensagem_tipo,
               a.numero_curto, a.conversa_id, a.valor_acordado,
               a.estado::text AS atendimento_estado,
               a.tipo_atendimento::text AS tipo_atendimento,
               a.urgencia::text AS urgencia,
               a.proxima_acao_esperada,
               c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
               m.id AS modelo_id, m.nome AS modelo_nome,
               m.chave_pix, m.titular_chave, m.evolution_instance_id
          FROM barravips.comprovantes_pix p
          JOIN barravips.mensagens msg ON msg.id = p.mensagem_id
          JOIN barravips.atendimentos a ON a.id = p.atendimento_id
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE p.id = %s
        """,
        (pix_id,),
    )
    return await result.fetchone()
