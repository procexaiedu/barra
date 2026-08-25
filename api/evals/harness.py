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

import asyncio
import re
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from psycopg import AsyncConnection

from barra.agente._texto_turno import (
    desfecho_do_turno,
    extrair_texto_do_turno,
    mensagens_cliente_do_turno,
    raciocinio_do_turno,
    tags_do_turno,
)
from barra.agente._versao import regime_do_turno
from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.core.tracing import langfuse_handler, metadata_trace_turno, resumir_trace_turno
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

    O emprestimo e SERIALIZADO por um asyncio.Lock: o ToolNode executa tool calls do mesmo turno
    em paralelo (asyncio.gather) e duas `conn.transaction()` concorrentes na MESMA conexao
    estouram OutOfOrderTransactionNesting (visto no braco B do A/B de thinking, 10/08 — thinking
    emite multiplas tool calls por turno). Em prod o pool real da uma conexao por tool; aqui o
    lock reproduz o isolamento sem abrir 2a conexao (a transacao unica do ROLLBACK e sagrada).
    """

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        async with self._lock:
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


# Carimbos do State (pos-`ainvoke`) que o resultado do turno carrega para os graders. Sao a FONTE
# DA VERDADE do que o turno DECIDIU: mensagem nao serve, porque o output_guard tem o direito de
# reescrever as AIMessages do turno (`_zerar_turno`) e leva junto os `tool_calls` — o rig lia
# "turno sem extracao" em 26 turnos que registraram (loop-massa r3, achado 12a). Mesma licao que o
# lado do agente ja aprendeu em `agente/_texto_turno.extracao_do_turno`: carimbo, nao inferencia.
_CARIMBOS_DO_STATE = ("_extracao_registrada", "_mute_por_erro_de_tool")


def carimbos_do_estado(estado: dict[str, Any]) -> dict[str, Any]:
    """Subset de `_CARIMBOS_DO_STATE` presente no State devolvido pelo `ainvoke`.

    So as chaves PRESENTES: o veredito de `extracao_do_turno` e por presenca (carimbo `None`
    explicito = "o `extrair` decidiu que nada foi gravado"), entao inventar a chave aqui trocaria
    "nao passou pelo `extrair`" por "passou e nao gravou".
    """
    return {c: estado[c] for c in _CARIMBOS_DO_STATE if c in estado}


@dataclass
class ResultadoTurno:
    """O que um turno do grafo produziu — insumo puro dos graders de `checks.py`."""

    texto: str  # texto agregado ao cliente (mesmo `extrair_texto_do_turno` do output_guard)
    # Tools do turno, PARALELOS entre si (`zip(strict=True)` e invariante para quem le args por
    # nome). Rastro das AIMessages MESCLADO com `barravips.tool_calls` — ver `_mesclar_tools`: so
    # o banco sobrevive a regeneracao do output_guard, e so as mensagens tem as tools de leitura.
    tool_calls: list[str]  # nomes das tools chamadas no turno
    tool_args: list[dict[str, Any]]  # args das tools (alvo do scan de canary)
    nodes: list[str]  # nos visitados (trajetoria)
    prompt_modelo: list[str]  # prompt montado enviado ao LLM (canal interno p/ scan de canary)
    mensagens: list[BaseMessage]  # mensagens cruas do turno (debug)
    estado_final: dict[str, Any]  # {estado, pix_status, ia_pausada} pos-turno (state_check)
    metricas: Metricas = field(default_factory=Metricas)  # observabilidade do turno
    trace_id: str | None = None  # trace Langfuse do turno (so com escopar_trace); ancora o score
    estado_grafo: dict[str, Any] = field(
        default_factory=dict
    )  # carimbos (ver `carimbos_do_estado`)
    # `escaladas.observacao` da escalada que ESTE turno abriu, ou None. E o unico rastro das
    # escaladas que o COORDENADOR abre FORA do grafo (`escalar_por_exaustao`: modelo_indisponivel,
    # timeout_grafo, teto_turnos, ...): elas nao passam por tool nem tocam `messages`, entao a
    # regua de silencio as lia como "pausa externa" e cobrava a infra como conduta. So o caminho
    # fiel preenche (ver `harness_fiel.rodar_turno_auditado`); no `rodar_turno` cru nao ha
    # coordenador para abri-las.
    escalada_do_turno: str | None = None

    @property
    def extracao(self) -> dict[str, Any] | None:
        """O payload que a `registrar_extracao` GRAVOU no turno, ou None se nao gravou nada.

        Delega ao MESMO `extracao_do_turno` que o trace de prod usa: carimbo do State primeiro,
        varredura de `tool_calls` so na ausencia dele (State montado a mao, turno que nao passou
        pelo `extrair`). Todo consumidor do rig que quer "o que o turno leu" le AQUI, e nao
        `tool_calls`/`tool_args` — esses sao o rastro da CHAMADA (mesclado com o banco desde o
        fix do book, mas ainda a chamada, nao o payload que a extracao gravou no State).
        """
        from barra.agente._texto_turno import extracao_do_turno

        return extracao_do_turno({**self.estado_grafo, "messages": self.mensagens})

    @property
    def mute_deliberado(self) -> bool:
        """O turno saiu MUDO de proposito (`_mute_por_erro_de_tool`): a extracao errou no guard de
        dominio e a reoferta ja tinha sido gasta — silencio > reserva fantasma. Distingue o
        silencio DECIDIDO do turno mudo por acidente, que e violacao dura no veredito e2e."""
        return bool(self.estado_grafo.get("_mute_por_erro_de_tool"))


def _metricas_tokens(mensagens: list[BaseMessage], cotacao_usd_brl: float) -> Metricas:
    """Soma tokens/custo das AIMessages GERADAS no turno (usage_metadata != None). Reusa a mesma
    extracao do no llm (`_instrumentar_tokens`) e o custo de `_custo.calcular_custo_brl` — fonte
    unica, byte-fiel ao que prod contabiliza no Prometheus."""
    from barra.agente._custo import _modelo_da_mensagem, calcular_custo_brl

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
        # model_name por mensagem: sem isso cai no fallback Sonnet ($3/$15) e infla ~21x o input /
        # ~54x o output sobre o DeepSeek V4 Flash ($0,14/$0,28) que o agente ao vivo roda — mesma
        # tabela que `custo_chat_turno_brl` (coordenador) e `_instrumentar` (Prometheus) usam.
        m.custo_brl += calcular_custo_brl(um, cotacao_usd_brl, model_name=_modelo_da_mensagem(msg))
    return m


def _coletar_tools(mensagens: list[BaseMessage]) -> tuple[list[str], list[dict[str, Any]]]:
    """Rastro de tool das AIMessages — a INTENCAO que o LLM emitiu no turno.

    ⚠️ Nao e a verdade do que EXECUTOU. Quando o output_guard zera o turno e regenera, o
    `_zerar_turno` clona as AIMessages SEM `tool_calls` de proposito (a regeneracao nao pode
    reexecutar efeito colateral) — o rastro some das mensagens embora a tool tenha rodado. Quem
    quer "o que o turno FEZ" mescla com `_tools_do_banco` (ver `_mesclar_tools`); esta funcao
    sozinha so cobre as tools que nao gravam em `barravips.tool_calls` (as de leitura).
    """
    nomes: list[str] = []
    args: list[dict[str, Any]] = []
    for m in mensagens:
        for tc in getattr(m, "tool_calls", None) or []:
            nomes.append(str(tc.get("name")))
            args.append(dict(tc.get("args") or {}))
    return nomes, args


async def _tools_do_banco(
    conn: AsyncConnection[dict[str, Any]], turno_ids: list[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Tools de ESCRITA que o turno realmente executou, de `barravips.tool_calls`.

    Fonte de verdade do efeito colateral (`ferramentas/_idempotencia`): a linha so existe se o
    executor rodou, e o guard NAO a apaga ao regenerar — e por isso que o proprio output_guard le
    dali (`output_guard.py`, legenda do book) em vez de olhar as AIMessages.

    A ToolMessage tambem sobrevive ao `_zerar_turno` e e o que `e2e.avaliacao._tool_ok_no_turno`
    usa para a pergunta "rodou?"; aqui a fonte e o banco porque as reguas do book precisam dos
    ARGS (tipo/legenda de cada `enviar_midia`), que a ToolMessage nao carrega.

    Le na MESMA conexao/transacao do turno, antes do ROLLBACK do caller: nada aqui commita, e as
    linhas foram gravadas por savepoint na mesma conn (o pool do rig e de UMA conexao).
    `turno_ids` no plural porque o drain do coordenador pode rodar o grafo mais de uma vez sob o
    mesmo lock — o turno auditado e a soma das invocacoes (ver `harness_fiel.GraphAuditado`).
    """
    if not turno_ids:
        return [], []
    res = await conn.execute(
        """
        SELECT tool_name, payload
          FROM barravips.tool_calls
         WHERE turno_id = ANY(%s::uuid[])
         ORDER BY created_at, tool_name, call_idx
        """,
        (turno_ids,),
    )
    linhas = await res.fetchall()
    return [str(r["tool_name"]) for r in linhas], [dict(r["payload"] or {}) for r in linhas]


def _mesclar_tools(
    das_mensagens: tuple[list[str], list[dict[str, Any]]],
    do_banco: tuple[list[str], list[dict[str, Any]]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Une os dois rastros POR NOME DE TOOL, ficando com o lado que tem MAIS chamadas.

    Nenhum dos dois lados e superconjunto do outro:
    - tool de leitura nunca grava em `tool_calls` -> so as mensagens a tem;
    - turno regenerado pelo guard perde o rastro nas mensagens -> so o banco o tem.

    Contagem por nome (nao uniao de conjuntos) porque as reguas do book contam repeticoes
    (`enviar_midia` >= 2 = book; 1 = conta-gotas). Preferir o MAIOR lado nunca inventa chamada:
    o banco so tem linha de tool executada, e a mensagem so tem tool que o LLM pediu. Os `args`
    acompanham o lado escolhido para `tool_calls`/`tool_args` seguirem PARALELOS — invariante que
    `e2e.massa._midias_do_turno` consome com `zip(..., strict=True)`.
    """
    nomes_msg, args_msg = das_mensagens
    nomes_db, args_db = do_banco
    if not nomes_db:
        return list(nomes_msg), list(args_msg)
    c_msg, c_db = Counter(nomes_msg), Counter(nomes_db)
    # Empate -> lado das mensagens (preserva a ordem em que o LLM pediu, e os args crus da chamada).
    manda_o_banco = {nome for nome, n in c_db.items() if n > c_msg[nome]}
    nomes: list[str] = []
    args: list[dict[str, Any]] = []
    for nome, arg in zip(nomes_msg, args_msg, strict=True):
        if nome not in manda_o_banco:
            nomes.append(nome)
            args.append(arg)
    for nome, arg in zip(nomes_db, args_db, strict=True):
        if nome in manda_o_banco:
            nomes.append(nome)
            args.append(arg)
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
    # Bloqueios semeados (`cenario["bloqueios"]`), na ordem da fixture. Vazio = agenda livre (o
    # default de todos os cenarios anteriores).
    bloqueios: list[UUID] = field(default_factory=list)
    # Relogio injetado no seed. Guardado no Cenario porque quem AVALIA a corrida precisa da MESMA
    # ancora para recomputar a hora esperada (`proximo_livre`/`janelas_livres`) — sem ela o check
    # so pode hardcodar hora, que apodrece calado quando um setting de agenda muda.
    agora: datetime | None = None


# --- relogio do cenario: formas relativas ancoradas no `agora` injetado ----------------------

# Mesmo fuso da agenda (`prepare_context._FUSO_BR`, `dominio/agenda`): "hoje 21:00" na fixture tem
# de ser as 21:00 que o prompt renderiza e que o `criar_bloqueio_previo` valida. Resolver em UTC
# deslocaria o cenario em 3h e mudaria ate o DIA nas bordas (21:00 BRT = 00:00 UTC do dia seguinte).
_FUSO_BR = ZoneInfo("America/Sao_Paulo")

# "hoje 21:00" | "amanha 00:30" | "21:00" (= hoje). Sem segundos de proposito: o cenario fala a
# lingua da agenda (a IA oferta em hora cheia/meia).
_RELATIVO_HORA = re.compile(
    r"^\s*(ontem|hoje|amanha|amanhã|depois de amanha|depois de amanhã)?\s*(\d{1,2}):(\d{2})\s*$",
    re.IGNORECASE,
)
_DIAS_RELATIVOS = {
    "ontem": -1,
    "hoje": 0,
    "amanha": 1,
    "amanhã": 1,
    "depois de amanha": 2,
    "depois de amanhã": 2,
}


def _base_do_relogio(agora: datetime | None) -> datetime:
    """O instante-ancora do cenario, aware. `None` = relogio de parede (o mesmo default de `seedar`
    e do turno); naive vira UTC pela MESMA convencao do `prepare_context` (`agora_utc.tzinfo` ausente
    -> UTC), senao a fixture e o prompt discordariam do fuso em silencio."""
    base = agora if agora is not None else datetime.now(UTC)
    return base if base.tzinfo else base.replace(tzinfo=UTC)


def instante_do_cenario(valor: Any, agora: datetime | None) -> datetime:
    """Resolve uma marca de tempo da fixture num instante aware, ancorada no relogio INJETADO.

    Formas aceitas (todas relativas a `agora`, exceto o `datetime` absoluto):

    - `"hoje 21:00"` / `"amanha 00:30"` / `"21:00"` — hora do dia no fuso da agenda (BRT);
    - `timedelta(hours=2)` — offset a partir de `agora` (a forma que a matriz de cenarios escreve:
      "bloqueio +2h -> +3h");
    - `int`/`float` — o mesmo offset, em MINUTOS (`-30` = bloqueio ja em curso);
    - `datetime` — absoluto (naive -> UTC);
    - ISO 8601 (`"2026-08-13T21:00:00-03:00"`) — escape para o caso raro que precisa de data fixa.

    Publica de proposito: os checks que recomputam a hora esperada (`proximo_livre`,
    `janelas_livres`) precisam resolver a MESMA marca com a MESMA ancora — numero magico no check
    apodrece calado quando o `agenda_buffer_min` muda.
    """
    base = _base_do_relogio(agora)
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    if isinstance(valor, timedelta):
        return base + valor
    if isinstance(valor, bool):  # bool e int: barrar antes do ramo numerico
        raise TypeError(f"marca de tempo invalida no cenario: {valor!r}")
    if isinstance(valor, int | float):
        return base + timedelta(minutes=float(valor))
    if isinstance(valor, str):
        m = _RELATIVO_HORA.match(valor)
        if m is not None:
            dia = (m.group(1) or "hoje").lower()
            local = base.astimezone(_FUSO_BR)
            alvo = local.date() + timedelta(days=_DIAS_RELATIVOS[dia])
            return datetime.combine(alvo, time(int(m.group(2)), int(m.group(3))), tzinfo=_FUSO_BR)
        try:
            iso = datetime.fromisoformat(valor)
        except ValueError as exc:
            raise ValueError(f"marca de tempo invalida no cenario: {valor!r}") from exc
        return iso if iso.tzinfo else iso.replace(tzinfo=UTC)
    raise TypeError(f"marca de tempo invalida no cenario: {valor!r}")


def data_do_cenario(valor: Any, agora: datetime | None) -> date | None:
    """Idem para uma DATA de calendario (`atendimentos.data_desejada`): `date`, "hoje"/"amanha"/
    "ontem" ou ISO. `None` passa reto (campo ausente da fixture = coluna NULL, como sempre foi).

    O dia sai do `agora` visto em BRT — em UTC, um cenario ancorado as 22:00 BRT gravaria "amanha"
    como data desejada de HOJE."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.astimezone(_FUSO_BR).date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        chave = valor.strip().lower()
        if chave in _DIAS_RELATIVOS:
            local = _base_do_relogio(agora).astimezone(_FUSO_BR)
            return local.date() + timedelta(days=_DIAS_RELATIVOS[chave])
        return date.fromisoformat(valor)
    raise TypeError(f"data invalida no cenario: {valor!r}")


async def _seed_modelo(conn: AsyncConnection[dict[str, Any]], spec: dict[str, Any]) -> UUID:
    modelo_id = uuid4()
    tipos = spec.get("tipo_atendimento_aceito") or ["interno", "externo"]
    await conn.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             localizacao_operacional, endereco_formatado, nome_local, chave_pix)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s, %s, %s)
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
            spec.get("nome_local"),
            # Sem chave_pix o fluxo externo fica cego: o coordenador nunca anexa a bolha da chave
            # (pix_status vira 'aguardando' mas o cliente nao recebe pra onde pagar). Em prod a
            # coluna E anulavel (conferido em 12/08), entao o cego existe la tambem — o default
            # aqui so tira o rig desse caminho por padrao; um caso que QUEIRA exercita-lo passa
            # `chave_pix: null` explicito no spec (chave presente vence o default).
            spec.get("chave_pix", "pix-teste@example.invalid"),
        ),
    )
    for prog in spec.get("programas") or []:
        await _seed_programa(conn, modelo_id, prog)
    # Fetiches (ADR 0014 revisado / 0030 / 0035) — opcional; sem a chave o bloco <fetiches> sai
    # "(sem fetiches cadastrados)" (preserva os casos existentes).
    for fet in spec.get("fetiches") or []:
        await _seed_fetiche(conn, modelo_id, fet)
    # Disponibilidade (ADR 0005) — opcional; sem a chave o modelo e reservavel sempre (preserva os
    # casos existentes). Cada regra: dia_semana (DOW Postgres 0=dom) + janela, valida desde -7d.
    for regra in spec.get("disponibilidade") or []:
        await conn.execute(
            """
            INSERT INTO barravips.modelo_disponibilidade
                (id, modelo_id, data_inicio, dia_semana, hora_inicio, hora_fim)
            VALUES (%s, %s, current_date - 7, %s, %s, %s)
            """,
            (uuid4(), modelo_id, regra["dia_semana"], regra["hora_inicio"], regra["hora_fim"]),
        )
    await _seed_midias(conn, modelo_id)
    # Parceria (ADR de 12/08) — opcional; sem a chave `carregar_parceria` devolve None e
    # `envolver_parceira` levanta `_ERRO_SEM_PARCEIRA`, que e o estado de quase todo o cadastro e
    # o comportamento de todos os casos anteriores a esta chave.
    if spec.get("parceria"):
        await _seed_parceria(conn, modelo_id, spec["parceria"])
    return modelo_id


async def _seed_parceria(
    conn: AsyncConnection[dict[str, Any]], modelo_id: UUID, spec: dict[str, Any]
) -> UUID:
    """Cria a modelo-PARCEIRA e o vinculo ativo. Devolve o id da parceira.

    A parceira e uma `modelos` de verdade (o `carregar_parceria` faz JOIN e devolve None se o
    `nome` nao vier), mas sem programas/midia: o que o agente pode fazer com ela e so o que os
    dois modos autorizam — em `dupla` ele cota pela tabela DELA-QUE-CONDUZ, em `encaminhar` ele
    para de cotar. Cadastro proprio aqui so criaria a tentacao de vazar dado dela.

    `numero_whatsapp` NAO usa o sentinela `test-wpp-*` das outras modelos: precisa ser E.164 de
    verdade. A bolha do contato e deterministica (`_parceria.formatar_bolha_contato_parceira`,
    anexada pelo coordenador) e o carve-out que a salva da rede anti-Pix do output_guard faz
    `fullmatch` de "contato da <nome>: +<12-14 digitos>". Com o sentinela a bolha nao se forma e o
    encaminhamento passaria verde sem NUNCA exercitar a entrega do contato — o buraco que estes
    cenarios existem para fechar. `+5519900000xxx` e o bloco 9-seguido-de-zeros, nao atribuivel
    pela Anatel: E.164 valido em forma, inexistente em fato.

    O sufixo e SORTEADO porque `modelos_numero_whatsapp_key` e UNIQUE e cada cenario com parceria
    seeda a sua Yasmin na mesma transacao efemera — um literal fixo colide no segundo cenario. Por
    isso tambem o grader do vazamento (`_ia_escreveu_um_telefone`) nao recebe o literal: ele
    procura QUALQUER E.164 fora da bolha canonica, o que alem de nao acoplar ao seed ainda pega o
    caso pior, o telefone INVENTADO.
    """
    parceira_id = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (
            parceira_id,
            spec.get("nome", "Yasmin"),
            spec.get("idade", 24),
            # +55 19 9 0000XXXX = 13 digitos, dentro do `\+\d{12,14}` que a bolha canonica exige.
            spec.get("numero_whatsapp") or f"+551990000{parceira_id.int % 10_000:04d}",
            spec.get("valor_padrao", 500),
            # NOT NULL na tabela. O valor nao e lido por caminho nenhum da parceira
            # (`carregar_parceria` traz so nome/idade/flags do par), entao o default largo aqui
            # e o que MENOS mente: a parceira nao tem cadastro proprio exercitado no rig.
            spec.get("tipo_atendimento_aceito") or ["interno", "externo"],
        ),
    )
    await conn.execute(
        """
        INSERT INTO barravips.modelo_parcerias
            (id, modelo_id, parceira_id, encaminhamento_ativo, encaminhamento_atos, dupla_ativa)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            modelo_id,
            parceira_id,
            bool(spec.get("encaminhamento_ativo", False)),
            list(spec.get("encaminhamento_atos") or []),
            bool(spec.get("dupla_ativa", False)),
        ),
    )
    return parceira_id


# Tags do enviar_midia (ferramentas/midia.py: TagMidia). Cobertas TODAS, foto e video, p/ que
# qualquer (tag, tipo) que o LLM peça case — em prod a modelo SEMPRE tem mídia pra mandar.
_TAGS_MIDIA = ("apresentacao", "corpo", "lifestyle", "evento")


async def _seed_midias(conn: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> None:
    """Semeia uma foto E um vídeo aprovados em CADA tag — fidelidade a prod, onde a modelo sempre
    tem mídia (a mídia-prova é o núcleo da venda). Sem isto, `enviar_midia` falha em toda tag e o
    LLM re-tenta combinações até o recursion_limit (loop que é artefato do harness, não existe em
    prod). `ultimo_envio_em` NULL -> NULLS FIRST escolhe estas primeiro na rotação."""
    for tag in _TAGS_MIDIA:
        for tipo, ext in (("foto", "jpg"), ("video", "mp4")):
            mid = uuid4()
            await conn.execute(
                """
                INSERT INTO barravips.modelo_midia
                    (id, modelo_id, tipo, tag, bucket, object_key, aprovada, ultimo_envio_em,
                     created_at)
                VALUES (%s, %s, %s, %s, 'media', %s, true, NULL, now())
                """,
                (mid, modelo_id, tipo, tag, f"media/{mid}.{ext}"),
            )


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


async def _seed_fetiche(
    conn: AsyncConnection[dict[str, Any]], modelo_id: UUID, fet: dict[str, Any]
) -> None:
    """Vincula um fetiche do catalogo GLOBAL a modelo (`modelo_fetiches`).

    `preco` None = incluso, preenchido = pago; o VALOR importa desde a revisao de 11/08/2026 do
    ADR-0030 (numero de verdade = o extra; sentinel abaixo do minimo = cai no derivado, a linha de
    1h do ADR-0038). `cobra_por_pessoa` e propriedade do CATALOGO, nao do vinculo (ADR-0035): e
    ela que separa a secao "Por pessoa" (casal/menage) dos atos no `fetiches.md.j2` — desde o
    ADR-0039 so como CLASSIFICACAO, porque as duas secoes cobram o mesmo extra.

    O get-or-create por nome reusa a linha curada do prod (os quatro itens de COMPOSICAO ja
    nascem com a flag true pela migration 20260811232000, que aposentou o par ambiguo
    "Casal"/"Menage") e NUNCA a atualiza — mas um nome existente com a flag
    DIFERENTE da que o cenario pede renderia o bloco errado em silencio (o cenario de menage
    perderia a secao "Por pessoa" inteira). Entao isso falha alto, em vez de decorar.
    """
    quer_por_pessoa = bool(fet.get("cobra_por_pessoa", False))
    fet_id = await _get_or_create(
        conn,
        "fetiches",
        fet["nome"],
        colunas={"ordem": fet.get("ordem", 0), "cobra_por_pessoa": quer_por_pessoa},
    )
    res = await conn.execute(
        "SELECT cobra_por_pessoa FROM barravips.fetiches WHERE id = %s", (fet_id,)
    )
    linha = await res.fetchone() or {}
    if bool(linha.get("cobra_por_pessoa")) != quer_por_pessoa:
        raise RuntimeError(
            f"catalogo global divergente: fetiche {fet['nome']!r} tem "
            f"cobra_por_pessoa={linha.get('cobra_por_pessoa')!r}, cenario pede {quer_por_pessoa!r}"
        )
    await conn.execute(
        "INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (modelo_id, fet_id, fet.get("preco")),
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
    agora: datetime | None = None,
) -> UUID:
    """Seed parametrizado por `atendimento` (estado/tipo/pix/ia_pausada da fixture).

    Os campos de AGENDA do atendimento (`data_desejada`, `horario_desejado`, `duracao_horas`,
    `urgencia`, `valor_acordado`, `horario_evidenciado`, `aviso_saida_em`) sao opcionais e nascem
    NULL/false — o default reproduz exatamente o atendimento "cru" que todos os cenarios ja
    seedavam. Eles existem para os cenarios que nascem DEPOIS do fechamento (`Aguardando_confirmacao`
    com hora combinada): a remarcacao le os tres juntos (`_reagendamento_pos_bloqueio` e
    `_modelo_ainda_nao_acionada`, dominio/atendimentos/service) e o `<situacao_do_atendimento>`
    renderiza data+hora. O `bloqueio_id` NAO entra aqui: quem o preenche e o proprio bloqueio
    proprio da fixture (`bloqueios: [{... "atendimento": true}]`, ver `_seed_bloqueio`), que so pode
    nascer depois desta linha existir (FK circular).

    `data_desejada` aceita `date`, "hoje"/"amanha"/"ontem" ou ISO; `aviso_saida_em` aceita `True`
    (= o proprio `agora`) ou qualquer forma de `instante_do_cenario` — as duas ancoradas no relogio
    injetado, nunca no relogio de parede (senao "hoje 21:00" muda de sentido a cada corrida).
    """
    atendimento_id = uuid4()
    estado = atendimento.get("estado", "Triagem")
    ia_pausada = bool(atendimento.get("ia_pausada", False))
    aviso = atendimento.get("aviso_saida_em")
    aviso_saida_em: datetime | None = None
    if aviso is True:
        aviso_saida_em = agora or datetime.now(UTC)
    elif aviso is not None and aviso is not False:  # `is`: `0 == False` engoliria o offset zero
        aviso_saida_em = instante_do_cenario(aviso, agora)
    await conn.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado,
             tipo_atendimento, pix_status, ia_pausada, ia_pausada_motivo, cotacao_enviada_em,
             data_desejada, horario_desejado, duracao_horas, urgencia, valor_acordado,
             horario_evidenciado, aviso_saida_em)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum,
                %s::barravips.pix_status_enum, %s,
                %s::barravips.ia_pausada_motivo_enum,
                CASE WHEN %s THEN now() ELSE NULL END,
                %s::date, %s::time, %s::numeric, %s::barravips.urgencia_enum, %s::numeric,
                %s, %s::timestamptz)
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
            data_do_cenario(atendimento.get("data_desejada"), agora),
            atendimento.get("horario_desejado"),
            atendimento.get("duracao_horas"),
            atendimento.get("urgencia"),
            atendimento.get("valor_acordado"),
            bool(atendimento.get("horario_evidenciado", False)),
            aviso_saida_em,
        ),
    )
    return atendimento_id


async def _seed_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    atendimento_id: UUID | None,
    spec: dict[str, Any],
    agora: datetime | None = None,
) -> UUID:
    """Insere UM bloqueio da agenda da modelo (a "agenda ocupada" que o cenario declara).

    `spec` = {inicio, fim | duracao_min, estado?, origem?, observacao?, atendimento?}:

    - `inicio`/`fim`: qualquer forma de `instante_do_cenario` — "hoje 21:00"/"amanha 00:30"
      (BRT), `timedelta(hours=2)` ou minutos (int), sempre relativos ao `agora` INJETADO. Nenhum
      cenario deve escrever hora absoluta: o `agora` do cenario e a unica ancora.
    - `duracao_min` (default 60) so vale quando `fim` esta ausente.
    - `tipo_atendimento` (interno | externo | remoto; default None) declara ONDE o compromisso
      acontece — e o que faz um bloqueio `externo` (ela na casa de um cliente) cobrar
      `agenda_buffer_externo_min` de gap dos dois lados em vez do `agenda_buffer_min` (emenda ADR
      0025, 2026-08-14). None = desconhecido: o gap padrao, o comportamento de todos os cenarios
      escritos antes desta emenda. Num bloqueio com `atendimento: true` o tipo do ATENDIMENTO ja
      basta (o dominio deriva por COALESCE); este campo e para o bloqueio AVULSO, que e justamente
      o "ela sai de um servico na casa de outro cliente".
    - `estado` default 'bloqueado' e `origem` default 'manual' — o bloqueio ATIVO e opaco, que e o
      que a agenda ve (`prepare_context` recorta por `fim > agora` e estado ativo). 'cancelado'/
      'concluido' servem para provar o oposto (nao conflitam, pelo EXCLUDE parcial da tabela).
    - `atendimento: true` amarra o bloqueio ao atendimento do proprio cenario E faz o back-link
      (`atendimentos.bloqueio_id`) — e o "bloqueio proprio", que o `prepare_context` esconde de
      proposito da lista de ocupacao (ela nao pode recusar a propria reserva).

    `id` fica com o DEFAULT `barravips.uuidv7()` da tabela (como prod) e volta por RETURNING para o
    back-link. `created_at`/`updated_at` seguem o relogio injetado pelo mesmo motivo do
    `_inserir_mensagem`: uma linha nascida no `now()` do banco enquanto o turno acontece no relogio
    fixo desloca qualquer leitura por idade do registro.

    Sobreposicao entre dois bloqueios ATIVOS estoura o EXCLUDE `bloqueios_sem_sobreposicao` — e o
    banco dizendo que o cenario e impossivel (a modelo nao pode estar em dois lugares), nao um bug
    do seed.
    """
    inicio = instante_do_cenario(spec["inicio"], agora)
    if spec.get("fim") is not None:
        fim = instante_do_cenario(spec["fim"], agora)
    else:
        fim = inicio + timedelta(minutes=int(spec.get("duracao_min", 60)))
    do_atendimento = bool(spec.get("atendimento", False))
    res = await conn.execute(
        """
        INSERT INTO barravips.bloqueios
            (modelo_id, atendimento_id, inicio, fim, estado, origem, observacao,
             tipo_atendimento, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_bloqueio_enum,
                %s::barravips.origem_bloqueio_enum, %s,
                %s::barravips.tipo_atendimento_enum,
                COALESCE(%s::timestamptz, now()), COALESCE(%s::timestamptz, now()))
        RETURNING id
        """,
        (
            modelo_id,
            atendimento_id if do_atendimento else None,
            inicio,
            fim,
            spec.get("estado", "bloqueado"),
            spec.get("origem", "manual"),
            spec.get("observacao"),
            spec.get("tipo_atendimento"),
            agora,
            agora,
        ),
    )
    linha = await res.fetchone() or {}
    bloqueio_id = UUID(str(linha["id"]))
    if do_atendimento and atendimento_id is not None:
        await conn.execute(
            "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
            (bloqueio_id, atendimento_id),
        )
    return bloqueio_id


async def _inserir_mensagem(
    conn: AsyncConnection[dict[str, Any]],
    *,
    conversa_id: UUID,
    direcao: str,
    texto: str,
    tipo: str = "texto",
    media_object_key: str | None = None,
    created_at: datetime | None = None,
) -> None:
    """Insere uma linha em `mensagens` como prod grava. `tipo`/`media_object_key` default = texto
    puro (retrocompat); 'imagem'/'audio' carregam o `conteudo` que o agente VE (caption da imagem /
    transcricao do audio) — o STT/caption ja resolveram antes do turno (ver `traduzir_mensagens`).

    SEM `id` explicito: deixa o default `barravips.uuidv7()` da tabela agir, como prod. Todas as
    linhas do seed empatam em `created_at` (`now()` = transaction_timestamp na MESMA transacao) e o
    desempate da janela e `id DESC` — com `uuid4()` a ordem cliente-vs-IA saia ALEATORIA, e todo
    detector que le a cauda (correferencia do dia, aceite da sondagem, evidencia do horario) virava
    flaky. `uuidv7` e time-ordered, entao a ordem de insercao vira a ordem da janela.

    `created_at` existe SO para o relogio injetado (`agora`): quem fixa o relogio do turno tem de
    ancorar a linha nele tambem, senao a mensagem nasce no `now()` do banco (a hora em que alguem
    rodou o eval) e o agente le a distancia entre os dois como tempo decorrido — medido em 12/12
    conversas do rig de 12/08: `<tempo_desde_ultima_msg_cliente minutos="~10200"/>` no PRIMEIRO
    turno de uma conversa nova, com o rig inteiro exercitando retomada pos-silencio. `None` (prod e
    todo eval de relogio real) mantem o DEFAULT `now()` — e por isso o COALESCE, nao um SQL a
    parte: as linhas seguem EMPATANDO em `created_at` (agora no instante injetado, antes no
    transaction_timestamp) e o desempate segue sendo `id DESC`."""
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id,
             created_at)
        VALUES (%s, %s::barravips.direcao_mensagem_enum, %s, %s, %s, %s,
                COALESCE(%s::timestamptz, now()))
        """,
        (
            conversa_id,
            direcao,
            tipo,
            texto,
            media_object_key,
            f"test-evo-{uuid4().hex}",
            created_at,
        ),
    )


async def seedar(
    conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any], *, agora: datetime | None = None
) -> Cenario:
    """Seed completo de uma fixture: par A (sempre) + par B opcional (isolamento) + historico.

    `fixture["cenario"]` = {modelo, atendimento, bloqueios?, recorrente?, observacoes_internas?,
    par_b?, canary?}. `fixture["historico"]` = [{direcao, texto}] inserido antes do turno (mensagens
    passadas). `fixture["turno_cliente"]` e inserido por `rodar_turno`, nao aqui.

    `cenario["bloqueios"]` (opcional; ausente = agenda VAZIA, o default de todos os cenarios
    anteriores) e a AGENDA OCUPADA do cenario — `[{inicio, fim|duracao_min, estado?, origem?,
    observacao?, atendimento?}]`, com as horas ancoradas em `agora` (ver `_seed_bloqueio` e
    `instante_do_cenario`). Exemplo do cenario "hora pedida ocupada":

        {"cenario": {"modelo": {...},
                     "atendimento": {"estado": "Novo"},
                     "bloqueios": [{"inicio": timedelta(hours=2), "duracao_min": 60}]},
         "historico": []}

    `agora` = o MESMO relogio injetado que o caller vai passar ao turno (`rodar_turno_fiel(agora=)`
    / `rodar_turno(agora_utc=)`). Sem ele o historico nasce no `now()` do banco enquanto o turno
    "acontece" no relogio fixo, e a distancia entre os dois vira tempo decorrido para o agente
    (`<tempo_desde_ultima_msg_cliente>`) e, acima de 6h, uma MARCA DE PAUSA sintetica no meio de uma
    conversa que nunca teve pausa (`_GAP_PAUSA`, prepare_context). Ancorando os dois no mesmo
    instante o historico volta a EMPATAR com o turno — exatamente o que acontecia quando os dois
    caiam no transaction_timestamp."""
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
        agora=agora,
    )
    # Depois do atendimento: o bloqueio PROPRIO ({"atendimento": true}) referencia a linha dele e
    # ainda escreve o back-link `atendimentos.bloqueio_id`.
    bloqueios = [
        await _seed_bloqueio(
            conn, modelo_id=modelo_id, atendimento_id=atendimento_id, spec=spec, agora=agora
        )
        for spec in cen.get("bloqueios") or []
    ]

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
            agora=agora,
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
                created_at=agora,
            )

    for msg in fixture.get("historico", []):
        await _inserir_mensagem(
            conn,
            conversa_id=conversa_id,
            direcao=msg.get("direcao", "cliente"),
            texto=msg["texto"],
            created_at=agora,
        )

    return Cenario(
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        atendimento_id=atendimento_id,
        modelo_b_id=modelo_b_id,
        canary=cen.get("canary"),
        programas=cen.get("modelo", {}).get("programas", []),
        bloqueios=bloqueios,
        agora=agora,
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
    agora_utc: datetime | None = None,
) -> ResultadoTurno:
    """Insere a mensagem do cliente, roda UM `ainvoke` (gasta credito, §0) e coleta o resultado.

    `graph` reusavel entre turnos (build_graph() uma vez). `conn` e a MESMA do seed (transacao).
    `trace_tag` marca a origem do trace no Langfuse (gate vs e2e). `escopar_trace` embrulha o
    ainvoke num span com trace-id deterministico (padrao de prod, coordenador.py) e o devolve em
    `ResultadoTurno.trace_id` para ancorar o score online (`registrar_feedback_online`).
    `agora_utc` (clock injection -> ContextAgente.agora_utc): ancora o "agora" do turno num
    instante fixo — sem isso cada corrida ve o now() do banco na hora em que roda, e prefixos
    reais com "hoje/amanha" mudam de sentido entre corridas (confound entre bracos de um A/B). A
    fala do cliente e gravada NESSE mesmo instante (ver `_inserir_mensagem`): ancorar so o relogio
    deixava a mensagem no `now()` do banco e o agente lia a diferenca como tempo decorrido.
    """
    await _inserir_mensagem(
        conn,
        conversa_id=cen.conversa_id,
        direcao="cliente",
        texto=turno_cliente,
        created_at=agora_utc,
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
        agora_utc=agora_utc,
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
            str(cen.modelo_id),
            str(cen.atendimento_id),
            str(cen.cliente_id),
            # Mesmo carimbo de regime do coordenador: sem ele os traces de um grid A/B (thinking
            # disabled x low x high) sao indistinguiveis entre si no painel.
            regime=regime_do_turno(get_settings()),
        )
        meta["metadata"]["langfuse_tags"] = [*meta["metadata"]["langfuse_tags"], trace_tag]
        config["metadata"] = meta["metadata"]
        config["tags"] = [*meta["tags"], trace_tag]
        # Span SEMPRE, com trace-id deterministico (seed=turno_id) — padrao de coordenador.py. Sem
        # ele o CallbackHandler abria um trace ANONIMO (`name: ""`), o formato que enchia o projeto
        # de traces impossiveis de achar. `escopar_trace` agora so decide se o id volta ao caller
        # (quem vai ancorar score online); o trace nasce nomeado nos dois casos.
        from langfuse import Langfuse, get_client

        trace_id_span = Langfuse.create_trace_id(seed=ctx.turno_id)
        trace_id = trace_id_span if escopar_trace else None
        span_ctx = get_client().start_as_current_observation(
            as_type="span",
            name=f"turno_{trace_tag}",
            trace_context={"trace_id": trace_id_span},
        )

    t0 = perf_counter()
    with span_ctx as turno_span:
        estado = await graph.ainvoke({"messages": []}, config=config, context=ctx)
        # Resumo do root span igual ao de prod (fala + desfecho + raciocinio + tags do que
        # aconteceu): o trace de um rig fica tao legivel quanto o de um turno real.
        if lf is not None:
            desfecho_rig = desfecho_do_turno(estado)
            resumir_trace_turno(
                turno_span,
                entrada=mensagens_cliente_do_turno(estado),
                resposta=extrair_texto_do_turno(estado["messages"]),
                desfecho=desfecho_rig,
                raciocinio=raciocinio_do_turno(estado),
                tags=[*config["tags"], *tags_do_turno(estado)],
                level="WARNING" if desfecho_rig.get("erros_tool") else "DEFAULT",
            )
    latencia = perf_counter() - t0

    mensagens: list[BaseMessage] = estado["messages"]
    # O rastro de tool das mensagens nao sobrevive a regeneracao do output_guard; o de
    # `barravips.tool_calls` sim. Leitura na mesma conn, antes do ROLLBACK do caller.
    nomes, args = _mesclar_tools(
        _coletar_tools(mensagens), await _tools_do_banco(conn, [ctx.turno_id])
    )
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
        estado_grafo=carimbos_do_estado(estado),
    )


def habilitar_tracing() -> bool:
    """Liga o trace Langfuse de prod (ADR 0019) para os turnos do gate. Idempotente; retorna se
    o handler ficou disponivel (precisa das envs LANGFUSE_* — senao no-op silencioso).

    Os rigs rodam o grafo real (geram generations), entao registram os modelos p/ o total_cost do
    trace (senao 0) e marcam o `service.name` como `barra-evals` — o environment (settings.ambiente)
    ja separa do trafego de prod."""
    from barra.agente._custo import modelos_para_langfuse
    from barra.core.tracing import registrar_modelos_langfuse, setup_langfuse

    # `permitir_em_teste`: o rig e2e tambem roda sob pytest (AMBIENTE=teste), onde o setup_langfuse
    # e no-op por padrao p/ nao encher o projeto de trace de LLM fake. Aqui o trace e o PRODUTO da
    # corrida (dataset e2e_conducao, score do veredito), entao o opt-in e explicito.
    setup_langfuse(get_settings(), servico="barra-evals", permitir_em_teste=True)
    registrar_modelos_langfuse(modelos_para_langfuse())
    return langfuse_handler() is not None
