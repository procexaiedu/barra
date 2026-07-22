"""Gate pre-envio com regeneracao one-shot + detector de repeticao (output_guard, producao assistida).

Unit test sem DB/LLM (mesmo rig do test_output_guard.py): `_regenerar`/`_julgar_aup`/`abrir_handoff`
sao trocados por fakes; conn/pool fakes. Cobre:

- detector puro `bolhas_repetidas`: bolha longa quase identica a bolha recente da IA flagra;
  cumprimento curto, reformulacao real e negacao canned NAO flagram; duplicata dentro do turno flagra.
- regen LIMPOU: leak/repeticao/mudo no texto -> regenera 1x -> despacha a nova (originais zeradas,
  nova anexada), sem handoff.
- regen PERSISTIU: leak -> bloqueia + handoff (nova tambem zerada); repeticao -> dropa a bolha
  repetida (silencio > papagaio), sem handoff.
- regen DESLIGADA (flag): leak volta ao comportamento antigo (bloqueio direto, sem chamada);
  repeticao dropa direto das mensagens originais.
- leak em LEGENDA e nao-regeneravel: bloqueia sem tentar regen.
- judge (Etapa 2) roda tambem sobre o texto regenerado: viola -> bloqueia tudo.
- `_regenerar` (unit): monta a janela ate ANTES do turno + lembrete; recusa/excecao -> None.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END

from barra.agente._canned import NEGACOES_CANNED
from barra.agente.contexto import ContextAgente
from barra.settings import get_settings

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo; importlib pega o modulo
# real p/ monkeypatch (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")
mod_defesa = importlib.import_module("barra.agente._defesa")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    def __init__(self, legendas: list[str] | None = None) -> None:
        self._legendas = legendas or []

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        if "enviar_midia" in query:
            return _FakeResult([{"legenda": leg} for leg in self._legendas])
        return _FakeResult([])


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime(legendas: list[str] | None = None) -> _Runtime:
    pool = _FakePool(_FakeConn(legendas))
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _state(texto: str, historico: list[str] | None = None) -> dict[str, Any]:
    """Janela minima: historico (AIMessages SEM usage = ja enviadas) + a bolha do turno (com usage)."""
    msgs: list[BaseMessage] = [HumanMessage(content="oi", id="h1")]
    for i, h in enumerate(historico or []):
        msgs.append(AIMessage(content=h, id=f"hist{i}"))
    msgs.append(HumanMessage(content="e ai?", id="h2"))
    msgs.append(AIMessage(content=texto, id="a1", usage_metadata=_USAGE))
    return {"messages": msgs}


class _Capturador:
    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, conn: Any, **kwargs: Any) -> None:
        self.chamadas.append(kwargs)


def _fake_regen(content: str | None) -> Any:
    """Fake de _regenerar: devolve a AIMessage regenerada (ou None = indisponivel) e grava a chamada."""

    class _Regen:
        def __init__(self) -> None:
            self.chamadas: list[dict[str, Any]] = []

        async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
            self.chamadas.append(kwargs)
            if content is None:
                return None
            return AIMessage(content=content, id="regen1", usage_metadata=_USAGE)

    return _Regen()


def _judge_ok(monkeypatch: Any) -> None:
    async def _ok(texto: str, settings: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)


def _msgs_update(res: Any) -> dict[str, Any]:
    return {m.id: m.content for m in (res.update or {}).get("messages", [])}


# --- detector puro -------------------------------------------------------------------------------

_BOLHA_LONGA = "então amor, qual horário fica melhor pra você vir aqui hoje?"


def test_repeticao_flagra_bolha_quase_identica_ao_historico() -> None:
    # variacao minima (pontuacao/emoji) da mesma pergunta ja enviada = rastro de papagaio.
    quase = "Então amor, qual horário fica melhor pra você vir aqui hoje 🥰"
    assert mod.bolhas_repetidas(quase, [_BOLHA_LONGA]) == [quase]


def test_repeticao_nao_flagra_cumprimento_curto() -> None:
    # "oi amor" repete legitimamente (abaixo de _REPETICAO_MIN_VERBATIM chars normalizados).
    assert mod.bolhas_repetidas("oi amor", ["oi amor", _BOLHA_LONGA]) == []


def test_repeticao_flagra_bolha_de_preco_curta_verbatim() -> None:
    # onda 1 finding C: "400 1h no meu local" (19 chars normalizados) passava sob o piso fuzzy de
    # 25 e o papagaio literal ia ao cliente. Reenvio EXATO agora conta pelo piso verbatim.
    preco = "400 1h no meu local"
    assert mod.bolhas_repetidas(preco, [preco]) == [preco]


def test_repeticao_verbatim_isenta_saudacao_media() -> None:
    # "boa tarde amor" (14 chars) segue isento mesmo verbatim: fica abaixo do piso verbatim (15),
    # onde a repeticao de saudacao ainda e legitima.
    assert mod.bolhas_repetidas("boa tarde amor", ["boa tarde amor"]) == []


def test_repeticao_nao_flagra_reformulacao_real() -> None:
    # reformulacao humana ("como te falei...") cai abaixo do limiar de similaridade.
    reform = "como te falei amor: 400 a hora aqui no meu local, perto do centro"
    assert mod.bolhas_repetidas(reform, ["o valor de 1h é 400 no meu local amor"]) == []


def test_repeticao_flagra_duplicata_dentro_do_mesmo_turno() -> None:
    turno = f"{_BOLHA_LONGA}\n\n{_BOLHA_LONGA}"
    assert mod.bolhas_repetidas(turno, []) == [_BOLHA_LONGA]


def test_repeticao_isenta_negacao_canned() -> None:
    canned = next(iter(NEGACOES_CANNED))
    assert mod.bolhas_repetidas(canned, [canned]) == []


def test_bolhas_historicas_so_mensagens_ja_enviadas() -> None:
    state = _state("nova fala do turno", historico=["primeira\n\nsegunda"])
    historicas = mod._bolhas_historicas(state["messages"])
    # a bolha do turno (com usage) fica de fora; o historico quebra por \n\n.
    assert historicas == ["primeira", "segunda"]


# --- fluxo: regen limpou --------------------------------------------------------------------------


async def test_leak_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("consigo sim amor, me chama que combinamos 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "leak"
    msgs = _msgs_update(res)
    # original zerada + regenerada anexada (id novo, texto limpo).
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "consigo sim amor, me chama que combinamos 🥰"
    assert not cap.chamadas  # limpou -> sem handoff


async def test_repeticao_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("me conta amor, conseguiu ver o horário? 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_BOLHA_LONGA, historico=[_BOLHA_LONGA]), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "repeticao"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "me conta amor, conseguiu ver o horário? 🥰"
    assert not cap.chamadas


async def test_mudo_por_saneamento_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    # turno 100%-raciocinio: antes ficava mudo; com regen, vira fala de verdade.
    _judge_ok(monkeypatch)
    regen = _fake_regen("oi amor, me conta o que você procura?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("o cliente demonstrou interesse, meu próximo passo é cotar"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "mudo"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "oi amor, me conta o que você procura?"


async def test_sonda_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    # Regressao (lead RNine, 22/07): a sonda era dropada em silencio no Estagio 0 e o turno saia so
    # com o cumprimento, emperrando a conversa. Agora ela e gatilho de regen e a fala volta inteira.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Tudo bem sim amor 🥰\n\nEstá aqui na cidade ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Tudo bem sim amor 🥰\n\nO que você procura ?"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "sonda"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Tudo bem sim amor 🥰\n\nEstá aqui na cidade ?"
    assert not cap.chamadas


# --- fluxo: regen persistiu -----------------------------------------------------------------------


async def test_leak_persistiu_na_regen_bloqueia_e_zera_tudo(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("continuo sendo uma IA amor")  # regen tambem vaza
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert len(cap.chamadas) == 1  # handoff aberto (fallback pre-regen)
    msgs = _msgs_update(res)
    assert msgs["a1"] == "" and msgs["regen1"] == ""  # nada sai ao cliente, nem a regen


async def test_repeticao_persistiu_na_regen_fica_mudo_sem_handoff(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen(_BOLHA_LONGA)  # regen repete de novo
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_BOLHA_LONGA, historico=[_BOLHA_LONGA]), _runtime()
    )

    assert res.goto == END
    assert not cap.chamadas  # repeticao NUNCA vira handoff: silencio > papagaio
    msgs = _msgs_update(res)
    assert msgs["a1"] == "" and msgs["regen1"] == ""


async def test_sonda_persistiu_na_regen_dropa_so_o_probe(monkeypatch: Any) -> None:
    # Reincidiu: cai no fallback de hoje (drop da bolha ofensora), mas o resto da fala sai.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Tudo bem sim amor 🥰\n\nO que você busca ?")  # sonda de novo
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Tudo bem sim amor 🥰\n\nO que você procura ?"), _runtime()
    )

    assert not cap.chamadas  # sonda NUNCA vira handoff
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Tudo bem sim amor 🥰"


# --- fluxo: regen desligada/indisponivel ----------------------------------------------------------


async def test_flag_desligada_leak_bloqueia_direto_sem_regen(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("nunca deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)
    settings = get_settings().model_copy(update={"output_guard_regen_habilitado": False})
    monkeypatch.setattr(mod, "get_settings", lambda: settings)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert not regen.chamadas  # kill-switch: comportamento antigo
    assert len(cap.chamadas) == 1
    assert _msgs_update(res)["a1"] == ""


async def test_repeticao_sem_regen_dropa_a_bolha_e_mantem_a_fresca(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    settings = get_settings().model_copy(update={"output_guard_regen_habilitado": False})
    monkeypatch.setattr(mod, "get_settings", lambda: settings)

    fresca = "consegue chegar aqui pra que horas amor?"
    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(f"{_BOLHA_LONGA}\n\n{fresca}", historico=[_BOLHA_LONGA]), _runtime()
    )

    assert not cap.chamadas
    # a repetida sai; a fresca segue ao cliente na PROPRIA mensagem reescrita (mesmo id).
    assert _msgs_update(res)["a1"] == fresca


# --- fronteiras: legenda e judge ------------------------------------------------------------------


async def test_leak_em_legenda_bloqueia_sem_tentar_regen(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("nunca deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("fala limpa amor"), _runtime(legendas=["sou uma IA nessa foto"])
    )

    assert not regen.chamadas  # legenda ja persistiu como arg de tool: nao-regeneravel
    assert len(cap.chamadas) == 1
    assert _msgs_update(res)["a1"] == ""


async def test_judge_roda_sobre_o_texto_regenerado_e_pode_bloquear(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("fala regenerada que o judge reprova")
    monkeypatch.setattr(mod, "_regenerar", regen)
    julgados: list[str] = []

    async def _viola(texto: str, settings: Any) -> Any:
        julgados.append(texto)
        return mod._VeredictoAup(viola=True, motivo="aup_dura")

    monkeypatch.setattr(mod, "_julgar_aup", _viola)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert julgados == ["fala regenerada que o judge reprova"]  # a regen NAO pula o judge
    assert len(cap.chamadas) == 1
    msgs = _msgs_update(res)
    assert msgs["a1"] == "" and msgs["regen1"] == ""


# --- _regenerar (unit) ----------------------------------------------------------------------------


class _FakeChat:
    def __init__(self, resp: AIMessage | Exception) -> None:
        self._resp = resp
        self.janelas: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self.janelas.append(list(messages))
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


async def test_regenerar_corta_o_turno_e_anexa_o_lembrete(monkeypatch: Any) -> None:
    resp = AIMessage(content="nova fala", id="r1", usage_metadata=_USAGE)
    chat = _FakeChat(resp)
    mod_llm = importlib.import_module("barra.core.llm")
    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", lambda *a, **kw: chat)

    state = _state("sou uma IA amor", historico=["fala antiga"])
    msgs_turno = [m for m in state["messages"] if getattr(m, "usage_metadata", None)]
    out = await mod._regenerar(
        state["messages"],
        msgs_turno,
        rascunho="sou uma IA amor",
        gatilho="leak",
        settings=get_settings(),
    )

    assert out is resp
    janela = chat.janelas[0]
    # a janela termina no lembrete_silencioso com o rascunho; o turno sujo fica de fora.
    assert all(getattr(m, "id", None) != "a1" for m in janela)
    assert isinstance(janela[-1], HumanMessage)
    assert "sou uma IA amor" in str(janela[-1].content)
    assert "<lembrete_silencioso>" in str(janela[-1].content)


async def test_regenerar_recusa_ou_excecao_devolve_none(monkeypatch: Any) -> None:
    mod_llm = importlib.import_module("barra.core.llm")
    state = _state("sou uma IA amor")
    msgs_turno = [m for m in state["messages"] if getattr(m, "usage_metadata", None)]

    recusa = AIMessage(content="", id="r1", response_metadata={"finish_reason": "content_filter"})
    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", lambda *a, **kw: _FakeChat(recusa))
    assert (
        await mod._regenerar(
            state["messages"], msgs_turno, rascunho="x", gatilho="leak", settings=get_settings()
        )
        is None
    )

    monkeypatch.setattr(
        mod_llm, "criar_chat_deepseek", lambda *a, **kw: _FakeChat(RuntimeError("boom"))
    )
    assert (
        await mod._regenerar(
            state["messages"], msgs_turno, rascunho="x", gatilho="leak", settings=get_settings()
        )
        is None
    )


async def test_excecao_no_guard_deixa_o_turno_mudo(monkeypatch: Any) -> None:
    """Fail-closed: o guard é a última defesa dentro do grafo, então falha DELE (DB fora, bug) não
    pode virar passagem livre — as bolhas do turno vão zeradas para o coordenador."""

    async def _explode(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("pool esgotado")

    monkeypatch.setattr(mod, "_legendas_do_turno", _explode)
    state = _state("consigo sim amor")

    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [m.content for m in res.update["messages"]] == [""]
