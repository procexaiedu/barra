"""O bolso no SQL: quem escreve, com que guarda e o que sai da fila (tickets 14 e 21).

Sem banco de propósito — a migration `20260820122000` (a coluna `bolso`) ainda **não** foi
aplicada em lugar nenhum, e o que estes testes precisam provar não é que o Postgres aceita o
comando: é que o comando **carrega as guardas certas**. Cada uma delas, se cair, produz um erro
silencioso e caro:

- `definir_forma_de_pagamento` fixa `dela` **só** para dinheiro (espécie não tem outro bolso) e
  **só** quando o bolso ainda era `nao_dito` — a regra mais fraca da tabela não pode atropelar um
  comprovante que já provou `empresa`.
- `abater_vendas` fixa `dela` no mesmo UPDATE do abate: é o mesmo fato (o comprovante que credita
  a transferência é o que produz o débito do bruto), e separá-los deixaria o saldo com uma perna
  só por um instante.
- `definir_bolso_da_venda` é **compare-and-swap** sobre o valor que o chamador viu. Sem isso, duas
  evidências concorrentes escreveriam as duas e a última venceria em silêncio — num campo que
  inverte o sinal do saldo.
- `vendas_pix_a_comprovar` tira o bolso `empresa` da fila: o dinheiro que caiu direto na casa não
  tem transferência dela para abater, e cobrá-lo dela é a cobrança que volta idêntica todo dia.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from barra.dominio.grupo_financeiro import repo

BIANCA = UUID("b1a11ca0-0000-0000-0000-000000000001")
VENDA = UUID("aaaaaaaa-0000-0000-0000-000000000001")
COMPROVANTE = UUID("cccccccc-0000-0000-0000-000000000001")
MENSAGEM = UUID("dddddddd-0000-0000-0000-000000000001")


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConn:
    """Grava (query, params) e devolve as linhas que o teste mandou. Nenhum banco envolvido."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.binds: list[tuple[str, Any]] = []
        self._rows = rows or []

    async def execute(self, query: str, params: Any = None) -> _Cursor:
        self.binds.append((query, params))
        return _Cursor(self._rows)

    @property
    def query(self) -> str:
        return self.binds[-1][0]

    @property
    def params(self) -> tuple[Any, ...]:
        return tuple(self.binds[-1][1] or ())


def _linha_da_venda(**extra: Any) -> dict[str, Any]:
    linha: dict[str, Any] = {
        "id": VENDA,
        "modelo_id": BIANCA,
        "valor": Decimal("600.00"),
        "data": date(2026, 8, 20),
        "mensagem_id": MENSAGEM,
        "cliente_nome": "Lucas",
        "local_atendimento": None,
        "duracao_minutos": None,
        "forma_pagamento": "pix",
        "comprovante_id": None,
        "anulada_em": None,
        "recebido_por_modelo_id": None,
    }
    linha.update(extra)
    return linha


def _linha_do_bolso(**extra: Any) -> dict[str, Any]:
    linha: dict[str, Any] = {
        "id": VENDA,
        "modelo_id": BIANCA,
        "valor": Decimal("600.00"),
        "data": date(2026, 8, 20),
        "bolso": "nao_dito",
        "forma_pagamento": "pix",
        "cliente_nome": "Lucas",
        "bolso_mensagem_id": None,
    }
    linha.update(extra)
    return linha


# --- a forma que fixa o bolso -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dinheiro_fixa_o_bolso_na_mesma_transacao_da_forma() -> None:
    conn = FakeConn([_linha_da_venda(forma_pagamento="dinheiro")])

    await repo.definir_forma_de_pagamento(
        conn,  # type: ignore[arg-type]
        VENDA,
        forma="dinheiro",
        mensagem_id=MENSAGEM,
    )

    assert "bolso = CASE WHEN" in conn.query
    assert "bolso = 'nao_dito'" in conn.query
    # (forma, mensagem, especie, especie, mensagem, venda)
    assert conn.params == ("dinheiro", MENSAGEM, True, True, MENSAGEM, VENDA)


@pytest.mark.asyncio
async def test_pix_e_cartao_nao_dizem_nada_sobre_o_bolso() -> None:
    """A tabela de evidência tem UMA linha de forma, e ela é só o dinheiro (ADR-0047 §2)."""
    for forma in ("pix", "debito", "credito", "link"):
        conn = FakeConn([_linha_da_venda(forma_pagamento=forma)])

        await repo.definir_forma_de_pagamento(
            conn,  # type: ignore[arg-type]
            VENDA,
            forma=forma,
            mensagem_id=MENSAGEM,
        )

        assert conn.params[2] is False, forma
        assert conn.params[3] is False, forma


# --- o abate que fixa o bolso -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_abate_fixa_o_bolso_em_dela_e_aponta_para_a_mensagem_do_comprovante() -> None:
    """Primeira linha da tabela: ela transferiu para a casa, logo o dinheiro passou por ela."""
    conn = FakeConn([_linha_da_venda(comprovante_id=COMPROVANTE)])

    baixadas = await repo.abater_vendas(conn, COMPROVANTE, [VENDA])  # type: ignore[arg-type]

    assert [v.id for v in baixadas] == [VENDA]
    assert "THEN 'dela'::barravips.bolso_da_venda_enum" in conn.query
    assert "FROM barravips.comprovantes_do_grupo c" in conn.query
    assert conn.params == (COMPROVANTE, COMPROVANTE, VENDA)


@pytest.mark.asyncio
async def test_o_abate_nao_reescreve_bolso_ja_afirmado() -> None:
    """`CASE WHEN bolso = 'nao_dito'` — divergência vira pergunta na porta, nunca UPDATE calado."""
    conn = FakeConn([_linha_da_venda()])

    await repo.abater_vendas(conn, COMPROVANTE, [VENDA])  # type: ignore[arg-type]

    assert conn.query.count("CASE WHEN bolso = 'nao_dito'") == 2


# --- o compare-and-swap -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_definir_bolso_e_compare_and_swap_sobre_o_valor_visto() -> None:
    conn = FakeConn([_linha_do_bolso(bolso="empresa", bolso_mensagem_id=MENSAGEM)])

    venda = await repo.definir_bolso_da_venda(
        conn,  # type: ignore[arg-type]
        VENDA,
        de="nao_dito",
        para="empresa",
        mensagem_id=MENSAGEM,
    )

    assert venda is not None and venda.bolso == "empresa"
    assert venda.afirmado
    assert conn.params == ("empresa", MENSAGEM, VENDA, "nao_dito")


@pytest.mark.asyncio
async def test_bolso_que_mudou_no_meio_do_caminho_nao_escreve() -> None:
    """A segunda evidência concorrente recebe `None` e cai na conduta de divergência."""
    conn = FakeConn([])

    assert (
        await repo.definir_bolso_da_venda(
            conn,  # type: ignore[arg-type]
            VENDA,
            de="nao_dito",
            para="empresa",
            mensagem_id=MENSAGEM,
        )
        is None
    )


@pytest.mark.asyncio
async def test_o_rastro_do_bolso_entra_como_correcao_de_campo() -> None:
    """`venda_registrada_eventos` é append-only e o CHECK dela admite três tipos — nenhum novo."""
    conn = FakeConn([])

    await repo.registrar_evento_do_bolso(
        conn,  # type: ignore[arg-type]
        VENDA,
        de="nao_dito",
        para="empresa",
        mensagem_id=MENSAGEM,
    )

    assert "'correcao', 'bolso'" in conn.query
    assert conn.params == (VENDA, "nao_dito", "empresa", MENSAGEM)


# --- as filas -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bolso_empresa_sai_da_fila_do_comprovante() -> None:
    """Não há transferência dela para abater — e cobrá-la seria a cobrança insolúvel de todo dia."""
    conn = FakeConn([])

    await repo.vendas_pix_a_comprovar(conn, BIANCA)  # type: ignore[arg-type]

    assert "bolso <> 'empresa'" in conn.query


@pytest.mark.asyncio
async def test_a_fila_da_manha_do_bolso_e_so_o_nao_dito() -> None:
    """Irmã de `vendas_sem_forma_de_pagamento`: as duas pendências viajam na MESMA mensagem."""
    conn = FakeConn([_linha_do_bolso()])

    fila = await repo.vendas_sem_bolso_dito(conn, BIANCA)  # type: ignore[arg-type]

    assert [v.id for v in fila] == [VENDA]
    assert not fila[0].afirmado
    assert "v.bolso = 'nao_dito'" in conn.query
    assert "m.recebida_em" in conn.query


@pytest.mark.asyncio
async def test_a_janela_da_fala_traz_as_afirmadas_junto() -> None:
    """A fala que contradiz um bolso afirmado não pode ser filtrada para fora da lista."""
    conn = FakeConn([_linha_do_bolso(bolso="dela")])

    candidatas = await repo.vendas_para_o_bolso(conn, BIANCA)  # type: ignore[arg-type]

    assert candidatas[0].afirmado
    assert "bolso = 'nao_dito'" not in conn.query
    assert conn.params == (BIANCA, repo.MAX_VENDAS_CONFRONTAVEIS)
