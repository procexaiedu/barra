"""Extrai UMA conversa de um `conversas*.jsonl` para o root-cause do Loop A, sem estourar contexto.

O campo `prompt_montado` de cada turno `ia` tem ~24k chars (o SystemMessage montado do agente). Um
subagente de root-cause que carregasse o jsonl inteiro (vários cenários x várias falas x 24k) estoura
o contexto -- o handoff alerta explicitamente. Este CLI imprime UMA conversa como TRANSCRITO legível
(falas + sinais de diagnóstico do turno: estado/ia_pausada/pix_status/tools/escalou/tool_io/nodes/
extracao), OMITINDO `prompt_montado`/`thinking` por padrão; e só anexa o prompt de UM turno `ia`
(`--prompt-do-turno IDX`) quando o root-cause precisa do prompt exato que gerou a falha.

Começa pelo veredito determinístico (reusa `classificar`) para o agente ver terminal/flags/motivo de
imediato -- muitos modos de falha (FP do piso, degradação) já se diagnosticam dali, sem ler o prompt.

    uv run python -m evals.diagnostico.extrair <jsonl> <conversa_id>
    uv run python -m evals.diagnostico.extrair <jsonl> <conversa_id> --prompt-do-turno 3

PURO/OFFLINE: zero LLM, zero API, zero DB.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .classificar import carregar_conversas, classificar


def _achar(conversas: list[dict[str, Any]], conversa_id: str) -> dict[str, Any] | None:
    for c in conversas:
        if str(c.get("conversa_id") or c.get("cenario") or "") == conversa_id:
            return c
    return None


def _linha_ia(t: dict[str, Any]) -> str:
    """Sinais de diagnóstico de um turno ia, em uma linha compacta (sem o prompt_montado)."""
    sinais = [
        f"estado={t.get('estado')}",
        f"ia_pausada={t.get('ia_pausada')}",
        f"pix_status={t.get('pix_status')}",
        f"escalou={t.get('escalou')}",
    ]
    if t.get("tools"):
        sinais.append(f"tools={t['tools']}")
    if t.get("nodes"):
        sinais.append(f"nodes={t['nodes']}")
    if t.get("extracao"):
        sinais.append(f"extracao={json.dumps(t['extracao'], ensure_ascii=False)}")
    return "      ↳ " + " ".join(sinais)


def transcrito(conversa: dict[str, Any]) -> str:
    """Monta o transcrito legível da conversa (sem prompt_montado/thinking)."""
    v = classificar(conversa)
    linhas: list[str] = [
        f"== {v.conversa_id} (cenario={conversa.get('cenario')}) ==",
        f"VEREDITO det.: terminal={v.terminal} e2e_completo={v.e2e_completo} "
        f"motivo_escalada={v.motivo_escalada} estado_final={v.estado_final} "
        f"ia_pausada_final={v.ia_pausada_final} avancou_estado={v.avancou_estado}",
        f"FLAGS: {list(v.flags) or '—'}",
        f"(precisa_julgamento={v.precisa_julgamento}; o classificador NUNCA crava e2e_limpo=True "
        f"sozinho -- persona/conduta são SEU julgamento contra regua_persona.md)",
        "",
    ]
    for t in conversa.get("turnos", []) or []:
        papel = t.get("papel")
        if papel == "ato":
            linhas.append(
                f"  [ato] {t.get('ato')}  (estado={t.get('estado')} "
                f"ia_pausada={t.get('ia_pausada')} pix_status={t.get('pix_status')})"
            )
        elif papel == "cliente":
            linhas.append(f"  CLIENTE: {t.get('texto')}")
        elif papel == "ia":
            linhas.append(f"  [ia idx={t.get('idx')}] {t.get('texto')}")
            linhas.append(_linha_ia(t))
            for io in t.get("tool_io") or []:
                linhas.append(f"        tool_io: {json.dumps(io, ensure_ascii=False, default=str)}")
    return "\n".join(linhas)


def prompt_do_turno(conversa: dict[str, Any], idx: int) -> str | None:
    """O `prompt_montado` (SystemMessage) do turno ia de índice `idx`, ou None se não houver."""
    for t in conversa.get("turnos", []) or []:
        if t.get("papel") == "ia" and t.get("idx") == idx:
            return t.get("prompt_montado")
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # console Windows cp1252
    parser = argparse.ArgumentParser(description="Extrai uma conversa p/ root-cause (offline).")
    parser.add_argument("jsonl", help="o conversas*.jsonl.")
    parser.add_argument("conversa_id", help="conversa_id (ou cenario) a extrair.")
    parser.add_argument(
        "--prompt-do-turno",
        type=int,
        default=None,
        metavar="IDX",
        help="anexa o prompt_montado (~24k chars) do turno ia idx=IDX -- só do que falhou.",
    )
    args = parser.parse_args()

    p = Path(args.jsonl)
    if not p.exists():
        print(f"{p} não existe.", file=sys.stderr)
        raise SystemExit(2)
    conversa = _achar(carregar_conversas(p), args.conversa_id)
    if conversa is None:
        print(f"conversa_id {args.conversa_id!r} não encontrada em {p}.", file=sys.stderr)
        raise SystemExit(2)

    print(transcrito(conversa))
    if args.prompt_do_turno is not None:
        pm = prompt_do_turno(conversa, args.prompt_do_turno)
        print(f"\n== prompt_montado do turno ia idx={args.prompt_do_turno} ==")
        print(pm if pm is not None else "(turno ia idx não encontrado ou sem prompt_montado)")


if __name__ == "__main__":
    main()
