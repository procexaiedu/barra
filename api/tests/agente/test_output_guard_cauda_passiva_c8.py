"""Ciclo 8 da campanha 13/08 — as 4 caudas passivas que SAIRAM ao cliente no re-run c8.

Diagnostico por fala (dump c8-real, casos eb04:79981032001710 e eb04:14224965292147):

B1 — t8 de eb04:79981032001710, "Sem pressa amor, me chama quando tiver um tempo livre": o
     detector CASAVA (ordem invertida do ciclo 4 mais o ramo direto). Quem desarmou foi o
     `cliente_encerrou_no_burst`: o burst dele era "Hmm hoje acho que nao vou dar conta nao / To
     lotado de coisa pra resolver" e o ramo "nao vou (dar)" do `_RE_RECUSA_DURA` leu recusa do DIA
     como encerramento da conversa. Recusar o dia nao encerra nada — e o insumo do
     `dia_recusado_pelo_cliente`, que carimba `<dia_recusado>` no `<agenda>` e manda a proxima
     oferta sair do primeiro dia da janela que ele NAO recusou. Ou seja, o proximo passo concreto
     que a regen desta cauda cobra existe justamente neste turno.

B2 — t19/t20 do mesmo caso, "me chama que eu vou sim" e "Me chama que eu ajusto minha agenda pra
     voce": ordem NOVA, "me chama QUE <acao minha>". Os dois ramos do "quando" (direto e
     invertido) nao a alcancam porque a condicao aqui vem no que ELA faz depois, nao no que ele
     faz antes. Ramo proprio, com o "que" colado no verbo.

B3 — t15 de eb04:14224965292147, "Fico na torcida": familia do "fico", complemento fora da lista.
     Entra na lista FECHADA de complementos — e a lista fechada que preserva "Fico ate voce
     chegar" e "Fico ate domingo", que na MESMA conversa respondem a pergunta dele ("ate quando
     voce fica ?") e nao podem virar gatilho.

B4 — t8 de eb04:14224965292147, "Tranquilo amor, me avisa 🥰": verbo de chamada NU no fim da
     bolha, sem "quando" e sem "que". Ancorado no fim de proposito: no meio da frase quem decide e
     o complemento ("me avisa quando sair" e execucao do encontro, nao entrega de iniciativa).

Varredura de falso positivo: os 85 turnos com fala das 9 conversas do dump c8 passam pelo detector
com o lexico novo e SO estes 5 turnos acendem — os outros 80 seguem limpos. Os casos de fronteira
dessa varredura estao fixados abaixo em `test_c8_fronteiras_que_nao_podem_flagrar`.

Unit tests sem DB/LLM (mesmo rig de test_output_guard_ciclo4.py): fakes de conn/pool/regen/judge.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END

from barra.agente._disciplina import dia_recusado_pelo_cliente
from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo; importlib pega o modulo
# real p/ monkeypatch (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")

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


def _state(texto: str, *, fala_cliente: str = "oi") -> dict[str, Any]:
    msgs: list[BaseMessage] = [
        HumanMessage(content=fala_cliente, id="h1"),
        AIMessage(content=texto, id="a1", usage_metadata=_USAGE),
    ]
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


# As falas REAIS do dump c8 (turnos que sairam ao cliente).
_T8_BURST = "Hmm hoje acho que não vou dar conta não kkkk\nTô lotado de coisa pra resolver"
_T8_CAUDA = "Sem pressa amor, me chama quando tiver um tempo livre"
_T19_CAUDA = "Poxa amor\n\nOutro dia então, me chama que eu vou sim rs"
_T20_CAUDA = "Faz total sentido amor, com calma é melhor mesmo rs\n\nMe chama que eu ajusto minha agenda pra você"
_TORCIDA_CAUDA = "Fico na torcida"
_AVISA_CAUDA = "Tranquilo amor, me avisa 🥰"


# --- B1: recusa do DIA nao e encerramento ---------------------------------------------------------


def test_b1_o_detector_sempre_casou_a_cauda_do_t8() -> None:
    # A cauda nunca foi o buraco: ela ja casava antes do ciclo 8 (ordem direta + invertida).
    assert mod.bolhas_despedida_passiva(_T8_CAUDA) == [_T8_CAUDA]


def test_b1_recusa_do_dia_no_burst_nao_e_encerramento() -> None:
    assert mod.cliente_encerrou_no_burst(_T8_BURST.split("\n")) is False
    assert mod.cliente_encerrou_no_burst(["amanhã não vou conseguir"]) is False
    assert mod.cliente_encerrou_no_burst(["sexta não vou poder amor"]) is False


def test_b1_encerramento_definitivo_segue_desarmando() -> None:
    # Ciclos 2 e 3: sem dia nomeado nada muda.
    assert mod.cliente_encerrou_no_burst(["não vou mais, esquece"]) is True
    assert mod.cliente_encerrou_no_burst(["deixa pra lá"]) is True
    assert mod.cliente_encerrou_no_burst(["não vou conseguir"]) is True
    # ... e com dia nomeado JUNTO do encerramento definitivo, tambem encerra.
    assert mod.cliente_encerrou_no_burst(["hoje eu não vou mais"]) is True
    assert mod.cliente_encerrou_no_burst(["amanhã eu desisto, esquece"]) is True
    # A objecao de preco do caso real eb02 nunca foi recusa.
    assert mod.cliente_encerrou_no_burst(["Você tem seu valor, eu não vou pedir desconto"]) is False


def test_b1_a_familia_do_burst_carimba_dia_recusado() -> None:
    """A prova de que o proximo passo concreto EXISTE nesse turno: o mesmo burst que deixou de
    encerrar a conversa e o que o `<dia_recusado>` le, e o bloco manda mirar o 1o dia nao recusado.

    NOTA (achado do ciclo 8, fora do escopo deste fix — mora em `_disciplina`): a fala LITERAL do
    t8 ("Hmm hoje acho que nao vou dar conta nao / To lotado de coisa pra resolver") escapa do
    `dia_recusado_pelo_cliente` por um fio — o dia esta na 1a clausula e o token de
    impossibilidade ("lotado") na 2a, e o "acho que" desgruda o "hoje" do "nao". Sem o "acho que",
    ou com o dia na mesma clausula do "lotado", o carimbo sai. O gatilho da cauda passiva NAO
    depende do carimbo (sao superficies independentes); o carimbo so torna o proximo passo mais
    facil de escolher."""
    assert dia_recusado_pelo_cliente([(False, "hoje não vou dar conta")]) == "hoje"
    assert dia_recusado_pelo_cliente([(False, "Tô lotado hoje")]) == "hoje"


async def test_b1_fio_completo_o_t8_dispara_despedida(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Que tal amanhã às 20h então amor ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_T8_CAUDA, fala_cliente=_T8_BURST), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "despedida"
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == [_T8_CAUDA]
    assert _msgs_update(res)["regen1"] == "Que tal amanhã às 20h então amor ?"


def test_b1_feedback_da_regen_nao_contradiz_o_dia_recusado() -> None:
    """O `<dia_recusado>` tira o dia recusado da mesa; o feedback da cauda passiva pede passo
    concreto SEM cravar dia nenhum (a direcao vem do contexto). Se o feedback nomeasse "hoje", as
    duas superficies se contradiriam no mesmo turno — este teste e o cadeado disso."""
    fb = mod._FEEDBACK_GATILHO["despedida"]
    assert "proximo passo concreto" in fb
    assert "com os dados do seu contexto" in fb
    for dia in ("hoje", "amanha", "agora", "sexta", "segunda"):
        assert dia not in fb


# --- B2/B3/B4: as variantes que escapavam do lexico -----------------------------------------------


@pytest.mark.parametrize(
    ("turno", "cauda"),
    [
        (_T19_CAUDA, "Outro dia então, me chama que eu vou sim rs"),
        (_T20_CAUDA, "Me chama que eu ajusto minha agenda pra você"),
        (_TORCIDA_CAUDA, _TORCIDA_CAUDA),
        (_AVISA_CAUDA, _AVISA_CAUDA),
    ],
)
def test_c8_variantes_reais_agora_flagram(turno: str, cauda: str) -> None:
    assert mod.bolhas_despedida_passiva(turno) == [cauda]


@pytest.mark.parametrize(
    "cauda",
    ["me chama que a gente combina", "só me avisa que eu te espero", "pode me chama que eu vejo"],
)
def test_c8_familia_do_que_generaliza_alem_do_literal(cauda: str) -> None:
    assert mod.bolhas_despedida_passiva(cauda) == [cauda]


@pytest.mark.parametrize("cauda", ["me chama", "Tranquilo amor, me avisa", "só me fala 🥰"])
def test_c8_verbo_de_chamada_nu_no_fim_flagra(cauda: str) -> None:
    assert mod.bolhas_despedida_passiva(cauda) == [cauda]


@pytest.mark.parametrize(
    "bolha",
    [
        # Excecao de EXECUCAO do encontro ja combinado (fronteira do ciclo 3, tem de sobreviver).
        "te espero rs, me avisa quando sair",
        "Combinado amor, me chama quando estiver chegando",
        # A excecao de execucao na ordem INVERTIDA tambem termina no verbo nu — por isso o ramo
        # novo exige clausula SEM "quando" ate o verbo.
        "quando você chegar me avisa",
        "quando estiver chegando me avisa amor",
        # Execucao tambem na ordem "me chama QUE ..." e com o deslocamento NU (sem "quando") —
        # as duas saem do corpus de saidas e sao coordenacao de quem ja vem.
        "Quando chegar me chama que a gente combina 🥰",
        "Perfeito\nChega me avisa\nQue passo o quarto",
        # "que" interrogativo e empurrao ATIVO, o oposto da cauda.
        "Me fala que horas você quer te espero",
        "Quando chegar na cidade me chama amor",
        "combinado amor, me manda a foto quando chegar 🥰",
        # A MESMA conversa do "Fico na torcida" responde "ate quando voce fica ?" — a lista
        # fechada de complementos do "fico" e o que preserva estas.
        "Fico até você chegar",
        "Fico tranquila o dia todo amor",
        "Volto pra minha casa em outro estado",
        # Verbo de chamada NO MEIO da frase, com complemento proprio: nao e cauda.
        "Me chama no zap que é mais fácil pra mim, vou te mandar o número",
        # Passo concreto na propria bolha desarma (veto pre-existente).
        "Me chama que eu ajusto minha agenda pra você amanhã",
        # Pergunta desarma (veto pre-existente).
        "Me chama que eu ajusto minha agenda, pode ser ?",
    ],
)
def test_c8_fronteiras_que_nao_podem_flagrar(bolha: str) -> None:
    assert mod.bolhas_despedida_passiva(bolha) == []


def test_c8_adiamento_explicito_segue_isentando_a_espera() -> None:
    # Ciclo 5 V3: "ja ja te passo" -> "fico no aguardo" e resposta, nao cauda. Intacto.
    assert mod.cliente_adiou_no_burst(["já já te passo amor"]) is True
    assert mod.eh_resposta_de_espera("Fico no aguardo então 🥰") is True


async def test_c8_fio_completo_do_t20_veta_so_a_cauda(monkeypatch: Any) -> None:
    """O turno tem uma bolha boa antes da cauda: o veto e granular (so a ultima vai nomeada)."""
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Faz total sentido amor\n\nConsigo amanhã às 21h, fecha ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_T20_CAUDA, fala_cliente="prefiro marcar com calma"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "despedida"
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == [
        "Me chama que eu ajusto minha agenda pra você"
    ]
    assert res.goto == END
