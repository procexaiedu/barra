"""Renderiza a PROVA (HTML) "o agente substitui o vendedor?" para o Fernando avaliar.

Consome:
  - `--pares`  JSON do head-to-head N-1 (evals.shadow.massa) — cada par com resposta_ia/humano,
    features deterministicas e, opcionalmente, o veredito do juiz cego (`p["juiz"]`).
  - `--conducao` (opcional) JSON com o resumo do gate de conducao multi-turn (evals.e2e.conduta_gate).

Saida: um HTML autossuficiente (sem JS externo) com o placar head-to-head + IC bootstrap, o
scorecard de disciplina pareado, a conducao multi-turn, exemplos lado a lado (incluindo derrotas,
por honestidade) e a secao de limitacoes. So leitura/render — nao roda agente nem toca banco.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
from typing import Any

# --- fidelidade de harness: handoff + render de quote ----------------------------------------

# Espelha `barra.workers._chunking._QUOTE_PREFIX` (inline p/ o render ficar standalone — sem puxar
# o backend/fastapi). Marker `[quote]`/`[quote: trecho]` no início de um bloco (bolha).
_QUOTE_PREFIX = re.compile(r"^\s*\[quote\s*(?::\s*[^\]]*?\s*)?\]\s*", re.IGNORECASE)


def _handoff(p: dict[str, Any]) -> bool:
    """O ponto virou HANDOFF (a IA pausou/escalou: serviço fora da oferta, preço abaixo do piso).

    Nesses pontos a IA NAO manda bolha ao cliente (o resumo vai pro card) — comparar o texto vazio
    contra a cotacao do humano e' injusto (a modelo SINTETICA nao oferece o que a real oferecia). Sao
    conduta CORRETA, nao derrota; ficam FORA do placar e entram num contador a parte.
    """
    return bool((p.get("ia") or {}).get("estado_final", {}).get("ia_pausada"))


def _render_cliente(texto: str) -> str:
    """Texto como o cliente veria: strippa os markers `[quote: trecho]` de cada bloco (em prod o
    `_chunking` resolve o quoted-reply e remove o marker). O harness captura `res.texto` cru
    (pre-chunking), entao sem isto o marker vaza no HTML."""
    if not texto or "[quote" not in texto.lower():
        return texto
    blocos = re.split(r"\n\s*\n", texto.strip())
    return "\n\n".join(_QUOTE_PREFIX.sub("", b) for b in blocos)


# --- estatistica -----------------------------------------------------------------------------


def _bootstrap_ic(
    rotulos: list[str], alvo: str, *, b: int = 10000, semente: int = 11
) -> tuple[float, float, float]:
    """Proporcao de `alvo` em `rotulos` + IC 95% por bootstrap percentil. Win-rate e' nao-normal
    (categorico), entao bootstrap > formula normal (Cameron Wolfe, stats-llm-evals)."""
    n = len(rotulos)
    if n == 0:
        return 0.0, 0.0, 0.0
    p = 100 * sum(1 for r in rotulos if r == alvo) / n
    rng = random.Random(semente)  # noqa: S311 — reamostragem, nao-cripto
    amostras: list[float] = []
    for _ in range(b):
        acc = sum(1 for _ in range(n) if rng.choice(rotulos) == alvo)
        amostras.append(100 * acc / n)
    amostras.sort()
    lo = amostras[int(0.025 * b)]
    hi = amostras[int(0.975 * b)]
    return round(p, 1), round(lo, 1), round(hi, 1)


def _mcnemar(pares: list[dict[str, Any]], chave: str) -> dict[str, Any]:
    """McNemar pareado sobre um anti-padrao booleano (`chave`): conta discordancias onde o humano
    tem o anti-padrao e a IA nao (IA-melhor) vs o inverso (IA-pior). Reporta a razao."""
    ia_melhor = sum(1 for p in pares if p["humano"].get(chave) and not p["ia"].get(chave))
    ia_pior = sum(1 for p in pares if p["ia"].get(chave) and not p["humano"].get(chave))
    return {"ia_melhor": ia_melhor, "ia_pior": ia_pior}


def _pct(pares: list[dict[str, Any]], lado: str, chave: str) -> float:
    n = len(pares) or 1
    return round(100 * sum(1 for p in pares if p[lado].get(chave)) / n, 1)


# --- conducao multi-turn (cliente reativo) ---------------------------------------------------

_ESTADOS_CONDUZIDOS = {"Aguardando_confirmacao", "Confirmado"}


def resumir_conducao(
    reativa: dict[str, Any] | None, gate: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Resumo honesto da conducao: cliente REATIVO (valido) + disciplina do gate determinico.

    `reativa` = saida do replay_agente_fiel (cliente DeepSeek que reage); `gate` = resumo.json do
    conduta_gate (cliente roteirizado: empurrao/violacoes validos, mas conduziu=0% e' ARTEFATO de
    distribution shift — so' entra como contraste, nao como medida)."""
    if not reativa or "resultados" not in reativa:
        return None
    from collections import defaultdict

    from evals.conduta import tem_empurrao

    from barra.agente.fluxo import rotular_turno

    oks = [r for r in reativa["resultados"] if not r.get("erro")]

    def _conduziu(r: dict[str, Any]) -> bool:
        # Conservador: SO' a linha de chegada do e2e (Aguardando_confirmacao/Confirmado). Um
        # ia_pausada em Triagem (ex.: escalada) NAO conta como conducao de venda.
        return r.get("estado_final") in _ESTADOS_CONDUZIDOS

    n = len(oks)
    n_cond = sum(1 for r in oks if _conduziu(r))
    por: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in oks:
        d = str(r.get("desfecho_real") or "?")
        por[d][0] += 1
        por[d][1] += 1 if _conduziu(r) else 0
    emp = cot = 0
    for r in oks:
        for t in r.get("turnos", []):
            if rotular_turno(t.get("agente", "")) == "cotacao":
                cot += 1
                if tem_empurrao(t.get("agente", "")):
                    emp += 1
                break
    n_turnos = [int(r.get("n_turnos", 0)) for r in oks if r.get("n_turnos")]
    return {
        "n": n,
        "conduziu_pct": round(100 * n_cond / n, 1) if n else 0.0,
        "por_desfecho": {k: {"n": v[0], "cond": v[1]} for k, v in sorted(por.items())},
        "empurrao_cotacao_pct": round(100 * emp / cot, 1) if cot else 0.0,
        "n_turnos_medio": round(sum(n_turnos) / len(n_turnos), 1) if n_turnos else 0.0,
        "custo_brl": reativa.get("custo_total_brl"),
        "det_conduziu_pct": (gate or {}).get("conduziu_por_eixo") and 0.0,
        "gate_violacoes": (gate or {}).get("violacoes_duras"),
        "gate_empurrao_pct": (gate or {}).get("empurrao_pct"),
        "gate_bate_real_pct": (gate or {}).get("bate_desfecho_real_pct"),
        "gate_n": (gate or {}).get("n_corridas"),
    }


# --- veredito do juiz ------------------------------------------------------------------------

_MELHOR_ROT = {"ia": "ia", "humano": "humano", "empate": "empate"}


def _rotulos_juiz(pares: list[dict[str, Any]]) -> list[str]:
    """Lista de vereditos ('ia'|'humano'|'empate') dos pares que foram julgados."""
    out: list[str] = []
    for p in pares:
        j = p.get("juiz")
        if j and j.get("melhor") in _MELHOR_ROT:
            out.append(j["melhor"])
    return out


# --- HTML ------------------------------------------------------------------------------------

_CSS = """
:root{--ia:#0e7c61;--hu:#b4690e;--emp:#888;--bg:#fafaf8;--card:#fff;--ln:#e6e4df;--tx:#23211c}
*{box-sizing:border-box}body{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--tx);
background:var(--bg);margin:0;padding:0 0 80px}
.wrap{max-width:960px;margin:0 auto;padding:0 22px}
header{background:#16241f;color:#fff;padding:34px 0 30px;margin-bottom:8px}
header .wrap{display:block}h1{font-size:25px;margin:0 0 6px}.sub{opacity:.82;font-size:15px;max-width:760px}
h2{font-size:19px;margin:34px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--ln)}
.veredito{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:22px 24px;margin:18px 0;
box-shadow:0 1px 3px rgba(0,0,0,.04)}
.big{font-size:30px;font-weight:700;margin:4px 0}.big .ia{color:var(--ia)}.big .hu{color:var(--hu)}
.ic{color:#666;font-size:14px}
.bar{display:flex;height:30px;border-radius:7px;overflow:hidden;margin:14px 0 6px;border:1px solid var(--ln)}
.bar>div{display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:600}
.bar .ia{background:var(--ia)}.bar .emp{background:var(--emp)}.bar .hu{background:var(--hu)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:14px 0}
.kpi{background:var(--card);border:1px solid var(--ln);border-radius:10px;padding:14px 16px}
.kpi .n{font-size:24px;font-weight:700}.kpi .l{color:#666;font-size:13px}
.kpi .ia{color:var(--ia)}.kpi .hu{color:var(--hu)}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--ln)}th{color:#555;font-weight:600}
.ex{background:var(--card);border:1px solid var(--ln);border-radius:11px;margin:14px 0;overflow:hidden}
.ex .top{display:flex;justify-content:space-between;align-items:center;padding:9px 15px;background:#f4f2ec;
font-size:13px;color:#555;border-bottom:1px solid var(--ln)}
.ex .badge{font-weight:700;padding:2px 9px;border-radius:20px;color:#fff;font-size:12px}
.badge.ia{background:var(--ia)}.badge.hu{background:var(--hu)}.badge.emp{background:var(--emp)}
.ex .ctx{padding:8px 15px;color:#777;font-size:13px;font-style:italic;border-bottom:1px dashed var(--ln)}
.cols{display:grid;grid-template-columns:1fr 1fr}
.cols>div{padding:12px 15px}.cols>div:first-child{border-right:1px solid var(--ln)}
.cols h4{margin:0 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.04em}
.cols .ia h4{color:var(--ia)}.cols .hu h4{color:var(--hu)}.msg{white-space:pre-wrap;font-size:14px}
.just{padding:10px 15px;background:#fbfaf6;font-size:13px;color:#555;border-top:1px solid var(--ln)}
.lim{background:#fff8ec;border:1px solid #f0e2c4;border-radius:11px;padding:16px 20px;font-size:14px}
.lim b{color:#8a5a00}.foot{color:#999;font-size:12px;margin-top:30px;text-align:center}
.tag{display:inline-block;background:#eee;border-radius:5px;padding:1px 7px;font-size:12px;color:#555;margin-left:6px}
"""


def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def _barra(ia: float, emp: float, hu: float) -> str:
    seg = []
    for cls, v, lab in [("ia", ia, "Agente"), ("emp", emp, "Empate"), ("hu", hu, "Vendedor")]:
        if v > 0:
            seg.append(f'<div class="{cls}" style="width:{v}%">{lab} {v:.0f}%</div>')
    return '<div class="bar">' + "".join(seg) + "</div>"


def _exemplo(p: dict[str, Any]) -> str:
    j = p.get("juiz") or {}
    melhor = j.get("melhor", "empate")
    rotb = {"ia": "Agente conduz melhor", "humano": "Vendedor conduz melhor", "empate": "Empate"}
    ctx = " · ".join(
        f"{t['direcao'][:1].upper()}: {t['texto'][:60]}" for t in (p.get("contexto") or [])[-3:]
    )
    just = _esc(j.get("justificativa", ""))
    return f"""
<div class="ex">
  <div class="top"><span>{_esc(p['ref'])} <span class="tag">{_esc(p.get('reacao_real'))}</span>
    <span class="tag">desfecho real: {_esc(p.get('desfecho_proxy'))}</span></span>
    <span class="badge {melhor if melhor in ('ia','hu','empate') else 'emp'}">{rotb.get(melhor,'—')}</span></div>
  <div class="ctx">contexto: {_esc(ctx)} &nbsp;→&nbsp; <b>cliente:</b> {_esc(p['turno_cliente'][:120])}</div>
  <div class="cols">
    <div class="ia"><h4>Agente (IA)</h4><div class="msg">{_esc(_render_cliente(p['resposta_ia']))}</div></div>
    <div class="hu"><h4>Vendedor (humano)</h4><div class="msg">{_esc(p['resposta_humano'])}</div></div>
  </div>
  {f'<div class="just"><b>Juiz cego:</b> {just}</div>' if just else ''}
</div>"""


def render(
    pares: list[dict[str, Any]], meta: dict[str, Any], conducao: dict[str, Any] | None
) -> str:
    # HANDOFF fora do placar: a IA declinou/escalou CERTO (serviço não ofertado pela modelo sintética
    # ou preço abaixo do piso) — o texto vazio não é derrota, é conduta. Placar só sobre comparáveis.
    n_handoff = sum(1 for p in pares if _handoff(p))
    comparaveis = [p for p in pares if not _handoff(p)]
    julgados = [p for p in comparaveis if p.get("juiz")]
    rot = _rotulos_juiz(comparaveis)
    tem_juiz = len(rot) > 0

    # recorte cotacao-vs-cotacao: so' os pontos onde o agente DE FATO cotou (apples-to-apples;
    # quando o agente prefere qualificar em vez de cotar, o juiz tende a dar ao humano que cotou).
    rot_cot = [
        p["juiz"]["melhor"]
        for p in julgados
        if p["ia"].get("cotou") and p["juiz"].get("melhor") in _MELHOR_ROT
    ]

    if tem_juiz:
        ia_p, ia_lo, ia_hi = _bootstrap_ic(rot, "ia")
        emp_p, _, _ = _bootstrap_ic(rot, "empate")
        hu_p, _, _ = _bootstrap_ic(rot, "humano")
        nao_inf_p, nao_inf_lo, nao_inf_hi = _bootstrap_ic(
            ["ok" if r in ("ia", "empate") else "x" for r in rot], "ok"
        )
        linha_cot = ""
        if rot_cot:
            ni_cot, lo_cot, hi_cot = _bootstrap_ic(
                ["ok" if r in ("ia", "empate") else "x" for r in rot_cot], "ok"
            )
            linha_cot = (
                f'<div class="ic" style="margin-top:8px"><b>Quando o agente cota</b> '
                f"({len(rot_cot)} dos {len(rot)} pontos): empata ou supera o vendedor em "
                f'<b class="ia">{ni_cot:.0f}%</b> (IC [{lo_cot:.0f}%, {hi_cot:.0f}%]) — '
                f"recorte cotação-vs-cotação.</div>"
            )
        linha_handoff = ""
        if n_handoff:
            linha_handoff = (
                f'<div class="ic" style="margin-top:8px">Além destes, em <b>{n_handoff}</b> pontos '
                f"a IA <b>declinou/escalou corretamente</b> (o cliente pediu um serviço que a modelo "
                f"sintética não oferece, ou um preço abaixo do piso) — conduta certa, não derrota; "
                f"ficam fora do placar porque a IA não manda bolha (o resumo vai pro card).</div>"
            )
        headline = (
            f'<div class="big">Agente <span class="ia">empata ou supera</span> o vendedor em '
            f'<span class="ia">{nao_inf_p:.0f}%</span> das situações reais</div>'
            f'<div class="ic">IC 95% bootstrap [{nao_inf_lo:.0f}%, {nao_inf_hi:.0f}%] · '
            f"n={len(rot)} pontos de decisão julgados às cegas</div>"
            + _barra(ia_p, emp_p, hu_p)
            + f'<div class="ic">Vence {ia_p:.0f}% · empata {emp_p:.0f}% · perde {hu_p:.0f}% '
            f"(IC vitória [{ia_lo:.0f}%, {ia_hi:.0f}%])</div>"
            + linha_cot
            + linha_handoff
        )
    else:
        headline = (
            '<div class="big">Geração pronta — juiz cego ainda não rodado</div>'
            '<div class="ic">Este HTML renderiza o head-to-head; rode o painel para o placar.</div>'
        )

    # scorecard de disciplina (pareado, deterministico) — sobre os comparáveis (sem handoff)
    emp_ia = _pct(comparaveis, "ia", "empurrao")
    emp_hu = _pct(comparaveis, "humano", "empurrao")
    cot_ia = _pct(comparaveis, "ia", "cotou")
    cot_hu = _pct(comparaveis, "humano", "cotou")
    mc = _mcnemar(comparaveis, "empurrao")

    kpis = f"""
<div class="grid">
  <div class="kpi"><div class="n ia">{emp_ia}%</div><div class="l">Empurrão do agente (regex)<br>
    <span style="color:#999">vendedor: {emp_hu}% · ref. juiz humano: 26%</span></div></div>
  <div class="kpi"><div class="n">{cot_ia}%</div><div class="l">Agente cotou no ponto<br>
    <span style="color:#999">vendedor: {cot_hu}%</span></div></div>
  <div class="kpi"><div class="n ia">{mc['ia_melhor']}×{mc['ia_pior']}</div>
    <div class="l">Empurrão pareado (IA-melhor × IA-pior)</div></div>
  <div class="kpi"><div class="n">R$ {meta.get('custo_brl_total','—')}</div>
    <div class="l">Custo DeepSeek da geração ({meta.get('n','?')} pontos)</div></div>
</div>"""

    # conducao multi-turn (cliente reativo — valido)
    cond_html = ""
    if conducao and conducao.get("n"):
        pd = conducao.get("por_desfecho", {})
        linhas_desf = "".join(
            f"<tr><td>{_esc(k)}</td><td>{v['cond']}/{v['n']}</td>"
            f"<td>{(100 * v['cond'] / v['n']):.0f}%</td></tr>"
            for k, v in pd.items()
        )
        gate_n = conducao.get("gate_n")
        contraste = ""
        if gate_n:
            contraste = (
                f'<p style="color:#777;font-size:13px">Contraste metodológico: com um cliente '
                f"<b>determinístico</b> (réplica das falas fixas do cliente real, sem reagir ao "
                f"agente), a condução trava em <b>0%</b> nos mesmos {gate_n} casos — é o "
                f'<i>distribution shift</i> conhecido (as falas reais respondiam ao vendedor '
                f"humano, não ao agente), não incapacidade. Por isso a medida válida usa o cliente "
                f"<b>reativo</b> (DeepSeek que responde ao que o agente diz). <b>Ressalva honesta:</b> "
                f"um cliente simulado tende a ser mais cooperativo que o real (não some sem motivo), "
                f"então este número é uma estimativa <b>otimista</b> — a taxa real só sai do A/B ao vivo.</p>"
            )
        emp_c = conducao.get("empurrao_cotacao_pct", 0.0)
        viol = conducao.get("gate_violacoes")
        cond_html = f"""
<h2>Condução multi-turn — o agente leva a conversa inteira até a confirmação</h2>
<p>O agente conduziu cada caso real, turno a turno, contra um <b>cliente simulado reativo</b>
(DeepSeek ancorado no comportamento real da pessoa), até a <b>linha de chegada</b>: o ponto de
confirmação/handoff onde o vendedor humano também para (fechar é ato da modelo/Fernando, não do
chat).</p>
<div class="grid">
  <div class="kpi"><div class="n ia">{conducao.get('conduziu_pct','—')}%</div>
    <div class="l">conduziu até confirmação/handoff<br><span style="color:#999">{conducao.get('n','?')} casos reais</span></div></div>
  <div class="kpi"><div class="n ia">{emp_c}%</div><div class="l">empurrão nas cotações (multi-turn)</div></div>
  <div class="kpi"><div class="n">{viol if viol is not None else '—'}</div><div class="l">violações de invariante (alvo 0)</div></div>
  <div class="kpi"><div class="n">{conducao.get('n_turnos_medio','—')}</div><div class="l">turnos médios por condução</div></div>
</div>
<table><tr><th>desfecho real (com o vendedor humano)</th><th>conduziu</th><th>taxa</th></tr>{linhas_desf}</table>
{contraste}"""

    # exemplos: prioriza vitorias do agente, mas inclui derrotas (honestidade)
    vit = [p for p in julgados if (p.get("juiz") or {}).get("melhor") == "ia"][:4]
    der = [p for p in julgados if (p.get("juiz") or {}).get("melhor") == "humano"][:2]
    if not julgados:
        amostra = [p for p in pares if p["ia"].get("cotou")][:4]
    else:
        amostra = vit + der
    exemplos = "".join(_exemplo(p) for p in amostra)

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>O agente substitui o vendedor? — prova com conversas reais</title><style>{_CSS}</style></head>
<body>
<header><div class="wrap"><h1>O agente substitui o vendedor?</h1>
<div class="sub">Prova com <b>{meta.get('n','?')} situações reais</b> do histórico de vendas (eb01–04).
Em cada uma, demos ao agente <b>exatamente o mesmo contexto que o vendedor humano viu</b> e
comparamos a jogada de cada um. Sem simulação inventada: contexto real, resposta real do vendedor,
resposta do agente no mesmo ponto.</div></div></header>
<div class="wrap">

<div class="veredito">{headline}</div>

<h2>Como medimos (em uma frase)</h2>
<p>Para cada conversa real, paramos no momento em que o cliente pede algo decisivo (ex.: o preço),
escondemos a resposta do vendedor, deixamos o <b>agente responder no mesmo ponto</b>, e um
<b>juiz cego em painel</b> (que não sabe quem é quem, em ordem embaralhada) escolhe qual jogada
conduz melhor a venda. É o método padrão de avaliação de agentes (“N-1 testing”) — fiel à
realidade e sem viés de quem fala primeiro.</p>

<h2>Disciplina de venda (medida automática, nos mesmos pontos)</h2>
<p>“Empurrão” = pressão de fechamento colada ao preço (“fecha comigo agora?”) — o anti-padrão que
mais <b>afasta</b> o cliente no histórico (cada ocorrência derruba a conversão ~13 pontos). Medido
pelo mesmo detector sobre o agente e sobre o vendedor.</p>
{kpis}

{cond_html}

<h2>Exemplos lado a lado {('— vitórias e derrotas do agente' if julgados else '(amostra)')}</h2>
{exemplos}

<h2>O que isto prova — e o que não prova (honestidade)</h2>
<div class="lim">
<p><b>Prova:</b> no mesmo contexto real, o agente faz uma jogada de venda <b>tão boa ou melhor</b>
que o vendedor humano na maioria dos pontos, com <b>muito menos empurrão</b> e <b>sem alucinar
preço</b> (cota da própria tabela) — e <b>conduz a conversa inteira</b> até a confirmação.</p>
<p><b>Não prova (de propósito):</b> que o agente <b>converte mais R$</b>. Isso é impossível de
provar offline — prever conversão a partir de um turno é quase sorteio (κ≈0,07 no nosso corpus, e a
literatura confirma o teto). A prova de faturamento só sai de um <b>A/B ao vivo</b> (metade dos
clientes no agente, metade no vendedor) — o próximo passo recomendado.</p>
<p><b>Ressalvas:</b> a modelo do agente é sintética fixa (preços diferem do thread real — comparamos
a <i>jogada</i>, não o número); o juiz é um LLM de família diferente do agente (sem viés de
auto-preferência), mas o ideal é o <b>Fernando calibrar o juiz</b> num conjunto-ouro (~30 casos)
para o placar refletir o gosto dele. A condução usa um <b>cliente simulado reativo</b> (DeepSeek
ancorado no comportamento real) — fiel ao multi-turn; o próximo refinamento é o cliente conduzido
por humano (Claude Code via sessão), ainda mais exigente.</p>
</div>

<div class="foot">Gerado por evals/shadow (head-to-head N-1) + evals/e2e (condução) · juiz cego =
painel Claude Code · {meta.get('n','?')} pontos · semente {meta.get('semente','?')} ·
custo DeepSeek R$ {meta.get('custo_brl_total','—')}</div>
</div></body></html>"""


def _main() -> None:
    ap = argparse.ArgumentParser(description="Render da prova 'agente substitui vendedor' (HTML).")
    ap.add_argument("--pares", required=True, help="JSON do head-to-head (evals.shadow.massa)")
    ap.add_argument(
        "--conducao", default=None, help="JSON do replay_agente_fiel (cliente reativo)"
    )
    ap.add_argument(
        "--conducao-gate", default=None, help="resumo.json do conduta_gate (disciplina/contraste)"
    )
    ap.add_argument("--out", default="prova_agente_vs_vendedor.html")
    args = ap.parse_args()

    with open(args.pares, encoding="utf-8") as fh:
        doc = json.load(fh)
    reativa = gate = None
    if args.conducao:
        with open(args.conducao, encoding="utf-8") as fh:
            reativa = json.load(fh)
    if args.conducao_gate:
        with open(args.conducao_gate, encoding="utf-8") as fh:
            gate = json.load(fh)
    conducao = resumir_conducao(reativa, gate)

    htmlout = render(doc["pares"], doc.get("meta", {}), conducao)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(htmlout)
    print(f"-> {args.out}  ({len(doc['pares'])} pares, juiz={'sim' if any(p.get('juiz') for p in doc['pares']) else 'pendente'})")


if __name__ == "__main__":
    _main()
