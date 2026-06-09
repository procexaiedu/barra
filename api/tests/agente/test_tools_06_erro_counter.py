"""TOOLS-06: counter agente_tool_erro_recuperavel_total incrementa num caminho de ERRO recuperavel.

Unit, sem DB: o caminho de janela > 14 dias de `consultar_agenda` levanta ToolException ANTES de
tocar o pool (db_pool=None prova que nao consultou), entao chamamos a corrotina crua do @tool com
um runtime fake. (Data malformada deixou de ser caminho do corpo: params tipados `date` validam na
camada de args.) O registry do prometheus_client e global/compartilhado -> medimos o DELTA por
(tool, motivo) p/ nao colidir com outros testes que tocam o mesmo counter.
"""

from datetime import date
from typing import Any

import pytest
from langchain_core.tools import ToolException
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
    """Janela > 14 dias: ToolException + counter{tool=consultar_agenda,motivo=janela_excedida}+1."""
    antes = _valor("consultar_agenda", "janela_excedida")
    with pytest.raises(ToolException, match=r"^ERRO:"):  # texto/prefixo do ERRO preservado
        await _chamar(
            data_inicio=date(2026, 5, 1),
            data_fim=date(2026, 5, 20),
            runtime=_Runtime(_Ctx(None, "00000000-0000-0000-0000-000000000000")),
        )
    assert _valor("consultar_agenda", "janela_excedida") == antes + 1
