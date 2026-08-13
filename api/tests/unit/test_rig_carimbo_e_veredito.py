"""O rig lendo o TURNO como ele foi, e nao como as mensagens ficaram (loop-massa r3, 12a/12b).

Puro: sem DB, sem credito, sem LLM. Dois defeitos do harness, medidos na r3:

- **12a** — o transcrito lia `tool_calls` das AIMessages; quando o output_guard regenera,
  `_zerar_turno` reescreve essas mensagens SEM os tool_calls e o transcrito saia
  "turno sem extracao" em 26 turnos que registraram (concentrados no FECHAMENTO). A fonte da
  verdade e o CARIMBO do State (`_extracao_registrada`), que o lado do agente ja usa.
- **12b** — `VeredictoE2E.ok` era `conduziu and not violacoes`, e `conduziu` e so
  `estado_final in ESTADOS_CONDUZIDOS`: corrida que terminou em `Aguardando_confirmacao` com a IA
  PAUSADA e bolha VAZIA no turno do fechamento entrou no corpus com `veredito_ok: true`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from evals.e2e.avaliacao import avaliar_e2e
from evals.e2e.perfil import PerfilCaso
from evals.e2e.runner import ResultadoE2E
from evals.e2e.sessao import _extracao_do_turno
from evals.harness import Metricas, ResultadoTurno, carimbos_do_estado
from evals.harness_fiel import GraphAuditado
from langchain_core.messages import AIMessage, ToolMessage

from barra.agente.nos.output_guard import _zerar_turno
from barra.dominio.atendimentos.service import _MSG_GUARD_PISO, _MSG_GUARD_REAGENDAMENTO

_ARGS = {"intencao": "agendamento", "valor_acordado": 400, "duracao_horas": 1}
_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def _ia(texto: str, **kw: Any) -> AIMessage:
    """AIMessage GERADA no turno (o `usage_metadata` e o que a marca como do turno)."""
    return AIMessage(content=texto, id=kw.pop("id", "m1"), usage_metadata=_USAGE, **kw)


def _extraiu() -> AIMessage:
    return _ia(
        "",
        tool_calls=[{"name": "registrar_extracao", "id": "c1", "args": _ARGS, "type": "tool_call"}],
    )


_NODES = ["prepare_context", "intercept_disclosure", "llm", "extrair", "post_process"]


def _turno(
    *,
    texto: str = "ok amor",
    mensagens: list[Any] | None = None,
    estado: str = "Qualificado",
    ia_pausada: bool = False,
    estado_grafo: dict[str, Any] | None = None,
    tool_calls: list[str] | None = None,
    tool_args: list[dict[str, Any]] | None = None,
    nodes: list[str] | None = None,
) -> ResultadoTurno:
    """Turno em que o GRAFO RODOU (`nodes` default = a trajetoria real). `nodes=[]` + `mensagens`
    vazias e o turno que nem foi processado (gate `ia_pausada`/terminal do coordenador)."""
    return ResultadoTurno(
        texto=texto,
        tool_calls=tool_calls or [],
        tool_args=tool_args or [],
        nodes=_NODES if nodes is None else nodes,
        prompt_modelo=[],
        mensagens=mensagens or [],
        estado_final={"estado": estado, "pix_status": "nao_solicitado", "ia_pausada": ia_pausada},
        metricas=Metricas(),
        estado_grafo=estado_grafo or {},
    )


def _perfil() -> PerfilCaso:
    return PerfilCaso(nome="teste", abertura="oi", modelo={})


def _veredito(turnos: list[ResultadoTurno]) -> Any:
    res = ResultadoE2E(
        perfil_nome="teste",
        trajetoria=[t.estado_final for t in turnos],
        turnos=turnos,
        estado_final=(turnos[-1].estado_final or {}).get("estado") if turnos else None,
    )
    return avaliar_e2e(res, _perfil())


# --- 12a: a extracao do turno vem do carimbo ---------------------------------------------------


def test_extracao_sobrevive_ao_guard_que_zerou_as_mensagens() -> None:
    """O turno de fechamento com regen: as AIMessages voltam vazias e sem tool_calls, e o
    transcrito reportava `extracao: null`. Com o carimbo, reporta o que de fato registrou."""
    zeradas = _zerar_turno([_extraiu()])
    r = _turno(
        mensagens=[*zeradas, _ia("fechado amor", id="m2")],
        estado_grafo={"_extracao_registrada": _ARGS},
    )

    assert r.tool_calls == [], "pre-condicao do achado: o rastro da CHAMADA sumiu"
    assert r.extracao == _ARGS
    assert _extracao_do_turno(r) == _ARGS  # o campo `extracao` do transcrito da sessao


def test_extracao_cai_na_varredura_sem_carimbo() -> None:
    """Sem carimbo (State montado a mao, turno que nao passou pelo `extrair`) o fallback vale."""
    assert _turno(mensagens=[_extraiu()]).extracao == _ARGS
    assert _turno().extracao is None


def test_extracao_revertida_nao_ressuscita() -> None:
    """Carimbo NEGATIVO (`None` explicito: o `extrair` errou e reverteu) vence a varredura — senao
    o rig publicaria como extracao do turno um payload que nao existe no banco."""
    r = _turno(mensagens=[_extraiu()], estado_grafo={"_extracao_registrada": None})
    assert r.extracao is None


def test_carimbos_do_estado_so_leva_chave_presente() -> None:
    """Presenca e o veredito: inventar a chave trocaria "nao passou pelo `extrair`" por
    "passou e nao gravou"."""
    assert carimbos_do_estado({"messages": [], "_extracao_registrada": _ARGS}) == {
        "_extracao_registrada": _ARGS
    }
    assert carimbos_do_estado({"messages": []}) == {}
    assert carimbos_do_estado({"_mute_por_erro_de_tool": True}) == {"_mute_por_erro_de_tool": True}


class _GraphFalso:
    """Grafo que devolve um State com carimbo diferente por invocacao (drain do coordenador)."""

    def __init__(self, estados: list[dict[str, Any]]) -> None:
        self._estados = estados
        self.i = 0

    async def ainvoke(self, _entrada: Any, *, config: Any = None, context: Any = None) -> Any:
        estado = self._estados[self.i]
        self.i += 1
        return estado


def test_graph_auditado_guarda_o_carimbo_da_ultima_invocacao() -> None:
    """O drain roda o grafo mais de uma vez sob o mesmo lock; quem decidiu o turno foi a ultima."""
    graph = _GraphFalso(
        [
            {"messages": [], "_extracao_registrada": None},
            {"messages": [], "_extracao_registrada": _ARGS, "_mute_por_erro_de_tool": True},
        ]
    )
    auditado = GraphAuditado(graph)

    asyncio.run(_duas_invocacoes(auditado))

    assert auditado.carimbos == {"_extracao_registrada": _ARGS, "_mute_por_erro_de_tool": True}


async def _duas_invocacoes(auditado: GraphAuditado) -> None:
    await auditado.ainvoke({"messages": []}, config=None, context=None)
    await auditado.ainvoke({"messages": []}, config=None, context=None)


# --- 12b: turno mudo e pausa da IA sao violacao dura -------------------------------------------


def test_turno_mudo_no_fechamento_nao_e_conducao_limpa() -> None:
    """`decidido_rapido_a`: o bloqueio do output_guard pausou a IA e a bolha saiu vazia no turno em
    que o cliente FECHOU — e o veredito dizia `ok: true` porque o estado no banco tinha subido."""
    v = _veredito([_turno(texto="", estado="Aguardando_confirmacao", ia_pausada=True)])

    assert v.conduziu is True  # a linha de chegada esta la, e e isso que enganava o grader
    assert v.ok is False
    assert any("mudo" in x for x in v.violacoes)
    assert any("pausada" in x for x in v.violacoes)


def test_silencio_deliberado_do_extrair_nao_vira_violacao() -> None:
    """`_mute_por_erro_de_tool` e DECISAO de outro no (silencio > reserva fantasma): o carimbo
    existe justamente para o passo seguinte nao desfazer a decisao."""
    v = _veredito(
        [_turno(texto="", estado="Qualificado", estado_grafo={"_mute_por_erro_de_tool": True})]
    )
    assert v.violacoes == []


def test_escalada_do_proprio_turno_nao_e_pausa_externa() -> None:
    """A IA chamou `escalar` e a modelo assumiu: pausa legitima, decidida DENTRO do turno."""
    msgs = [
        _ia("", tool_calls=[{"name": "escalar", "id": "e1", "args": {}, "type": "tool_call"}]),
        ToolMessage(content="escalada aberta", name="escalar", tool_call_id="e1"),
    ]
    v = _veredito([_turno(texto="", mensagens=msgs, ia_pausada=True)])
    assert v.violacoes == []


def test_escalada_silenciosa_da_guarda_tambem_conta() -> None:
    """A guarda do `registrar_extracao` (piso/tipo/reagendamento) escala por dentro, sem tool
    `escalar` — mesmo criterio do coordenador (`MENSAGENS_GUARD_ESCALADA`)."""
    msgs = [ToolMessage(content=_MSG_GUARD_PISO, name="registrar_extracao", tool_call_id="c1")]
    v = _veredito([_turno(texto="So um minutinho amor", mensagens=msgs, ia_pausada=True)])
    assert v.violacoes == []


def test_turno_sob_pausa_herdada_nao_e_turno_mudo() -> None:
    """`externo_a2` t6 (re-prova r3): a IA escalou de propria conta no t5 (canned da guarda) e o
    t6 NEM RODOU O GRAFO — `trace_id: null`, `nodes: []`, `custo 0`, gate `ia_pausada` do
    coordenador. Nao ha bolha porque nao houve turno: rotular isso de "turno mudo" cobra duas
    vezes pela MESMA escalada, que ja foi julgada (e aprovada) no t5. Vira anotacao, e a anotacao
    nao zera o `ok`."""
    msgs = [
        ToolMessage(content=_MSG_GUARD_REAGENDAMENTO, name="registrar_extracao", tool_call_id="c1")
    ]
    v = _veredito(
        [
            _turno(
                texto="Deixa eu ver aqui e ja te retorno vida",
                mensagens=msgs,
                estado="Aguardando_confirmacao",
                ia_pausada=True,
                estado_grafo={"_extracao_registrada": {"cotacao_apresentada": True}},
            ),
            _turno(texto="", estado="Aguardando_confirmacao", ia_pausada=True, nodes=[]),
        ]
    )
    assert v.violacoes == []
    assert v.ok is True
    assert any("turno 2" in x and "nao processado" in x for x in v.anotacoes)


def test_turno_mudo_com_grafo_rodado_continua_violacao() -> None:
    """A isencao acima e ESTREITA: o grafo rodou (`nodes`) e nenhuma bolha chegou — o silencio e
    do modelo, nao do gate. E tambem o descarte do turno na pausa externa (o resgate critico so
    cobre a bolha deterministica), que segue valendo como violacao."""
    v = _veredito([_turno(texto="", estado="Aguardando_confirmacao", ia_pausada=True)])
    assert any("turno 1" in x and "mudo" in x for x in v.violacoes)
    assert any("turno 1" in x and "pausada" in x for x in v.violacoes)
    assert v.ok is False
    assert v.anotacoes == []


def test_turno_so_de_midia_nao_e_mudo() -> None:
    """Foto sem legenda chegou ao cliente: bolha vazia nao e silencio."""
    msgs = [ToolMessage(content="midia enviada", name="enviar_midia", tool_call_id="m1")]
    assert _veredito([_turno(texto="", mensagens=msgs)]).violacoes == []


def test_erro_da_tool_nao_conta_como_escalada() -> None:
    """Tool que FALHOU nao abriu pausa nenhuma (mesmo par de sinais do `extrair_texto_do_turno`)."""
    msgs = [
        ToolMessage(content="ERRO: nao deu", name="escalar", tool_call_id="e1", status="error"),
    ]
    v = _veredito([_turno(texto="", mensagens=msgs, ia_pausada=True)])
    assert any("pausada" in x for x in v.violacoes)
