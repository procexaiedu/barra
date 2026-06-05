"""Orquestracao da rotulagem de calibracao: upload->rodada, rotulos, export."""

from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import UUID

from psycopg import AsyncConnection

from barra.calibracao import repo
from barra.calibracao.export import RotuloFala, montar_golden
from barra.calibracao.falas import falas_de, parse_jsonl
from barra.calibracao.schemas import (
    FalaParaRotular,
    FalasResponse,
    MeuRotulo,
    RodadaResumo,
    RodadasResponse,
    RotuloInput,
)
from barra.core.errors import ErroDominio


class _EmailsRotulador(Protocol):
    calibracao_email_fernando: str | None
    calibracao_email_socia: str | None


def resolver_rotulador(email: str | None, settings: _EmailsRotulador) -> str:
    """Email do operador logado -> 'fernando' | 'socia' (puro; testavel offline).

    Unica forma de distinguir os dois (sem RBAC, ambos papel='fernando'). Email nao mapeado
    -> 403: a tela so abre p/ quem esta configurado como rotulador.
    """
    alvo = (email or "").strip().lower()
    f = (settings.calibracao_email_fernando or "").strip().lower()
    s = (settings.calibracao_email_socia or "").strip().lower()
    if alvo and alvo == f:
        return "fernando"
    if alvo and alvo == s:
        return "socia"
    raise ErroDominio(
        "ROTULADOR_NAO_AUTORIZADO",
        "Seu usuario nao esta configurado como rotulador de calibracao.",
        status_code=403,
    )


def _resumo(row: dict[str, Any]) -> RodadaResumo:
    return RodadaResumo(
        id=row["id"], nome=row["nome"], created_at=row["created_at"], total_falas=row["total_falas"]
    )


async def criar_rodada(
    conn: AsyncConnection[Any], nome: str, descricao: str | None, conteudo: bytes
) -> RodadaResumo:
    nome = nome.strip()
    if not nome:
        raise ErroDominio("NOME_OBRIGATORIO", "Informe um nome para a rodada.")
    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ErroDominio("ARQUIVO_INVALIDO", "O arquivo nao e UTF-8 valido.") from e
    try:
        conversas = parse_jsonl(texto)
    except json.JSONDecodeError as e:
        raise ErroDominio("JSONL_INVALIDO", f"JSONL malformado: {e}") from e
    falas = falas_de(conversas)
    if not falas:
        raise ErroDominio(
            "SEM_FALAS",
            "Nenhuma fala da IA encontrada no arquivo (esperado .jsonl de gerar_conversas.py).",
        )
    if await repo.nome_existe(conn, nome):
        raise ErroDominio(
            "NOME_DUPLICADO", f"Ja existe uma rodada chamada {nome!r}.", status_code=409
        )

    rodada_id = await repo.criar_rodada(conn, nome, descricao, falas)
    row = await repo.obter_rodada(conn, rodada_id)
    assert row is not None
    return _resumo(row)


async def listar(conn: AsyncConnection[Any]) -> RodadasResponse:
    rows = await repo.listar_rodadas(conn)
    return RodadasResponse(rodadas=[_resumo(r) for r in rows])


async def _exigir_rodada(conn: AsyncConnection[Any], rodada_id: UUID) -> dict[str, Any]:
    row = await repo.obter_rodada(conn, rodada_id)
    if row is None:
        raise ErroDominio("RODADA_NAO_ENCONTRADA", "Rodada nao encontrada.", status_code=404)
    return row


async def falas_para_rotular(
    conn: AsyncConnection[Any], rodada_id: UUID, rotulador: str
) -> FalasResponse:
    rodada = await _exigir_rodada(conn, rodada_id)
    rows = await repo.falas_da_rodada(conn, rodada_id, rotulador)
    falas = [
        FalaParaRotular(
            id=r["id"],
            fala_id=r["fala_id"],
            conversa_id=r["conversa_id"],
            cenario=r["cenario"],
            texto_resposta=r["texto_resposta"],
            historico=r["historico"],
            meu_rotulo=(
                MeuRotulo(passou=r["meu_passou"], observacao=r["minha_obs"])
                if r["meu_passou"] is not None
                else None
            ),
        )
        for r in rows
    ]
    return FalasResponse(rodada=_resumo(rodada), rotulador=rotulador, falas=falas)


async def marcar(conn: AsyncConnection[Any], entrada: RotuloInput, rotulador: str) -> None:
    ok = await repo.upsert_rotulo(
        conn, entrada.fala_pk, rotulador, entrada.passou, entrada.observacao
    )
    if not ok:
        raise ErroDominio("FALA_NAO_ENCONTRADA", "Fala nao encontrada.", status_code=404)


async def exportar(conn: AsyncConnection[Any], rodada_id: UUID) -> tuple[str, list[str]]:
    """Reconstroi o golden.jsonl da rodada (formato que calibrar.py consome) + avisos."""
    await _exigir_rodada(conn, rodada_id)
    falas = await repo.falas_para_export(conn, rodada_id)
    rot_f: dict[str, RotuloFala] = {}
    rot_s: dict[str, RotuloFala] = {}
    for r in await repo.rotulos_para_export(conn, rodada_id):
        alvo = rot_f if r["rotulador"] == "fernando" else rot_s
        alvo[r["fala_id"]] = RotuloFala(passou=r["passou"], observacao=r["observacao"])

    golden, avisos = montar_golden(falas, rot_f, rot_s)
    jsonl = "\n".join(json.dumps(linha, ensure_ascii=False) for linha in golden)
    return (jsonl + "\n" if jsonl else ""), avisos
