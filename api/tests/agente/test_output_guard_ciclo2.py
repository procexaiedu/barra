"""Ciclo 2 da campanha 13/08 — os tres defeitos do lote, no output_guard.

D1 — token de CONTROLE do provider vazando na bolha (INEDITO): "Tudo bem sim</｜｜DSML｜｜parameter>"
     foi ao cliente (eb03:265695300456547 t0, trace ec23d226). O Estagio 0 agora strippa a
     substring do token (`_RE_TOKEN_PROVIDER`) mantendo a fala, e `tem_marcador_system` — a fonte
     unica dos evals (checks.py / e2e/avaliacao.py / online do coordenador) — flagra o fragmento
     se ele voltar por um caminho sem strip.

D2 — narracao de MECANICA DO SISTEMA como fala (recorrencia): "As midias ja sairam no turno, nao
     preciso repetir nada." (c2-fotos/duvida_das_fotos_rep1 t2). Familia nova no
     `_MARCADORES_RACIOCINIO`: bolha flagrada e descartada no Estagio 0, irmas preservadas.

D3 — CAUDA PASSIVA (recorrencia, 3 casos): a IA encerra devolvendo a iniciativa sem passo
     concreto. Gatilho novo `despedida` (rede de MELHORIA): detector deterministico na ULTIMA
     bolha -> regen com conduta substituta; persistiu -> pass-through. Nao arma com hora/dia
     concreto ou pergunta na bolha, pos-escalada, nem sobre recusa dura do cliente.

Unit tests sem DB/LLM (mesmo rig de test_output_guard_regen.py): fakes de conn/pool/regen/judge.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from barra.agente.contexto import ContextAgente
from barra.agente.ferramentas.escalada import ESCALADA_ABERTA_PREFIXO

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


def _state(texto: str, *, escalada: bool = False, fala_cliente: str = "oi") -> dict[str, Any]:
    msgs: list[BaseMessage] = [HumanMessage(content=fala_cliente, id="h1")]
    if escalada:
        msgs.append(
            ToolMessage(content=f"{ESCALADA_ABERTA_PREFIXO} aviso enviado", tool_call_id="t1")
        )
    msgs.append(AIMessage(content=texto, id="a1", usage_metadata=_USAGE))
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


# --- D1: token de controle do provider ------------------------------------------------------------

# A bolha REAL do dump (ciclo2/eb03_265695300456547_lid.json, t0): fragmento parcial do token DSML
# do DeepSeek colado na fala boa, no FIM da bolha.
_TURNO_D1 = "Oii\n\nBom dia amor\n\nTudo bem sim</｜｜DSML｜｜parameter>"


def test_d1_strippa_o_token_real_e_a_fala_sobrevive() -> None:
    # O caso real literal: o fragmento sai, as tres bolhas de fala ficam intactas.
    assert mod._limpar_bolhas(_TURNO_D1) == "Oii\n\nBom dia amor\n\nTudo bem sim"


@pytest.mark.parametrize(
    "bruta,limpa",
    [
        # fragmento TRUNCADO no fim da bolha (sem o `>` de fechamento)
        ("Tudo bem sim</｜｜DSML", "Tudo bem sim"),
        # token de fim-de-sentenca inteiro (com o separador ▁ U+2581)
        ("oi amor<｜end▁of▁sentence｜>", "oi amor"),
        # resto solto SEM o `<` de abertura
        ("Tudo bem sim｜｜DSML｜｜parameter>", "Tudo bem sim"),
        # token de papel do template de chat
        ("<｜User｜>pode vir amor", "pode vir amor"),
        # residuo `</...parameter>` sem a barra fullwidth
        ("consigo sim</parameter>", "consigo sim"),
    ],
)
def test_d1_strippa_fragmentos_parciais(bruta: str, limpa: str) -> None:
    assert mod._limpar_bolhas(bruta) == limpa


def test_d1_bolha_so_token_some_e_nao_vira_bolha_vazia() -> None:
    assert mod._limpar_bolhas("<｜User｜>") == ""
    assert mod._limpar_bolhas("boa fala amor\n\n<｜end▁of▁sentence｜>") == "boa fala amor"


@pytest.mark.parametrize(
    "bolha",
    [
        # pipe ASCII normal e fala legitima — nunca tocado
        "aceito pix | dinheiro amor",
        "600 1h | 700 2h no meu local",
        # angle-bracket comum sem cara de token
        "te amo <3",
        "600 1h (valor fechado) amor",
    ],
)
def test_d1_nao_toca_fala_com_pipe_ascii_ou_simbolo_comum(bolha: str) -> None:
    assert mod._limpar_bolhas(bolha) == bolha
    assert mod.tem_marcador_system(bolha) is False


def test_d1_eval_flagra_o_fragmento_se_voltar() -> None:
    # `tem_marcador_system` e a fonte unica dos evals (checks.py, e2e/avaliacao.py, online do
    # coordenador): a bolha DESPACHADA com o fragmento tem de acender o flag.
    assert mod.tem_marcador_system("Tudo bem sim</｜｜DSML｜｜parameter>") is True
    assert mod.tem_marcador_system("oi<｜end▁of▁sentence｜>") is True
    assert mod.tem_marcador_system("amanha de noite fica otimo amor, te espero") is False


# --- D2: narracao de mecanica do sistema ----------------------------------------------------------

# O turno REAL (c2-fotos/duvida_das_fotos_rep1.json, t2): duas bolhas de fala boa + a narracao.
_TURNO_D2 = (
    "Sou eu mesma amor, bem gata como nas fotos rs\n\n"
    "Gravei um vídeo pra você\n\n"
    "As mídias já saíram no turno, não preciso repetir nada."
)


def test_d2_detecta_a_narracao_de_mecanica_real() -> None:
    assert (
        mod.tem_marcador_raciocinio("As mídias já saíram no turno, não preciso repetir nada.")
        is True
    )


def test_d2_estagio0_dropa_a_narracao_e_preserva_as_irmas() -> None:
    assert mod._limpar_bolhas(_TURNO_D2) == (
        "Sou eu mesma amor, bem gata como nas fotos rs\n\nGravei um vídeo pra você"
    )


@pytest.mark.parametrize(
    "bolha",
    [
        "as mídias já saíram amor",  # verbo de despacho sobre "midias" (vocabulario de sistema)
        "não preciso repetir nada",
        "o sistema já anexou a chave",
        "conforme as instruções eu respondo assim",
        "vou seguir o prompt",
    ],
)
def test_d2_detecta_a_familia_de_narracao(bolha: str) -> None:
    assert mod.tem_marcador_raciocinio(bolha) is True


@pytest.mark.parametrize(
    "bolha",
    [
        # "turno" HUMANO (periodo de trabalho) nao e mecanica — o lookahead preserva
        "trabalho no turno da noite amor",
        # fala legitima perto do vocabulario
        "vou te mandar as fotos agora",
        "gravei um vídeo pra você",
        "te passo as instruções de como chegar depois que fechar",  # sem "conforme/segundo"
        "o valor de 1h é 400 no meu local amor",
    ],
)
def test_d2_nao_flagra_fala_legitima(bolha: str) -> None:
    assert mod.tem_marcador_raciocinio(bolha) is False


# --- D3: despedida passiva (cauda que devolve a iniciativa) ---------------------------------------

# As tres falas REAIS do lote (ciclo2/): eb02:190971727847425 t7, eb04:123192630878267 t7,
# eb01:219739251032218 t5 — sempre a ULTIMA bolha do turno.
_TURNOS_D3 = [
    "Poxa\n\nTe espero quando quiser rs",
    "Pode deixar\n\nMe chama quando quiser",
    (
        "O encontro é 1h, mas posso ficar mais se você quiser rs\n\n"
        "Até 2h a gente aproveita com calma, 700\n\n"
        "Me avisa quando você decidir vir que eu te espero"
    ),
]


@pytest.mark.parametrize("turno", _TURNOS_D3)
def test_d3_detecta_as_tres_falas_reais(turno: str) -> None:
    despedidas = mod.bolhas_despedida_passiva(turno)
    assert despedidas == [turno.split("\n\n")[-1]]


@pytest.mark.parametrize(
    "turno",
    [
        # hora concreta na bolha = despedida ATIVA (cobre tambem o estado ja fechado com hora)
        "Te espero às 14h amor",
        "Fechado amor\n\nTe espero às 21h então",
        # pergunta avanca — nao e cauda passiva
        "então às 20h combinado?",
        # dia concreto
        "Me chama amanhã então",
        # a passiva NAO e a ultima bolha: a cauda que fica e a ativa
        "Me chama quando quiser\n\nConsigo às 22h, fecha?",
        # instrucao operacional legitima ("quando sair/chegar" nao esta na familia passiva)
        "te espero rs, me avisa quando sair",
    ],
)
def test_d3_nao_flagra_despedida_ativa(turno: str) -> None:
    assert mod.bolhas_despedida_passiva(turno) == []


def test_d3_recusa_dura_do_cliente_desarma_mas_objecao_nao() -> None:
    assert mod.cliente_encerrou_no_burst(["não vou mais, esquece"]) is True
    assert mod.cliente_encerrou_no_burst(["deixa pra lá"]) is True
    # o burst REAL do caso eb02 ("nao vou" + objeto) e objecao de preco, nao recusa — tem de
    # continuar armando o gatilho.
    assert mod.cliente_encerrou_no_burst(["Você tem seu valor, eu não vou pedir desconto"]) is False


def test_d3_feedback_do_gatilho_existe_e_prescreve_a_direcao() -> None:
    # Incidente #36: nomear o proibido E dar a direcao (intencao, nunca frase literal).
    feedback = mod._FEEDBACK_GATILHO["despedida"]
    assert "iniciativa" in feedback and "concreto" in feedback


async def test_d3_dispara_regen_com_gatilho_despedida_e_despacha_a_nova(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Consigo hoje às 20h amor, fecha pra você?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Poxa\n\nTe espero quando quiser rs"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "despedida"
    # veto GRANULAR: so a cauda passiva vai vetada; o resto do rascunho e aproveitavel.
    assert list(regen.chamadas[0]["bolhas_vetadas"]) == ["Te espero quando quiser rs"]
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Consigo hoje às 20h amor, fecha pra você?"


async def test_d3_persistiu_na_regen_e_pass_through(monkeypatch: Any) -> None:
    # Rede de MELHORIA: persistiu -> o texto segue como esta (dropar a despedida sem substituta e
    # o anti-padrao do incidente #36); nunca handoff nem mudo. Desde o ciclo 4 o pass-through do
    # persistiu vale para a bolha UNICA (drop = mudo, pior); a regen reincidente com irmas boas
    # no turno tem a cauda CORTADA — ver test_output_guard_ciclo4.py (A3).
    cap_handoff: list[Any] = []

    async def _handoff(conn: Any, **kwargs: Any) -> None:
        cap_handoff.append(kwargs)

    monkeypatch.setattr(mod_defesa, "abrir_handoff", _handoff)
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Me chama quando quiser")  # reincide, bolha unica
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Pode deixar\n\nMe chama quando quiser"), _runtime()
    )

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Me chama quando quiser"  # saiu como esta
    assert not cap_handoff


async def test_d3_pos_escalada_nao_dispara(monkeypatch: Any) -> None:
    # Turno com rastro ESCALADA_ABERTA_PREFIXO: a espera/encaminhamento e decisao de outro no —
    # regenerar uma fala de venda por cima seria o bug de eb02:21123135741957 t12.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("qualquer regen seria errada aqui")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Me chama quando quiser", escalada=True), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas


async def test_d3_recusa_dura_no_burst_nao_dispara(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _FakeRegen("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Tranquilo amor\n\nMe chama quando quiser", fala_cliente="não vou mais, esquece"),
        _runtime(),
    )

    assert res.goto == END
    assert not regen.chamadas
