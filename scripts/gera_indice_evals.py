#!/usr/bin/env python
"""Gera um indice HTML legivel de TODAS as fixtures de eval do agente.

As fixtures vivem em `api/evals/{canonicos,adversariais}/*.jsonl` (uma por linha).
Hoje so da pra le-las nos .jsonl crus; este gerador emite uma pagina estatica,
agrupada por categoria -> subcategoria, com selo BARRA (trava o gate) / AVISA
(advisory) e os campos uteis de cada fixture.

Fidelidade do gate: NAO reimplementamos a regra por chute. Extraimos as funcoes
REAIS `carregar_fixtures`, `_gate_da_fixture` e `_politica_agregacao` direto de
`api/evals/runners/runner.py` via AST -- sem importar o modulo inteiro (que puxa
build_graph/langchain/psycopg e exigiria .env). Um self-test confirma que a
extracao casa com o comportamento documentado.

Saida: docs/agente/evals-fixtures-indice.html (UTF-8, sem build, so Google Fonts).

Uso:
    python scripts/gera_indice_evals.py
"""

import ast
import html
import json
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable

RAIZ = Path(__file__).resolve().parents[1]
EVALS = RAIZ / "api" / "evals"
RUNNER = EVALS / "runners" / "runner.py"
SAIDA = RAIZ / "docs" / "agente" / "evals-fixtures-indice.html"

# So estes subdirs sao fixtures do AGENTE. `calibracao/` e dado de calibracao do
# judge (linhas com `_header`, sem id/categoria/gate) -- nao entra no indice.
SUBDIRS = ["canonicos", "adversariais"]


def _funcoes_reais() -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    """Extrai as 3 funcoes puras do runner.py via AST e as compila isoladas.

    Evita `import runner` (que dispara `from barra.agente.graph import build_graph`
    e exigiria settings/.env). As funcoes sao puras; basta dar-lhes o namespace que
    suas assinaturas/defaults referenciam.
    """
    fonte = RUNNER.read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    querer = {"carregar_fixtures", "_gate_da_fixture", "_politica_agregacao"}
    defs = [n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name in querer]
    faltando = querer - {n.name for n in defs}
    if faltando:
        raise RuntimeError(f"funcoes ausentes no runner.py: {sorted(faltando)}")
    ns: dict[str, Any] = {
        "json": json,
        "Path": Path,
        "Iterable": Iterable,
        "Any": Any,
        "_EVALS_RAIZ": EVALS,
    }
    modulo = ast.Module(body=defs, type_ignores=[])
    exec(compile(modulo, str(RUNNER), "exec"), ns)  # noqa: S102 -- codigo do proprio repo
    return ns["carregar_fixtures"], ns["_gate_da_fixture"], ns["_politica_agregacao"]


carregar_fixtures, _gate_da_fixture, _politica_agregacao = _funcoes_reais()


def _selftest_gate() -> None:
    """Confirma que a extracao casa com a regra documentada do runner."""
    assert _gate_da_fixture({"gate": "regressao", "categoria": "adversariais"}) == "regressao"
    assert _gate_da_fixture({"gate": "capability", "categoria": "canonicos"}) == "capability"
    assert _gate_da_fixture({"categoria": "adversariais"}) == "capability"
    assert _gate_da_fixture({"categoria": "canonicos"}) == "regressao"
    assert _gate_da_fixture({"gate": "lixo", "categoria": "canonicos"}) == "regressao"
    assert _politica_agregacao("adversariais") == "todas"
    assert _politica_agregacao("canonicos") == "tolerante"


# --- extracao dos campos exibiveis -------------------------------------------------------------


def _estado_final(fixture: dict[str, Any]) -> tuple[str | None, bool | None]:
    """Estado/ia_pausada finais esperados (espelha como avaliar() monta o state_check).

    Top-level vence; cai pro state_check do ultimo turno roteirizado quando ausente.
    """
    exp = fixture.get("expectativas", {})
    sc = dict(exp.get("state_check") or {})
    estado = exp.get("estado_final_atendimento") or sc.get("atendimento_estado")
    pausada = exp.get("ia_pausada_final")
    if pausada is None:
        pausada = sc.get("ia_pausada")
    if estado is None or pausada is None:
        msgs = fixture.get("mensagens_entrada", [])
        for m in reversed(msgs):
            stc = m.get("state_check")
            if stc:
                estado = estado or stc.get("atendimento_estado")
                if pausada is None:
                    pausada = stc.get("ia_pausada")
                break
    return estado, pausada


def _politica_humana(categoria: str) -> str:
    pol = _politica_agregacao(categoria)
    if pol == "todas":
        return "pass^5 — nenhuma das 5 rodadas pode falhar"
    return "tolerante — ≥4/5 rodadas (≥80%)"


def coletar() -> list[dict[str, Any]]:
    """Carrega as fixtures (via funcao real) e extrai os campos do indice, em ordem."""
    fixtures = carregar_fixtures(raiz=EVALS, subdirs=SUBDIRS)
    itens: list[dict[str, Any]] = []
    for fx in fixtures:
        fid = fx.get("id")
        if not fid:
            print(f"  AVISO: fixture sem 'id' ignorada: {str(fx)[:80]}")
            continue
        exp = fx.get("expectativas", {})
        estado, pausada = _estado_final(fx)
        rubricas = fx.get("rubricas", {})
        itens.append(
            {
                "id": fid,
                "categoria": fx.get("categoria", ""),
                "subcategoria": fx.get("subcategoria", "(sem subcategoria)"),
                "descricao": fx.get("descricao", ""),
                "gate": _gate_da_fixture(fx),
                "obrig": list(exp.get("tool_calls_obrigatorias", [])),
                "proib": list(exp.get("tool_calls_proibidas", [])),
                "estado_final": estado,
                "ia_pausada_final": pausada,
                "politica": _politica_humana(fx.get("categoria", "")),
                "rubricas": [
                    {"nome": k, "judge": v.get("judge", "?")} for k, v in rubricas.items()
                ],
                "isolamento_canary": bool(exp.get("isolamento_canary")),
                "n_turnos_cliente": sum(
                    1 for m in fx.get("mensagens_entrada", []) if m.get("direcao", "cliente") == "cliente"
                ),
            }
        )
    return itens


# --- HTML --------------------------------------------------------------------------------------

ROTULO = {"regressao": "BARRA", "capability": "AVISA"}


def _e(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _chips(itens: list[str], classe: str) -> str:
    if not itens:
        return '<span class="vazio">—</span>'
    return "".join(f'<code class="chip {classe}">{_e(t)}</code>' for t in itens)


def _card(it: dict[str, Any]) -> str:
    gate = it["gate"]
    rotulo = ROTULO.get(gate, gate)
    estado = it["estado_final"]
    pausada = it["ia_pausada_final"]
    estado_txt = []
    if estado:
        estado_txt.append(f'<span class="kv-v">{_e(estado)}</span>')
    if pausada is not None:
        estado_txt.append(
            f'<span class="kv-v ia-{"on" if pausada else "off"}">ia_pausada={_e(str(pausada).lower())}</span>'
        )
    estado_html = " ".join(estado_txt) if estado_txt else '<span class="vazio">—</span>'

    rubricas_html = "".join(
        f'<code class="chip rub rub-{_e(r["judge"])}">{_e(r["nome"])}·{_e(r["judge"])}</code>'
        for r in it["rubricas"]
    ) or '<span class="vazio">—</span>'

    marcas = []
    if it["isolamento_canary"]:
        marcas.append('<span class="tag-canary">isolamento_canary</span>')
    if it["n_turnos_cliente"] > 1:
        marcas.append(f'<span class="tag-multi">{it["n_turnos_cliente"]} turnos</span>')
    marcas_html = " ".join(marcas)

    return f"""
      <article class="card" data-categoria="{_e(it['categoria'])}" data-gate="{_e(gate)}">
        <header class="card-top">
          <code class="fid">{_e(it['id'])}</code>
          <span class="selo selo-{_e(gate)}">{_e(rotulo)}</span>
        </header>
        <p class="desc">{_e(it['descricao'])}</p>
        <dl class="meta">
          <div class="row"><dt>obrigatórias</dt><dd>{_chips(it['obrig'], 'ok')}</dd></div>
          <div class="row"><dt>proibidas</dt><dd>{_chips(it['proib'], 'no')}</dd></div>
          <div class="row"><dt>estado final</dt><dd>{estado_html}</dd></div>
          <div class="row"><dt>aprovação</dt><dd><span class="pol">{_e(it['politica'])}</span></dd></div>
          <div class="row"><dt>rubricas</dt><dd>{rubricas_html}</dd></div>
        </dl>
        {f'<footer class="card-tags">{marcas_html}</footer>' if marcas_html else ''}
      </article>"""


def _agrupar(itens: list[dict[str, Any]]) -> "OrderedDict[str, OrderedDict[str, list[dict[str, Any]]]]":
    """categoria -> subcategoria -> [itens], preservando a ordem de aparicao (= ordem do runner)."""
    arvore: OrderedDict[str, OrderedDict[str, list[dict[str, Any]]]] = OrderedDict()
    for it in itens:
        cat = it["categoria"] or "(sem categoria)"
        sub = it["subcategoria"]
        arvore.setdefault(cat, OrderedDict()).setdefault(sub, []).append(it)
    return arvore


def construir_html(itens: list[dict[str, Any]]) -> str:
    total = len(itens)
    n_barra = sum(1 for i in itens if i["gate"] == "regressao")
    n_avisa = total - n_barra
    cats = sorted({i["categoria"] or "(sem categoria)" for i in itens})

    arvore = _agrupar(itens)
    secoes: list[str] = []
    for cat, subs in arvore.items():
        n_cat = sum(len(v) for v in subs.values())
        blocos_sub = []
        for sub, lista in subs.items():
            cards = "".join(_card(it) for it in lista)
            blocos_sub.append(
                f"""
          <section class="sub" data-categoria="{_e(cat)}">
            <h3 class="sub-h">{_e(sub)} <span class="sub-n">{len(lista)}</span></h3>
            <div class="grid">{cards}</div>
          </section>"""
            )
        secoes.append(
            f"""
        <section class="cat" data-categoria="{_e(cat)}">
          <h2 class="cat-h">{_e(cat)} <span class="cat-n">{n_cat}</span></h2>
          {''.join(blocos_sub)}
        </section>"""
        )

    chips_cat = "".join(
        f'<button class="filtro" data-tipo="cat" data-val="{_e(c)}">{_e(c)}</button>' for c in cats
    )

    return _TEMPLATE.format(
        total=total,
        n_barra=n_barra,
        n_avisa=n_avisa,
        chips_cat=chips_cat,
        secoes="".join(secoes),
        gerado_por="scripts/gera_indice_evals.py",
    )


_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fixtures de eval · Elite Baby</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#100e14; --painel:#15121b; --sup:#1b1823; --linha:#322c3e;
  --texto:#ece4d6; --suave:#9a8f7e; --ouro:#f0bf5e; --ouro2:#caa042;
  --verde:#6cc08a; --vermelho:#df5a44; --azul:#6fa8cf;
}}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:smooth; }}
body {{
  margin:0; background:var(--bg); color:var(--texto);
  font-family:'Archivo',system-ui,sans-serif; font-size:15px; line-height:1.55;
  background-image:
    linear-gradient(var(--linha) 1px, transparent 1px),
    linear-gradient(90deg, var(--linha) 1px, transparent 1px);
  background-size:42px 42px; background-position:center top;
}}
body::before {{
  content:""; position:fixed; inset:0; pointer-events:none; z-index:0; opacity:.035;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}}
.wrap {{ position:relative; z-index:1; max-width:1180px; margin:0 auto; padding:48px 24px 96px; }}
header.topo {{ border-bottom:1px solid var(--linha); padding-bottom:28px; margin-bottom:8px; }}
.kicker {{ font-family:'JetBrains Mono',monospace; font-size:12px; letter-spacing:.18em;
  text-transform:uppercase; color:var(--ouro2); }}
h1 {{ font-family:'Fraunces',serif; font-weight:700; font-size:clamp(30px,5vw,46px);
  margin:.18em 0 .1em; color:var(--texto); letter-spacing:-.01em; }}
h1 em {{ font-style:italic; color:var(--ouro); }}
.sub-titulo {{ color:var(--suave); max-width:62ch; }}
.stats {{ display:flex; gap:14px; flex-wrap:wrap; margin-top:22px; }}
.stat {{ background:var(--painel); border:1px solid var(--linha); border-radius:12px;
  padding:12px 18px; min-width:104px; }}
.stat .num {{ font-family:'Fraunces',serif; font-size:30px; font-weight:600; line-height:1; }}
.stat .lbl {{ font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--suave); margin-top:6px; }}
.stat.barra .num {{ color:var(--vermelho); }}
.stat.avisa .num {{ color:var(--azul); }}
.stat.total .num {{ color:var(--ouro); }}

.barra-filtros {{ position:sticky; top:0; z-index:5; margin:26px 0 8px;
  background:linear-gradient(var(--bg) 72%, transparent); padding:14px 0 16px; }}
.grupo-filtro {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; }}
.grupo-filtro > .leg {{ font-family:'JetBrains Mono',monospace; font-size:11px;
  letter-spacing:.12em; text-transform:uppercase; color:var(--suave); margin-right:4px; min-width:74px; }}
.filtro {{ font-family:'JetBrains Mono',monospace; font-size:12px; cursor:pointer;
  color:var(--texto); background:var(--sup); border:1px solid var(--linha);
  border-radius:999px; padding:6px 14px; transition:.16s; }}
.filtro:hover {{ border-color:var(--ouro2); color:var(--ouro); }}
.filtro.on {{ background:var(--ouro); color:#1a1206; border-color:var(--ouro); font-weight:700; }}
.filtro.g-barra.on {{ background:var(--vermelho); border-color:var(--vermelho); color:#fff; }}
.filtro.g-avisa.on {{ background:var(--azul); border-color:var(--azul); color:#0e1620; }}

.cat-h {{ font-family:'Fraunces',serif; font-weight:600; font-size:26px; margin:40px 0 2px;
  padding-bottom:8px; border-bottom:1px solid var(--linha); display:flex; align-items:baseline; gap:10px; }}
.cat-n, .sub-n {{ font-family:'JetBrains Mono',monospace; font-size:13px; color:var(--suave);
  background:var(--sup); border:1px solid var(--linha); border-radius:999px; padding:1px 10px; }}
.sub-h {{ font-family:'JetBrains Mono',monospace; font-weight:500; font-size:14px;
  letter-spacing:.06em; color:var(--ouro2); margin:26px 0 12px; text-transform:lowercase;
  display:flex; align-items:center; gap:8px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(360px,1fr)); gap:14px; }}

.card {{ background:var(--painel); border:1px solid var(--linha); border-radius:14px;
  padding:16px 18px 14px; display:flex; flex-direction:column;
  animation:surge .5s ease both; }}
.card:hover {{ border-color:var(--ouro2); }}
@keyframes surge {{ from {{ opacity:0; transform:translateY(7px); }} to {{ opacity:1; transform:none; }} }}
.card-top {{ display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:9px; }}
.fid {{ font-family:'JetBrains Mono',monospace; font-size:12.5px; color:var(--ouro);
  word-break:break-all; }}
.selo {{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700;
  letter-spacing:.1em; padding:3px 10px; border-radius:6px; white-space:nowrap; flex-shrink:0; }}
.selo-regressao {{ color:#1a0d09; background:linear-gradient(135deg,var(--vermelho),var(--ouro));
  box-shadow:0 0 0 1px rgba(223,90,68,.4); }}
.selo-capability {{ color:#0e1620; background:var(--azul); }}
.desc {{ margin:0 0 12px; color:var(--texto); font-size:13.5px; line-height:1.5; }}
.meta {{ margin:0; border-top:1px solid var(--linha); padding-top:10px;
  display:flex; flex-direction:column; gap:6px; }}
.meta .row {{ display:grid; grid-template-columns:96px 1fr; gap:8px; align-items:start; }}
.meta dt {{ font-family:'JetBrains Mono',monospace; font-size:10.5px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--suave); padding-top:3px; }}
.meta dd {{ margin:0; display:flex; flex-wrap:wrap; gap:5px; align-items:center; }}
.chip {{ font-family:'JetBrains Mono',monospace; font-size:11px; padding:2px 8px;
  border-radius:5px; border:1px solid var(--linha); background:var(--sup); color:var(--texto); }}
.chip.ok {{ border-color:rgba(108,192,138,.5); color:var(--verde); }}
.chip.no {{ border-color:rgba(223,90,68,.45); color:var(--vermelho); }}
.chip.rub {{ color:var(--suave); }}
.chip.rub-llm {{ border-color:rgba(111,168,207,.45); color:var(--azul); }}
.chip.rub-deterministico {{ border-color:rgba(240,191,94,.4); color:var(--ouro2); }}
.kv-v {{ font-family:'JetBrains Mono',monospace; font-size:11.5px; color:var(--texto);
  background:var(--sup); border:1px solid var(--linha); border-radius:5px; padding:2px 8px; }}
.ia-on {{ color:var(--vermelho); }} .ia-off {{ color:var(--verde); }}
.pol {{ font-size:12px; color:var(--suave); }}
.vazio {{ color:var(--linha); }}
.card-tags {{ margin-top:10px; display:flex; gap:6px; flex-wrap:wrap; }}
.tag-canary, .tag-multi {{ font-family:'JetBrains Mono',monospace; font-size:10px;
  letter-spacing:.06em; padding:2px 8px; border-radius:999px; }}
.tag-canary {{ color:var(--vermelho); border:1px dashed rgba(223,90,68,.5); }}
.tag-multi {{ color:var(--azul); border:1px solid rgba(111,168,207,.4); }}
.cat.oculto, .sub.oculto, .card.oculto {{ display:none; }}
footer.rodape {{ margin-top:60px; padding-top:20px; border-top:1px solid var(--linha);
  color:var(--suave); font-size:12px; font-family:'JetBrains Mono',monospace; }}
.legenda {{ display:flex; gap:18px; flex-wrap:wrap; margin-top:10px; }}
.legenda span {{ display:inline-flex; align-items:center; gap:7px; }}
.pip {{ width:11px; height:11px; border-radius:3px; display:inline-block; }}
.pip.b {{ background:linear-gradient(135deg,var(--vermelho),var(--ouro)); }}
.pip.a {{ background:var(--azul); }}
</style>
</head>
<body>
<div class="wrap">
  <header class="topo">
    <div class="kicker">Elite Baby · avaliação do agente</div>
    <h1>Índice de <em>fixtures</em> de eval</h1>
    <p class="sub-titulo">Cada fixture é um roteiro de conversa com o gabarito do que a IA
    deve e não deve fazer. O selo <strong>BARRA</strong> indica regressão (trava o cutover);
    <strong>AVISA</strong> é capability (advisory). A regra de gate espelha
    <code>_gate_da_fixture</code> do runner.</p>
    <div class="stats">
      <div class="stat total"><div class="num">{total}</div><div class="lbl">fixtures</div></div>
      <div class="stat barra"><div class="num">{n_barra}</div><div class="lbl">BARRA</div></div>
      <div class="stat avisa"><div class="num">{n_avisa}</div><div class="lbl">AVISA</div></div>
    </div>
  </header>

  <div class="barra-filtros">
    <div class="grupo-filtro">
      <span class="leg">categoria</span>
      <button class="filtro on" data-tipo="cat" data-val="*">todas</button>
      {chips_cat}
    </div>
    <div class="grupo-filtro">
      <span class="leg">gate</span>
      <button class="filtro on" data-tipo="gate" data-val="*">todos</button>
      <button class="filtro g-barra" data-tipo="gate" data-val="regressao">BARRA</button>
      <button class="filtro g-avisa" data-tipo="gate" data-val="capability">AVISA</button>
    </div>
  </div>

  <main id="lista">
    {secoes}
  </main>

  <footer class="rodape">
    <div class="legenda">
      <span><i class="pip b"></i> BARRA = regressão (bloqueia o gate, pass-rate ~100%)</span>
      <span><i class="pip a"></i> AVISA = capability (advisory, não bloqueia até graduar)</span>
    </div>
    <p>Gerado por <code>{gerado_por}</code> a partir de <code>api/evals/{{canonicos,adversariais}}</code>.
    Regenere quando as fixtures mudarem.</p>
  </footer>
</div>

<script>
const estado = {{ cat:"*", gate:"*" }};
function aplica() {{
  document.querySelectorAll(".card").forEach(c => {{
    const okCat = estado.cat === "*" || c.dataset.categoria === estado.cat;
    const okGate = estado.gate === "*" || c.dataset.gate === estado.gate;
    c.classList.toggle("oculto", !(okCat && okGate));
  }});
  // esconde subsecoes/secoes sem cards visiveis
  document.querySelectorAll(".sub").forEach(s => {{
    const visiveis = s.querySelectorAll(".card:not(.oculto)").length;
    s.classList.toggle("oculto", visiveis === 0);
  }});
  document.querySelectorAll(".cat").forEach(s => {{
    const visiveis = s.querySelectorAll(".card:not(.oculto)").length;
    s.classList.toggle("oculto", visiveis === 0);
  }});
}}
document.querySelectorAll(".filtro").forEach(btn => {{
  btn.addEventListener("click", () => {{
    const tipo = btn.dataset.tipo;
    estado[tipo] = btn.dataset.val;
    document.querySelectorAll(`.filtro[data-tipo="${{tipo}}"]`).forEach(b => b.classList.remove("on"));
    btn.classList.add("on");
    aplica();
  }});
}});
aplica();
</script>
</body>
</html>
"""


def main() -> None:
    _selftest_gate()
    print("self-test gate: OK (extracao casa com a regra do runner)")
    itens = coletar()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(construir_html(itens), encoding="utf-8")

    total = len(itens)
    n_barra = sum(1 for i in itens if i["gate"] == "regressao")
    por_cat: dict[str, int] = {}
    barra_cat: dict[str, int] = {}
    for i in itens:
        c = i["categoria"] or "(sem)"
        por_cat[c] = por_cat.get(c, 0) + 1
        if i["gate"] == "regressao":
            barra_cat[c] = barra_cat.get(c, 0) + 1
    print(f"fixtures: {total} | BARRA: {n_barra} | AVISA: {total - n_barra}")
    for c in sorted(por_cat):
        print(f"  {c}: {por_cat[c]} fixtures, {barra_cat.get(c, 0)} BARRA")
    print(f"HTML: {SAIDA}")


if __name__ == "__main__":
    main()
