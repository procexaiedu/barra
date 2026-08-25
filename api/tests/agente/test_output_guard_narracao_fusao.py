"""Ciclo 7 — NARRACAO DA MECANICA numa bolha UNICA (regressao por interacao de dois fixes).

O defeito nasceu da soma de duas coisas certas do mesmo dia:
  * a fusao DETERMINISTICA do book (post_process) faz o turno de midia sair como bolha UNICA;
  * o Estagio 0 derruba a bolha INTEIRA quando ela narra a mecanica do envio.
No cenario `duvida_das_fotos` a bolha fundida veio com a narracao colada no fim ("As midias ja
sairam junto com a minha mensagem" — parafrase do RETORNO da `enviar_midia`), o drop esvaziou o
turno, a rede do vazio nao tinha irma a resgatar e a regen devolveu uma resposta SEM o
enquadramento do video que o cenario exige.

TRES superficies, porque corrigir uma e deixar a outra e nao corrigir:
  1. `ferramentas/midia.py`: o retorno da tool ENSINAVA a narracao ("anexada (enviada apos o
     texto)… a midia sai do mesmo jeito"). Agora e registro interno, com a proibicao explicita.
  2. `output_guard._sanear_raciocinio`: turno que o Estagio 0 esvaziaria INTEIRO roda de novo em
     modo RESGATE — cirurgia por FRASE na bolha de narracao, a fala boa sobrevive. A decisao e do
     TURNO (nunca da bolha), para `_limpar_bolhas` seguir distributivo.
  3. `_feedback_mudo_com_anexo`: se ainda assim zerar, a regen recebe o pedido de RECONSTRUIR a
     linha que acompanha a midia, nao so "escreva alguma coisa" (incidente #36).

Unit tests sem DB/LLM/credito: mesmo rig de fakes de test_output_guard_ciclo5/mudo_c5.py.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo (memoria
# "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")
midia_mod = importlib.import_module("barra.agente.ferramentas.midia")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- as falas do caso -----------------------------------------------------------------------------

# A bolha UNICA que a fusao do book produz no cenario `duvida_das_fotos`: as bolhas do turno
# juntadas por ". " — as duas primeiras sao fala boa (a segunda e o ENQUADRAMENTO do video que o
# cenario cobra), a terceira e a narracao da mecanica.
_FALA_1 = "Sou eu mesma amor, bem gata como nas fotos rs"
_FALA_2 = "Gravei um vídeo pra você 🥰"
_NARRACAO = "As mídias já saíram junto com a minha mensagem"
_BOLHA_FUNDIDA = f"{_FALA_1}. {_FALA_2}. {_NARRACAO}"
_RESGATE = f"{_FALA_1}. {_FALA_2}."

# A bolha REAL do t12 de eb04:23966555099311 (mesma forma, do dump do ciclo 5).
_BOLHA_T12 = (
    "Só você vai ver esse rs. Te espero hoje, fecha ? A mídia já saiu junto com a minha mensagem"
)


# --- rig ------------------------------------------------------------------------------------------


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


def _state(texto: str, *, fala_cliente: str = "você é você mesma?") -> dict[str, Any]:
    """Turno de MIDIA: a `enviar_midia` executou (e a fusao do book veio dela)."""
    msgs: list[BaseMessage] = [
        HumanMessage(content=fala_cliente, id="h1"),
        AIMessage(
            content=texto,
            id="a1",
            usage_metadata=_USAGE,
            tool_calls=[{"name": "enviar_midia", "id": "tc1", "args": {}}],
        ),
        ToolMessage(content="midia enviada", tool_call_id="tc1"),
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


def _texto_ao_cliente(res: Any, state: dict[str, Any]) -> str:
    por_id: dict[str, str] = {
        str(m.id): str(m.content)
        for m in state["messages"]
        if isinstance(m, AIMessage) and m.usage_metadata is not None
    }
    for m in (res.update or {}).get("messages", []):
        por_id[str(m.id)] = str(m.content)
    return "\n\n".join(p for p in por_id.values() if p.strip())


# --- 1: a bolha UNICA fundida perde a frase, nao o turno ------------------------------------------


def test_bolha_unica_fundida_perde_so_a_frase_de_narracao() -> None:
    texto, msgs = mod._sanear_raciocinio(
        [AIMessage(content=_BOLHA_FUNDIDA, id="a1", usage_metadata=_USAGE)], _BOLHA_FUNDIDA
    )
    assert texto == _RESGATE
    assert _NARRACAO not in texto
    assert _FALA_2 in texto  # o enquadramento do video, que o cenario cobra, sobrevive
    assert [str(m.content) for m in msgs] == [_RESGATE]


def test_bolha_unica_real_do_dump_tambem_e_resgatada() -> None:
    texto, _ = mod._sanear_raciocinio(
        [AIMessage(content=_BOLHA_T12, id="a1", usage_metadata=_USAGE)], _BOLHA_T12
    )
    assert texto == "Só você vai ver esse rs. Te espero hoje, fecha ?"


async def test_fio_completo_o_turno_de_midia_nao_zera(monkeypatch: Any) -> None:
    """O defeito medido: bolha unica -> drop -> turno vazio -> rede do vazio sem irma -> regen sem
    o enquadramento. Agora nao ha regen nenhuma: a fala boa segue e so a narracao cai."""
    _judge_ok(monkeypatch)
    regen = _FakeRegen("regen indevida")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state(_BOLHA_FUNDIDA)
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas
    despachado = _texto_ao_cliente(res, state)
    assert despachado == _RESGATE
    assert "junto com a minha mensagem" not in despachado


def test_bolha_100_pct_narracao_continua_sumindo_inteira() -> None:
    """Sem frase boa a salvar, o comportamento e o de sempre (a bolha some)."""
    for bolha in (_NARRACAO, "As mídias já saíram no turno, não preciso repetir nada."):
        assert mod._limpar_bolhas(bolha) == ""
        assert mod._resgatar_narracao(bolha) == ""


# --- 2: turno MULTI-BOLHA nao muda de comportamento ------------------------------------------------


def test_narracao_em_turno_multi_bolha_dropa_a_bolha_como_antes() -> None:
    """Com irma viva o drop nao emudece nada — e resgatar a frase aqui duplicaria conteudo que a
    irma ja carrega (a fusao junta as MESMAS bolhas). Pin do comportamento do ciclo 5 V4."""
    turno = f"Só você vai ver esse rs\n\n{_BOLHA_T12}"
    assert mod._limpar_bolhas(turno) == "Só você vai ver esse rs"
    texto, _ = mod._sanear_raciocinio(
        [AIMessage(content=turno, id="a1", usage_metadata=_USAGE)], turno
    )
    assert texto == "Só você vai ver esse rs"


def test_estagio0_segue_distributivo_nos_dois_modos() -> None:
    """O invariante que o modo RESGATE nao pode quebrar: sanear o AGREGADO tem de dar o mesmo que
    sanear cada AIMessage e rejuntar — senao o guard julga um texto e o coordenador despacha
    outro."""
    for pedacos in (
        [_BOLHA_FUNDIDA],  # bolha unica -> modo resgate
        [f"Só você vai ver esse rs\n\n{_BOLHA_T12}"],  # multi-bolha -> modo normal
        ["Consigo às 14h, fecha ?", _NARRACAO],  # narracao em mensagem propria
    ):
        agregado = "\n\n".join(pedacos)
        msgs = [
            AIMessage(content=p, id=f"a{i}", usage_metadata=_USAGE) for i, p in enumerate(pedacos)
        ]
        texto, reescritas = mod._sanear_raciocinio(msgs, agregado)
        # `_reescrever_turno` devolve SO as mensagens que mudaram: o reducer do LangGraph as troca
        # por id e o coordenador re-deriva o texto do turno inteiro — e essa re-derivacao que tem
        # de bater com o `texto` que o guard julgou.
        por_id = {str(m.id): str(m.content) for m in msgs}
        por_id.update({str(m.id): str(m.content) for m in reescritas})
        por_mensagem = "\n\n".join(p for p in por_id.values() if p.strip())
        assert texto == por_mensagem


def test_resgate_nao_conflita_com_os_detectores_de_midia_do_ciclo7() -> None:
    """O residuo do resgate carrega "Gravei um video pra voce" — que o detector novo do ciclo 7
    flagra. Ele nao arma aqui porque a `enviar_midia` EXECUTOU neste turno (o caller so chama o
    detector com `not midia_saiu_no_turno`); sem tool, a mesma frase seria mentira e flagraria."""
    assert mod.bolhas_midia_recem_afirmada(_RESGATE) == [_RESGATE]  # so o detector, sem o gate
    state = _state(_BOLHA_FUNDIDA)
    msgs = mod.mensagens_do_turno(state["messages"])
    assert mod.turno_enviou_midia(msgs, state["messages"]) is True


# --- 3: o retorno da tool nao ensina mais a narracao -----------------------------------------------


@pytest.mark.parametrize(
    "retorno",
    [
        midia_mod._CONFIRMACAO.format(tipo="Vídeo", tag="apresentacao"),
        midia_mod._CONFIRMACAO_PARCEIRA.format(tipo="Foto"),
    ],
)
def test_retorno_da_tool_nao_tem_frase_repassavel(retorno: str) -> None:
    # As duas frases que o modelo parafraseava como bolha ao cliente sairam.
    assert "enviada após o texto" not in retorno
    assert "sai do mesmo jeito" not in retorno
    # E a proibicao esta explicita (e o retorno se declara registro interno, nao fala).
    assert "registro interno do sistema" in retorno
    assert "não se repassa ao cliente" in retorno
    assert "NÃO narre o envio" in retorno
    # Cinto-suspensorio: se o modelo copiar o retorno verbatim, o Estagio 0 derruba a bolha.
    assert mod.tem_marcador_raciocinio(retorno) is True


def test_retorno_da_tool_preserva_o_contrato_do_2o_passe() -> None:
    """A 2a metade do retorno existe por causa de `objetivo_rapido` t1 (trace 66b8161e): sem ela o
    modelo re-emitia a bolha do 1o passe e o cliente recebia a pergunta duas vezes."""
    retorno = midia_mod._CONFIRMACAO.format(tipo="Foto", tag="corpo")
    assert "não repita nenhuma delas" in retorno
    assert "responda" in retorno and "vazio" in retorno


# --- 4: o lembrete da regen, se o turno zerar mesmo assim -----------------------------------------


def test_feedback_mudo_com_anexo_pede_o_enquadramento_de_volta() -> None:
    msg = mod._feedback_mudo_com_anexo(["as suas fotos/video"])
    assert "as suas fotos/video" in msg
    assert "enquadramento" in msg
    # Nomear o proibido E dar a direcao (incidente #36): a intencao e prescrita, a frase nao.
    assert "não explique o envio" in msg or "nao explique o envio" in msg
    assert msg != mod._FEEDBACK_GATILHO["mudo"]


def test_feedback_mudo_sem_anexo_cai_na_razao_estatica() -> None:
    assert mod._feedback_mudo_com_anexo([]) == mod._FEEDBACK_GATILHO["mudo"]
