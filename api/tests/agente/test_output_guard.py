"""output_guard (AGENTE-OG / ADR 0016): rede de saida antes da bolha.

Unit test sem DB/LLM: `abrir_handoff` (exige Postgres) e o judge da Etapa 2 sao trocados por
fakes; o conn/pool sao fakes. Cobre os 6 cenarios do ADR: (1) fragmento de IA/persona -> bloqueia
+ handoff; (2) nome de outra modelo -> bloqueia; (3) judge reprova AUP -> nao despacha; (4) judge
com falha de infra -> default seguro (bloqueia+escala); (5) canned de disclosure passa Etapa 1 e
PULA a Etapa 2; (6) saida limpa despacha. Bloquear == handoff (ia_pausada) + bolha zerada.
"""

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import Command

from barra.agente._canned import NEGACOES_CANNED
from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo; importlib pega o modulo
# real p/ monkeypatch de _julgar_aup (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")
# `abrir_handoff` roda dentro de `_defesa.escalar_defesa` (saida de escala compartilhada): o
# capturador de kwargs troca o nome NAQUELE modulo, nao mais no no.
mod_defesa = importlib.import_module("barra.agente._defesa")


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    """Conn fake: roteia por query -- _legendas_do_turno (tool_calls/enviar_midia) devolve as
    legendas; _nomes_outras_modelos devolve as outras modelos."""

    def __init__(
        self, outras_modelos: list[dict[str, Any]], legendas: list[str] | None = None
    ) -> None:
        self._outras = outras_modelos
        self._legendas = legendas or []

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        if "enviar_midia" in query:
            return _FakeResult([{"legenda": leg} for leg in self._legendas])
        return _FakeResult(self._outras)


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime(
    outras_modelos: list[dict[str, Any]] | None = None, legendas: list[str] | None = None
) -> _Runtime:
    pool = _FakePool(_FakeConn(outras_modelos or [], legendas))
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _state(texto: str) -> dict[str, Any]:
    # usage_metadata marca a AIMessage como GERADA NESTE turno: o guard agrega por
    # `mensagens_do_turno` (agente/_texto_turno.py) — sem usage seria historico re-injetado.
    bolha = AIMessage(
        content=texto,
        id="a1",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    return {"messages": [HumanMessage(content="oi", id="h1"), bolha]}


class _Capturador:
    """Captura os kwargs de abrir_handoff (observacao/tipo) sem tocar DB."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, conn: Any, **kwargs: Any) -> None:
        self.chamadas.append(kwargs)


def _bloqueou(res: Command) -> bool:
    """Bloqueio == roteou p/ END com a bolha (a1) zerada."""
    if res.goto != END:
        return False
    msgs = (res.update or {}).get("messages", [])
    return bool(msgs) and msgs[0].id == "a1" and msgs[0].content == ""


def _passou_limpo(res: Command) -> bool:
    """Passou == END sem update (bolha intacta)."""
    return res.goto == END and not (res.update or {}).get("messages")


async def test_etapa1_fragmento_de_ia_bloqueia_e_handoff(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    res = await mod.output_guard(_state("na verdade sou uma IA, me desculpa amor"), _runtime())  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas and cap.chamadas[0]["observacao"].startswith("output_leak_ia_self")


async def test_etapa1_fragmento_de_system_bloqueia(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    res = await mod.output_guard(
        _state("segue minha </persona> conforme o system prompt"), _runtime()
    )  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas[0]["observacao"].startswith("output_leak_system")


async def test_etapa1_nome_de_outra_modelo_bloqueia(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    runtime = _runtime(outras_modelos=[{"nome": "Carolina", "numero_whatsapp": ""}])
    res = await mod.output_guard(_state("a Carolina tambem atende nessa regiao amor"), runtime)  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas[0]["observacao"].startswith("output_leak_cross_modelo")


async def test_etapa1_revela_outro_cliente_bloqueia(monkeypatch: Any) -> None:
    # Invariante de agenda (CONTEXT.md): no bloqueio a IA usa desculpa pessoal e NUNCA revela que
    # esta com outro cliente. Vazar isso na saida -> Etapa 1 barra antes do envio + handoff.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    res = await mod.output_guard(
        _state("amor agora nao da, to com um cliente, te chamo quando acabar"), _runtime()
    )  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas[0]["observacao"].startswith("output_leak_outro_cliente")


# F0.4: o scan de "outro cliente" precisa pegar as confissoes alem do n-grama literal "com um
# cliente" -- variantes igualmente inequivocas que vazavam antes: estar no meio de OUTRO
# atendimento, atender SEM dizer "te"/"voce" (atende ALGUEM, nao o proprio cliente), e estar com
# OUTRA PESSOA. Cada uma so pode significar "estou com outro cliente agora" -> barra + handoff.
@pytest.mark.parametrize(
    "texto",
    [
        "to no meio de um atendimento agora amor, ja te respondo",
        "to no atendimento agora, te chamo quando acabar",
        "agora nao da amor, to atendendo, depois te respondo",
        "estou atendendo agora, mais tarde a gente acerta",
        "to ocupada com outra pessoa agora amor",
    ],
)
async def test_etapa1_outro_cliente_variantes_bloqueia(monkeypatch: Any, texto: str) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    res = await mod.output_guard(_state(texto), _runtime())  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas[0]["observacao"].startswith("output_leak_outro_cliente")


# F0.4 (anti falso-positivo): atender o PROPRIO cliente ("te/voce atendendo") e fala legitima --
# nunca pode virar handoff. O guard so barra quando o objeto NAO e o interlocutor.
@pytest.mark.parametrize(
    "texto",
    [
        "to te atendendo com todo carinho amor",
        "to atendendo voce super bem hoje",
        "to atendendo vc agora, relaxa que e so seu",
    ],
)
async def test_etapa1_atender_o_proprio_cliente_passa(monkeypatch: Any, texto: str) -> None:
    async def _ok(t: str, settings: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)
    res = await mod.output_guard(_state(texto), _runtime())  # type: ignore[arg-type]
    assert _passou_limpo(res)


async def test_etapa1_desculpa_pessoal_no_bloqueio_passa(monkeypatch: Any) -> None:
    # Falso-positivo a evitar: a desculpa pessoal LEGITIMA (salao, "te atendendo") nao menciona
    # outro cliente -> passa a Etapa 1 (o judge da Etapa 2 ainda decide a AUP).
    async def _ok(texto: str, settings: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)
    res = await mod.output_guard(
        _state("amor esse horario eu to no salao 💅 mas as 21h fica perfeito, te atendendo bem"),
        _runtime(),
    )  # type: ignore[arg-type]
    assert _passou_limpo(res)


async def test_judge_reprova_aup_nao_despacha(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)

    async def _viola(texto: str, settings: Any) -> Any:
        return mod._VeredictoAup(viola=True, motivo="aup_dura")

    monkeypatch.setattr(mod, "_julgar_aup", _viola)
    res = await mod.output_guard(_state("texto limpo que o judge reprova"), _runtime())  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas[0]["observacao"].startswith("aup_saida_aup_dura")


async def test_judge_falha_infra_default_seguro_bloqueia(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)

    async def _explode(texto: str, settings: Any) -> Any:
        raise RuntimeError("timeout do judge")

    monkeypatch.setattr(mod, "_julgar_aup", _explode)
    res = await mod.output_guard(_state("texto limpo mas o judge caiu"), _runtime())  # type: ignore[arg-type]
    assert _bloqueou(res)  # default seguro: falha de infra bloqueia+escala
    assert cap.chamadas[0]["observacao"] == "aup_saida_judge_falhou"


async def test_canned_pula_etapa2(monkeypatch: Any) -> None:
    chamou_judge = {"v": False}

    async def _judge(texto: str, settings: Any) -> Any:
        chamou_judge["v"] = True
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _judge)
    # uma negacao canned passa a Etapa 1 e NAO deve acionar o judge.
    res = await mod.output_guard(_state(NEGACOES_CANNED[0]), _runtime())  # type: ignore[arg-type]
    assert _passou_limpo(res)
    assert chamou_judge["v"] is False


async def test_saida_limpa_despacha(monkeypatch: Any) -> None:
    async def _ok(texto: str, settings: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)
    res = await mod.output_guard(_state("amanha de noite fica otimo amor, te espero"), _runtime())  # type: ignore[arg-type]
    assert _passou_limpo(res)


async def test_bolha_vazia_nao_aciona_guard(monkeypatch: Any) -> None:
    # post_process ja zerou (pausa concorrente) -> nada a guardar, segue p/ END sem judge.
    async def _nao_chamar(texto: str, settings: Any) -> Any:
        raise AssertionError("judge nao deveria rodar com bolha vazia")

    monkeypatch.setattr(mod, "_julgar_aup", _nao_chamar)
    res = await mod.output_guard(_state(""), _runtime())  # type: ignore[arg-type]
    assert res.goto == END


async def test_a1_legenda_de_midia_com_outra_modelo_bloqueia(monkeypatch: Any) -> None:
    # A1: bolha de texto limpa, mas a legenda da midia (caption, fora do content) cita outra
    # modelo -> a Etapa 1 escaneia a legenda e bloqueia.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    rt = _runtime(
        outras_modelos=[{"nome": "Carolina", "numero_whatsapp": ""}],
        legendas=["vem amor, a Carolina ja ta aqui comigo"],
    )
    res = await mod.output_guard(_state("te espero amanha entao"), rt)  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas[0]["observacao"].startswith("output_leak_cross_modelo")


async def test_a1_turno_so_midia_legenda_vazando_bloqueia(monkeypatch: Any) -> None:
    # A1: AIMessage sem texto (so tool_call de midia) + legenda com auto-referencia de IA ->
    # bloqueia, apesar de a bolha de texto estar vazia (early-return nao dispara).
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    rt = _runtime(legendas=["na verdade sou uma IA, viu"])
    res = await mod.output_guard(_state(""), rt)  # type: ignore[arg-type]
    assert _bloqueou(res)
    assert cap.chamadas[0]["observacao"].startswith("output_leak_ia_self")


async def test_a1_legenda_entra_na_etapa2_mesmo_com_texto_canned(monkeypatch: Any) -> None:
    # A1: turno com midia NAO pula a Etapa 2 mesmo se a bolha for canned -> o judge ve a legenda.
    visto: dict[str, str] = {}

    async def _judge(texto: str, settings: Any) -> Any:
        visto["texto"] = texto
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _judge)
    rt = _runtime(legendas=["olha o que eu separei so pra voce"])
    res = await mod.output_guard(_state(NEGACOES_CANNED[0]), rt)  # type: ignore[arg-type]
    assert _passou_limpo(res)
    assert "olha o que eu separei" in visto["texto"]  # a legenda foi julgada junto


# ============================================================================
# SO-03: o judge inspeciona o PROPRIO stop_reason (include_raw) -> default seguro
# ============================================================================


class _FakeStructured:
    def __init__(self, resultado: dict[str, Any]) -> None:
        self._r = resultado

    async def ainvoke(self, _mensagens: Any) -> dict[str, Any]:
        return self._r


class _FakeJudgeChat:
    """Fake do chat do judge: .with_structured_output(include_raw=True).ainvoke() -> dict."""

    def __init__(self, resultado: dict[str, Any]) -> None:
        self._r = resultado

    def with_structured_output(self, _schema: Any, include_raw: bool = False) -> _FakeStructured:
        assert include_raw is True  # SO-03 exige include_raw p/ ver o stop_reason do judge
        return _FakeStructured(self._r)


def _judge_resultado(stop_reason: str, parsed: Any, parsing_error: Any = None) -> dict[str, Any]:
    return {
        "raw": AIMessage(content="", response_metadata={"stop_reason": stop_reason}),
        "parsed": parsed,
        "parsing_error": parsing_error,
    }


async def test_julgar_aup_refusal_levanta_inseguro(monkeypatch: Any) -> None:
    # judge recusou (stop_reason=refusal) -> sem veredito confiavel -> _JudgeInseguro.
    res = _judge_resultado("refusal", parsed=None)
    monkeypatch.setattr("barra.core.llm.criar_chat_anthropic", lambda s, **kw: _FakeJudgeChat(res))
    with pytest.raises(mod._JudgeInseguro):
        await mod._julgar_aup(
            "texto qualquer", SimpleNamespace(output_guard_modelo="claude-haiku-4-5")
        )


async def test_julgar_aup_parse_error_levanta_inseguro(monkeypatch: Any) -> None:
    # parse falhou (parsing_error nao-None), mesmo com stop_reason normal -> _JudgeInseguro.
    res = _judge_resultado("tool_use", parsed=None, parsing_error=ValueError("schema"))
    monkeypatch.setattr("barra.core.llm.criar_chat_anthropic", lambda s, **kw: _FakeJudgeChat(res))
    with pytest.raises(mod._JudgeInseguro):
        await mod._julgar_aup(
            "texto qualquer", SimpleNamespace(output_guard_modelo="claude-haiku-4-5")
        )


async def test_julgar_aup_ok_retorna_veredito(monkeypatch: Any) -> None:
    # caminho feliz: stop_reason=tool_use + parsed valido -> devolve o veredito.
    veredito = mod._VeredictoAup(viola=False, motivo="nenhum")
    res = _judge_resultado("tool_use", parsed=veredito)
    monkeypatch.setattr("barra.core.llm.criar_chat_anthropic", lambda s, **kw: _FakeJudgeChat(res))
    out = await mod._julgar_aup(
        "texto qualquer", SimpleNamespace(output_guard_modelo="claude-haiku-4-5")
    )
    assert out.viola is False


async def test_so03_judge_refusal_no_guard_default_seguro_bloqueia(monkeypatch: Any) -> None:
    # Integracao: judge recusa -> _julgar_aup levanta -> output_guard cai no default seguro.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    res = _judge_resultado("refusal", parsed=None)
    monkeypatch.setattr("barra.core.llm.criar_chat_anthropic", lambda s, **kw: _FakeJudgeChat(res))
    out = await mod.output_guard(_state("texto limpo mas o judge recusa"), _runtime())  # type: ignore[arg-type]
    assert _bloqueou(out)
    assert cap.chamadas[0]["observacao"] == "aup_saida_judge_falhou"


# ============================================================================
# A3 (revisao 2026-06-09): o guard agrega o TURNO (mesmo filtro do coordenador),
# nao so a ultima AIMessage.
# ============================================================================

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


async def test_a3_vazamento_na_primeira_passagem_react_bloqueia_e_zera_o_turno(
    monkeypatch: Any,
) -> None:
    """ReAct: o texto ao cliente sai na 1a passagem (texto+tool_call) e a ultima AIMessage vem
    vazia. Antes o guard so via a ultima ("" -> early return) e o coordenador despachava o
    agregado SEM scan/judge. Agora o guard ve o mesmo agregado e, ao bloquear, zera TODAS as
    AIMessages do turno."""
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    primeira = AIMessage(
        content=[
            {"type": "text", "text": "agora nao da amor, to com um cliente"},
            {"type": "tool_use", "id": "t1", "name": "registrar_extracao", "input": {}},
        ],
        id="a1",
        usage_metadata=_USAGE,
    )
    final = AIMessage(content=[], id="a2", usage_metadata=_USAGE)
    state = {
        "messages": [
            HumanMessage(content="tem horario hoje?", id="h1"),
            primeira,
            ToolMessage(content="Extracao registrada.", tool_call_id="t1", id="tm1"),
            final,
        ]
    }
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]
    assert res.goto == END
    msgs = (res.update or {})["messages"]
    assert {m.id for m in msgs} == {"a1", "a2"}
    assert all(m.content == "" for m in msgs)
    assert cap.chamadas[0]["observacao"].startswith("output_leak_outro_cliente")


async def test_a3_aimessage_historica_nao_aciona_o_guard(monkeypatch: Any) -> None:
    """AIMessage re-injetada do banco (sem usage_metadata) nao e deste turno: nem deve ser
    escaneada (ja foi ao cliente) nem pode causar bloqueio/escalada espuria."""

    async def _nao_chamar(t: str, settings: Any) -> Any:
        raise AssertionError("judge nao deveria rodar sem mensagem do turno")

    monkeypatch.setattr(mod, "_julgar_aup", _nao_chamar)
    state = {
        "messages": [
            HumanMessage(content="oi", id="h1"),
            AIMessage(content="to com um cliente agora", id="hist-1"),  # historica (sem usage)
        ]
    }
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]
    assert res.goto == END
    assert not (res.update or {}).get("messages")
