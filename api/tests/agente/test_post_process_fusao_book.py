"""post_process: fusao deterministica das bolhas do turno do BOOK (campanha 13/08).

O <midia> manda o texto do turno que envia o book sair em UMA bolha ("o envio do book e um ato
unico ... essa e a UNICA bolha do turno") e a alavanca de prompt FALHOU 0/5 (cenario
duvida_das_fotos: 5/5 corridas com 2-3 bolhas de texto). A garantia virou deterministica no
post_process: turno com book (>= 2 `enviar_midia` executadas) e mais de uma bolha => fusao numa
so, ANTES do output_guard (que re-escaneia a bolha fundida normalmente).

Excecao (documentada no proprio <midia>): o turno que ainda precisa COTAR sai no trilho de 3
bolhas (reconhecimento / valor / linha do book) — preco citado nas bolhas => nao funde. Mesmo
contrato do check `_book_em_uma_bolha` do eval (evals/e2e/massa.py), que so mede o turno da
duvida das fotos, onde o preco ja estava na mesa.
"""

import importlib
import re
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao post_process, sombreando o submodulo; importlib pega o modulo
# real (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.post_process")

_RE_BOLHAS = re.compile(r"\n\s*\n")


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    def __init__(self, ia_pausada: bool) -> None:
        self._ia_pausada = ia_pausada

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult({"ia_pausada": self._ia_pausada})


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime() -> _Runtime:
    pool = _FakePool(_FakeConn(ia_pausada=False))
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _ai_turno(texto: str, _id: str) -> AIMessage:
    # usage_metadata marca a AIMessage como GERADA NESTE turno (mensagens_do_turno).
    return AIMessage(
        content=texto,
        id=_id,
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def _com_book(m: AIMessage, n_midias: int = 3) -> AIMessage:
    """Anexa o rastro do book: `n_midias` tool_calls de `enviar_midia` (foto antes de video)."""
    m.tool_calls = [
        {
            "name": "enviar_midia",
            "args": {"tag": "apresentacao", "tipo": "video" if i == n_midias - 1 else "foto"},
            "id": f"{m.id}-tc{i}",
            "type": "tool_call",
        }
        for i in range(n_midias)
    ]
    return m


def _tool_msgs_do_book(m: AIMessage) -> list[ToolMessage]:
    """Uma ToolMessage de sucesso por tool_call do book (o retorno `_CONFIRMACAO` da tool)."""
    return [
        ToolMessage(
            content=f"{tc['args'].get('tipo', 'foto').capitalize()} de 'apresentacao' anexada "
            "(enviada após o texto).",
            id=f"t-{tc['id']}",
            tool_call_id=tc["id"],
        )
        for tc in m.tool_calls
    ]


def _bolhas(texto: str) -> list[str]:
    return [b for b in _RE_BOLHAS.split(texto) if b.strip()]


async def test_book_com_tres_bolhas_funde_em_uma_na_ordem() -> None:
    """O caso medido 0/5 (duvida_das_fotos, rep3): 3 bolhas num turno de book viram UMA, com o
    conteudo integral na ordem original."""
    a1 = _com_book(
        _ai_turno(
            "Sou eu mesma amor rs\n\nDeixa eu te mostrar melhor\n\nGravei um vídeo pensando em você",
            "a1",
        )
    )
    state = {
        "messages": [HumanMessage(content="essas fotos são suas mesmo ?", id="h1"), a1]
        + _tool_msgs_do_book(a1)
    }
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    (reescrita,) = out["messages"]
    assert reescrita.id == "a1"
    assert len(_bolhas(reescrita.content)) == 1
    # conteudo integral, na ordem
    pos = [reescrita.content.index(t) for t in ("Sou eu mesma", "Deixa eu te mostrar", "Gravei")]
    assert pos == sorted(pos)


async def test_book_com_bolhas_em_duas_passagens_funde_na_primeira_e_esvazia_a_segunda() -> None:
    """Bolha na 1a passagem (com os tool_calls) + bolha na reentrada pos-tools: a fundida fica na
    1a mensagem, a 2a esvazia — o agregado do turno vira uma bolha so."""
    from barra.agente._texto_turno import extrair_texto_do_turno

    a1 = _com_book(_ai_turno("Sou eu mesma amor rs", "a1"))
    a2 = _ai_turno("O que achou amor ?", "a2")
    state = {
        "messages": [
            HumanMessage(content="essas fotos são suas mesmo ?", id="h1"),
            a1,
            *_tool_msgs_do_book(a1),
            a2,
        ]
    }
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    por_id = {m.id: m for m in out["messages"]}
    assert set(por_id) == {"a1", "a2"}
    assert por_id["a2"].content == ""
    assert "Sou eu mesma amor rs" in por_id["a1"].content
    assert "O que achou amor ?" in por_id["a1"].content
    # o agregado do turno (o que o coordenador despacha) e UMA bolha
    novo_state = [HumanMessage(content="x", id="h1"), por_id["a1"], por_id["a2"]]
    assert len(_bolhas(extrair_texto_do_turno(novo_state))) == 1


async def test_book_com_uma_bolha_fica_intocado() -> None:
    """Turno de book ja obediente (1 bolha): nada a fundir, post_process e no-op."""
    a1 = _com_book(_ai_turno("Sou eu mesma amor, gravei um vídeo pra você 🥰", "a1"))
    state = {"messages": [HumanMessage(content="é você ?", id="h1"), a1, *_tool_msgs_do_book(a1)]}
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    assert out == {}


async def test_book_no_trilho_de_cotacao_nao_funde() -> None:
    """Excecao do <midia> ("so o turno que ainda precisa cotar tem as bolhas a mais"): pedido de
    foto ANTES do preco sai no trilho de 3 bolhas (reconhecimento / valor / linha do book), com o
    preco em bolha propria — fundir colaria o preco em outra fala. Preco citado => nao funde."""
    a1 = _com_book(
        _ai_turno("Te mando sim amor\n\n600 1h no meu local\n\nGravei um vídeo pra você 🥰", "a1")
    )
    state = {
        "messages": [HumanMessage(content="me manda uma foto ?", id="h1"), a1]
        + _tool_msgs_do_book(a1)
    }
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    assert out == {}


async def test_sem_book_varias_bolhas_fica_intocado() -> None:
    """Turno de texto comum (sem `enviar_midia`) com varias bolhas: a fusao e SO do book — o
    formato multi-bolha e a voz normal da persona."""
    a1 = _ai_turno("Oii\n\nBoa tarde amor 🥰\n\nTudo bem sim", "a1")
    state = {"messages": [HumanMessage(content="oi, tudo bem?", id="h1"), a1]}
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    assert out == {}


async def test_uma_midia_so_nao_e_book_e_fica_intocado() -> None:
    """1 `enviar_midia` e foto avulsa, nao book (mesmo piso do `_mandou_o_book` do eval)."""
    a1 = _com_book(_ai_turno("Toma amor\n\nGostou ?", "a1"), n_midias=1)
    state = {
        "messages": [HumanMessage(content="manda outra", id="h1"), a1] + _tool_msgs_do_book(a1)
    }
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    assert out == {}


async def test_midias_com_erro_nao_contam_como_book() -> None:
    """2 chamadas de `enviar_midia` mas so 1 executou (a outra errou): nenhum book chegou ao
    cliente — nao funde."""
    a1 = _com_book(_ai_turno("Te mostro sim\n\nJá te mando amor", "a1"), n_midias=2)
    tms = _tool_msgs_do_book(a1)
    tms[1] = ToolMessage(
        content="ERRO: nenhuma mídia tipo 'video' disponível.",
        id=tms[1].id,
        tool_call_id=tms[1].tool_call_id,
        status="error",
    )
    state = {"messages": [HumanMessage(content="é você ?", id="h1"), a1, *tms]}
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    assert out == {}


async def test_turno_com_rastro_de_escalada_fica_intocado() -> None:
    """Book + `escalar` no mesmo turno (rastro de escalada): quem manda e o zeramento/canned da
    pausa — a fusao nao toca o turno."""
    a1 = _com_book(_ai_turno("Um momento amor\n\nJá te respondo", "a1"), n_midias=2)
    a1.tool_calls = [
        *a1.tool_calls,
        {"name": "escalar", "args": {"motivo": "outro"}, "id": "tc-esc", "type": "tool_call"},
    ]
    state = {
        "messages": [
            HumanMessage(content="...", id="h1"),
            a1,
            *_tool_msgs_do_book(a1)[:2],
            ToolMessage(content="escalada aberta", id="t-esc", tool_call_id="tc-esc"),
        ]
    }
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    assert out == {}


async def test_fusao_preserva_tool_calls_usage_e_kwargs() -> None:
    """Reescrita de conteudo, nao zeramento: `tool_calls`, usage_metadata, response_metadata e o
    `additional_kwargs` inteiro (reasoning_content do trace) sobrevivem a fusao."""
    a1 = _com_book(_ai_turno("Sou eu sim\n\nGravei um vídeo pra você", "a1"))
    a1.additional_kwargs = {"reasoning_content": "pensei nisso", "tool_calls": [{"raw": True}]}
    a1.response_metadata = {"model_name": "deepseek-chat"}
    state = {"messages": [HumanMessage(content="é você ?", id="h1"), a1, *_tool_msgs_do_book(a1)]}
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    (reescrita,) = out["messages"]
    assert [tc["name"] for tc in reescrita.tool_calls] == ["enviar_midia"] * 3
    assert reescrita.usage_metadata == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert reescrita.response_metadata == {"model_name": "deepseek-chat"}
    assert reescrita.additional_kwargs["reasoning_content"] == "pensei nisso"
    # ToolMessages nunca sao reescritas: nenhuma entra no update
    assert all(isinstance(m, AIMessage) for m in out["messages"])


async def test_gramatica_da_emenda_ponto_apos_palavra_espaco_apos_pontuacao() -> None:
    """Emenda com a gramatica das bolhas: ponto quando a bolha termina em palavra, so espaco
    quando ja termina em pontuacao/emoji."""
    a1 = _com_book(_ai_turno("Sou eu mesma amor rs\n\nGravei pra você 🥰\n\nVem me ver", "a1"))
    state = {"messages": [HumanMessage(content="é você ?", id="h1"), a1, *_tool_msgs_do_book(a1)]}
    out = await mod.post_process(state, _runtime())  # type: ignore[arg-type]
    (reescrita,) = out["messages"]
    assert reescrita.content == "Sou eu mesma amor rs. Gravei pra você 🥰 Vem me ver"
