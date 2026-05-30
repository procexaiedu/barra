"""TOOLS-06: counter agente_tool_erro_recuperavel_total incrementa num caminho de ERRO recuperavel.

Unit, sem DB: o caminho de data invalida de `consultar_agenda` retorna o 'ERRO:' ANTES de tocar o
pool (db_pool=None prova que nao consultou), entao chamamos a corrotina crua do @tool com um
runtime fake. O registry do prometheus_client e global/compartilhado -> medimos o DELTA por
(tool, motivo) p/ nao colidir com outros testes que tocam o mesmo counter.
"""

from typing import Any

from prometheus_client import REGISTRY

from barra.agente.ferramentas.leitura import consultar_agenda

# .coroutine e a corrotina crua do @tool; .ainvoke({...}) NAO injeta runtime, .coroutine sim.
_chamar = consultar_agenda.coroutine  # type: ignore[attr-defined]


class _Ctx:
    def __init__(self, pool: Any, modelo_id: str) -> None:
        self.db_pool, self.modelo_id = pool, modelo_id


class _Runtime:
    def __init__(self, ctx: _Ctx) -> None:
        self.context = ctx


def _valor(tool: str, motivo: str) -> float:
    valor = REGISTRY.get_sample_value(
        "agente_tool_erro_recuperavel_total", {"tool": tool, "motivo": motivo}
    )
    return valor or 0.0


async def test_erro_recuperavel_incrementa_counter() -> None:
    """Data malformada: ERRO recuperavel + counter{tool=consultar_agenda,motivo=data_invalida}+1."""
    antes = _valor("consultar_agenda", "data_invalida")
    out = await _chamar(
        data_inicio="2026-13-99",
        data_fim="2026-05-20",
        runtime=_Runtime(_Ctx(None, "00000000-0000-0000-0000-000000000000")),
    )
    assert out.startswith("ERRO:")  # texto/comportamento do ERRO preservado
    assert _valor("consultar_agenda", "data_invalida") == antes + 1
