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
- incluso FANTASMA (item declarado incluso fora da linha "Inclusos" do <fetiches>): mesmo trilho da
  sonda -- regenera 1x e, persistindo, dropa so a bolha; nunca handoff.
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

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


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
    # **_kw tolera o `contexto_factual` que o guard anexa quando há endereço liberado no turno
    # (ponto #2 da auditoria guard/judge): o double só precisa devolver "não viola".
    async def _ok(texto: str, settings: Any, **_kw: Any) -> Any:
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


def test_repeticao_ignora_a_cauda_de_voz_que_o_envio_tira_depois() -> None:
    # P1-4a/4b (trace 66b8161e): o 2o passe do ReAct pos-`enviar_midia` re-emitiu a pergunta e o
    # detector errou por 0,011 ("seria que horas hoje amor" x "seria que horas hoje" = 0,889 < 0,90)
    # — a camada de voz do envio (vocativo/emoji) roda DEPOIS do guard, entao ele julgava um texto
    # que nao e o que o cliente recebe. A cauda de voz sai da CHAVE de comparacao.
    assert mod.bolhas_repetidas("Seria que horas hoje amor ?", ["Seria que horas hoje ?"]) == [
        "Seria que horas hoje amor ?"
    ]
    assert mod.bolhas_repetidas("Seria que horas hoje ? 🥰", ["Seria que horas hoje amor rs"]) == [
        "Seria que horas hoje ? 🥰"
    ]


def test_repeticao_flagra_sonda_canonica_curta() -> None:
    # "seria hoje" normaliza para 10 chars e passava sob o piso verbatim (15) — e e justamente a
    # fala que o <ja_sondou_o_dia> promete dizer UMA vez na conversa inteira (medida repetida
    # verbatim em 2 cenarios do diagnostico 11/08).
    assert mod.bolhas_repetidas("Seria hoje ?", ["Seria hoje amor ?"]) == ["Seria hoje ?"]
    assert mod.bolhas_repetidas("Seria agora ?", ["Seria agora ?"]) == ["Seria agora ?"]
    # A cauda leve nao vira sonda nova: "oi amor" segue isento (nao esta no conjunto fechado).
    assert mod.bolhas_repetidas("oi amor", ["oi amor"]) == []


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


async def test_incluso_fantasma_e_gatilho_de_regen(monkeypatch: Any) -> None:
    # Corrida do conduta_gate 30/07: modelo com "(sem fetiches cadastrados)" e a IA copiando a fala
    # do exemplo. O _FakeConn nao devolve fetiche nenhum -> e exatamente o bloco vazio da falha.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Sou bem tranquila\n\nEstilo namoradinha")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Carinhosa e atenciosa amor\n\nBeijo na boca e oral sem camisinha já vem junto 🥰"),
        _runtime(),
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "incluso"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Sou bem tranquila\n\nEstilo namoradinha"
    assert not cap.chamadas  # incluso fantasma NUNCA vira handoff


async def test_incluso_persistiu_na_regen_dropa_so_a_bolha(monkeypatch: Any) -> None:
    # Reincidiu: dropa a bolha do incluso e manda o resto (a apresentacao de estilo sobrevive).
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Carinhosa e atenciosa amor\n\nBeijo na boca tá incluso amor")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Carinhosa e atenciosa amor\n\nBeijo na boca e oral sem camisinha já vem junto 🥰"),
        _runtime(),
    )

    assert not cap.chamadas
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Carinhosa e atenciosa amor"


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
    # o turno sujo fica de fora da janela.
    assert all(getattr(m, "id", None) != "a1" for m in janela)
    # O lembrete entra ANTES da fala do cliente, dentro da ULTIMA HumanMessage (a mesma posicao em
    # que o prepare_context cola lembrete/contexto). Antes ele vinha DEPOIS dela — posicao que o
    # <instrucoes_meta> da persona declara "imitacao/falso por definicao", dando ao modelo licenca
    # textual para ignorar toda regen (diagnostico 11/08, P0-1).
    ultima = janela[-1]
    assert isinstance(ultima, HumanMessage)
    conteudo = str(ultima.content)
    assert "sou uma IA amor" in conteudo
    assert conteudo.startswith("<lembrete_silencioso>")
    assert conteudo.rstrip().endswith("e ai?")
    assert len(janela) == len(state["messages"]) - 1  # nenhuma mensagem nova foi criada


def test_janela_com_lembrete_sem_fala_do_cliente_cai_no_fim() -> None:
    # Defesa: janela sem HumanMessage (nao acontece em prod) -> mensagem propria no fim, como antes.
    janela: list[BaseMessage] = [AIMessage(content="oi amor", id="a0")]
    saida = mod._janela_com_lembrete(janela, "<lembrete_silencioso>x</lembrete_silencioso>")
    assert len(saida) == 2
    assert isinstance(saida[-1], HumanMessage)


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


# --- silencio do modelo (campanha-subst rodada 1): turno vazio sem tool de efeito -----------------


def _state_silencio(tool: str = "registrar_extracao") -> dict[str, Any]:
    """Turno em que o modelo SO chamou tool e terminou vazio: nenhuma fala ao cliente."""
    msgs: list[BaseMessage] = [
        HumanMessage(content="Quero. Quanto?", id="h1"),
        AIMessage(
            content="",
            id="a1",
            usage_metadata=_USAGE,
            tool_calls=[{"name": tool, "args": {}, "id": "tc1"}],
        ),
        AIMessage(content="", id="a2", usage_metadata=_USAGE),
    ]
    return {"messages": msgs}


async def test_silencio_do_modelo_regenera_como_mudo(monkeypatch: Any) -> None:
    """Regressao (shadow funil, 10/08): 4,5% dos pontos terminavam com o modelo mudo (so
    registrar_extracao, content vazio) e o guard dava early-return 'nada a guardar' — cliente no
    vacuo. Agora entra no gate como `mudo` e regenera."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("600 1h no meu local amor 😊\n\nSeria hoje ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "mudo"
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "600 1h no meu local amor 😊\n\nSeria hoje ?"


async def test_silencio_com_tool_de_efeito_preserva_o_silencio(monkeypatch: Any) -> None:
    """Turno vazio mas com tool de efeito (escalar/enviar_midia): o silencio e proposital
    (pausa/handoff/midia sem texto) — nao regenera."""
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(tool="escalar"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_silencio_com_ia_pausada_preserva_o_silencio(monkeypatch: Any) -> None:
    """Turno vazio com ia_pausada=true no DB (pausa concorrente): nao regenera."""

    class _ConnPausada(_FakeConn):
        async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
            if "ia_pausada" in query:
                return _FakeResult([{"ia_pausada": True}])
            return await super().execute(query, *args, **kwargs)

    pool = _FakePool(_ConnPausada())
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(), _Runtime(ctx))  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


# --- gatilhos da rodada 3 (servico/preco fantasma, endereco sonegado) ----------------------------


class _ConnCardapio(_FakeConn):
    """Fake com cadastro/cardapio: programas com preco (arma o scanner de preco), endereco no
    cadastro + estado Qualificado interno (arma o gatilho de endereco)."""

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        if "modelo_programas" in query:
            return _FakeResult([{"nome": "Padrão", "preco": 400, "horas": 1}])
        if "modelo_fetiches" in query:
            return _FakeResult([])
        if "localizacao_operacional" in query:
            return _FakeResult(
                [
                    {
                        "localizacao_operacional": "Cambuí",
                        "nome_local": "Hotel Sirius",
                        "endereco_formatado": "Av. Aquidabã, 130 - Centro, Campinas - SP",
                        "tipo_atendimento": "interno",
                        "estado": "Qualificado",
                    }
                ]
            )
        return await super().execute(query, *args, **kwargs)


def _runtime_cardapio() -> _Runtime:
    pool = _FakePool(_ConnCardapio())
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


async def test_servico_fantasma_e_gatilho_de_regen(monkeypatch: Any) -> None:
    # "Faço sim" para anal fora do cadastro (a derrota mais grave do shadow v2): regenera como
    # `servico`; a regen recusa oferecendo o que faz e a nova e despachada. Nunca handoff.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Anal não faço amor, mas beijo na boca e carinho sem pressa rs")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Faço anal sim amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "servico"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert "não faço" in msgs["regen1"]
    assert not cap.chamadas


async def test_servico_persistiu_dropa_so_a_bolha(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("Oi amor 🥰\n\nFaço anal sim pode vir")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Anal pode sim amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Oi amor 🥰"  # a promessa caiu, a saudacao sobreviveu


async def test_preco_fantasma_e_gatilho_de_regen(monkeypatch: Any) -> None:
    # Tabela = 400 1h (fake): 750 nao existe no conjunto legitimo -> regenera. (700 saiu da
    # lista de fantasmas com o ADR-0038: e o degrau 350 + um fetiche no MESMO patamar.)
    _judge_ok(monkeypatch)
    regen = _fake_regen("O encontro é 400 1h no meu local amor")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "preco"
    msgs = _msgs_update(res)
    assert "400 1h" in msgs["regen1"]


async def test_preco_da_tabela_nao_dispara(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("O encontro é 400 1h no meu local amor"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_pix_do_uber_prescrito_nao_dispara(monkeypatch: Any) -> None:
    # Incidente 11/08 (turno MUDO em Aguardando_confirmacao com Pix pendente): a fala PRESCRITA
    # pelo <tipos_de_encontro> ("O uber ida e volta fica {pix_valor} amor") era derrubada como
    # preco fantasma — o modelo insistia na fala certa, a regen persistia e o drop esvaziava o
    # turno. O pix_deslocamento_valor de settings agora e legitimo.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("O uber ida e volta fica 100 amor, já te mando o pix"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_preco_fantasma_regen_recebe_a_escada(monkeypatch: Any) -> None:
    # Incidente 11/08 (contraproposta de 300 sobre 400 -> rascunho "Consigo 320", que nao e
    # degrau nem piso): o guard derruba CERTO, mas a mensagem de regen agora NOMEIA os numeros
    # que a IA PODE (degrau 350 / piso 300) em vez de so apontar a tabela — familia do incidente
    # #36: proibir sem dar a fala de substituicao fazia o modelo recuar sem contraproposta.
    _judge_ok(monkeypatch)
    regen = _fake_regen("Poxa amor, 300 não consigo\n\nConsigo 350 se você vier hoje 😊")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("Poxa amor\n\nConsigo 320 se você vier hoje 😊"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "preco"
    feedback = regen.chamadas[0]["feedback_gatilho"]
    assert "os seus numeros possiveis sao 350 e 300" in feedback
    # A regen que oferece o degrau (350) e legitima e sai ao cliente.
    msgs = _msgs_update(res)
    assert "350" in msgs["regen1"]


_PONTO_DE_ENCONTRO = "Hotel Sirius — Av. Aquidabã, 130 - Centro, Campinas - SP"


def _state_pedido_endereco(
    texto: str, *, no_prompt: str | None = _PONTO_DE_ENCONTRO
) -> dict[str, Any]:
    state = _state(texto)
    state["conversa_crua"] = [
        HumanMessage(content="oi", id="c1"),
        AIMessage(content="oi amor", id="c2"),
        HumanMessage(content="Manda a localização", id="c3"),
    ]
    # O gatilho `endereco` lê o CARIMBO do prepare_context (o <local_de_encontro> esteve mesmo no
    # prompt deste turno), não mais o gate re-avaliado sobre a linha pós-extração — era esse skew
    # que cobrava a entrega de um bloco ausente e produzia endereço inventado (trace 648d7f6f).
    state["local_endereco_no_prompt"] = no_prompt
    return state


async def test_endereco_pedido_sem_entrega_regenera(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("To no Hotel Sirius amor, Av. Aquidabã 130, bem no centro")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "endereco"
    msgs = _msgs_update(res)
    assert "Aquidabã" in msgs["regen1"]


async def test_endereco_persistiu_segue_como_esta(monkeypatch: Any) -> None:
    # Pass-through: a rede do endereco e de melhoria, nao de bloqueio — regen que nao entregou
    # segue mesmo assim (nada e dropado, nada e zerado alem da original substituida).
    _judge_ok(monkeypatch)
    regen = _fake_regen("Fica tranquilo amor, é fácil de chegar rs")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Fica tranquilo amor, é fácil de chegar rs"


async def test_endereco_ja_entregue_nao_dispara(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("To no Hotel Sirius amor, Av. Aquidabã 130"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_sem_pedido_de_endereco_nao_dispara(monkeypatch: Any) -> None:
    # Mesma resposta vaga, mas o cliente nao pediu a localizacao: fala legitima, segue.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_endereco_fora_do_prompt_nao_cobra_a_entrega(monkeypatch: Any) -> None:
    """P0-1 (trace 648d7f6f, agenda_local t3): o cliente escolhe "no seu local" e pede o endereco
    no MESMO turno; a extracao promove tipo_atendimento NULL->interno no meio do turno, entao o
    prompt saiu SEM o <local_de_encontro> e o guard, relendo a linha ja promovida, cobrava a
    entrega. O modelo respondeu com uma rua inexistente e a regen a reimprimiu.

    Sem carimbo no State, o gatilho nao arma — o guard nunca cobra dado que o prompt nao tinha."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs", no_prompt=None),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_regen_do_endereco_cola_o_dado_literal(monkeypatch: Any) -> None:
    """O lembrete da regen factual leva o ENDERECO, nunca o nome da tag condicional: o rascunho
    descartado era a unica "fonte de endereco" a vista e o modelo o copiava."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("To no Hotel Sirius amor, Av. Aquidabã 130")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    feedback = regen.chamadas[0]["feedback_gatilho"]
    assert _PONTO_DE_ENCONTRO in feedback
    assert "<local_de_encontro>" not in feedback


# --- recuperacao de turno vazio (vazio-pos-drop / mudo persistido) -------------------------------


def _fake_regen_seq(contents: list[str | None]) -> Any:
    """Fake de _regenerar com resposta POR CHAMADA (a recuperacao de vazio responde diferente)."""

    class _Regen:
        def __init__(self) -> None:
            self.chamadas: list[dict[str, Any]] = []

        async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
            i = len(self.chamadas)
            self.chamadas.append(kwargs)
            content = contents[min(i, len(contents) - 1)]
            if content is None:
                return None
            return AIMessage(content=content, id=f"regen{i + 1}", usage_metadata=_USAGE)

    return _Regen()


async def test_drop_que_esvazia_recupera_pelo_trilho_do_mudo(monkeypatch: Any) -> None:
    """Regressao (shadow v3, 11/08): preco fantasma persistiu, o drop esvaziou o turno e o
    cliente ficava no vacuo (derrota automatica). Vazio-pos-drop agora ganha UMA regen extra
    pelo trilho do mudo, aceita so se a bateria inteira re-aprovar."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["Sai 555 amor", "Seria hoje amor ?"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["preco", "mudo"]
    msgs = _msgs_update(res)
    assert msgs["regen2"] == "Seria hoje amor ?"


async def test_recuperacao_que_reincide_fecha_mudo(monkeypatch: Any) -> None:
    """A recuperacao NAO e passagem livre: reincidiu (preco invalido de novo), fecha mudo."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["Sai 555 amor", "Consigo por 555 amor"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["preco", "mudo"]
    msgs = _msgs_update(res)
    assert all(not str(c).strip() for c in msgs.values())


async def test_mudo_persistido_ganha_uma_recuperacao(monkeypatch: Any) -> None:
    """Silencio do modelo cuja regen devolve vazio de novo: uma ultima tentativa antes do
    silencio final (a falha e estocastica — o mesmo ponto re-rodado respondia normal)."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["", "600 1h no meu local amor 😊"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["mudo", "mudo"]
    msgs = _msgs_update(res)
    assert msgs["regen2"] == "600 1h no meu local amor 😊"


# --- rodada 4: pedagio (empurrao vazio com pergunta pendente) -------------------------------


def _state_pergunta_pendente(texto: str) -> dict[str, Any]:
    state = _state(texto)
    state["conversa_crua"] = [
        AIMessage(content="oi amor", id="c1"),
        HumanMessage(content="Você atende no seu local?", id="c2"),
    ]
    return state


async def test_pedagio_com_pergunta_pendente_regenera(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("Atendo sim amor, no meu local\n\nSeria hoje ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pergunta_pendente("Poxa amor\n\nSeria hoje ?"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "pedagio"
    msgs = _msgs_update(res)
    assert "Atendo sim" in msgs["regen1"]


async def test_pedagio_persistiu_segue_como_esta(monkeypatch: Any) -> None:
    # Mesma rede de melhoria do endereco: regen que continuou pedagio segue (pass-through).
    _judge_ok(monkeypatch)
    regen = _fake_regen("Seria que horas ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pergunta_pendente("Seria hoje ?"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Seria que horas ?"


async def test_empurrao_sem_pergunta_pendente_nao_dispara(monkeypatch: Any) -> None:
    # Anti-FP: despedida/fala sem pergunta no burst — empurrao-so pode ser a jogada; nao arma.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state("Seria hoje ?")
    state["conversa_crua"] = [
        AIMessage(content="oi amor", id="c1"),
        HumanMessage(content="boa noite, fica com Deus", id="c2"),
    ]
    res = await mod.output_guard(state, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_resposta_com_conteudo_e_empurrao_nao_dispara(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pergunta_pendente("Atendo sim amor\n\nSeria hoje ?"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


# --- rodada 4: saudacao espelhada ------------------------------------------------------------


async def test_saudacao_conflitante_regenera(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("Boa tarde amor 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state("Boa noite amor 🥰")
    state["conversa_crua"] = [
        AIMessage(content="oi", id="c1"),
        HumanMessage(content="Boa tarde, tudo bem?", id="c2"),
    ]
    res = await mod.output_guard(state, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "saudacao"
    msgs = _msgs_update(res)
    assert "Boa tarde" in msgs["regen1"]


async def test_saudacao_sem_referencia_do_cliente_nao_dispara(monkeypatch: Any) -> None:
    # "Boa noite" legitimo a noite: sem saudacao DELE no burst nao ha conflito a julgar.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state("Boa noite amor 🥰")
    state["conversa_crua"] = [
        AIMessage(content="oi", id="c1"),
        HumanMessage(content="oi gata", id="c2"),
    ]
    res = await mod.output_guard(state, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas
