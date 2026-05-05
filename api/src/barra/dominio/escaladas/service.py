"""Porta unica para comandos operacionais sensiveis."""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.errors import ConflitoEstado, EntradaInvalida, NaoEncontrado

Origem = Literal["painel", "grupo_coordenacao", "pipeline_pix", "cron", "agente"]
Autor = Literal["IA", "Fernando", "modelo", "sistema"]


@dataclass(frozen=True)
class ResultadoComando:
    atendimento_id: UUID
    estado: str
    pix_status: str | None = None


async def aplicar_comando(
    conn: AsyncConnection[Any],
    *,
    origem: Origem,
    autor: Autor,
    atendimento_id: UUID,
    comando: str,
    payload: dict[str, Any],
) -> ResultadoComando:
    async with conn.transaction():
        atendimento = await _buscar_atendimento(conn, atendimento_id)
        if atendimento is None:
            raise NaoEncontrado("Atendimento")

        if comando == "devolver_para_ia":
            return await _devolver_para_ia(conn, atendimento, origem, autor, payload)
        if comando == "registrar_fechado":
            return await _registrar_fechado(conn, atendimento, origem, autor, payload)
        if comando == "registrar_perdido":
            return await _registrar_perdido(conn, atendimento, origem, autor, payload)
        if comando == "corrigir_registro":
            return await _corrigir_registro(conn, atendimento, origem, autor, payload)
        if comando == "atualizar_pix":
            return await _atualizar_pix(conn, atendimento, origem, autor, payload)
        if comando == "comando_invalido":
            await _evento(conn, atendimento_id, "comando_invalido", origem, autor, payload)
            return ResultadoComando(atendimento_id, atendimento["estado"], atendimento["pix_status"])

        raise EntradaInvalida("COMANDO_INVALIDO", "Comando invalido.")


async def _buscar_atendimento(conn: AsyncConnection[Any], atendimento_id: UUID) -> dict[str, Any] | None:
    result = await conn.execute(
        """
        SELECT a.*, m.percentual_repasse
          FROM barravips.atendimentos a
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE a.id = %s
         FOR UPDATE OF a
        """,
        (atendimento_id,),
    )
    return await result.fetchone()


async def _devolver_para_ia(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    if atendimento["estado"] in {"Fechado", "Perdido"}:
        raise ConflitoEstado("Atendimento ja esta finalizado.")
    if not atendimento["ia_pausada"]:
        raise ConflitoEstado("Atendimento nao esta pausado.")

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET ia_pausada = false,
               ia_pausada_motivo = NULL,
               responsavel_atual = 'IA',
               proxima_acao_esperada = NULL,
               motivo_escalada = NULL,
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (_fonte(origem), atendimento["id"]),
    )
    await conn.execute(
        """
        UPDATE barravips.escaladas
           SET fechada_em = now(), fechada_por = %s, fechada_canal = %s
         WHERE atendimento_id = %s AND fechada_em IS NULL
        """,
        (payload.get("usuario_id"), _canal(origem), atendimento["id"]),
    )
    await _evento(conn, atendimento["id"], "devolucao_para_ia", origem, autor, payload)
    return ResultadoComando(atendimento["id"], atendimento["estado"], atendimento["pix_status"])


async def _registrar_fechado(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    valor = payload.get("valor_final")
    if valor is None:
        raise EntradaInvalida("VALOR_FINAL_OBRIGATORIO", "Valor final obrigatorio.", {"campo": "valor_final"})
    if atendimento["estado"] in {"Fechado", "Perdido"}:
        raise ConflitoEstado("Atendimento ja esta finalizado.")

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = 'Fechado',
               valor_final = %s,
               percentual_repasse_snapshot = COALESCE(percentual_repasse_snapshot, %s),
               ia_pausada = false,
               ia_pausada_motivo = NULL,
               responsavel_atual = 'Fernando',
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (Decimal(str(valor)), atendimento["percentual_repasse"], _fonte(origem), atendimento["id"]),
    )
    await _evento(
        conn,
        atendimento["id"],
        "fechado_registrado",
        origem,
        autor,
        {"valor_final": str(valor), **payload},
    )
    await _evento(
        conn,
        atendimento["id"],
        "transicao_estado",
        origem,
        autor,
        {"de": atendimento["estado"], "para": "Fechado"},
    )
    return ResultadoComando(atendimento["id"], "Fechado", atendimento["pix_status"])


async def _registrar_perdido(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    motivo = payload.get("motivo")
    observacao = payload.get("observacao")
    if motivo is None:
        raise EntradaInvalida("MOTIVO_OBRIGATORIO", "Motivo obrigatorio.", {"campo": "motivo"})
    if motivo == "outro" and not observacao:
        raise EntradaInvalida(
            "OBSERVACAO_OBRIGATORIA",
            "Observacao obrigatoria para motivo outro.",
            {"campo": "observacao"},
        )
    if atendimento["estado"] in {"Fechado", "Perdido"}:
        raise ConflitoEstado("Atendimento ja esta finalizado.")

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = 'Perdido',
               motivo_perda = %s,
               motivo_perda_obs = %s,
               ia_pausada = false,
               ia_pausada_motivo = NULL,
               responsavel_atual = 'Fernando',
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (motivo, observacao, _fonte(origem), atendimento["id"]),
    )
    await _evento(conn, atendimento["id"], "perdido_registrado", origem, autor, payload)
    await _evento(
        conn,
        atendimento["id"],
        "transicao_estado",
        origem,
        autor,
        {"de": atendimento["estado"], "para": "Perdido"},
    )
    return ResultadoComando(atendimento["id"], "Perdido", atendimento["pix_status"])


async def _corrigir_registro(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    novo = payload.get("novo_resultado")
    if novo == "Fechado" and payload.get("valor_final") is None:
        raise EntradaInvalida("VALOR_FINAL_OBRIGATORIO", "Valor final obrigatorio.", {"campo": "valor_final"})
    if novo == "Perdido" and payload.get("motivo") is None:
        raise EntradaInvalida("MOTIVO_OBRIGATORIO", "Motivo obrigatorio.", {"campo": "motivo"})

    bloqueio_id = atendimento.get("bloqueio_id")
    if bloqueio_id and not payload.get("confirmar_alteracao_bloqueio_finalizado"):
        row = await conn.execute(
            "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s",
            (bloqueio_id,),
        )
        bloqueio = await row.fetchone()
        if bloqueio and bloqueio["estado"] in {"em_atendimento", "concluido"}:
            raise ConflitoEstado(
                "Alteracao de bloqueio finalizado exige confirmacao.",
                {"campo": "confirmar_alteracao_bloqueio_finalizado"},
            )

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = %s,
               valor_final = %s,
               motivo_perda = %s,
               motivo_perda_obs = %s,
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (
            novo,
            payload.get("valor_final"),
            payload.get("motivo"),
            payload.get("observacao"),
            _fonte(origem),
            atendimento["id"],
        ),
    )
    await _evento(conn, atendimento["id"], "correcao_registro", origem, autor, payload)
    return ResultadoComando(atendimento["id"], str(novo), atendimento["pix_status"])


async def _atualizar_pix(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    decisao = payload.get("decisao")
    if decisao == "validado":
        estado = "Confirmado" if atendimento["tipo_atendimento"] == "externo" else atendimento["estado"]
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET pix_status = 'validado',
                   estado = %s,
                   ia_pausada = true,
                   ia_pausada_motivo = 'modelo_em_atendimento',
                   responsavel_atual = 'modelo',
                   fonte_decisao_ultima_transicao = %s
             WHERE id = %s
            """,
            (estado, _fonte(origem), atendimento["id"]),
        )
        await _evento(conn, atendimento["id"], "pix_status_mudado", origem, autor, payload)
        return ResultadoComando(atendimento["id"], estado, "validado")

    if decisao == "invalido":
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET pix_status = 'invalido',
                   ia_pausada = false,
                   ia_pausada_motivo = NULL,
                   fonte_decisao_ultima_transicao = %s
             WHERE id = %s
            """,
            (_fonte(origem), atendimento["id"]),
        )
        await _evento(conn, atendimento["id"], "pix_status_mudado", origem, autor, payload)
        return ResultadoComando(atendimento["id"], atendimento["estado"], "invalido")

    raise EntradaInvalida("DECISAO_PIX_INVALIDA", "Decisao Pix invalida.")


async def abrir_handoff(
    conn: AsyncConnection[Any],
    *,
    atendimento_id: UUID,
    responsavel: str,
    motivo: str,
    resumo_operacional: str,
    acao_esperada: str,
    origem: Origem,
    autor: Autor,
    card_message_id: str | None = None,
) -> None:
    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO barravips.escaladas (
              atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada, card_message_id
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (atendimento_id, responsavel, motivo, resumo_operacional, acao_esperada, card_message_id),
        )
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET ia_pausada = true,
                   ia_pausada_motivo = 'handoff_ia',
                   responsavel_atual = %s,
                   motivo_escalada = %s,
                   proxima_acao_esperada = %s
             WHERE id = %s
            """,
            (responsavel, motivo, acao_esperada, atendimento_id),
        )
        await _evento(
            conn,
            atendimento_id,
            "handoff_aberto",
            origem,
            autor,
            {"responsavel": responsavel, "motivo": motivo, "acao_esperada": acao_esperada},
        )


async def _evento(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    tipo: str,
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        """,
        (atendimento_id, tipo, _origem_evento(origem), autor, json.dumps(payload, default=str)),
    )


def _fonte(origem: Origem) -> str:
    return {
        "painel": "painel_fernando",
        "grupo_coordenacao": "comando_grupo",
        "pipeline_pix": "pipeline_pix",
        "cron": "cron_em_execucao",
        "agente": "extracao_ia",
    }[origem]


def _origem_evento(origem: Origem) -> str:
    return "grupo_coordenacao" if origem == "grupo_coordenacao" else origem


def _canal(origem: Origem) -> str:
    return "grupo_coordenacao" if origem == "grupo_coordenacao" else "painel"
