import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Query, Request
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import ConflitoEstado, EntradaInvalida, NaoEncontrado
from barra.core.evolution import EvolutionClient
from barra.core.storage import presigned_get, presigned_put, remove_object
from barra.dominio.modelos.schemas import (
    AtualizarPrecoProgramaBody,
    ConectarWhatsappRequest,
    FotoPerfilPatch,
    MidiaCreate,
    MidiaPatch,
    MidiaUploadUrlRequest,
    ModeloCreate,
    ModeloPatch,
    ServicoBody,
    VincularProgramaBody,
)

router = APIRouter(dependencies=[Depends(get_user)])
PERSONA_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "agente" / "prompts" / "persona.md"
_logger = logging.getLogger(__name__)


@router.get("")
async def listar_modelos(
    request: Request,
    status: str | None = None,
    evolution: str | None = None,
    tipo: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    filtros: list[str] = []
    params: list[Any] = []

    if status:
        filtros.append("m.status = %s")
        params.append(status)
    if evolution == "pareada":
        filtros.append("m.evolution_instance_id IS NOT NULL")
    elif evolution == "nao_pareada":
        filtros.append("m.evolution_instance_id IS NULL")
    if tipo:
        filtros.append("%s::barravips.tipo_atendimento_enum = ANY(m.tipo_atendimento_aceito)")
        params.append(tipo)
    if q:
        termo = q.strip().lower()
        digitos = "".join(ch for ch in termo if ch.isdigit())
        filtros.append(
            """
            (
              lower(m.nome) LIKE %s
              OR regexp_replace(m.numero_whatsapp, '\\D', '', 'g') LIKE %s
              OR lower(coalesce(m.localizacao_operacional, '')) LIKE %s
            )
            """
        )
        params.extend([f"{termo}%", f"{digitos}%" if digitos else "___sem_numero___", f"{termo}%"])
    if cursor:
        filtros.append("m.created_at > %s::timestamptz")
        params.append(cursor)

    where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    result = await conn.execute(
        f"""
        SELECT m.*,
               coalesce(a.atendimentos_abertos, 0) AS atendimentos_abertos,
               coalesce(a.conversas_ia_pausada, 0) AS conversas_ia_pausada,
               e.ultimo_handoff_em
          FROM barravips.modelos m
          LEFT JOIN LATERAL (
            SELECT count(*) FILTER (WHERE estado NOT IN ('Fechado', 'Perdido')) AS atendimentos_abertos,
                   count(*) FILTER (
                     WHERE estado NOT IN ('Fechado', 'Perdido') AND ia_pausada = true
                   ) AS conversas_ia_pausada
              FROM barravips.atendimentos a
             WHERE a.modelo_id = m.id
          ) a ON true
          LEFT JOIN LATERAL (
            SELECT max(es.aberta_em) AS ultimo_handoff_em
              FROM barravips.escaladas es
              JOIN barravips.atendimentos at ON at.id = es.atendimento_id
             WHERE at.modelo_id = m.id
          ) e ON true
          {where_sql}
         ORDER BY CASE m.status WHEN 'ativa' THEN 0 WHEN 'pausada' THEN 1 ELSE 2 END,
                  m.created_at ASC
         LIMIT %s
        """,
        [*params, limit + 1],
    )
    rows = list(await result.fetchall())
    page = rows[:limit]
    return {
        "items": [_modelo_lista_item(request, row) for row in page],
        "next_cursor": rows[limit]["created_at"].isoformat() if len(rows) > limit else None,
    }


@router.post("", status_code=201)
async def criar_modelo(
    body: ModeloCreate,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await conn.execute(
        """
        INSERT INTO barravips.modelos (
          nome, idade, numero_whatsapp, valor_padrao, percentual_repasse, chave_pix,
          titular_chave, idiomas, localizacao_operacional,
          endereco_formatado, latitude, longitude, place_id,
          tipo_atendimento_aceito
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            body.endereco_formatado,
            body.latitude,
            body.longitude,
            body.place_id,
            body.tipo_atendimento_aceito,
        ),
    )
    row = await result.fetchone()
    assert row is not None
    return _modelo_com_foto(request, cast(dict[str, Any], row))


@router.get("/{modelo_id}")
async def obter_modelo(
    modelo_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    modelo = await _modelo(conn, modelo_id)
    midia = await _midia(conn, request, modelo_id)
    programas = await _programas(conn, modelo_id)
    indicadores = await _indicadores(conn, modelo_id)
    return {
        "modelo": _modelo_com_foto(request, modelo),
        "midia": midia,
        "programas": programas,
        "evolution": _evolution_payload(modelo),
        "indicadores": indicadores,
    }


@router.patch("/{modelo_id}")
async def editar_modelo(
    modelo_id: UUID,
    body: ModeloPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    atual = await _modelo(conn, modelo_id)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return atual

    if updates.get("status") == "inativa" and atual["evolution_instance_id"]:
        numero_mudou = "numero_whatsapp" in updates and updates["numero_whatsapp"] != atual["numero_whatsapp"]
        if not numero_mudou:
            raise ConflitoEstado("Despareie a Evolution antes de inativar")

    if "numero_whatsapp" in updates and updates["numero_whatsapp"] != atual["numero_whatsapp"]:
        updates["evolution_instance_id"] = None
        updates["evolution_status"] = "desconectado"
        updates["evolution_pareado_em"] = None

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
    modelo = await _modelo(conn, modelo_id)
    if (
        modelo["evolution_instance_id"]
        and modelo["evolution_status"] == "conectado"
        and not body.confirmar_rotacao
    ):
        return {
            "status": "conectado",
            "instance_id": modelo["evolution_instance_id"],
            "qr_code": None,
        }

    instance_id = modelo["evolution_instance_id"] or f"modelo-{modelo_id}"
    client = EvolutionClient(request.app.state.settings)
    # Idempotente: se a instância ainda não existe na Evolution, criamos com o
    # webhook já apontado para nosso backend. Se já existir, segue direto.
    try:
        await client.criar_instancia(instance_id, numero=modelo.get("numero_whatsapp"))
        resposta = await client.conectar_instancia(instance_id)
    except httpx.HTTPStatusError as exc:
        raise ConflitoEstado(
            f"Evolution recusou a conexão (HTTP {exc.response.status_code}). "
            "Verifique a chave da Evolution e o status da instância."
        ) from exc
    qr_code = _extrair_qr_code(resposta)
    await conn.execute(
        """
        UPDATE barravips.modelos
           SET evolution_instance_id = %s,
               evolution_status = 'pareando',
               evolution_pareado_em = NULL
         WHERE id = %s
        """,
        (instance_id, modelo_id),
    )
    return {"status": "pareando", "instance_id": instance_id, "qr_code": qr_code}


@router.post("/{modelo_id}/desparear-whatsapp")
async def desparear_whatsapp(
    modelo_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    modelo = await _modelo(conn, modelo_id)
    instance_id = modelo["evolution_instance_id"]
    if instance_id:
        client = EvolutionClient(request.app.state.settings)
        # Best-effort: se a Evolution recusar o logout, ainda zeramos o estado
        # local. O ghost de sessão fica para o operador resolver via painel da
        # Evolution; a próxima conexão por aqui faz POST /instance/create de
        # novo e sobrescreve o estado remoto.
        await client.logout_instancia(instance_id)
    await conn.execute(
        """
        UPDATE barravips.modelos
           SET evolution_instance_id = NULL,
               evolution_status = 'desconectado',
               evolution_pareado_em = NULL
         WHERE id = %s
        """,
        (modelo_id,),
    )
    return {
        "modelo_id": str(modelo_id),
        "evolution_instance_id": None,
        "evolution_status": "desconectado",
    }


@router.get("/{modelo_id}/whatsapp/status")
async def whatsapp_status(
    modelo_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    """Status de pareamento. Faz auto-cure: se o DB diz 'pareando' mas a
    Evolution já reporta 'open', promove para 'conectado' aqui (cobre o caso
    em que o webhook CONNECTION_UPDATE não chegou — ex: dev sem tunnel)."""
    modelo = await _modelo(conn, modelo_id)
    instance_id = modelo["evolution_instance_id"]
    status_atual = modelo["evolution_status"]

    if status_atual == "pareando" and instance_id:
        client = EvolutionClient(request.app.state.settings)
        try:
            estado = await client.estado_conexao(instance_id)
        except httpx.HTTPError:
            estado = "unknown"
        if estado == "open":
            await conn.execute(
                """
                UPDATE barravips.modelos
                   SET evolution_status = 'conectado',
                       evolution_pareado_em = now()
                 WHERE id = %s
                """,
                (modelo_id,),
            )
            modelo = await _modelo(conn, modelo_id)

    return _evolution_payload(modelo)


@router.post("/{modelo_id}/pausar")
async def pausar_modelo(
    modelo_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        modelo = await _modelo(conn, modelo_id, for_update=True)
        if modelo["status"] != "ativa":
            raise ConflitoEstado("Modelo nao esta ativa.")

        conversas_pausadas = await _count(
            conn,
            """
            SELECT count(*) FROM barravips.atendimentos
             WHERE modelo_id = %s
               AND estado NOT IN ('Fechado', 'Perdido')
               AND ia_pausada = false
            """,
            (modelo_id,),
        )
        em_execucao = await _count(
            conn,
            """
            SELECT count(*) FROM barravips.atendimentos
             WHERE modelo_id = %s AND estado = 'Em_execucao'
            """,
            (modelo_id,),
        )
        await conn.execute(
            "UPDATE barravips.modelos SET status = 'pausada' WHERE id = %s",
            (modelo_id,),
        )
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET ia_pausada = true,
                   ia_pausada_motivo = 'modelo_em_atendimento',
                   responsavel_atual = 'modelo'
             WHERE modelo_id = %s
               AND estado NOT IN ('Fechado', 'Perdido')
               AND ia_pausada = false
            """,
            (modelo_id,),
        )
        await _evento_modelo(
            conn,
            "modelo_pausada",
            {
                "modelo_id": str(modelo_id),
                "conversas_pausadas": conversas_pausadas,
                "em_execucao_em_curso": em_execucao,
            },
        )
        card_enviado = await _enviar_card_pausa(conn, request, modelo, conversas_pausadas, em_execucao)

    return {
        "modelo_id": str(modelo_id),
        "status": "pausada",
        "conversas_pausadas": conversas_pausadas,
        "em_execucao_em_curso": em_execucao,
        "card_enviado": card_enviado,
    }


@router.post("/{modelo_id}/ativar")
async def ativar_modelo(
    modelo_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        modelo = await _modelo(conn, modelo_id, for_update=True)
        if modelo["status"] == "ativa":
            raise ConflitoEstado("Modelo ja esta ativa.")
        if modelo["status"] == "inativa":
            raise ConflitoEstado("Modelo inativa nao pode ser reativada por este fluxo.")

        await conn.execute(
            "UPDATE barravips.modelos SET status = 'ativa' WHERE id = %s",
            (modelo_id,),
        )
        pendentes = await _count(
            conn,
            """
            SELECT count(*) FROM barravips.atendimentos
             WHERE modelo_id = %s
               AND estado NOT IN ('Fechado', 'Perdido')
               AND ia_pausada = true
               AND ia_pausada_motivo = 'modelo_em_atendimento'
            """,
            (modelo_id,),
        )
        await _evento_modelo(
            conn,
            "modelo_reativada",
            {"modelo_id": str(modelo_id), "conversas_pausadas_pendentes": pendentes},
        )
    return {
        "modelo_id": str(modelo_id),
        "status": "ativa",
        "conversas_pausadas_pendentes": pendentes,
    }


@router.post("/{modelo_id}/coordenacao/verificar")
async def verificar_coordenacao(
    modelo_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    modelo = await _modelo(conn, modelo_id)
    if not modelo.get("coordenacao_chat_id"):
        raise EntradaInvalida("COORDENACAO_AUSENTE", "Grupo de Coordenacao nao vinculado.")
    if not modelo["evolution_instance_id"]:
        return {"ok": False, "motivo": "Evolution nao pareada.", "membros": []}

    settings = request.app.state.settings
    if not settings.evolution_base_url:
        return {"ok": False, "motivo": "Evolution nao configurada.", "membros": []}
    if not settings.evolution_fernando_jids:
        return {"ok": False, "motivo": "Numero do Fernando nao configurado.", "membros": []}

    client = EvolutionClient(settings)
    try:
        info = await client.buscar_grupo_info(modelo["evolution_instance_id"], modelo["coordenacao_chat_id"])
    except httpx.HTTPError:
        return {"ok": False, "motivo": "Grupo inexistente ou instancia offline.", "membros": []}

    membros = _extrair_membros(info)
    ok = _grupo_tem_membros_esperados(membros, modelo["numero_whatsapp"], settings.evolution_fernando_jids)
    if ok:
        await conn.execute(
            "UPDATE barravips.modelos SET coordenacao_verificada_em = now() WHERE id = %s",
            (modelo_id,),
        )
    return {
        "ok": ok,
        "motivo": None if ok else "Grupo deve conter exatamente Fernando e o numero da modelo.",
        "membros": membros,
    }


@router.post("/{modelo_id}/foto-perfil/upload-url")
async def criar_upload_url_foto_perfil(
    modelo_id: UUID,
    body: MidiaUploadUrlRequest,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    await _ensure_modelo(conn, modelo_id)
    filename = PurePosixPath(body.filename).name
    object_key = f"modelos/{modelo_id}/perfil/{uuid4()}/{filename}"
    upload_url = presigned_put(
        getattr(request.app.state, "minio", None),
        request.app.state.settings.minio_bucket_media,
        object_key,
    )
    return {"object_key": object_key, "upload_url": upload_url, "expires_in": 900}


@router.patch("/{modelo_id}/foto-perfil")
async def atualizar_foto_perfil(
    modelo_id: UUID,
    body: FotoPerfilPatch,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    _validar_prefixo_perfil(modelo_id, body.object_key)
    result = await conn.execute(
        """
        UPDATE barravips.modelos
           SET foto_perfil_object_key = %s
         WHERE id = %s
        RETURNING *
        """,
        (body.object_key, modelo_id),
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Modelo")
    return _modelo_com_foto(request, cast(dict[str, Any], row))


@router.delete("/{modelo_id}/foto-perfil", status_code=204)
async def remover_foto_perfil(
    modelo_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await _ensure_modelo(conn, modelo_id)
    await conn.execute(
        "UPDATE barravips.modelos SET foto_perfil_object_key = NULL WHERE id = %s",
        (modelo_id,),
    )


@router.get("/{modelo_id}/prompt-preview")
async def prompt_preview(
    modelo_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    modelo = await _modelo(conn, modelo_id)
    template = await asyncio.to_thread(_ler_persona_template)
    idiomas = _array_text(modelo["idiomas"])
    tipos = _array_text(modelo["tipo_atendimento_aceito"])
    # Campos geocodificados (endereco_formatado/latitude/longitude/place_id) já são
    # persistidos pelo Places Autocomplete na UI mas ainda NÃO entram no prompt.
    # Ao implementar a ferramenta `enviar_localizacao` do agente, expor:
    #   - endereco_formatado: descrição completa que a IA cita no texto.
    #   - latitude/longitude: payload do envio de localização via Evolution
    #     (`/message/sendLocation`) no fluxo INTERNO de `Aguardando_confirmacao`.
    # `localizacao_operacional` segue como "bairro, cidade" curto p/ fluxo EXTERNO.
    texto = "\n".join(
        [
            template.rstrip(),
            "",
            "## Campos estruturados da modelo",
            f"- Nome: {modelo['nome']}",
            f"- Idade: {modelo['idade']}",
            f"- Idiomas: {', '.join(idiomas)}",
            f"- Localizacao operacional: {modelo['localizacao_operacional'] or 'nao informada'}",
            f"- Tipos de atendimento aceitos: {', '.join(tipos)}",
        ]
    )
    return {"texto": texto, "gerado_em": datetime.now(UTC).isoformat()}


@router.get("/{modelo_id}/servicos")
async def listar_servicos(
    modelo_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    await _ensure_modelo(conn, modelo_id)
    return await _servicos(conn, modelo_id)


@router.post("/{modelo_id}/servicos", status_code=201)
async def criar_servico(
    modelo_id: UUID,
    body: ServicoBody,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    await _ensure_modelo(conn, modelo_id)
    result = await conn.execute(
        """
        INSERT INTO barravips.modelo_servicos (modelo_id, nome, duracao_horas, preco, ativo, ordem)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (modelo_id, body.nome.strip(), body.duracao_horas, body.preco, body.ativo, body.ordem),
    )
    row = await result.fetchone()
    assert row is not None
    return cast(dict[str, Any], row)


@router.patch("/{modelo_id}/servicos/{servico_id}")
async def editar_servico(
    modelo_id: UUID,
    servico_id: UUID,
    body: ServicoBody,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    await _ensure_modelo(conn, modelo_id)
    result = await conn.execute(
        """
        UPDATE barravips.modelo_servicos
           SET nome = %s,
               duracao_horas = %s,
               preco = %s,
               ativo = %s,
               ordem = %s
         WHERE id = %s AND modelo_id = %s
        RETURNING *
        """,
        (body.nome.strip(), body.duracao_horas, body.preco, body.ativo, body.ordem, servico_id, modelo_id),
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Servico")
    return _serializar_servico(cast(dict[str, Any], row))


@router.delete("/{modelo_id}/servicos/{servico_id}", status_code=204)
async def deletar_servico(
    modelo_id: UUID,
    servico_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await _ensure_modelo(conn, modelo_id)
    await conn.execute(
        "DELETE FROM barravips.modelo_servicos WHERE id = %s AND modelo_id = %s",
        (servico_id, modelo_id),
    )


@router.get("/{modelo_id}/programas")
async def listar_programas_modelo(
    modelo_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    await _ensure_modelo(conn, modelo_id)
    return await _programas(conn, modelo_id)


@router.post("/{modelo_id}/programas", status_code=201)
async def vincular_programa(
    modelo_id: UUID,
    body: VincularProgramaBody,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    await _ensure_modelo(conn, modelo_id)
    programa = await _one(conn, "SELECT * FROM barravips.programas WHERE id = %s", (body.programa_id,))
    if programa is None:
        raise NaoEncontrado("Programa")
    duracao = await _one(conn, "SELECT * FROM barravips.duracoes WHERE id = %s", (body.duracao_id,))
    if duracao is None:
        raise NaoEncontrado("Duração")
    result = await conn.execute(
        """
        INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (modelo_id, programa_id, duracao_id) DO UPDATE SET preco = EXCLUDED.preco
        RETURNING *
        """,
        (modelo_id, body.programa_id, body.duracao_id, body.preco),
    )
    row = await result.fetchone()
    assert row is not None
    return _serializar_vinculo(row, programa, duracao)


@router.patch("/{modelo_id}/programas/{programa_id}/duracoes/{duracao_id}")
async def atualizar_preco_programa(
    modelo_id: UUID,
    programa_id: UUID,
    duracao_id: UUID,
    body: AtualizarPrecoProgramaBody,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    await _ensure_modelo(conn, modelo_id)
    result = await conn.execute(
        """
        UPDATE barravips.modelo_programas SET preco = %s
         WHERE modelo_id = %s AND programa_id = %s AND duracao_id = %s
        RETURNING *
        """,
        (body.preco, modelo_id, programa_id, duracao_id),
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Vínculo programa-modelo")
    programa = await _one(conn, "SELECT * FROM barravips.programas WHERE id = %s", (programa_id,))
    duracao = await _one(conn, "SELECT * FROM barravips.duracoes WHERE id = %s", (duracao_id,))
    assert programa is not None and duracao is not None
    return _serializar_vinculo(row, programa, duracao)


@router.delete("/{modelo_id}/programas/{programa_id}/duracoes/{duracao_id}", status_code=204)
async def desvincular_programa(
    modelo_id: UUID,
    programa_id: UUID,
    duracao_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await _ensure_modelo(conn, modelo_id)
    await conn.execute(
        "DELETE FROM barravips.modelo_programas WHERE modelo_id = %s AND programa_id = %s AND duracao_id = %s",
        (modelo_id, programa_id, duracao_id),
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
    await _ensure_modelo(conn, modelo_id)
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
    tipo: str | None = None,
    tag: str | None = None,
    aprovada: bool | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await _midia(conn, request, modelo_id, tipo=tipo, tag=tag, aprovada=aprovada)


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
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    result = await conn.execute(
        """
        DELETE FROM barravips.modelo_midia
         WHERE id = %s AND modelo_id = %s
        RETURNING bucket, object_key
        """,
        (midia_id, modelo_id),
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Midia")

    minio = getattr(request.app.state, "minio", None)
    if minio is not None:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: remove_object(minio, row["bucket"], row["object_key"])
            )
        except Exception as exc:
            _logger.warning(
                "falha_remover_minio bucket=%s key=%s erro=%s",
                row["bucket"], row["object_key"], exc,
            )


async def _modelo(
    conn: AsyncConnection[Any],
    modelo_id: UUID,
    *,
    for_update: bool = False,
) -> dict[str, Any]:
    lock = " FOR UPDATE" if for_update else ""
    row = await _one(conn, f"SELECT * FROM barravips.modelos WHERE id = %s{lock}", (modelo_id,))
    if row is None:
        raise NaoEncontrado("Modelo")
    return row


async def _ensure_modelo(conn: AsyncConnection[Any], modelo_id: UUID) -> None:
    await _modelo(conn, modelo_id)


async def _midia(
    conn: AsyncConnection[Any],
    request: Request,
    modelo_id: UUID,
    *,
    tipo: str | None = None,
    tag: str | None = None,
    aprovada: bool | None = None,
) -> list[dict[str, Any]]:
    filtros = ["modelo_id = %s"]
    params: list[Any] = [modelo_id]
    if tipo:
        filtros.append("tipo = %s")
        params.append(tipo)
    if tag:
        filtros.append("tag = %s")
        params.append(tag)
    if aprovada is not None:
        filtros.append("aprovada = %s")
        params.append(aprovada)
    rows = await _all(
        conn,
        f"""
        SELECT * FROM barravips.modelo_midia
         WHERE {' AND '.join(filtros)}
         ORDER BY created_at DESC
        """,
        tuple(params),
    )
    for row in rows:
        row["url_assinada"] = presigned_get(
            getattr(request.app.state, "minio", None),
            row["bucket"],
            row["object_key"],
        )
    return rows


async def _programas(conn: AsyncConnection[Any], modelo_id: UUID) -> list[dict[str, Any]]:
    rows = await _all(
        conn,
        """
        SELECT mp.programa_id, mp.duracao_id, mp.preco,
               p.nome, p.categoria,
               d.nome AS duracao_nome, d.ordem AS duracao_ordem
          FROM barravips.modelo_programas mp
          JOIN barravips.programas p ON p.id = mp.programa_id
          JOIN barravips.duracoes d ON d.id = mp.duracao_id
         WHERE mp.modelo_id = %s
         ORDER BY p.categoria NULLS FIRST, p.nome ASC, d.ordem ASC
        """,
        (modelo_id,),
    )
    return [
        {
            "programa_id": str(row["programa_id"]),
            "duracao_id": str(row["duracao_id"]),
            "nome": row["nome"],
            "categoria": row["categoria"],
            "duracao_nome": row["duracao_nome"],
            "preco": float(row["preco"]),
        }
        for row in rows
    ]


def _serializar_vinculo(
    vinculo: dict[str, Any], programa: dict[str, Any], duracao: dict[str, Any]
) -> dict[str, Any]:
    return {
        "programa_id": str(vinculo["programa_id"]),
        "duracao_id": str(vinculo["duracao_id"]),
        "nome": programa["nome"],
        "categoria": programa["categoria"],
        "duracao_nome": duracao["nome"],
        "preco": float(vinculo["preco"]),
    }


async def _servicos(conn: AsyncConnection[Any], modelo_id: UUID) -> list[dict[str, Any]]:
    rows = await _all(
        conn,
        """
        SELECT * FROM barravips.modelo_servicos
         WHERE modelo_id = %s
         ORDER BY ordem ASC, duracao_horas ASC, preco ASC
        """,
        (modelo_id,),
    )
    return [_serializar_servico(row) for row in rows]


def _serializar_servico(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "modelo_id": str(row["modelo_id"]),
        "nome": row["nome"],
        "duracao_horas": float(row["duracao_horas"]),
        "preco": float(row["preco"]),
        "ativo": row["ativo"],
        "ordem": row["ordem"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def _indicadores(conn: AsyncConnection[Any], modelo_id: UUID) -> dict[str, Any]:
    result = await conn.execute(
        """
        SELECT count(*) FILTER (WHERE a.estado NOT IN ('Fechado', 'Perdido')) AS atendimentos_abertos,
               count(*) FILTER (
                 WHERE a.estado NOT IN ('Fechado', 'Perdido') AND a.ia_pausada = true
               ) AS conversas_ia_pausada,
               (
                 SELECT max(es.aberta_em)
                   FROM barravips.escaladas es
                   JOIN barravips.atendimentos at ON at.id = es.atendimento_id
                  WHERE at.modelo_id = %s
               ) AS ultimo_handoff_em
          FROM barravips.atendimentos a
         WHERE a.modelo_id = %s
        """,
        (modelo_id, modelo_id),
    )
    row = await result.fetchone()
    assert row is not None
    return {
        "atendimentos_abertos": row["atendimentos_abertos"],
        "conversas_ia_pausada": row["conversas_ia_pausada"],
        "ultimo_handoff_em": row["ultimo_handoff_em"],
    }


async def _count(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> int:
    result = await conn.execute(query, params)
    row = await result.fetchone()
    assert row is not None
    return int(row["count"])


async def _evento_modelo(conn: AsyncConnection[Any], tipo: str, payload: dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
        VALUES (NULL, %s, 'painel', 'Fernando', %s)
        """,
        (tipo, payload),
    )


async def _enviar_card_pausa(
    conn: AsyncConnection[Any],
    request: Request,
    modelo: dict[str, Any],
    conversas_pausadas: int,
    em_execucao: int,
) -> bool:
    settings = request.app.state.settings
    if not (
        settings.evolution_base_url
        and modelo.get("evolution_instance_id")
        and modelo.get("coordenacao_chat_id")
    ):
        return False
    client = EvolutionClient(settings)
    try:
        await client.enviar_texto(
            conn=conn,
            instance_id=modelo["evolution_instance_id"],
            remote_jid=modelo["coordenacao_chat_id"],
            texto=(
                f"Modelo {modelo['nome']} pausada operacionalmente. "
                f"{conversas_pausadas} conversa(s) pausada(s); "
                f"{em_execucao} atendimento(s) em Em_execucao preservado(s)."
            ),
            contexto="grupo_coordenacao",
            tipo="card",
            payload={
                "modelo_id": str(modelo["id"]),
                "conversas_pausadas": conversas_pausadas,
                "em_execucao_em_curso": em_execucao,
            },
        )
    except Exception:
        # A pausa ja foi efetivada no banco; uma falha de envio do card (Evolution
        # offline, timeout, instancia caida) nao pode derrubar a operacao nem rolar
        # a transacao. Logamos para que a coordenacao saiba que nao foi notificada.
        _logger.warning(
            "Falha ao enviar card de pausa da modelo %s para a Coordenacao",
            modelo["id"],
            exc_info=True,
        )
        return False
    return True


def _modelo_lista_item(request: Request, row: dict[str, Any]) -> dict[str, Any]:
    item = _modelo_com_foto(request, row)
    return {
        "id": item["id"],
        "nome": item["nome"],
        "numero_whatsapp": item["numero_whatsapp"],
        "status": item["status"],
        "evolution_instance_id": item["evolution_instance_id"],
        "evolution_status": item.get("evolution_status") or "desconectado",
        "evolution_pareado_em": _isoformat(item.get("evolution_pareado_em")),
        "coordenacao_chat_id": item.get("coordenacao_chat_id"),
        "foto_perfil_url": item["foto_perfil_url"],
        "indicadores": {
            "atendimentos_abertos": row["atendimentos_abertos"],
            "conversas_ia_pausada": row["conversas_ia_pausada"],
            "ultimo_handoff_em": row["ultimo_handoff_em"],
        },
    }


def _evolution_payload(modelo: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": modelo.get("evolution_instance_id"),
        "status": modelo.get("evolution_status") or "desconectado",
        "pareado_em": _isoformat(modelo.get("evolution_pareado_em")),
    }


def _extrair_qr_code(resposta: dict[str, Any]) -> str | None:
    """A doc oficial da Evolution v2 lista `pairingCode`/`code`, mas na prática
    a instância retorna o QR em `qrcode` (data URI ou base64 puro) e às vezes
    em `base64`. Aceitamos qualquer variante — o frontend prefixa o data URI
    quando precisa."""
    for chave in ("qrcode", "base64", "code"):
        valor = resposta.get(chave)
        if isinstance(valor, str) and valor:
            return valor
        if isinstance(valor, dict):
            # qrcode pode vir aninhado: {"qrcode": {"base64": "..."}}
            aninhado = valor.get("base64") or valor.get("code")
            if isinstance(aninhado, str) and aninhado:
                return aninhado
    return None


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return cast(str, isoformat())
    return str(value)


def _modelo_com_foto(request: Request, row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["idiomas"] = _array_text(item.get("idiomas"))
    item["tipo_atendimento_aceito"] = _array_text(item.get("tipo_atendimento_aceito"))
    if "evolution_status" in item and item["evolution_status"] is None:
        item["evolution_status"] = "desconectado"
    if "evolution_pareado_em" in item:
        item["evolution_pareado_em"] = _isoformat(item["evolution_pareado_em"])
    object_key = item.get("foto_perfil_object_key")
    item["foto_perfil_url"] = (
        presigned_get(
            getattr(request.app.state, "minio", None),
            request.app.state.settings.minio_bucket_media,
            object_key,
        )
        if object_key
        else None
    )
    return item


def _array_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return []
    cleaned = value.strip()
    if not cleaned:
        return []
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return [item.strip().strip('"') for item in cleaned[1:-1].split(",") if item.strip()]
    return [item.strip() for item in cleaned.split(",") if item.strip()]


def _validar_prefixo_midia(modelo_id: UUID, object_key: str) -> None:
    prefixo = f"modelos/{modelo_id}/midia/"
    _validar_object_key(object_key, prefixo)


def _validar_prefixo_perfil(modelo_id: UUID, object_key: str) -> None:
    prefixo = f"modelos/{modelo_id}/perfil/"
    _validar_object_key(object_key, prefixo)


def _validar_object_key(object_key: str, prefixo: str) -> None:
    if not object_key.startswith(prefixo):
        raise EntradaInvalida(
            "MIDIA_NAMESPACE_INVALIDO",
            "object_key fora do namespace da modelo.",
            {"prefixo_esperado": prefixo},
        )
    if ".." in PurePosixPath(object_key).parts:
        raise EntradaInvalida("MIDIA_NAMESPACE_INVALIDO", "object_key invalido.")


def _extrair_membros(info: dict[str, Any]) -> list[str]:
    data = info.get("data")
    group_metadata = info.get("groupMetadata")
    candidatos = (
        info.get("participants")
        or info.get("participantes")
        or (data.get("participants") if isinstance(data, dict) else None)
        or (group_metadata.get("participants") if isinstance(group_metadata, dict) else None)
        or []
    )
    membros: list[str] = []
    if isinstance(candidatos, list):
        for item in candidatos:
            if isinstance(item, str):
                membros.append(item)
            elif isinstance(item, dict):
                jid = item.get("id") or item.get("jid") or item.get("remoteJid")
                if jid:
                    membros.append(str(jid))
    return membros


def _grupo_tem_membros_esperados(membros: list[str], numero_modelo: str, fernando_jids: list[str]) -> bool:
    if len(membros) != 2:
        return False
    numeros = {_digitos_jid(m) for m in membros}
    return _digitos_jid(numero_modelo) in numeros and any(_digitos_jid(j) in numeros for j in fernando_jids)


def _digitos_jid(valor: str) -> str:
    return "".join(ch for ch in valor.split("@", 1)[0] if ch.isdigit())


def _ler_persona_template() -> str:
    return PERSONA_TEMPLATE_PATH.read_text(encoding="utf-8")


async def _one(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _all(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())
