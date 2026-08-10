"""Harness ADVERSARIAL: agente real x cliente-LLM com personas HARD (NAO reencena o corpus).

Mede o que o `conversas_chave` (espelho de fidelidade, mesmo cliente cooperativo) NAO mede: segurar
o Piso de desconto, conceder UM Desconto de fechamento na objecao, sobreviver a desconfianca de
golpe, conduzir o pickup (externo sem Pix, ADR 0020). O cliente-LLM aqui NAO copia o corpus — ele
encarna uma persona dificil e pressiona o agente de verdade.

Reusa a maquinaria FIEL do terminal (mesmo `_rodar_turno_fiel`, debounce, clock injetavel, cauda
deterministica `_cravar_terminal`); so troca o seed (modelo sintetica Manu, sem corpus) e a fonte do
cliente (persona de `sim_deepseek.PERSONAS`). Modelo Manu: Encontro 1h=400 (piso 15% = 340), aceita
interno/externo/remoto.

§0: gasta credito DeepSeek (agente + cliente-sim, AUTORIZADO). Seed+ROLLBACK contra prod — nada
commita; nao toca WhatsApp/Redis/prod.

Uso (de api/):
  PYTHONPATH=. TEST_DATABASE_URL="$DATABASE_URL" uv run python \
      ../scripts/eval_corpus/replay_agente_adversarial.py --out /caminho/adv.json --seeds 2
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

from evals.harness import habilitar_tracing, seedar
from evals.shadow.gerar import PERFIL_SINTETICO
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.llm import criar_chat_deepseek
from barra.settings import Settings, get_settings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replay_agente_fiel import _ancora_agora_utc, _bolhas, _rodar_turno_fiel  # noqa: E402
from replay_agente_terminal import (  # noqa: E402
    ESTADOS_COMPROMETIDO,
    MAX_TURNOS,
    _RE_PRECO,
    _cravar_terminal,
    _ler_atendimento,
)
from sim_deepseek import PERSONAS, FalaCliente, prompt_cliente, sanear_fala_cliente  # noqa: E402

# Personas HARD a rodar (subset de sim_deepseek.PERSONAS). Cada uma estressa um gap que o
# conversas_chave nao tocou:
#   preco_sensivel  -> segurar o piso / conceder UM desconto / escalar abaixo do piso
#   desconfia_golpe -> sobreviver a desconfianca sem ceder demais nem travar
#   insiste_pickup  -> conduzir pickup (externo sem Pix, ADR 0020); nao cobrar pix de uber
#   sumido_rapido   -> nao spammar/repetir quando o cliente esfria; parar com graca
PERSONAS_HARD = ["preco_sensivel", "desconfia_golpe", "insiste_pickup", "sumido_rapido"]

PROGRAMAS_ADV = [
    {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400, "ordem": 1},
    {"nome": "Encontro", "duracao_nome": "2 horas", "horas": 2, "preco": 700, "ordem": 2},
    {"nome": "Video chamada", "duracao_nome": "15 minutos", "horas": 0.25, "preco": 150, "ordem": 1},
]
TABELA_1H = Decimal("400")
PISO_1H = Decimal("340")  # 400 * (1 - desconto_max_pct 0.15) — melhor valor que a IA pode oferecer
_MIN_PROGRAMA = Decimal("200")  # ignora Pix (100) e video (150) na heuristica de piso do 1h


def _fixture() -> dict[str, Any]:
    """Fixture da modelo sintetica Manu (sem corpus): aceita os 3 tipos, cardapio cobre tudo."""
    modelo = copy.deepcopy(PERFIL_SINTETICO)
    modelo["tipo_atendimento_aceito"] = ["interno", "externo", "remoto"]
    modelo["programas"] = copy.deepcopy(PROGRAMAS_ADV)
    modelo.setdefault("chave_pix", "manu@pix.com")
    return {"cenario": {"modelo": modelo, "atendimento": {"estado": "Triagem"}}, "historico": []}


def _precos_ia(textos: list[str]) -> list[Decimal]:
    out: list[Decimal] = []
    for t in textos:
        for m in _RE_PRECO.findall(t or ""):
            try:
                out.append(Decimal(m))
            except (InvalidOperation, ValueError):
                pass
    return out


async def _escaladas(conn: AsyncConnection[dict[str, Any]], aid: Any) -> list[str]:
    """Motivos das escaladas abertas no atendimento (fora_de_oferta etc.). Robusto a schema."""
    try:
        cur = await conn.execute(
            "SELECT * FROM barravips.escaladas WHERE atendimento_id = %s", (aid,)
        )
        rows = await cur.fetchall()
    except Exception:
        return []
    out: list[str] = []
    for r in rows:
        d = dict(r)
        out.append(str(d.get("motivo") or d.get("motivo_escalada") or "escalada"))
    return out


async def _replay(dsn: str, persona_key: str, seed_idx: int, graph: Any, s: Settings) -> dict[str, Any]:
    conn = await AsyncConnection.connect(dsn, row_factory=dict_row, autocommit=False)
    try:
        cen = await seedar(conn, _fixture())
        cli = criar_chat_deepseek(s).with_structured_output(FalaCliente, method="function_calling")
        persona = PERSONAS[persona_key]

        contador = [0]
        hist: list[dict[str, str]] = []
        eventos: list[dict[str, Any]] = []
        textos_ia: list[str] = []
        textos_cliente: list[str] = []
        custo = 0.0
        ultimo_est: dict[str, Any] = {}
        ancora = _ancora_agora_utc()

        # abertura GERADA pela persona (nao ha corpus a reencenar)
        fala0 = await cli.ainvoke(prompt_cliente(persona, []))
        bolhas_c = sanear_fala_cliente(_bolhas(fala0.bolhas)) or ["oi"]
        hist.append({"lado": "C", "bolhas": "\n".join(bolhas_c)})

        for _ in range(MAX_TURNOS):
            for b in bolhas_c:
                eventos.append({"lado": "C", "tipo": "texto", "texto": b})
            textos_cliente.extend(bolhas_c)

            texto, _tools, est, c = await _rodar_turno_fiel(
                conn, cen, bolhas_c, graph, contador, agora_utc=ancora
            )
            custo += c
            ultimo_est = est
            if texto.strip():
                eventos.append({"lado": "IA", "tipo": "texto", "texto": texto})
                textos_ia.append(texto)
            hist.append({"lado": "M", "bolhas": texto})

            if est.get("estado") in ESTADOS_COMPROMETIDO or est.get("ia_pausada"):
                break

            try:
                fala = await cli.ainvoke(prompt_cliente(persona, hist))
            except Exception:
                break
            if fala.encerrou or not fala.bolhas.strip():
                break
            bolhas_c = sanear_fala_cliente(_bolhas(fala.bolhas))
            if not bolhas_c:
                break
            hist.append({"lado": "C", "bolhas": "\n".join(bolhas_c)})

        comprometido = ultimo_est.get("estado") in ESTADOS_COMPROMETIDO
        terminal = await _cravar_terminal(
            conn, cen, contador, comprometido, textos_ia, textos_cliente
        )
        eventos.extend(terminal["eventos"])

        at = await _ler_atendimento(conn, cen.atendimento_id)
        escaladas = await _escaladas(conn, cen.atendimento_id)
        precos = _precos_ia(textos_ia)
        return {
            "persona": persona_key,
            "seed": seed_idx,
            "desfecho": terminal["desfecho"],
            "valor_final": terminal["valor_final"],
            "motivo_perda": terminal.get("motivo_perda"),
            "valor_acordado": (
                str(at.get("valor_acordado")) if at.get("valor_acordado") is not None else None
            ),
            "tipo_atendimento": at.get("tipo_atendimento"),
            "escaladas": escaladas,
            "ia_pausada": bool(ultimo_est.get("ia_pausada")),
            "precos_ia": [str(p) for p in precos],
            # sinais deterministicos de conduta de preco (heuristica; painel confirma nuance):
            "ofereceu_desconto": any(PISO_1H <= p < TABELA_1H for p in precos),
            "furou_piso": any(_MIN_PROGRAMA <= p < PISO_1H for p in precos),
            "escalou_fora_de_oferta": any("fora_de_oferta" in e for e in escaladas),
            "n_turnos_ia": len(textos_ia),
            "custo_brl": round(custo, 6),
            "eventos": eventos,
        }
    except Exception as exc:
        import traceback

        return {
            "persona": persona_key,
            "seed": seed_idx,
            "erro": f"{type(exc).__name__}: {exc}",
            "tb": traceback.format_exc()[-1000:],
        }
    finally:
        await conn.rollback()
        await conn.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, default=2, help="repeticoes por persona (estocastico)")
    ap.add_argument("--conc", type=int, default=4)
    ap.add_argument("--personas", help="CSV (default: todas as HARD)")
    ap.add_argument("--temperatura", type=float, help="override do chat #1 (sweep no rig hard)")
    args = ap.parse_args()

    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("defina TEST_DATABASE_URL (ou DATABASE_URL)")

    ligou = habilitar_tracing()
    print(f"langfuse: {'ligado' if ligou else 'desligado'}", file=sys.stderr)
    s = get_settings()
    if args.temperatura is not None:
        s = s.model_copy(update={"chat_temperature": args.temperatura})
    print(f"chat_temperature = {s.chat_temperature}", file=sys.stderr)
    graph = build_graph_com(s)

    personas = [p.strip() for p in args.personas.split(",")] if args.personas else PERSONAS_HARD
    tarefas = [(p, i) for p in personas for i in range(args.seeds)]
    sem = asyncio.Semaphore(args.conc)

    async def _t(spec: tuple[str, int]) -> dict[str, Any]:
        async with sem:
            pk, si = spec
            print(f"[start] {pk}#{si}", file=sys.stderr)
            r = await _replay(dsn, pk, si, graph, s)
            tag = r.get("erro") or (
                f"{r.get('desfecho')} {r.get('valor_final') or r.get('motivo_perda')} "
                f"desc={r.get('ofereceu_desconto')} piso_furado={r.get('furou_piso')} "
                f"escalou={r.get('escalou_fora_de_oferta')} R${r.get('custo_brl')}"
            )
            print(f"[done ] {pk}#{si} — {tag}", file=sys.stderr)
            return r

    resultados = await asyncio.gather(*(_t(t) for t in tarefas))
    total = sum(r.get("custo_brl", 0.0) for r in resultados)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(
            {"temperatura": s.chat_temperature, "resultados": resultados, "custo_total_brl": round(total, 6)},
            fh, ensure_ascii=False, indent=2,
        )
    print(f"\nOK — {len(resultados)} runs, custo R${total:.4f} -> {args.out}", file=sys.stderr)


def build_graph_com(s: Settings) -> Any:
    """build_graph(settings) — isolado p/ o override de temperatura pegar no chat #1."""
    from barra.agente.graph import build_graph

    return build_graph(s)


if __name__ == "__main__":
    asyncio.run(main())
