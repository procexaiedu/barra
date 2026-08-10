"""Persiste os labels de um workflow de rotulagem (cotacao|perda) nas tabelas corpus.eval_*.

Lê o output file do workflow direto do disco (não passa pelo contexto do agente) e faz
upsert idempotente via jsonb_to_recordset (escaping nativo de aspas/emoji/jsonb).
desfecho_proxy vem por JOIN em corpus.threads; hold_out = (instancia='eb04').

Uso:  DATABASE_URL=... python persistir.py <cotacao|perda> <output_file.json>
"""
import json
import os
import sys

import psycopg

UPSERT = {
    "cotacao": """
        INSERT INTO corpus.eval_cotacao
          (instancia, remote_jid, reacao_real, label_bin, n_juizes, n_votos,
           concordancia, votos, justificativa, cotacao_turno, desfecho_proxy, hold_out)
        SELECT x.instancia, x.remote_jid, x.reacao_real, x.label_bin, x.n_juizes, x.n_votos,
               x.concordancia, x.votos, x.justificativa, x.cotacao_turno,
               t.desfecho_proxy, (x.instancia = 'eb04')
        FROM jsonb_to_recordset(%s::jsonb) AS x(
          instancia text, remote_jid text, reacao_real text, label_bin text,
          n_juizes int, n_votos int, concordancia numeric, votos jsonb,
          justificativa text, cotacao_turno int)
        JOIN corpus.threads t USING (instancia, remote_jid)
        ON CONFLICT (instancia, remote_jid) DO UPDATE SET
          reacao_real=EXCLUDED.reacao_real, label_bin=EXCLUDED.label_bin,
          n_juizes=EXCLUDED.n_juizes, n_votos=EXCLUDED.n_votos, concordancia=EXCLUDED.concordancia,
          votos=EXCLUDED.votos, justificativa=EXCLUDED.justificativa,
          cotacao_turno=EXCLUDED.cotacao_turno, desfecho_proxy=EXCLUDED.desfecho_proxy,
          hold_out=EXCLUDED.hold_out, criado_em=now();
    """,
    "perda": """
        INSERT INTO corpus.eval_perda
          (instancia, remote_jid, motivo, declarado, bloco_grosso, n_juizes, n_votos,
           concordancia, votos, justificativa, obs, desfecho_proxy, hold_out)
        SELECT x.instancia, x.remote_jid, x.motivo, x.declarado, x.bloco_grosso, x.n_juizes, x.n_votos,
               x.concordancia, x.votos, x.justificativa, NULLIF(x.obs, ''),
               t.desfecho_proxy, (x.instancia = 'eb04')
        FROM jsonb_to_recordset(%s::jsonb) AS x(
          instancia text, remote_jid text, motivo text, declarado boolean, bloco_grosso text,
          n_juizes int, n_votos int, concordancia numeric, votos jsonb,
          justificativa text, obs text)
        JOIN corpus.threads t USING (instancia, remote_jid)
        ON CONFLICT (instancia, remote_jid) DO UPDATE SET
          motivo=EXCLUDED.motivo, declarado=EXCLUDED.declarado, bloco_grosso=EXCLUDED.bloco_grosso,
          n_juizes=EXCLUDED.n_juizes, n_votos=EXCLUDED.n_votos, concordancia=EXCLUDED.concordancia,
          votos=EXCLUDED.votos, justificativa=EXCLUDED.justificativa, obs=EXCLUDED.obs,
          desfecho_proxy=EXCLUDED.desfecho_proxy, hold_out=EXCLUDED.hold_out, criado_em=now();
    """,
    "judge": """
        INSERT INTO corpus.eval_judge_pred
          (instancia, remote_jid, outcome_pred, rubric_score, f_warmth, f_bare,
           f_glued_urgency, f_glued_question, f_media_fria, confianca, run_tag)
        SELECT x.instancia, x.remote_jid, x.outcome_pred, x.rubric_score, x.f_warmth, x.f_bare,
               x.f_glued_urgency, x.f_glued_question, x.f_media_fria, x.confianca, 'v1'
        FROM jsonb_to_recordset(%s::jsonb) AS x(
          instancia text, remote_jid text, outcome_pred text, rubric_score numeric,
          f_warmth boolean, f_bare boolean, f_glued_urgency boolean, f_glued_question boolean,
          f_media_fria boolean, confianca numeric)
        ON CONFLICT (instancia, remote_jid, run_tag) DO UPDATE SET
          outcome_pred=EXCLUDED.outcome_pred, rubric_score=EXCLUDED.rubric_score,
          f_warmth=EXCLUDED.f_warmth, f_bare=EXCLUDED.f_bare, f_glued_urgency=EXCLUDED.f_glued_urgency,
          f_glued_question=EXCLUDED.f_glued_question, f_media_fria=EXCLUDED.f_media_fria,
          confianca=EXCLUDED.confianca, criado_em=now();
    """,
}


def main() -> None:
    tabela, path = sys.argv[1], sys.argv[2]
    if tabela not in UPSERT:
        sys.exit(f"tabela inválida: {tabela} (use cotacao|perda)")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL não encontrada")

    doc = json.load(open(path))
    res = doc["result"]
    labels = res["preds"] if tabela == "judge" else res["labels"]
    print(f"registros no output: {len(labels)}")

    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('corpus.eval_cotacao'), to_regclass('corpus.eval_perda')"
            )
            cot, per = cur.fetchone()
            if cot is None or per is None:
                sys.exit("tabelas corpus.eval_* não existem neste banco — DSN diverge do MCP?")
            cur.execute(UPSERT[tabela], (json.dumps(labels, ensure_ascii=False),))
            print(f"linhas afetadas: {cur.rowcount}")
        conn.commit()


if __name__ == "__main__":
    main()
