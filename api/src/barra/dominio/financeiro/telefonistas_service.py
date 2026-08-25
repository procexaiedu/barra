"""Cadastro do Telefonista pelo painel: nome, percentual e ativo (ADR-0048).

A aba **Telefonistas**, ao lado de Modelos, é onde o dono mexe no número — foi pedida com essas
palavras (*"cadastrar o nome deles, pra vocês conseguirem alterar os valores da comissão deles"*).
Este módulo é a orquestração dela: normaliza o que o gestor digitou, traduz colisão de JID em 409
e nada mais. A aritmética da comissão **não mora aqui** — ela é projeção, feita na leitura
(ADR-0048 §6).

⚠️ Mexer no percentual reprojeta a comissão **inteira**, inclusive a de vendas passadas: não há
snapshot por venda, por decisão. Quem quiser preservar o número de um mês fechado tem que resolver
isso no relatório, nunca inventando uma coluna de snapshot aqui.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation

from barra.core.errors import ConflitoEstado, NaoEncontrado
from barra.dominio.financeiro import telefonistas_repo
from barra.dominio.financeiro.schemas import (
    TelefonistaCriar,
    TelefonistaPatch,
    TelefonistaResponse,
    TelefonistasListaResponse,
)
from barra.dominio.financeiro.telefonistas_repo import TelefonistaLido


def _response(lido: TelefonistaLido) -> TelefonistaResponse:
    return TelefonistaResponse(
        id=lido.id,
        nome=lido.nome,
        percentual_comissao=float(lido.percentual_comissao),
        ativo=lido.ativo,
        whatsapp_jid=lido.whatsapp_jid,
    )


def _jid_normalizado(bruto: str | None) -> str | None:
    """Espaço em volta e string vazia viram `None`.

    Vazio precisa virar `NULL` e não `''`: o índice único é parcial
    (`WHERE whatsapp_jid IS NOT NULL`), então dois telefonistas com `''` colidiriam — e um JID
    vazio não identifica ninguém. Nenhuma outra limpeza: o JID pode chegar como `@lid` opaco, e
    "consertar" o formato aqui seria palpite sobre o que a Evolution manda.
    """
    if bruto is None:
        return None
    limpo = bruto.strip()
    return limpo or None


def _traduzir_jid_duplicado(exc: UniqueViolation) -> ConflitoEstado | UniqueViolation:
    if (getattr(exc.diag, "constraint_name", None) or "") == "vendedores_whatsapp_jid_uniq":
        return ConflitoEstado("Este WhatsApp ja esta vinculado a outro telefonista.")
    return exc


async def listar_telefonistas(
    conn: AsyncConnection[Any], *, incluir_inativos: bool
) -> TelefonistasListaResponse:
    itens = await telefonistas_repo.listar(conn, incluir_inativos=incluir_inativos)
    return TelefonistasListaResponse(items=[_response(t) for t in itens])


async def criar_telefonista(
    conn: AsyncConnection[Any], body: TelefonistaCriar, user_id: UUID | None
) -> TelefonistaResponse:
    try:
        telefonista_id = await telefonistas_repo.criar(
            conn,
            nome=body.nome.strip(),
            percentual_comissao=body.percentual_comissao,
            whatsapp_jid=_jid_normalizado(body.whatsapp_jid),
            created_by=user_id,
        )
    except UniqueViolation as exc:
        raise _traduzir_jid_duplicado(exc) from exc
    criado = await telefonistas_repo.obter(conn, telefonista_id)
    assert criado is not None
    return _response(criado)


async def atualizar_telefonista(
    conn: AsyncConnection[Any], telefonista_id: UUID, body: TelefonistaPatch
) -> TelefonistaResponse:
    """PATCH parcial: só os campos enviados são tocados (`exclude_unset`).

    `ativo=false` é a desativação — o telefonista sai dos seletores e para de aparecer na aba, mas
    o histórico de comissão e os atendimentos dele continuam apontando para a mesma linha. Não há
    DELETE: `financeiro_comissoes_pagas` referencia `vendedores` com `ON DELETE RESTRICT`.
    """
    campos: dict[str, Any] = body.model_dump(exclude_unset=True)
    if "nome" in campos and campos["nome"] is not None:
        campos["nome"] = campos["nome"].strip()
    if "whatsapp_jid" in campos:
        campos["whatsapp_jid"] = _jid_normalizado(campos["whatsapp_jid"])
    # `None` só é apagamento em `whatsapp_jid` (coluna nullable). Nos demais, `None` é "não mexe" —
    # o cliente que manda `nome: null` está mandando lixo, e gravar isso violaria o NOT NULL.
    campos = {
        coluna: valor
        for coluna, valor in campos.items()
        if valor is not None or coluna == "whatsapp_jid"
    }
    if not campos:
        return await obter_telefonista(conn, telefonista_id)

    try:
        existe = await telefonistas_repo.atualizar(conn, telefonista_id, campos)
    except UniqueViolation as exc:
        raise _traduzir_jid_duplicado(exc) from exc
    if not existe:
        raise NaoEncontrado("Telefonista")
    return await obter_telefonista(conn, telefonista_id)


async def obter_telefonista(
    conn: AsyncConnection[Any], telefonista_id: UUID
) -> TelefonistaResponse:
    lido = await telefonistas_repo.obter(conn, telefonista_id)
    if lido is None:
        raise NaoEncontrado("Telefonista")
    return _response(lido)
