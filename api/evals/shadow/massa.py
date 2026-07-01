"""Camada 2 (shadow) — loop em massa head-to-head contra o Vendedor humano.

Para N pontos de decisao REAIS do corpus (por ora: o turno da COTACAO, ja localizado em
`corpus.eval_cotacao.cotacao_turno`), roda o grafo REAL sobre o MESMO contexto que o humano viu
e captura `(contexto, resposta_ia, resposta_humano)`. Scorers deterministicos rodam sobre IA e
humano nos MESMOS pontos (empurrao pareado, McNemar). O juiz cego head-to-head e' Moeda A (painel
Claude Code, fora deste modulo) — le o JSON de saida (`pares` + `meta`).

Desenho (doc evals/shadow/README.md): "N-1 testing" — prefixo real, 1 turno, sem distribution
shift. A modelo e SINTETICA fixa (Manu, espelha render_v1_prompt.py); precos diferem do thread
real DE PROPOSITO — comparamos a JOGADA (calor/empurrao/estrutura), nao o numero cotado.

§0: a GERACAO gasta DeepSeek (1 ainvoke/ponto) e exige `TEST_DATABASE_URL` + `SHADOW_AUTORIZADO=1`.
`--fake` injeta o grafo mock (sem credito) p/ validar o encanamento. ROLLBACK sempre: SELECT
read-only no corpus + seed efemero em barravips descartado no fim (nada commita).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection, OperationalError
from psycopg.rows import dict_row

from barra.agente.fluxo import rotular_turno
from evals.conduta import tem_empurrao
from evals.harness import rodar_turno, seedar
from evals.shadow.gerar import PERFIL_SINTETICO


@dataclass
class PontoDecisao:
    """Um ponto N-1 do corpus: contexto real + a resposta real do humano a ser batida."""

    ref: str
    instancia: str
    hold_out: bool
    label_bin: str | None
    reacao_real: str | None
    desfecho_proxy: str | None
    cotacao_turno: int
    contexto: list[dict[str, str]]  # [{direcao: 'cliente'|'ia', texto}] ANTES do ponto
    turno_cliente: str  # ultima fala do cliente que o humano respondeu
    resposta_humano: str  # o turno real do Vendedor (a cotacao) a ser batido


def pontuar_deterministico(texto: str, *, tem_midia: bool = False) -> dict[str, Any]:
    """Features determics. de UMA resposta (IA ou humano): ato dominante, empurrao, tamanho."""
    ato = rotular_turno(texto, tem_midia)
    palavras = len((texto or "").split())
    return {
        "ato": ato,
        "cotou": ato == "cotacao",
        "empurrao": tem_empurrao(texto),
        "len_palavras": palavras,
    }


async def _carregar_turnos(
    conn: AsyncConnection[dict[str, Any]], instancia: str, remote_jid: str
) -> list[dict[str, Any]]:
    res = await conn.execute(
        """
        SELECT turno_idx, from_me, COALESCE(texto, '') AS texto, tem_midia
        FROM corpus.turnos
        WHERE instancia = %s AND remote_jid = %s
        ORDER BY turno_idx
        """,
        (instancia, remote_jid),
    )
    return list(await res.fetchall())


def _montar_ponto(linha: dict[str, Any], turnos: list[dict[str, Any]]) -> PontoDecisao | None:
    """Fatia os turnos no ponto da cotacao. None se a forma nao permite um par N-1 limpo:

    - resposta_humano = o turno em `cotacao_turno` (deve ser from_me e textual);
    - turno_cliente   = ultima fala textual do cliente ANTES da cotacao (o gatilho);
    - contexto        = turnos antes desse gatilho (from_me -> 'ia', senao 'cliente').
    """
    ct = int(linha["cotacao_turno"])
    por_idx = {int(t["turno_idx"]): t for t in turnos}
    alvo = por_idx.get(ct)
    if alvo is None or not alvo["from_me"]:
        return None
    resposta_humano = str(alvo["texto"]).strip()
    if not resposta_humano:
        return None  # cotacao so-midia: nada textual p/ o juiz comparar

    # pivot = ultima fala textual do cliente antes da cotacao
    pivot_idx: int | None = None
    for t in turnos:
        idx = int(t["turno_idx"])
        if idx >= ct:
            break
        if not t["from_me"] and str(t["texto"]).strip():
            pivot_idx = idx
    if pivot_idx is None:
        return None
    turno_cliente = str(por_idx[pivot_idx]["texto"]).strip()

    contexto: list[dict[str, str]] = []
    for t in turnos:
        idx = int(t["turno_idx"])
        if idx >= pivot_idx:
            break
        txt = str(t["texto"]).strip()
        if not txt:
            continue  # turnos so-midia nao entram no historico textual do seed
        contexto.append({"direcao": "ia" if t["from_me"] else "cliente", "texto": txt})

    ref = f"{linha['instancia']}:{linha['remote_jid']}"
    return PontoDecisao(
        ref=ref,
        instancia=str(linha["instancia"]),
        hold_out=bool(linha["hold_out"]),
        label_bin=linha.get("label_bin"),
        reacao_real=linha.get("reacao_real"),
        desfecho_proxy=linha.get("desfecho_proxy"),
        cotacao_turno=ct,
        contexto=contexto,
        turno_cliente=turno_cliente,
        resposta_humano=resposta_humano,
    )


async def extrair_pontos_cotacao(
    conn: AsyncConnection[dict[str, Any]],
    *,
    limite: int,
    hold_out: str | None = None,
    semente: int = 7,
) -> list[PontoDecisao]:
    """Amostra estratificada (GOOD/BAD) de pontos de cotacao com par N-1 limpo.

    `hold_out`: None = todo o corpus; 'eb04' = so hold-out; 'calib' = eb01-03. Amostragem
    deterministica (`semente`) p/ reprodutibilidade entre rodadas.
    """
    cond = ""
    if hold_out == "eb04":
        cond = "AND hold_out"
    elif hold_out == "calib":
        cond = "AND NOT hold_out"
    res = await conn.execute(
        f"""
        SELECT instancia, remote_jid, cotacao_turno, label_bin, reacao_real,
               desfecho_proxy, hold_out
        FROM corpus.eval_cotacao
        WHERE cotacao_turno IS NOT NULL AND label_bin IS NOT NULL {cond}
        ORDER BY instancia, remote_jid
        """
    )
    linhas = list(await res.fetchall())

    # Monta os pontos validos (forma N-1 limpa), depois estratifica por label_bin.
    rng = random.Random(semente)  # noqa: S311 — amostragem reprodutivel, nao-cripto
    rng.shuffle(linhas)
    bons: list[PontoDecisao] = []
    ruins: list[PontoDecisao] = []
    for linha in linhas:
        if len(bons) + len(ruins) >= limite * 3 and len(bons) >= limite and len(ruins) >= limite:
            break
        turnos = await _carregar_turnos(conn, linha["instancia"], linha["remote_jid"])
        ponto = _montar_ponto(linha, turnos)
        if ponto is None:
            continue
        (bons if ponto.label_bin == "GOOD" else ruins).append(ponto)

    metade = limite // 2
    sel = bons[:metade] + ruins[: limite - metade]
    if len(sel) < limite:  # um lado escasso: completa com o que sobrou
        resto = bons[metade:] + ruins[limite - metade :]
        sel += resto[: limite - len(sel)]
    rng.shuffle(sel)
    return sel[:limite]


async def _seed_historico_fiel(
    conn: AsyncConnection[dict[str, Any]], cen: Any, contexto: list[dict[str, str]]
) -> None:
    """Insere o historico FIEL: `barravips.uuidv7()` + `created_at` crescente (mais antigo primeiro).

    Sem isto a janela do agente sai EMBARALHADA: `carregar_mensagens` ordena por
    `created_at DESC, id DESC`, mas o `_inserir_mensagem` do harness grava `now()` (empatado) +
    `uuid4()` (aleatorio) -> ordem aleatoria -> o agente recumprimenta/perde o fio (a "amnesia" do
    replay cru, ver replay_agente_fiel.py). Cada bolha aqui ganha um instante distinto no passado,
    deixando o turno_cliente (inserido por rodar_turno com `now()`) como o mais recente.
    """
    n = len(contexto)
    for i, t in enumerate(contexto):
        seg = (n - i) * 2  # mais antigo = offset maior (mais no passado)
        await conn.execute(
            """
            INSERT INTO barravips.mensagens
                (id, conversa_id, atendimento_id, direcao, tipo, conteudo,
                 evolution_message_id, created_at)
            VALUES (barravips.uuidv7(), %s, %s, %s::barravips.direcao_mensagem_enum, 'texto', %s,
                    %s, now() - make_interval(secs => %s))
            """,
            (
                cen.conversa_id,
                cen.atendimento_id,
                t["direcao"],
                t["texto"],
                f"fiel-{uuid4().hex}",
                seg,
            ),
        )


async def gerar_par(
    conn: AsyncConnection[dict[str, Any]], ponto: PontoDecisao, *, graph: Any
) -> dict[str, Any]:
    """Roda o grafo real sobre o contexto do ponto (§0: 1 ainvoke) e monta o registro do par.

    Semeadura FIEL: o cenario nasce SEM historico (seedar com historico=[]) e o contexto entra por
    `_seed_historico_fiel` (uuidv7 + created_at ordenado), senao a janela embaralha (amnesia). O
    `rodar_turno` insere o turno_cliente (now(), o mais recente) e roda 1 ainvoke. NAO faz rollback
    — o caller envolve o lote inteiro num rollback so'.
    """
    fixture = {
        "cenario": {"modelo": PERFIL_SINTETICO, "atendimento": {"estado": "Qualificado"}},
        "historico": [],
        "turno_cliente": ponto.turno_cliente,
    }
    cen = await seedar(conn, fixture)
    await _seed_historico_fiel(conn, cen, ponto.contexto)
    res = await rodar_turno(conn, cen, turno_cliente=ponto.turno_cliente, graph=graph)
    resposta_ia = (res.texto or "").strip()
    # HANDOFF: a IA pausou/escalou no turno (fora_de_oferta: serviço não ofertado / preço abaixo do
    # piso). O texto vai VAZIO ao cliente (o resumo vira card) -> NÃO e' derrota vs a cotacao do
    # humano, e' conduta. Auto-documenta o motivo (senao o proximo re-sonda a tabela escaladas).
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
        "handoff": handoff,
        "handoff_motivo": handoff_motivo,
        "ref": ponto.ref,
        "instancia": ponto.instancia,
        "hold_out": ponto.hold_out,
        "label_bin": ponto.label_bin,
        "reacao_real": ponto.reacao_real,
        "desfecho_proxy": ponto.desfecho_proxy,
        "cotacao_turno": ponto.cotacao_turno,
        "contexto": ponto.contexto,
        "turno_cliente": ponto.turno_cliente,
        "resposta_ia": resposta_ia,
        "resposta_humano": ponto.resposta_humano,
        "ia": {
            **pontuar_deterministico(resposta_ia),
            "tool_calls": res.tool_calls,
            "estado_final": res.estado_final,
            "custo_brl": round(res.metricas.custo_brl, 6),
        },
        "humano": pontuar_deterministico(ponto.resposta_humano),
    }


def _agregar(pares: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumo determinico do lote (o juiz cego entra depois, sobre os pares)."""
    n = len(pares)
    if not n:
        return {"n": 0}
    emp_ia = sum(1 for p in pares if p["ia"]["empurrao"])
    emp_hu = sum(1 for p in pares if p["humano"]["empurrao"])
    cotou_ia = sum(1 for p in pares if p["ia"]["cotou"])
    cotou_hu = sum(1 for p in pares if p["humano"]["cotou"])
    # McNemar pareado (empurrao): discordancias IA-melhor (humano empurra, IA nao) vs IA-pior.
    ia_melhor = sum(1 for p in pares if p["humano"]["empurrao"] and not p["ia"]["empurrao"])
    ia_pior = sum(1 for p in pares if p["ia"]["empurrao"] and not p["humano"]["empurrao"])
    custo = sum(p["ia"].get("custo_brl", 0.0) for p in pares)
    return {
        "n": n,
        "empurrao_ia_pct": round(100 * emp_ia / n, 2),
        "empurrao_humano_pct": round(100 * emp_hu / n, 2),
        "cotou_ia_pct": round(100 * cotou_ia / n, 2),
        "cotou_humano_pct": round(100 * cotou_hu / n, 2),
        "mcnemar_empurrao": {"ia_melhor": ia_melhor, "ia_pior": ia_pior},
        "custo_brl_total": round(custo, 4),
        "ref_baseline_empurrao": {
            "regex_humano_corpus_pct": 3.25,
            "juiz_humano_pct": 26.0,
            "v1_regex_pct": 0.3,
        },
    }


async def _conectar(dsn: str, *, tentativas: int = 4) -> AsyncConnection[dict[str, Any]]:
    """Conecta com retry + backoff: o DB de prod (Supavisor) as vezes derruba a conexao sob carga
    ('server closed the connection unexpectedly'); um connect transitorio nao deve matar um lote de
    300 (§0: read-only + rollback). Reaplica no reconnect pos-crash de ponto (rodar_massa)."""
    ultimo: OperationalError | None = None
    for i in range(tentativas):
        try:
            return await AsyncConnection.connect(
                dsn, autocommit=False, row_factory=dict_row, prepare_threshold=None
            )
        except OperationalError as e:
            ultimo = e
            await asyncio.sleep(2 * (i + 1))
    raise ultimo if ultimo is not None else RuntimeError("conexao falhou sem excecao")


async def rodar_massa(
    conn: AsyncConnection[dict[str, Any]],
    graph: Any,
    *,
    dsn: str,
    limite: int,
    hold_out: str | None,
    semente: int,
) -> tuple[dict[str, Any], AsyncConnection[dict[str, Any]]]:
    """Gera os pares ponto a ponto, ISOLANDO a falha de cada um (devolve a conn viva no fim).

    Cada ponto e' independente (N-1) e seu seed efemero e' descartado por um `rollback` apos o
    ponto — §0 (nada commita) e a conn nao acumula 300 seeds numa transacao so'. Se um ponto crasha
    (ex.: o agente dispara `enviar_midia` em paralelo e os `conn.transaction()` concorrentes na conn
    unica do harness colidem -> `OutOfOrderTransactionNesting`, que corrompe a conn e impede ate' o
    rollback), o ponto e' PULADO e a conn e' reaberta limpa — um ponto raro nao derruba o lote
    inteiro. `puladas` entra na meta p/ o relatorio nao fingir cobertura total.
    """
    pontos = await extrair_pontos_cotacao(conn, limite=limite, hold_out=hold_out, semente=semente)
    if not pontos:
        raise SystemExit("nenhum ponto de cotacao N-1 limpo no recorte (DSN/§0?).")
    pares: list[dict[str, Any]] = []
    puladas: list[dict[str, str]] = []
    for i, ponto in enumerate(pontos, 1):
        try:
            par = await gerar_par(conn, ponto, graph=graph)
            pares.append(par)
            await conn.rollback()  # descarta o seed do ponto (§0); proximo comeca limpo
        except Exception as e:
            puladas.append({"ref": ponto.ref, "erro": type(e).__name__})
            print(f"  ! ponto {i} pulado ({ponto.ref}): {type(e).__name__}", flush=True)
            # A conn pode estar com o nesting de transacao corrompido (rollback proibido) — reabre.
            try:
                await conn.close()
            except Exception:  # noqa: S110
                pass
            conn = await _conectar(dsn)
        if i % 10 == 0:
            print(f"  ... {i}/{len(pontos)} pontos gerados", flush=True)
    doc = {
        "meta": {
            "ponto": "cotacao",
            "hold_out": hold_out or "todos",
            "semente": semente,
            "modelo_sintetica": "Manu (PERFIL_SINTETICO)",
            "pontos_pedidos": len(pontos),
            "pontos_pulados": puladas,
            **_agregar(pares),
        },
        "pares": pares,
    }
    return doc, conn


async def _main(args: argparse.Namespace) -> dict[str, Any]:
    from barra.agente.graph import build_graph
    from barra.settings import get_settings
    from evals.e2e.sessao import _graph_fake

    # Override de temperatura EVAL-ONLY (experimento A/B): model_copy nao muta o default de prod.
    settings = None
    if args.temperatura is not None:
        settings = get_settings().model_copy(update={"chat_temperature": args.temperatura})
        print(f"[experimento] chat_temperature = {args.temperatura} (override eval-only)")
    graph = _graph_fake() if args.fake else build_graph(settings)
    dsn = os.environ["TEST_DATABASE_URL"]
    conn = await _conectar(dsn)
    try:
        doc, conn = await rodar_massa(
            conn, graph, dsn=dsn, limite=args.n, hold_out=args.hold_out, semente=args.semente
        )
        return doc
    finally:
        try:
            await conn.rollback()  # seed efemero nunca commita (§0)
        except Exception:  # noqa: S110 — conn ja pode ter sido reaberta/fechada no loop
            pass
        await conn.close()


def _emitir(doc: dict[str, Any], out: str) -> None:
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    m = doc["meta"]
    print("\n=== Shadow massa (cotacao) ===")
    print(f"pares: {m['n']}  custo: R$ {m['custo_brl_total']}  recorte: {m['hold_out']}")
    print(
        f"empurrao(regex)  IA: {m['empurrao_ia_pct']}%   humano: {m['empurrao_humano_pct']}%"
        f"   (McNemar IA-melhor={m['mcnemar_empurrao']['ia_melhor']} "
        f"IA-pior={m['mcnemar_empurrao']['ia_pior']})"
    )
    print(f"cotou            IA: {m['cotou_ia_pct']}%   humano: {m['cotou_humano_pct']}%")
    print(f"-> {out}")
    print("juiz cego head-to-head: Moeda A (painel Claude Code), rode sobre os `pares`.")


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Shadow Camada 2: geracao em massa head-to-head.")
    ap.add_argument(
        "--n", type=int, default=60, help="nº de pontos de cotacao (estratif. GOOD/BAD)"
    )
    ap.add_argument("--hold-out", choices=["eb04", "calib"], default=None, help="recorte do corpus")
    ap.add_argument("--semente", type=int, default=7, help="semente da amostragem (reprodutivel)")
    ap.add_argument(
        "--temperatura",
        type=float,
        default=None,
        help="override EVAL-ONLY de chat_temperature (experimento A/B; None = default de prod 1.3)",
    )
    ap.add_argument(
        "--out", default="evals/saidas/shadow_massa.json", help="JSON de saida (pares + meta)"
    )
    ap.add_argument(
        "--fake", action="store_true", help="grafo mock: valida encanamento sem credito"
    )
    args = ap.parse_args()

    if not args.fake and os.environ.get("SHADOW_AUTORIZADO") != "1":
        raise SystemExit(
            "Geracao shadow gasta credito DeepSeek (§0). Defina SHADOW_AUTORIZADO=1 + "
            "TEST_DATABASE_URL apos a autorizacao do dev, ou use --fake p/ validar o encanamento."
        )
    doc = asyncio.run(_main(args))
    _emitir(doc, args.out)


if __name__ == "__main__":
    _cli()
