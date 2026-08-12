"""Ingestão incremental do corpus a partir do Procex Chat (procex_chat.wa_messages).

Contexto (2026-08): os 4 celulares dos vendedores foram re-pareados em 07/08 no EvoGo
como instâncias `elitebaby*` do Procex Chat, que sincroniza as mensagens em
`procex_chat.wa_messages` — no MESMO Postgres do schema `corpus`. A Fase 0 original
(Evolution REST `findMessages` das eb01–eb04) parou em 12/06; este script cobre a
continuação sem sair do banco.

O que faz, por instância `elitebaby%`:
  1. INSERT em corpus.mensagens_raw (`ev_id = 'pcx:' || wa_messages.id`, ON CONFLICT
     DO NOTHING — idempotente); exclui grupos (@g.us), broadcast e deletadas.
  2. Rebuild de corpus.turnos SÓ dos pares (instancia, remote_jid) tocados —
     gaps-and-islands: bolhas consecutivas do mesmo lado colapsam num turno,
     sem quebra por gap de tempo (mesma convenção da Fase 0).
  3. Upsert de corpus.threads dos pares tocados com os campos ESTRUTURAIS
     (contagens, lados, horas) e flags por regex (proveniência v2 — as regex da
     Fase 0 não foram versionadas; estas são aproximações documentadas abaixo).
     `desfecho_proxy`/`tipo_atendimento_proxy` ficam NULL de propósito: a varredura
     semântica (fichas via Claude) é quem rotula desfecho — não este script.

Diferenças duráveis vs corpus antigo:
  - remote_jid aqui é E.164@s.whatsapp.net (não @lid) — ESTES threads casam com o
    painel; os antigos continuam irrecuperáveis (PONTE_LID_TELEFONE.md).
  - `thread_ops` = heurística por lista de números internos (telefones das próprias
    instâncias da organização + números ProceX), não por conteúdo.

Uso:
    cd api && uv run python ../scripts/eval_corpus/ingest_incremental.py [--dry-run]

Env: DATABASE_URL (escreve APENAS no schema corpus; wa_* é leitura).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

import psycopg
from psycopg.rows import dict_row

INSTANCIAS_LIKE = "elitebaby%"

# Números internos da operação (donos das instâncias da org + linhas ProceX vistas em
# procex_chat.wa_instances). Conversa com eles é coordenação, não cliente.
NUMEROS_INTERNOS = {
    "5521995346564",  # elitebaby
    "5521998564625",  # elitebaby2
    "5521960145522",  # elitebaby3
    "5521984089974",  # elitebaby4 / elitebaby01
    "5519997858650",  # procex / procex-teste
    "5519998389055",  # ProceX-2
    "5519981201085",  # davialmeida
}

RE_VALOR = re.compile(r"(?:r\$\s*)?\b\d{3}(?:[.,]\d{2})?\b|\b\d{1,2}\s*(?:hs?|hora)", re.I)
RE_PIX = re.compile(r"\bpix\b", re.I)
RE_LOCAL = re.compile(r"\blocal\b|\bendere[cç]o\b|\bonde\s+(?:fica|voc[eê])\b", re.I)
RE_SAIDA = re.compile(r"\bdomic[ií]lio\b|\bvou\s+at[eé]\b|\bsa[ií]da\b|\bat[eé]\s+voc[eê]\b", re.I)
RE_ENDERECO = re.compile(r"\b(?:rua|av\.?|avenida|aquidab[aã])\b\s+\S+", re.I)
RE_AGENDA = re.compile(r"\bconfirmad[oa]\b|\bfechado\s+ent[aã]o\b|\bte\s+espero\s+[aà]s?\b", re.I)
RE_CHEGADA = re.compile(r"\bchegu?ei\b|\bchegando\b|\bt[oô]\s+aqui\b|\bna\s+porta\b", re.I)
RE_QUARTO = re.compile(r"\bandar\b|\bapto?\b|\bapartamento\b|\bquarto\s+\d", re.I)
RE_COMPROVANTE = re.compile(r"\bcomprovante\b", re.I)
RE_OBJECAO = re.compile(r"\bcar[oa]\b|\bmuito\s+alto\b|\bn[aã]o\s+tenho\s+(?:tudo\s+)?isso\b", re.I)
RE_NEGOU = re.compile(r"\bn[aã]o\s+(?:vou|quero|d[aá]|rola)\b|\bdeixa\s+pra\s+pr[oó]xima\b", re.I)

SQL_INSERT_RAW = """
INSERT INTO corpus.mensagens_raw
    (instancia, ev_id, msg_id, remote_jid, from_me, push_name, message_type, ts, texto, raw)
SELECT i.name,
       'pcx:' || m.id,
       m.whatsapp_id,
       c.jid,
       m.from_me,
       m.sender_name,
       m.type,
       m.timestamp,
       m.content,
       jsonb_build_object('fonte', 'procex_chat', 'wa_message_id', m.id,
                          'conversation_id', m.conversation_id, 'status', m.status,
                          'media_mime', m.media_mime, 'quoted_message_id', m.quoted_message_id)
FROM procex_chat.wa_messages m
JOIN procex_chat.wa_conversations c ON c.id = m.conversation_id
JOIN procex_chat.wa_instances i ON i.id = m.instance_id
WHERE i.name ILIKE %(like)s
  AND c.jid NOT LIKE '%%@g.us'
  AND c.jid NOT LIKE '%%@broadcast'
  AND NOT m.is_deleted
ON CONFLICT (instancia, ev_id) DO NOTHING
RETURNING instancia, remote_jid
"""

SQL_REBUILD_TURNOS = """
WITH bolhas AS (
    SELECT instancia, remote_jid, from_me, ts, message_type, texto,
           row_number() OVER w AS rn,
           row_number() OVER w
             - row_number() OVER (PARTITION BY instancia, remote_jid, from_me ORDER BY ts, ev_id)
             AS ilha
    FROM corpus.mensagens_raw
    WHERE (instancia, remote_jid) IN (SELECT instancia, remote_jid FROM tocados)
      AND message_type <> 'protocolMessage'
    WINDOW w AS (PARTITION BY instancia, remote_jid ORDER BY ts, ev_id)
)
INSERT INTO corpus.turnos
    (instancia, remote_jid, from_me, turno_idx, ts_inicio, ts_fim, n_bolhas, tipos, texto, tem_midia)
SELECT instancia, remote_jid, from_me,
       dense_rank() OVER (PARTITION BY instancia, remote_jid ORDER BY min(rn)),
       min(ts), max(ts), count(*),
       array_agg(DISTINCT message_type),
       NULLIF(string_agg(NULLIF(btrim(texto), ''), E'\n' ORDER BY rn), ''),
       bool_or(message_type <> 'text')
FROM bolhas
GROUP BY instancia, remote_jid, from_me, ilha
"""


def _flags_thread(turnos: list[dict]) -> dict:
    vend = [t["texto"] or "" for t in turnos if t["from_me"]]
    cli = [t["texto"] or "" for t in turnos if not t["from_me"]]
    vend_txt, cli_txt, tudo = "\n".join(vend), "\n".join(cli), "\n".join(
        t["texto"] or "" for t in turnos
    )
    return {
        "tem_valor": bool(RE_VALOR.search(vend_txt)),
        "tem_pix": bool(RE_PIX.search(tudo)),
        "tem_local": bool(RE_LOCAL.search(tudo)),
        "tem_saida": bool(RE_SAIDA.search(tudo)),
        "tem_endereco": bool(RE_ENDERECO.search(vend_txt)),
        "tem_localizacao_msg": any("location" in (t["tipos"] or []) for t in turnos),
        "vend_video": any(t["from_me"] and "video" in (t["tipos"] or []) for t in turnos),
        "vend_foto": any(t["from_me"] and "image" in (t["tipos"] or []) for t in turnos),
        "cli_audio": any(not t["from_me"] and "audio" in (t["tipos"] or []) for t in turnos),
        "agenda_firme": bool(RE_AGENDA.search(tudo)),
        "sinal_chegada": bool(RE_CHEGADA.search(cli_txt)),
        "sinal_quarto": bool(RE_QUARTO.search(vend_txt)),
        "sinal_comprovante": bool(RE_COMPROVANTE.search(tudo)),
        "objecao": bool(RE_OBJECAO.search(cli_txt)),
        "negou": bool(RE_NEGOU.search(cli_txt)),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="roda tudo e dá ROLLBACK no fim")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL não setada")

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(SQL_INSERT_RAW, {"like": INSTANCIAS_LIKE})
            novos = await cur.fetchall()
            tocados = sorted({(r["instancia"], r["remote_jid"]) for r in novos})
            print(f"mensagens novas: {len(novos)} | pares tocados: {len(tocados)}")
            if not tocados:
                await conn.rollback()
                return

            await cur.execute(
                "CREATE TEMP TABLE tocados (instancia text, remote_jid text) ON COMMIT DROP"
            )
            async with cur.copy("COPY tocados FROM STDIN") as copy:
                for par in tocados:
                    await copy.write_row(par)

            await cur.execute(
                "DELETE FROM corpus.turnos WHERE (instancia, remote_jid) IN "
                "(SELECT instancia, remote_jid FROM tocados)"
            )
            await cur.execute(SQL_REBUILD_TURNOS)
            print(f"turnos reconstruídos: {cur.rowcount}")

            await cur.execute(
                "DELETE FROM corpus.threads WHERE (instancia, remote_jid) IN "
                "(SELECT instancia, remote_jid FROM tocados)"
            )
            n_threads = 0
            for instancia, jid in tocados:
                await cur.execute(
                    "SELECT from_me, texto, tipos, ts_inicio, ts_fim FROM corpus.turnos "
                    "WHERE instancia=%s AND remote_jid=%s ORDER BY turno_idx",
                    (instancia, jid),
                )
                turnos = await cur.fetchall()
                if not turnos:
                    continue
                flags = _flags_thread(turnos)
                horas = (turnos[-1]["ts_fim"] - turnos[0]["ts_inicio"]).total_seconds() / 3600
                await cur.execute(
                    """
                    INSERT INTO corpus.threads
                        (instancia, remote_jid, n_turnos, n_cli, n_vend, cliente_iniciou,
                         tem_valor, tem_pix, tem_local, tem_saida, tem_endereco,
                         tem_localizacao_msg, vend_video, vend_foto, cli_audio, agenda_firme,
                         sinal_chegada, sinal_quarto, sinal_comprovante, thread_ops,
                         ghost_pos_cotacao, objecao, negou, ultimo_lado, horas,
                         desfecho_proxy, tipo_atendimento_proxy)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,NULL,NULL)
                    """,
                    (
                        instancia,
                        jid,
                        len(turnos),
                        sum(1 for t in turnos if not t["from_me"]),
                        sum(1 for t in turnos if t["from_me"]),
                        not turnos[0]["from_me"],
                        flags["tem_valor"],
                        flags["tem_pix"],
                        flags["tem_local"],
                        flags["tem_saida"],
                        flags["tem_endereco"],
                        flags["tem_localizacao_msg"],
                        flags["vend_video"],
                        flags["vend_foto"],
                        flags["cli_audio"],
                        flags["agenda_firme"],
                        flags["sinal_chegada"],
                        flags["sinal_quarto"],
                        flags["sinal_comprovante"],
                        jid.split("@")[0] in NUMEROS_INTERNOS,
                        _ghost(turnos),
                        flags["objecao"],
                        flags["negou"],
                        "vend" if turnos[-1]["from_me"] else "cli",
                        round(horas, 2),
                    ),
                )
                n_threads += 1
            print(f"threads upsertadas: {n_threads}")

            if args.dry_run:
                await conn.rollback()
                print("DRY-RUN: rollback")
            else:
                await conn.commit()
                print("COMMIT")


def _ghost(turnos: list[dict]) -> bool:
    idx = next(
        (i for i, t in enumerate(turnos) if t["from_me"] and RE_VALOR.search(t["texto"] or "")),
        None,
    )
    return idx is not None and not any(not t["from_me"] for t in turnos[idx + 1 :])


if __name__ == "__main__":
    asyncio.run(main())
