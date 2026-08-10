"""Injeta a coluna 'Agente (IA)' no conversas_chave_vendedor.html a partir do JSON do replay.

Le `replay_agente.py` --out e, para cada section `chat` (c0..c7, na ordem de REFS), monta a
coluna direita: por turno, a fala REAL do cliente (rosa) + a resposta do agente (verde) + uma
linha-meta com o estado pos-turno e as tools chamadas (a inspecao interna). Onde o agente
pausou/emudeceu, mantem o turno com nota honesta. Rodape resume estado final, custo e ressalvas.

NAO gasta credito — so transforma HTML. Idempotente: detecta col-head.agente e nao duplica.

Uso:
  python scripts/eval_corpus/render_replay_html.py \
      --json /caminho/replay_resultado.json \
      --html conversas_chave_vendedor.html
"""

from __future__ import annotations

import argparse
import html
import json
import re
from typing import Any

_ESTILO_META = (
    "<style id=\"ag-replay-css\">"
    ".ag-meta{font-size:10.5px;color:#5a6b78;font-family:monospace;margin:-4px 6px 10px;"
    "padding-left:4px;line-height:1.45;}"
    ".ag-meta b{color:#0a7d6b;}"
    ".ag-mudo{color:#999;font-style:italic;}"
    "</style>"
)


def _esc(t: str) -> str:
    # o cliente-sim às vezes emite '<br>' literal como separador de bolha; trata como quebra
    return html.escape(t.replace("<br>", "\n")).replace("\n", "<br>")


def _bolha_cliente(texto: str) -> str:
    return (
        '<div class="row c"><div class="bubble"><span class="quem">Cliente</span>'
        f"{_esc(texto)}</div></div>"
    )


def _bolha_agente(texto: str, mudo: bool) -> str:
    if mudo:
        corpo = '<span class="ag-mudo">(IA pausada — handoff; sem resposta ao cliente)</span>'
    else:
        corpo = _esc(texto) if texto.strip() else '<span class="ag-mudo">(sem texto)</span>'
    return (
        '<div class="row v"><div class="bubble"><span class="quem">Agente (IA)</span>'
        f"{corpo}</div></div>"
    )


def _linha_meta(turno: dict[str, Any]) -> str:
    estado = turno.get("estado") or "—"
    tools = turno.get("tools") or []
    pix = turno.get("pix_status")
    partes = [f"estado=<b>{html.escape(str(estado))}</b>"]
    if pix:
        partes.append(f"pix={html.escape(str(pix))}")
    partes.append("tools: " + (", ".join(html.escape(t) for t in tools) if tools else "—"))
    return f'<div class="ag-meta">{" · ".join(partes)}</div>'


def _rodape(res: dict[str, Any]) -> str:
    if res.get("erro"):
        return f'<div class="nota-ag">⚠️ Replay falhou: <code>{html.escape(res["erro"])}</code></div>'
    bits = [
        f'estado final <code>{html.escape(str(res.get("estado_final")))}</code>',
        f'{res.get("n_turnos")} turnos',
        f'custo R${res.get("custo_brl")}',
    ]
    if res.get("pausado_em") is not None:
        bits.append(f'IA pausou no turno {res["pausado_em"]} (handoff)')
    if res.get("tipo_esperado"):
        bits.append(f'tipo esperado: {html.escape(str(res["tipo_esperado"]))}')
    return (
        '<div class="nota-ag"><b>Harness fiel ao WhatsApp</b> (grafo real, DeepSeek V4 Flash) — '
        + " · ".join(bits)
        + ". Cliente <b>simulado</b> (DeepSeek) ancorado na persona real da thread, reagindo ao "
        "agente; debounce (N bolhas/turno) + persistência da IA por bolha + ordem uuidv7, espelhando "
        "o estado do DB de produção. Modelo sintética (1h R$400 / 2h R$700, interno+externo).</div>"
    )


def _coluna_agente(res: dict[str, Any]) -> str:
    cabeca = '<div class="col"><div class="col-head agente">Agente (IA) · grafo real</div><div class="thread">'
    if res.get("erro"):
        corpo = f'<div class="placeholder">Replay falhou: {html.escape(res["erro"])}</div>'
        return cabeca + corpo + "</div></div>"
    linhas: list[str] = []
    for t in res.get("turnos", []):
        mudo = bool(t.get("ia_pausada")) and not (t.get("agente") or "").strip()
        linhas.append(_bolha_cliente(t.get("cliente", "")))
        linhas.append(_bolha_agente(t.get("agente", ""), mudo))
        linhas.append(_linha_meta(t))
    linhas.append(_rodape(res))
    return cabeca + "\n".join(linhas) + "</div></div>"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--html", required=True)
    args = ap.parse_args()

    with open(args.json, encoding="utf-8") as fh:
        dados = json.load(fh)
    resultados: list[dict[str, Any]] = dados["resultados"]

    with open(args.html, encoding="utf-8") as fh:
        doc = fh.read()

    if 'class="col-head agente"' in doc:
        raise SystemExit("HTML já tem coluna do agente — abortando para não duplicar.")

    # injeta o CSS da meta uma vez, antes de </style>
    doc = doc.replace("</style>", _ESTILO_META + "</style>", 1)

    # ordem dos resultados == ordem das sections c0..c7
    partes = doc.split("</section>")
    if len(partes) - 1 < len(resultados):
        raise SystemExit(f"sections={len(partes) - 1} < resultados={len(resultados)}")

    idx = 0
    for i, chunk in enumerate(partes):
        if 'class="compare"' not in chunk or idx >= len(resultados):
            continue
        col = _coluna_agente(resultados[idx])
        # insere a col do agente imediatamente antes do </div> que fecha o .compare
        cabeca_chunk, _, cauda = chunk.rpartition("</div>")
        partes[i] = cabeca_chunk + col + "</div>" + cauda
        idx += 1

    novo = "</section>".join(partes)

    # sub: agente passa a ficar à DIREITA (corrige o texto stale agente-à-esquerda)
    novo = re.sub(
        r"<b>Agente \(IA\)</b>\s*a esquerda, <b>Vendedor \(humano\)</b>\s*a direita",
        "<b>Vendedor (humano)</b> à esquerda, <b>Agente (IA)</b> à direita",
        novo,
    )

    with open(args.html, "w", encoding="utf-8") as fh:
        fh.write(novo)
    print(f"OK — {idx} colunas de agente injetadas em {args.html}")


if __name__ == "__main__":
    main()
