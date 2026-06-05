"""Expansao .jsonl -> falas julgaveis da IA (puro/offline; nucleo da rotulagem).

Replica fielmente a logica de `docs/agente/evals-notas.html` (`parseJsonl`, `falasDe`,
`falaKey`, `historicoAte`) para que o `fala_id`/`texto_resposta`/`historico` materializados
no Postgres batam EXATAMENTE com o golden que `evals/calibracao/calibrar.py` consome. Sem
rede/DB -> testavel no `make test`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Rotulo legivel dos atos dual-control no historico (espelha ATO_LABEL do HTML).
ATO_LABEL: dict[str, str] = {
    "enviar_pix_valido": "💸 cliente enviou o comprovante de Pix (validado)",
    "enviar_pix_duvidoso": "💸 cliente enviou o comprovante de Pix (duvidoso)",
    "enviar_foto_portaria": "📸 cliente enviou a foto da portaria (chegou)",
    "enviar_aviso_saida": "🚶 cliente avisou que saiu de casa",
    "ficar_em_silencio": "… cliente ficou em silêncio",
}


@dataclass(frozen=True)
class Fala:
    """Uma fala da IA a ser rotulada (snapshot do que o judge avalia)."""

    fala_id: str  # conversa_id::idx
    conversa_id: str
    cenario: str
    texto_resposta: str
    historico: list[str]  # turnos ANTES da fala: 'cliente: …' / 'ia: …' / '[ato]'
    ordem: int  # ordem global de exibicao na rodada


def parse_jsonl(texto: str) -> list[dict[str, Any]]:
    """Le conversas de um .jsonl (espelha `parseJsonl` do HTML).

    Pula linhas vazias, o `_header` de template e linhas sem `conversa_id`/`turnos` (lista).
    Levanta `json.JSONDecodeError` em linha sintaticamente invalida (o caller transforma em 400).
    """
    conversas: list[dict[str, Any]] = []
    for bruto in texto.splitlines():
        bruto = bruto.strip()
        if not bruto:
            continue
        obj = json.loads(bruto)
        if "_header" in obj:
            continue
        if not obj.get("conversa_id") or not isinstance(obj.get("turnos"), list):
            continue
        conversas.append(obj)
    return conversas


def _historico_ate(turnos: list[dict[str, Any]], pos_fala: int) -> list[str]:
    """Historico = todos os turnos ANTES da fala (por posicao no array).

    Equivale ao `historicoAte` do HTML: como o break la ocorre exatamente na fala-alvo, parar
    na posicao da fala no array produz o mesmo resultado, sem depender do campo `idx`.
    """
    hist: list[str] = []
    for t in turnos[:pos_fala]:
        papel = t.get("papel")
        if papel == "ia":
            hist.append("ia: " + str(t.get("texto", "")))
        elif papel == "cliente":
            hist.append("cliente: " + str(t.get("texto", "")))
        elif papel == "ato":
            ato = str(t.get("ato", ""))
            hist.append("[" + ATO_LABEL.get(ato, ato) + "]")
    return hist


def falas_de(conversas: list[dict[str, Any]]) -> list[Fala]:
    """Expande conversas em falas julgaveis (turnos `papel=="ia"`), na ordem do arquivo.

    `idx` (chave de rotulagem) vem do campo `idx` gravado por gerar_conversas.py; se ausente,
    enumera as falas da IA na conversa (fallback robusto). `fala_id = conversa_id::idx`.
    """
    falas: list[Fala] = []
    ordem = 0
    for conv in conversas:
        conversa_id = str(conv["conversa_id"])
        cenario = str(conv.get("cenario") or conversa_id)
        turnos = conv["turnos"]
        contador_ia = 0
        for pos, t in enumerate(turnos):
            if t.get("papel") != "ia":
                continue
            idx = t["idx"] if t.get("idx") is not None else contador_ia
            contador_ia += 1
            falas.append(
                Fala(
                    fala_id=f"{conversa_id}::{idx}",
                    conversa_id=conversa_id,
                    cenario=cenario,
                    texto_resposta=str(t.get("texto", "")),
                    historico=_historico_ate(turnos, pos),
                    ordem=ordem,
                )
            )
            ordem += 1
    return falas
