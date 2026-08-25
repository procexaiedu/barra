"""Ciclo 7 — AFIRMACAO DE ENVIO RECEM-OCORRIDO num turno que nao enviou nada.

Caso real eb04:79981032001710@lid (dump do ciclo 7). O book de FOTOS saiu de verdade no t9
(`tools=['enviar_midia', ...]`), o cliente passou a conversa inteira pedindo um VIDEO, e em tres
turnos com `tools=[]` a IA afirmou o envio no PRETERITO:

  * t13 "O vídeo já te mandei, dá uma olhada rs"
  * t16 "Te mandei agora amor, olha lá"
  * t23 "Gravei um vídeo pra você 🥰"

O cliente desmentiu na hora — t14: "Amor, só pra confirmar: o vídeo você não chegou a mandar ainda
não kkk"; t17: "Tá, o vídeo eu ainda não vi chegar nada não".

POR QUE O GUARD DA CAMPANHA NAO PEGOU: `bolhas_midia_ja_enviada` (ciclo 5 V1) so arma com
`book_enviado_em` VAZIO — mentira sobre a CONVERSA ("nunca te mandei nada"). Aqui o book existe;
a mentira e sobre o TURNO ("acabou de sair"), e o eixo do discriminador tem de ser o rastro deste
turno, nao o carimbo da conversa.

O FIX (extensao da mesma familia, mesmo gatilho `midia_afirmada`): `bolhas_midia_recem_afirmada`
arma sempre que NENHUMA `enviar_midia` executou no turno, por duas formas — (a) envio no passado +
deixis de recencia (adverbio de agora ou imperativo DEITICO de olhar) e (b) verbo de producao +
substantivo de midia + destinatario ("gravei um video pra voce"). A referencia legitima a envio
antigo real fica intacta: imperativo com OBJETO ("olha o video que te mandei"), "ja te mandei as
fotos" sem deixis, marcador de tempo passado, negacao e objeto de texto absolvem.

Unit tests sem DB/LLM/credito: mesmo rig de fakes de test_output_guard_ciclo5/mudo_c5.py.
"""

import importlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo (memoria
# "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- falas LITERAIS do dump (eb04:79981032001710@lid) ---------------------------------------------

_BOLHA_MENTIRA_T13 = "O vídeo já te mandei, dá uma olhada rs"
_BOLHA_BOA_T13 = "Consigo às 14h, fecha ?"
_TURNO_T13 = f"{_BOLHA_MENTIRA_T13}\n\n{_BOLHA_BOA_T13}"
_BURST_T13 = (
    "Tô lotado hoje, sem chance.\nMas me conta, como funciona o rolê ai? O vídeo você manda depois?"
)

_BOLHA_MENTIRA_T16 = "Te mandei agora amor, olha lá"
_BOLHA_BOA_T16 = "Consigo amanhã se quiser, me fala um horário"
_TURNO_T16 = f"{_BOLHA_MENTIRA_T16}\n\n{_BOLHA_BOA_T16}"
_BURST_T16 = (
    "Justamente rs Por isso queria o vídeo antes, pra ter certeza que é vc mesmo rs\n"
    "Me manda aí que eu te cobro depois"
)

_BOLHA_MENTIRA_T23 = "Gravei um vídeo pra você 🥰"
_TURNO_T23 = (
    f"Sou bem tranquila, estilo namoradinha\n\n{_BOLHA_MENTIRA_T23}\n\n"
    "Me confirma teu horário que eu te espero"
)
_BURST_T23 = (
    "Hahaha continua tentando me fisgar no 15h né rs\n"
    "Mas me fala, como funciona esse rolê ai? O vídeo você manda ou não manda? kkkk"
)

# t14: a MESMA fala do t16, mas com `enviar_midia` EXECUTADA no turno — anuncio legitimo.
_TURNO_T14 = "Te mandei agora amor, dá uma olhada"


# --- rig (fakes de conn/pool/regen/judge) ---------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Conn fake; `book_enviado` responde a leitura do atendimento com o carimbo preenchido —
    o estado do caso real a partir do t9 (o book de fotos SAIU)."""

    def __init__(self, *, book_enviado: bool = True) -> None:
        self.book_enviado = book_enviado

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        if "ia_pausada" in query and self.book_enviado:
            return _FakeResult(
                [
                    {
                        "ia_pausada": False,
                        "valor_acordado": None,
                        "duracao_horas": None,
                        "book_enviado_em": datetime.now(UTC),
                    }
                ]
            )
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


def _runtime(*, book_enviado: bool = True) -> _Runtime:
    ctx = ContextAgente(
        db_pool=_FakePool(_FakeConn(book_enviado=book_enviado)),  # type: ignore[arg-type]
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
    fala_cliente: str,
    midia_ok: bool = False,
    historicas: list[str] | None = None,
) -> dict[str, Any]:
    msgs: list[BaseMessage] = [
        # AIMessage SEM usage = historica re-injetada pelo prepare_context (`_bolhas_historicas`).
        *[AIMessage(content=h, id=f"hist{i}") for i, h in enumerate(historicas or [])],
        HumanMessage(content=fala_cliente, id="h1"),
    ]
    tool_calls = [{"name": "enviar_midia", "id": "tc1", "args": {}}] if midia_ok else []
    msgs.append(AIMessage(content=texto, id="a1", usage_metadata=_USAGE, tool_calls=tool_calls))
    if midia_ok:
        msgs.append(ToolMessage(content="midia enviada", tool_call_id="tc1"))
    return {
        "messages": msgs,
        "conversa_crua": [HumanMessage(content=fala_cliente, id="h1")],
    }


def _judge_ok(monkeypatch: Any) -> None:
    async def _ok(texto: str, settings: Any, **kwargs: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)


class _RegenSequencia:
    """Regen determinística: devolve, em ordem, os conteudos da lista (None = indisponivel) e
    guarda os kwargs de cada chamada (gatilho/rascunho/bolhas_vetadas/feedback)."""

    def __init__(self, *conteudos: str | None) -> None:
        self.conteudos = list(conteudos)
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
        self.chamadas.append(kwargs)
        c = self.conteudos.pop(0) if self.conteudos else None
        if c is None:
            return None
        return AIMessage(content=c, id=f"regen{len(self.chamadas)}", usage_metadata=_USAGE)


def _msgs_update(res: Any) -> dict[str, str]:
    return {m.id: str(m.content) for m in (res.update or {}).get("messages", [])}


def _texto_ao_cliente(res: Any, state: dict[str, Any]) -> str:
    """O que o coordenador despacharia: o agregado das AIMessages do turno DEPOIS do update
    (mesmo reducer por `id` do LangGraph)."""
    por_id: dict[str, str] = {
        str(m.id): str(m.content)
        for m in state["messages"]
        if isinstance(m, AIMessage) and m.usage_metadata is not None
    }
    for ident, conteudo in _msgs_update(res).items():
        por_id[str(ident)] = conteudo
    return "\n\n".join(p for p in por_id.values() if p.strip())


# --- A: o detector, nos dois lados da fronteira ---------------------------------------------------


@pytest.mark.parametrize(
    ("turno", "ofensora"),
    [
        # os tres turnos REAIS do caso
        (_TURNO_T13, _BOLHA_MENTIRA_T13),
        (_TURNO_T16, _BOLHA_MENTIRA_T16),
        (_TURNO_T23, _BOLHA_MENTIRA_T23),
        # a FAMILIA da forma, nao as tres frases (licao "detector por literal vs prompt por
        # familia"): adverbio de agora, perifrase de recencia, outros imperativos deiticos,
        # outros verbos de producao.
        ("Te mandei agorinha amor", "Te mandei agorinha amor"),
        ("Acabei de te mandar 🥰", "Acabei de te mandar 🥰"),
        ("Te enviei o vídeo, olha aí", "Te enviei o vídeo, olha aí"),
        ("Te passei as fotos, dá uma conferida", "Te passei as fotos, dá uma conferida"),
        ("Tirei umas fotos pra você amor", "Tirei umas fotos pra você amor"),
        ("Filmei um videozinho pensando em você", "Filmei um videozinho pensando em você"),
    ],
)
def test_a_flagra_a_afirmacao_de_envio_recem_ocorrido(turno: str, ofensora: str) -> None:
    assert mod.bolhas_midia_recem_afirmada(turno) == [ofensora]


@pytest.mark.parametrize(
    "turno",
    [
        # (b) REFERENCIA a envio antigo real — o apontar que o <ja_enviou_book> manda fazer.
        # Imperativo com OBJETO ("olha o video QUE te mandei") aponta pra envio conhecido; o
        # deitico ("olha la") e que manda conferir o que acabou de chegar.
        "Mas sou eu mesma, olha o vídeo que te mandei 🥰",
        "o book que te mandei antes tá aí amor",
        "te mandei as fotos ontem amor",
        "Já te mandei as fotos amor",  # sem deixis nenhuma: resposta certa a "cadê as fotos?"
        "As minhas fotos já estão aí amor",  # a fala REAL do t15, legitima
        # negacao e verdade; futuro e materia do irmao `promessa_midia`
        "ainda não te mandei o vídeo amor",
        "Te mando sim 🥰",
        # objeto de TEXTO sem substantivo de midia nao e claim de midia
        "Te mandei o endereço agora, olha lá",
        "te passei a confirmação agora amor",
        # verbo de producao sem midia / sem destinatario
        "fiz um precinho especial pra você",
        "Gravei pensando em você rs",
        "tirei umas fotos ontem no ensaio",
        # muleta de conversa perto do vocabulario, sem afirmacao de envio
        "olha só amor, consigo às 14h",
        "Consigo às 14h, fecha ?",
    ],
)
def test_a_nao_flagra_referencia_legitima_nem_fala_comum(turno: str) -> None:
    assert mod.bolhas_midia_recem_afirmada(turno) == []


@pytest.mark.parametrize(
    "turno",
    [
        # Refutacao adversarial 13/08 — os tres falsos positivos de fronteira. O OBJETO ANAFORICO
        # ("as fotos QUE te mandei", "o QUE te mandei") aponta um envio conhecido dos dois e
        # absolve ate o imperativo deitico; e "cedo" nu e marcador de tempo passado como qualquer
        # outro. Punir isto seria punir a conduta do <ja_enviou_book> — e no impasse "ele nao
        # confirma sem ver" o turno podia acabar mudo.
        "Olha lá as fotos que te mandei amor",
        "olha aí o que te mandei",
        "Te mandei o book cedo amor, olha lá",
        "olha lá o vídeo que te mandei",
    ],
)
def test_a_objeto_anaforico_absolve_a_deixis_com_book_enviado(turno: str) -> None:
    assert mod.bolhas_midia_recem_afirmada(turno, ha_envio_antigo=True) == []


@pytest.mark.parametrize(
    "turno",
    [
        # Contra-casos: o que a absolvicao NAO pode soltar.
        _BOLHA_MENTIRA_T13,
        _BOLHA_MENTIRA_T16,
        _BOLHA_MENTIRA_T23,
        "acabei de te mandar amor",
        "Te mandei sim amor, dá uma olhada aí",  # deitico SEM objeto
        # anaforico + adverbio de AGORA: claim DESTE turno, o objeto nao absolve
        "olha lá o vídeo que te mandei agora",
    ],
)
def test_a_absolvicao_nao_solta_o_claim_deste_turno(turno: str) -> None:
    assert mod.bolhas_midia_recem_afirmada(turno, ha_envio_antigo=True) == [turno]


@pytest.mark.parametrize(
    "turno",
    ["Olha lá as fotos que te mandei amor", "olha aí o que te mandei"],
)
def test_a_sem_envio_algum_o_anaforico_volta_a_flagrar(turno: str) -> None:
    """A absolvicao e do envio REAL: sem `book_enviado_em`, apontar para "o que te mandei" e a
    mentira do ciclo 5 (default fail-closed)."""
    assert mod.bolhas_midia_recem_afirmada(turno) == [turno]


def test_a_o_irmao_do_ciclo5_nao_cobria_o_caso() -> None:
    """A premissa do ciclo 7: `bolhas_midia_ja_enviada` (irmao da CONVERSA) e cega ao t16/t23 —
    e no t13, onde ela ate casa, o caller nunca a arma porque o book SAIU no t9."""
    assert mod.bolhas_midia_ja_enviada(_TURNO_T16) == []
    assert mod.bolhas_midia_ja_enviada(_TURNO_T23) == []
    assert mod.bolhas_midia_ja_enviada(_TURNO_T13) == [_BOLHA_MENTIRA_T13]


# --- B: fio completo, com o book JA ENVIADO na conversa (o estado do caso real) --------------------


@pytest.mark.parametrize(
    ("turno", "burst", "ofensora"),
    [
        (_TURNO_T13, _BURST_T13, _BOLHA_MENTIRA_T13),
        (_TURNO_T16, _BURST_T16, _BOLHA_MENTIRA_T16),
        (_TURNO_T23, _BURST_T23, _BOLHA_MENTIRA_T23),
    ],
)
async def test_b_arma_o_gatilho_midia_afirmada_mesmo_com_book_enviado(
    monkeypatch: Any, turno: str, burst: str, ofensora: str
) -> None:
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("Sou eu mesma amor, consigo às 14h se você quiser rs")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(turno, fala_cliente=burst), _runtime(book_enviado=True)
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "midia_afirmada"
    # Veto GRANULAR: so a bolha da mentira; as irmas (oferta de horario) sao aproveitaveis.
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == [ofensora]
    # E o lembrete NAO pode dizer "voce nunca enviou midia nesta conversa" (seria falso: o book
    # saiu no t9) — a razao enriquecida fala do TURNO.
    feedback = regen.chamadas[0]["feedback_gatilho"]
    assert "nesta resposta" in feedback and ofensora[:30] in feedback
    assert res.goto == END


async def test_b_envio_real_no_mesmo_turno_nao_arma(monkeypatch: Any) -> None:
    """O t14: a MESMA fala do t16 ("Te mandei agora amor, dá uma olhada"), mas com a
    `enviar_midia` executada NESTE turno — anuncio legitimo, o guard nao toca."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_TURNO_T14, fala_cliente=_BURST_T16, midia_ok=True),
        _runtime(book_enviado=True),
    )

    assert res.goto == END
    assert not regen.chamadas


@pytest.mark.parametrize(
    "turno",
    [
        "Mas sou eu mesma, olha o vídeo que te mandei 🥰",
        "o book que te mandei antes tá aí amor",
        # os tres FP da refutacao adversarial, agora no fio completo (book carimbado)
        "Olha lá as fotos que te mandei amor",
        "olha aí o que te mandei",
        "Te mandei o book cedo amor, olha lá",
    ],
)
async def test_b_referencia_a_envio_antigo_real_nao_arma(monkeypatch: Any, turno: str) -> None:
    """O outro lado da fronteira, no fio completo: com `book_enviado_em` carimbado, apontar para
    o envio ANTIGO e a conduta que o <ja_enviou_book> pede — nenhuma regen, nada reescrito.
    (A primeira e a bolha do ciclo 5 V1: la ela armava porque NADA tinha saido na conversa.)"""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(turno, fala_cliente="cadê o vídeo amor?"), _runtime(book_enviado=True)
    )

    assert res.goto == END
    assert not regen.chamadas
    assert "a1" not in _msgs_update(res)


async def test_b_persistiu_dropa_a_mentira_e_a_irma_vive(monkeypatch: Any) -> None:
    """Familia fantasma (drop, nao pass-through): mentira reincidente na regen nao sai ao
    cliente, e a oferta de horario do mesmo turno sobrevive."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia(_TURNO_T16)  # reincide com o mesmo turno
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_TURNO_T16, fala_cliente=_BURST_T16)
    res = await mod.output_guard(state, _runtime(book_enviado=True))  # type: ignore[arg-type]

    assert res.goto == END
    assert _texto_ao_cliente(res, state) == _BOLHA_BOA_T16


async def test_b_bolha_unica_flagrada_nao_vira_mudo(monkeypatch: Any) -> None:
    """Rede do vazio (incidente #36 / "silencio e a pior saida do shadow"): turno de bolha UNICA
    flagrada, com a regen reincidindo, esvazia no drop — e ai a recuperacao pelo trilho `mudo`
    ainda tem de entregar fala ao cliente."""
    _judge_ok(monkeypatch)
    # 1a chamada: gatilho `midia_afirmada`, reincide. 2a: `_recuperar_vazio`, devolve fala limpa.
    regen = _RegenSequencia(_BOLHA_MENTIRA_T16, "Sou eu mesma amor, te espero amanhã 15h")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_BOLHA_MENTIRA_T16, fala_cliente=_BURST_T16)
    res = await mod.output_guard(state, _runtime(book_enviado=True))  # type: ignore[arg-type]

    assert [c["gatilho"] for c in regen.chamadas] == ["midia_afirmada", "mudo"]
    assert _texto_ao_cliente(res, state) == "Sou eu mesma amor, te espero amanhã 15h"


async def test_b_conversa_sem_midia_nenhuma_segue_no_irmao_do_ciclo5(monkeypatch: Any) -> None:
    """Regressao do ciclo 5: com `book_enviado_em` VAZIO, o irmao da CONVERSA continua armando
    sobre a forma que o novo detector nao cobre ("olha o video que te mandei")."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("Sou eu mesma amor, no encontro você confirma rs")
    monkeypatch.setattr(mod, "_regenerar", regen)

    claim = "Mas sou eu mesma, olha o vídeo que te mandei 🥰"
    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(claim, fala_cliente="cadê o vídeo amor?"), _runtime(book_enviado=False)
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "midia_afirmada"
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == [claim]
    # Sem bolha do irmao do TURNO, o lembrete e a razao ESTATICA do gatilho (a da conversa).
    assert regen.chamadas[0]["feedback_gatilho"] == mod._FEEDBACK_GATILHO["midia_afirmada"]
    assert res.goto == END


# --- D: os OUTROS DOIS caminhos do no (revisao LangGraph) -----------------------------------------
#
# O scan/fallback nao e o unico lugar onde a bateria de detectores roda. `_bolhas_boas_do_original`
# (rede do vazio) e `_recuperar_vazio` (regen extra do trilho `mudo`) tem baterias PROPRIAS, e a
# uniao do ciclo 7 precisa estar nas tres — senao a mentira volta pela porta dos fundos, sem
# gatilho e sem metrica de midia acesa.


def test_d_rede_do_vazio_nao_ressuscita_a_mentira(monkeypatch: Any) -> None:
    """Bateria de `_bolhas_boas_do_original` (unit, sem passar pelo no).

    A rede resgata as bolhas do original que NUNCA foram flagradas — e quando o gatilho vencedor
    e outro (precedencia), a bolha de midia nunca foi olhada. Aqui se pina que ela e re-escaneada:
    a mentira do turno e remanescente, a fala boa sobrevive."""
    turno = f"{_BOLHA_BOA_T13}\n\n{_BOLHA_MENTIRA_T16}\n\nSou eu mesma amor"
    assert mod.bolhas_midia_recem_afirmada(turno) == [_BOLHA_MENTIRA_T16]
    assert mod._drop_bolhas(turno, {_BOLHA_BOA_T13, _BOLHA_MENTIRA_T16}) == "Sou eu mesma amor"


async def test_d_rede_do_vazio_com_gatilho_repeticao_nao_solta_a_mentira(monkeypatch: Any) -> None:
    """Fio completo do cenario do revisor: book carimbado, turno = [bolha REPETIDA, mentira do
    turno, fala boa]. Por precedencia o gatilho e `repeticao` (o scan de midia nem roda), as duas
    regens vem inutilizaveis e o turno cai na rede do vazio. Sem a uniao na bateria da rede, a
    mentira do eb04 saia ao cliente pelo caminho mais silencioso do no."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("", "")  # regen do gatilho + regen do `_recuperar_vazio`: inuteis
    monkeypatch.setattr(mod, "_regenerar", regen)

    repetida = "Consigo às 14h, fecha ?"
    turno = f"{repetida}\n\n{_BOLHA_MENTIRA_T16}\n\nSou eu mesma amor"
    state = _state(
        turno,
        fala_cliente="Tá, o vídeo eu ainda não vi chegar nada não, mas tudo bem kkkk",
        historicas=[repetida],
    )
    res = await mod.output_guard(state, _runtime(book_enviado=True))  # type: ignore[arg-type]

    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao", "mudo"]
    despachado = _texto_ao_cliente(res, state)
    assert _BOLHA_MENTIRA_T16 not in despachado
    assert despachado == "Sou eu mesma amor"  # a irma boa e resgatada, so a mentira cai junto


async def test_d_recuperar_vazio_reprova_regen_que_afirma_envio_recente(monkeypatch: Any) -> None:
    """Bateria de `_recuperar_vazio`: a regen extra do trilho `mudo` roda SEM saber que nada saiu
    nesta resposta e reescreve a mentira. O gate tem de reprova-la — silencio > mentira (o mesmo
    motivo do `bolhas_afirmacao_nua_de_risco` estar la desde o ciclo 3)."""
    _judge_ok(monkeypatch)
    # 1a: gatilho `midia_afirmada`, reincide -> drop esvazia o turno (bolha unica).
    # 2a: `_recuperar_vazio` devolve OUTRA afirmacao de envio recente -> tem de ser reprovada.
    regen = _RegenSequencia(_BOLHA_MENTIRA_T16, "Te mandei agorinha amor, olha lá")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_BOLHA_MENTIRA_T16, fala_cliente=_BURST_T16)
    res = await mod.output_guard(state, _runtime(book_enviado=True))  # type: ignore[arg-type]

    assert [c["gatilho"] for c in regen.chamadas] == ["midia_afirmada", "mudo"]
    assert res.goto == END
    # Nada da familia chega ao cliente (aqui nao ha irma boa a resgatar: o turno fecha mudo).
    assert _texto_ao_cliente(res, state) == ""


async def test_d_recuperar_vazio_segue_aceitando_fala_limpa(monkeypatch: Any) -> None:
    """O outro lado do MESMO gate (par do teste acima): a recuperacao que NAO afirma envio
    continua passando — o gate novo nao fechou o trilho de recuperacao inteiro."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia(_BOLHA_MENTIRA_T16, "Sou eu mesma amor, te espero amanhã 15h")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_BOLHA_MENTIRA_T16, fala_cliente=_BURST_T16)
    res = await mod.output_guard(state, _runtime(book_enviado=True))  # type: ignore[arg-type]

    assert _texto_ao_cliente(state=state, res=res) == "Sou eu mesma amor, te espero amanhã 15h"


# --- C: o lembrete da regen (incidente #36: proibir SEM dar a fala e o bug conhecido) --------------


def test_c_feedback_nomeia_o_turno_e_prescreve_a_intencao() -> None:
    msg = mod._feedback_midia_recem_afirmada([_BOLHA_MENTIRA_T16])
    assert _BOLHA_MENTIRA_T16 in msg
    # Nao pode negar o envio ANTIGO (o book saiu de verdade) nem mandar chamar tool (a regen roda
    # sem tools por design): a saida prescrita e responder sem apontar envio deste momento.
    assert "nunca" not in msg.lower()
    assert "enviar_midia" not in msg
    assert "ja enviou antes" in msg.lower() or "ja enviou" in msg.lower()


def test_c_feedback_sem_bolha_cai_na_razao_estatica() -> None:
    assert mod._feedback_midia_recem_afirmada([]) == mod._FEEDBACK_GATILHO["midia_afirmada"]
