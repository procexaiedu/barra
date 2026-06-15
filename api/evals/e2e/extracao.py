"""Extracao mecanica de PerfilCaso a partir do corpus (corpus.threads + corpus.turnos).

Offline e SEM credito: so SELECT. Preenche o lado do CLIENTE — abertura, roteiro de falas reais,
persona ancorada nessas falas e os rotulos de desfecho (corpus). A modelo e MODELO_SINTETICA fixa
(ver perfil.py). `from_me=true` => Vendedor (papel que a IA reencena); `from_me=false` => Cliente.

A persona embute as falas REAIS do cliente como ancora: o ClienteLLM (corrida real) reencena
aquele cliente — mesmo jeito, mesmas objecoes — em vez de um cliente generico. O ClienteRoteirizado
(offline) consome `roteiro_cliente` (as proprias falas) como baseline barato.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

from .perfil import MODELO_SINTETICA, PerfilCaso

# desfecho_proxy de corpus.threads agrupado pela leitura comercial (ver distribuicao no corpus).
DESFECHOS_CONVERTIDOS = ("convertido_provavel",)
DESFECHOS_PERDIDOS = ("perdido_sumiu", "perdido_objecao")

# tipo_atendimento_proxy -> expectativa de tipo fixado. "ambos"/None => sem expectativa dura.
_TIPO_PROXY: dict[str, str] = {"interno": "interno", "externo": "externo"}

_PERSONA_TMPL = """\
Cliente real da operação (desfecho observado: {desfecho}). Reproduza ESTE cliente: o mesmo jeito \
de escrever, o mesmo nível de decisão e as MESMAS objeções que ele levantou — não seja mais fácil \
nem mais difícil do que ele foi. Falas reais dele, na ordem em que mandou:
{falas}"""


async def extrair_perfis(
    conn: AsyncConnection[dict[str, Any]],
    *,
    desfechos: tuple[str, ...],
    tipo: str | None = "interno",
    limite: int = 20,
    min_cli: int = 2,
    max_cli: int = 10,
) -> list[PerfilCaso]:
    """Seleciona threads do corpus pelo desfecho/tipo e monta um PerfilCaso de cada.

    `min_cli`/`max_cli` limitam o nº de falas do cliente (threads com conversa real, nem curta
    demais nem uma novela). Threads sem falas textuais suficientes sao descartadas.
    """
    cond_tipo = "AND t.tipo_atendimento_proxy = %(tipo)s" if tipo else ""
    res = await conn.execute(
        f"""
        SELECT t.instancia, t.remote_jid, t.desfecho_proxy, t.tipo_atendimento_proxy, ec.label_bin
        FROM corpus.threads t
        LEFT JOIN corpus.eval_cotacao ec USING (instancia, remote_jid)
        WHERE t.desfecho_proxy = ANY(%(desfechos)s)
          AND t.cliente_iniciou
          AND t.n_cli BETWEEN %(min_cli)s AND %(max_cli)s
          {cond_tipo}
        ORDER BY t.remote_jid
        LIMIT %(limite)s
        """,
        {
            "desfechos": list(desfechos),
            "tipo": tipo,
            "min_cli": min_cli,
            "max_cli": max_cli,
            "limite": limite,
        },
    )
    threads = await res.fetchall()

    perfis: list[PerfilCaso] = []
    for th in threads:
        falas = await _falas_do_cliente(conn, th["instancia"], th["remote_jid"])
        if len(falas) < min_cli:
            continue
        perfis.append(_montar(th, falas))
    return perfis


async def extrair_perfil_por_ref(
    conn: AsyncConnection[dict[str, Any]], ref: str
) -> PerfilCaso | None:
    """Monta o PerfilCaso de UMA thread por `ref` ("instancia:remote_jid"). None se nao achar
    a thread ou se ela nao tiver falas textuais do cliente. Usado pela sessao turn-by-turn."""
    instancia, _, remote_jid = ref.partition(":")
    res = await conn.execute(
        """
        SELECT t.instancia, t.remote_jid, t.desfecho_proxy, t.tipo_atendimento_proxy, ec.label_bin
        FROM corpus.threads t
        LEFT JOIN corpus.eval_cotacao ec USING (instancia, remote_jid)
        WHERE t.instancia = %s AND t.remote_jid = %s
        """,
        (instancia, remote_jid),
    )
    th = await res.fetchone()
    if th is None:
        return None
    falas = await _falas_do_cliente(conn, th["instancia"], th["remote_jid"])
    if not falas:
        return None
    return _montar(th, falas)


async def _falas_do_cliente(
    conn: AsyncConnection[dict[str, Any]], instancia: str, remote_jid: str
) -> list[str]:
    """Falas textuais do cliente (from_me=false), em ordem. Ignora turnos so-midia/vazios."""
    res = await conn.execute(
        """
        SELECT texto FROM corpus.turnos
        WHERE instancia = %s AND remote_jid = %s AND from_me = false
          AND texto IS NOT NULL AND length(btrim(texto)) > 0
        ORDER BY turno_idx
        """,
        (instancia, remote_jid),
    )
    return [str(r["texto"]).strip() for r in await res.fetchall()]


def _montar(th: dict[str, Any], falas: list[str], eixo: str = "") -> PerfilCaso:
    numeradas = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(falas))
    desfecho = th["desfecho_proxy"]
    ref = f"{th['instancia']}:{th['remote_jid']}"
    return PerfilCaso(
        nome=f"{eixo or desfecho}:{ref}",
        abertura=falas[0],
        modelo=MODELO_SINTETICA,
        roteiro_cliente=falas[1:],
        persona=_PERSONA_TMPL.format(desfecho=desfecho, falas=numeradas),
        tipo_esperado=_TIPO_PROXY.get(th["tipo_atendimento_proxy"]),
        desfecho_real=desfecho,
        label_bin=th["label_bin"],
        thread_ref=ref,
        eixo_comportamento=eixo,
    )


# Eixos de COMPORTAMENTO do cliente: cada um e uma clausula extra sobre a base (cliente iniciou,
# 2-10 falas, nao-ops). Estratifica por COMO o cliente age, nao so pelo desfecho — cobre a
# distribuicao real (literatura: personas diversas pegam falhas diferentes). A ordem e a
# prioridade na deduplicacao: uma thread entra no 1o eixo que casa, nao em dois.
_EIXOS: list[tuple[str, str]] = [
    (
        "decidido_rapido",
        "t.desfecho_proxy = 'convertido_provavel' AND t.tem_valor AND t.n_cli BETWEEN 2 AND 4",
    ),
    ("objetor", "t.objecao"),
    ("ghost_pos_cotacao", "t.ghost_pos_cotacao"),
    (
        "explorador_ambiguo",
        "t.desfecho_proxy IN ('ambiguo','qualificado_sem_prova') AND t.n_cli >= 5",
    ),
    ("pre_cotacao_sumiu", "t.desfecho_proxy = 'sem_cotacao'"),
    ("externo", "t.tipo_atendimento_proxy = 'externo'"),
]


async def extrair_nucleo(
    conn: AsyncConnection[dict[str, Any]],
    *,
    por_eixo: int = 2,
    min_cli: int = 2,
    max_cli: int = 10,
) -> list[PerfilCaso]:
    """Monta o NUCLEO de perfis estratificado por eixo de comportamento (`por_eixo` de cada).

    Dedup global por ref (prioridade = ordem de `_EIXOS`) — uma thread nunca conta em dois eixos.
    So SELECT, sem credito. Sobrepoe a selecao por-desfecho do `extrair_perfis` para cobertura.
    """
    vistos: set[str] = set()
    perfis: list[PerfilCaso] = []
    for eixo, cond in _EIXOS:
        res = await conn.execute(
            f"""
            SELECT t.instancia, t.remote_jid, t.desfecho_proxy, t.tipo_atendimento_proxy, ec.label_bin
            FROM corpus.threads t
            LEFT JOIN corpus.eval_cotacao ec USING (instancia, remote_jid)
            WHERE t.cliente_iniciou AND t.n_cli BETWEEN %(min)s AND %(max)s
              AND NOT COALESCE(t.thread_ops, false)
              AND ({cond})
            ORDER BY t.remote_jid
            """,
            {"min": min_cli, "max": max_cli},
        )
        n = 0
        for th in await res.fetchall():
            if n >= por_eixo:
                break
            ref = f"{th['instancia']}:{th['remote_jid']}"
            if ref in vistos:
                continue
            falas = await _falas_do_cliente(conn, th["instancia"], th["remote_jid"])
            if len(falas) < min_cli:
                continue
            vistos.add(ref)
            perfis.append(_montar(th, falas, eixo=eixo))
            n += 1
    return perfis
