"""Replay puro: roda o GRAFO REAL contra as falas reais do cliente (corpus), por ref.

Para cada `ref` ("instancia:remote_jid") das conversas-chave, semeia um caso novo
(`Novo`) com a modelo sintetica (mesma do e2e), e alimenta as falas REAIS do cliente
turno-a-turno via `rodar_turno` — o mesmo caminho de producao (DeepSeek V4 Flash, factory
`_criar_chat_principal`, grafo sem checkpointer). Captura por turno: texto do agente,
tools chamadas e estado pos-turno ({estado, pix_status, ia_pausada}) — a inspecao interna.

Replay PURO: alimenta TODAS as falas do corpus, mesmo se o agente divergir do humano. Onde
o agente pausa (handoff/ia_pausada) o turno seguinte ja chega com a IA muda — sinal honesto.

Saida: JSON com a trajetoria de cada cenario. Render do HTML fica em `render_replay_html.py`.

⚠️ §0: gasta credito DeepSeek real (AUTORIZADO). Seed dentro de transacao com ROLLBACK
SEMPRE contra prod (mesmo banco do corpus) — NADA commita; nao toca WhatsApp/Redis/prod.

Uso (a partir de api/):
  TEST_DATABASE_URL="$DATABASE_URL" uv run python ../scripts/eval_corpus/replay_agente.py \
      --out /caminho/replay_resultado.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.graph import build_graph
from evals.e2e.extracao import extrair_perfil_por_ref
from evals.e2e.perfil import perfil_para_fixture
from evals.e2e.persistencia import gravar_resposta_ia
from evals.harness import rodar_turno, seedar

from dados_reais import carregar

# Os 8 cenarios-chave (ordem = conversas_chave_vendedor.html, c0..c7). A lista aponta para
# threads REAIS ("instancia:remote_jid" com o @lid do cliente) -> PII, fica fora do git
# (`_dados_reais/`, ver dados_reais.py).
REFS: list[str] = carregar("replay_agente", "REFS")

# Trava de seguranca: nunca rodar mais que isto de turnos por cenario (alguns tem 70+ falas;
# apos a IA pausar, o resto e ruido). Mantem o custo e o tempo sob controle.
MAX_TURNOS = 40


async def _replay_um(dsn: str, ref: str, graph: Any) -> dict[str, Any]:
    """Semeia um caso por `ref`, alimenta as falas reais do cliente e coleta a trajetoria.

    ROLLBACK garantido no finally — a transacao inteira (seed + N inserts de mensagem) some.
    """
    conn = await AsyncConnection.connect(dsn, row_factory=dict_row, autocommit=False)
    try:
        perfil = await extrair_perfil_por_ref(conn, ref)
        if perfil is None:
            return {"ref": ref, "erro": "ref nao encontrado em corpus.turnos / sem falas"}

        cen = await seedar(conn, perfil_para_fixture(perfil))
        falas = [perfil.abertura, *perfil.roteiro_cliente][:MAX_TURNOS]

        turnos: list[dict[str, Any]] = []
        custo = 0.0
        pausado_em: int | None = None
        for i, fala in enumerate(falas):
            r = await rodar_turno(conn, cen, turno_cliente=fala)
            # FIDELIDADE AO WHATSAPP: em prod o worker `enviar_turno` grava a bolha da IA em
            # `mensagens` (direcao='ia'), que vira histórico do próximo turno. No harness o worker
            # é no-op (FakeRedis) — sem isto o agente roda AMNÉSICO (re-cumprimenta/re-cota a cada
            # turno). Mesma linha que o runner e2e usa (runner.py:114). Pula texto vazio (pausa).
            await gravar_resposta_ia(conn, cen, r.texto)
            custo += r.metricas.custo_brl
            ia_pausada = bool(r.estado_final.get("ia_pausada"))
            if ia_pausada and pausado_em is None:
                pausado_em = i
            turnos.append(
                {
                    "i": i,
                    "cliente": fala,
                    "agente": r.texto,
                    "tools": r.tool_calls,
                    "estado": r.estado_final.get("estado"),
                    "pix_status": r.estado_final.get("pix_status"),
                    "ia_pausada": ia_pausada,
                }
            )

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
    except Exception as exc:  # noqa: BLE001 — um cenario que quebra nao derruba os outros
        return {"ref": ref, "erro": f"{type(exc).__name__}: {exc}"}
    finally:
        await conn.rollback()
        await conn.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="caminho do JSON de saida")
    ap.add_argument("--conc", type=int, default=8, help="cenarios concorrentes")
    args = ap.parse_args()

    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("defina TEST_DATABASE_URL (ou DATABASE_URL) — aponta pro banco do corpus")

    graph = build_graph()  # compilado uma vez; stateless (le tudo do ctx/conn por invoke)
    sem = asyncio.Semaphore(args.conc)

    async def _tarefa(ref: str) -> dict[str, Any]:
        async with sem:
            print(f"[start] {ref}", file=sys.stderr)
            res = await _replay_um(dsn, ref, graph)
            tag = res.get("erro") or f"{res.get('n_turnos')} turnos, R${res.get('custo_brl')}"
            print(f"[done ] {ref} — {tag}", file=sys.stderr)
            return res

    resultados = await asyncio.gather(*(_tarefa(r) for r in REFS))

    total = sum(r.get("custo_brl", 0.0) for r in resultados)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"resultados": resultados, "custo_total_brl": round(total, 6)}, fh, ensure_ascii=False, indent=2)
    print(f"\nOK — {len(resultados)} cenarios, custo total R${total:.4f} -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
