"""Shadow do FUNIL INTEIRO — generaliza massa.py para pontos de decisão arbitrários.

massa.py cobre só o ponto da COTAÇÃO (corpus.eval_cotacao). Aqui os pontos vêm de um
JSONL externo (a amostra estratificada da varredura F1: `pontos_decisao_amostra.jsonl`),
um por linha:

    {"ref": "eb04:123@lid", "idx": 7, "tipo": "objecao_preco", "desfecho": "perdido_objecao",
     "gatilho": "...", "midia": false, "recorrente": false}

Mesmo desenho N-1 do massa.py (prefixo real congelado → 1 jogada de cada lado), mesmas
garantias (§0: rollback por ponto, handoff excluído do placar com motivo). Diferenças:

- **Modelo real da instância**: seeda a ficha real (dados_reais MODELOS_REAIS) mesclada
  sobre PERFIL_SINTETICO para campos ausentes — a ameaça nº 3 do plano (cardápio/preço)
  cai; o juiz ainda é instruído a julgar conduta, não valor.
- **Estado inicial por tipo de jogada** (abertura nasce em Novo; meio de funil em
  Triagem; pós-cotação em Qualificado) — senão a máquina de estados invalida a jogada.
- **--arm a|b|c**: braço A = prod (thinking disabled), braço B = thinking high, braço C =
  thinking low, via `settings.model_copy` (EVAL-ONLY; o default de prod não muda).
- Latência por ponto e truncamento (`finish_reason`) viram métricas (ameaça nº 12).

Uso:
    TEST_DATABASE_URL=... SHADOW_AUTORIZADO=1 uv run python -m evals.shadow.funil \
        --pontos /caminho/pontos_decisao_amostra.jsonl --arm a --out evals/saidas/funil_a.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection

from evals.harness import rodar_turno, seedar
from evals.shadow.gerar import PERFIL_SINTETICO
from evals.shadow.massa import (
    _carregar_turnos,
    _conectar,
    _montar_ponto,
    _seed_historico_fiel,
    pontuar_deterministico,
)

# Estado do atendimento coerente com o momento do funil da jogada (R1 do validador de
# ordem: Aguardando_confirmacao exige cotação apresentada — por isso pós-cotação seeda
# Qualificado, nunca além).
ESTADO_POR_TIPO: dict[str, str] = {
    "abertura": "Novo",
    "sondagem": "Triagem",
    "pitch": "Triagem",
    "midia_prova": "Triagem",
    "outro": "Triagem",
    "cotacao": "Qualificado",
    "objecao_preco": "Qualificado",
    "negociacao_desconto": "Qualificado",
    "recusa_limite": "Qualificado",
    "logistica_local": "Qualificado",
    "agendamento_fechamento": "Qualificado",
    "reengajamento": "Qualificado",
    "pos_venda": "Qualificado",
}


def _modelos_reais_por_instancia() -> dict[str, dict[str, Any]]:
    """Ficha real de UMA modelo por instância (a 1ª disponível), mesclada sobre a
    sintética para os campos que a ficha real não traz (idade, fetiches, ...)."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts/eval_corpus"))
    try:
        import dados_reais  # type: ignore[import-not-found]

        reais: dict[str, dict[str, Any]] = dados_reais.carregar(
            "replay_agente_terminal", "MODELOS_REAIS"
        )
    except Exception:
        return {}
    por_inst: dict[str, dict[str, Any]] = {}
    for ref, ficha in reais.items():
        inst = ref.split(":", 1)[0]
        por_inst.setdefault(inst, {**PERFIL_SINTETICO, **ficha})
    return por_inst


def _modelo_para(instancia: str, reais: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if instancia in reais:
        return reais[instancia]
    # Instâncias novas (elitebaby*) são os mesmos vendedores re-pareados; usa a ficha
    # rica do eb04 como base quando existir, senão a sintética.
    return reais.get("eb04", dict(PERFIL_SINTETICO))


def _fichas_por_thread() -> dict[str, dict[str, Any]]:
    """Fichas derivadas da evidência literal da PRÓPRIA thread (rodada 4): a instância
    atende por várias modelos, e a ficha por instância criava derrotas-artefato (agente
    coerente com o seed contradiz a vendedora real da thread). Gerado por
    scripts/eval_corpus/fichas_por_thread.py; ausente = fallback total para a instância."""
    caminho = os.path.join(
        os.path.dirname(__file__),
        "../../../scripts/eval_corpus/_dados_reais/fichas_por_thread.json",
    )
    try:
        with open(caminho, encoding="utf-8") as fh:
            fichas: dict[str, dict[str, Any]] = json.load(fh)
            return fichas
    except FileNotFoundError:
        return {}


_CAMPOS_THREAD = ("programas", "fetiches", "localizacao_operacional", "endereco_formatado")

# Período de trabalho padrão da casa (espelha o cadastro real em prod, ex.: Tatiane):
# 7 dias, 10:00 -> 04:00 do dia seguinte (overnight = hora_fim < hora_inicio, como o painel
# grava). Sem janelas o <periodo_de_trabalho> renderiza "disponível sempre" — cadastro
# incompleto que nenhuma modelo real tem. A âncora --agora do grid PRECISA cair dentro da
# janela (ex.: 14:00 BRT), senão o agente recusa "agora" onde o vendedor real atendia.
_DISPONIBILIDADE_PADRAO = [
    {"dia_semana": d, "hora_inicio": "10:00", "hora_fim": "04:00"} for d in range(7)
]


def _ficha_do_ponto(
    ref: str, reais: dict[str, dict[str, Any]], por_thread: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Ficha da thread (evidência própria) sobreposta à da instância, campo a campo.
    `nao_faz` da thread remove o programa contradito (recusa literal > oferta herdada);
    o seed continua expressando limite por AUSÊNCIA de programa (closed-world)."""
    instancia = ref.split(":", 1)[0]
    ficha = dict(_modelo_para(instancia, reais))
    da_thread = por_thread.get(ref)
    if not da_thread:
        return ficha
    for campo in _CAMPOS_THREAD:
        if da_thread.get(campo):
            ficha[campo] = da_thread[campo]
    nao_faz = set(da_thread.get("nao_faz") or [])
    if "anal" in nao_faz:
        ficha["programas"] = [
            p for p in (ficha.get("programas") or []) if p.get("nome") != "Completo"
        ]
    if nao_faz:
        ficha["nao_faz"] = sorted(nao_faz)  # seedar ignora; fica auditável no par
    return ficha


def _completar_ficha(ficha: dict[str, Any]) -> dict[str, Any]:
    """Completa a ficha ao nível de um cadastro real do painel: toda modelo de prod tem
    período de trabalho — sem ele o agente roda com "disponível sempre", que não existe
    em prod. Aplicado DEPOIS do merge thread/instância (nunca sobrescreve evidência)."""
    if not ficha.get("disponibilidade"):
        ficha["disponibilidade"] = list(_DISPONIBILIDADE_PADRAO)
    return ficha


def carregar_pontos(caminho: str, *, limite: int | None) -> list[dict[str, Any]]:
    pontos = []
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if linha:
                pontos.append(json.loads(linha))
    return pontos[:limite] if limite else pontos


async def gerar_par_funil(
    conn: AsyncConnection[dict[str, Any]],
    ponto_cfg: dict[str, Any],
    *,
    graph: Any,
    reais: dict[str, dict[str, Any]],
    por_thread: dict[str, dict[str, Any]],
    agora_utc: datetime | None = None,
) -> dict[str, Any] | None:
    """Roda o grafo no ponto (1 ainvoke). None = forma N-1 inválida (ex.: jogada
    só-mídia) — o caller contabiliza como excluído, nunca some em silêncio."""
    instancia, remote_jid = ponto_cfg["ref"].split(":", 1)
    turnos = await _carregar_turnos(conn, instancia, remote_jid)
    ponto = _montar_ponto(
        {
            "instancia": instancia,
            "remote_jid": remote_jid,
            "cotacao_turno": ponto_cfg["idx"],
            "hold_out": instancia == "eb04",
            "label_bin": None,
            "reacao_real": None,
            "desfecho_proxy": ponto_cfg.get("desfecho"),
        },
        turnos,
    )
    if ponto is None:
        return None

    estado = ESTADO_POR_TIPO.get(ponto_cfg.get("tipo", ""), "Triagem")
    fixture = {
        "cenario": {
            "modelo": _completar_ficha(_ficha_do_ponto(ponto_cfg["ref"], reais, por_thread)),
            "atendimento": {"estado": estado},
            # Fidelidade cliente-x-vendedor: o vendedor real SABIA se o cliente era recorrente
            # (`<cliente recorrente=...>` no contexto_dinamico). Sem seedar, todo recorrente
            # vira "novo" e o agente re-cumprimenta/re-sonda — derrota-artefato do harness.
            "recorrente": bool(ponto_cfg.get("recorrente")),
        },
        "historico": [],
        "turno_cliente": ponto.turno_cliente,
    }
    cen = await seedar(conn, fixture)
    await _seed_historico_fiel(conn, cen, ponto.contexto)
    t0 = time.monotonic()
    res = await rodar_turno(
        conn,
        cen,
        turno_cliente=ponto.turno_cliente,
        graph=graph,
        agora_utc=agora_utc,
        # Marca a ORIGEM no trace: `tags="funil"` separa os pontos do grid dos turnos do gate e do
        # e2e no mesmo projeto Langfuse (o regime — thinking/prompts — ja vem do carimbo do harness).
        trace_tag="funil",
    )
    latencia_s = round(time.monotonic() - t0, 2)
    resposta_ia = (res.texto or "").strip()

    handoff = bool(res.estado_final.get("ia_pausada"))
    handoff_motivo: str | None = None
    if handoff:
        cur = await conn.execute(
            "SELECT observacao FROM barravips.escaladas WHERE atendimento_id = %s "
            "ORDER BY aberta_em DESC LIMIT 1",
            (cen.atendimento_id,),
        )
        row = await cur.fetchone()
        handoff_motivo = row["observacao"] if row else None

    return {
        "ref": ponto.ref,
        "idx": ponto_cfg["idx"],
        "tipo": ponto_cfg.get("tipo"),
        "desfecho": ponto_cfg.get("desfecho"),
        "recorrente": bool(ponto_cfg.get("recorrente")),
        "midia": bool(ponto_cfg.get("midia")),
        "estado_seed": estado,
        "handoff": handoff,
        "handoff_motivo": handoff_motivo,
        "contexto": ponto.contexto,
        "turno_cliente": ponto.turno_cliente,
        "resposta_ia": resposta_ia,
        "resposta_humano": ponto.resposta_humano,
        "ia": {
            **pontuar_deterministico(resposta_ia),
            "tool_calls": res.tool_calls,
            "custo_brl": round(res.metricas.custo_brl, 6),
            "latencia_s": latencia_s,
        },
        "humano": pontuar_deterministico(ponto.resposta_humano),
    }


def _agregar_funil(pares: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumo determinístico por tipo de jogada (o juiz cego entra depois)."""
    saida: dict[str, Any] = {"n": len(pares)}
    if not pares:
        return saida
    por_tipo: dict[str, list[dict[str, Any]]] = {}
    for p in pares:
        por_tipo.setdefault(p["tipo"] or "outro", []).append(p)
    saida["por_tipo"] = {
        tipo: {
            "n": len(ps),
            "empurrao_ia": sum(1 for p in ps if p["ia"]["empurrao"]),
            "empurrao_humano": sum(1 for p in ps if p["humano"]["empurrao"]),
            "mcnemar_ia_melhor": sum(
                1 for p in ps if p["humano"]["empurrao"] and not p["ia"]["empurrao"]
            ),
            "mcnemar_ia_pior": sum(
                1 for p in ps if p["ia"]["empurrao"] and not p["humano"]["empurrao"]
            ),
        }
        for tipo, ps in sorted(por_tipo.items())
    }
    lats = sorted(p["ia"]["latencia_s"] for p in pares)
    saida["latencia_p50_s"] = lats[len(lats) // 2]
    saida["latencia_p95_s"] = lats[min(len(lats) - 1, int(len(lats) * 0.95))]
    saida["custo_brl_total"] = round(sum(p["ia"]["custo_brl"] for p in pares), 4)
    saida["handoffs"] = sum(1 for p in pares if p["handoff"])
    # Turno sem texto e sem handoff = a IA silenciou (em prod nada chega ao cliente).
    # Derrota automática no julgamento — nunca esconder no agregado.
    saida["respostas_vazias"] = sum(1 for p in pares if not p["resposta_ia"] and not p["handoff"])
    return saida


async def _main(args: argparse.Namespace) -> dict[str, Any]:
    from barra.agente.graph import build_graph
    from barra.settings import get_settings
    from evals.e2e.sessao import _graph_fake

    thinking = {"a": "disabled", "b": "high", "c": "low"}[args.arm]
    overrides: dict[str, Any] = {"deepseek_thinking_chat": thinking}
    if args.temperatura is not None:
        overrides["chat_temperature"] = args.temperatura
    settings = get_settings().model_copy(update=overrides)

    # Âncora de "agora" (clock injection): fixa e IGUAL para todos os braços de um grid —
    # sem ela cada corrida vê o now() do banco na hora em que roda e "hoje/amanhã" dos
    # prefixos reais muda de sentido entre braços (confound). Default: hoje 09:00 BRT
    # (mesma convenção do replay fiel, REPLAY_AGORA_BRT).
    if args.agora:
        agora_utc = datetime.fromisoformat(args.agora).astimezone(UTC)
    else:
        brt = ZoneInfo("America/Sao_Paulo")
        agora_utc = datetime.now(brt).replace(hour=9, minute=0, second=0, microsecond=0)
        agora_utc = agora_utc.astimezone(UTC)
    # Trace Langfuse do grid: cada ponto vira um trace nomeado com o REGIME carimbado
    # (`thinking:<arm>`, `prompts:<hash>`), que e como se compara dois braços sem abrir os JSONs —
    # e onde se le o `reasoning_content` quando o braço thinking se comporta de forma estranha.
    # No-op silencioso sem as envs LANGFUSE_* (harness.habilitar_tracing).
    from evals.harness import habilitar_tracing

    tracing_ligado = habilitar_tracing()
    print(
        f"[braço {args.arm.upper()}{f' · {args.rotulo}' if args.rotulo else ''}] "
        f"deepseek_thinking_chat={thinking}  agora_utc={agora_utc.isoformat()}  "
        f"tracing={'on' if tracing_ligado else 'off'}"
    )

    graph = _graph_fake() if args.fake else build_graph(settings)
    reais = _modelos_reais_por_instancia()
    por_thread = _fichas_por_thread()
    print(f"fichas por thread: {len(por_thread)} (fallback instância para o resto)")
    pontos = carregar_pontos(args.pontos, limite=args.n)
    dsn = os.environ["TEST_DATABASE_URL"]
    conn = await _conectar(dsn)
    pares: list[dict[str, Any]] = []
    excluidos: list[dict[str, Any]] = []
    try:
        for i, cfg in enumerate(pontos, 1):
            try:
                par = await gerar_par_funil(
                    conn,
                    cfg,
                    graph=graph,
                    reais=reais,
                    por_thread=por_thread,
                    agora_utc=agora_utc,
                )
                if par is None:
                    excluidos.append({"ref": cfg["ref"], "idx": cfg["idx"], "motivo": "forma_n1"})
                else:
                    pares.append(par)
                await conn.rollback()
            except Exception as e:
                excluidos.append({"ref": cfg["ref"], "idx": cfg["idx"], "motivo": type(e).__name__})
                print(f"  ! ponto {i} pulado ({cfg['ref']}): {type(e).__name__}", flush=True)
                try:
                    await conn.close()
                except Exception:  # noqa: S110
                    pass
                conn = await _conectar(dsn)
            if i % 10 == 0:
                print(f"  ... {i}/{len(pontos)}", flush=True)
    finally:
        try:
            await conn.rollback()
        except Exception:  # noqa: S110
            pass
        await conn.close()
    return {
        "meta": {
            "braco": args.arm,
            "thinking": thinking,
            "temperatura": args.temperatura,
            "rotulo": args.rotulo,
            "agora_utc": agora_utc.isoformat(),
            "pontos_pedidos": len(pontos),
            "excluidos": excluidos,
            **_agregar_funil(pares),
        },
        "pares": pares,
    }


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Shadow do funil inteiro (N-1, 2 braços).")
    ap.add_argument("--pontos", required=True, help="JSONL da amostra de pontos de decisão")
    ap.add_argument(
        "--arm",
        choices=["a", "b", "c"],
        default="a",
        help="a=disabled (prod), b=thinking high, c=thinking low",
    )
    ap.add_argument("--n", type=int, default=None, help="limita o nº de pontos (smoke)")
    ap.add_argument("--temperatura", type=float, default=None, help="override eval-only")
    ap.add_argument("--rotulo", default=None, help="nome do braço no relatório (ex.: nt07, hi_r1)")
    ap.add_argument(
        "--agora",
        default=None,
        help="âncora ISO de 'agora' (igual p/ todos os braços do grid); default hoje 09:00 BRT",
    )
    ap.add_argument("--out", default="evals/saidas/funil.json")
    ap.add_argument("--fake", action="store_true", help="grafo mock, sem crédito")
    args = ap.parse_args()

    if not args.fake and os.environ.get("SHADOW_AUTORIZADO") != "1":
        raise SystemExit("§0: exige SHADOW_AUTORIZADO=1 (ou --fake).")
    doc = asyncio.run(_main(args))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    m = doc["meta"]
    print(f"\n=== Shadow funil (braço {m['braco']}) ===")
    print(
        f"pares: {m['n']}  excluídos: {len(m['excluidos'])}  "
        f"handoffs: {m.get('handoffs', 0)}  custo: R$ {m.get('custo_brl_total', 0)}  "
        f"p95: {m.get('latencia_p95_s', '-')}s"
    )
    for tipo, agg in (m.get("por_tipo") or {}).items():
        print(f"  {tipo:24s} n={agg['n']}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    _cli()
