"""Carimbo de contexto: detector de regressao a custo ~zero de API (Fase A do gate).

A tese: **a conduta e funcao do prompt montado**. Se o contexto que um cenario produz sai
identico ao da ultima vez e o modelo e o mesmo, o NOSSO codigo nao regrediu ali — e montar esse
contexto nao precisa do LLM. O `--fake` da massa ja monta os 73 por R$ 0,01; o que se paga hoje e
chamar o modelo para descobrir o que um hash responde de graca.

Isso ataca de frente a regressao mais silenciosa do projeto: a **tag que some do contexto** sem
ninguem notar (uma coluna fora do SELECT basta), que hoje so aparece quando alguem repara numa
conduta estranha numa corrida cara.

O carimbo de cada cenario tem quatro camadas, e cada uma pega uma classe distinta:

1. `prompt_hash`  — o contexto inteiro, NORMALIZADO (ver `normalizar_prompt`). Pega qualquer
   mudanca; e o alarme largo, nao o diagnostico.
2. `tags`         — as tags de bloco presentes no contexto. E o diagnostico: quando o hash muda,
   o diff das tags diz O QUE mudou, e uma tag que sumiu reprova mesmo que o hash tivesse mudado
   por motivo legitimo.
3. `nodes`/`tools`— trajetoria do grafo. Pega desvio de rota (no que deixou de ser visitado,
   tool que sumiu do bind) sem custo nenhum de LLM.
4. `estado`/`pix` — a FSM pos-turno. Pega regressao de DOMINIO, que e codigo deterministico e nao
   depende do modelo: transicao que deixou de acontecer, `pix_status` que nao muda mais.

⚠️ O QUE ISTO **NAO** MEDE: conduta. Prompt identico + modelo trocado (ou build novo do DeepSeek,
que nao tem snapshot pinavel) = carimbo verde com conduta diferente. Por isso a Fase A **nunca**
substitui a Fase B: ela decide QUEM roda no LLM, e um punhado de sentinelas roda sempre,
justamente para pegar o drift do provider que nenhum hash enxerga.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

BASELINE = Path(__file__).resolve().parent / "baseline_carimbos.json"

# --- normalizacao ------------------------------------------------------------------------------
# Sem isto o hash muda a CADA corrida e o instrumento nao serve para nada. Cada padrao aqui e uma
# coisa que varia sem que nada tenha regredido — e a lista e deliberadamente CURTA: normalizar
# demais cega o detector (um valor de tabela virando placeholder esconderia o bug de preco).
_VOLATEIS: tuple[tuple[re.Pattern[str], str], ...] = (
    # O delimitador do spotlight (`prepare_context._cercar_dado_midia`) e um sha do id INTERNO da
    # mensagem — uuidv7 novo a cada seed, logo diferente em toda corrida. E o unico caso em que o
    # proprio mecanismo de defesa injeta entropia no prompt.
    (re.compile(r"\b(AUDIO|LEGENDA)_[0-9a-f]{8}\b"), r"\1_<HASH>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<UUID>"),
    # Datas e horas de relogio: o cenario sem `agora` declarado usa relogio de parede, entao o
    # <agenda> e o <periodo_de_trabalho> mudam de um dia para o outro sem regressao nenhuma.
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "<DATA>"),
    (re.compile(r"\b\d{2}/\d{2}(?:/\d{2,4})?\b"), "<DATA>"),
    (
        re.compile(
            r"\b(?:segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)(?:-feira)?\b", re.I
        ),
        "<DIASEM>",
    ),
    # Minutos desde a ultima mensagem do cliente: conta do relogio real, muda sempre.
    (re.compile(r'minutos="\d+"'), 'minutos="<N>"'),
    (re.compile(r"\btest-(?:wpp|evo)-[0-9a-f]+\b"), "<ID_TESTE>"),
)

# Tag de bloco do turno: `<nome>` / `<nome attr="...">` / `<nome/>`. Le so o NOME — o conteudo ja
# esta no hash, e uma lista de nomes e o que da diff legivel quando o hash muda.
_RE_TAG = re.compile(r"<(/?)([a-z_]{3,60})(?:\s[^>]*)?/?>")


def normalizar_prompt(texto: str) -> str:
    """Zera o que varia entre corridas sem que nada tenha mudado no codigo."""
    for padrao, subst in _VOLATEIS:
        texto = padrao.sub(subst, texto)
    return texto


def tags_do_prompt(partes: list[str]) -> list[str]:
    """Os nomes de tag presentes no contexto, ordenados e sem repeticao.

    Ordenado (e nao na ordem de renderizacao) de proposito: a ordem dos blocos e detalhe de
    montagem que o `prompt_hash` ja cobre; o que esta camada responde e a pergunta binaria "a tag
    esta la?", que e a que o mecanismo da tag-que-some derruba.
    """
    return sorted({m.group(2) for p in partes for m in _RE_TAG.finditer(p)})


def carimbar(res: Any) -> dict[str, Any]:
    """O carimbo de UMA corrida de cenario (`ResultadoE2E`)."""
    partes = [p for turno in res.turnos for p in turno.prompt_modelo]
    normalizado = "\n".join(normalizar_prompt(p) for p in partes)
    ultimo = res.turnos[-1].estado_final if res.turnos else {}
    return {
        "prompt_hash": hashlib.sha256(normalizado.encode()).hexdigest()[:16],
        "tags": tags_do_prompt(partes),
        "nodes": sorted({n for turno in res.turnos for n in turno.nodes}),
        "tools": sorted({t for turno in res.turnos for t in turno.tool_calls}),
        "estado": (ultimo or {}).get("estado"),
        "pix": (ultimo or {}).get("pix_status"),
        "n_turnos": len(res.turnos),
    }


# --- comparacao --------------------------------------------------------------------------------


def comparar(novo: dict[str, Any], velho: dict[str, Any]) -> list[str]:
    """As diferencas entre dois carimbos, em linguagem de diagnostico (vazio = sem mudanca).

    A tag AUSENTE vem primeiro e com destaque porque e a unica cuja leitura ja e o veredito: as
    outras linhas dizem "mudou, va olhar"; essa diz "um bloco sumiu do contexto".
    """
    diffs: list[str] = []
    sumiram = sorted(set(velho.get("tags") or []) - set(novo.get("tags") or []))
    surgiram = sorted(set(novo.get("tags") or []) - set(velho.get("tags") or []))
    if sumiram:
        diffs.append(f"⚠ TAG AUSENTE no contexto: {', '.join(sumiram)}")
    if surgiram:
        diffs.append(f"tag nova: {', '.join(surgiram)}")
    for campo in ("nodes", "tools"):
        so_velho = sorted(set(velho.get(campo) or []) - set(novo.get(campo) or []))
        so_novo = sorted(set(novo.get(campo) or []) - set(velho.get(campo) or []))
        if so_velho:
            diffs.append(f"{campo} que sumiu: {', '.join(so_velho)}")
        if so_novo:
            diffs.append(f"{campo} novo: {', '.join(so_novo)}")
    for campo in ("estado", "pix", "n_turnos"):
        if novo.get(campo) != velho.get(campo):
            diffs.append(f"{campo}: {velho.get(campo)!r} -> {novo.get(campo)!r}")
    # Por ultimo: sem nenhuma das linhas acima, o hash sozinho diz "o TEXTO de algum bloco mudou"
    # (uma frase do prompt reescrita), que e mudanca legitima na maioria das vezes.
    if novo.get("prompt_hash") != velho.get("prompt_hash") and not diffs:
        diffs.append("texto de bloco mudou (tags, rota e estado intactos)")
    return diffs


def carregar_baseline() -> dict[str, Any]:
    if not BASELINE.exists():
        return {}
    dados: dict[str, Any] = json.loads(BASELINE.read_text(encoding="utf-8"))
    return dados


def gravar_baseline(carimbos: dict[str, Any]) -> None:
    BASELINE.write_text(
        json.dumps(carimbos, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
