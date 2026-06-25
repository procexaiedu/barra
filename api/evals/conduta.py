"""Scorers de CONDUTA de venda sobre um transcript e2e (Camada 2): FORMA (fluxo), VOZ
(estilometria) e DISCIPLINA (anti-empurrao). Puros e deterministicos — sem DB/rede/LLM, como
`checks.py`/`sequencia.py`. Comparam o transcript do AGENTE contra baselines humanos CONGELADOS
em `evals/baselines/` (agregados, sem texto cru; gerados por `evals.baselines.gerar`).

Fronteira de leitura (honestidade, ver plano):
  - So significativo sobre transcript REAL. No modo --fake o texto e canned, entao os numeros
    nao representam conduta — o --fake valida o encanamento, nao o veredito.
  - FORMA (fluxo) e POPULACIONAL: JSD sobre a distribuicao de transicoes de atos de MUITAS
    conversas vs o baseline humano. Uma conversa so e' alto-variancia -> `fluxo_jsd_populacao`
    recebe a LISTA de corridas, nao uma so.
  - VOZ e DISCIPLINA sao por-conversa (a estilometria agrega as bolhas da corrida; o empurrao
    olha o turno da cotacao) -> entram no `CondutaScore` de cada `VeredictoE2E`.

A aprovacao e RELATIVA ao piso de ruido (ELA-vs-ELA / eb-split) gravado nos baselines, nunca um
absoluto. Os limiares (pass bar) vivem na POLITICA do gate (`evals.e2e.conduta_gate`), nao aqui.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from barra.agente.fluxo import js_divergencia, matriz_transicao, rotular_turno
from evals.estilometria import bolhas, carregar_perfil, distancia, perfil_de_bolhas

if TYPE_CHECKING:
    from evals.e2e.runner import ResultadoE2E

_BASELINES = Path(__file__).parent / "baselines"


# --- DISCIPLINA: detector regex de empurrao --------------------------------------------------

# Empurrao = no turno da COTACAO (turno do preco) ha urgencia/CTA de fechamento COLADA ao numero
# ('seria agora?', 'vamos fechar?', 'bora?'). Definicao do juiz em sim_deepseek.py:89 (`f_glued_
# urgency`), aqui como regex determinista (proxy do juiz LLM). Sondar o DIA antes do preco
# ('seria hoje?') NAO conta — por isso 'seria\s+agora' entra mas 'seria hoje' nao casa.
# v1 conservador; calibrar o recall contra o corpus na corrida §0 (ver plano: fallback p/ judge).
_EMPURRAO_RE = re.compile(
    r"vamos\s+fechar|bora\s+fechar|bora\s+marcar|\bbora\b\s*[?!]|"
    r"seria\s+agora|vamos\s+agora|fecham?os\s+(agora|ent[ãa]o|isso)|"
    r"me\s+confirma\s+(agora|j[áa])|posso\s+(te\s+)?(garantir|encaixar|reservar)|"
    r"garante?\s+(seu|o)\s+hor[áa]rio|fecha\s+comigo|"
    r"s[óo]\s+(hoje|por\s+hoje)\b|[úu]ltim[ao]\s+(vaga|hor[áa]rio)|"
    r"aproveita\s+(que|agora)|vou\s+te\s+encaixar\s+agora",
    re.IGNORECASE,
)


def tem_empurrao(texto: str) -> bool:
    """CTA de fechamento colada ao texto (detector regex). Publico: reusado pelo gerador de
    baseline (`evals.baselines.gerar`) sobre os turnos de cotacao do corpus humano."""
    return bool(_EMPURRAO_RE.search(texto or ""))


def empurrao_na_cotacao(res: ResultadoE2E) -> tuple[bool, bool]:
    """(cotou, empurrao). `cotou`: houve turno do agente rotulado como cotacao. `empurrao`:
    esse turno traz CTA de fechamento colada ao preco. Olha so o 1o turno de cotacao."""
    for t in res.turnos:
        texto = t.texto or ""
        if rotular_turno(texto) == "cotacao":
            return True, tem_empurrao(texto)
    return False, False


# --- VOZ: estilometria sobre as bolhas do agente ---------------------------------------------


def carregar_perfil_estilo(path: str | Path | None = None) -> dict[str, Any]:
    """Perfil estilometrico congelado d'ELA. Erro claro se o baseline ainda nao foi gerado."""
    p = Path(path) if path else _BASELINES / "estilo_corpus.json"
    if not p.exists():
        raise FileNotFoundError(
            f"baseline de estilo ausente em {p} — rode `python -m evals.baselines.gerar` "
            "(§0 read-only sobre o corpus) e commite o JSON agregado."
        )
    return carregar_perfil(p)


def estilo_dist(res: ResultadoE2E, *, perfil: dict[str, Any] | None = None) -> float | None:
    """Distancia estilometrica agregada das bolhas do agente vs o perfil congelado. None se a
    corrida nao produziu nenhuma bolha textual (ex.: pausou no 1o turno)."""
    bs = [b for t in res.turnos if (t.texto or "").strip() for b in bolhas(t.texto)]
    if not bs:
        return None
    if perfil is None:
        perfil = carregar_perfil_estilo()
    return distancia(perfil, perfil_de_bolhas(bs))["agregado"]


# --- FORMA: fluxo do funil (populacional) ----------------------------------------------------


def _atos_do_agente(res: ResultadoE2E) -> list[str]:
    """Sequencia de atos dos turnos do agente (lado 'M' do funil)."""
    return [rotular_turno(t.texto) for t in res.turnos if (t.texto or "").strip()]


def carregar_baseline_fluxo(
    path: str | Path | None = None,
) -> tuple[Counter[tuple[str, str]], dict[str, Any]]:
    """Counter de transicoes de atos do corpus humano + meta (piso JSD). Erro claro se ausente."""
    p = Path(path) if path else _BASELINES / "fluxo_atos.json"
    if not p.exists():
        raise FileNotFoundError(
            f"baseline de fluxo ausente em {p} — rode `python -m evals.baselines.gerar` "
            "(§0 read-only sobre o corpus) e commite o JSON agregado."
        )
    doc = json.loads(p.read_text(encoding="utf-8"))
    c: Counter[tuple[str, str]] = Counter()
    for chave, v in doc["transicoes"].items():
        a, b = chave.split(">")
        c[(a, b)] = v
    return c, doc.get("__meta__", {})


def fluxo_jsd_populacao(
    lista_res: list[ResultadoE2E], *, baseline: Counter[tuple[str, str]] | None = None
) -> float:
    """JSD das transicoes de atos do AGENTE (todas as corridas) vs o baseline humano congelado.
    Populacional: passe a lista inteira de corridas. `baseline` injetavel (teste sem arquivo)."""
    if baseline is None:
        baseline, _ = carregar_baseline_fluxo()
    seqs = [s for s in (_atos_do_agente(r) for r in lista_res) if s]
    return js_divergencia(baseline, matriz_transicao(seqs))


# --- agregacao por-conversa (entra no VeredictoE2E) ------------------------------------------


@dataclass
class CondutaScore:
    """Conduta de UMA corrida e2e. FORMA (fluxo) e populacional -> nao entra aqui."""

    cotou: bool
    empurrao: bool
    estilo_dist: float | None  # None: sem bolha textual, ou baseline ainda nao gerado

    def to_dict(self) -> dict[str, Any]:
        return {"cotou": self.cotou, "empurrao": self.empurrao, "estilo_dist": self.estilo_dist}


def avaliar_conduta(
    res: ResultadoE2E, *, perfil_estilo: dict[str, Any] | None = None
) -> CondutaScore:
    """Conduta por-conversa (voz + disciplina). Sem baseline de estilo committado, `estilo_dist`
    fica None (a corrida real o gera) — nao quebra as corridas existentes (massa/sessao)."""
    cotou, empurrao = empurrao_na_cotacao(res)
    try:
        ed = estilo_dist(res, perfil=perfil_estilo)
    except FileNotFoundError:
        ed = None
    return CondutaScore(cotou=cotou, empurrao=empurrao, estilo_dist=ed)
