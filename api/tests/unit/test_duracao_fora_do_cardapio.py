"""Duração sem linha na tabela DESTA modelo não entra no snapshot (loop-massa r3, extração #2).

Caso vivo (`objetor_a t2`): o cliente PERGUNTOU 30 min, a IA RECUSOU, e a extração gravou
`duracao_horas=0.5` assim mesmo. Dali em diante todo consumidor procura um pacote que não existe —
`_abaixo_do_piso` → `_piso_do_pacote` → `_linhas_da_duracao` vazio → `(None, "sem_linha")` →
`abaixo = piso is None or ...` **True por `piso is None`**, e um 300 que era exatamente o piso
virava escalada `fora_de_oferta`.

O defeito NÃO é "0.5 é inválido": meia hora é pacote legítimo (a Catarina tem, com
`preco_minimo=250`, pinado em `test_piso_absoluto_da_linha_vence_o_percentual`). É "duração sem
linha na tabela DESTA modelo" — por isso o predicado lê o cardápio dela, não uma lista fixa.

Unit puro: conn roteirizado por trecho de SQL, sem DB.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from barra.dominio.atendimentos.service import _duracao_fora_do_cardapio

_AID = UUID("00000000-0000-0000-0000-0000000000a1")
_MODELO = UUID("00000000-0000-0000-0000-0000000000b1")


class _ConnRoteirizado:
    """Responde por trecho de SQL: o atendimento, as linhas da duração e o "tem cardápio?"."""

    def __init__(self, *, linhas_da_duracao: list[dict[str, Any]], tem_cardapio: bool) -> None:
        self._linhas = linhas_da_duracao
        self._tem_cardapio = tem_cardapio

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        linhas = self._linhas
        tem_cardapio = self._tem_cardapio

        class _R:
            async def fetchone(self) -> dict[str, Any] | None:
                if "FROM barravips.atendimentos" in sql:
                    return {"modelo_id": _MODELO}
                return {"?column?": 1} if tem_cardapio else None

            async def fetchall(self) -> list[dict[str, Any]]:
                return linhas

        return _R()


def _linha(preco: str, minimo: str) -> dict[str, Any]:
    return {
        "programa_id": UUID("00000000-0000-0000-0000-0000000000c1"),
        "nome": "Normal",
        "preco": Decimal(preco),
        "preco_minimo": Decimal(minimo),
    }


async def test_duracao_com_linha_na_tabela_nao_e_descartada() -> None:
    """O pacote de 30 min da Catarina é legítimo: existindo a linha, a duração passa."""
    conn = _ConnRoteirizado(linhas_da_duracao=[_linha("250", "250")], tem_cardapio=True)
    assert await _duracao_fora_do_cardapio(conn, _AID, 0.5) is False  # type: ignore[arg-type]


async def test_duracao_sem_linha_com_cardapio_cheio_e_descartada() -> None:
    """A mesma 0.5h numa modelo que só vende 1h/2h: é o pacote inexistente que trava a cotação."""
    conn = _ConnRoteirizado(linhas_da_duracao=[], tem_cardapio=True)
    assert await _duracao_fora_do_cardapio(conn, _AID, 0.5) is True  # type: ignore[arg-type]


async def test_cadastro_vazio_nao_vira_bloqueio() -> None:
    """Sem NENHUMA linha cadastrada não há menu contra o que julgar — descartar ali travaria toda
    modelo em cadastro pela metade (mesmo princípio do "array vazio não trava" da guarda de tipo)."""
    conn = _ConnRoteirizado(linhas_da_duracao=[], tem_cardapio=False)
    assert await _duracao_fora_do_cardapio(conn, _AID, 3) is False  # type: ignore[arg-type]


async def test_sem_duracao_no_payload_nao_ha_o_que_julgar() -> None:
    conn = _ConnRoteirizado(linhas_da_duracao=[], tem_cardapio=True)
    assert await _duracao_fora_do_cardapio(conn, _AID, None) is False  # type: ignore[arg-type]
