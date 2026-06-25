"""Sessao e2e turn-by-turn: o CLIENTE e o Claude Code, nao um 2o LLM.

Processo de longa duracao (servidor HTTP local). No startup: conecta o DB, extrai UM PerfilCaso
por `--ref`, seeda numa transacao ABERTA e constroi o graph. Cada POST /turno roda UM turno do
agente real (1 ainvoke) e devolve a resposta+estado, SINCRONO. Assim so o AGENTE usa a API; o
cliente e o Claude Code, que le a resposta e decide a proxima fala (ancorado nas falas reais do
corpus, em GET /perfil). No /fim: ROLLBACK + shutdown — nada commita em prod (§0).

Endpoints:
  GET  /perfil  -> {ref, desfecho_real, label_bin, tipo_esperado, abertura, falas_reais, persona}
  POST /turno   {"texto": "..."} -> {i, texto, estado, ia_pausada, conduziu, tool_calls, custo_brl}
  POST /fim     -> {n_turnos, custo_total_brl} e encerra o processo (rollback)

Uso:
  # validacao SEM credito (chat mockado):
  TEST_DATABASE_URL=... uv run python -m evals.e2e.sessao --ref eb04:..@lid --fake --port 8765
  # corrida REAL (gasta credito do agente, §0 — exige autorizacao):
  E2E_AUTORIZADO=1 TEST_DATABASE_URL=... uv run python -m evals.e2e.sessao --ref eb04:..@lid --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from evals.e2e.avaliacao import (
    avaliar_e2e,
    flush_langfuse,
    gravar_veredito,
    pontuar_no_langfuse,
)
from evals.e2e.extracao import extrair_perfil_por_ref
from evals.e2e.perfil import ESTADOS_CONDUZIDOS, PerfilCaso, perfil_para_fixture
from evals.e2e.persistencia import gravar_resposta_ia, seed_caso_persistente
from evals.e2e.runner import ResultadoE2E
from evals.harness import Cenario, ResultadoTurno, habilitar_tracing, rodar_turno, seedar

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- chat fake (modo --fake): conduz um caso interno, 1 extracao + 1 bolha por turno ---------


class _BoundFake:
    def __init__(self, chat: _ChatFakeInterno, *, forcado: bool) -> None:
        self._chat = chat
        self._forcado = forcado

    async def ainvoke(self, _messages: Any) -> Any:

        if self._forcado:
            return self._chat._extracao()
        self._chat.n += 1
        return self._chat._extracao() if self._chat.n % 2 == 1 else self._chat._bolha()


class _ChatFakeInterno:
    """Avanca qualquer mensagem do cliente: extracao interna completa + bolha. Sobe o estado
    Novo->Triagem->Qualificado->Aguardando_confirmacao (1 degrau/turno). So para validar o
    encanamento da sessao SEM credito."""

    model = "fake-e2e"

    def __init__(self) -> None:
        from datetime import date, timedelta

        self.n = 0
        amanha = date.today() + timedelta(days=1)
        self._args = {
            "proxima_acao_esperada": "conduzir o agendamento interno",
            "intencao": "agendamento",
            "tipo_atendimento": "interno",
            "horario_desejado": "15:00",
            "data_desejada": amanha.isoformat(),
            "duracao_horas": 1,
            "cotacao_apresentada": True,
        }

    def _extracao(self) -> Any:
        from langchain_core.messages import AIMessage

        return AIMessage(
            content="",
            usage_metadata=_USAGE,
            response_metadata={"stop_reason": "tool_use"},
            tool_calls=[
                {
                    "name": "registrar_extracao",
                    "args": self._args,
                    "id": uuid4().hex,
                    "type": "tool_call",
                }
            ],
        )

    def _bolha(self) -> Any:
        from langchain_core.messages import AIMessage

        return AIMessage(
            content="combinado amor 😘",
            usage_metadata=_USAGE,
            response_metadata={"stop_reason": "end_turn"},
            tool_calls=[],
        )

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _BoundFake:
        return _BoundFake(self, forcado=tool_choice is not None)


def _graph_fake() -> Any:
    """build_graph() com o chat real trocado pelo fake (restaura o factory depois do build)."""
    from barra.agente import graph as gm

    fake = _ChatFakeInterno()
    orig = gm.criar_chat_deepseek  # type: ignore[attr-defined]
    gm.criar_chat_deepseek = lambda *a, **k: fake  # type: ignore[attr-defined,assignment]
    try:
        return gm.build_graph()
    finally:
        gm.criar_chat_deepseek = orig  # type: ignore[attr-defined]


# --- estado da sessao ------------------------------------------------------------------------


class Sessao:
    def __init__(
        self,
        conn: AsyncConnection[dict[str, Any]],
        graph: Any,
        cen: Cenario,
        perfil: PerfilCaso,
        *,
        persistir: bool,
    ) -> None:
        self.conn = conn
        self.graph = graph
        self.cen = cen
        self.perfil = perfil
        self.persistir = persistir  # True: commita em barravips (painel); False: ROLLBACK no /fim
        self.i = 0
        self.custo = 0.0
        # Acumulados p/ o veredito no /fim (mesma estrutura que runner.ResultadoE2E consome).
        self.turnos: list[ResultadoTurno] = []
        self.trajetoria: list[dict[str, Any]] = []


async def abrir_sessao(ref: str, *, fake: bool, persistir: bool) -> Sessao:
    conn = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    perfil = await extrair_perfil_por_ref(conn, ref)
    if perfil is None:
        await conn.close()
        raise SystemExit(f"perfil nao encontrado (ou sem falas) para ref {ref!r}")
    # persistir: caso sob a modelo sandbox, conversa origem='e2e', COMMIT (Fernando avalia no
    # painel). Senao: seed efemero com ROLLBACK no /fim (nada toca prod).
    if persistir:
        cen = await seed_caso_persistente(conn, perfil)
    else:
        cen = await seedar(conn, perfil_para_fixture(perfil))
    graph = _graph_fake() if fake else _build_graph_real()
    return Sessao(conn, graph, cen, perfil, persistir=persistir)


def _build_graph_real() -> Any:
    from barra.agente.graph import build_graph

    return build_graph()


# --- handlers HTTP ---------------------------------------------------------------------------


async def _h_perfil(request: Request) -> JSONResponse:
    p: PerfilCaso = request.app.state.sessao.perfil
    return JSONResponse(
        {
            "ref": p.thread_ref,
            "desfecho_real": p.desfecho_real,
            "label_bin": p.label_bin,
            "tipo_esperado": p.tipo_esperado,
            "abertura": p.abertura,
            "falas_reais": [p.abertura, *p.roteiro_cliente],
            "persona": p.persona,
        }
    )


async def _h_turno(request: Request) -> JSONResponse:
    s: Sessao = request.app.state.sessao
    body = await request.json()
    texto = str(body.get("texto", "")).strip()
    if not texto:
        return JSONResponse({"erro": "campo 'texto' vazio"}, status_code=400)

    r = await rodar_turno(
        s.conn, s.cen, turno_cliente=texto, graph=s.graph, trace_tag="e2e", escopar_trace=True
    )
    s.i += 1
    s.custo += r.metricas.custo_brl
    s.turnos.append(r)
    s.trajetoria.append(r.estado_final)
    estado = (r.estado_final or {}).get("estado")
    if s.persistir:
        # grava a bolha da IA (o worker de envio nao roda no harness) e COMMITA o turno inteiro
        # (UPDATEs do grafo + msg do cliente + bolha da IA) -> aparece no painel /observabilidade.
        await gravar_resposta_ia(s.conn, s.cen, r.texto)
        await s.conn.commit()
    else:
        # Janela FIEL mesmo sem persistir: grava a bolha da IA na transacao efemera (sem commit, o
        # /fim da ROLLBACK) -> o proximo /turno a ve e o agente nao re-cumprimenta/re-cota amnesico.
        await gravar_resposta_ia(s.conn, s.cen, r.texto)
    return JSONResponse(
        {
            "i": s.i,
            "texto": r.texto,
            "estado": estado,
            "ia_pausada": bool((r.estado_final or {}).get("ia_pausada")),
            "conduziu": estado in ESTADOS_CONDUZIDOS,
            "tool_calls": r.tool_calls,
            "custo_brl": round(r.metricas.custo_brl, 6),
        }
    )


def _inferir_desfecho(s: Sessao, override: str | None) -> str:
    """Como a conducao parou. O cliente (Claude Code) pode informar `desfecho` no /fim
    (cliente_sumiu/max_turnos); senao inferimos do ultimo estado/pausa."""
    if not s.turnos:
        return "sem_turnos"
    ultimo = s.turnos[-1].estado_final or {}
    if ultimo.get("estado") in ESTADOS_CONDUZIDOS:
        return "conduziu"
    if ultimo.get("ia_pausada"):
        return "pausou_handoff"
    return override or "encerrado"


def _veredito_da_sessao(s: Sessao, override: str | None) -> Any:
    """Monta o ResultadoE2E acumulado e devolve o VeredictoE2E (puro, sem tocar o DB)."""
    res = ResultadoE2E(
        perfil_nome=s.perfil.nome,
        trajetoria=s.trajetoria,
        turnos=s.turnos,
        desfecho_conducao=_inferir_desfecho(s, override),
        estado_final=(s.turnos[-1].estado_final or {}).get("estado") if s.turnos else None,
        desfecho_real=s.perfil.desfecho_real,
    )
    return avaliar_e2e(res, s.perfil)


async def _h_fim(request: Request) -> JSONResponse:
    s: Sessao = request.app.state.sessao
    body = await request.json() if await request.body() else {}
    veredito = _veredito_da_sessao(s, str(body.get("desfecho") or "") or None)

    # Veredito como score no trace Langfuse do ultimo turno (EVAL-11 online) + flush da entrega.
    await pontuar_no_langfuse(s.turnos[-1].trace_id if s.turnos else None, veredito)
    await flush_langfuse()

    # Veredito em corpus.eval_e2e: conn AUTOCOMMIT separada (sobrevive ao rollback do seed). So com
    # E2E_RUN_TAG (intencao explicita) e a ddl.sql aplicada — ambos §0 (escrita em prod).
    run_tag = os.environ.get("E2E_RUN_TAG")
    if run_tag:
        conn_eval = await AsyncConnection.connect(
            os.environ["TEST_DATABASE_URL"], autocommit=True, row_factory=dict_row
        )
        try:
            await gravar_veredito(
                conn_eval,
                veredito,
                run_tag=run_tag,
                thread_ref=s.perfil.thread_ref,
                desfecho_real=s.perfil.desfecho_real,
                trajetoria=s.trajetoria,
                eixo=s.perfil.eixo_comportamento,
            )
        finally:
            await conn_eval.close()

    if not s.conn.closed:
        if s.persistir:
            await s.conn.commit()  # turnos ja commitados; garante o estado final
        else:
            await s.conn.rollback()  # nada commita (§0)
        await s.conn.close()
    request.app.state.server.should_exit = True
    return JSONResponse(
        {
            "n_turnos": s.i,
            "custo_total_brl": round(s.custo, 6),
            "conduziu": veredito.conduziu,
            "desfecho_conducao": veredito.desfecho_conducao,
            "estado_final": veredito.estado_final,
            "bate_desfecho_real": veredito.bate_desfecho_real,
            "violacoes": veredito.violacoes,
            "veredito_ok": veredito.ok,
            "gravado_run_tag": run_tag,
            "encerrado": True,
        }
    )


def _gravar_perfil(io_dir: str, perfil: PerfilCaso) -> None:
    """Grava o perfil (falas reais + persona) para o Claude Code se ancorar como cliente."""
    io = Path(io_dir)
    io.mkdir(parents=True, exist_ok=True)
    (io / "perfil.json").write_text(
        json.dumps(
            {
                "ref": perfil.thread_ref,
                "desfecho_real": perfil.desfecho_real,
                "label_bin": perfil.label_bin,
                "tipo_esperado": perfil.tipo_esperado,
                "falas_reais": [perfil.abertura, *perfil.roteiro_cliente],
                "persona": perfil.persona,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def _serve(args: argparse.Namespace) -> None:
    ligou = habilitar_tracing()  # liga o trace Langfuse de prod (ADR 0019); no-op sem as envs
    print(f"langfuse: {'ligado' if ligou else 'desligado (sem LANGFUSE_*)'}")
    sessao = await abrir_sessao(args.ref, fake=args.fake, persistir=args.persistir)
    app = Starlette(
        routes=[
            Route("/perfil", _h_perfil, methods=["GET"]),
            Route("/turno", _h_turno, methods=["POST"]),
            Route("/fim", _h_fim, methods=["POST"]),
        ]
    )
    app.state.sessao = sessao
    if args.io:
        _gravar_perfil(args.io, sessao.perfil)

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    server = uvicorn.Server(config)
    app.state.server = server
    try:
        await server.serve()
    finally:
        if not sessao.conn.closed:
            # persistir: turnos ja foram commitados por /turno; aqui so encerra. Senao: rollback
            # de garantia se o cliente nao chamou /fim (nada toca prod).
            if not sessao.persistir:
                await sessao.conn.rollback()
            await sessao.conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Sessao e2e turn-by-turn (cliente = Claude Code).")
    ap.add_argument("--ref", required=True, help='thread do corpus: "instancia:remote_jid"')
    ap.add_argument("--io", help="dir para gravar perfil.json (ancoragem do cliente)")
    ap.add_argument("--fake", action="store_true", help="chat mockado: valida sem credito")
    ap.add_argument(
        "--persistir",
        action="store_true",
        help="COMMITA em barravips (modelo sandbox, origem=e2e) p/ o Fernando avaliar no painel",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Defina TEST_DATABASE_URL (prod self-hosted).")
    autorizado = os.environ.get("E2E_AUTORIZADO") == "1"
    # --persistir ESCREVE em prod (commit), mesmo com --fake -> exige autorizacao (§0).
    if args.persistir and not autorizado:
        raise SystemExit(
            "--persistir COMMITA conversas e2e em barravips (§0). Defina E2E_AUTORIZADO=1 apos a "
            "autorizacao do dev (e aplique a migration *_conversas_origem_e2e.sql)."
        )
    # corrida REAL (sem --fake) gasta credito do agente -> exige autorizacao (§0).
    if not args.fake and not autorizado:
        raise SystemExit(
            "Corrida e2e REAL gasta credito do agente (§0). Defina E2E_AUTORIZADO=1 apos a "
            "autorizacao do dev, ou use --fake para validar o encanamento sem credito."
        )
    asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
