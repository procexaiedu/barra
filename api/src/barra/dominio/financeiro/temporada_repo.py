"""SQL de ESCRITA da Temporada e do razão pelo painel (ticket 05).

`razao_repo.py` é o lado da leitura: traduz linhas do banco em `Lancamento` e não escreve nada.
Este módulo é o outro lado, e existe porque o ticket 05 é o único do painel que **move dinheiro
de verdade**: abrir a temporada, lançar o vale adiantado, registrar o pagamento feito à modelo e
marcar a temporada como fechada.

⚠️ **Nada aqui grava saldo** (ADR-0045 §7). Não há coluna de saldo, de fechamento nem de
snapshot, e não é esquecimento: fechar a temporada grava `estado` e `fechada_em` — uma marca de
rotina — e o pagamento grava o **fato** de que o dinheiro saiu (`financeiro_repasses_pagos` com
`temporada_id`). O número continua sendo apurado a cada leitura pelo `razao.apurar`, então um
comprovante que chegar depois de "fechada" recalcula o saldo e a diferença contra o já pago
aparece como "falta pagar R$ X". Não existe reabertura porque nunca houve congelamento.

⚠️ **Fechar é ação do PAINEL, nunca frase no grupo** (ADR-0045 §8): move dinheiro de verdade e a
modelo está dentro do grupo. Por isso a única porta de escrita da temporada é HTTP autenticado —
`agente_financeiro/` não importa este módulo, e não deve passar a importar.

⚠️ **O que "vale" NÃO é** (ADR-0047 §5): "ficou com ela", dito sobre uma venda, não é vale — é a
venda com `bolso = 'dela'` mais a ausência da transferência, e o razão já dá o número certo sem
conceito novo. Lançar um vale também contaria o mesmo dinheiro duas vezes. Vale é adiantamento
**fora** de uma venda.

⚠️ Este módulo escreve em tabelas da onda `20260820*` (`temporadas`, `razao_lancamentos_manuais`,
`financeiro_repasses_pagos.temporada_id`), cujas migrations estão **escritas e não aplicadas**.
Sem elas as rotas respondem erro de SQL, de propósito: não há caminho degradado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection

TipoDoLancamentoManual = Literal["vale", "ajuste"]
SentidoDoLancamento = Literal["debito", "credito"]
OrigemDoLancamento = Literal["painel", "grupo"]

ORIGEM_DO_PAINEL: OrigemDoLancamento = "painel"
"""A única origem que este módulo escreve. `grupo` é do agente (com `mensagem_id` obrigatório pelo
CHECK `razao_lancamentos_manuais_grupo_tem_mensagem`) e entra por outra porta."""


@dataclass(frozen=True)
class LancamentoManualLido:
    """Uma linha de `razao_lancamentos_manuais` com a **origem** à vista.

    `origem` é o que o extrato do painel precisa para distinguir o vale que o gestor digitou do
    vale que o agente leu no grupo — os dois debitam igual, mas só um tem alguém do lado de cá
    responsável pelo número (`created_by`).
    """

    id: UUID
    modelo_id: UUID
    tipo: TipoDoLancamentoManual
    sentido: SentidoDoLancamento
    valor: Decimal
    data: date
    descricao: str | None
    origem: OrigemDoLancamento
    temporada_id: UUID | None
    mensagem_id: UUID | None
    anulado_em: datetime | None


_COLUNAS_DO_LANCAMENTO = """
    r.id, r.modelo_id, r.tipo, r.sentido, r.valor, r.data, r.descricao,
    r.origem, r.temporada_id, r.mensagem_id, r.anulado_em
"""


def _lancamento(row: dict[str, Any]) -> LancamentoManualLido:
    return LancamentoManualLido(
        id=row["id"],
        modelo_id=row["modelo_id"],
        tipo=row["tipo"],
        sentido=row["sentido"],
        valor=row["valor"],
        data=row["data"],
        descricao=row["descricao"],
        origem=row["origem"],
        temporada_id=row["temporada_id"],
        mensagem_id=row["mensagem_id"],
        anulado_em=row["anulado_em"],
    )


# =============================================================================
# Temporada
# =============================================================================


async def criar_temporada(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    cidade: str,
    data_inicio: date,
    data_fim: date,
    observacao: str | None,
    user_id: UUID | None,
) -> UUID:
    """Abre a temporada. Nasce `aberta` e sem `fechada_em` — o CHECK amarra os dois."""
    cur = await conn.execute(
        """
        INSERT INTO barravips.temporadas
            (modelo_id, cidade, data_inicio, data_fim, observacao, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (modelo_id, cidade, data_inicio, data_fim, observacao, user_id),
    )
    row = await cur.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def marcar_temporada_fechada(conn: AsyncConnection[Any], temporada_id: UUID) -> bool:
    """Marca a temporada como fechada. Idempotente, e **não** congela nada.

    `fechada_em` só é gravada na primeira vez (`COALESCE`): ela serve para explicar o extrato ("o
    que chegou depois disto é a diferença a pagar"), então reescrevê-la a cada clique apagaria
    justamente a data que responde essa pergunta. Temporada `cancelada` não fecha — a viagem não
    aconteceu, não há o que pagar.
    """
    cur = await conn.execute(
        """
        UPDATE barravips.temporadas
           SET estado = 'fechada',
               fechada_em = COALESCE(fechada_em, now())
         WHERE id = %s
           AND estado <> 'cancelada'
        """,
        (temporada_id,),
    )
    return cur.rowcount > 0


async def temporadas_sobrepostas(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    data_inicio: date,
    data_fim: date,
) -> list[UUID]:
    """As temporadas vivas da mesma modelo que cruzam este período.

    O banco não impede a sobreposição (exigiria `btree_gist` + EXCLUDE, extensão que o projeto não
    usa — está dito na migration `20260820124000`). A checagem mora aqui porque duas temporadas
    sobrepostas fazem a MESMA venda aparecer nas duas, e o gestor pagaria duas vezes por ela.
    """
    cur = await conn.execute(
        """
        SELECT t.id
          FROM barravips.temporadas t
         WHERE t.modelo_id = %(modelo)s
           AND t.estado <> 'cancelada'
           AND t.data_inicio <= %(fim)s::date
           AND t.data_fim >= %(inicio)s::date
         ORDER BY t.data_inicio
        """,
        {"modelo": modelo_id, "inicio": data_inicio, "fim": data_fim},
    )
    return [row["id"] for row in await cur.fetchall()]


# =============================================================================
# Pagamento da temporada
# =============================================================================


async def criar_pagamento_da_temporada(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    temporada_id: UUID | None,
    data_pagamento: date,
    valor: Decimal,
    forma_pagamento: str,
    observacao: str | None,
    comprovante_object_key: str | None,
    user_id: UUID | None,
) -> UUID:
    """Grava o pagamento feito à modelo como FATO, com data (ADR-0045 §7).

    Reusa `financeiro_repasses_pagos` — a tabela que desde o ADR-0011 significa "a casa pagou a
    modelo" — com `temporada_id` como recorte. Uma tabela paralela criaria dois lugares com o
    mesmo significado, e a primeira soma que esquecesse um deles pagaria a modelo duas vezes.
    """
    cur = await conn.execute(
        """
        INSERT INTO barravips.financeiro_repasses_pagos
            (modelo_id, temporada_id, data_pagamento, valor, forma_pagamento,
             observacao, comprovante_object_key, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            modelo_id,
            temporada_id,
            data_pagamento,
            valor,
            forma_pagamento,
            observacao,
            comprovante_object_key,
            user_id,
        ),
    )
    row = await cur.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


# =============================================================================
# Vale e ajuste (razao_lancamentos_manuais)
# =============================================================================


async def criar_lancamento_manual(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    tipo: TipoDoLancamentoManual,
    sentido: SentidoDoLancamento,
    valor: Decimal,
    data: date,
    descricao: str | None,
    temporada_id: UUID | None,
    user_id: UUID | None,
) -> UUID:
    """O vale adiantado do painel. `valor` é SEMPRE positivo; a direção mora em `sentido`.

    `origem` é fixa em `painel` — a origem `grupo` exige `mensagem_id` pelo CHECK, e mensagem de
    grupo não existe deste lado. `chave_conteudo` fica nula pelo mesmo motivo: o dedup existe para
    o repost do grupo; aqui o gestor é responsável pelo que digita.
    """
    cur = await conn.execute(
        """
        INSERT INTO barravips.razao_lancamentos_manuais
            (modelo_id, tipo, sentido, valor, data, descricao, origem, temporada_id, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            modelo_id,
            tipo,
            sentido,
            valor,
            data,
            descricao,
            ORIGEM_DO_PAINEL,
            temporada_id,
            user_id,
        ),
    )
    row = await cur.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def anular_lancamento_manual(conn: AsyncConnection[Any], lancamento_id: UUID) -> bool:
    """Estado com rastro, nunca DELETE. Anulado sai do razão e solta a `chave_conteudo`."""
    cur = await conn.execute(
        """
        UPDATE barravips.razao_lancamentos_manuais
           SET anulado_em = now()
         WHERE id = %s
           AND anulado_em IS NULL
        """,
        (lancamento_id,),
    )
    return cur.rowcount > 0


async def obter_lancamento_manual(
    conn: AsyncConnection[Any], lancamento_id: UUID
) -> LancamentoManualLido | None:
    cur = await conn.execute(
        f"""
        SELECT {_COLUNAS_DO_LANCAMENTO}
          FROM barravips.razao_lancamentos_manuais r
         WHERE r.id = %s
        """,
        (lancamento_id,),
    )
    row = await cur.fetchone()
    return None if row is None else _lancamento(row)


async def lancamentos_manuais(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    de: date | None = None,
    ate: date | None = None,
    incluir_anulados: bool = False,
) -> list[LancamentoManualLido]:
    """Os vales e ajustes da modelo no recorte, **com a origem** (painel x grupo).

    O extrato do razão (`razao_repo`) já soma estas linhas no saldo, mas achata a origem: lá um
    vale é um `Lancamento` e nada mais. Aqui elas aparecem como o que são para quem confere — e é
    por isso que a tela de fechamento mostra os vales separados dos demais lançamentos.
    """
    cur = await conn.execute(
        f"""
        SELECT {_COLUNAS_DO_LANCAMENTO}
          FROM barravips.razao_lancamentos_manuais r
         WHERE r.modelo_id = %(modelo)s
           AND (%(incluir_anulados)s::bool OR r.anulado_em IS NULL)
           AND (%(de)s::date IS NULL OR r.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR r.data <= %(ate)s::date)
         ORDER BY r.data, r.id
        """,
        {
            "modelo": modelo_id,
            "incluir_anulados": incluir_anulados,
            "de": de,
            "ate": ate,
        },
    )
    return [_lancamento(row) for row in await cur.fetchall()]
