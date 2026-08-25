"""Ciclo 3 da campanha 13/08 — os dois defeitos do lote, no output_guard.

D1 — PROMESSA DE MIDIA sem tool (eb03:32904415564000 t7/t10): "Manda video da seu corpo inteiro"
     rendeu "Te mando sim 🥰 / Mas me confirma o horario certinho" — promessa verbal SEM
     `enviar_midia` no turno, condicionada a confirmacao (a forma exata do deadlock do c2) — e em
     t10 a promessa nua de novo. Gatilho novo `promessa_midia` (rede de MELHORIA): regen com
     conduta substituta (a regen nao chama tool: remove a promessa e segue o fechamento, ou nega
     em personagem); persistiu -> pass-through. Nao arma com `enviar_midia` executada no turno
     (mesmo rastro da fusao do book), pos-escalada, pausado, nem promessa negada na frase.

D2 — CAUDA PASSIVA por FAMILIA (3a aparicao de variantes): "Me chama quando organizar"
     (eb01:219739251032218 t3 do c3-rerun), "Me chama quando conseguir", "Fico no aguardo"
     (eb02:142133503778852 t6 — frase que o proprio prompt nomeia como proibida). O verbo depois
     do "quando" deixa de ser lista fechada; a lista fechada que fica e a EXCECAO de execucao
     ("quando chegar/sair/estiver..."). O veto de passo concreto segue na ULTIMA bolha: o caso
     real do c2 (eb01, fixado em teste) tem 1h/2h/700 nas bolhas anteriores do mesmo turno.

Unit tests sem DB/LLM (mesmo rig de test_output_guard_ciclo2.py): fakes de conn/pool/regen/judge.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from barra.agente.contexto import ContextAgente

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
    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult([])


class _FakePool:
    @asynccontextmanager
    async def connection(self) -> Any:
        yield _FakeConn()


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime() -> _Runtime:
    ctx = ContextAgente(
        db_pool=_FakePool(),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _state(
    texto: str,
    *,
    fala_cliente: str = "oi",
    midia_ok: bool = False,
    midia_erro: bool = False,
) -> dict[str, Any]:
    """State minimo do turno; `midia_ok`/`midia_erro` anexam o rastro de `enviar_midia`
    (tool_call na AIMessage + ToolMessage de sucesso/erro — o criterio da fusao do book)."""
    msgs: list[BaseMessage] = [HumanMessage(content=fala_cliente, id="h1")]
    tool_calls = (
        [{"name": "enviar_midia", "id": "tc1", "args": {}}] if midia_ok or midia_erro else []
    )
    msgs.append(AIMessage(content=texto, id="a1", usage_metadata=_USAGE, tool_calls=tool_calls))
    if midia_ok:
        msgs.append(ToolMessage(content="midia enviada", tool_call_id="tc1"))
    if midia_erro:
        msgs.append(ToolMessage(content="ERRO: midia indisponivel", tool_call_id="tc1"))
    return {
        "messages": msgs,
        "conversa_crua": [HumanMessage(content=fala_cliente, id="h1")],
    }


def _judge_ok(monkeypatch: Any) -> None:
    async def _ok(texto: str, settings: Any, **kwargs: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)


class _FakeRegen:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
        self.chamadas.append(kwargs)
        if self.content is None:
            return None
        return AIMessage(content=self.content, id="regen1", usage_metadata=_USAGE)


def _msgs_update(res: Any) -> dict[str, str]:
    return {m.id: str(m.content) for m in (res.update or {}).get("messages", [])}


# --- D1: promessa de midia sem tool ---------------------------------------------------------------

# O pedido REAL do dump (c3-lote/eb03_32904415564000_lid.json): repetido em t6, t7, t10.
_PEDIDO_MIDIA = "Manda vídeo da seu corpo inteiro"
# As duas bolhas REAIS que prometeram sem tool: t7 (condicionada a confirmacao) e t10 (nua).
_TURNO_T7 = "Te mando sim 🥰\n\nMas me confirma o horário certinho, que horas você quer ?"
_TURNO_T10 = "Te mando sim"


def test_d1_pedido_de_midia_no_burst() -> None:
    assert mod.pediu_midia_no_burst(["Oi", _PEDIDO_MIDIA]) is True
    assert mod.pediu_midia_no_burst(["manda vídeo da seu corpo inteiro", "sem roupa"]) is True
    # pedido de TEXTO nao e pedido de midia — "te mando o endereco" depois dele e legitimo.
    assert mod.pediu_midia_no_burst(["manda seu endereço", "que horas você atende?"]) is False


@pytest.mark.parametrize(
    ("turno", "ofensora"),
    [
        (_TURNO_T7, "Te mando sim 🥰"),
        (_TURNO_T10, "Te mando sim"),
    ],
)
def test_d1_detecta_as_promessas_reais(turno: str, ofensora: str) -> None:
    assert mod.bolhas_promessa_de_midia(turno, pediu_midia=True) == [ofensora]


def test_d1_substantivo_de_midia_arma_sem_pedido_no_burst() -> None:
    # promessa espontanea com o objeto explicito: nao depende do burst.
    assert mod.bolhas_promessa_de_midia("Vou te mandar um vídeo meu depois amor", pediu_midia=False)


@pytest.mark.parametrize(
    "turno",
    [
        # objeto de TEXTO: promessa legitima (endereco/numero/confirmacao nao sao midia).
        "Te mando o endereço certinho",
        "Já te mando a localização amor",
        # PASSADO: reenvio ja feito ("te mandei" nao e promessa).
        "Te mandei as fotos amor",
        # promessa NEGADA na propria frase: recusar e conduta valida.
        "Não vou mandar vídeo amor",
        # fala DELE citada ("me manda" e pedido do cliente, nao promessa da modelo).
        "me manda foto sua",
    ],
)
def test_d1_nao_flagra_promessa_legitima(turno: str) -> None:
    assert mod.bolhas_promessa_de_midia(turno, pediu_midia=True) == []


def test_d1_promessa_nua_sem_pedido_no_burst_nao_arma() -> None:
    # mundo fechado: sem objeto na frase e sem pedido de midia no burst, nada a prometer.
    assert mod.bolhas_promessa_de_midia(_TURNO_T10, pediu_midia=False) == []


def test_d1_rastro_de_enviar_midia() -> None:
    ok = _state("Te mando sim", midia_ok=True)
    erro = _state("Te mando sim", midia_erro=True)
    sem = _state("Te mando sim")
    msgs_ok = [m for m in ok["messages"] if isinstance(m, AIMessage)]
    msgs_erro = [m for m in erro["messages"] if isinstance(m, AIMessage)]
    msgs_sem = [m for m in sem["messages"] if isinstance(m, AIMessage)]
    assert mod.turno_enviou_midia(msgs_ok, ok["messages"]) is True
    # midia que errou NAO chegou ao cliente — a promessa segue vazia.
    assert mod.turno_enviou_midia(msgs_erro, erro["messages"]) is False
    assert mod.turno_enviou_midia(msgs_sem, sem["messages"]) is False


def test_d1_feedback_do_gatilho_nomeia_o_proibido_e_a_substituta() -> None:
    # Incidente #36: nomear o proibido E a direcao (intencao, nunca frase literal). A regen nao
    # chama tool: a substituta e seguir sem prometer (ou negar), nunca "envie agora".
    feedback = mod._FEEDBACK_GATILHO["promessa_midia"]
    assert "promet" in feedback and "condicione" in feedback


async def test_d1_dispara_regen_com_gatilho_promessa_midia(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Consigo hoje às 20h amor, fecha pra você?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_TURNO_T7, fala_cliente=_PEDIDO_MIDIA), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "promessa_midia"
    # veto GRANULAR: so a bolha da promessa; o resto do rascunho e aproveitavel.
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == ["Te mando sim 🥰"]
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Consigo hoje às 20h amor, fecha pra você?"


async def test_d1_com_enviar_midia_ok_no_turno_nao_dispara(monkeypatch: Any) -> None:
    # A midia SAIU neste turno: "te mando sim" e o anuncio legitimo do envio.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_TURNO_T7, fala_cliente=_PEDIDO_MIDIA, midia_ok=True), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas


async def test_d1_persistiu_na_regen_e_pass_through(monkeypatch: Any) -> None:
    # Rede de MELHORIA: persistiu -> o texto segue como esta (t10 real e a bolha UNICA do turno:
    # dropar = mudo, a pior saida medida no shadow); nunca handoff nem mudo.
    cap_handoff: list[Any] = []

    async def _handoff(conn: Any, **kwargs: Any) -> None:
        cap_handoff.append(kwargs)

    monkeypatch.setattr(mod_defesa, "abrir_handoff", _handoff)
    _judge_ok(monkeypatch)
    regen = _FakeRegen(_TURNO_T10)  # reincide
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_TURNO_T10, fala_cliente=_PEDIDO_MIDIA), _runtime()
    )

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == _TURNO_T10  # saiu como esta
    assert not cap_handoff


# --- D2: cauda passiva por familia ----------------------------------------------------------------

# As tres falas REAIS do ciclo 3: eb01:219739251032218 t3 (c3-rerun), o lexico que a recusa dura
# mascarou no lote, e eb02:142133503778852 t6 — a frase que o PROPRIO prompt nomeia como proibida.
_TURNOS_D2 = [
    "Tabom amor\n\nMe chama quando organizar",
    "Que bom que você gosta rs\n\nMe chama quando conseguir",
    "Fico no aguardo",
]


@pytest.mark.parametrize("turno", _TURNOS_D2)
def test_d2_detecta_as_tres_variantes_reais(turno: str) -> None:
    assert mod.bolhas_despedida_passiva(turno) == [turno.split("\n\n")[-1]]


@pytest.mark.parametrize(
    "turno",
    [
        # familia do aguardo sem "quando" — variantes proximas das reais
        "Aguardo seu retorno",
        "Fico aguardando você amor",
        "Me manda mensagem quando puder",
    ],
)
def test_d2_familia_generalizada_flagra(turno: str) -> None:
    assert mod.bolhas_despedida_passiva(turno) == [turno]


@pytest.mark.parametrize(
    "turno",
    [
        # excecao de EXECUCAO + hora concreta na mesma bolha (o FP levantado no ciclo 3)
        "Me chama quando chegar amor, te espero às 14h",
        # excecao de execucao SOZINHA: coordenar a chegada nao e devolver a iniciativa
        "Me chama quando você chegar",
        "me avisa quando estiver chegando amor",
        # fronteira pre-existente do c2, tem de continuar valendo
        "te espero rs, me avisa quando sair",
    ],
)
def test_d2_nao_flagra_coordenacao_de_execucao(turno: str) -> None:
    assert mod.bolhas_despedida_passiva(turno) == []


def test_d2_veto_de_passo_concreto_segue_na_ultima_bolha() -> None:
    # Decisao do ciclo 3: o veto NAO olha o turno inteiro — o caso real do c2 (eb01) tem 1h/2h/700
    # nas bolhas ANTERIORES e a cauda passiva na ultima; digito de duracao/preco nao e passo
    # proposto. Este teste fixa a decisao com o lexico novo.
    turno = "O encontro é 1h, até 2h fica 700\n\nMe chama quando organizar"
    assert mod.bolhas_despedida_passiva(turno) == ["Me chama quando organizar"]


async def test_d2_recusa_dura_no_burst_nao_dispara(monkeypatch: Any) -> None:
    # O caso "Me chama quando conseguir" do lote foi desarmado por recusa dura — o desarme tem de
    # continuar valendo com o lexico generalizado.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Fico no aguardo", fala_cliente="não vou mais, esquece"), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas


async def test_d2_dispara_regen_com_gatilho_despedida(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Consigo hoje às 20h amor, fecha pra você?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Tabom amor\n\nMe chama quando organizar"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "despedida"
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == ["Me chama quando organizar"]
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Consigo hoje às 20h amor, fecha pra você?"
