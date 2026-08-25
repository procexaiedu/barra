"""Turno MUDO do ciclo 5 — eb04:23966555099311@lid t21 (rotulo "turno 22" do relatorio).

Fecha o loop que o ciclo 6 deu por fechado SEM re-exercer: o replay estocastico divergiu no
turno 1 e nunca chegou ao ponto do defeito. Aqui o caso e reconstruido OFFLINE e DETERMINISTICO,
com as falas literais do dump (`c5/lote/eb04_23966555099311_lid.json`, turnos i=17..21).

O QUE ACONTECEU (reconstruido dos `prompts` do turno i=21 — 3 passadas de chat no array):
  * burst do cliente: "já já te passo"; rascunho da t1: "Tabom amor, te espero" — bolha UNICA,
    verbatim da resposta do t17 (`vistas` do detector, dentro da janela de 12).
  * passada 2 (`prompts[127]`) e o lembrete de regen com gatilho `repeticao`:
    'A bolha que nao passou foi: "Tabom amor, te espero"' + 'Rascunho descartado:\\nTabom amor,
    te espero' — a assinatura literal de `_feedback_repeticao` com UMA ofensora.
  * passada 3 (`prompts[170]`) e o lembrete do trilho `mudo`: "ela era so raciocinio interno ou
    veio VAZIA" com o MESMO rascunho — a assinatura de `_recuperar_vazio(texto_cru)`.
  * nada mais foi chamado (o array acaba ali) e `agente` = "" -> MUDO.
  * o MESMO rascunho aparece nos turnos 19, 21 e 22 (os tres lembretes de regen do dump citam
    "Tabom amor, te espero"): o gatilho armava nos tres, dois foram salvos pela sorte da regen
    (t19 -> "Fico no aguardo", t22 -> "Fico te esperando 🥰") e um morreu. O mudo e a cauda
    estocastica de um gatilho SISTEMATICO, nao um acidente isolado.

CAMINHO EXATO DO MUDO (nao foi judge, nao foi timeout, nao foi leak):
  gatilho `repeticao` -> regen 1 inutilizavel -> `_recuperar_vazio` (regen 2) inutilizavel ->
  `_bolhas_boas_do_original()` devolve None porque o turno ORIGINAL tinha UMA bolha e ela era a
  ofensora (`sobra` vazia) -> `Command(goto=END, update=_zeradas_todas())`.
  A "rede do vazio" da campanha (`_bolhas_boas_do_original`) NAO cobre este caminho por
  construcao: ela resgata as bolhas do original que NUNCA foram flagradas, e aqui nao havia
  nenhuma. `test_c_*` pinava esse residual estrutural.

ATUALIZACAO 14/08 (corrida c12, 5 turnos mudos em 327 — 3 de bolha unica): o residual foi
fechado pelo PISO ANTI-MUDO (`_piso_anti_mudo`). O trilho acima continua identico ate a ultima
porta; so o desfecho mudou — gatilho de QUALIDADE nao emudece o turno inteiro, a bolha original
passa com metrica propria (`passou_por_falta_de_alternativa`). Os asserts de "turno vazio" deste
arquivo viraram, por isso, asserts de "a bolha original sai". Gatilho de SEGURANCA (e pos-escalada)
segue fechando MUDO — quem pina isso e `test_output_guard_piso_anti_mudo_c12.py`.

O FIX QUE DE FATO COBRE o t21 e outro: o ciclo 5 V3 (`cliente_adiou_no_burst` +
`eh_resposta_de_espera` alimentando `responde_pedido`). Ele desarma o gatilho na RAIZ — o
detector de repeticao nem arma, entao nao ha regen, nao ha vazio e nao ha rede a acionar.
Mas o teste V3 de `test_output_guard_ciclo5.py` exercitou a bolha "Fico no aguardo" (a do t19),
nao a bolha que REALMENTE morreu no t21 ("Tabom amor, te espero"). `test_b_*` fecha essa lacuna
com a bolha e o historico literais do t21.

Sem DB, sem LLM, sem credito: mesmo rig de fakes de test_output_guard_ciclo3/4/5.py.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END

from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo (memoria
# "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- falas LITERAIS do dump (eb04:23966555099311@lid) ---------------------------------------------

# Bolhas que a IA ja tinha enviado, na ordem, dos turnos i=8..i=20. A janela do detector e de 12
# bolhas: a ofensora do t17 ("Tabom amor, te espero") e a 14a de 19 -> entra na janela.
_HISTORICAS_T21 = [
    "Sim amor, me cuido bastante",
    (
        "Não faço chamada amor. Mas te mando umas fotos minhas rs. "
        "Gravei um vídeo pra você Estou livre hoje, quer vir?"
    ),
    "Te mando amor",
    "Gravei um vídeo pra você 🥰",
    "Só você vai ver esse",
    ("Só você vai ver esse rs. Te espero hoje, fecha ? A mídia já saiu junto com a minha mensagem"),
    "Te mandei sim amor, dá uma olhada aí",
    "Te espero hoje, fecha ?",
    "Que bom que gostou",
    "Te espero hoje, quer vir ?",
    "Sou bem carinhosa e atenciosa amor, encontro nosso sem pressa",
    "Te espero hoje, consigo a partir das 10:30, fecha ?",
    "Tranquilo amor, me avisa",
    "Tabom amor, te espero",  # t17 — a bolha que o t21 repete verbatim
    "Confirmado amor",
    "Me confirma o horário certinho que eu te espero",
    "Fico no aguardo",  # t19
    "Fechado amor",
    "Me passa o horário que eu te espero",  # t20
]

_BURST_T21 = "já já te passo"
# Rascunho da 1a passada do t21, lido dos DOIS lembretes de regen do dump (`Rascunho descartado:`).
_RASCUNHO_T21 = "Tabom amor, te espero"


# --- rig (fakes de conn/pool/regen/judge) ---------------------------------------------------------


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


def _state(texto: str, *, fala_cliente: str, historicas: list[str]) -> dict[str, Any]:
    msgs: list[BaseMessage] = [
        # AIMessage SEM usage = historica re-injetada pelo prepare_context (`_bolhas_historicas`).
        *[AIMessage(content=h, id=f"hist{i}") for i, h in enumerate(historicas)],
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


class _RegenSequencia:
    """Regen determinística: devolve, em ordem, os conteudos da lista (None = indisponivel) e
    guarda os kwargs de cada chamada (gatilho/rascunho) p/ conferir o trilho percorrido."""

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
    """O que o coordenador despacharia: o agregado das AIMessages do turno DEPOIS do update.

    Mesmo reducer do LangGraph por `id`: as mensagens do turno que o update reescreve valem a
    versao reescrita; as que ele nao toca valem a original; ids novos (regen) entram no fim.
    """
    por_id: dict[str, str] = {
        str(m.id): str(m.content)
        for m in state["messages"]
        if isinstance(m, AIMessage) and m.usage_metadata is not None
    }
    for ident, conteudo in _msgs_update(res).items():
        por_id[str(ident)] = conteudo
    return "\n\n".join(p for p in por_id.values() if p.strip())


# --- A: o mecanismo do mudo, reproduzido -----------------------------------------------------------


def test_a_o_rascunho_do_t21_e_verbatim_da_bolha_do_t17() -> None:
    """A premissa do caso: sem isencao, a bolha unica do t21 e repeticao EXATA do t17."""
    assert _RASCUNHO_T21 in _HISTORICAS_T21
    assert mod.bolhas_repetidas(_RASCUNHO_T21, _HISTORICAS_T21) == [_RASCUNHO_T21]


async def test_a_fio_completo_reproduz_o_trilho_do_c5(monkeypatch: Any) -> None:
    """Baseline do ciclo 5 (ANTES do fix V3): `cliente_adiou_no_burst` neutralizado p/ simular o
    codigo de entao. Reproduz o trilho literal do dump — regen `repeticao` e regen do trilho
    `mudo`, com o rascunho literal.

    O DESFECHO mudou em 14/08 (piso anti-mudo, corrida c12): o trilho continua igual, mas o turno
    nao fecha mais vazio — `repeticao` e gatilho de QUALIDADE e a bolha original passa quando as
    duas regens falham. O que este teste pina hoje e o trilho; o mudo virou o `assert` invertido
    logo abaixo."""
    _judge_ok(monkeypatch)
    monkeypatch.setattr(mod, "cliente_adiou_no_burst", lambda falas: False)
    # As duas regens do dump vieram inutilizaveis (vazia ou reincidente): aqui, vazias.
    regen = _RegenSequencia("", "")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T21, fala_cliente=_BURST_T21, historicas=_HISTORICAS_T21)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    # Exatamente as duas passadas de regen que o dump mostra, na ordem e com o rascunho literal.
    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao", "mudo"]
    assert regen.chamadas[0]["rascunho"] == _RASCUNHO_T21
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == [_RASCUNHO_T21]
    # Regen #1 veio VAZIA aqui, entao nao ha 2a forma a vetar: o rascunho da recuperacao segue
    # sendo so o original (`texto_cru`), como no dump.
    assert regen.chamadas[1]["rascunho"] == _RASCUNHO_T21
    # O que era o defeito (turno vazio) hoje e barrado pelo piso anti-mudo: a bolha original sai.
    assert _texto_ao_cliente(res, state) == _RASCUNHO_T21


def test_a_a_rede_do_vazio_nao_cobre_bolha_unica() -> None:
    """Por que a rede do vazio (o suposto fix da campanha) nao salvou o t21: ela resgata as
    bolhas do original que NUNCA foram flagradas — e o t21 tinha UMA bolha, a ofensora.
    `_drop_bolhas` do original pela ofensora devolve vazio."""
    assert mod._drop_bolhas(_RASCUNHO_T21, {_RASCUNHO_T21}) == ""
    # Com uma irma nao-flagrada no turno, a mesma rede TERIA salvado — a diferenca e o numero de
    # bolhas, nao o gatilho.
    turno_com_irma = f"{_RASCUNHO_T21}\n\nJá anotei aqui amor"
    assert mod._drop_bolhas(turno_com_irma, {_RASCUNHO_T21}) == "Já anotei aqui amor"


# --- B: o fix que cobre o t21 (ciclo 5 V3), agora com a bolha REAL do turno -------------------------


def test_b_o_burst_do_t21_e_adiamento_explicito() -> None:
    assert mod.cliente_adiou_no_burst([_BURST_T21]) is True


def test_b_a_bolha_real_do_t21_e_da_familia_da_espera() -> None:
    """A lacuna do teste V3 do ciclo 5: ele pinou "Fico no aguardo" (bolha do t19). A bolha que
    morreu no t21 foi "Tabom amor, te espero" — outra redacao, mesma familia (`\\bte espero\\b`)."""
    assert mod.eh_resposta_de_espera(_RASCUNHO_T21) is True
    assert mod.eh_resposta_de_espera("Fico no aguardo") is True


def test_b_a_isencao_desarma_a_repeticao_na_bolha_real() -> None:
    assert (
        mod.bolhas_repetidas(
            _RASCUNHO_T21, _HISTORICAS_T21, responde_pedido=mod.eh_resposta_de_espera
        )
        == []
    )


async def test_b_fio_completo_o_t21_nao_sai_mais_mudo(monkeypatch: Any) -> None:
    """O caso do ciclo 5 re-exercido contra o codigo ATUAL, com o historico e a bolha literais:
    a bolha sobrevive, sem gastar regen nenhuma."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T21, fala_cliente=_BURST_T21, historicas=_HISTORICAS_T21)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas  # nenhum gatilho armou
    assert "a1" not in _msgs_update(res)  # o turno original segue vivo, intacto
    assert _texto_ao_cliente(res, state) == _RASCUNHO_T21


@pytest.mark.parametrize(
    ("burst", "historicas"),
    [
        # t19 — 1 regen no dump, saiu "Fico no aguardo" (sorte).
        ("à noite te passo", _HISTORICAS_T21[:14]),
        # t21 — 2 regens no dump, saiu MUDO (o defeito).
        ("já já te passo", _HISTORICAS_T21),
        # t22 — 1 regen no dump, saiu "Fico te esperando 🥰" (sorte de novo).
        ("mando já td certo", [*_HISTORICAS_T21, "Fico te esperando"]),
    ],
)
async def test_b_os_tres_turnos_do_mesmo_rascunho_sobrevivem(
    burst: str, historicas: list[str], monkeypatch: Any
) -> None:
    """O dump mostra o MESMO rascunho "Tabom amor, te espero" nos turnos 19, 21 e 22 (os tres
    lembretes de regen citam a bolha literalmente) — o modelo responde sempre isso a quem enrola,
    e o detector de repeticao armava nos tres. Dois sobreviveram por sorte da regen, um morreu.
    Com o V3 armado, o gatilho nao existe em nenhum dos tres: nada de regen, nada de sorte."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T21, fala_cliente=burst, historicas=historicas)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas
    assert _texto_ao_cliente(res, state) == _RASCUNHO_T21


# --- C: o residual ESTRUTURAL que a campanha nao fechou (pin de comportamento) ----------------------


async def test_c_bolha_unica_flagrada_sem_isencao_nao_fecha_mais_mudo(monkeypatch: Any) -> None:
    """O buraco que sobrava depois do V3, agora FECHADO. A isencao do adiamento consertava a
    INSTANCIA (t21), nao a CLASSE: turno de bolha UNICA + gatilho por-bolha legitimo + regen
    inutilizavel 2x fechava MUDO, porque a rede do vazio nao tem irma para resgatar e nao existe
    canned generica de venda. Burst sem adiamento ("blz"), mesma bolha repetida.

    A classe voltou a aparecer em escala na corrida c12 (5 turnos mudos em 327, 3 deles de bolha
    unica) e o fecho e o PISO ANTI-MUDO: `repeticao` e QUALIDADE, silencio total e a pior saida
    medida no shadow, entao a bolha original passa em vez de o turno emudecer. O trilho ate a
    ultima porta continua o mesmo — o que muda e so a saida dela."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("", "")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T21, fala_cliente="blz", historicas=_HISTORICAS_T21)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao", "mudo"]
    assert _texto_ao_cliente(res, state) == _RASCUNHO_T21


async def test_c_com_irma_nao_flagrada_a_rede_do_vazio_segura(monkeypatch: Any) -> None:
    """O contraste que isola a variavel: MESMO gatilho, MESMAS regens inutilizaveis — so muda o
    numero de bolhas. Com uma irma limpa no original, a rede do vazio entrega o turno."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("", "")
    monkeypatch.setattr(mod, "_regenerar", regen)

    irma = "Já anotei aqui amor"
    state = _state(f"{_RASCUNHO_T21}\n\n{irma}", fala_cliente="blz", historicas=_HISTORICAS_T21)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert _texto_ao_cliente(res, state) == irma


@pytest.mark.parametrize(
    "fala",
    [
        "já já te passo",  # t21
        "à noite te passo",  # t19
        "mando já td certo",  # t22
    ],
)
def test_c_as_tres_falas_de_adiamento_do_caso(fala: str) -> None:
    """As tres falas de enrolacao deste dump armam a isencao — o t21 nao depende de uma redacao."""
    assert mod.cliente_adiou_no_burst([fala]) is True
