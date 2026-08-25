"""Ciclo 5 da campanha 13/08 — quatro variantes do lote, com as falas literais dos dumps.

V1 — PLACEHOLDER `[book]` + AFIRMACAO FALSA DE MIDIA (eb02:115139634290814 t6/t7): o modelo
     emitiu a bolha literal "[book]" no lugar do envio e, no turno seguinte, promoveu a invencao
     a fato ("olha o vídeo que te mandei 🥰") — nenhuma midia saiu na conversa INTEIRA.
     (a) `_RE_PLACEHOLDER` cobre colchete GENERICO (qualquer `[...]` fora do `[quote]`, o unico
     colchete legitimo da persona); (b) gatilho novo `midia_afirmada` (familia fantasma, drop):
     claim de midia JA enviada com `book_enviado_em` None e sem `enviar_midia` no turno.

V2 — PRECO RE-PERGUNTADO morre no papagaio (eb04:154056970494004 t5): "Tu não falou o valor gata
     rsrsr" e COBRANCA, nao pergunta — nao casava `_RE_PEDIDO_PRECO` (100% interrogativo), a
     isencao `responde_pedido` nao armava e a cotacao re-entregue ("400 1h + o uber ida e volta")
     morria no detector de repeticao (regen sem o dado). Familia "nao falou o valor / cade o
     valor" entra no regex; a causa era essa e o conserto e nela.

V3 — ESPERA REITERADA -> MUDO (eb04:23966555099311 t19/t21): cliente enrola ("à noite te passo",
     "já já te passo"), a resposta natural e a familia "fico no aguardo" e o guard a punia nas
     DUAS superficies (repeticao -> mudo no t21; despedida passiva). Opcao A (isencao local, sem
     estado novo): adiamento explicito no burst (verbo de aviso futuro + marcador temporal na
     mesma fala) desarma as duas — só para a bolha que E espera, e só no turno do adiamento
     (sem adiamento novo, a espera repetida volta a flagrar: sem eco infinito unilateral).

V4 — NARRACAO DA MECANICA DO ENVIO (eb04:23966555099311 t12): "A mídia já saiu junto com a minha
     mensagem" e eco da regra do book ("sai junto, dentro dela") narrado ao cliente. A familia
     narracao-de-mecanica do Estagio 0 ganha o singular e os combos do "junto com a mensagem";
     a bolha cai, irmas vivem. A frase-fonte do prompt foi reescrita ("cabe dentro dela").

Unit tests sem DB/LLM (mesmo rig de test_output_guard_ciclo3/4.py): fakes de conn/pool/regen/judge.
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

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo; importlib pega o modulo
# real p/ monkeypatch (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")
foco = importlib.import_module("barra.agente.nos._foco_do_turno")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Conn fake; `book_enviado` responde a leitura do atendimento com o carimbo preenchido."""

    def __init__(self, *, book_enviado: bool = False) -> None:
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
    def __init__(self, conn: _FakeConn | None = None) -> None:
        self._conn = conn or _FakeConn()

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime(*, book_enviado: bool = False) -> _Runtime:
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
    fala_cliente: str = "oi",
    historicas: list[str] | None = None,
    midia_ok: bool = False,
) -> dict[str, Any]:
    msgs: list[BaseMessage] = [
        # AIMessage SEM usage = historica re-injetada pelo prepare_context (_bolhas_historicas).
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


# --- V1a: placeholder de colchete generico --------------------------------------------------------

# O turno REAL do caso (eb02:115139634290814 t6): a bolha "[book]" no lugar do envio de midia.
_TURNO_T6 = (
    "Que isso amor, sou eu mesma 🥰\n\n[book]\n\n"
    "Qualquer dia fico tranquila, hoje tô bem livre rs\n\nConsigo às 14h, fecha ?"
)


@pytest.mark.parametrize(
    "bolha",
    [
        "[book]",  # a invencao literal do caso real
        "[fotos]",
        "[video do book]",
        "é na [insira a rua] número 10",  # pin pre-existente do colchete instrucional
        "o ponto é [seu endereço aqui]",
    ],
)
def test_v1a_colchete_generico_e_placeholder(bolha: str) -> None:
    assert mod.tem_placeholder_template(bolha) is True


@pytest.mark.parametrize(
    "bolha",
    [
        # [quote]/[quote: trecho] e o UNICO colchete legitimo (persona) e precisa chegar VIVO ao
        # chunking — inclusive malformado com espaco antes.
        "[quote] beleza amor",
        "[quote: seria hoje] consigo sim",
        "[ quote: o valor] é 400 amor",
        "600 1h (valor fechado) amor",  # parenteses de fala legitima seguem fora
    ],
)
def test_v1a_quote_e_fala_legitima_sobrevivem(bolha: str) -> None:
    assert mod.tem_placeholder_template(bolha) is False


def test_v1a_estagio0_dropa_o_book_e_as_irmas_vivem() -> None:
    # O drop e por BOLHA (Estagio 0): a invencao cai, a fala real do turno segue.
    assert mod._limpar_bolhas(_TURNO_T6) == (
        "Que isso amor, sou eu mesma 🥰\n\n"
        "Qualquer dia fico tranquila, hoje tô bem livre rs\n\nConsigo às 14h, fecha ?"
    )


# --- V1b: afirmacao de midia ja enviada sem envio nenhum ------------------------------------------

# O turno REAL do caso (t7): a bolha boa e a bolha que aponta para um envio que nao existe.
_BOLHA_BOA_T7 = "Café em lugar público não rola amor, te recebo no meu local"
_BOLHA_CLAIM_T7 = "Mas sou eu mesma, olha o vídeo que te mandei 🥰"
_TURNO_T7 = f"{_BOLHA_BOA_T7}\n\n{_BOLHA_CLAIM_T7}"
_BURST_T7 = "Gostaria de ver você antes de qualquer negócio. Um café?"


@pytest.mark.parametrize(
    ("turno", "ofensora"),
    [
        (_TURNO_T7, _BOLHA_CLAIM_T7),
        ("Já te enviei as fotos amor", "Já te enviei as fotos amor"),
    ],
)
def test_v1b_detecta_o_claim_de_midia_no_passado(turno: str, ofensora: str) -> None:
    assert mod.bolhas_midia_ja_enviada(turno) == [ofensora]


@pytest.mark.parametrize(
    "turno",
    [
        "Te mando sim 🥰",  # futuro e materia do irmao `promessa_midia`
        "ainda não te mandei o vídeo amor",  # negacao: verdade, desarma
        "Te mandei o endereço certinho",  # objeto de TEXTO nao e claim de midia
        "Te mandei sim amor",  # claim NU sem substantivo de midia: fora, documentado
    ],
)
def test_v1b_nao_flagra_fala_legitima(turno: str) -> None:
    assert mod.bolhas_midia_ja_enviada(turno) == []


async def test_v1b_dispara_regen_com_gatilho_midia_afirmada(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Sou eu mesma amor, no encontro você confirma rs")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_TURNO_T7, fala_cliente=_BURST_T7), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "midia_afirmada"
    # Veto GRANULAR: so a bolha do claim; a recusa do cafe e aproveitavel.
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == [_BOLHA_CLAIM_T7]
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Sou eu mesma amor, no encontro você confirma rs"


async def test_v1b_com_book_enviado_nao_dispara(monkeypatch: Any) -> None:
    # `book_enviado_em` preenchido: "olha o video que te mandei" e o apontar legitimo do
    # <ja_enviou_book> — o guard nao arma nada.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_TURNO_T7, fala_cliente=_BURST_T7), _runtime(book_enviado=True)
    )

    assert res.goto == END
    assert not regen.chamadas
    assert "a1" not in _msgs_update(res)  # nada reescrito


async def test_v1b_com_midia_no_turno_nao_dispara(monkeypatch: Any) -> None:
    # "te mandei o video agora" com `enviar_midia` executada NESTE turno e o anuncio legitimo.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Te mandei o vídeo agora amor", fala_cliente=_BURST_T7, midia_ok=True),
        _runtime(),
    )

    assert res.goto == END
    assert not regen.chamadas


async def test_v1b_persistiu_dropa_o_claim_e_a_irma_vive(monkeypatch: Any) -> None:
    # Familia fantasma (drop, nao pass-through): mentira reincidente nao sai ao cliente.
    _judge_ok(monkeypatch)
    regen = _FakeRegen(_TURNO_T7)  # reincide com o mesmo turno
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_TURNO_T7, fala_cliente=_BURST_T7), _runtime()
    )

    assert res.goto == END
    assert _msgs_update(res)["regen1"] == _BOLHA_BOA_T7  # claim dropado, irma vive


# --- V2: cobranca de preco arma a isencao `responde_pedido` ---------------------------------------

# As falas REAIS do caso (eb04:154056970494004): a cotacao do t3 e a cobranca do t5.
_COTACAO_T3 = "400 1h + o uber ida e volta"
_COBRANCA_T5 = "Tu não falou o valor gata rsrsr"


@pytest.mark.parametrize(
    "fala",
    [
        _COBRANCA_T5,
        "você não disse o preço",
        "não me passou o valor amor",
        "cadê o valor?",
        "faltou o valor gata",
    ],
)
def test_v2_cobranca_de_preco_e_pedido_de_preco(fala: str) -> None:
    assert foco.contem_pedido_de_preco(fala) is True


@pytest.mark.parametrize(
    "fala",
    [
        "Apesar que linda assim., o valor não importa rsrsrs 😍🥰",  # do burst real: NAO e pedido
        "quanto tempo você fica?",
        "Vc é muito linda., meu Deus 😍😍😍",
    ],
)
def test_v2_nao_acende_sem_cobranca(fala: str) -> None:
    assert foco.contem_pedido_de_preco(fala) is False


async def test_v2_fio_completo_a_cotacao_reentregue_sobrevive(monkeypatch: Any) -> None:
    """O caso real de ponta a ponta: cotacao do t3 na janela historica, cobranca do t5 no burst,
    rascunho re-entregando o valor — a isencao `responde_pedido` arma (digito = o dado pedido) e
    o guard nao flagra nada; o turno sai como esta, com o preco dentro."""
    _judge_ok(monkeypatch)
    regen = _FakeRegen(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_COTACAO_T3, fala_cliente=_COBRANCA_T5, historicas=[_COTACAO_T3]), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas
    assert "a1" not in _msgs_update(res)  # a cotacao original segue viva


# --- V3: espera reiterada sobre adiamento explicito -----------------------------------------------


@pytest.mark.parametrize(
    "fala",
    [
        "já já te passo",  # t21 real
        "à noite te passo",  # t19 real
        "mando já td certo",  # t22 real
        "amanhã te falo certinho",
        "depois te aviso amor",
    ],
)
def test_v3_adiamento_explicito_detectado(fala: str) -> None:
    assert mod.cliente_adiou_no_burst([fala]) is True


@pytest.mark.parametrize(
    "fala",
    [
        "fechou",  # aceite, nao adiamento
        "te passo o endereço",  # verbo sem marcador temporal
        "hoje sim",  # marcador sem verbo de aviso
        "manda o vídeo então",  # imperativo DELE, nao aviso em 1a pessoa
    ],
)
def test_v3_nao_arma_sem_adiamento(fala: str) -> None:
    assert mod.cliente_adiou_no_burst([fala]) is False


def test_v3_isencao_da_repeticao_pinada_dos_dois_lados() -> None:
    espera = "Fico no aguardo"
    # COM o predicado da espera (o que o guard monta quando o burst e adiamento): isenta.
    assert mod.bolhas_repetidas(espera, [espera], responde_pedido=mod.eh_resposta_de_espera) == []
    # SEM adiamento (predicado ausente): a espera repetida segue flagrada — sem eco infinito.
    assert mod.bolhas_repetidas(espera, [espera]) == [espera]
    # Bolha repetida que NAO e espera nao ganha a isencao mesmo com o predicado armado.
    eco = "Sou bem tranquila, estilo namoradinha completa"
    assert mod.bolhas_repetidas(eco, [eco], responde_pedido=mod.eh_resposta_de_espera) == [eco]


async def test_v3_fio_completo_o_t21_nao_morre_mudo(monkeypatch: Any) -> None:
    """O caso real: "Fico no aguardo" ja dito no t19, o cliente adia de novo ("já já te passo") e
    a mesma espera volta — nem repeticao nem despedida passiva armam; o turno sai como esta."""
    _judge_ok(monkeypatch)
    regen = _FakeRegen(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Fico no aguardo", fala_cliente="já já te passo", historicas=["Fico no aguardo"]),
        _runtime(),
    )

    assert res.goto == END
    assert not regen.chamadas
    assert "a1" not in _msgs_update(res)


async def test_v3_sem_adiamento_a_espera_repetida_ainda_flagra(monkeypatch: Any) -> None:
    # O outro lado do pin: burst sem adiamento -> a repeticao arma como sempre.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Consigo hoje às 20h amor, fecha ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Fico no aguardo", fala_cliente="blz", historicas=["Fico no aguardo"]), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "repeticao"
    assert _msgs_update(res)["regen1"] == "Consigo hoje às 20h amor, fecha ?"


async def test_v3_sem_adiamento_a_despedida_passiva_ainda_arma(monkeypatch: Any) -> None:
    # E a outra superficie: primeira espera (sem historicas), burst sem adiamento -> despedida.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Consigo hoje às 20h amor, fecha ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Fico no aguardo", fala_cliente="blz"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "despedida"
    assert _msgs_update(res)["regen1"] == "Consigo hoje às 20h amor, fecha ?"


async def test_v3_com_adiamento_a_primeira_espera_tambem_passa(monkeypatch: Any) -> None:
    # t19 real: "à noite te passo" -> "Fico no aguardo" (primeira vez) nao e cauda passiva.
    _judge_ok(monkeypatch)
    regen = _FakeRegen(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Fico no aguardo", fala_cliente="à noite te passo"), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas


# --- V4: narracao da mecanica do envio ------------------------------------------------------------

# A bolha REAL do t12 (uma bolha so: pontos, nao \n\n).
_BOLHA_T12 = (
    "Só você vai ver esse rs. Te espero hoje, fecha ? A mídia já saiu junto com a minha mensagem"
)


@pytest.mark.parametrize(
    "bolha",
    [
        _BOLHA_T12,
        "A mídia já saiu junto com a minha mensagem",
        "A mídia já saiu",  # singular do branch pre-existente (so havia o plural)
        "as fotos vão junto amor",
        "o vídeo saiu junto com a mensagem",
        "As mídias já saíram no turno, não preciso repetir nada.",  # pin pre-existente
    ],
)
def test_v4_narracao_de_mecanica_detectada(bolha: str) -> None:
    assert mod.tem_marcador_raciocinio(bolha) is True


@pytest.mark.parametrize(
    "bolha",
    [
        "te mandei o vídeo agora",  # anuncio legitimo pos-envio (a fala, nao a mecanica)
        "Gravei um vídeo pra você 🥰",  # o enquadramento prescrito pelo prompt
        "ela é minha amiga, vem junto se quiser",  # pin pre-existente do "junto" legitimo
        "Só você vai ver esse rs",
    ],
)
def test_v4_fala_legitima_de_midia_vive(bolha: str) -> None:
    assert mod.tem_marcador_raciocinio(bolha) is False


def test_v4_estagio0_dropa_a_bolha_e_as_irmas_vivem() -> None:
    turno = f"Só você vai ver esse rs\n\n{_BOLHA_T12}"
    assert mod._limpar_bolhas(turno) == "Só você vai ver esse rs"


async def test_v4_fio_completo_pos_envio_legitimo_passa(monkeypatch: Any) -> None:
    # "te mandei o vídeo agora" com a midia saindo NESTE turno: nenhum gatilho (nem o V1b).
    _judge_ok(monkeypatch)
    regen = _FakeRegen(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Te mandei o vídeo agora amor, dá uma olhada", fala_cliente="oi", midia_ok=True),
        _runtime(),
    )

    assert res.goto == END
    assert not regen.chamadas
