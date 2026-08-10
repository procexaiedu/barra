"""Harness FIEL ao WhatsApp: dirige o grafo real contra um cliente simulado (DeepSeek) que
REAGE ao agente, replicando o estado do DB que a stack de produção geraria.

Por que isto e fiel (e o `replay_agente.py` literal nao era) — 3 divergências corrigidas:
  1. CLIENTE COERENTE: em vez de injetar as falas literais do corpus (que reagiam ao VENDEDOR
     humano e viram non-sequitur contra o agente), um cliente DeepSeek ancorado na persona real
     da thread reage à resposta REAL do agente. Mata a incoerência que induzia o agente a travar.
  2. DEBOUNCE: o webhook agrupa um burst de N mensagens rápidas do cliente em UM turno
     (despacho.py). Aqui cada burst do cliente vira N linhas `direcao='cliente'` ANTES de um único
     ainvoke — o agente vê o conjunto, como no WhatsApp.
  3. FORMA/ORDEM DA JANELA: prod grava 1 linha `direcao='ia'` POR BOLHA (envio.py, via
     chunk_texto) e ordena por uuidv7+created_at distintos. Aqui a resposta da IA passa pelo
     MESMO `chunk_texto` (N linhas) e toda inserção usa `barravips.uuidv7()` + created_at crescente
     — senão, numa única transação, `now()` empata e o ORDER BY cai no uuid4 aleatório (janela
     embaralhada). O graph.ainvoke + ContextAgente + prepare_context já eram idênticos a prod.

§0: gasta crédito DeepSeek (agente + cliente-sim, AUTORIZADO). Seed+ROLLBACK contra prod — nada
commita; não toca WhatsApp/Redis/prod.

Uso (de api/):
  PYTHONPATH=. TEST_DATABASE_URL="$DATABASE_URL" uv run python \
      ../scripts/eval_corpus/replay_agente_fiel.py --out /caminho/fiel.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from evals.e2e.extracao import extrair_perfil_por_ref
from evals.e2e.perfil import ESTADOS_CONDUZIDOS, perfil_para_fixture
from evals.harness import (
    FakeRedis,
    NodesVisitedHandler,
    PoolDeUmaConexao,
    _coletar_tools,
    _metricas_tokens,
    estado_pos_turno,
    habilitar_tracing,
    seedar,
)
from langfuse import Langfuse, get_client
from langgraph.errors import GraphRecursionError
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente._texto_turno import extrair_texto_do_turno
from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.core.llm import criar_chat_deepseek
from barra.core.tracing import langfuse_handler, metadata_trace_turno, resumir_trace_turno
from barra.settings import Settings, get_settings
from barra.workers._chunking import chunk_texto

# FalaCliente (bolhas + encerrou) e prompt_cliente: reuso do simulador A/B fiel à prod.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_deepseek import FalaCliente, prompt_cliente, sanear_fala_cliente

from dados_reais import carregar  # noqa: E402

# Threads REAIS do corpus ("instancia:remote_jid", @lid do cliente) -> PII, fora do git.
REFS: list[str] = carregar("replay_agente_fiel", "REFS")

MAX_TURNOS = 28  # cliente-sim pode encerrar antes; trava de custo/tempo

# Mesmo fuso que prepare_context usa p/ derivar a âncora BRT (prepare_context.py:_FUSO_BR).
_FUSO_BR = ZoneInfo("America/Sao_Paulo")


def _ancora_agora_utc() -> datetime:
    """Âncora de "agora" coerente do turno (clock injection): hoje às REPLAY_AGORA_BRT (default
    09:00) no fuso BR, em aware-UTC. O corpus não expõe timestamp (PerfilCaso só carrega `texto`),
    então uma manhã fixa torna os horários-alvo dos cenários (13h/22h/"agora") FUTUROS e coerentes
    — em vez do current_timestamp de parede (~18h) que faria "13h" virar passado e o LLM flailar."""
    h, _, m = os.environ.get("REPLAY_AGORA_BRT", "09:00").partition(":")
    ancora_br = datetime.now(_FUSO_BR).replace(
        hour=int(h), minute=int(m or 0), second=0, microsecond=0
    )
    return ancora_br.astimezone(UTC)


def _bolhas(texto: str) -> list[str]:
    """Quebra a fala do cliente em bolhas (uma linha = uma mensagem de WhatsApp). Colapsa bolhas
    consecutivas identicas — o corpus as vezes duplica cada linha do turno (artefato de agregacao,
    ex.: 'Oi bom dia\\nOi bom dia\\nAtende casal?\\nAtende casal?'). Tambem desfaz o ' / ' que o
    ClienteLLM as vezes copia da notacao visual do transcript original (extracao._render_transcript
    junta linhas de um turno com ' / ' so p/ exibicao) como se fosse texto literal da fala."""
    texto = re.sub(r"\s+/\s+", "\n", texto)
    out: list[str] = []
    for b in re.split(r"\n+", texto):
        b = b.strip()
        if b and (not out or out[-1] != b):
            out.append(b)
    return out


async def _inserir_bolha(
    conn: AsyncConnection[dict[str, Any]], cen: Any, direcao: str, texto: str, seg_atras: int
) -> None:
    """Insere UMA bolha com uuidv7 (ordenável) + created_at crescente (seg_atras decresce) —
    replica a ordem temporal que prod tem com inserts em transações/tempos distintos."""
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, atendimento_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (barravips.uuidv7(), %s, %s, %s::barravips.direcao_mensagem_enum, 'texto', %s, %s,
                now() - make_interval(secs => %s))
        """,
        (cen.conversa_id, cen.atendimento_id, direcao, texto, f"fiel-{uuid4().hex}", seg_atras),
    )


async def _rodar_turno_fiel(
    conn: AsyncConnection[dict[str, Any]],
    cen: Any,
    bolhas_cliente: list[str],
    graph: Any,
    contador: list[int],
    agora_utc: datetime | None = None,
) -> tuple[str, list[str], dict[str, Any], float]:
    """Debounce (N bolhas do cliente -> 1 ainvoke) + persistência da IA por bolha (chunk_texto).

    `agora_utc` (clock injection): None -> prepare_context lê o current_timestamp do banco
    (relógio de parede, incoerente com cenários matinais); setado -> instante fixo coerente."""
    for b in bolhas_cliente:
        contador[0] += 1
        await _inserir_bolha(conn, cen, "cliente", b, 1000 - contador[0])

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
    # Trace Langfuse (mesmo padrao do rodar_turno do gate): anexa o CallbackHandler + escopa um
    # span por turno com trace-id deterministico, tag `replay_fiel`. No-op se o tracing nao foi
    # ligado (langfuse_handler() None -> sem chaves/`habilitar_tracing`). Sem isto o replay rodava
    # cego pro Langfuse (so o NodesVisitedHandler local), por isso nada subia.
    config: dict[str, Any] = {
        "recursion_limit": int(os.environ.get("REPLAY_RECURSION_LIMIT", "18")),
        "callbacks": [handler],
    }
    span_ctx: AbstractContextManager[Any] = nullcontext()
    lf = langfuse_handler()
    if lf is not None:
        config["callbacks"].append(lf)
        meta = metadata_trace_turno(
            str(cen.modelo_id), str(cen.atendimento_id), str(cen.cliente_id)
        )
        meta["metadata"]["langfuse_tags"] = [*meta["metadata"]["langfuse_tags"], "replay_fiel"]
        config["metadata"] = meta["metadata"]
        config["tags"] = [*meta["tags"], "replay_fiel"]
        trace_id = Langfuse.create_trace_id(seed=ctx.turno_id)
        span_ctx = get_client().start_as_current_observation(
            as_type="span", name="replay_fiel", trace_context={"trace_id": trace_id}
        )
    with span_ctx as span_obj:
        try:
            estado = await graph.ainvoke({"messages": []}, config=config, context=ctx)
        except GraphRecursionError:
            # Backstop (#1): um loop ReAct estourando o recursion_limit (ex.: enviar_midia
            # re-tentando tag vazia) NÃO derruba o batch inteiro do ref (que custa crédito).
            # Trata como turn sem texto e segue — o bound determinístico no enviar_midia já evita
            # o loop de mídia; isto cobre qualquer loop futuro sem mascarar o do agente.
            print(f"[recursion] {cen.atendimento_id} — turn sem texto", file=sys.stderr)
            est = await estado_pos_turno(conn, cen.atendimento_id)
            resumir_trace_turno(span_obj, entrada=bolhas_cliente, resposta="", desfecho=est)
            return "", [], est, 0.0
        mensagens = estado["messages"]
        texto = extrair_texto_do_turno(mensagens)
        nomes, _ = _coletar_tools(mensagens)
        metr = _metricas_tokens(mensagens, get_settings().usd_brl_cotacao)
        est = await estado_pos_turno(conn, cen.atendimento_id)
        # ROOT span autossuficiente (ADR 0019): sem isto input/output do trace nascem nulos e a
        # lista do Langfuse mostra colunas vazias — o desfecho/msg vivem so nas observations.
        resumir_trace_turno(span_obj, entrada=bolhas_cliente, resposta=texto, desfecho=est)

    if texto.strip():
        bolhas_ia, _ = chunk_texto(texto)
        for b in bolhas_ia:
            if b.strip():
                contador[0] += 1
                await _inserir_bolha(conn, cen, "ia", b, 1000 - contador[0])

    return texto, nomes, est, metr.custo_brl


async def _replay_um(dsn: str, ref: str, graph: Any, s: Settings) -> dict[str, Any]:
    conn = await AsyncConnection.connect(dsn, row_factory=dict_row, autocommit=False)
    try:
        perfil = await extrair_perfil_por_ref(conn, ref)
        if perfil is None:
            return {"ref": ref, "erro": "ref sem falas em corpus.turnos"}

        cen = await seedar(conn, perfil_para_fixture(perfil))
        cli = criar_chat_deepseek(s).with_structured_output(FalaCliente, method="function_calling")

        contador = [0]
        hist: list[dict[str, str]] = []
        turnos: list[dict[str, Any]] = []
        custo = 0.0
        pausado_em: int | None = None

        bolhas_c = _bolhas(perfil.abertura)  # turno 0 = abertura REAL do corpus
        hist.append({"lado": "C", "bolhas": "\n".join(bolhas_c)})
        ancora = _ancora_agora_utc()  # clock injection: âncora fixa coerente (manhã) por run

        for i in range(MAX_TURNOS):
            texto, tools, est, c = await _rodar_turno_fiel(
                conn, cen, bolhas_c, graph, contador, agora_utc=ancora
            )
            custo += c
            ia_p = bool(est.get("ia_pausada"))
            if ia_p and pausado_em is None:
                pausado_em = i
            turnos.append(
                {
                    "i": i,
                    "cliente": "\n".join(bolhas_c),
                    "agente": texto,
                    "tools": tools,
                    "estado": est.get("estado"),
                    "pix_status": est.get("pix_status"),
                    "ia_pausada": ia_p,
                }
            )
            hist.append({"lado": "M", "bolhas": texto})

            if est.get("estado") in ESTADOS_CONDUZIDOS or ia_p:
                break

            try:
                fala = await cli.ainvoke(prompt_cliente(perfil.persona, hist))
            except Exception:
                break
            if fala.encerrou or not fala.bolhas.strip():
                break
            bolhas_c = sanear_fala_cliente(_bolhas(fala.bolhas), perfil.linhas_vendedor)
            if not bolhas_c:
                break
            hist.append({"lado": "C", "bolhas": "\n".join(bolhas_c)})

        return {
            "ref": ref,
            "perfil_nome": perfil.nome,
            "tipo_esperado": perfil.tipo_esperado,
            "desfecho_real": perfil.desfecho_real,
            "n_turnos": len(turnos),
            "pausado_em": pausado_em,
            "estado_final": turnos[-1]["estado"] if turnos else None,
            "custo_brl": round(custo, 6),
            "turnos": turnos,
        }
    except Exception as exc:
        return {"ref": ref, "erro": f"{type(exc).__name__}: {exc}"}
    finally:
        await conn.rollback()
        await conn.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--conc", type=int, default=8)
    ap.add_argument(
        "--refs",
        help="CSV de refs a rodar (subconjunto de REFS; default: todas). Formato 'ebNN:<id>@lid'.",
    )
    args = ap.parse_args()

    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("defina TEST_DATABASE_URL (ou DATABASE_URL)")

    ligou = habilitar_tracing()  # liga o trace Langfuse de prod (ADR 0019); no-op sem as LANGFUSE_*
    print(f"langfuse: {'ligado' if ligou else 'desligado (sem LANGFUSE_*)'}", file=sys.stderr)
    s = get_settings()
    graph = build_graph()
    sem = asyncio.Semaphore(args.conc)

    async def _tarefa(ref: str) -> dict[str, Any]:
        async with sem:
            print(f"[start] {ref}", file=sys.stderr)
            res = await _replay_um(dsn, ref, graph, s)
            tag = res.get("erro") or (
                f"{res.get('n_turnos')}t -> {res.get('estado_final')} R${res.get('custo_brl')}"
            )
            print(f"[done ] {ref} — {tag}", file=sys.stderr)
            return res

    refs = [r.strip() for r in args.refs.split(",") if r.strip()] if args.refs else REFS
    resultados = await asyncio.gather(*(_tarefa(r) for r in refs))
    total = sum(r.get("custo_brl", 0.0) for r in resultados)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(
            {"resultados": resultados, "custo_total_brl": round(total, 6)},
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nOK — {len(resultados)} cenários, custo R${total:.4f} -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
