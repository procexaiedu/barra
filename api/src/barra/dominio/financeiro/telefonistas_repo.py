"""SQL do cadastro do **Telefonista** — o percentual de comissão dele (ADR-0048 §1).

A tabela é `barravips.vendedores`: "telefonista" é como o dono chama o **Vendedor** quando fala do
grupo financeiro, e não existe entidade nova. O cadastro básico (nome/nível/ativo) já tinha porta
em `dominio/vendedores/`; o que não tinha era o número que o dono pediu para poder mexer
(*"uma porcentagem pro telefonista que a gente possa alterar, de 1% a 10%"*), e é ele que este
módulo lê e escreve.

⚠️ **A faixa 1-10% é operacional, não invariante** (ADR-0048, alternativa rejeitada): o CHECK do
banco é `0..100` e o do Pydantic também. Quem avisa que 12% está fora do usual é a tela, não uma
recusa — o próprio dono divagou *"ou até 100%"*.

⚠️ **Não há snapshot** (ADR-0048 §6). Mudar `percentual_comissao` aqui muda a projeção de toda a
comissão, inclusive a de vendas antigas. É o padrão do Módulo Financeiro e o oposto do
`percentual_repasse_snapshot` da modelo, que é negociado com ela e não pode ser reescrito.

⚠️ `percentual_comissao` e `whatsapp_jid` nascem na migration
`infra/sql/20260820126000_vendedores_percentual_e_whatsapp_jid.sql`, **escrita e ainda não
aplicada**. Sem ela o SQL daqui falha — de propósito, como as rotas de temporada: não há caminho
degradado, porque devolver "0%" de uma coluna que não existe seria pior.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

COLUNAS_EDITAVEIS = frozenset({"nome", "percentual_comissao", "ativo", "whatsapp_jid"})
"""As únicas colunas que o PATCH desta porta pode tocar. `nivel` fica de fora de propósito: ele
sobrevive só como default de cadastro (ADR-0048 §1) e não é mais consultado no cálculo."""


@dataclass(frozen=True)
class TelefonistaLido:
    """Uma linha de `vendedores` pelo recorte do ADR-0048: quem é, quanto leva e por qual JID.

    `whatsapp_jid` é o vínculo que diz QUEM vendeu (§5) — a ficha é postada por uma pessoa. Vem
    junto na leitura porque telefonista sem JID nunca ganha comissão de venda anunciada no grupo,
    e isso precisa ser visível no cadastro, não descoberto no fim do mês.
    """

    id: UUID
    nome: str
    percentual_comissao: Decimal
    ativo: bool
    whatsapp_jid: str | None


_SELECT_BASE = """
    SELECT v.id, v.nome, v.percentual_comissao, v.ativo, v.whatsapp_jid
      FROM barravips.vendedores v
"""


def _linha(row: dict[str, Any]) -> TelefonistaLido:
    return TelefonistaLido(
        id=row["id"],
        nome=row["nome"],
        percentual_comissao=Decimal(str(row["percentual_comissao"])),
        ativo=row["ativo"],
        whatsapp_jid=row["whatsapp_jid"],
    )


async def listar(conn: AsyncConnection[Any], *, incluir_inativos: bool) -> list[TelefonistaLido]:
    """Ativos primeiro, depois por nome — a ordem em que o gestor procura alguém na lista."""
    where = "" if incluir_inativos else "WHERE v.ativo"
    result = await conn.execute(f"{_SELECT_BASE} {where} ORDER BY v.ativo DESC, v.nome")
    return [_linha(row) for row in await result.fetchall()]


async def obter(conn: AsyncConnection[Any], telefonista_id: UUID) -> TelefonistaLido | None:
    result = await conn.execute(f"{_SELECT_BASE} WHERE v.id = %s", (telefonista_id,))
    row = await result.fetchone()
    return _linha(row) if row is not None else None


async def criar(
    conn: AsyncConnection[Any],
    *,
    nome: str,
    percentual_comissao: Decimal,
    whatsapp_jid: str | None,
    created_by: UUID | None,
) -> UUID:
    result = await conn.execute(
        """
        INSERT INTO barravips.vendedores (nome, percentual_comissao, whatsapp_jid, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (nome, percentual_comissao, whatsapp_jid, created_by),
    )
    row = await result.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def atualizar(
    conn: AsyncConnection[Any], telefonista_id: UUID, campos: dict[str, Any]
) -> bool:
    """UPDATE dinâmico com as colunas fechadas em `COLUNAS_EDITAVEIS`.

    O nome da coluna entra por f-string (o psycopg não parametriza identificador), então o conjunto
    fechado é o que impede input do cliente virar SQL. Os VALORES continuam parametrizados.
    """
    if not campos:
        return True
    desconhecidas = set(campos) - COLUNAS_EDITAVEIS
    if desconhecidas:
        raise ValueError(f"coluna nao editavel: {sorted(desconhecidas)}")
    sets = [f"{coluna} = %s" for coluna in campos]
    params = [*campos.values(), telefonista_id]
    result = await conn.execute(
        f"UPDATE barravips.vendedores SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    return result.rowcount > 0
