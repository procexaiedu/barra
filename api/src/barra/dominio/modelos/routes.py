from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import EntradaInvalida, NaoEncontrado
from barra.core.evolution import EvolutionClient
from barra.core.storage import presigned_get, presigned_put
from barra.dominio.modelos.schemas import (
    ConectarWhatsappRequest,
    FaqBody,
    MidiaCreate,
    MidiaPatch,
    MidiaUploadUrlRequest,
    ModeloCreate,
    ModeloPatch,
)

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def listar_modelos(conn: AsyncConnection[Any] = Depends(get_conn)) -> list[dict[str, Any]]:
    result = await conn.execute("SELECT * FROM barravips.modelos ORDER BY created_at DESC")
    return list(await result.fetchall())


@router.post("", status_code=201)
async def criar_modelo(
    body: ModeloCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await conn.execute(
        """
        INSERT INTO barravips.modelos (
          nome, idade, numero_whatsapp, valor_padrao, percentual_repasse, chave_pix,
          titular_chave, idiomas, localizacao_operacional, tipo_atendimento_aceito
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            body.nome,
            body.idade,
            body.numero_whatsapp,
            body.valor_padrao,
            body.percentual_repasse,
            body.chave_pix,
            body.titular_chave,
            body.idiomas,
            body.localizacao_operacional,
            body.tipo_atendimento_aceito,
        ),
    )
    row = await result.fetchone()
    assert row is not None
    return cast(dict[str, Any], row)


@router.get("/{modelo_id}")
async def obter_modelo(
    modelo_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    modelo = await _one(conn, "SELECT * FROM barravips.modelos WHERE id = %s", (modelo_id,))
    if modelo is None:
        raise NaoEncontrado("Modelo")
    faq = await _all(
        conn,
        "SELECT * FROM barravips.modelo_faq WHERE modelo_id = %s ORDER BY created_at DESC",
        (modelo_id,),
    )
    midia = await _midia(conn, request, modelo_id)
    return {
        "modelo": modelo,
        "faq": faq,
        "midia": midia,
        "evolution_status": {"instance_id": modelo["evolution_instance_id"]},
    }


@router.patch("/{modelo_id}")
async def editar_modelo(
    modelo_id: UUID,
    body: ModeloPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        modelo = await _one(conn, "SELECT * FROM barravips.modelos WHERE id = %s", (modelo_id,))
        if modelo is None:
            raise NaoEncontrado("Modelo")
        return modelo
    set_sql = ", ".join([f"{key} = %s" for key in updates])
    params = list(updates.values()) + [modelo_id]
    result = await conn.execute(
        f"UPDATE barravips.modelos SET {set_sql} WHERE id = %s RETURNING *",
        params,
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Modelo")
    return cast(dict[str, Any], row)


@router.post("/{modelo_id}/conectar-whatsapp")
async def conectar_whatsapp(
    modelo_id: UUID,
    body: ConectarWhatsappRequest,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    modelo = await _one(conn, "SELECT * FROM barravips.modelos WHERE id = %s", (modelo_id,))
    if modelo is None:
        raise NaoEncontrado("Modelo")
    if modelo["evolution_instance_id"] and not body.confirmar_rotacao:
        return {"status": "connected", "instance_id": modelo["evolution_instance_id"], "qr_code": None}
    instance_id = modelo["evolution_instance_id"] or f"modelo-{modelo_id}"
    client = EvolutionClient(request.app.state.settings)
    status = await client.conectar_instancia(instance_id)
    await conn.execute(
        "UPDATE barravips.modelos SET evolution_instance_id = %s WHERE id = %s",
        (instance_id, modelo_id),
    )
    return {"status": status.get("status", "pending"), "instance_id": instance_id, "qr_code": status.get("qrcode")}


@router.get("/{modelo_id}/faq")
async def listar_faq(modelo_id: UUID, conn: AsyncConnection[Any] = Depends(get_conn)) -> list[dict[str, Any]]:
    await _ensure_modelo(conn, modelo_id)
    return await _all(
        conn,
        "SELECT * FROM barravips.modelo_faq WHERE modelo_id = %s ORDER BY created_at DESC",
        (modelo_id,),
    )


@router.post("/{modelo_id}/faq", status_code=201)
async def criar_faq(
    modelo_id: UUID,
    body: FaqBody,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    await _ensure_modelo(conn, modelo_id)
    result = await conn.execute(
        """
        INSERT INTO barravips.modelo_faq (modelo_id, pergunta, resposta, tags)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (modelo_id, body.pergunta, body.resposta, body.tags),
    )
    row = await result.fetchone()
    assert row is not None
    return cast(dict[str, Any], row)


@router.patch("/{modelo_id}/faq/{faq_id}")
async def editar_faq(
    modelo_id: UUID,
    faq_id: UUID,
    body: FaqBody,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await conn.execute(
        """
        UPDATE barravips.modelo_faq
           SET pergunta = %s, resposta = %s, tags = %s
         WHERE id = %s AND modelo_id = %s
        RETURNING *
        """,
        (body.pergunta, body.resposta, body.tags, faq_id, modelo_id),
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("FAQ")
    return cast(dict[str, Any], row)


@router.delete("/{modelo_id}/faq/{faq_id}", status_code=204)
async def deletar_faq(
    modelo_id: UUID,
    faq_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await conn.execute(
        "DELETE FROM barravips.modelo_faq WHERE id = %s AND modelo_id = %s",
        (faq_id, modelo_id),
    )


@router.post("/{modelo_id}/midia/upload-url")
async def criar_upload_url(
    modelo_id: UUID,
    body: MidiaUploadUrlRequest,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    await _ensure_modelo(conn, modelo_id)
    filename = PurePosixPath(body.filename).name
    object_key = f"modelos/{modelo_id}/midia/{uuid4()}/{filename}"
    upload_url = presigned_put(
        getattr(request.app.state, "minio", None),
        request.app.state.settings.minio_bucket_media,
        object_key,
    )
    return {"object_key": object_key, "upload_url": upload_url, "expires_in": 900}


@router.post("/{modelo_id}/midia", status_code=201)
async def criar_midia(
    modelo_id: UUID,
    body: MidiaCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    _validar_prefixo_midia(modelo_id, body.object_key)
    result = await conn.execute(
        """
        INSERT INTO barravips.modelo_midia (modelo_id, tipo, tag, object_key, aprovada)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (modelo_id, body.tipo, body.tag, body.object_key, body.aprovada),
    )
    row = await result.fetchone()
    assert row is not None
    return cast(dict[str, Any], row)


@router.get("/{modelo_id}/midia")
async def listar_midia(
    modelo_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await _midia(conn, request, modelo_id)


@router.patch("/{modelo_id}/midia/{midia_id}")
async def editar_midia(
    modelo_id: UUID,
    midia_id: UUID,
    body: MidiaPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise EntradaInvalida("ENTRADA_VAZIA", "Nenhum campo informado.")
    set_sql = ", ".join([f"{key} = %s" for key in updates])
    params = list(updates.values()) + [midia_id, modelo_id]
    result = await conn.execute(
        f"""
        UPDATE barravips.modelo_midia
           SET {set_sql}
         WHERE id = %s AND modelo_id = %s
        RETURNING *
        """,
        params,
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Midia")
    return cast(dict[str, Any], row)


@router.delete("/{modelo_id}/midia/{midia_id}", status_code=204)
async def deletar_midia(
    modelo_id: UUID,
    midia_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await conn.execute(
        "DELETE FROM barravips.modelo_midia WHERE id = %s AND modelo_id = %s",
        (midia_id, modelo_id),
    )


async def _ensure_modelo(conn: AsyncConnection[Any], modelo_id: UUID) -> None:
    if await _one(conn, "SELECT 1 FROM barravips.modelos WHERE id = %s", (modelo_id,)) is None:
        raise NaoEncontrado("Modelo")


async def _midia(conn: AsyncConnection[Any], request: Request, modelo_id: UUID) -> list[dict[str, Any]]:
    rows = await _all(
        conn,
        "SELECT * FROM barravips.modelo_midia WHERE modelo_id = %s ORDER BY created_at DESC",
        (modelo_id,),
    )
    for row in rows:
        row["url_assinada"] = presigned_get(
            getattr(request.app.state, "minio", None),
            row["bucket"],
            row["object_key"],
        )
    return rows


def _validar_prefixo_midia(modelo_id: UUID, object_key: str) -> None:
    prefixo = f"modelos/{modelo_id}/midia/"
    if not object_key.startswith(prefixo):
        raise EntradaInvalida(
            "MIDIA_NAMESPACE_INVALIDO",
            "object_key fora do namespace da modelo.",
            {"prefixo_esperado": prefixo},
        )
    if ".." in PurePosixPath(object_key).parts:
        raise EntradaInvalida("MIDIA_NAMESPACE_INVALIDO", "object_key invalido.")


async def _one(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _all(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())
