"""Flags A2 de memória durável do atendimento: <ja_enviou_book> e sondagem do dia histórica.

As duas disciplinas ("o book vai UMA vez", "a sondagem do dia é UMA vez na conversa inteira")
dependiam da janela de 20 msgs: o evento deslizava pra fora e o LLM repetia. Agora são
MATERIALIZADAS em `atendimentos` (`book_enviado_em`/`dia_sondado_em`, carimbadas no write-time por
workers/envio.py) e `_resolver_variaveis` lê a coluna (recebida por kwarg, sem reescanear falas).
A sondagem histórica ainda entra no OR com a janela em `_anexar_contexto_dinamico`. Sem DB.
"""

from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico, _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

_TS = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)  # instante qualquer: presença = flag ligada


# --- fakes --------------------------------------------------------------------------------------


class _FakeConnVazio:
    """Vazio em tudo: as flags chegam por kwarg (coluna do atendimento), não por query."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx() -> ContextAgente:
    return ContextAgente(
        atendimento_id="22222222-2222-2222-2222-222222222222",
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
    )


async def _resolver(atendimento: dict[str, Any]) -> dict[str, Any]:
    return await _resolver_variaveis(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        atendimento=atendimento,
    )


# --- book: leitura da coluna + reset em atendimento novo ----------------------------------------


async def test_book_ja_enviado_le_coluna_e_reseta_na_recorrencia() -> None:
    com_book = await _resolver({"book_enviado_em": _TS})
    sem_book = await _resolver({})  # atendimento novo do mesmo par nasce sem a flag

    assert com_book["book_ja_enviado"] is True
    assert sem_book["book_ja_enviado"] is False


# --- sondagem do dia: coluna histórica ----------------------------------------------------------


async def test_sondagem_historica_le_coluna() -> None:
    sondou = await _resolver({"dia_sondado_em": _TS})
    nao_sondou = await _resolver({})

    assert sondou["dia_ja_sondado_hist"] is True
    assert nao_sondou["dia_ja_sondado_hist"] is False


async def test_or_janela_historico_injeta_tag_no_contexto() -> None:
    """Janela SEM a sondagem (deslizou pra fora) + coluna COM ela → <ja_sondou_o_dia> na cauda."""
    janela = [
        AIMessage(content="600 1h no meu local"),
        HumanMessage(content="e como funciona?"),
    ]
    mensagens, _fase, _hm = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        janela,
        atendimento={"dia_sondado_em": _TS},
    )
    cauda = str(mensagens[-1].content)
    assert "<ja_sondou_o_dia>" in cauda


# --- render do template -------------------------------------------------------------------------


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_book_enviado_injeta_tag() -> None:
    out = _render(book_ja_enviado=True)
    assert "<ja_enviou_book>" in out
    assert "NÃO reenvie" in out


def test_render_sem_book_nao_injeta_tag() -> None:
    assert "<ja_enviou_book>" not in _render(book_ja_enviado=False)
    assert "<ja_enviou_book>" not in _render()
