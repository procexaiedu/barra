"""Runner minimo de evals (EVAL-01): carrega fixtures .jsonl, seeda o estado, roda o grafo
real MULTI-TURNO e aplica graders DETERMINISTICOS, emitindo exit-code de gate.

Escopo (roadmap EVAL-01): graders deterministicos apenas -- tool_calls_obrigatorias/proibidas,
texto_resposta (nao_deve_conter/deve_conter_um_de/max_chars), ia_pausada_final, estado_final /
state_check. Rubricas `judge: llm` sao de EVAL-02 (ignoradas aqui); nodes_proibidos /
NodesVisitedHandler sao de EVAL-08.

Multi-turno (refino 08b §5): `mensagens_entrada` e uma LISTA consumida mensagem-a-mensagem.
Cada mensagem do CLIENTE dispara UMA `ainvoke` (o prepare_context reconstroi a janela do banco);
mensagens com `direcao:"ia"`/`"modelo_manual"` sao respostas roteirizadas que entram no banco
como historico mas NAO disparam invoke. Sem isso o contador de insistencia (disclosure) so
chegaria a 1 num unico invoke e a fixture multi-turno nunca exercitaria a escalada na 3a.
Cada mensagem pode declarar `state_check` (estado esperado APOS aquele turno); as
`expectativas` de topo valem para o ULTIMO turno (o resultado final da conversa roteirizada).

Escalada determinista == `escalar`: disclosure-insistente/jailbreak escalam via `abrir_handoff`
(no intercept_disclosure), nao pela tool `escalar`. A Captura detecta a linha aberta em
`escaladas` (`escalou`) e injeta "escalar" no conjunto de tools, para `tool_calls_obrigatorias/
proibidas:["escalar"]` cobrir tanto o caminho deterministico quanto o do LLM.

Agregacao POR FIXTURE (refino 08b §5 / EVAL-04/03 §3.5): as K amostras de uma fixture sao
colapsadas em UM veredito por `agregar_por_fixture` (nunca tratadas como K pontos independentes).
No EVAL-01 e K=1 (identidade); o loop K=5 + politica por categoria (pass^k vs maioria) e EVAL-04/03.

Invocacao real espelha tests/agente/test_fixtures_leitura_decisao.py: grafo SEM checkpointer,
pool fake de UMA conexao (prepare_context + tools na MESMA transacao), ROLLBACK por fixture
(estado acumula ENTRE turnos da mesma fixture; so reseta ao trocar de fixture). Usa
TEST_DATABASE_URL (nunca prod direto) + ANTHROPIC_API_KEY.

`avaliar()`, `gate()`, `planejar_turnos()` e `agregar_por_fixture()` sao PUROS (nao tocam
DB/LLM): sao o nucleo testavel do gate (tests/evals/test_runner_gate.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph

_EVALS_RAIZ = Path(__file__).resolve().parents[1]


# --- carregamento de fixtures ------------------------------------------------------------------


def carregar_fixtures(
    raiz: Path = _EVALS_RAIZ, subdirs: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """Le todas as fixtures .jsonl (uma por linha) sob `raiz` (ou apenas os `subdirs` dados)."""
    bases = [raiz / s for s in subdirs] if subdirs else [raiz]
    fixtures: list[dict[str, Any]] = []
    for base in bases:
        for arquivo in sorted(base.rglob("*.jsonl")):
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    fixtures.append(json.loads(linha))
    return fixtures


# --- captura do turno --------------------------------------------------------------------------


@dataclass
class Captura:
    """O que o turno produziu, extraido para o `avaliar()` puro decidir pass/fail."""

    tools_chamadas: set[str]
    texto_final: str
    estado_atendimento: str
    ia_pausada: bool
    pix_status: str
    # True se uma linha foi aberta em `escaladas` durante a fixture (handoff determinista do
    # intercept_disclosure OU a tool `escalar` do LLM). `avaliar()` injeta "escalar" no conjunto
    # de tools quando True, para o grader cobrir os dois caminhos de escalada.
    escalou: bool = False


def _tools_chamadas(mensagens: list[BaseMessage]) -> set[str]:
    """Nomes de tools pedidas (tool_calls em AIMessage) ou executadas (ToolMessage)."""
    nomes: set[str] = set()
    for m in mensagens:
        for tc in getattr(m, "tool_calls", None) or []:
            nome = tc.get("name")
            if nome:
                nomes.add(nome)
        if isinstance(m, ToolMessage) and m.name:
            nomes.add(m.name)
    return nomes


def _texto_final(mensagens: list[BaseMessage]) -> str:
    """Conteudo (texto) da ultima AIMessage -- a bolha que iria ao cliente."""
    for m in reversed(mensagens):
        if isinstance(m, AIMessage):
            conteudo = m.content
            if isinstance(conteudo, str):
                return conteudo
            partes = [
                bloco.get("text", "")
                for bloco in conteudo
                if isinstance(bloco, dict) and bloco.get("type") == "text"
            ]
            return "".join(partes)
    return ""


# --- seeding (espelha test_fixtures_leitura_decisao.py) ----------------------------------------


class _PoolDeUmaConexao:
    """Pool fake de UMA conexao: prepare_context e as tools leem a MESMA transacao (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


async def _seed_entidades(
    conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any]
) -> tuple[UUID, UUID, UUID, UUID]:
    """Cria modelo/cliente/conversa/atendimento a partir do `estado_inicial` (SEM mensagens).

    Retorna (modelo_id, atendimento_id, cliente_id, conversa_id). `estado_inicial.recorrente` vai
    na conversa (par cliente-modelo); estado/ia_pausada/pix_status vao no atendimento. As mensagens
    sao inseridas turno-a-turno por `_inserir_mensagem` (multi-turno, refino 08b §5).
    """
    inicial = fixture.get("estado_inicial", {})
    estado = inicial.get("atendimento_estado", "Triagem")
    ia_pausada = bool(inicial.get("ia_pausada", False))
    pix_status = inicial.get("pix_status", "nao_solicitado")
    recorrente = bool(inicial.get("recorrente", False))

    modelo_id, cliente_id, conversa_id, atendimento_id = uuid4(), uuid4(), uuid4(), uuid4()

    await conn.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Eval", 25, f"eval-wpp-{uuid4().hex}", 500, ["interno", "externo"]),
    )
    await conn.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"eval-tel-{uuid4().hex}", None),
    )
    await conn.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id, recorrente)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"eval-chat-{uuid4().hex}", recorrente),
    )
    await conn.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id,
             estado, pix_status, ia_pausada, ia_pausada_motivo)
        VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            atendimento_id,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            pix_status,
            ia_pausada,
            "handoff_ia" if ia_pausada else None,
        ),
    )
    return modelo_id, atendimento_id, cliente_id, conversa_id


async def _inserir_mensagem(
    conn: AsyncConnection[dict[str, Any]], conversa_id: UUID, msg: dict[str, Any]
) -> None:
    """Insere UMA mensagem da fixture na conversa (direcao cliente/ia/modelo_manual)."""
    direcao = msg.get("direcao", "cliente")
    if direcao not in ("cliente", "ia", "modelo_manual"):
        direcao = "cliente"
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, %s, %s, 'texto', %s, %s)
        """,
        (uuid4(), conversa_id, direcao, msg["texto"], f"eval-evo-{uuid4().hex}"),
    )


@dataclass
class PlanoTurno:
    """Uma entrada de `mensagens_entrada`: a mensagem + se ela dispara um turno (`ainvoke`)."""

    indice: int
    msg: dict[str, Any]
    dispara: bool  # True so para mensagens do cliente; 'ia'/'modelo_manual' = historico


def planejar_turnos(mensagens_entrada: list[dict[str, Any]]) -> list[PlanoTurno]:
    """Plano determinista de consumo turno-a-turno (PURO -- testavel sem DB/LLM).

    Toda mensagem entra no banco (historico da janela); so as do CLIENTE disparam `ainvoke`
    (refino 08b §5). `direcao` ausente assume cliente.
    """
    return [
        PlanoTurno(indice=i, msg=m, dispara=m.get("direcao", "cliente") == "cliente")
        for i, m in enumerate(mensagens_entrada)
    ]


async def _capturar(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID, estado: dict[str, Any]
) -> Captura:
    """Coleta a Captura de UM turno: tools/texto das mensagens + estado + escalada (pos-invoke)."""
    res = await conn.execute(
        "SELECT estado, ia_pausada, pix_status FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    escalada_row = await res.fetchone()
    return Captura(
        tools_chamadas=_tools_chamadas(estado["messages"]),
        texto_final=_texto_final(estado["messages"]),
        estado_atendimento=row["estado"],
        ia_pausada=row["ia_pausada"],
        pix_status=row["pix_status"],
        escalou=bool(escalada_row and escalada_row["n"] > 0),
    )


async def executar_fixture(
    conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any]
) -> tuple[Captura, list[str]]:
    """Seeda, roda o grafo MULTI-TURNO e coleta a Captura final + falhas de state_check por turno.

    Requer ANTHROPIC_API_KEY + DB de teste. Insere cada mensagem; so as do cliente disparam
    `ainvoke` (planejar_turnos). Estado acumula entre turnos da MESMA conexao (sem rollback aqui;
    o rollback e por fixture em `rodar`). A Captura retornada e a do ULTIMO turno do cliente.
    """
    modelo_id, atendimento_id, cliente_id, conversa_id = await _seed_entidades(conn, fixture)
    grafo = build_graph()
    captura: Captura | None = None
    falhas_turno: list[str] = []

    for plano in planejar_turnos(fixture.get("mensagens_entrada", [])):
        await _inserir_mensagem(conn, conversa_id, plano.msg)
        if not plano.dispara:
            continue  # resposta roteirizada da IA: historico da janela, nao dispara turno
        estado = await grafo.ainvoke(
            {"messages": []},
            config={"recursion_limit": 18},
            context=ContextAgente(
                db_pool=_PoolDeUmaConexao(conn),  # type: ignore[arg-type]
                redis=None,  # type: ignore[arg-type]
                modelo_id=str(modelo_id),
                atendimento_id=str(atendimento_id),
                cliente_id=str(cliente_id),
                turno_id=str(uuid4()),  # cada turno e um job distinto (turno_id novo)
                # eval single-shot por turno, IDs novos por fixture: BP_MODELO/BP_JANELA seriam
                # so write nunca read -> desliga o cache_control deles (WIP EVAL-01).
                cache_modelo_e_janela=False,
            ),
        )
        captura = await _capturar(conn, atendimento_id, estado)
        state_check_turno = plano.msg.get("state_check")
        if state_check_turno:
            falhas_turno += _comparar_state(
                state_check_turno, captura, prefixo=f"turno[{plano.indice}] "
            )

    if captura is None:
        raise ValueError(
            f"fixture {fixture.get('id', '?')!r} nao tem mensagem de cliente -- nenhum turno disparado"
        )
    return captura, falhas_turno


# --- avaliacao (PURA: graders deterministicos) -------------------------------------------------


@dataclass
class Avaliacao:
    id: str
    passou: bool
    falhas: list[str] = field(default_factory=list)
    # categoria da fixture (ex.: "adversariais", "canonicos"): governa a politica de agregacao
    # por categoria (pass^k vs maioria) em `agregar_por_fixture`. EVAL-01 nao a usa (K=1).
    categoria: str = ""


def _comparar_state(state_check: dict[str, Any], captura: Captura, prefixo: str = "") -> list[str]:
    """Compara o `state_check` declarativo contra a Captura. PURO. Reusado por turno e no final."""
    atual = {
        "atendimento_estado": captura.estado_atendimento,
        "ia_pausada": captura.ia_pausada,
        "pix_status": captura.pix_status,
    }
    return [
        f"{prefixo}{chave}: esperado {esperado!r}, obtido {atual[chave]!r}"
        for chave, esperado in state_check.items()
        if chave in atual and atual[chave] != esperado
    ]


def _tools_efetivas(captura: Captura) -> set[str]:
    """Tools observadas + "escalar" sintetico quando houve handoff determinista (escalou)."""
    tools = set(captura.tools_chamadas)
    if captura.escalou:
        tools.add("escalar")
    return tools


def avaliar(fixture: dict[str, Any], captura: Captura) -> Avaliacao:
    """Aplica os graders deterministicos da fixture sobre a Captura. Sem DB/LLM.

    Rubricas `judge: llm` (EVAL-02) e `nodes_proibidos` (EVAL-08) sao ignoradas aqui.
    """
    exp = fixture.get("expectativas", {})
    falhas: list[str] = []
    tools = _tools_efetivas(captura)

    obrigatorias = set(exp.get("tool_calls_obrigatorias", []))
    faltando = obrigatorias - tools
    if faltando:
        falhas.append(f"tool_calls_obrigatorias nao chamadas: {sorted(faltando)}")

    proibidas = set(exp.get("tool_calls_proibidas", []))
    chamou_proibida = proibidas & tools
    if chamou_proibida:
        falhas.append(f"tool_calls_proibidas chamadas: {sorted(chamou_proibida)}")

    texto = exp.get("texto_resposta", {})
    alvo = captura.texto_final.lower()
    vazados = [t for t in texto.get("nao_deve_conter", []) if t.lower() in alvo]
    if vazados:
        falhas.append(f"texto vazou termo proibido: {vazados}")
    deve_um = texto.get("deve_conter_um_de")
    if deve_um and not any(t.lower() in alvo for t in deve_um):
        falhas.append(f"texto nao contem nenhum de: {deve_um}")
    max_chars = texto.get("max_chars")
    if max_chars is not None and len(captura.texto_final) > max_chars:
        falhas.append(f"texto excede max_chars ({len(captura.texto_final)} > {max_chars})")

    # state_check (declarativo) tem precedencia sobre os aliases soltos; aplica os dois.
    state_check = dict(exp.get("state_check") or {})
    if "ia_pausada_final" in exp:
        state_check.setdefault("ia_pausada", exp["ia_pausada_final"])
    if "estado_final_atendimento" in exp:
        state_check.setdefault("atendimento_estado", exp["estado_final_atendimento"])
    falhas += _comparar_state(state_check, captura)

    return Avaliacao(
        id=fixture.get("id", "?"),
        passou=not falhas,
        falhas=falhas,
        categoria=fixture.get("categoria", ""),
    )


def _politica_agregacao(categoria: str) -> str:
    """Como colapsar as K amostras de uma fixture em 1 veredito.

    EVAL-01: K=1 -> "todas" (a unica amostra decide). EVAL-04/03 refina por categoria
    (pass^k p/ adversariais/Pix; maioria >=4/5 p/ corretude). Ponto unico para essa evolucao.
    """
    return "todas"


def _colapsar_fixture(fid: str, grupo: list[Avaliacao]) -> Avaliacao:
    """Colapsa as K amostras de UMA fixture num unico veredito (cluster do erro por fixture)."""
    categoria = grupo[0].categoria if grupo else ""
    politica = _politica_agregacao(categoria)
    k = len(grupo)
    n_pass = sum(a.passou for a in grupo)
    if politica == "maioria":
        passou = n_pass * 2 > k  # estrita maioria das amostras
    else:  # "todas"/"pass_k": nenhuma amostra pode falhar
        passou = n_pass == k
    # Cluster do erro por fixture: agrega as falhas distintas das amostras (ordem de aparicao).
    falhas: list[str] = []
    for a in grupo:
        for f in a.falhas:
            if f not in falhas:
                falhas.append(f)
    if k > 1 and falhas:
        falhas = [f"({n_pass}/{k} amostras ok) {f}" for f in falhas]
    return Avaliacao(id=fid, passou=passou, falhas=falhas, categoria=categoria)


def agregar_por_fixture(avaliacoes: list[Avaliacao]) -> list[Avaliacao]:
    """Agrupa por fixture id e colapsa cada grupo num veredito unico (refino 08b §5).

    NUNCA trata as K amostras como pontos independentes -- o gate conta FIXTURES, nao amostras.
    Preserva a ordem de primeira aparicao de cada fixture. PURO -- testavel sem DB/LLM.
    """
    grupos: dict[str, list[Avaliacao]] = {}
    for a in avaliacoes:
        grupos.setdefault(a.id, []).append(a)
    return [_colapsar_fixture(fid, grupo) for fid, grupo in grupos.items()]


def gate(avaliacoes: list[Avaliacao], threshold: float = 1.0) -> int:
    """Exit-code de gate: 0 se pass-rate (por FIXTURE) >= threshold, 1 caso contrario (ou vazia).

    Espera a lista JA agregada por fixture (`agregar_por_fixture`) -- cada item e 1 veredito.
    """
    if not avaliacoes:
        return 1
    pass_rate = sum(a.passou for a in avaliacoes) / len(avaliacoes)
    return 0 if pass_rate >= threshold else 1


# --- orquestracao + CLI ------------------------------------------------------------------------


async def _conectar() -> AsyncConnection[dict[str, Any]]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        print(
            "ERRO: TEST_DATABASE_URL nao definido (runner nao roda contra prod).", file=sys.stderr
        )
        raise SystemExit(2)
    return await AsyncConnection.connect(
        url, autocommit=False, row_factory=dict_row, prepare_threshold=None
    )


async def rodar(fixtures: list[dict[str, Any]], k: int = 1) -> list[Avaliacao]:
    """Roda cada fixture K vezes (K=1 no EVAL-01; loop K=5 e EVAL-04/03), ROLLBACK por amostra.

    Cada amostra e uma fixture multi-turno inteira numa transacao (estado acumula entre turnos,
    rollback ao fim da amostra). Retorna as avaliacoes JA agregadas por fixture -- 1 veredito cada.
    """
    brutas: list[Avaliacao] = []
    conn = await _conectar()
    try:
        for fixture in fixtures:
            for _ in range(k):
                try:
                    captura, falhas_turno = await executar_fixture(conn, fixture)
                    av = avaliar(fixture, captura)
                    if falhas_turno:
                        av.falhas = [*falhas_turno, *av.falhas]
                        av.passou = not av.falhas
                    brutas.append(av)
                finally:
                    await conn.rollback()
    finally:
        await conn.close()
    return agregar_por_fixture(brutas)


def _imprimir(avaliacoes: list[Avaliacao]) -> None:
    for a in avaliacoes:
        marca = "PASS" if a.passou else "FAIL"
        print(f"[{marca}] {a.id}")
        for f in a.falhas:
            print(f"        - {f}")
    n_pass = sum(a.passou for a in avaliacoes)
    print(f"\n{n_pass}/{len(avaliacoes)} fixtures passaram.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Runner de evals deterministico (EVAL-01).")
    parser.add_argument(
        "--subdir", action="append", help="subdiretorio de evals/ a rodar (repetivel)."
    )
    parser.add_argument(
        "--threshold", type=float, default=1.0, help="pass-rate minimo para o gate (default 1.0)."
    )
    args = parser.parse_args()

    # psycopg async pendura no ProactorEventLoop (default Windows) -> Selector antes do loop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    fixtures = carregar_fixtures(subdirs=args.subdir)
    if not fixtures:
        print("Nenhuma fixture encontrada.", file=sys.stderr)
        raise SystemExit(2)

    avaliacoes = asyncio.run(rodar(fixtures))
    _imprimir(avaliacoes)
    raise SystemExit(gate(avaliacoes, args.threshold))


if __name__ == "__main__":
    main()
