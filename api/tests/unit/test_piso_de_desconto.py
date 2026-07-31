"""Piso do Desconto de fechamento (ADR-0031) — o site ÚNICO da conta.

`piso_de_desconto` é `preço de tabela x (1 - desconto_teto_pct)`. O mesmo número serve a dois
consumidores que precisam concordar até no arredondamento: a guarda que JULGA o `valor_acordado`
(`_abaixo_do_piso`) e o `<ja_fez_contraproposta n="1">` da cauda, que MOSTRA o teto à IA em vez do
percentual que ela multiplicava de cabeça (`teto_de_contraproposta`). Sem DB, sem crédito.
"""

from decimal import Decimal
from typing import Any

from barra.dominio.atendimentos.service import piso_de_desconto, teto_de_contraproposta

# --- a conta (pura) -----------------------------------------------------------------------------


def test_piso_e_o_teto_percentual_sobre_a_tabela() -> None:
    # default de settings: desconto_teto_pct = 0.25 (ADR-0031, ~25%).
    assert piso_de_desconto(Decimal("400")) == Decimal("300.00")
    assert piso_de_desconto(Decimal("700")) == Decimal("525.00")


def test_piso_nao_arredonda_por_conta_propria() -> None:
    """Quem julga e quem mostra recebem o MESMO Decimal — arredondar aqui é o que faria a oferta
    que a cauda mandou fazer cair um centavo abaixo do piso e escalar à toa."""
    assert piso_de_desconto(Decimal("350")) == Decimal("262.50")


# --- o valor que a cauda mostra ------------------------------------------------------------------


class _FakeConn:
    """Responde a query de preços da duração com o par (menor, maior) combinado."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.params: tuple[Any, ...] = ()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        self.params = params
        row = self.row

        class _R:
            async def fetchone(self) -> dict[str, Any] | None:
                return row

        return _R()


async def _teto(row: dict[str, Any] | None, duracao: Any = 1) -> Decimal | None:
    return await teto_de_contraproposta(_FakeConn(row), "m1", duracao)  # type: ignore[arg-type]


async def test_duracao_com_um_preco_so_devolve_o_piso_desse_preco() -> None:
    assert await _teto({"menor": Decimal("400"), "maior": Decimal("400")}) == Decimal("300.00")


async def test_duracao_com_precos_diferentes_nao_devolve_numero() -> None:
    """O piso do guard é o do programa mais BARATO de propósito (ADR-0004 §Decisão item 5); o teto
    que ela oferta é sobre o pacote VENDIDO, que o atendimento não grava. Com dois preços na mesma
    duração as duas leituras divergem — a cauda cala e vale o percentual do <desconto>."""
    assert await _teto({"menor": Decimal("400"), "maior": Decimal("700")}) is None


async def test_sem_programa_na_duracao_nao_devolve_numero() -> None:
    # Agregado sem GROUP BY devolve uma linha com NULL quando não há programa na duração.
    assert await _teto({"menor": None, "maior": None}) is None


async def test_sem_duracao_fechada_nao_consulta_nem_devolve_numero() -> None:
    conn = _FakeConn({"menor": Decimal("400"), "maior": Decimal("400")})
    assert await teto_de_contraproposta(conn, "m1", None) is None  # type: ignore[arg-type]
    assert conn.params == ()
