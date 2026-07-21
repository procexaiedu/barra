"""Runner em MASSA dos cenarios sinteticos de funcionalidade (Bloco D do plano).

Roda cada `CenarioFunc` com `ClienteRoteirizado` (Python, sem sub-agente): seed -> conducao
multi-turn -> pos-evento determinístico (foto de portaria) -> veredito. Deduplica por `run_tag`
(consulta `corpus.eval_e2e`: o que ja rodou naquele tag e pulado) e agrega cobertura.

`k` execucoes por cenario (default 1; pass^k pronto mas desligado por orcamento — decisao do dev).

⚠️ §0: com o graph REAL gasta credito do agente (1 ainvoke/turno) e exige TEST_DATABASE_URL.
Gravar em `corpus.eval_e2e` (run_tag setado) escreve em prod e exige a ddl.sql aplicada. A
validacao offline injeta um graph fake + ROLLBACK — ver tests/agente/test_e2e_massa.py.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.tracing import garantir_dataset, linkar_item_run, upsert_item_dataset
from evals.e2e.avaliacao import (
    avaliar_e2e,
    flush_langfuse,
    gravar_veredito,
    pontuar_no_langfuse,
)
from evals.e2e.cenarios import CenarioFunc, cenarios
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.persistencia import gravar_resposta_ia, seed_caso_persistente
from evals.e2e.runner import ResultadoE2E, rodar_e2e
from evals.harness import Cenario, ResultadoTurno, estado_pos_turno, habilitar_tracing

# Dataset Langfuse dos cenarios e2e: cada perfil e um item estavel (id = perfil.nome); cada corrida
# (`--dataset-run`) vira um dataset-RUN que linka os itens aos traces daquela execucao (ADR 0019).
DATASET_E2E = "e2e_conducao"


async def _disparar_foto_portaria(conn: AsyncConnection[dict[str, Any]], cen: Cenario) -> None:
    """Evento determinístico: insere a 'imagem' e chama o handoff de domínio (sem worker/vision).

    No P0 qualquer imagem em Aguardando_confirmacao interno e foto de portaria (CONTEXT.md). Reusa
    `handoff_foto_portaria_ia` (mesmo caminho de workers/media.py). `media_object_key=None`.
    """
    from barra.dominio.atendimentos.service import handoff_foto_portaria_ia

    msg_id = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, %s, 'cliente', 'texto', %s, %s)
        """,
        (msg_id, cen.conversa_id, "[foto portaria]", f"e2e-foto-{uuid4().hex}"),
    )
    await handoff_foto_portaria_ia(
        conn, atendimento_id=cen.atendimento_id, mensagem_id=msg_id, media_object_key=None
    )


# BUG #1 (falsa-confirmacao de agenda): a IA nunca pode confirmar no texto um horario que o gate de
# Disponibilidade recusou. `_CONFIRMA` = tokens de fechamento; `_REANCORA` = a conduta correta
# (revela a volta / oferece outro horario). Detecta por BOLHA: confirmacao + o horario rejeitado SEM
# reancoragem na mesma bolha. Regex de alta precisao — o sinal so e significativo na corrida REAL.
_CONFIRMA_AGENDA = re.compile(
    r"fechad[oa]|combinad[oa]|marcad[oa]|confirmad[oa]|te espero|te aguardo|pode vir|"
    r"nos vemos|te esperando",
    re.I,
)
_REANCORA_AGENDA = re.compile(
    r"j[áa] parei|por hoje|amanh|mais cedo|mais tarde|n[ãa]o consigo|n[ãa]o rola|n[ãa]o d[áa]|"
    r"outro hor[áa]rio|consigo at[ée]|s[óo] at[ée]|fora do",
    re.I,
)


def _confirmou_horario_fora(res: ResultadoE2E, hora: str) -> bool:
    """True se a IA confirmou no texto um horario que o gate de Disponibilidade recusou — a
    falsa-confirmacao do BUG #1 (desync chat<->estado). Por bolha: token de confirmacao + o horario
    rejeitado, SEM reancoragem (a conduta certa revela a volta e oferece outro horario)."""
    alvo = re.compile(rf"\b{re.escape(hora)}\s*h?\b")
    for turno in res.turnos:
        for bolha in re.split(r"\n\s*\n", turno.texto or ""):
            if (
                alvo.search(bolha)
                and _CONFIRMA_AGENDA.search(bolha)
                and not _REANCORA_AGENDA.search(bolha)
            ):
                return True
    return False


# Rotulos de tipo (interno/externo/remoto) sao vocabulario de sistema — a IA nunca os diz ao
# cliente (regras.md.j2 <nucleo>). Duracao maior = o upsell por sinal de tempo livre (<sobe_o_ticket>).
_RE_JARGAO = re.compile(r"\b(interno|externo|remoto)\b", re.I)
_RE_DURACAO_MAIOR = re.compile(r"\b2\s*h(oras?)?\b|pernoite|noite (toda|inteira)", re.I)


def _vazou_jargao(res: ResultadoE2E) -> bool:
    """True se alguma bolha da IA usou os rotulos de tipo (interno/externo/remoto) ao cliente."""
    return any(_RE_JARGAO.search(t.texto or "") for t in res.turnos)


def _propos_duracao_maior(res: ResultadoE2E) -> bool:
    """True se a IA propos uma duracao maior (2h/pernoite/noite toda) em algum turno."""
    return any(_RE_DURACAO_MAIOR.search(t.texto or "") for t in res.turnos)


def _avaliar_cenario(cf: CenarioFunc, res: ResultadoE2E) -> dict[str, Any]:
    """Checa as expectativas do cenario sobre os turnos (so significativo com o agente REAL)."""
    tools = [t for turno in res.turnos for t in turno.tool_calls]
    pediu_pix = "pedir_pix_deslocamento" in tools
    aval: dict[str, Any] = {"tools": sorted(set(tools))}
    if cf.tool_esperada is not None:
        aval["tool_esperada_ok"] = cf.tool_esperada in tools
    if cf.estado_esperado is not None:
        aval["estado_esperado_ok"] = res.estado_final == cf.estado_esperado
    if cf.nao_deve_pedir_pix:
        aval["nao_pediu_pix_ok"] = not pediu_pix
    if cf.nao_deve_escalar:
        aval["nao_escalou_ok"] = "escalar" not in tools
    if cf.hora_fora_disponibilidade is not None:
        aval["nao_confirmou_fora_ok"] = not _confirmou_horario_fora(
            res, cf.hora_fora_disponibilidade
        )
    if cf.nao_deve_vazar_jargao:
        aval["sem_jargao_ok"] = not _vazou_jargao(res)
    if cf.deve_propor_duracao_maior:
        aval["propos_maior_ok"] = _propos_duracao_maior(res)
    return aval


async def _persistir_turno(
    conn: AsyncConnection[dict[str, Any]], cen: Cenario, r: ResultadoTurno
) -> None:
    """Hook pos-turno (modo --persistir): grava a bolha da IA e COMMITA -> aparece no painel."""
    await gravar_resposta_ia(conn, cen, r.texto)
    await conn.commit()


async def rodar_massa(
    conn: AsyncConnection[dict[str, Any]],
    graph: Any,
    *,
    k: int = 1,
    run_tag: str | None = None,
    conn_eval: AsyncConnection[dict[str, Any]] | None = None,
    max_turnos: int = 10,
    persistir: bool = False,
    dataset_run: str | None = None,
) -> list[dict[str, Any]]:
    """Roda os cenarios `k` vezes cada. `conn` seeda/conduz (ROLLBACK do caller, ou COMMIT por turno
    quando `persistir`); `conn_eval` (AUTOCOMMIT separada) recebe o veredito quando `run_tag` setado.

    `persistir`: cada cenario vira uma conversa `origem='e2e'` sob a modelo sandbox (painel
    /observabilidade). O trace Langfuse + score (`escopar_trace`) ligam sozinhos se `setup_langfuse`
    rodou no startup; sem handler, sao no-op.

    `dataset_run`: nome da corrida no dataset Langfuse `e2e_conducao`. Setado -> cada cenario vira um
    item (id=perfil.nome) e o trace do ultimo turno e linkado a esse run (Fase 5). Best-effort/no-op
    sem handler (tracing off)."""
    if dataset_run:
        garantir_dataset(DATASET_E2E)
    feitos: set[str] = set()
    if run_tag and conn_eval is not None:
        cur = await conn_eval.execute(
            "SELECT perfil_nome FROM corpus.eval_e2e WHERE run_tag = %s", (run_tag,)
        )
        feitos = {r["perfil_nome"] for r in await cur.fetchall()}

    resultados: list[dict[str, Any]] = []
    for cf in cenarios():
        if cf.perfil.nome in feitos:
            resultados.append({"cenario": cf.nome, "pulado": "ja_testado"})
            continue
        for _ in range(k):
            cen = await seed_caso_persistente(conn, cf.perfil) if persistir else None
            res = await rodar_e2e(
                conn,
                cf.perfil,
                ClienteRoteirizado(cf.perfil.roteiro_cliente),
                graph=graph,
                max_turnos=max_turnos,
                cen=cen,
                pos_turno=_persistir_turno if persistir else None,
                escopar_trace=True,
            )
            if cf.pos_evento == "foto_portaria" and res.cenario is not None:
                await _disparar_foto_portaria(conn, res.cenario)
                if persistir:
                    await conn.commit()
                est = await estado_pos_turno(conn, res.cenario.atendimento_id)
                res.estado_final = est.get("estado")
                res.trajetoria.append(est)
            veredito = avaliar_e2e(res, cf.perfil)
            aval = _avaliar_cenario(cf, res)
            trace_id = res.turnos[-1].trace_id if res.turnos else None
            await pontuar_no_langfuse(trace_id, veredito)
            if dataset_run:
                # Item estavel por perfil; o trace (ja pontuado pelo judge) vira um item DESTE run.
                upsert_item_dataset(
                    DATASET_E2E, cf.perfil.nome, {"eixo": cf.perfil.eixo_comportamento}
                )
                await asyncio.to_thread(
                    linkar_item_run, DATASET_E2E, cf.perfil.nome, dataset_run, trace_id
                )
            if run_tag and conn_eval is not None:
                await gravar_veredito(
                    conn_eval,
                    veredito,
                    run_tag=run_tag,
                    thread_ref=None,
                    desfecho_real=None,
                    trajetoria=res.trajetoria,
                    eixo=cf.perfil.eixo_comportamento,
                )
            resultados.append(
                {
                    "cenario": cf.nome,
                    "descricao": cf.descricao,
                    "estado_final": res.estado_final,
                    "desfecho_conducao": res.desfecho_conducao,
                    "violacoes": veredito.violacoes,
                    "custo_brl": round(res.custo_brl, 6),
                    "avaliacao": aval,
                }
            )
    return resultados


def _resumo(resultados: list[dict[str, Any]]) -> str:
    linhas = ["", "=== Cobertura de funcionalidades (cenarios sinteticos) ==="]
    custo = 0.0
    for r in resultados:
        if r.get("pulado"):
            linhas.append(f"  - {r['cenario']:22} PULADO ({r['pulado']})")
            continue
        custo += float(r.get("custo_brl", 0) or 0)
        flags = r.get("avaliacao", {})
        checks = " ".join(f"{k}={v}" for k, v in flags.items() if k.endswith("_ok"))
        viol = f" ⚠ {len(r['violacoes'])} violacoes" if r.get("violacoes") else ""
        linhas.append(f"  - {r['cenario']:22} estado={r.get('estado_final')!s:22} {checks}{viol}")
    linhas.append(f"  custo total: R$ {custo:.4f}")
    return "\n".join(linhas)


async def _main(args: argparse.Namespace) -> None:
    from barra.agente.graph import build_graph
    from evals.e2e.sessao import _graph_fake

    ligou = habilitar_tracing()  # liga o trace Langfuse de prod (ADR 0019); no-op sem as envs
    print(f"langfuse: {'ligado' if ligou else 'desligado (sem LANGFUSE_*)'}")
    graph = _graph_fake() if args.fake else build_graph()

    conn = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    conn_eval: AsyncConnection[dict[str, Any]] | None = None
    if args.run_tag:
        conn_eval = await AsyncConnection.connect(
            os.environ["TEST_DATABASE_URL"], autocommit=True, row_factory=dict_row
        )
    try:
        resultados = await rodar_massa(
            conn,
            graph,
            k=args.k,
            run_tag=args.run_tag,
            conn_eval=conn_eval,
            persistir=args.persistir,
            dataset_run=args.dataset_run,
        )
    finally:
        if not args.persistir:
            await conn.rollback()  # seed efemero nunca commita (§0); veredito vai pela conn_eval
        await conn.close()
        if conn_eval is not None:
            await conn_eval.close()
        await flush_langfuse()  # garante a entrega dos traces/scores no processo curto
    print(_resumo(resultados))


def main() -> None:
    ap = argparse.ArgumentParser(description="Runner em massa dos cenarios sinteticos e2e.")
    ap.add_argument("--k", type=int, default=1, help="execucoes por cenario (pass^k; default 1)")
    ap.add_argument("--run-tag", help="grava vereditos em corpus.eval_e2e sob este tag (§0)")
    ap.add_argument(
        "--persistir",
        action="store_true",
        help="COMMITA cada cenario em barravips (modelo sandbox, origem=e2e) p/ o painel (§0)",
    )
    ap.add_argument(
        "--fake", action="store_true", help="chat mockado: valida o encanamento sem credito"
    )
    ap.add_argument(
        "--dataset-run",
        help="vincula cada cenario ao dataset Langfuse e2e_conducao sob este nome de run (Fase 5)",
    )
    args = ap.parse_args()
    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Defina TEST_DATABASE_URL (prod self-hosted).")
    autorizado = os.environ.get("E2E_AUTORIZADO") == "1"
    # --persistir COMMITA em prod (mesmo com --fake) e a corrida REAL gasta credito -> §0.
    if args.persistir and not autorizado:
        raise SystemExit(
            "--persistir COMMITA conversas e2e em barravips (§0). Defina E2E_AUTORIZADO=1 apos a "
            "autorizacao do dev (e aplique a migration *_conversas_origem_e2e.sql)."
        )
    if not args.fake and not autorizado:
        raise SystemExit(
            "Corrida em massa REAL gasta credito do agente (§0). Defina E2E_AUTORIZADO=1 apos a "
            "autorizacao do dev, ou use --fake para validar o encanamento sem credito."
        )
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
