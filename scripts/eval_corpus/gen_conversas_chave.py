"""Gera um HTML com conversas-chave do corpus do Vendedor (read-only).

Seleciona 7 threads reais que cobrem os cenarios-chave que o agente precisa
replicar e renderiza cada uma como um chat estilo WhatsApp, para o Fernando
comparar o atendimento do agente com o do Vendedor humano.

Read-only sobre corpus.turnos (Postgres prod self-hosted). Sem prod-write.
"""
import html
import os
import re
from pathlib import Path

import psycopg

from dados_reais import carregar

ENV = Path(__file__).resolve().parents[2] / "api" / ".env"
for linha in ENV.read_text().splitlines():
    if linha.startswith("DATABASE_URL="):
        os.environ["DATABASE_URL"] = linha.split("=", 1)[1].strip()
        break

# (instancia, jid, titulo, cenario, resumo) na ordem de exibicao. Threads REAIS do corpus
# (@lid do cliente + resumo do que aconteceu) -> PII, fora do git (ver dados_reais.py).
CONVERSAS = carregar("gen_conversas_chave", "CONVERSAS")

SQL = """
SELECT turno_idx, from_me, ts_inicio, texto, n_bolhas, tem_midia, tipos
FROM corpus.turnos
WHERE instancia = %s AND remote_jid = %s
ORDER BY turno_idx
"""


def render_texto(texto: str | None, tem_midia: bool, tipos) -> str:
    partes = []
    if tem_midia:
        rotulo = "midia"
        if tipos:
            t = ",".join(tipos)
            if "image" in t:
                rotulo = "foto"
            elif "video" in t:
                rotulo = "video"
            elif "audio" in t or "ptt" in t:
                rotulo = "audio"
        partes.append(f'<span class="midia">[{rotulo}]</span>')
    if texto:
        esc = html.escape(texto)
        esc = re.sub(r"\n+", "<br>", esc)
        partes.append(esc)
    return " ".join(partes) if partes else '<span class="vazio">(sem texto)</span>'


def main() -> None:
    chats = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for inst, jid, titulo, cenario, resumo in CONVERSAS:
            rows = conn.execute(SQL, (inst, jid)).fetchall()
            bolhas = []
            for _idx, from_me, ts, texto, _nb, tem_midia, tipos in rows:
                lado = "v" if from_me else "c"
                quem = "Vendedor (modelo)" if from_me else "Cliente"
                hora = ts.strftime("%d/%m %H:%M") if ts else ""
                corpo = render_texto(texto, tem_midia, tipos)
                bolhas.append(
                    f'<div class="row {lado}"><div class="bubble">'
                    f'<span class="quem">{quem}</span>{corpo}'
                    f'<span class="hora">{hora}</span></div></div>'
                )
            chats.append({
                "titulo": titulo, "cenario": cenario, "resumo": resumo,
                "inst": inst, "jid": jid, "n": len(rows),
                "bolhas": "\n".join(bolhas),
            })

    indice = "\n".join(
        f'<li><a href="#c{i}"><b>{i+1}. {html.escape(c["titulo"])}</b>'
        f' — {html.escape(c["cenario"])}</a></li>'
        for i, c in enumerate(chats)
    )
    secoes = []
    for i, c in enumerate(chats):
        secoes.append(f"""
<section class="chat" id="c{i}">
  <header>
    <h2>{i+1}. {html.escape(c["titulo"])}</h2>
    <p class="cenario">{html.escape(c["cenario"])}</p>
    <p class="resumo">{html.escape(c["resumo"])}</p>
    <p class="meta">{c["inst"]} · {html.escape(c["jid"])} · {c["n"]} turnos</p>
  </header>
  <div class="thread">{c["bolhas"]}</div>
</section>""")

    pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Conversas-chave do Vendedor — Elite Baby</title>
<style>
  :root {{ --c:#e8e8e8; --v:#d9fdd3; --bg:#0b141a; --panel:#111b21; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif;
         background:#f0f2f5; color:#111; }}
  .wrap {{ max-width:860px; margin:0 auto; padding:24px 16px 80px; }}
  h1 {{ font-size:24px; margin:0 0 4px; }}
  .sub {{ color:#555; margin:0 0 24px; font-size:14px; }}
  .toc {{ background:#fff; border:1px solid #e0e0e0; border-radius:12px;
          padding:16px 20px; margin-bottom:28px; }}
  .toc h3 {{ margin:0 0 10px; font-size:14px; text-transform:uppercase;
             letter-spacing:.5px; color:#667; }}
  .toc ul {{ margin:0; padding-left:18px; line-height:1.9; font-size:14px; }}
  .toc a {{ color:#075e54; text-decoration:none; }}
  .toc a:hover {{ text-decoration:underline; }}
  .chat {{ background:#fff; border:1px solid #e0e0e0; border-radius:12px;
           overflow:hidden; margin-bottom:32px; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  .chat header {{ background:#075e54; color:#fff; padding:16px 20px; }}
  .chat header h2 {{ margin:0 0 6px; font-size:18px; }}
  .cenario {{ margin:0 0 6px; font-size:14px; font-weight:600; color:#d2f5e3; }}
  .resumo {{ margin:0 0 6px; font-size:13px; color:#cfe9e3; line-height:1.4; }}
  .meta {{ margin:0; font-size:11px; color:#9fc7bf; font-family:monospace; }}
  .thread {{ padding:18px 16px;
             background:#efeae2 url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Ccircle cx='20' cy='20' r='1' fill='%23d9d2c8'/%3E%3C/svg%3E"); }}
  .row {{ display:flex; margin-bottom:8px; }}
  .row.c {{ justify-content:flex-start; }}
  .row.v {{ justify-content:flex-end; }}
  .bubble {{ max-width:78%; padding:7px 10px 18px; border-radius:8px;
             font-size:14.5px; line-height:1.38; position:relative;
             box-shadow:0 1px 1px rgba(0,0,0,.08); word-wrap:break-word; }}
  .row.c .bubble {{ background:#fff; border-top-left-radius:2px; }}
  .row.v .bubble {{ background:var(--v); border-top-right-radius:2px; }}
  .quem {{ display:block; font-size:11px; font-weight:700; margin-bottom:2px; }}
  .row.c .quem {{ color:#e542a3; }}
  .row.v .quem {{ color:#075e54; }}
  .hora {{ position:absolute; right:8px; bottom:3px; font-size:10px; color:#667781; }}
  .midia {{ display:inline-block; background:#cfd8dc; color:#37474f;
            border-radius:4px; padding:0 5px; font-size:12px; font-weight:600; }}
  .vazio {{ color:#999; font-style:italic; }}
  .top {{ position:fixed; right:18px; bottom:18px; background:#075e54; color:#fff;
          border-radius:50%; width:46px; height:46px; display:flex;
          align-items:center; justify-content:center; text-decoration:none;
          font-size:20px; box-shadow:0 2px 6px rgba(0,0,0,.3); }}
</style></head>
<body><div class="wrap">
  <h1>Conversas-chave do Vendedor</h1>
  <p class="sub">Atendimentos reais do corpus Elite Baby (instancias eb01–04),
     selecionados para comparar lado a lado com o atendimento do agente.
     Cliente a esquerda (rosa), Vendedor/modelo a direita (verde).</p>
  <nav class="toc"><h3>Cenarios</h3><ul>{indice}</ul></nav>
  {''.join(secoes)}
</div><a class="top" href="#" title="topo">↑</a></body></html>"""

    saida = Path(__file__).resolve().parents[2] / "conversas_chave_vendedor.html"
    saida.write_text(pagina, encoding="utf-8")
    print(f"OK -> {saida} ({sum(c['n'] for c in chats)} turnos, {len(chats)} conversas)")


if __name__ == "__main__":
    main()
