"""Harness compartilhado: seed parametrizado + trajetoria + execucao de um turno do grafo.

Reusado pela Camada 1 (gate de seguranca, pytest `@needs_key @needs_db`) e pela Camada 2
(shadow, script de geracao). A invariante e a mesma de `test_fixtures_leitura_decisao.py`:
DB real via `TEST_DATABASE_URL`, pool de UMA conexao (prepare_context e as tools leem a MESMA
transacao), ROLLBACK sempre no teardown — nada commita.

Generaliza os `_seed_*` hardcoded daquele teste (08 §2): estado/tipo/pix parametrizados,
DUAS modelos (par A e par B) com o MESMO cliente para o gate de isolamento (SEC-01), e
observacoes_internas como portador do canary do par B (dado por-par que a IA da modelo A
nunca pode carregar).

NAO chama a API da Anthropic por si so: quem dispara o `ainvoke` (e o gasto de credito, §0) e
o caller. Este modulo so prepara o cenario, executa um turno e coleta o resultado.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from psycopg import AsyncConnection

from barra.agente._texto_turno import extrair_texto_do_turno
from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.core.tracing import langfuse_handler, metadata_trace_turno
from barra.settings import get_settings

# --- fake redis (reincidencia de seguranca + enqueue de cards das tools) ---------------------


class FakeRedis:
    """Redis em memoria: cobre o que o caminho de seguranca e as tools de escrita tocam offline.

    `_contabilizar_reincidencia` usa set(nx)/incr/expire/delete; as tools usam enqueue_job (no-op
    aqui — nada e despachado ao Evolution offline, §0). Sem persistencia entre turnos (cada gate e
    um cenario isolado).
    """

    def __init__(self) -> None:
        self._d: dict[str, Any] = {}

    async def set(self, k: str, v: Any = "1", *, ex: Any = None, nx: bool = False, **_: Any) -> Any:
        if nx and k in self._d:
            return None
        self._d[k] = v
        return True

    async def get(self, k: str, *_a: Any, **_k: Any) -> Any:
        return self._d.get(k)

    async def delete(self, *ks: str, **_k: Any) -> None:
        for k in ks:
            self._d.pop(k, None)

    async def incr(self, k: str, *_a: Any, **_k: Any) -> int:
        self._d[k] = int(self._d.get(k, 0)) + 1
        return int(self._d[k])

    async def expire(self, k: str, s: int, *_a: Any, **_k: Any) -> bool:
        return True

    async def enqueue_job(self, *_a: Any, **_k: Any) -> None:
        return None


# --- pool de UMA conexao (espelha test_fixtures_leitura_decisao._PoolDeUmaConexao) -----------


class PoolDeUmaConexao:
    """prepare_context e as tools leem a MESMA transacao (sem commit). ROLLBACK no caller.

    `connection()` e um @asynccontextmanager (igual o pool real e o _PoolDeUmaConexao do teste):
    `core.db.conexao` faz `async with pool.connection() as conn`.
    """

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


# --- trajetoria: quais nos do grafo foram visitados (EVAL-08) --------------------------------


class NodesVisitedHandler(BaseCallbackHandler):
    """Registra os nos do LangGraph visitados no turno, via `metadata['langgraph_node']`.

    "grade what the agent produced, not the path it took" (Anthropic): a trajetoria so e gate
    quando a EXECUCAO e a falha — ex.: o caminho canned de disclosure NAO pode visitar `tools`
    nem `llm`. Sem checkpointer, cada turno emite os eventos de chain dos nos percorridos.
    """

    def __init__(self) -> None:
        self.nodes: list[str] = []
        # Prompt(s) montado(s) e enviado(s) ao modelo neste turno. Auditar o canary AQUI (canal
        # interno), nao so na resposta: AgentLeak mostra que so o output cega ~42% do vazamento.
        # Se a query de isolamento furar (WHERE sem modelo_id), o dado do par B entra no prompt
        # mesmo que o LLM nao o repita na bolha — e o canary aparece aqui.
        self.prompt_modelo: list[str] = []

    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, **kwargs: Any) -> None:
        node = (kwargs.get("metadata") or {}).get("langgraph_node")
        if node and (not self.nodes or self.nodes[-1] != node):
            self.nodes.append(str(node))

    def on_chat_model_start(
        self, serialized: dict[str, Any] | None, messages: Any, **kwargs: Any
    ) -> None:
        # `messages` = list[list[BaseMessage]] enviada ao ChatAnthropic (prompt completo do turno).
        for grupo in messages or []:
            for m in grupo or []:
                conteudo = getattr(m, "content", m)
                self.prompt_modelo.append(conteudo if isinstance(conteudo, str) else repr(conteudo))


# --- resultado de um turno -------------------------------------------------------------------


@dataclass
class Metricas:
    """Observabilidade por turno (tokens/custo/cache/latencia) — alimenta o relatorio do gate."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    custo_brl: float = 0.0
    latencia_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def write_rate(self) -> float:
        """cache_write / (cache_read + cache_write) — tripwire de invalidacao de prefixo (08 §4.4)."""
        base = self.cache_read + self.cache_write
        return self.cache_write / base if base else 0.0

    def como_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "total_tokens": self.total_tokens,
            "custo_brl": round(self.custo_brl, 6),
            "latencia_s": round(self.latencia_s, 3),
            "write_rate": round(self.write_rate, 3),
        }


@dataclass
class ResultadoTurno:
    """O que um turno do grafo produziu — insumo puro dos graders de `checks.py`."""

    texto: str  # texto agregado ao cliente (mesmo `extrair_texto_do_turno` do output_guard)
    tool_calls: list[str]  # nomes das tools chamadas no turno
    tool_args: list[dict[str, Any]]  # args das tools (alvo do scan de canary)
    nodes: list[str]  # nos visitados (trajetoria)
    prompt_modelo: list[str]  # prompt montado enviado ao LLM (canal interno p/ scan de canary)
    mensagens: list[BaseMessage]  # mensagens cruas do turno (debug)
    estado_final: dict[str, Any]  # {estado, pix_status, ia_pausada} pos-turno (state_check)
    metricas: Metricas = field(default_factory=Metricas)  # observabilidade do turno
    trace_id: str | None = None  # trace Langfuse do turno (so com escopar_trace); ancora o score


def _metricas_tokens(mensagens: list[BaseMessage], cotacao_usd_brl: float) -> Metricas:
    """Soma tokens/custo das AIMessages GERADAS no turno (usage_metadata != None). Reusa a mesma
    extracao do no llm (`_instrumentar_tokens`) e o custo de `_custo.calcular_custo_brl` — fonte
    unica, byte-fiel ao que prod contabiliza no Prometheus."""
    from barra.agente._custo import calcular_custo_brl

    m = Metricas()
    for msg in mensagens:
        um = getattr(msg, "usage_metadata", None)
        if not um:
            continue
        det = um.get("input_token_details") or {}
        m.input_tokens += int(um.get("input_tokens", 0))
        m.output_tokens += int(um.get("output_tokens", 0))
        m.cache_read += int(det.get("cache_read", 0) or 0)
        m.cache_write += int(
            (det.get("ephemeral_5m_input_tokens", 0) or 0)
            + (det.get("ephemeral_1h_input_tokens", 0) or 0)
        )
        m.custo_brl += calcular_custo_brl(um, cotacao_usd_brl)
    return m


def _coletar_tools(mensagens: list[BaseMessage]) -> tuple[list[str], list[dict[str, Any]]]:
    nomes: list[str] = []
    args: list[dict[str, Any]] = []
    for m in mensagens:
        for tc in getattr(m, "tool_calls", None) or []:
            nomes.append(str(tc.get("name")))
            args.append(dict(tc.get("args") or {}))
    return nomes, args


async def estado_pos_turno(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    """Le {estado, pix_status, ia_pausada} do atendimento DEPOIS do turno (state_check)."""
    res = await conn.execute(
        "SELECT estado, pix_status, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    linha = await res.fetchone()
    return dict(linha) if linha else {}


# --- seed parametrizado ----------------------------------------------------------------------


@dataclass
class Cenario:
    """Cenario seedado de um turno. IDs sao preenchidos pelo `seedar`."""

    cliente_id: UUID
    modelo_id: UUID
    conversa_id: UUID
    atendimento_id: UUID
    # par B (isolamento): segunda modelo, MESMO cliente. None fora do gate de isolamento.
    modelo_b_id: UUID | None = None
    canary: str | None = None  # token do par B que NAO pode aparecer em A
    programas: list[dict[str, Any]] = field(default_factory=list)


async def _seed_modelo(conn: AsyncConnection[dict[str, Any]], spec: dict[str, Any]) -> UUID:
    modelo_id = uuid4()
    tipos = spec.get("tipo_atendimento_aceito") or ["interno", "externo"]
    await conn.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             localizacao_operacional, endereco_formatado)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            spec.get("nome", "Modelo Teste"),
            spec.get("idade", 25),
            f"test-wpp-{uuid4().hex}",
            spec.get("valor_padrao", 500),
            tipos,
            spec.get("localizacao_operacional"),
            spec.get("endereco_formatado"),
        ),
    )
    for prog in spec.get("programas") or []:
        await _seed_programa(conn, modelo_id, prog)
    return modelo_id


async def _seed_programa(
    conn: AsyncConnection[dict[str, Any]], modelo_id: UUID, prog: dict[str, Any]
) -> None:
    """Vincula um programa x duracao ao modelo com preco. Schema real (verificado no prod):
    `modelo_programas` tem PK composta (modelo_id, programa_id, duracao_id) — SEM coluna `id`;
    `duracoes.ordem` e NOT NULL. Faz get-or-create de programa/duracao por NOME (reusa o catalogo
    global existente, evita violar unique e duplicar) antes de inserir o vinculo."""
    prog_id = await _get_or_create(
        conn, "programas", prog["nome"], colunas={"categoria": prog.get("categoria")}
    )
    dur_id = await _get_or_create(
        conn,
        "duracoes",
        prog.get("duracao_nome", "1 hora"),
        colunas={"ordem": prog.get("ordem", 999), "horas": prog.get("horas", 1)},
    )
    await conn.execute(
        "INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (modelo_id, prog_id, dur_id, prog["preco"]),
    )


async def _get_or_create(
    conn: AsyncConnection[dict[str, Any]],
    tabela: str,
    nome: str,
    *,
    colunas: dict[str, Any],
) -> UUID:
    """Devolve o id de uma linha de catalogo global por `nome`; cria se nao existir (uuid novo).

    Reusa os programas/duracoes ja seedados no prod (catalogo curado) — o teste e efemero (ROLLBACK),
    entao nao polui; e nao dispara unique-violation ao reinserir um nome existente.
    """
    res = await conn.execute(f"SELECT id FROM barravips.{tabela} WHERE nome = %s LIMIT 1", (nome,))
    linha = await res.fetchone()
    if linha:
        return UUID(str(linha["id"]))
    novo = uuid4()
    cols = ", ".join(["id", "nome", *colunas])
    marks = ", ".join(["%s"] * (2 + len(colunas)))
    await conn.execute(
        f"INSERT INTO barravips.{tabela} ({cols}) VALUES ({marks})",
        (novo, nome, *colunas.values()),
    )
    return novo


async def _seed_cliente(conn: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await conn.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", None),
    )
    return cliente_id


async def _seed_conversa(
    conn: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    recorrente: bool,
    observacoes_internas: str | None,
) -> UUID:
    conversa_id = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.conversas
            (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            conversa_id,
            cliente_id,
            modelo_id,
            f"test-chat-{uuid4().hex}",
            recorrente,
            observacoes_internas,
        ),
    )
    return conversa_id


async def _seed_atendimento(
    conn: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    numero_curto: int,
    atendimento: dict[str, Any],
) -> UUID:
    """Seed parametrizado por `atendimento` (estado/tipo/pix/ia_pausada da fixture)."""
    atendimento_id = uuid4()
    estado = atendimento.get("estado", "Triagem")
    ia_pausada = bool(atendimento.get("ia_pausada", False))
    await conn.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado,
             tipo_atendimento, pix_status, ia_pausada, ia_pausada_motivo, cotacao_enviada_em)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum,
                %s::barravips.pix_status_enum, %s,
                %s::barravips.ia_pausada_motivo_enum,
                CASE WHEN %s THEN now() ELSE NULL END)
        """,
        (
            atendimento_id,
            numero_curto,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            atendimento.get("tipo_atendimento"),
            atendimento.get("pix_status", "nao_solicitado"),
            ia_pausada,
            atendimento.get("ia_pausada_motivo") if ia_pausada else None,
            bool(atendimento.get("cotacao_enviada", False)),
        ),
    )
    return atendimento_id


async def _inserir_mensagem(
    conn: AsyncConnection[dict[str, Any]],
    *,
    conversa_id: UUID,
    direcao: str,
    texto: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, %s, %s::barravips.direcao_mensagem_enum, 'texto', %s, %s)
        """,
        (uuid4(), conversa_id, direcao, texto, f"test-evo-{uuid4().hex}"),
    )


async def seedar(conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any]) -> Cenario:
    """Seed completo de uma fixture: par A (sempre) + par B opcional (isolamento) + historico.

    `fixture["cenario"]` = {modelo, atendimento, recorrente?, observacoes_internas?, par_b?, canary?}.
    `fixture["historico"]` = [{direcao, texto}] inserido antes do turno (mensagens passadas).
    `fixture["turno_cliente"]` e inserido por `rodar_turno`, nao aqui.
    """
    cen = fixture.get("cenario", {})
    cliente_id = await _seed_cliente(conn)
    modelo_id = await _seed_modelo(conn, cen.get("modelo", {}))
    conversa_id = await _seed_conversa(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        recorrente=bool(cen.get("recorrente", False)),
        observacoes_internas=cen.get("observacoes_internas"),
    )
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        numero_curto=1,
        atendimento=cen.get("atendimento", {}),
    )

    modelo_b_id: UUID | None = None
    par_b = cen.get("par_b")
    if par_b:
        # par B: MESMA pessoa (mesmo cliente_id) atendida por OUTRA modelo, com dado por-par
        # (observacoes_internas = canary). A IA da modelo A nunca pode carregar isso.
        modelo_b_id = await _seed_modelo(conn, par_b.get("modelo", {}))
        conversa_b = await _seed_conversa(
            conn,
            cliente_id=cliente_id,
            modelo_id=modelo_b_id,
            recorrente=bool(par_b.get("recorrente", False)),
            observacoes_internas=par_b.get("observacoes_internas"),
        )
        await _seed_atendimento(
            conn,
            cliente_id=cliente_id,
            modelo_id=modelo_b_id,
            conversa_id=conversa_b,
            numero_curto=1,
            atendimento=par_b.get("atendimento", {"estado": "Triagem"}),
        )
        # Mensagens do par B portando o canary: a janela de mensagens (WHERE cliente_id AND
        # modelo_id) e o canal PRINCIPAL de isolamento. Se a query furar (so cliente_id), estas
        # mensagens entram no prompt da modelo A e o canary aparece no scan de canais internos.
        for msg in par_b.get("historico", []):
            await _inserir_mensagem(
                conn,
                conversa_id=conversa_b,
                direcao=msg.get("direcao", "cliente"),
                texto=msg["texto"],
            )

    for msg in fixture.get("historico", []):
        await _inserir_mensagem(
            conn,
            conversa_id=conversa_id,
            direcao=msg.get("direcao", "cliente"),
            texto=msg["texto"],
        )

    return Cenario(
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        atendimento_id=atendimento_id,
        modelo_b_id=modelo_b_id,
        canary=cen.get("canary"),
        programas=cen.get("modelo", {}).get("programas", []),
    )


# --- execucao de um turno --------------------------------------------------------------------


async def rodar_turno(
    conn: AsyncConnection[dict[str, Any]],
    cen: Cenario,
    *,
    turno_cliente: str,
    graph: Any | None = None,
    trace_tag: str = "eval_gate",
    escopar_trace: bool = False,
) -> ResultadoTurno:
    """Insere a mensagem do cliente, roda UM `ainvoke` (gasta credito, §0) e coleta o resultado.

    `graph` reusavel entre turnos (build_graph() uma vez). `conn` e a MESMA do seed (transacao).
    `trace_tag` marca a origem do trace no Langfuse (gate vs e2e). `escopar_trace` embrulha o
    ainvoke num span com trace-id deterministico (padrao de prod, coordenador.py) e o devolve em
    `ResultadoTurno.trace_id` para ancorar o score online (`registrar_feedback_online`).
    """
    await _inserir_mensagem(
        conn, conversa_id=cen.conversa_id, direcao="cliente", texto=turno_cliente
    )
    if graph is None:
        graph = build_graph()
    handler = NodesVisitedHandler()
    ctx = ContextAgente(
        db_pool=PoolDeUmaConexao(conn),  # type: ignore[arg-type]
        redis=FakeRedis(),  # type: ignore[arg-type]
        modelo_id=str(cen.modelo_id),
        atendimento_id=str(cen.atendimento_id),
        cliente_id=str(cen.cliente_id),
        turno_id=str(uuid4()),
        cache_modelo_e_janela=False,  # turno isolado: BP_MODELO/JANELA seriam write puro
    )
    # Observabilidade: trace Langfuse (ADR 0019) quando habilitado (`habilitar_tracing`), escopado
    # por modelo/atendimento — o MESMO caminho de prod. Tags extras marcam que o trace e do gate.
    config: dict[str, Any] = {"recursion_limit": 18, "callbacks": [handler]}
    trace_id: str | None = None
    span_ctx: AbstractContextManager[Any] = nullcontext()
    lf = langfuse_handler()
    if lf is not None:
        config["callbacks"].append(lf)
        meta = metadata_trace_turno(
            str(cen.modelo_id), str(cen.atendimento_id), str(cen.cliente_id)
        )
        meta["metadata"]["langfuse_tags"] = [*meta["metadata"]["langfuse_tags"], trace_tag]
        config["metadata"] = meta["metadata"]
        config["tags"] = [*meta["tags"], trace_tag]
        if escopar_trace:
            # trace-id deterministico (seed=turno_id) + span explicito: o CallbackHandler pendura
            # o grafo nele e o mesmo id ancora o score online no /fim (padrao de coordenador.py).
            from langfuse import Langfuse, get_client

            trace_id = Langfuse.create_trace_id(seed=ctx.turno_id)
            span_ctx = get_client().start_as_current_observation(
                as_type="span", name="turno_e2e", trace_context={"trace_id": trace_id}
            )

    t0 = perf_counter()
    with span_ctx:
        estado = await graph.ainvoke({"messages": []}, config=config, context=ctx)
    latencia = perf_counter() - t0

    mensagens: list[BaseMessage] = estado["messages"]
    nomes, args = _coletar_tools(mensagens)
    metricas = _metricas_tokens(mensagens, get_settings().usd_brl_cotacao)
    metricas.latencia_s = latencia
    return ResultadoTurno(
        texto=extrair_texto_do_turno(mensagens),
        tool_calls=nomes,
        tool_args=args,
        nodes=handler.nodes,
        prompt_modelo=handler.prompt_modelo,
        mensagens=mensagens,
        estado_final=await estado_pos_turno(conn, cen.atendimento_id),
        metricas=metricas,
        trace_id=trace_id,
    )


def habilitar_tracing() -> bool:
    """Liga o trace Langfuse de prod (ADR 0019) para os turnos do gate. Idempotente; retorna se
    o handler ficou disponivel (precisa das envs LANGFUSE_* — senao no-op silencioso)."""
    from barra.core.tracing import setup_langfuse

    setup_langfuse(get_settings())
    return langfuse_handler() is not None
