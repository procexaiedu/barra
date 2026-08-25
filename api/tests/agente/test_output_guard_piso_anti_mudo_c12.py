"""Turno MUDO da corrida c12 tardia (14/08) — o cliente perdido na rua que recebeu silencio.

Dados: `.scratch/campanha-substituicao-20260813/out_c12_tardio/`. 5 turnos mudos em 327, e os
cinco com a MESMA cadeia (eb02:158827940974842 t21/t27, eb04:136301357568178 t10,
eb04:154412781666344 t19, eb04:43087783055505 t18):

    chat #1  -> rascunho flagrado por `repeticao`
    regen #1 (gatilho=repeticao)                 -> reincide -> drop de TODAS as bolhas -> vazio
    regen #2 (`_recuperar_vazio`, trilho `mudo`) -> reincide -> None
    `_aplicar_rede_do_vazio()`                   -> False (nao havia bolha nao-flagrada)
    -> turno MUDO

As falas deste arquivo sao literais do eb04:43087783055505 t18 (prompts[127] e prompts[170] do
dump carregam os dois lembretes de regen, palavra por palavra). O impasse e de POLITICA: o cliente
esta na rua, sem internet, pedindo o numero da casa; a unica fala autorizada e "me confirma o
horario que eu te passo". Com a funcao fixa e a forma vetada nao existe frase nova — o guard nao
estava corrigindo um erro, estava punindo a unica resposta que a politica permite.

Tres defeitos, tres consertos (todos exercidos aqui):
  1. o lembrete da recuperacao MENTIA ("veio VAZIA") no lugar do gatilho que de fato vetou, e com
     a mentira ia embora a lista literal das bolhas ofensoras -> `_feedback_recuperacao_do_vazio`;
  2. o rascunho vetado era so o ORIGINAL, entao o modelo reescrevia a mesma frase pela terceira
     vez -> as DUAS formas ja tentadas viajam vetadas;
  3. bolha UNICA nao tem rede (3 dos 5 mudos) -> PISO ANTI-MUDO: gatilho de QUALIDADE nao emudece
     o turno inteiro; o original passa, com metrica propria. SEGURANCA nunca passa por essa porta.

Sem DB, sem LLM, sem credito: mesmo rig de fakes de test_output_guard_mudo_c5.py.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END
from prometheus_client import REGISTRY

from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo (memoria
# "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- falas LITERAIS do dump (eb04:43087783055505@lid, turnos i=9..17) ------------------------------

_HISTORICAS_T18 = [
    "To na rua Latino Coelho, chácara da barra",
    "Bem discretinho, você chega de boa rs",
    "É rapidinho do terminal",
    "Você vem de boa, te espero aqui",
    "Consigo 10h pra você rs",
    "Tranquilo amor",
    "Consigo às 10:30 amor",
    "400 1h no meu local",
    "To livre hoje a partir das 10:30 amor",
    "To na Latino Coelho, te espero amor",
    "Me confirma que eu te passo o número certinho rs",
    "Me confirma 10:30 que eu te passo o número",  # t17 — a bolha que o t18 repete
]

_BURST_T18 = "Cadê o endereço aí na barra\nManda o número que eu te chamo na rua sem internet"
# Rascunho da 1a passada do t18 (prompts[127] cita esta bolha como a ofensora, e prompts[170] a
# repete como "Rascunho descartado" — a prova de que a recuperacao re-alimentava o ORIGINAL).
_RASCUNHO_T18 = "Me confirma 10:30 que eu te passo o número certinho amor"
# A regen #1: reformulacao de cauda, exatamente o que o lembrete velho induzia. Reincide.
_REGEN1_T18 = "Pode me confirmar 10:30 que eu te passo o número"

# Familia fantasma (SEGURANCA) usada nos controles negativos.
_MENTIRA_DE_MIDIA = "Te mandei agora amor, olha lá"


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
    """Regen deterministica: devolve, em ordem, os conteudos da lista (None = indisponivel) e
    guarda os kwargs de cada chamada (gatilho/rascunho/feedback) p/ conferir o trilho."""

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
    (mesmo reducer do LangGraph, por `id`)."""
    por_id: dict[str, str] = {
        str(m.id): str(m.content)
        for m in state["messages"]
        if isinstance(m, AIMessage) and m.usage_metadata is not None
    }
    for ident, conteudo in _msgs_update(res).items():
        por_id[str(ident)] = conteudo
    return "\n\n".join(p for p in por_id.values() if p.strip())


def _piso_usado(gatilho: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "agente_output_regen_total",
            {"gatilho": gatilho, "resultado": "passou_por_falta_de_alternativa"},
        )
        or 0.0
    )


# --- A: a premissa do caso (o gatilho arma nas DUAS formas) ----------------------------------------


def test_a_o_rascunho_e_a_reescrita_reincidem_no_mesmo_gatilho() -> None:
    """Por que o turno morria: a bolha do t18 repete a do t17, e a reformulacao de cauda que o
    lembrete velho induz cai no MESMO piso (mesmo comeco + mesmo numero)."""
    assert mod.bolhas_repetidas(_RASCUNHO_T18, _HISTORICAS_T18) == [_RASCUNHO_T18]
    assert mod.bolhas_repetidas(_REGEN1_T18, _HISTORICAS_T18) == [_REGEN1_T18]


def test_a_a_rede_do_vazio_e_inerte_com_bolha_unica() -> None:
    """3 dos 5 mudos medidos tinham UMA bolha: a rede resgata as NAO-flagradas, e nao havia."""
    assert mod._drop_bolhas(_RASCUNHO_T18, {_RASCUNHO_T18}) == ""


# --- B: o defeito, de ponta a ponta -----------------------------------------------------------------


async def test_b_fio_completo_o_t18_nao_sai_mais_mudo(monkeypatch: Any) -> None:
    """VERMELHO antes / VERDE depois: o trilho e o mesmo do dump (regen `repeticao`, regen do
    trilho `mudo`), as duas reincidem — e agora o piso anti-mudo entrega a bolha original em vez
    de deixar o cliente no vacuo. A metrica `passou_por_falta_de_alternativa` acende: silencio
    evitado NAO e conduta boa, e o menos ruim de duas saidas ruins."""
    _judge_ok(monkeypatch)
    antes = _piso_usado("repeticao")
    regen = _RegenSequencia(_REGEN1_T18, _RASCUNHO_T18)  # reincide nas duas
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T18, fala_cliente=_BURST_T18, historicas=_HISTORICAS_T18)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao", "mudo"]
    assert _texto_ao_cliente(res, state) == _RASCUNHO_T18
    assert _piso_usado("repeticao") == antes + 1.0
    # A regen inutilizavel e despachada ZERADA (usage preservado p/ o custo do turno).
    assert _msgs_update(res).get("regen1") == ""


# --- C: o lembrete da recuperacao para de mentir (controle (iii)) -----------------------------------


async def test_c_a_recuperacao_leva_a_razao_verdadeira_com_a_bolha_colada(
    monkeypatch: Any,
) -> None:
    """prompts[170] do dump: "ela era so raciocinio interno ou veio VAZIA". Era falso — o rascunho
    foi VETADO por `repeticao` — e com a mentira ia embora a unica informacao capaz de fazer o
    modelo escapar: a lista literal das bolhas ofensoras."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia(_REGEN1_T18, _RASCUNHO_T18)
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T18, fala_cliente=_BURST_T18, historicas=_HISTORICAS_T18)
    await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    recuperacao = regen.chamadas[1]
    # O TRILHO segue sendo o do `mudo` (metrica/orcamento); a RAZAO e a do gatilho vencedor.
    assert recuperacao["gatilho"] == "mudo"
    feedback = recuperacao["feedback_gatilho"]
    assert feedback is not None
    assert "veio VAZIA" not in feedback
    assert mod._FEEDBACK_GATILHO["repeticao"] in feedback
    assert _RASCUNHO_T18 in feedback  # a bolha ofensora, palavra por palavra
    assert "tentou reescrever uma vez e caiu no MESMO problema" in feedback


async def test_c_a_recuperacao_de_gatilho_sem_versao_rica_ainda_cita_a_bolha(
    monkeypatch: Any,
) -> None:
    """Gatilho sem feedback enriquecido na t1 (`sonda` manda a razao estatica + `bolhas_vetadas`):
    a recuperacao ainda tem de citar a bolha, senao o modelo so recebe um rotulo."""
    _judge_ok(monkeypatch)
    probe = "O que você procura ?"
    regen = _RegenSequencia(probe, probe)  # reincide nas duas
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(probe, fala_cliente="oi", historicas=[])
    await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert [c["gatilho"] for c in regen.chamadas] == ["sonda", "mudo"]
    feedback = regen.chamadas[1]["feedback_gatilho"]
    assert mod._FEEDBACK_GATILHO["sonda"] in feedback
    assert f'"{probe}"' in feedback  # citacao literal, que a t1 so tinha em `bolhas_vetadas`


# --- D: o rascunho vetado passa a ser as DUAS formas ja tentadas ------------------------------------


async def test_d_a_recuperacao_veta_as_duas_formas_ja_tentadas(monkeypatch: Any) -> None:
    """Causa 2: a recuperacao recebia so o ORIGINAL e o modelo o reescrevia pela terceira vez
    (eb04:43087783055505: "...numero certinho amor" -> "...numero" -> "...numero certinho").
    Agora as duas formas vetadas viajam juntas."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia(_REGEN1_T18, _RASCUNHO_T18)
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T18, fala_cliente=_BURST_T18, historicas=_HISTORICAS_T18)
    await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    rascunho_da_recuperacao = regen.chamadas[1]["rascunho"]
    assert _RASCUNHO_T18 in rascunho_da_recuperacao
    assert _REGEN1_T18 in rascunho_da_recuperacao


# --- E: controles NEGATIVOS ------------------------------------------------------------------------


async def test_e_gatilho_de_seguranca_esvaziando_o_turno_continua_mudo(monkeypatch: Any) -> None:
    """Controle (i): `midia_afirmada` e SEGURANCA. Bolha UNICA, as duas regens reincidem, a rede
    nao tem o que resgatar — e o piso NAO abre. Mentira sobre envio que nunca houve nao vira
    excecao por o turno ficar mudo: aqui o mudo E a saida certa."""
    _judge_ok(monkeypatch)
    antes = _piso_usado("midia_afirmada")
    regen = _RegenSequencia(_MENTIRA_DE_MIDIA, _MENTIRA_DE_MIDIA)
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_MENTIRA_DE_MIDIA, fala_cliente="cadê o vídeo amor?", historicas=[])
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["midia_afirmada", "mudo"]
    assert _texto_ao_cliente(res, state) == ""
    assert _piso_usado("midia_afirmada") == antes


async def test_e_seguranca_escondida_atras_da_repeticao_nao_vaza_pelo_piso(
    monkeypatch: Any,
) -> None:
    """Controle (i-bis), o furo sutil: o scan para no PRIMEIRO gatilho por precedencia, entao um
    turno [bolha repetida, mentira de midia] arma `repeticao` e ninguem olha a mentira. Se o piso
    devolvesse o original inteiro so por o gatilho vencedor ser de qualidade, a mentira sairia ao
    cliente pelo caminho mais silencioso do no. O piso re-roda a bateria de SEGURANCA e desiste."""
    _judge_ok(monkeypatch)
    regen = _RegenSequencia("", "")  # as duas inutilizaveis
    monkeypatch.setattr(mod, "_regenerar", regen)

    turno = f"{_RASCUNHO_T18}\n\n{_MENTIRA_DE_MIDIA}"
    state = _state(turno, fala_cliente=_BURST_T18, historicas=_HISTORICAS_T18)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert _texto_ao_cliente(res, state) == ""  # mudo, e nao a mentira


async def test_e_regen_da_t1_que_limpa_nao_muda_nada(monkeypatch: Any) -> None:
    """Controle (ii): caminho feliz intacto. A regen #1 devolve fala nova e limpa -> uma unica
    chamada, nenhuma recuperacao, nenhum piso: quem sai ao cliente e a regen."""
    _judge_ok(monkeypatch)
    antes = _piso_usado("repeticao")
    limpa = "To na Latino Coelho 128, quando você chegar me chama que eu desço"
    regen = _RegenSequencia(limpa)
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T18, fala_cliente=_BURST_T18, historicas=_HISTORICAS_T18)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao"]  # nao houve recuperacao
    assert _texto_ao_cliente(res, state) == limpa
    assert _piso_usado("repeticao") == antes


async def test_e_pos_escalada_o_piso_nao_ressuscita_fala_de_venda(monkeypatch: Any) -> None:
    """Controle (iv): com escalada ABERTA no turno a decisao e de outro no — o guard nao reabre a
    boca da IA. `repeticao` nem arma pos-escalada, entao o turno so-raciocinio cai no `mudo` e o
    piso tem de continuar fechado (eb02:21123135741957 t12)."""
    from langchain_core.messages import ToolMessage

    _judge_ok(monkeypatch)
    regen = _RegenSequencia("")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_RASCUNHO_T18, fala_cliente=_BURST_T18, historicas=_HISTORICAS_T18)
    state["messages"].append(
        ToolMessage(content=f"{mod.ESCALADA_ABERTA_PREFIXO} ok", tool_call_id="tc1", id="tm1")
    )
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    # Nada armou (escalada desarma os gatilhos de QUALIDADE): o turno segue como estava.
    assert not regen.chamadas
    assert _texto_ao_cliente(res, state) == _RASCUNHO_T18
