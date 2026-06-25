"""Persistencia LEGIVEL dos transcripts e2e para avaliacao humana posterior.

Sem DB nem credito: recebe as corridas JA executadas (perfil, resultado, veredito) e grava num
diretorio (1) `transcritos.html` auto-contido — cada conversa turno-a-turno (cliente x agente)
com o veredito/conduta em destaque, no espirito do `conversas_chave_vendedor.html` (o dev abre e
avalia) — e (2) `transcritos.jsonl` maquina-legivel (uma conversa por linha). NAO computa metrica
nova: so serializa o que `avaliacao`/`conduta` ja produziram.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from evals.estilometria import bolhas

if TYPE_CHECKING:
    from evals.e2e.avaliacao import VeredictoE2E
    from evals.e2e.perfil import PerfilCaso
    from evals.e2e.runner import ResultadoE2E

    Corrida = tuple[PerfilCaso, ResultadoE2E, VeredictoE2E]

_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:880px;
margin:0 auto;padding:24px 16px;background:#fafafa;color:#1a1a1a}
h1{font-size:20px;margin:0 0 4px} .sub{color:#666;font-size:13px;margin:0 0 24px}
.resumo{background:#fff;border:1px solid #e3e3e3;border-radius:12px;padding:12px 16px;margin:0 0 24px;
font-size:13px;white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.conv{background:#fff;border:1px solid #e3e3e3;border-radius:12px;padding:16px;margin:0 0 24px}
.hd{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #eee;
padding-bottom:8px;margin-bottom:12px;gap:8px;flex-wrap:wrap}
.nome{font-weight:600} .eixo{color:#888;font-size:12px}
.badges span{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;margin-left:4px}
.ok{background:#e6f6ea;color:#1a7f37} .bad{background:#fde8e8;color:#b42318} .neu{background:#eef;color:#3b3b9b}
.turno{margin:12px 0}
.cli,.age{padding:8px 12px;border-radius:12px;max-width:82%;white-space:pre-wrap;font-size:14px;
line-height:1.45;margin:3px 0;width:fit-content}
.cli{background:#eef1f5} .age{background:#dcf5dd;margin-left:auto}
.vazio{background:#f5f5f5;color:#999;font-style:italic}
.est{font-size:11px;color:#999;text-align:right;margin-top:2px}
.meta{font-size:12px;color:#666;margin-top:8px;border-top:1px dashed #eee;padding-top:8px}
.viol{color:#b42318;font-size:12px;margin-top:6px}
"""


def _registro(perfil: Any, res: Any, ver: Any) -> dict[str, Any]:
    """Achata uma corrida no dicionario que vira tanto o JSONL quanto o HTML."""
    turnos = [
        {
            "cliente": cli,
            "agente": t.texto,
            "estado": (t.estado_final or {}).get("estado"),
            "ia_pausada": bool((t.estado_final or {}).get("ia_pausada")),
            "tools": list(t.tool_calls),
            "custo_brl": round(t.metricas.custo_brl, 6),
        }
        for cli, t in zip(res.turnos_cliente, res.turnos, strict=False)
    ]
    return {
        "perfil": perfil.nome,
        "eixo": getattr(perfil, "eixo_comportamento", None),
        "desfecho_real": res.desfecho_real,
        "desfecho_conducao": res.desfecho_conducao,
        "estado_final": res.estado_final,
        "conduziu": ver.conduziu,
        "violacoes": list(ver.violacoes),
        "conduta": ver.conduta.to_dict() if ver.conduta else None,
        "n_turnos": res.n_turnos,
        "custo_brl": round(res.custo_brl, 6),
        "turnos": turnos,
    }


def _badges(reg: dict[str, Any]) -> str:
    out = [
        f'<span class="{"ok" if reg["conduziu"] else "bad"}">'
        f"{'conduziu' if reg['conduziu'] else 'nao conduziu'}</span>"
    ]
    if reg["violacoes"]:
        out.append(f'<span class="bad">{len(reg["violacoes"])} violacao(oes)</span>')
    cond = reg["conduta"]
    if cond:
        if cond.get("cotou"):
            out.append('<span class="neu">cotou</span>')
        if cond.get("empurrao"):
            out.append('<span class="bad">empurrao</span>')
        ed = cond.get("estilo_dist")
        if ed is not None:
            out.append(f'<span class="neu">estilo {ed:.3f}</span>')
    return '<span class="badges">' + "".join(out) + "</span>"


def _conversa_html(reg: dict[str, Any]) -> str:
    linhas = [
        '<div class="conv">',
        '<div class="hd"><span>'
        f'<span class="nome">{html.escape(reg["perfil"])}</span> '
        f'<span class="eixo">[{html.escape(str(reg["eixo"]))}]</span></span>'
        f"{_badges(reg)}</div>",
    ]
    for t in reg["turnos"]:
        linhas.append('<div class="turno">')
        linhas.append(f'<div class="cli">{html.escape(t["cliente"])}</div>')
        bs = bolhas(t["agente"]) if (t["agente"] or "").strip() else []
        if bs:
            for b in bs:
                linhas.append(f'<div class="age">{html.escape(b)}</div>')
        else:
            rotulo = "[IA pausou — handoff]" if t["ia_pausada"] else "[turno sem bolha de texto]"
            linhas.append(f'<div class="age vazio">{rotulo}</div>')
        marca = f"estado: {html.escape(str(t['estado']))}"
        if t["tools"]:
            marca += f"  ·  tools: {html.escape(', '.join(t['tools']))}"
        linhas.append(f'<div class="est">{marca}</div>')
        linhas.append("</div>")
    meta = (
        f"desfecho real (corpus): {html.escape(str(reg['desfecho_real']))}  ·  "
        f"desfecho conducao: {html.escape(reg['desfecho_conducao'])}  ·  "
        f"estado final: {html.escape(str(reg['estado_final']))}  ·  "
        f"{reg['n_turnos']} turnos  ·  R$ {reg['custo_brl']}"
    )
    linhas.append(f'<div class="meta">{meta}</div>')
    if reg["violacoes"]:
        linhas.append('<div class="viol">⚠ ' + html.escape("; ".join(reg["violacoes"])) + "</div>")
    linhas.append("</div>")
    return "\n".join(linhas)


def salvar_transcritos(
    saida: str | Path,
    corridas: list[Any],
    *,
    titulo: str = "Transcritos e2e — conduta",
    rel: dict[str, Any] | None = None,
) -> Path:
    """Grava HTML + JSONL (+ resumo.json) das `corridas` em `saida`. Devolve o diretorio.

    `corridas`: lista de (perfil, ResultadoE2E, VeredictoE2E). `rel`: o relatorio agregado do
    gate (vira `resumo.json` e o cabecalho do HTML). Idempotente (sobrescreve o diretorio)."""
    destino = Path(saida)
    destino.mkdir(parents=True, exist_ok=True)
    regs = [_registro(perfil, res, ver) for perfil, res, ver in corridas]

    with (destino / "transcritos.jsonl").open("w", encoding="utf-8") as fh:
        for reg in regs:
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")

    if rel is not None:
        (destino / "resumo.json").write_text(
            json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    cabecalho = (
        f'<div class="resumo">{html.escape(json.dumps(rel, ensure_ascii=False, indent=2))}</div>'
        if rel is not None
        else ""
    )
    doc = (
        f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        f"<title>{html.escape(titulo)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{html.escape(titulo)}</h1>"
        f'<p class="sub">{len(regs)} conversas — cliente x agente, com veredito de conduta. '
        "Avalie cada uma e me diga onde o agente desvia do Vendedor.</p>"
        f"{cabecalho}" + "\n".join(_conversa_html(reg) for reg in regs) + "</body></html>"
    )
    (destino / "transcritos.html").write_text(doc, encoding="utf-8")
    return destino
