"""Flags A2 de memória durável do atendimento: <ja_enviou_book> e sondagem do dia histórica.

As duas disciplinas ("o book vai UMA vez", "a sondagem do dia é UMA vez na conversa inteira")
dependiam da janela de 20 msgs: o evento deslizava pra fora e o LLM repetia. Agora derivam da
mesma leva de falas da IA do atendimento (`_resolver_variaveis`, junto de `n_contrapropostas`):
mídia de saída persiste em `mensagens` com tipo='imagem' (workers/envio.py) → `book_ja_enviado`;
a sondagem histórica (`_PROBE_DIA_HOJE`) entra no OR com a janela em `_anexar_contexto_dinamico`.
Sem DB (fakes no padrão de test_contraproposta_flag.py).
"""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico, _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

# --- fakes (padrão test_contraproposta_flag) ------------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConnFalasIa:
    """Falas da IA indexadas por atendimento_id, cada uma como (conteudo, tipo)."""

    def __init__(self, falas_por_atendimento: dict[str, list[tuple[str, str]]]) -> None:
        self._falas = falas_por_atendimento

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        if "barravips.mensagens" in sql:
            falas = self._falas.get(params[0], [])
            return _Result([{"conteudo": c, "tipo": t} for c, t in falas])
        return _Result([])


def _ctx(atendimento_id: str) -> ContextAgente:
    return ContextAgente(
        atendimento_id=atendimento_id,
        db_pool=None,
        redis=None,
        modelo_id="11111111-1111-1111-1111-111111111111",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
    )


# --- book: derivação + reset em atendimento novo --------------------------------------------------


async def test_book_ja_enviado_por_midia_do_atendimento_e_reseta_na_recorrencia() -> None:
    conn = _FakeConnFalasIa(
        {
            "com-book": [("Oii", "texto"), ("", "imagem"), ("", "imagem")],
            "sem-book": [("Oii", "texto"), ("600 1h no meu local", "texto")],
        }
    )
    com_book = await _resolver_variaveis(conn, _ctx("com-book"))  # type: ignore[arg-type]
    sem_book = await _resolver_variaveis(conn, _ctx("sem-book"))  # type: ignore[arg-type]

    assert com_book["book_ja_enviado"] is True
    # atendimento novo do mesmo par (recorrência) nasce sem a flag: pode mandar book de novo
    assert sem_book["book_ja_enviado"] is False


# --- sondagem do dia: histórico fora da janela ----------------------------------------------------


async def test_sondagem_historica_sobrevive_ao_deslize_da_janela() -> None:
    conn = _FakeConnFalasIa(
        {
            "sondou-antes": [("Seria hoje ?", "texto")],
            "nunca-sondou": [("Oii", "texto")],
        }
    )
    sondou = await _resolver_variaveis(conn, _ctx("sondou-antes"))  # type: ignore[arg-type]
    nao_sondou = await _resolver_variaveis(conn, _ctx("nunca-sondou"))  # type: ignore[arg-type]

    assert sondou["dia_ja_sondado_hist"] is True
    assert nao_sondou["dia_ja_sondado_hist"] is False

    # legenda de mídia não é sondagem; conteudo vazio não explode
    conn2 = _FakeConnFalasIa({"a": [("", "imagem")]})
    assert (await _resolver_variaveis(conn2, _ctx("a")))["dia_ja_sondado_hist"] is False  # type: ignore[arg-type]


async def test_or_janela_historico_injeta_tag_no_contexto() -> None:
    """Janela SEM a sondagem (deslizou pra fora) + histórico COM ela → <ja_sondou_o_dia> na cauda."""
    conn = _FakeConnFalasIa({"atd": [("Seria hoje ?", "texto")]})
    janela = [
        AIMessage(content="600 1h no meu local"),
        HumanMessage(content="e como funciona?"),
    ]
    mensagens, _fase, _hm = await _anexar_contexto_dinamico(conn, _ctx("atd"), janela)  # type: ignore[arg-type]
    cauda = str(mensagens[-1].content)
    assert "<ja_sondou_o_dia>" in cauda


# --- render do template ---------------------------------------------------------------------------


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
