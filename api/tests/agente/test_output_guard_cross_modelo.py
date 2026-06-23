"""_nomes_outras_modelos (output_guard): negativa cross-modelo do banco, sem falso-positivo de vocativo.

Regressao (AGENTE): o scan cross-modelo (Etapa 1) incluia QUALQUER nome de outra modelo com >=4 chars.
Uma modelo cadastrada com nome-de-guerra = vocativo afetuoso comum ("Vida", "Amor") faria TODA bolha
de OUTRA modelo que usa o vocativo bater na negativa cross-modelo -> bloqueio + escalada espuria. O
`_VOCATIVOS_COMUNS` exclui esses nomes; nome artistico normal (Carolina) segue na lista. A Etapa 2
(judge AUP) permanece de backstop para o vazamento raro cujo alvo seja um nome-vocativo.
"""

import importlib
from typing import Any

# nos/__init__ reexporta output_guard; importlib pega o modulo real (memoria "nos/__init__ sombreia").
mod = importlib.import_module("barra.agente.nos.output_guard")


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, *_a: Any, **_k: Any) -> _FakeResult:
        return _FakeResult(self._rows)


async def test_exclui_nome_que_e_vocativo_comum() -> None:
    conn = _FakeConn(
        [
            {"nome": "Vida", "numero_whatsapp": ""},
            {"nome": "Carolina", "numero_whatsapp": ""},
        ]
    )
    termos = await mod._nomes_outras_modelos(conn, "00000000-0000-0000-0000-000000000000")
    assert "Carolina" in termos  # nome artistico normal: entra na negativa cross-modelo
    assert "Vida" not in termos  # vocativo comum: excluido (senao barraria "minha vida" das outras)


async def test_inclui_numero_mesmo_quando_nome_e_vocativo() -> None:
    # O numero nunca colide com vocativo -> segue na lista mesmo que o nome seja excluido.
    conn = _FakeConn([{"nome": "Amor", "numero_whatsapp": "5521999998888"}])
    termos = await mod._nomes_outras_modelos(conn, "x")
    assert "Amor" not in termos
    assert "5521999998888" in termos
