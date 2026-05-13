import asyncio
import io
import json
import logging
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.core.errors import ConflitoEstado, NaoEncontrado
from barra.core.storage import presigned_get
from barra.dominio.atendimentos.schemas import (
    AdicionarServicoRequest,
    AlterarEstadoRequest,
    CorrigirRegistroRequest,
    CriarAtendimentoRequest,
    DevolverRequest,
    EditarDadosRequest,
    FecharRequest,
    MidiaInternaResponse,
    PerderRequest,
)
from barra.dominio.atendimentos.service import garantir_atendimento_aberto
from barra.dominio.escaladas.service import aplicar_comando

_logger = logging.getLogger(__name__)

_TIPOS_VALIDOS_UPLOAD = {"imagem", "audio", "documento"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

router = APIRouter(dependencies=[Depends(get_user)])

_GRUPOS_ESTADO: dict[str, tuple[str, ...]] = {
    "Qualificando": ("Novo", "Triagem", "Qualificado"),
    "Aguardando": ("Aguardando_confirmacao", "Confirmado"),
}


@router.get("")
async def listar_atendimentos(
    conn: AsyncConnection[Any] = Depends(get_conn),
    estado: str | None = None,
    tipo_atendimento: str | None = None,
    urgencia: str | None = None,
    ia_pausada: bool | None = None,
    modelo_id: UUID | None = None,
    motivo_perda: str | None = None,
    motivo_escalada: str | None = None,
    q: str | None = None,
    qualificacao_completa: bool | None = None,
    data_inicio: date | None = Query(None),
    data_fim: date | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    if estado:
        grupo = _GRUPOS_ESTADO.get(estado)
        if grupo:
            placeholders = ", ".join(["%s"] * len(grupo))
            filtros.append(f"a.estado IN ({placeholders})")
            params.extend(grupo)
        else:
            filtros.append("a.estado = %s")
            params.append(estado)
    else:
        filtros.append("a.estado NOT IN ('Fechado', 'Perdido')")
    if tipo_atendimento:
        filtros.append("a.tipo_atendimento = %s")
        params.append(tipo_atendimento)
    if urgencia:
        filtros.append("a.urgencia = %s")
        params.append(urgencia)
    if ia_pausada is not None:
        filtros.append("a.ia_pausada = %s")
        params.append(ia_pausada)
    if modelo_id:
        filtros.append("a.modelo_id = %s")
        params.append(modelo_id)
    if motivo_perda and estado == "Perdido":
        filtros.append("a.motivo_perda = %s")
        params.append(motivo_perda)
    if motivo_escalada and ia_pausada is True:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.escaladas e2 "
            "WHERE e2.atendimento_id = a.id "
            "AND e2.aberta_em = (SELECT MAX(e3.aberta_em) FROM barravips.escaladas e3 WHERE e3.atendimento_id = a.id) "
            "AND e2.motivo = %s)"
        )
        params.append(motivo_escalada)
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s OR a.numero_curto::text = %s)")
        params.extend([f"%{q}%", f"%{q}%", q])
    if qualificacao_completa is True:
        filtros.append(
            "a.sinais_qualificacao IS NOT NULL"
            " AND jsonb_typeof(a.sinais_qualificacao->'envia_pix') = 'boolean'"
            " AND jsonb_typeof(a.sinais_qualificacao->'aceita_valor') = 'boolean'"
            " AND jsonb_typeof(a.sinais_qualificacao->'informa_local') = 'boolean'"
            " AND jsonb_typeof(a.sinais_qualificacao->'informa_horario') = 'boolean'"
        )
    elif qualificacao_completa is False:
        filtros.append(
            "NOT ("
            "a.sinais_qualificacao IS NOT NULL"
            " AND jsonb_typeof(a.sinais_qualificacao->'envia_pix') = 'boolean'"
            " AND jsonb_typeof(a.sinais_qualificacao->'aceita_valor') = 'boolean'"
            " AND jsonb_typeof(a.sinais_qualificacao->'informa_local') = 'boolean'"
            " AND jsonb_typeof(a.sinais_qualificacao->'informa_horario') = 'boolean'"
            ")"
        )
    if data_inicio:
        filtros.append("(a.created_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s")
        params.append(data_inicio)
    if data_fim:
        filtros.append("(a.created_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s")
        params.append(data_fim)
    if cursor:
        filtros.append("a.updated_at < %s::timestamptz")
        params.append(cursor)
    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT
          a.id, a.numero_curto, a.estado::text AS estado,
          a.tipo_atendimento::text AS tipo_atendimento, a.urgencia::text AS urgencia,
          a.ia_pausada, a.ia_pausada_motivo::text AS ia_pausada_motivo,
          a.responsavel_atual::text AS responsavel_atual, a.motivo_escalada,
          a.proxima_acao_esperada, a.sinais_qualificacao, a.valor_acordado, a.updated_at,
          c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
          m.id AS modelo_id, m.nome AS modelo_nome
        FROM barravips.atendimentos a
        JOIN barravips.clientes c ON c.id = a.cliente_id
        JOIN barravips.modelos m ON m.id = a.modelo_id
        WHERE {" AND ".join(filtros)}
        ORDER BY a.updated_at DESC
        LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    next_cursor = rows[-1]["updated_at"].isoformat() if len(rows) > limit else None
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": row["id"],
                "numero_curto": row["numero_curto"],
                "cliente": {
                    "id": row["cliente_id"],
                    "nome": row["cliente_nome"],
                    "telefone": row["cliente_telefone"],
                },
                "modelo": {"id": row["modelo_id"], "nome": row["modelo_nome"]},
                "estado": row["estado"],
                "tipo_atendimento": row["tipo_atendimento"],
                "urgencia": row["urgencia"],
                "ia_pausada": row["ia_pausada"],
                "ia_pausada_motivo": row["ia_pausada_motivo"],
                "responsavel_atual": row["responsavel_atual"],
                "motivo_escalada": row["motivo_escalada"],
                "proxima_acao_esperada": row["proxima_acao_esperada"],
                "sinais_qualificacao": row["sinais_qualificacao"],
                "valor_acordado": row["valor_acordado"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/tipos-local")
async def listar_tipos_local(
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, list[str]]:
    result = await conn.execute(
        "SELECT DISTINCT tipo_local FROM barravips.atendimentos "
        "WHERE tipo_local IS NOT NULL "
        "ORDER BY tipo_local"
    )
    rows = await result.fetchall()
    return {"items": [r["tipo_local"] for r in rows]}


@router.post("", status_code=201)
async def criar_atendimento(
    body: CriarAtendimentoRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        cliente = await _fetch_one(
            conn,
            "SELECT id, telefone, arquivado_em FROM barravips.clientes WHERE id = %s",
            (body.cliente_id,),
        )
        if cliente is None:
            raise NaoEncontrado("Cliente")
        if cliente["arquivado_em"] is not None:
            raise ConflitoEstado(
                "cliente_arquivado",
                details={"cliente_id": str(body.cliente_id)},
            )
        modelo = await _fetch_one(
            conn,
            "SELECT id FROM barravips.modelos WHERE id = %s",
            (body.modelo_id,),
        )
        if modelo is None:
            raise NaoEncontrado("Modelo")
        atendimento = await garantir_atendimento_aberto(
            conn,
            cliente_id=body.cliente_id,
            modelo_id=body.modelo_id,
            origem="painel_fernando",
            evolution_chat_id=f"{cliente['telefone']}@s.whatsapp.net",
        )
        if atendimento.ja_existia:
            raise ConflitoEstado(
                "atendimento_aberto_existente",
                details={"atendimento_id": str(atendimento.id)},
            )
    return {
        "id": str(atendimento.id),
        "numero_curto": atendimento.numero_curto,
        "estado": atendimento.estado,
        "cliente_id": str(atendimento.cliente_id),
        "modelo_id": str(atendimento.modelo_id),
        "conversa_id": str(atendimento.conversa_id),
    }


@router.get("/{atendimento_id}")
async def obter_atendimento(
    atendimento_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
    mensagens_limit: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    atendimento = await _fetch_one(
        conn,
        """
        SELECT a.*, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
               m.nome AS modelo_nome, m.percentual_repasse, b.inicio AS bloqueio_inicio,
               b.fim AS bloqueio_fim, b.estado::text AS bloqueio_estado,
               cv.recorrente AS conversa_recorrente,
               cv.observacoes_internas AS conversa_observacoes,
               cv.ultimo_motivo_perda::text AS conversa_ultimo_motivo_perda
          FROM barravips.atendimentos a
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
          LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
          LEFT JOIN barravips.conversas cv ON cv.id = a.conversa_id
         WHERE a.id = %s
        """,
        (atendimento_id,),
    )
    if atendimento is None:
        raise NaoEncontrado("Atendimento")

    mensagens = await _fetch_all(
        conn,
        """
        SELECT * FROM barravips.mensagens
         WHERE atendimento_id = %s
         ORDER BY created_at DESC
         LIMIT %s
        """,
        (atendimento_id, mensagens_limit),
    )
    eventos = await _fetch_all(
        conn,
        "SELECT * FROM barravips.eventos WHERE atendimento_id = %s ORDER BY created_at DESC LIMIT 100",
        (atendimento_id,),
    )
    pix = await _fetch_all(
        conn,
        "SELECT * FROM barravips.comprovantes_pix WHERE atendimento_id = %s ORDER BY created_at DESC",
        (atendimento_id,),
    )
    escaladas = await _fetch_all(
        conn,
        "SELECT * FROM barravips.escaladas WHERE atendimento_id = %s ORDER BY aberta_em DESC",
        (atendimento_id,),
    )
    servicos = await _fetch_all(
        conn,
        """
        SELECT ats.id, ats.programa_id, ats.duracao_id,
               p.nome, d.nome AS duracao_nome, ats.preco_snapshot, ats.created_at
          FROM barravips.atendimento_servicos ats
          JOIN barravips.programas p ON p.id = ats.programa_id
          JOIN barravips.duracoes d ON d.id = ats.duracao_id
         WHERE ats.atendimento_id = %s
         ORDER BY ats.created_at
        """,
        (atendimento_id,),
    )
    midias_internas = await _fetch_all(
        conn,
        """
        SELECT id, tipo, nome_arquivo, media_object_key, created_at
          FROM barravips.atendimento_midias
         WHERE atendimento_id = %s
         ORDER BY created_at DESC
        """,
        (atendimento_id,),
    )
    return {
        "atendimento": atendimento,
        "cliente": {
            "id": atendimento["cliente_id"],
            "nome": atendimento["cliente_nome"],
            "telefone": atendimento["cliente_telefone"],
        },
        "conversa": {
            "id": atendimento["conversa_id"],
            "recorrente": atendimento["conversa_recorrente"],
            "observacoes_internas": atendimento["conversa_observacoes"],
            "ultimo_motivo_perda": atendimento["conversa_ultimo_motivo_perda"],
        },
        "modelo": {"id": atendimento["modelo_id"], "nome": atendimento["modelo_nome"]},
        "bloqueio": None
        if atendimento["bloqueio_id"] is None
        else {
            "id": atendimento["bloqueio_id"],
            "inicio": atendimento["bloqueio_inicio"],
            "fim": atendimento["bloqueio_fim"],
            "estado": atendimento["bloqueio_estado"],
        },
        "mensagens": _enriquecer_midias(mensagens, request),
        "eventos": eventos,
        "comprovantes_pix": pix,
        "escaladas": escaladas,
        "servicos": servicos,
        "midias_internas": _enriquecer_midias(midias_internas, request),
    }


@router.post("/{atendimento_id}/devolver")
async def devolver_atendimento(
    atendimento_id: UUID,
    body: DevolverRequest,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="devolver_para_ia",
        payload={"observacao": body.observacao, "usuario_id": str(user.id)},
    )
    return {"id": result.atendimento_id, "estado": result.estado, "ia_pausada": False}


@router.post("/{atendimento_id}/fechar")
async def fechar_atendimento(
    atendimento_id: UUID,
    body: FecharRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="registrar_fechado",
        payload={"valor_final": body.valor_final},
    )
    return {"id": result.atendimento_id, "estado": result.estado}


@router.post("/{atendimento_id}/perder")
async def perder_atendimento(
    atendimento_id: UUID,
    body: PerderRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="registrar_perdido",
        payload=body.model_dump(),
    )
    return {"id": result.atendimento_id, "estado": result.estado}


@router.patch("/{atendimento_id}/estado")
async def alterar_estado(
    atendimento_id: UUID,
    body: AlterarEstadoRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    row = await _fetch_one(
        conn,
        "SELECT id, estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    if row is None:
        raise NaoEncontrado("Atendimento")
    estado_anterior = row["estado"]
    await conn.execute(
        "UPDATE barravips.atendimentos SET estado = %s WHERE id = %s",
        (body.estado, atendimento_id),
    )
    await conn.execute(
        "INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)"
        " VALUES (%s, 'transicao_estado', 'painel', 'Fernando', %s::jsonb)",
        (
            atendimento_id,
            json.dumps({"estado_anterior": estado_anterior, "estado_novo": body.estado, "via": "kanban"}),
        ),
    )
    return {"id": str(atendimento_id), "estado": body.estado}


@router.patch("/{atendimento_id}/dados")
async def editar_dados(
    atendimento_id: UUID,
    body: EditarDadosRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    row = await _fetch_one(
        conn,
        "SELECT id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    if row is None:
        raise NaoEncontrado("Atendimento")
    campos = body.model_dump(exclude_none=True)
    if campos:
        set_clausulas = ", ".join(f"{campo} = %s" for campo in campos)
        valores: list[Any] = [str(v) if hasattr(v, "isoformat") else v for v in campos.values()]
        valores.append(atendimento_id)
        await conn.execute(
            f"UPDATE barravips.atendimentos SET {set_clausulas} WHERE id = %s",
            valores,
        )
        payload_log = {k: str(v) for k, v in campos.items()}
        await conn.execute(
            "INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)"
            " VALUES (%s, 'dados_editados', 'painel', 'Fernando', %s::jsonb)",
            (atendimento_id, json.dumps(payload_log, ensure_ascii=False)),
        )
    return {"id": str(atendimento_id)}


@router.post("/{atendimento_id}/corrigir-registro")
async def corrigir_registro(
    atendimento_id: UUID,
    body: CorrigirRegistroRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="corrigir_registro",
        payload=body.model_dump(),
    )
    return {"id": result.atendimento_id, "estado": result.estado}


@router.get("/{atendimento_id}/servicos")
async def listar_servicos(
    atendimento_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await _fetch_all(
        conn,
        """
        SELECT ats.id, ats.programa_id, ats.duracao_id,
               p.nome, d.nome AS duracao_nome, ats.preco_snapshot, ats.created_at
          FROM barravips.atendimento_servicos ats
          JOIN barravips.programas p ON p.id = ats.programa_id
          JOIN barravips.duracoes d ON d.id = ats.duracao_id
         WHERE ats.atendimento_id = %s
         ORDER BY ats.created_at
        """,
        (atendimento_id,),
    )


@router.post("/{atendimento_id}/servicos", status_code=201)
async def adicionar_servico(
    atendimento_id: UUID,
    body: AdicionarServicoRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    at = await _fetch_one(
        conn, "SELECT modelo_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    if at is None:
        raise NaoEncontrado("Atendimento")
    mp = await _fetch_one(
        conn,
        "SELECT preco FROM barravips.modelo_programas WHERE modelo_id=%s AND programa_id=%s AND duracao_id=%s",
        (at["modelo_id"], body.programa_id, body.duracao_id),
    )
    if mp is None:
        raise NaoEncontrado("Programa não vinculado à modelo")
    row = await _fetch_one(
        conn,
        """
        INSERT INTO barravips.atendimento_servicos (atendimento_id, programa_id, duracao_id, preco_snapshot)
        VALUES (%s, %s, %s, %s)
        RETURNING id, programa_id, duracao_id, preco_snapshot, created_at
        """,
        (atendimento_id, body.programa_id, body.duracao_id, mp["preco"]),
    )
    assert row is not None
    return row


@router.delete("/{atendimento_id}/servicos/{servico_id}", status_code=204)
async def remover_servico(
    atendimento_id: UUID,
    servico_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    result = await conn.execute(
        "DELETE FROM barravips.atendimento_servicos WHERE id = %s AND atendimento_id = %s",
        (servico_id, atendimento_id),
    )
    if result.rowcount == 0:
        raise NaoEncontrado("Serviço")


@router.post("/{atendimento_id}/midias", status_code=201)
async def upload_midia(
    atendimento_id: UUID,
    request: Request,
    arquivo: UploadFile,
    tipo: str = Form(...),
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> MidiaInternaResponse:
    # Anexo interno do atendimento. NÃO vai para `mensagens` nem para Evolution.
    # Ver CONTEXT.md (Conversa cliente) e docs/mvp/06-dados-interfaces.md §4.2.
    if tipo not in _TIPOS_VALIDOS_UPLOAD:
        raise HTTPException(400, f"tipo inválido: {tipo!r}. Use 'imagem', 'audio' ou 'documento'.")
    ct = (arquivo.content_type or "").lower()
    if not (ct.startswith("image/") or ct.startswith("audio/") or ct == "application/pdf"):
        raise HTTPException(415, "tipo de arquivo não permitido (aceitos: image/*, audio/*, application/pdf)")

    data = await arquivo.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "arquivo muito grande (máximo 20 MB)")

    row = await _fetch_one(
        conn,
        "SELECT id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    if row is None:
        raise NaoEncontrado("Atendimento")

    minio = getattr(request.app.state, "minio", None)
    if minio is None:
        raise HTTPException(503, "MinIO não configurado")
    bucket = request.app.state.settings.minio_bucket_media

    file_uuid = uuid4()
    filename = arquivo.filename or f"midia.{ct.split('/')[-1]}"
    key = f"atendimentos/{atendimento_id}/midias/{file_uuid}/{filename}"

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: minio.put_object(bucket, key, io.BytesIO(data), len(data), content_type=ct),
    )

    midia = await _fetch_one(
        conn,
        """
        INSERT INTO barravips.atendimento_midias
          (atendimento_id, tipo, nome_arquivo, media_object_key, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, tipo, nome_arquivo, media_object_key, created_at
        """,
        (atendimento_id, tipo, filename, key, user.id),
    )
    assert midia is not None
    return MidiaInternaResponse(
        id=midia["id"],
        tipo=midia["tipo"],
        nome_arquivo=midia["nome_arquivo"],
        media_object_key=midia["media_object_key"],
        media_url=presigned_get(minio, bucket, key),
        created_at=midia["created_at"],
    )


@router.delete("/{atendimento_id}/midias/{midia_id}", status_code=204)
async def deletar_midia(
    atendimento_id: UUID,
    midia_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    row = await _fetch_one(
        conn,
        "SELECT media_object_key FROM barravips.atendimento_midias"
        " WHERE id = %s AND atendimento_id = %s",
        (midia_id, atendimento_id),
    )
    if row is None:
        raise NaoEncontrado("Mídia")

    await conn.execute("DELETE FROM barravips.atendimento_midias WHERE id = %s", (midia_id,))

    key = row.get("media_object_key")
    if key:
        minio = getattr(request.app.state, "minio", None)
        if minio is not None:
            bucket = request.app.state.settings.minio_bucket_media
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: minio.remove_object(bucket, key))
            except Exception as exc:
                _logger.warning("falha_remover_minio key=%s erro=%s", key, exc)


def _enriquecer_midias(mensagens: list[dict[str, Any]], request: Request) -> list[dict[str, Any]]:
    minio = getattr(request.app.state, "minio", None)
    bucket = request.app.state.settings.minio_bucket_media
    result = []
    for m in mensagens:
        key = m.get("media_object_key")
        url: str | None = None
        if key:
            try:
                url = presigned_get(minio, bucket, key)
            except Exception as exc:
                _logger.warning("falha_presigned_get key=%s erro=%s", key, exc)
        result.append({**m, "media_url": url})
    return result


async def _fetch_one(
    conn: AsyncConnection[Any],
    query: str,
    params: tuple[Any, ...],
) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _fetch_all(
    conn: AsyncConnection[Any],
    query: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())
