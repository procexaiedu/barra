"""O rig lendo o TURNO como ele foi, e nao como as mensagens ficaram (loop-massa r3, 12a/12b/12c).

Puro: sem DB, sem credito, sem LLM. Tres defeitos do harness (12a/12b na r3, 12c no c7):

- **12a** — o transcrito lia `tool_calls` das AIMessages; quando o output_guard regenera,
  `_zerar_turno` reescreve essas mensagens SEM os tool_calls e o transcrito saia
  "turno sem extracao" em 26 turnos que registraram (concentrados no FECHAMENTO). A fonte da
  verdade e o CARIMBO do State (`_extracao_registrada`), que o lado do agente ja usa.
- **12b** — `VeredictoE2E.ok` era `conduziu and not violacoes`, e `conduziu` e so
  `estado_final in ESTADOS_CONDUZIDOS`: corrida que terminou em `Aguardando_confirmacao` com a IA
  PAUSADA e bolha VAZIA no turno do fechamento entrou no corpus com `veredito_ok: true`.
- **12c** (c7) — MESMA raiz do 12a, na outra regua: `ResultadoTurno.tool_calls` tambem vinha das
  AIMessages, entao o turno regenerado contava ZERO midia. No `duvida_das_fotos` o book saiu de
  verdade (3x `enviar_midia`) e `book_na_duvida_ok`/`book_uma_bolha_ok` reprovaram em falso. A
  fonte da verdade do EFEITO e `barravips.tool_calls`, que o guard nao apaga.
"""

from __future__ import annotations

import asyncio
from typing import Any

from evals.e2e.avaliacao import avaliar_e2e
from evals.e2e.perfil import PerfilCaso
from evals.e2e.runner import ResultadoE2E
from evals.e2e.sessao import _extracao_do_turno
from evals.harness import (
    Metricas,
    ResultadoTurno,
    _coletar_tools,
    _mesclar_tools,
    _tools_do_banco,
    carimbos_do_estado,
)
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
    escalada_do_turno: str | None = None,
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
        escalada_do_turno=escalada_do_turno,
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


# --- 12c: as tools do turno vem do banco, nao das mensagens ------------------------------------


def _pediu_midia(n: int) -> AIMessage:
    """AIMessage do book: `enviar_midia` n vezes no MESMO turno (<midia>: foto antes do video)."""
    return _ia(
        "Você vai gostar 🥰",
        tool_calls=[
            {
                "name": "enviar_midia",
                "id": f"m{i}",
                "args": {"tag": "corpo", "tipo": "foto" if i < n - 1 else "video", "legenda": ""},
                "type": "tool_call",
            }
            for i in range(n)
        ],
    )


def _linhas_de_midia(n: int) -> list[dict[str, Any]]:
    """O que `barravips.tool_calls` guardou do book (payload do `_executar_idempotente`)."""
    return [
        {
            "tool_name": "enviar_midia",
            "payload": {
                "midia_id": f"id{i}",
                "tag": "corpo",
                "tipo": "foto" if i < n - 1 else "video",
                "legenda": "",
                "de": "propria",
            },
        }
        for i in range(n)
    ]


class _Resultado:
    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self._linhas = linhas

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._linhas


class _ConnFalsa:
    """Conexao que devolve as linhas de `tool_calls` e registra o que foi perguntado."""

    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self._linhas = linhas
        self.chamadas: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> _Resultado:
        self.chamadas.append((sql, params))
        return _Resultado(self._linhas)


def test_book_sobrevive_ao_guard_que_zerou_as_mensagens() -> None:
    """O achado do c7: o guard regenerou o turno da duvida das fotos e o rastro das 3 midias sumiu
    das AIMessages. O banco tem as 3, e e ele que decide — senao a regua do book reprova conduta
    certa e o proximo ciclo "corrige" um bug que nao existe."""
    zeradas = _zerar_turno([_pediu_midia(3)])

    das_mensagens = _coletar_tools(zeradas)
    assert das_mensagens == ([], []), "pre-condicao do achado: o rastro da CHAMADA sumiu"

    nomes, args = _mesclar_tools(das_mensagens, _tools_do_banco_sync(_linhas_de_midia(3)))
    assert nomes == ["enviar_midia"] * 3
    # os args tem que servir a regua do book (`massa._book_em_uma_bolha` le tipo/legenda).
    assert [a["tipo"] for a in args] == ["foto", "foto", "video"]
    assert all(a["legenda"] == "" for a in args)
    assert len(nomes) == len(args), "tool_calls e tool_args sao PARALELOS (zip strict=True)"


def test_tool_sem_rastro_no_banco_continua_vindo_das_mensagens() -> None:
    """So as tools de ESCRITA gravam em `tool_calls`. Trocar uma fonte pela outra perderia as de
    leitura — por isso e MESCLA, nao substituicao."""
    mensagens = (["consultar_agenda", "enviar_midia"], [{"dia": "hoje"}, {"tag": "corpo"}])
    nomes, args = _mesclar_tools(mensagens, (["enviar_midia"], [{"tag": "corpo", "de": "propria"}]))

    assert nomes == ["consultar_agenda", "enviar_midia"]
    assert args[0] == {"dia": "hoje"}


def test_empate_nao_duplica_a_chamada_que_os_dois_lados_tem() -> None:
    """Turno SEM regen: a mesma chamada esta nos dois lados. Contar duas vezes transformaria uma
    foto tímida em "book" (`>= 2`) — inverteria o veredito da regua que este fix veio consertar."""
    nomes, _ = _mesclar_tools((["enviar_midia"], [{"tag": "corpo"}]), _tools_do_banco_sync([]))
    assert nomes == ["enviar_midia"]

    nomes, _ = _mesclar_tools(
        (["enviar_midia"], [{"tag": "corpo"}]), _tools_do_banco_sync(_linhas_de_midia(1))
    )
    assert nomes == ["enviar_midia"]


def test_tools_do_banco_filtra_pelo_turno_e_nao_consulta_a_toa() -> None:
    """Os turnos de uma conversa e2e dividem a MESMA transacao (ROLLBACK so no fim do caso): sem
    filtrar por `turno_id` o turno 5 herdaria as midias do turno 1. E sem turno_id (grafo injetado
    a mao) nem chega a consultar."""
    conn = _ConnFalsa(_linhas_de_midia(2))
    nomes, _ = asyncio.run(_tools_do_banco(conn, ["t-1"]))  # type: ignore[arg-type]

    assert nomes == ["enviar_midia"] * 2
    sql, params = conn.chamadas[0]
    assert "turno_id = ANY" in sql and params == (["t-1"],)

    vazia = _ConnFalsa(_linhas_de_midia(2))
    assert asyncio.run(_tools_do_banco(vazia, [])) == ([], [])  # type: ignore[arg-type]
    assert vazia.chamadas == []


def _tools_do_banco_sync(linhas: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    conn = _ConnFalsa(linhas)
    return asyncio.run(_tools_do_banco(conn, ["t-1"]))  # type: ignore[arg-type]


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


# --- 12d: escalada aberta pelo COORDENADOR, fora do grafo (c8) ---------------------------------


def test_falha_de_infra_invalida_a_corrida_em_vez_de_reprovar_a_ia() -> None:
    """c8: um APITimeoutError do provider virou handoff `modelo_indisponivel` SEM bolha (por
    desenho, 07 §3.3) e a regua contou DUAS violacoes duras — "turno mudo" e "IA pausada sem
    escalada deste turno". Nenhuma delas e conduta: o turno nao chegou a acontecer."""
    v = _veredito([_turno(texto="", ia_pausada=True, escalada_do_turno="modelo_indisponivel")])

    assert v.violacoes == []
    assert v.invalida_por_infra == "modelo_indisponivel"
    assert any("infra" in x and "modelo_indisponivel" in x for x in v.anotacoes)


def test_todo_motivo_de_infra_do_coordenador_invalida() -> None:
    """Os quatro motivos de `escalar_por_exaustao` que nao dizem nada sobre a IA."""
    for motivo in ("modelo_indisponivel", "timeout_grafo", "erro_interno", "exaustao_iteracoes"):
        v = _veredito([_turno(texto="", ia_pausada=True, escalada_do_turno=motivo)])
        assert v.violacoes == [], motivo
        assert v.invalida_por_infra == motivo


def test_judge_do_guard_caido_invalida_em_vez_de_virar_handoff_legitimo() -> None:
    """c12: a QUARTA porta de escalada. O judge de AUP do `output_guard` caiu por rede e o guard
    fechou fail-closed (`_bloquear`), pausando a IA e zerando as bolhas — sem passar por
    `escalar_por_exaustao`. Como `aup_saida_judge_falhou` nao estava no frozenset, a regua leu
    "handoff legitimo, viol=0" e a unica falha de infra da corrida ficou INVISIVEL: em
    `eb02:224236417331442` t6 a resposta certa ja existia ("Continua 400 a 1h amor") e foi
    apagada por um APIConnectionError dentro de `_julgar_aup`."""
    v = _veredito([_turno(texto="", ia_pausada=True, escalada_do_turno="aup_saida_judge_falhou")])

    assert v.violacoes == []
    assert v.invalida_por_infra == "aup_saida_judge_falhou"


def test_escalada_de_sistema_e_legitima_mas_nao_invalida() -> None:
    """Teto de turnos do dia (CUSTO-04), safety filter e truncamento sao decisao MEDIDA do
    sistema: o turno sem bolha e legitimo, a corrida continua valendo (nao e refazivel)."""
    for motivo in ("teto_turnos", "modelo_recusou", "modelo_truncado"):
        v = _veredito([_turno(texto="", ia_pausada=True, escalada_do_turno=motivo)])
        assert v.violacoes == [], motivo
        assert v.invalida_por_infra is None, motivo
        assert any(f"escalada do sistema ({motivo})" in x for x in v.anotacoes), motivo


def test_pausa_externa_sem_escalada_nova_continua_violacao() -> None:
    """A isencao e ESTREITA: sem escalada nova (bloqueio do output_guard, pausa manual do
    operador, pausa herdada) o handoff externo segue sendo violacao dura — foi ele que o 12b
    trouxe, e a porta nova nao pode abri-lo de volta."""
    v = _veredito([_turno(texto="", ia_pausada=True)])

    assert any("mudo" in x for x in v.violacoes)
    assert any("pausada" in x for x in v.violacoes)
    assert v.invalida_por_infra is None
    assert v.ok is False


def test_corrida_boa_com_um_turno_de_infra_no_meio_fica_refazivel() -> None:
    """O flag e da CORRIDA, nao do turno: um turno conduzido antes nao apaga o aborto de infra.
    Quem agrega tem de EXCLUIR a corrida, e para isso precisa ver o motivo mesmo com `ok`."""
    v = _veredito(
        [
            _turno(texto="400 1h amor"),
            _turno(texto="", ia_pausada=True, escalada_do_turno="timeout_grafo"),
        ]
    )

    assert v.violacoes == []
    assert v.invalida_por_infra == "timeout_grafo"


class _ConnEscaladas:
    """Conexao que devolve as escaladas ABERTAS; a 1a resposta e o retrato ANTES do turno."""

    def __init__(self, *respostas: list[dict[str, Any]]) -> None:
        self._respostas = list(respostas)
        self.sqls: list[str] = []

    async def execute(self, sql: str, params: Any = None) -> _Resultado:
        self.sqls.append(sql)
        return _Resultado(self._respostas.pop(0))


def _carimbo(antes: list[dict[str, Any]], depois: list[dict[str, Any]]) -> tuple[str | None, Any]:
    from evals.harness_fiel import _escalada_nova, _escaladas_abertas

    conn = _ConnEscaladas(antes, depois)

    async def _corrida() -> str | None:
        vistas = await _escaladas_abertas(conn, "at-1")  # type: ignore[arg-type]
        return await _escalada_nova(conn, "at-1", vistas)  # type: ignore[arg-type]

    return asyncio.run(_corrida()), conn


def test_escalada_nova_do_coordenador_vira_carimbo_do_turno() -> None:
    """`escalar_por_exaustao` nao chama tool nem toca `messages` (07 §3.3: handoff sem bolha). A
    linha nova em `escaladas` e o UNICO rastro — e `observacao` guarda o motivo literal."""
    obs, _ = _carimbo(
        [{"id": "e1", "observacao": "conteudo_ilegal", "motivo": "outro"}],
        [
            {"id": "e1", "observacao": "conteudo_ilegal", "motivo": "outro"},
            {"id": "e2", "observacao": "modelo_indisponivel", "motivo": "outro"},
        ],
    )
    assert obs == "modelo_indisponivel"


def test_sem_escalada_nova_o_carimbo_e_none() -> None:
    """Pausa HERDADA / `abrir_handoff` no-op pela idempotencia: a escalada ja estava de pe e ja
    foi julgada no turno que a abriu. Carimbar de novo cobraria duas vezes a mesma decisao."""
    aberta = [{"id": "e1", "observacao": "modelo_indisponivel", "motivo": "outro"}]
    assert _carimbo(aberta, list(aberta))[0] is None
    assert _carimbo([], [])[0] is None


def test_carimbo_cai_no_motivo_quando_observacao_e_nula() -> None:
    """Escalada aberta por caminho que nao preenche `observacao` (a coluna e anulavel)."""
    obs, _ = _carimbo([], [{"id": "e9", "observacao": None, "motivo": "pausa manual"}])
    assert obs == "pausa manual"


def test_carimbo_discrimina_por_id_e_nunca_por_aberta_em() -> None:
    """O rig roda o caso inteiro numa transacao: `now()` do default e CONSTANTE dentro dela, entao
    a escalada do turno 5 tem o MESMO `aberta_em` da do turno 1. Uma janela temporal nao separaria
    nada — e o teste existe para o proximo leitor nao "consertar" isso de volta."""
    _, conn = _carimbo([], [{"id": "e2", "observacao": "timeout_grafo", "motivo": "outro"}])
    assert all("aberta_em" not in sql for sql in conn.sqls)
    assert all("fechada_em IS NULL" in sql for sql in conn.sqls)
