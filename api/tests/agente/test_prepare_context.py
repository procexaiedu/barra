"""Aceite M0-T4 — prepare_context: gate de pausa + system GERAL + janela deslizante.

ia_pausada=true -> Command(goto=END); senao messages = 2 SystemMessage + N HumanMessage/
AIMessage em ordem cronologica; modelo_manual vira AIMessage com prefixo. Fakes de pool/conn
(sem Postgres real, como o resto da suite); o grafo so e construido p/ provar que a pausa
encerra antes do llm (coordenacao graph.py <-> prepare_context).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from _fakes import _IDENTIDADE_PADRAO, FakeConn, FakePool, FakeRuntime, _Result
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.agente.nos.prepare_context import prepare_context, traduzir_mensagens


def _runtime(
    *,
    ia_pausada: bool = False,
    mensagens: list[dict[str, Any]] | None = None,
) -> FakeRuntime:
    conn = FakeConn(ia_pausada=ia_pausada, mensagens=mensagens or [])
    ctx = ContextAgente(
        db_pool=FakePool(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return FakeRuntime(ctx)


def _linhas_desc() -> list[dict[str, Any]]:
    """3 mensagens; ordem do DB e DESC (mais nova primeiro), o no reverte p/ cronologica."""
    base = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    nova_primeiro = [
        ("modelo_manual", "deixa que eu respondo", base + timedelta(minutes=2)),
        ("ia", "oi amor, tudo bem?", base + timedelta(minutes=1)),
        ("cliente", "ola", base),
    ]
    return [
        {
            "id": uuid4(),
            "direcao": direcao,
            "tipo": "texto",
            "conteudo": conteudo,
            "media_object_key": None,
            "created_at": ts,
        }
        for direcao, conteudo, ts in nova_primeiro
    ]


def test_ia_pausada_retorna_command_end() -> None:
    res = asyncio.run(prepare_context({"messages": []}, _runtime(ia_pausada=True)))
    assert isinstance(res, Command)
    assert res.goto == END


def test_caminho_normal_3_system_mais_janela_cronologica() -> None:
    res = asyncio.run(prepare_context({"messages": []}, _runtime(mensagens=_linhas_desc())))
    assert isinstance(res, Command)
    assert res.goto == "intercept_disclosure"
    msgs = res.update["messages"]
    # 3 SystemMessage (BP_GERAL fundido + BP_MODELO por-modelo + bloco estático do cadastro) + 3
    # da janela, todas string pura (cache do DeepSeek é automático no provider, sem marcador).
    # O 3º bloco nasceu do hoist de custo (traces 11/08): o que só o cadastro dela decide
    # (<sem_menage>/<sem_video_chamada>/<sem_fetiches>/<sem_periodo_longo>/<periodo_de_trabalho>)
    # rendia na cauda volátil e pagava cache-MISS todo turno. Vem por ÚLTIMO no prefixo, para o
    # par [geral][por-modelo] já quente no provider não mudar um byte.
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], SystemMessage)
    assert isinstance(msgs[2], SystemMessage)
    assert "<periodo_de_trabalho>" in msgs[2].content
    assert len(msgs) == 6
    # msgs[3] = contexto dinamico + HumanMessage do cliente (ultimo HumanMessage da janela; a fala
    # dele fica por ULTIMO na cauda -- incidente 29/07)
    assert isinstance(msgs[3], HumanMessage)
    assert msgs[3].content.endswith("ola")
    assert "<situacao_do_atendimento" in msgs[3].content
    # msgs[4] = penultima da janela = AIMessage "oi amor", string pura (sem marcação de cache)
    assert isinstance(msgs[4], AIMessage)
    assert msgs[4].content == "oi amor, tudo bem?"
    # msgs[5] = ultima da janela = modelo_manual, AIMessage com prefixo, content STRING
    assert isinstance(msgs[5], AIMessage)
    assert msgs[5].content == "[mensagem manual da modelo]: deixa que eu respondo"


def _linhas_n(n: int) -> list[dict[str, Any]]:
    """n mensagens alternando cliente/ia, em ordem DESC (mais nova primeiro = cliente)."""
    base = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    return [
        {
            "id": uuid4(),
            "direcao": "cliente" if i % 2 == 0 else "ia",
            "tipo": "texto",
            "conteudo": f"msg {i}",
            "media_object_key": None,
            "created_at": base + timedelta(minutes=n - i),
        }
        for i in range(n)
    ]


def test_janela_sai_como_string_pura() -> None:
    # Sem marcação de cache (DeepSeek cacheia o prefixo automaticamente): toda mensagem da janela
    # — inclusive a penúltima — fica string pura. A última HumanMessage carrega o contexto
    # dinâmico volátil, mas segue str. Nenhum content-block no caminho que roda em prod.
    res = asyncio.run(prepare_context({"messages": []}, _runtime(mensagens=_linhas_n(20))))
    assert isinstance(res, Command)
    for m in res.update["messages"]:
        assert isinstance(m.content, str)


def test_atendimento_id_none_pula_gate() -> None:
    rt = _runtime(mensagens=[])
    rt.context.atendimento_id = None  # type: ignore[assignment]
    res = asyncio.run(prepare_context({"messages": []}, rt))
    assert isinstance(res, Command)
    assert res.goto == "intercept_disclosure"
    # 3 system (BP_GERAL + BP_MODELO + bloco estático do cadastro) + 1 HumanMessage: janela
    # vazia, contexto dinamico anexa novo HumanMessage no fim. BP_MODELO e o bloco do cadastro
    # carregam por modelo_id mesmo com atendimento_id None.
    msgs = res.update["messages"]
    assert len(msgs) == 4
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], SystemMessage)
    assert isinstance(msgs[2], SystemMessage)
    assert isinstance(msgs[3], HumanMessage)
    assert "<situacao_do_atendimento" in msgs[3].content


def test_traduzir_audio_sem_transcricao_vira_placeholder() -> None:
    linhas = [
        {
            "id": uuid4(),
            "direcao": "cliente",
            "tipo": "audio",
            "conteudo": "",
            "media_object_key": "k",
            "created_at": None,
        },
        {
            "id": uuid4(),
            "direcao": "cliente",
            "tipo": "imagem",
            "conteudo": "",
            "media_object_key": "k",
            "created_at": None,
        },
    ]
    out = traduzir_mensagens(linhas)
    assert isinstance(out[0], HumanMessage)
    assert out[0].content == "[áudio que não consegui ouvir]"
    assert out[1].content == "[imagem]"


def test_traduzir_direcao_desconhecida_levanta() -> None:
    linhas = [
        {
            "id": uuid4(),
            "direcao": "sistema",
            "tipo": "texto",
            "conteudo": "x",
            "media_object_key": None,
            "created_at": None,
        },
    ]
    try:
        traduzir_mensagens(linhas)
    except ValueError as exc:
        assert "direcao desconhecida" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("esperava ValueError para direcao fora do enum")


@pytest.mark.needs_key  # build_graph() -> criar_chat_deepseek() exige DEEPSEEK_API_KEY
def test_grafo_pausa_encerra_antes_do_llm() -> None:
    # Prova a coordenacao graph.py <-> prepare_context: sem aresta estatica de saida, a pausa
    # (Command(goto=END)) encerra o turno sem fan-out p/ intercept_disclosure/llm (sem AIMessage).
    graph = build_graph()
    conn = FakeConn(ia_pausada=True, mensagens=[])
    ctx = ContextAgente(
        db_pool=FakePool(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    estado = asyncio.run(graph.ainvoke({"messages": []}, context=ctx))
    assert estado["messages"] == []


# --- evidencia do horario: a correferencia vai ao State (#35, 24/07) --------------------------


def _linhas_sondagem_imediatismo_aceita() -> list[dict[str, Any]]:
    """DESC (mais nova primeiro): a IA sondou "Seria agora ?" e o cliente respondeu "sim"."""
    base = datetime(2026, 7, 24, 2, 17, tzinfo=UTC)
    nova_primeiro = [
        ("cliente", "sim", base + timedelta(minutes=2)),
        ("ia", "Seria agora ?", base + timedelta(minutes=1)),
        ("cliente", "tá atendendo?", base),
    ]
    return [
        {
            "id": uuid4(),
            "direcao": direcao,
            "tipo": "texto",
            "conteudo": conteudo,
            "media_object_key": None,
            "created_at": ts,
        }
        for direcao, conteudo, ts in nova_primeiro
    ]


def test_evidencia_do_horario_vai_ao_state() -> None:
    """A correferencia "sondagem de imediatismo + sim" e publicada no State p/ o no `extrair`
    carimbar a evidencia (e, com ela, promover a `intencao` no dominio). REGRESSAO DE ORDEM: o
    "sim" e o ULTIMO HumanMessage, entao recebe o contexto dinamico concatenado na cauda -- se a
    deteccao rodasse DEPOIS da anexacao ele deixaria de ser uma "afirmacao curta" (e o bloco ainda
    coleria HORAS na cauda) e a flag viria errada."""
    res = asyncio.run(
        prepare_context({"messages": []}, _runtime(mensagens=_linhas_sondagem_imediatismo_aceita()))
    )
    assert isinstance(res, Command)
    assert res.update["horario_evidenciado"] is True
    # o "sim" de fato carrega o contexto dinamico (prova que a anexacao aconteceu na mesma msg)
    ultimo_humano = [m for m in res.update["messages"] if isinstance(m, HumanMessage)][-1]
    assert ultimo_humano.content.endswith("sim")
    assert "<situacao_do_atendimento" in ultimo_humano.content


def test_evidencia_falsa_sem_correferencia() -> None:
    """Janela sem o par sondagem+afirmacao -> flag False (nada sustenta um horario)."""
    res = asyncio.run(prepare_context({"messages": []}, _runtime(mensagens=_linhas_desc())))
    assert isinstance(res, Command)
    assert res.update["horario_evidenciado"] is False


def _linhas_sondagem_com_recuo() -> list[dict[str, Any]]:
    """DESC: sondagem aceita LA ATRAS, mas o cliente ja recuou depois ("ainda nao vai dar")."""
    base = datetime(2026, 7, 24, 2, 17, tzinfo=UTC)
    nova_primeiro = [
        ("cliente", "ainda não vai dar, te chamo depois", base + timedelta(minutes=9)),
        ("ia", "400 1h no meu local amor", base + timedelta(minutes=8)),
        ("cliente", "sim", base + timedelta(minutes=2)),
        ("ia", "Seria agora ?", base + timedelta(minutes=1)),
    ]
    return [
        {
            "id": uuid4(),
            "direcao": direcao,
            "tipo": "texto",
            "conteudo": conteudo,
            "media_object_key": None,
            "created_at": ts,
        }
        for direcao, conteudo, ts in nova_primeiro
    ]


def test_evidencia_nao_persiste_apos_recuo() -> None:
    """A evidencia e EVENTO, nao estado. Um "sim" de turnos atras nao pode seguir sustentando o
    horario (nem, por ele, a `intencao`) depois de o cliente recuar -- so o burst ATUAL conta."""
    res = asyncio.run(
        prepare_context({"messages": []}, _runtime(mensagens=_linhas_sondagem_com_recuo()))
    )
    assert isinstance(res, Command)
    assert res.update["horario_evidenciado"] is False


# --- pecas do contexto no State (spec extracao-janela-dedicada) --------------------------------


def test_pecas_do_turno_vao_ao_state_e_nao_ao_que_o_chat_recebe() -> None:
    """As tres pecas (ancora temporal, bloco `<ja_registrado>` e conversa CRUA) sao publicadas no
    State p/ a janela dedicada da extracao monta-las depois. O que o chat recebe nao muda: o bloco
    NAO aparece em `messages` (a cauda segue msg do cliente + contexto dinamico)."""
    rt = _runtime(mensagens=_linhas_desc())
    rt.context.agora_utc = datetime(2026, 7, 25, 17, 30, tzinfo=UTC)  # = 14:30 em Brasilia

    res = asyncio.run(prepare_context({"messages": []}, rt))

    assert isinstance(res, Command)
    assert res.update["agora_turno"] == datetime(2026, 7, 25, 14, 30)
    assert res.update["ja_registrado"].startswith("<ja_registrado>")
    assert all("<ja_registrado>" not in str(m.content) for m in res.update["messages"])
    # A conversa crua e a janela como ela e: mesma ordem, sem o belief colado na cauda (o que
    # `messages` ja nao permite separar).
    crua = res.update["conversa_crua"]
    assert [str(m.content) for m in crua] == [
        "ola",
        "oi amor, tudo bem?",
        "[mensagem manual da modelo]: deixa que eu respondo",
    ]


# --- carimbo do <local_de_encontro> no State (diagnostico 11/08, P0-1) --------------------------


_ENDERECO_FAKE = "Av. Aquidabã, 130 - Centro, Campinas - SP"


class _ConnComLocal(FakeConn):
    """FakeConn com endereco no cadastro e o atendimento no estado/tipo que o gate pede."""

    def __init__(self, *, estado: str, tipo: str | None, **kw: Any) -> None:
        super().__init__(
            ia_pausada=False,
            mensagens=_linhas_desc(),
            identidade={
                **_IDENTIDADE_PADRAO,
                "endereco_formatado": _ENDERECO_FAKE,
                "nome_local": "Hotel Sirius",
            },
            **kw,
        )
        self._estado = estado
        self._tipo = tipo

    async def execute(self, query: str, params: Any = None) -> Any:
        if "numero_curto" in query and "FROM barravips.atendimentos" in query:
            res = await super().execute(query, params)
            linha = await res.fetchone()
            assert linha is not None
            return _Result([{**linha, "estado": self._estado, "tipo_atendimento": self._tipo}])
        return await super().execute(query, params)


def _rt(conn: FakeConn) -> FakeRuntime:
    return FakeRuntime(
        ContextAgente(
            db_pool=FakePool(conn),  # type: ignore[arg-type]
            redis=None,  # type: ignore[arg-type]
            modelo_id=str(uuid4()),
            atendimento_id=str(uuid4()),
            cliente_id=str(uuid4()),
            turno_id=str(uuid4()),
        )
    )


def test_carimbo_do_local_espelha_o_bloco_que_entrou_no_prompt() -> None:
    """O State publica o ponto de encontro EXATAMENTE como o <local_de_encontro> o apresentou —
    e o output_guard le esse carimbo em vez de reavaliar o gate com a linha ja pos-extracao."""
    res = asyncio.run(
        prepare_context({"messages": []}, _rt(_ConnComLocal(estado="Qualificado", tipo="interno")))
    )

    assert isinstance(res, Command)
    carimbo = res.update["local_endereco_no_prompt"]
    assert carimbo is not None
    cauda = str([m for m in res.update["messages"] if isinstance(m, HumanMessage)][-1].content)
    assert "<local_de_encontro>" in cauda
    # O carimbo e o texto do bloco, no degrau vigente (Qualificado: SEM o numero da rua).
    assert carimbo == "Hotel Sirius — Av. Aquidabã - Centro, Campinas - SP"
    assert carimbo.split(" — ")[1] in cauda


def test_sem_bloco_no_prompt_o_carimbo_vem_vazio() -> None:
    """Triagem: o gate segura o bloco, entao nao ha o que o guard possa cobrar."""
    res = asyncio.run(
        prepare_context({"messages": []}, _rt(_ConnComLocal(estado="Triagem", tipo="interno")))
    )

    assert isinstance(res, Command)
    assert res.update["local_endereco_no_prompt"] is None
    cauda = str([m for m in res.update["messages"] if isinstance(m, HumanMessage)][-1].content)
    assert "<local_de_encontro>" not in cauda
