"""Loop fechado cliente-simulado <-> grafo da jornada dual-control (EVAL-12, 08b §3.2/§5).

NAO-GATE (ver sim/README.md): o verde-no-sim NUNCA conta para o cutover. QUALQUER falha encontrada
numa jornada e PROMOVIDA a fixture pre-roteirizada de `scripted_5/` (EVAL-01) -- e o corpus
DETERMINISTICO (pre-roteirizado, mesmas seeds) que conta para o gate, jamais o simulador.

A jornada e um loop fechado com TETO de turnos: a cada passo o cliente decide (cliente.decidir) e
ou (a) manda uma MENSAGEM -> o grafo roda 1 turno (reusa o seeding/invoke do runner.py), ou
(b) aplica um ATO dual-control (atos.py) que muta o estado real sem rodar o grafo. A trajetoria
(mensagens da IA + atos + estado) e coletada para o operador inspecionar e roteirizar a fixture.

Reusa `runner.py` (mesmo banco de teste, mesmo seeding, mesmo grafo sem checkpointer) carregando-o
por CAMINHO via importlib -- evals/ esta fora do pacote `barra` (igual tests/evals/test_runner_gate).
needs_db + needs_anthropic_api: NAO rodar offline (o loop chama o grafo e o cliente-LLM).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection

from . import atos as _atos
from .cliente import AcaoCliente, ClienteLike

_RUNNERS = Path(__file__).resolve().parents[1] / "runners"


def _carregar_runner() -> Any:
    """Carrega runner.py por caminho (evals/ fora do pacote `barra`) -- reusa seeding/invoke/captura."""
    caminho = _RUNNERS / "runner.py"
    spec = importlib.util.spec_from_file_location("eval_runner", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("eval_runner", modulo)
    spec.loader.exec_module(modulo)
    return modulo


@dataclass
class PassoJornada:
    """Um passo do loop: a acao do cliente + a bolha da IA (se rodou turno) + o estado pos-passo.

    Os campos de OBSERVABILIDADE (`pix_status`, `tools_chamadas`, `escalou`, `nodes_visitados`)
    afloram sinais que o turno ja produzia mas a serializacao descartava (EVAL-12): que tools a IA
    chamou, se abriu linha em `escaladas` (escala via tool `escalar`; NAO a escala-por-reincidencia
    do disclosure, que depende de redis real e nao roda no sim), e que nos do grafo rodaram NESTE
    turno. Tornam "chamada de tools / escalada / handoff" auditavel no corpus e na evals-notas.html.
    Em passos de ATO (sem invoke) so `pix_status` e o estado fazem sentido."""

    indice: int
    acao_mensagem: str | None
    acao_ato: str | None
    bolha_ia: str | None
    estado_atendimento: str | None
    ia_pausada: bool | None
    pix_status: str | None = None
    tools_chamadas: list[str] = field(default_factory=list)
    escalou: bool | None = None
    nodes_visitados: list[str] = field(default_factory=list)
    # snapshot que o agente extraiu no turno (payload do registrar_extracao): horario/duracao/tipo/
    # valor/sinais. Torna reservas e escaladas AUTO-EXPLICAVEIS no corpus (ex.: um horario vago
    # virando horario_desejado e disparando a reserva previa -> reagendamento). None se o turno nao
    # chamou registrar_extracao.
    extracao: dict[str, Any] | None = None
    # --- observabilidade de DIAGNOSTICO (C5a do flywheel; nao usada pela rotulagem) ---------------
    # O system montado pelo prepare_context (prefixo tools+system+janela) que a IA "viu" neste turno:
    # diagnostico de POR QUE decidiu (cardapio/contexto dinamico/janela). None se ausente.
    prompt_montado: str | None = None
    # Raciocinio (blocos thinking) do turno. Quase sempre None no P0 (thinking=disabled); capturado
    # de graca caso liguem adaptive. Util p/ root-cause quando presente.
    thinking: str | None = None
    # I/O das tools do turno: nome + args + resultado. Traz o MOTIVO da escalada (args de `escalar`)
    # -- o que o classificador E2E precisa p/ distinguir escalada legitima de espuria.
    tool_io: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Trajetoria:
    """O que a jornada produziu -- a sequencia de passos para o operador roteirizar a fixture."""

    passos: list[PassoJornada] = field(default_factory=list)

    def bolhas_da_ia(self) -> list[str]:
        """So as falas da IA, na ordem -- o `historico_visivel` que o cliente observa no proximo passo."""
        return [p.bolha_ia for p in self.passos if p.bolha_ia]


async def _aplicar_ato(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID, ato: str
) -> None:
    """Aplica um ato dual-control mutando o estado real (atos.py). Espelha os gatilhos de producao."""
    if ato == "enviar_pix_valido":
        await _atos.enviar_pix(conn, atendimento_id, valido=True)
    elif ato == "enviar_pix_duvidoso":
        await _atos.enviar_pix(conn, atendimento_id, valido=False)
    elif ato == "enviar_foto_portaria":
        await _atos.enviar_foto_portaria(conn, atendimento_id)
    elif ato == "enviar_aviso_saida":
        await _atos.enviar_aviso_saida(conn, atendimento_id)
    elif ato == "ficar_em_silencio":
        _atos.ficar_em_silencio()  # no-op: deixa o timeout decidir
    elif ato == "modelo_fecha_card":
        await _atos.modelo_fecha_card(conn, atendimento_id)  # 3o ator: a modelo fecha o card
    elif ato == "lembrete_cobra_e_fecha":
        # Lembrete de fechamento (F4.4): o cron cobra proativamente o valor e a modelo fecha respondendo.
        await _atos.lembrete_cobra_valor_e_fecha(conn, atendimento_id)
    elif ato == "cliente_some_timeout":
        await _atos.cliente_some_timeout(
            conn, atendimento_id
        )  # ramo "nao volta": timeout -> Perdido
    else:
        raise ValueError(f"ato desconhecido: {ato!r}")


class _RedisStub:
    """Stub de ArqRedis p/ a jornada: o agente toca o redis em alguns pontos (a tool `escalar`
    enfileira `enviar_card`; o intercept_disclosure conta reincidencia com set/incr/expire). Com
    redis=None tudo isso quebraria; aqui cada metodo vira coroutine no-op. So o estado de DB
    (escalada + pausa da IA) importa para a trajetoria -- o ENVIO (Evolution/card) e a contagem de
    reincidencia (rate-limit cross-turno) nao ocorrem no sim: aceitavel p/ gerar conversas, so nao
    exercita a escalada-por-reincidencia (que precisa de redis real).

    `__getattr__` IGNORA dunders (`__pydantic_serializer__` etc.): interceptar dunders fazia o
    Pydantic usar o no-op como serializer e quebrava o model_dump do input das tools (a
    serializacao do context toca o redis). Levantar AttributeError nos dunders devolve o
    comportamento padrao. (runner.py usa redis=None porque as fixtures escalam pelo caminho
    deterministico abrir_handoff, nunca pela tool escalar do LLM -- que a jornada exercita.)"""

    def __getattr__(self, nome: str) -> Any:
        if nome.startswith("__"):
            raise AttributeError(nome)

        async def _noop(*_a: Any, **_k: Any) -> None:
            return None

        return _noop


def _tool_use_ids(msg: Any) -> set[str]:
    """IDs dos tool_calls de uma AIMessage (duck-typed): de `.tool_calls` e dos blocos `tool_use`
    do content. Espelha coordenador._tool_use_ids sem depender de imports de langchain."""
    ids = {tc.get("id") for tc in (getattr(msg, "tool_calls", None) or []) if tc.get("id")}
    conteudo = getattr(msg, "content", None)
    if isinstance(conteudo, list):
        ids |= {
            b.get("id")
            for b in conteudo
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
        }
    return ids


def _extrair_fala_do_turno(messages: list[Any]) -> str:
    """Fala que iria ao cliente NESTE turno: agrega o texto das AIMessages APOS o ultimo
    HumanMessage. Captura tanto a resposta do LLM (multi-bolha) quanto a negacao CANNED do
    intercept_disclosure -- que vem SEM usage_metadata e seria descartada por
    workers.coordenador._extrair_texto_do_turno (que filtra por usage_metadata p/ ignorar
    historicas). Aqui o criterio e POSICIONAL: a fala nova (LLM ou canned) vem depois da msg atual
    do cliente; as AIMessages historicas re-injetadas pelo prepare_context vem ANTES dela. Duck-typing
    (`.type`/`.content`) p/ nao depender de imports de langchain.

    Espelha o coordenador (prod): descarta o texto da AIMessage cujo tool_call resultou em ToolMessage
    "ERRO:" (rascunho superado pela retentativa de tool-com-erro recuperavel) -- senao o jsonl do sim
    mostraria a fala duplicada que o cliente real NAO veria (bug externo_pix, 2026-06-03)."""
    ult_human = -1
    for i, m in enumerate(messages):
        if getattr(m, "type", None) == "human":
            ult_human = i
    janela = messages[ult_human + 1 :]
    ids_com_erro = {
        getattr(m, "tool_call_id", None)
        for m in janela
        if getattr(m, "type", None) == "tool"
        and str(getattr(m, "content", "")).startswith("ERRO:")
        and getattr(m, "tool_call_id", None)
    }
    partes: list[str] = []
    for m in janela:
        if getattr(m, "type", None) != "ai":
            continue
        if ids_com_erro and (_tool_use_ids(m) & ids_com_erro):
            continue  # rascunho superado por retentativa de tool-com-erro recuperavel
        conteudo = getattr(m, "content", None)
        if isinstance(conteudo, str):
            if conteudo.strip():
                partes.append(conteudo)
        elif isinstance(conteudo, list):
            for bloco in conteudo:
                if (
                    isinstance(bloco, dict)
                    and bloco.get("type") == "text"
                    and str(bloco.get("text", "")).strip()
                ):
                    partes.append(bloco["text"])
    return "\n\n".join(partes)


def _extrair_extracao_do_turno(messages: list[Any]) -> dict[str, Any] | None:
    """Payload do ULTIMO `registrar_extracao` chamado NESTE turno (apos a ultima HumanMessage) -- o
    snapshot que o agente extraiu (horario_desejado/duracao/tipo/valor/sinais). Torna a reserva
    previa e a escala de reagendamento auto-explicaveis no corpus: um horario VAGO ("depois das
    21h") que vira horario_desejado e dispara a reserva fica visivel ao rotulador. Duck-typing
    sobre `tool_calls` (sem depender de imports de langchain); None se o turno nao chamou a tool."""
    ult_human = -1
    for i, m in enumerate(messages):
        if getattr(m, "type", None) == "human":
            ult_human = i
    payload: dict[str, Any] | None = None
    for m in messages[ult_human + 1 :]:
        for tc in getattr(m, "tool_calls", None) or []:
            if tc.get("name") == "registrar_extracao":
                args = tc.get("args") or {}
                bruto = args.get("payload", args)
                if isinstance(bruto, dict):
                    payload = bruto  # ultimo vence (1 registrar_extracao por turno na pratica)
    return payload


def _texto_de_conteudo(conteudo: Any) -> str:
    """Texto plano de um `content` do langchain (str OU lista de blocos {type:text,...})."""
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "\n".join(
            str(b.get("text", ""))
            for b in conteudo
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _extrair_prompt_montado(messages: list[Any]) -> str | None:
    """O SystemMessage montado pelo prepare_context (prefixo tools+system+janela) que a IA "viu"
    neste turno -- diagnostico de POR QUE decidiu (cardapio/contexto dinamico/janela). Pega o
    PRIMEIRO system da janela; None se ausente. Duck-typing (`.type`/`.content`)."""
    for m in messages:
        if getattr(m, "type", None) == "system":
            return _texto_de_conteudo(getattr(m, "content", None)) or None
    return None


def _extrair_thinking_do_turno(messages: list[Any]) -> str | None:
    """Blocos de raciocinio (type='thinking') das AIMessages APOS o ultimo HumanMessage. Quase sempre
    None no P0 (thinking desabilitado); capturado de graca caso liguem adaptive. Duck-typing."""
    ult_human = -1
    for i, m in enumerate(messages):
        if getattr(m, "type", None) == "human":
            ult_human = i
    partes: list[str] = []
    for m in messages[ult_human + 1 :]:
        if getattr(m, "type", None) != "ai":
            continue
        conteudo = getattr(m, "content", None)
        if isinstance(conteudo, list):
            for bloco in conteudo:
                if isinstance(bloco, dict) and bloco.get("type") == "thinking":
                    txt = str(bloco.get("thinking") or bloco.get("text") or "")
                    if txt.strip():
                        partes.append(txt)
    return "\n".join(partes) or None


def _extrair_tool_io_do_turno(messages: list[Any]) -> list[dict[str, Any]]:
    """I/O das tools chamadas NESTE turno (apos o ultimo HumanMessage): nome + args (do tool_call) +
    resultado (do ToolMessage casado por id). Traz o MOTIVO da escalada (args de `escalar`) --
    essencial p/ o classificador distinguir escalada legitima de espuria. Duck-typing."""
    ult_human = -1
    for i, m in enumerate(messages):
        if getattr(m, "type", None) == "human":
            ult_human = i
    janela = messages[ult_human + 1 :]
    resultados: dict[str, str] = {}
    for m in janela:
        if getattr(m, "type", None) == "tool":
            tcid = getattr(m, "tool_call_id", None)
            if tcid:
                resultados[tcid] = _texto_de_conteudo(getattr(m, "content", None))
    io: list[dict[str, Any]] = []
    for m in janela:
        for tc in getattr(m, "tool_calls", None) or []:
            io.append(
                {
                    "tool": tc.get("name"),
                    "args": tc.get("args") or {},
                    "resultado": resultados.get(tc.get("id", "")),
                }
            )
    return io


async def _inserir_msg(
    conn: AsyncConnection[dict[str, Any]],
    conversa_id: UUID,
    direcao: str,
    texto: str,
    ordem: int,
) -> None:
    """Insere uma mensagem com id time-ordered (uuidv7) e created_at CRESCENTE por `ordem`.

    Diferente de `runner._inserir_mensagem` (uuid4 + created_at=now()): numa unica transacao now()
    e constante (transaction_timestamp), entao varias mensagens empatariam em created_at e a janela
    do prepare_context (ORDER BY created_at, id) embaralharia. Aqui o created_at cresce com `ordem`
    e o id e uuidv7 -- a janela sai na ordem cronologica real da conversa (pre-req p/ a IA "ver" o
    que ja disse e p/ o cliente progredir em vez de repetir a abertura)."""
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (barravips.uuidv7(), %s, %s, 'texto', %s, %s, now() + (%s * interval '1 second'))
        """,
        (conversa_id, direcao, texto, f"sim-{uuid4().hex}", ordem),
    )


async def jornada(
    conn: AsyncConnection[dict[str, Any]],
    fixture_seed: dict[str, Any],
    cliente: ClienteLike,
    decidir_ato: Any | None = None,
    *,
    max_turnos: int = 8,
    apos_seed: Any | None = None,
    fechar_card: bool = False,
    cobrar_e_fechar: bool = False,
    timeout_sumiu: bool = False,
) -> Trajetoria:
    """Roda a jornada dual-control fechada (needs_db + needs_anthropic_api). Coleta a trajetoria.

    `fixture_seed` so carrega `estado_inicial` (entidades) -- NUNCA expectativas (o cliente nao as
    ve). Reusa `runner._seed_entidades` para criar modelo/cliente/conversa/atendimento e
    `runner._inserir_mensagem` + grafo para rodar cada turno de texto. `decidir_ato(passo, estado)`
    e um hook opcional (roteiro da persona) que, dado o passo/estado, devolve um nome de ato a
    aplicar em vez de pedir texto ao cliente; default None = sempre texto.

    `apos_seed(conn, modelo_id, atendimento_id, cliente_id, conversa_id)` e um hook async opcional
    rodado logo apos `_seed_entidades` e ANTES do 1o turno -- usado para popular o cardapio/agenda
    da modelo recem-seedada (ver sim/seed_cardapio.py), ja que `_seed_entidades` cria modelo minima
    (sem programas, a IA nao teria preco para cotar). default None = nao mexe no seed.

    `fechar_card=True` (F4.2) aplica o fecho da venda APOS o loop: a conversa termina em
    `Em_execucao` (a foto de portaria pausou a IA e encerrou o loop) e entao a MODELO responde o card
    com o Valor final (`modelo_fecha_card` -> Fechado). E fora-de-banda (3o ator, nao um turno da IA);
    so dispara se a jornada de fato chegou em `Em_execucao`. default False = morre em Em_execucao.

    `cobrar_e_fechar=True` (F4.4) aplica o fecho pela COBRANCA PROATIVA APOS o loop: a conversa termina
    em `Em_execucao` (foto de portaria) e entao o Lembrete de fechamento cobra o Valor final -- o cron
    `cobrar_valor_final` manda o card no grupo de Coordenacao e a modelo responde com o valor -> Fechado
    (`lembrete_cobra_e_fecha`). Caminho-irmao do `fechar_card`: la a modelo fecha por impulso, aqui em
    resposta a cobranca do sistema. So dispara se a jornada chegou em `Em_execucao`. default False.

    `timeout_sumiu=True` (F4.3) aplica o ramo "NAO VOLTA" APOS o loop: o cliente avisou que saiu e
    SUMIU (silencio, sem foto de portaria), entao o loop terminou em `Aguardando_confirmacao`; o ato
    `cliente_some_timeout` envelhece o aviso e dispara o cron de prod (`aplicar_timeout_interno`) ->
    `Perdido(sumiu)`. Tambem fora-de-banda (timeout, nao um turno da IA); so dispara se a jornada de
    fato parou em `Aguardando_confirmacao`. default False = nao aplica o timeout.

    O caller envolve isto em transacao + ROLLBACK (como `runner.rodar`). Promova qualquer falha
    observada na trajetoria a uma fixture de `scripted_5/`.
    """
    runner = _carregar_runner()
    # metadata_trace_turno agrupa os traces do LangSmith-sim por atendimento (thread OTel). Import
    # LAZY: mantém loop.py importável em testes puros (test_obs_diagnostico) sem arrastar langsmith.
    from barra.core.tracing import metadata_trace_turno

    grafo = runner.build_graph()
    modelo_id, atendimento_id, _cliente_id, conversa_id = await runner._seed_entidades(
        conn, fixture_seed
    )
    if apos_seed is not None:
        await apos_seed(conn, modelo_id, atendimento_id, _cliente_id, conversa_id)
    handler = runner.NodesVisitedHandler()
    trajetoria = Trajetoria()
    ordem = 0  # contador monotonico de mensagens (created_at crescente -> janela em ordem)

    for indice in range(max_turnos):
        estado_atual = await _ler_estado(conn, atendimento_id)
        ato = decidir_ato(indice, estado_atual) if decidir_ato else None
        if ato:
            await _aplicar_ato(conn, atendimento_id, ato)
            pos = await _ler_estado(conn, atendimento_id)
            trajetoria.passos.append(
                PassoJornada(
                    indice=indice,
                    acao_mensagem=None,
                    acao_ato=ato,
                    bolha_ia=None,
                    estado_atendimento=pos["estado"],
                    ia_pausada=pos["ia_pausada"],
                    pix_status=pos["pix_status"],
                )
            )
            if pos["ia_pausada"]:
                break  # IA pausada (handoff/atendimento): a jornada conversacional terminou
            continue

        acao: AcaoCliente = await cliente.decidir(trajetoria.bolhas_da_ia())
        await _inserir_msg(conn, conversa_id, "cliente", acao.mensagem or "", ordem)
        ordem += 1
        nodes_antes = set(handler.nos)  # handler acumula entre turnos -> delta = nos DESTE turno
        resultado = await grafo.ainvoke(
            {"messages": []},
            config={
                "recursion_limit": 18,
                "callbacks": [handler],
                # agrupa o trace por modelo/atendimento no LangSmith-sim (inócuo se tracing off).
                **metadata_trace_turno(str(modelo_id), str(atendimento_id)),
            },
            context=runner.ContextAgente(
                db_pool=runner._PoolDeUmaConexao(conn),
                redis=_RedisStub(),  # escalar enfileira card (no-op no sim); runner e Any (path import)
                modelo_id=str(modelo_id),
                atendimento_id=str(atendimento_id),
                cliente_id=str(_cliente_id),
                turno_id=str(runner.uuid4()),
                # Liga BP_MODELO + BP_JANELA (= producao). Ao contrario do runner.py (1 turno por
                # fixture, IDs novos -> esses blocos seriam so-write, por isso ele passa False),
                # a jornada e MULTI-TURNO com IDs ESTAVEIS: modelo/conversa seedadas 1x e janela
                # append-only (<20 msgs). Entao o cardapio (BP_MODELO) e o historico crescente
                # (BP_JANELA) sao LIDOS nos turnos 2..N em vez de reenviados a preco cheio -- corta
                # o grosso do custo da geracao, que se concentra nos turnos tardios das conversas longas.
                cache_modelo_e_janela=True,
            ),
        )
        captura = await runner._capturar(conn, atendimento_id, resultado)
        # Bolha = fala nova do turno (ver _extrair_fala_do_turno): agrega o texto das AIMessages
        # apos a msg atual do cliente -- captura LLM (multi-bolha) E a negacao canned do
        # intercept_disclosure, ignora historicas e a passagem vazia pos-tool do ReAct.
        bolha = _extrair_fala_do_turno(resultado["messages"])
        if bolha:
            # Grava a fala da IA no banco p/ a janela do proximo turno inclui-la (a IA "ve" o que
            # disse; o cliente progride). Em producao quem grava e o worker enviar_turno.
            await _inserir_msg(conn, conversa_id, "ia", bolha, ordem)
            ordem += 1
        trajetoria.passos.append(
            PassoJornada(
                indice=indice,
                acao_mensagem=acao.mensagem,
                acao_ato=None,
                bolha_ia=bolha,
                estado_atendimento=captura.estado_atendimento,
                ia_pausada=captura.ia_pausada,
                pix_status=captura.pix_status,
                tools_chamadas=sorted(captura.tools_chamadas),
                escalou=captura.escalou,
                nodes_visitados=sorted(handler.nos - nodes_antes),
                extracao=_extrair_extracao_do_turno(resultado["messages"]),
                prompt_montado=_extrair_prompt_montado(resultado["messages"]),
                thinking=_extrair_thinking_do_turno(resultado["messages"]),
                tool_io=_extrair_tool_io_do_turno(resultado["messages"]),
            )
        )
        if captura.ia_pausada:
            break

    # Fecho da venda fora-de-banda (F4.2, 3o ator): a conversa terminou em `Em_execucao` (a foto de
    # portaria pausou a IA e encerrou o loop); agora a modelo responde o card com o Valor final ->
    # `Fechado`. Espelha producao -- o registro de resultado NAO e um turno da IA. So fecha se de
    # fato chegou em `Em_execucao` (jornada interna completa); senao a venda nao se concretizou.
    if fechar_card:
        pos = await _ler_estado(conn, atendimento_id)
        if pos["estado"] == "Em_execucao":
            await _aplicar_ato(conn, atendimento_id, "modelo_fecha_card")
            final = await _ler_estado(conn, atendimento_id)
            trajetoria.passos.append(
                PassoJornada(
                    indice=len(trajetoria.passos),
                    acao_mensagem=None,
                    acao_ato="modelo_fecha_card",
                    bolha_ia=None,
                    estado_atendimento=final["estado"],
                    ia_pausada=final["ia_pausada"],
                    pix_status=final["pix_status"],
                )
            )

    # Cobranca proativa fora-de-banda (F4.4, Lembrete de fechamento): a conversa terminou em
    # `Em_execucao` (a foto de portaria pausou a IA); agora o cron `cobrar_valor_final` cobra o Valor
    # final mandando o card no grupo de Coordenacao e a modelo responde com o valor -> `Fechado`.
    # Caminho-irmao do `fechar_card` (la a modelo fecha por impulso; aqui em resposta a cobranca). So
    # dispara se de fato chegou em `Em_execucao`; senao a venda nao se concretizou. Mutuamente
    # exclusivo com `fechar_card` na pratica (se ambos, o fecho ja levou a Fechado e o guard pula).
    if cobrar_e_fechar:
        pos = await _ler_estado(conn, atendimento_id)
        if pos["estado"] == "Em_execucao":
            await _aplicar_ato(conn, atendimento_id, "lembrete_cobra_e_fecha")
            final = await _ler_estado(conn, atendimento_id)
            trajetoria.passos.append(
                PassoJornada(
                    indice=len(trajetoria.passos),
                    acao_mensagem=None,
                    acao_ato="lembrete_cobra_e_fecha",
                    bolha_ia=None,
                    estado_atendimento=final["estado"],
                    ia_pausada=final["ia_pausada"],
                    pix_status=final["pix_status"],
                )
            )

    # Ramo "nao volta" fora-de-banda (F4.3, timeout): o cliente avisou que saiu e SUMIU, entao o loop
    # terminou em `Aguardando_confirmacao`; agora o timeout determinista de 45 min o marca
    # `Perdido(sumiu)`. Espelha producao -- a perda por silencio NAO e um turno da IA. So dispara se de
    # fato parou em `Aguardando_confirmacao` (avisou e nao chegou); senao a jornada teve outro desfecho.
    if timeout_sumiu:
        pos = await _ler_estado(conn, atendimento_id)
        if pos["estado"] == "Aguardando_confirmacao":
            await _aplicar_ato(conn, atendimento_id, "cliente_some_timeout")
            final = await _ler_estado(conn, atendimento_id)
            trajetoria.passos.append(
                PassoJornada(
                    indice=len(trajetoria.passos),
                    acao_mensagem=None,
                    acao_ato="cliente_some_timeout",
                    bolha_ia=None,
                    estado_atendimento=final["estado"],
                    ia_pausada=final["ia_pausada"],
                    pix_status=final["pix_status"],
                )
            )

    return trajetoria


async def _ler_estado(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    """Le o estado observavel do atendimento (estado + ia_pausada + pix_status) -- o que constrange
    os atos e alimenta a observabilidade do passo de ato."""
    res = await conn.execute(
        "SELECT estado, ia_pausada, pix_status FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row
