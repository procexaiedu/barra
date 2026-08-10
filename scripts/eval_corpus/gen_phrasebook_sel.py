"""Gera, por momento do funil, um .sql pronto que puxa o transcript real das threads
que a ficha (fichas_threads.jsonl) marca naquele momento. Cada .sql embute a lista de
pares (instancia, remote_jid) como VALUES e e rodado verbatim pelo agente do momento.
Read-only sobre corpus.turnos. Saida em scripts/eval_corpus/_phrasebook/<momento>.sql.
"""
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
JSONL = os.path.join(AQUI, "fichas_threads.jsonl")
OUTDIR = os.path.join(AQUI, "_phrasebook")
CAP = 40  # threads por momento — suficiente pra agrupar padroes recorrentes

fichas = [json.loads(l) for l in open(JSONL, encoding="utf-8") if l.strip()]


def cond(f, conf=0.6):
    return f.get("confianca", 0) >= conf and f.get("tag_qualidade") != "ops_ruido"


def tem(f, campo, val):
    return val in (f.get(campo) or [])


# momento -> filtro (cada filtro recebe a ficha e devolve bool)
MOMENTOS = {
    "abertura": lambda f: cond(f) and f.get("estagio_max") != "saudacao_only",
    "sondagem": lambda f: cond(f) and f.get("estagio_max") in ("sondagem", "cotou", "negociou", "combinou", "prova_vinda"),
    "cotacao": lambda f: cond(f) and tem(f, "conduta_vendedor", "cotacao_limpa"),
    "objecao_preco": lambda f: cond(f) and tem(f, "objecoes", "preco"),
    "recusa_desconto": lambda f: tem(f, "conduta_vendedor", "recusou_desconto"),  # so 47, pega todos
    "desconto_concedido": lambda f: cond(f, 0.5) and tem(f, "conduta_vendedor", "deu_desconto"),
    "ancora_horario": lambda f: cond(f) and tem(f, "conduta_vendedor", "ancora_horario"),
    "logistica": lambda f: cond(f) and f.get("estagio_max") in ("combinou", "prova_vinda"),
}

os.makedirs(OUTDIR, exist_ok=True)
resumo = {}
for nome, filtro in MOMENTOS.items():
    sel = [(f["instancia"], f["remote_jid"]) for f in fichas if filtro(f)]
    # dedup + cap deterministico (ordena por jid)
    sel = sorted(set(sel), key=lambda x: (x[1], x[0]))[:CAP]
    values = ",\n    ".join(f"('{i}','{j}')" for i, j in sel)
    sql = f"""-- momento: {nome} | {len(sel)} threads (ficha)
WITH sel(instancia, remote_jid) AS (VALUES
    {values}
)
SELECT t.instancia, t.remote_jid, t.turno_idx, t.from_me,
       COALESCE(NULLIF(btrim(t.texto),''),
                CASE WHEN t.tem_midia THEN '[midia]' ELSE '[--]' END) AS texto
FROM corpus.turnos t JOIN sel USING (instancia, remote_jid)
WHERE t.turno_idx <= 60
ORDER BY t.remote_jid, t.instancia, t.turno_idx
"""
    open(os.path.join(OUTDIR, f"{nome}.sql"), "w", encoding="utf-8").write(sql)
    resumo[nome] = len(sel)

print(json.dumps(resumo, indent=2))
