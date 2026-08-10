"""Renderiza o conversas_chave_vendedor.html LADO A LADO: a conversa real do Vendedor (com o
cliente real, do corpus) ao lado da simulacao do agente (conduzindo um cliente-LLM ate o desfecho
terminal natural, produzida por `replay_agente_terminal.py`).

Esquerda = Vendedor real x cliente real (corpus.turnos, read-only).
Direita  = Agente x cliente-LLM (eventos do terminal_*.json), com badge de desfecho (Fechado/Perdido).

Uso (de api/, com DATABASE_URL no .env):
  uv run python ../scripts/eval_corpus/gen_conversas_comparativo.py \
      --sim /caminho/terminal_8.json
"""
import argparse
import html
import json
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

# (instancia, jid, titulo, cenario, resumo, desfecho_vendedor) na ordem de exibicao. Threads
# REAIS do corpus (@lid do cliente + resumo do que aconteceu) -> PII, fora do git.
CONVERSAS = carregar("gen_conversas_comparativo", "CONVERSAS")

# Threads cortadas num turno_idx maximo (ex.: #8 tem um 2o arco disperso apos a
# 1a visita; corta no fecho do 1o arco). jid -> ultimo turno_idx incluido.
CORTES = carregar("gen_conversas_comparativo", "CORTES")

SQL = """
SELECT from_me, ts_inicio, texto, tem_midia, tipos
FROM corpus.turnos
WHERE instancia = %s AND remote_jid = %s AND turno_idx <= %s
ORDER BY turno_idx
"""


def _br(texto: str) -> str:
    return re.sub(r"\n+", "<br>", html.escape(texto))


def _dedup_bolhas(texto: str) -> str:
    """Corrige o artefato de ingestao (ex.: eb03 53807434191057) onde cada bolha
    foi gravada em dobro: colapsa SO quando o texto inteiro e um padrao perfeito
    A/A/B/B (toda linha par igual a seguinte). Threads normais nao casam e ficam
    byte-identicas."""
    linhas = texto.split("\n")
    if len(linhas) >= 2 and len(linhas) % 2 == 0 and all(
        linhas[i] == linhas[i + 1] for i in range(0, len(linhas), 2)
    ):
        return "\n".join(linhas[::2])
    return texto


def _render_quote(texto: str) -> str:
    """[quote: x] vira um balao citado embutido (como o reply do WhatsApp)."""
    def sub(m: re.Match[str]) -> str:
        return f'<span class="quote">{_br(m.group(1).strip())}</span>'
    return re.sub(r"\[quote:\s*(.*?)\]", sub, texto, flags=re.DOTALL)


def _midia_rotulo(tem_midia: bool, tipos) -> str | None:
    if not tem_midia:
        return None
    t = ",".join(tipos) if tipos else ""
    if "image" in t:
        return "foto"
    if "video" in t:
        return "video"
    if "audio" in t or "ptt" in t:
        return "audio"
    return "midia"


def _bolha(lado: str, quem: str, corpo: str, hora: str = "") -> str:
    h = f'<span class="hora">{hora}</span>' if hora else ""
    return (f'<div class="row {lado}"><div class="bubble">'
            f'<span class="quem">{quem}</span>{corpo}{h}</div></div>')


def render_vendedor(rows) -> str:
    """Uma linha do turno = uma bolha (paridade visual com o lado do Agente, onde cada bolha do
    ClienteLLM/IA ja e uma mensagem separada — sem isso o lado real fica empilhado num balao so
    enquanto o simulado aparece quebrado, dando a falsa impressao de conversas diferentes)."""
    out = []
    for from_me, ts, texto, tem_midia, tipos in rows:
        lado = "v" if from_me else "c"
        quem = "Vendedor (modelo)" if from_me else "Cliente"
        hora = ts.strftime("%d/%m %H:%M") if ts else ""
        rot = _midia_rotulo(tem_midia, tipos)
        linhas = [ln for ln in _dedup_bolhas(texto).split("\n") if ln.strip()] if texto else []
        if not linhas:
            corpo = f'<span class="midia">[{rot}]</span>' if rot else '<span class="vazio">(sem texto)</span>'
            out.append(_bolha(lado, quem, corpo, hora))
            continue
        for i, linha in enumerate(linhas):
            corpo = _br(linha)
            if i == 0 and rot:
                corpo = f'<span class="midia">[{rot}]</span> {corpo}'
            out.append(_bolha(lado, quem, corpo, hora if i == len(linhas) - 1 else ""))
    return "\n".join(out)


def render_agente(eventos) -> str:
    out = []
    for e in eventos:
        lado, tipo = e["lado"], e["tipo"]
        if lado == "MODELO" and tipo == "comando":
            res = e.get("resultado", "")
            cls = "fechado" if res == "Fechado" else "perdido"
            icon = "✅" if res == "Fechado" else "❌"
            out.append(
                f'<div class="terminal {cls}">📋 modelo no grupo de Coordenacao: '
                f'<b>{html.escape(e["texto"])}</b> &rarr; {html.escape(res)} {icon}</div>'
            )
            continue
        if tipo == "midia":
            if lado == "IA":  # midia enviada pela IA (Midia exclusiva) -> lado da modelo
                rot = e.get("rotulo") or "midia exclusiva"
                out.append(_bolha("v", "Agente (IA)",
                                  f'<span class="midia">[{html.escape(rot)}]</span>'))
            else:
                rot = e.get("rotulo") or "midia"
                out.append(_bolha("c", "Cliente",
                                  f'<span class="midia">[{html.escape(rot)}]</span>'))
            continue
        # texto
        if lado == "C":
            out.append(_bolha("c", "Cliente", _br(e["texto"])))
        else:  # IA -> lado da modelo (numero operado pela IA); 1 balao por chunk (\n\n)
            for chunk in re.split(r"\n{2,}", e["texto"].strip()):
                if chunk.strip():
                    out.append(_bolha("v", "Agente (IA)", _render_quote(chunk.strip())))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", required=True, help="JSON do replay_agente_terminal.py")
    ap.add_argument("--out", default=str(
        Path(__file__).resolve().parents[2] / "conversas_chave_vendedor.html"))
    args = ap.parse_args()

    sim = json.load(open(args.sim, encoding="utf-8"))
    por_ref = {r["ref"]: r for r in sim["resultados"]}

    chats = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for inst, jid, titulo, cenario, resumo, desf_v in CONVERSAS:
            ref = f"{inst}:{jid}"
            rows = conn.execute(SQL, (inst, jid, CORTES.get(jid, 10**9))).fetchall()
            r = por_ref.get(ref, {})
            chats.append({
                "ref": ref, "titulo": titulo, "cenario": cenario, "resumo": resumo,
                "inst": inst, "jid": jid, "n_v": len(rows),
                "desf_v": desf_v,
                "bolhas_v": render_vendedor(rows),
                "bolhas_a": render_agente(r.get("eventos", [])),
                "desf_a": r.get("desfecho_sim"),
                "valor_a": r.get("valor_final"),
                "motivo_a": r.get("motivo_perda"),
                "erro_a": r.get("erro"),
            })

    indice = "\n".join(
        f'<li><a href="#c{i}"><b>{i+1}. {html.escape(c["titulo"])}</b>'
        f' — {html.escape(c["cenario"])}</a></li>'
        for i, c in enumerate(chats)
    )

    def badge(desf, valor=None, motivo=None):
        if not desf:
            return '<span class="badge na">sem dado</span>'
        if desf in ("Convertido", "Fechado"):
            cls = "ok"
        elif desf in ("Inconclusivo", "Ambiguo", "Ambíguo", "Sem cotacao", "Sem cotação"):
            cls = "na"
        else:
            cls = "perd"
        extra = ""
        if valor:
            extra = f" · R${html.escape(str(valor))}"
        elif motivo:
            extra = f" · {html.escape(str(motivo))}"
        return f'<span class="badge {cls}">{html.escape(desf)}{extra}</span>'

    secoes = []
    for i, c in enumerate(chats):
        if c["erro_a"]:
            col_a = (f'<div class="thread erro">Falha na simulacao: '
                     f'{html.escape(str(c["erro_a"]))}</div>')
        else:
            col_a = f'<div class="thread">{c["bolhas_a"]}</div>'
        secoes.append(f"""
<section class="chat" id="c{i}">
  <header>
    <h2>{i+1}. {html.escape(c["titulo"])}</h2>
    <p class="cenario">{html.escape(c["cenario"])}</p>
    <p class="resumo">{html.escape(c["resumo"])}</p>
    <p class="meta">{c["inst"]} · {html.escape(c["jid"])}</p>
  </header>
  <div class="comparativo">
    <div class="coluna">
      <div class="coluna-head">Vendedor real <span class="sub2">· cliente real</span>
        {badge(c["desf_v"])}</div>
      <div class="thread">{c["bolhas_v"]}</div>
    </div>
    <div class="coluna">
      <div class="coluna-head">Agente <span class="sub2">· cliente-LLM</span>
        {badge(c["desf_a"], c["valor_a"], c["motivo_a"])}</div>
      {col_a}
    </div>
  </div>
</section>""")

    pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Conversas-chave: Vendedor real x Agente (cliente-LLM) — Elite Baby</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif;
         background:#f0f2f5; color:#111; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:24px 16px 80px; }}
  h1 {{ font-size:24px; margin:0 0 4px; }}
  .sub {{ color:#555; margin:0 0 24px; font-size:14px; line-height:1.5; }}
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
  .comparativo {{ display:grid; grid-template-columns:1fr 1fr; gap:0; }}
  @media (max-width:820px) {{ .comparativo {{ grid-template-columns:1fr; }} }}
  .coluna {{ border-right:1px solid #e0e0e0; }}
  .coluna:last-child {{ border-right:none; }}
  .coluna-head {{ padding:10px 14px; font-size:13px; font-weight:700; color:#333;
                  background:#f7f9fa; border-bottom:1px solid #e8e8e8;
                  display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .sub2 {{ font-weight:400; color:#888; }}
  .badge {{ margin-left:auto; font-size:11px; font-weight:700; padding:2px 9px;
            border-radius:999px; }}
  .badge.ok {{ background:#d9fdd3; color:#0a6b2e; }}
  .badge.perd {{ background:#ffe0e0; color:#a11; }}
  .badge.na {{ background:#eee; color:#888; }}
  .thread {{ padding:16px 14px; min-height:120px;
             background:#efeae2 url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Ccircle cx='20' cy='20' r='1' fill='%23d9d2c8'/%3E%3C/svg%3E"); }}
  .thread.erro {{ color:#a11; font-size:13px; font-style:italic; }}
  .row {{ display:flex; margin-bottom:8px; }}
  .row.c {{ justify-content:flex-start; }}
  .row.v {{ justify-content:flex-end; }}
  .bubble {{ max-width:82%; padding:7px 10px 18px; border-radius:8px;
             font-size:14px; line-height:1.38; position:relative;
             box-shadow:0 1px 1px rgba(0,0,0,.08); word-wrap:break-word; }}
  .row.c .bubble {{ background:#fff; border-top-left-radius:2px; }}
  .row.v .bubble {{ background:#d9fdd3; border-top-right-radius:2px; }}
  .quem {{ display:block; font-size:11px; font-weight:700; margin-bottom:2px; }}
  .row.c .quem {{ color:#e542a3; }}
  .row.v .quem {{ color:#075e54; }}
  .hora {{ position:absolute; right:8px; bottom:3px; font-size:10px; color:#667781; }}
  .quote {{ display:block; border-left:3px solid #06cf9c; background:rgba(6,207,156,.08);
            padding:3px 8px; margin:0 0 4px; border-radius:4px; font-size:13px; color:#555; }}
  .midia {{ display:inline-block; background:#cfd8dc; color:#37474f;
            border-radius:4px; padding:0 5px; font-size:12px; font-weight:600; }}
  .vazio {{ color:#999; font-style:italic; }}
  .terminal {{ text-align:center; font-size:12.5px; margin:12px auto; padding:7px 12px;
               border-radius:8px; max-width:90%; }}
  .terminal.fechado {{ background:#d9fdd3; color:#0a6b2e; }}
  .terminal.perdido {{ background:#ffe0e0; color:#a11; }}
  .top {{ position:fixed; right:18px; bottom:18px; background:#075e54; color:#fff;
          border-radius:50%; width:46px; height:46px; display:flex;
          align-items:center; justify-content:center; text-decoration:none;
          font-size:20px; box-shadow:0 2px 6px rgba(0,0,0,.3); }}
</style></head>
<body><div class="wrap">
  <h1>Conversas-chave: Vendedor real &times; Agente (cliente-LLM)</h1>
  <p class="sub">A esquerda, o atendimento real do Vendedor humano com o cliente real (corpus
     Elite Baby). A direita, o <b>agente</b> conduzindo um <b>cliente-LLM</b> que parte da mesma
     persona/abertura mas <b>reage de fato ao que o agente diz</b> — ate um desfecho terminal
     natural (Fechado/Perdido). Cliente a esquerda de cada coluna (rosa); Vendedor/Agente a
     direita (verde). O fechamento e cravado pela modelo no grupo de Coordenacao, como em producao.
     <br><b>Atencao:</b> a coluna do Vendedor e o humano real, de qualidade <b>variavel</b> — inclui
     anti-padroes que o agente <b>nao</b> deve imitar (ex.: #4 nunca cota; #7 estorna Pix; #13 pickup,
     fluxo descartado). Nao e gabarito de conduta, e o estimulo real + baseline humano. O badge de
     desfecho vem do proxy do corpus; onde a conversa nao mostra o fechamento, marca-se
     <i>Inconclusivo</i>.</p>
  <nav class="toc"><h3>Cenarios</h3><ul>{indice}</ul></nav>
  {''.join(secoes)}
</div><a class="top" href="#" title="topo">&uarr;</a></body></html>"""

    Path(args.out).write_text(pagina, encoding="utf-8")
    print(f"OK -> {args.out} ({len(chats)} cenarios)")


if __name__ == "__main__":
    main()
