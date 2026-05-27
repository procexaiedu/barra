"""Job ARQ `validar_pix` (06 §2.2 + §0 emendas grilling 2026-05-23).

Pipeline: baixa o comprovante do MinIO -> OpenRouter vision com response_format json_schema
-> compara plausibilidade/valor/chave/titular -> persiste em `comprovantes_pix` -> aplica
`atualizar_pix` pela porta unica de `escaladas.service` (que avanca o atendimento para
`Confirmado` + `ia_pausada` em ambos os branches) -> enfileira o card no grupo de
Coordenacao por modelo.

O fluxo **nunca trava por Pix** (01 §6.1): validado E em_revisao levam o atendimento adiante;
a duvidez de em_revisao e informativa (sinaliza no card a modelo e cai na fila de revisao
assincrona de Fernando no painel).

Sem `timestamp` (emenda §0 item 11: skew BRT/UTC marca falso quase tudo, e sendo nao-bloqueante
so gerava ruido). Sem fallback a `media_url` da Evolution (emenda §0 item 2: a URL expira; a
midia ja foi subida pro MinIO pelo webhook fino).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from decimal import Decimal
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from barra.core.metrics import (
    PIX_DIVERGENCIA,
    PIX_VALIDACAO_DECISAO,
    PIX_VALIDACAO_DURACAO,
)
from barra.dominio.escaladas.service import aplicar_comando

logger = logging.getLogger(__name__)


# --- Schema de saida do vision -----------------------------------------------
# `extra="forbid"` <-> JSON Schema `additionalProperties:false` (06 §0 ressalva 4a +
# cruzamento doc oficial 24-05): sem isso o roteamento dinamico do OpenRouter pode aceitar
# campos extras silenciosamente.
class ExtracaoPix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valor: Decimal | None = Field(
        None, description="Valor pago em BRL, com 2 decimais."
    )
    chave_pix_destinatario: str | None = Field(
        None, description="Chave Pix do beneficiario (CPF, email, telefone, aleatoria)."
    )
    titular_destinatario: str | None = Field(
        None, description="Nome do titular do beneficiario."
    )
    banco_origem: str | None = Field(
        None, description="Banco emissor do pagamento."
    )
    plausibilidade_visual: bool = Field(
        description=(
            "True se a imagem parece um comprovante real; False se suspeita "
            "(montagem, screenshot de outro app, recibo manuscrito)."
        )
    )
    motivo_se_implausivel: str | None = Field(
        None,
        description="Motivo curto quando plausibilidade_visual=False; vazio caso contrario.",
    )


PROMPT_PIX = """Voce e um extrator de dados de comprovantes Pix brasileiros.

Analise a imagem do comprovante. Para cada campo:
- Deixe NULL se nao estiver legivel ou nao aparecer.
- plausibilidade_visual=false se: imagem foi claramente editada, screenshot de outro app que nao e banco/Pix, recibo manuscrito, montagem digital evidente.
- valor SEMPRE com 2 casas decimais.
"""


# --- Helpers ----------------------------------------------------------------
def _detectar_mime_imagem(dados: bytes) -> str:
    """Mime por magic bytes (06 §2.4). Cobre os 4 formatos que o vision aceita."""
    if dados[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    if dados[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _chaves_compativeis(extraida: str, esperada: str) -> bool:
    """Compara chaves Pix com tolerancia (espacos, pontuacao) (06 §2.4)."""
    def _norm(s: str) -> str:
        return re.sub(r"[\s.\-+()/]", "", s).lower()
    return _norm(extraida) == _norm(esperada)


def _titulares_compativeis(extraido: str, esperado: str) -> bool:
    """Match parcial: primeiro nome + ultimo sobrenome (06 §2.4)."""
    e_tokens = extraido.lower().split()
    es_tokens = esperado.lower().split()
    if not e_tokens or not es_tokens:
        return False
    return e_tokens[0] == es_tokens[0] and e_tokens[-1] == es_tokens[-1]


async def _baixar_minio(minio: Any, bucket: str, key: str) -> bytes:
    """`minio.get_object` e sincrono — roda em executor (mesmo padrao de `_upload_minio`)."""
    loop = asyncio.get_running_loop()

    def _ler() -> bytes:
        resp = minio.get_object(bucket, key)
        try:
            return cast(bytes, resp.read())
        finally:
            resp.close()
            resp.release_conn()

    return await loop.run_in_executor(None, _ler)


async def _extrair_via_openrouter(
    bytes_img: bytes,
    *,
    media_type: str,
    client: AsyncOpenAI,
    modelo: str,
) -> ExtracaoPix:
    """OpenRouter via SDK OpenAI-compativel + response_format json_schema (06 §0 item 4).

    `provider.require_parameters=true` (ressalva 4a): sem isso o roteamento dinamico pode
    cair num provider que ignora o json_schema. Imagem ANTES do texto (ressalva ordem
    image-then-text + cruzamento vision.md 24-05).
    """
    b64 = base64.standard_b64encode(bytes_img).decode("ascii")
    schema = ExtracaoPix.model_json_schema()
    resposta = await client.chat.completions.create(
        model=modelo,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "ExtracaoPix",
                "schema": schema,
                "strict": True,
            },
        },
        extra_body={"provider": {"require_parameters": True}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"},
                    },
                    {"type": "text", "text": PROMPT_PIX},
                ],
            }
        ],
        max_tokens=800,
    )
    conteudo = resposta.choices[0].message.content
    if not conteudo:
        raise ValueError("vision retornou content vazio")
    return ExtracaoPix.model_validate_json(conteudo)


# --- Job principal ----------------------------------------------------------
async def validar_pix(
    ctx: dict[str, Any],
    *,
    mensagem_id: str,
    atendimento_id: str,
) -> None:
    """Valida o comprovante de uma mensagem ja persistida no MinIO.

    Assinatura enxuta (06 §0 item 2): nada de `media_url` — a midia ja esta no MinIO via
    webhook fino; o worker le `media_object_key` em `mensagens` e baixa de la.
    """
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    settings = ctx["settings"]
    vision_client: AsyncOpenAI = ctx["vision_client"]

    inicio = perf_counter()
    try:
        # 1. busca object_key da mensagem + expectativas (chave/titular) da modelo
        async with pool.connection() as conn:
            res = await conn.execute(
                """
                SELECT m.media_object_key,
                       mo.chave_pix     AS chave_pix_modelo,
                       mo.titular_chave AS titular_modelo
                  FROM barravips.mensagens m
                  JOIN barravips.atendimentos a ON a.id = %s
                  JOIN barravips.modelos     mo ON mo.id = a.modelo_id
                 WHERE m.id = %s
                """,
                (UUID(atendimento_id), UUID(mensagem_id)),
            )
            ctx_row = await res.fetchone()
        if ctx_row is None or not ctx_row["media_object_key"]:
            logger.error(
                "validar_pix sem media_object_key mensagem_id=%s atendimento_id=%s",
                mensagem_id,
                atendimento_id,
            )
            return

        object_key: str = ctx_row["media_object_key"]
        chave_modelo: str | None = ctx_row["chave_pix_modelo"]
        titular_modelo: str | None = ctx_row["titular_modelo"]

        # 2. baixa do MinIO + detecta mime real (nao confiar na extensao da URL Evolution)
        bytes_img = await _baixar_minio(minio, settings.minio_bucket_media, object_key)
        media_type = _detectar_mime_imagem(bytes_img)

        # 3. vision
        extracao = await _extrair_via_openrouter(
            bytes_img,
            media_type=media_type,
            client=vision_client,
            modelo=settings.openrouter_model_vision_pix or "anthropic/claude-sonnet-4.6",
        )

        # 4. comparacoes (sem timestamp, emenda §0 item 11)
        motivo_em_revisao: str | None = None
        motivo_bucket: str | None = None
        if not extracao.plausibilidade_visual:
            motivo_em_revisao = (
                f"plausibilidade visual: {extracao.motivo_se_implausivel or 'imagem suspeita'}"
            )
            motivo_bucket = "plausibilidade"
        elif extracao.valor is None or extracao.valor < settings.pix_deslocamento_valor:
            motivo_em_revisao = (
                f"valor extraido {extracao.valor} < esperado R${settings.pix_deslocamento_valor}"
            )
            motivo_bucket = "valor"
        elif (
            chave_modelo
            and extracao.chave_pix_destinatario
            and not _chaves_compativeis(extracao.chave_pix_destinatario, chave_modelo)
        ):
            motivo_em_revisao = (
                f"chave divergente: extraida {extracao.chave_pix_destinatario}, "
                f"esperada {chave_modelo}"
            )
            motivo_bucket = "chave"
        elif (
            titular_modelo
            and extracao.titular_destinatario
            and not _titulares_compativeis(extracao.titular_destinatario, titular_modelo)
        ):
            motivo_em_revisao = f"titular divergente: extraido {extracao.titular_destinatario}"
            motivo_bucket = "titular"

        decisao_pipeline = "validado" if motivo_em_revisao is None else "em_revisao"

        # 5. persiste comprovante + aplica via porta unica de `escaladas.service`. timestamp_extraido
        # gravado como NULL (drop §0 item 11). aplicar_comando avanca o atendimento para Confirmado
        # + ia_pausada=true em ambos os branches (07 §5, ja implementado).
        async with pool.connection() as conn, conn.transaction():
            inserido = await conn.execute(
                """
                INSERT INTO barravips.comprovantes_pix
                  (atendimento_id, mensagem_id, valor_extraido, chave_extraida, titular_extraido,
                   timestamp_extraido, decisao_pipeline, motivo_em_revisao)
                VALUES (%s, %s, %s, %s, %s, NULL, %s, %s)
                RETURNING id
                """,
                (
                    UUID(atendimento_id),
                    UUID(mensagem_id),
                    extracao.valor,
                    extracao.chave_pix_destinatario,
                    extracao.titular_destinatario,
                    decisao_pipeline,
                    motivo_em_revisao,
                ),
            )
            row_id = await inserido.fetchone()
            comprovante_id = row_id["id"]

            await aplicar_comando(
                conn,
                origem="pipeline_pix",
                autor="sistema",
                atendimento_id=UUID(atendimento_id),
                comando="atualizar_pix",
                payload={"decisao": decisao_pipeline, "motivo": motivo_em_revisao},
            )

        # 6. metricas + card
        PIX_VALIDACAO_DECISAO.labels(decisao_pipeline).inc()
        if motivo_bucket is not None:
            PIX_DIVERGENCIA.labels(motivo_bucket).inc()

        redis = ctx["redis"]
        await redis.enqueue_job(
            "enviar_card",
            tipo="pix_validado" if decisao_pipeline == "validado" else "pix_em_revisao",
            atendimento_id=str(atendimento_id),
            comprovante_id=str(comprovante_id),
            _job_id=f"card:pix:{atendimento_id}",
        )
        logger.info(
            "validar_pix decisao=%s atendimento_id=%s motivo=%s",
            decisao_pipeline,
            atendimento_id,
            motivo_em_revisao,
        )
    finally:
        PIX_VALIDACAO_DURACAO.observe(perf_counter() - inicio)


__all__ = [
    "ExtracaoPix",
    "_chaves_compativeis",
    "_detectar_mime_imagem",
    "_titulares_compativeis",
    "validar_pix",
]
