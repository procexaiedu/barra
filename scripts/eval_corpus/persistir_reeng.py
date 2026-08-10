"""Persiste/agrega os votos de movimento (§13) na tabela corpus.eval_reengajamento.

reviveu/gap/midia/comprimento ja foram inseridos deterministicamente (ver reengajamento_ddl.sql
+ insert inicial). Este script SO faz UPDATE das colunas do juiz (movimento/tem_desconto/
tipo_silencio/votos/concordancia) por (instancia, remote_jid, msg_id).

Entrada: 1+ arquivos JSON, cada um = a saida de UM juiz no formato {"labels":[{...}]}.
Agrega por voto majoritario (3 juizes), desempate por confianca. Idempotente.

Uso:  DATABASE_URL=... python persistir_reeng.py juiz1.json juiz2.json juiz3.json [juiz4.json ...]
      (pode passar varios grupos: agrupa TODOS os votos do mesmo msg_id, nao importa o arquivo)
"""
import json
import os
import sys
from collections import defaultdict

import psycopg


def mode(vals):
    c = defaultdict(int)
    for v in vals:
        c[v] += 1
    best, bestn = None, 0
    for k, n in c.items():
        if n > bestn:
            best, bestn = k, n
    return best, bestn


def main():
    files = sys.argv[1:]
    if not files:
        sys.exit("uso: persistir_reeng.py juiz1.json [juiz2.json ...]")

    by_msg = defaultdict(list)
    for jidx, f in enumerate(files):
        data = json.load(open(f))
        for l in data.get("labels", []):
            k = (l["instancia"], l["remote_jid"], l["msg_id"])
            by_msg[k].append(
                {
                    "movimento": l["movimento"],
                    "tem_desconto": bool(l.get("tem_desconto", False)),
                    "tipo_silencio": l["tipo_silencio"],
                    "confianca": float(l.get("confianca", 0.0)),
                    "justificativa": l.get("justificativa", ""),
                    "juiz": jidx + 1,
                }
            )

    rows = []
    for (inst, jid, mid), votos in by_msg.items():
        mov, nv = mode([v["movimento"] for v in votos])
        if nv == 1:  # empate total -> maior confianca
            mov = sorted(votos, key=lambda v: -v["confianca"])[0]["movimento"]
        desc = mode([v["tem_desconto"] for v in votos])[0]
        sil = mode([v["tipo_silencio"] for v in votos])[0]
        maj = next((v for v in votos if v["movimento"] == mov), votos[0])
        rows.append(
            {
                "instancia": inst,
                "remote_jid": jid,
                "msg_id": mid,
                "movimento": mov,
                "tem_desconto": desc,
                "tipo_silencio": sil,
                "n_juizes": len(votos),
                "n_votos": nv,
                "concordancia": round(nv / len(votos), 3),
                "justificativa": (maj.get("justificativa") or "")[:200],
                "votos": [
                    {"m": v["movimento"], "d": v["tem_desconto"], "s": v["tipo_silencio"], "c": v["confianca"], "j": v["juiz"]}
                    for v in votos
                ],
            }
        )

    UPD = """
        UPDATE corpus.eval_reengajamento e SET
          movimento=x.movimento, tem_desconto=x.tem_desconto, tipo_silencio=x.tipo_silencio,
          n_juizes=x.n_juizes, n_votos=x.n_votos, concordancia=x.concordancia,
          votos=x.votos, justificativa=x.justificativa
        FROM jsonb_to_recordset(%s::jsonb) AS x(
          instancia text, remote_jid text, msg_id text, movimento text, tem_desconto boolean,
          tipo_silencio text, n_juizes int, n_votos int, concordancia numeric, votos jsonb,
          justificativa text)
        WHERE e.instancia=x.instancia AND e.remote_jid=x.remote_jid AND e.msg_id=x.msg_id;
    """
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        cur = c.execute(UPD, (json.dumps(rows),))
        print(f"updated {cur.rowcount} pokes ({len(rows)} codificados)")


if __name__ == "__main__":
    main()
