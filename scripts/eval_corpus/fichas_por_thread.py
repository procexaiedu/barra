"""Fichas por THREAD para o shadow do funil — evidência literal da própria conversa.

Por que existe: o shadow seedava a ficha da INSTÂNCIA (MODELOS_REAIS), mas cada instância
atende por várias modelos. O enriquecimento por instância pôs "Completo (com anal)" em toda
eb02 e criou derrotas-artefato: o agente, coerente com a ficha seedada, contradiz a vendedora
real DAQUELA thread e o juiz pune (rodada 3: 4 das 6 derrotas de recusa_limite no dev).

Regra de fidelidade (§3 do plano): NUNCA inventar — só evidência LITERAL de turnos `from_me`
da própria thread; ambíguo → campo ausente → fallback para a ficha da instância no merge do
`evals/shadow/funil.py`. Cada ficha registra as evidências (auditável).

Uso:
    DATABASE_URL=... uv run python fichas_por_thread.py \
        pontos_decisao_amostra.jsonl pontos_decisao_heldout.jsonl
    -> _dados_reais/fichas_por_thread.json  (gitignored: PII)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "_dados_reais" / "fichas_por_thread.json"

# --- detectores (calibrados na amostra real do corpus; conservadores por desenho) ---

# "400 1h", "Cache 500 1h", "1h 600" — preço interno; "+uber" perto = externo (fora).
_PRECO_1H = re.compile(r"\b(\d{3,4})\s*(?:a\s+)?1\s*h(?:ora)?\b|\b1\s*h(?:ora)?\s+(\d{3,4})\b", re.I)
_PRECO_1H_MIL = re.compile(r"\b1\s*h(?:ora)?\s+mil\b|\bmil\s+(?:a\s+)?1\s*h\b", re.I)
_PRECO_30MIN = re.compile(
    r"\b(\d{2,4})\s*(?:a\s+)?(?:30\s*min\w*|meia\s*hora)\b|\b(?:30\s*min\w*|meia\s*hora)\s+(\d{2,4})\b",
    re.I,
)
_UBER_PERTO = re.compile(r"\+\s*uber|uber", re.I)
_COMPLETO_PERTO = re.compile(r"\bcompleto\b|\bcom\s+anal\b", re.I)

_NAO_FAZ_ANAL = re.compile(r"n[ãa]o\s+fa[çc]o\s+(?:o\s+)?anal|anal\s+n[ãa]o(?:\s+fa[çc]o)?\b", re.I)
_NAO_FAZ_NATURAL = re.compile(
    r"n[ãa]o\s+fa[çc]o\s+(?:sem\s+camisinha|natural)|s[óo]\s+com\s+camisinha", re.I
)
_BEIJO = re.compile(r"beijo\s+na\s+boca", re.I)
_ORAL_SEM = re.compile(r"\boral\s+sem\b", re.I)

_ENDERECO = re.compile(
    r"\b(?:av|avenida|rua|r\.)\.?\s+[\w\sãáéíóúâêôç]{2,40}?,?\s+\d{1,5}\b", re.I
)
_HOTEL = re.compile(r"\bhotel\s+[\w'áéíóú]{3,20}", re.I)
_LOCALIZACAO = re.compile(r"\b(?:estou|to|tô)\s+(?:no|na|em)\s+([\w\sãáéíóúç]{4,35})", re.I)


def _janela(texto: str, ini: int, fim: int, raio: int = 40) -> str:
    return texto[max(0, ini - raio) : fim + raio]


def extrair_ficha(turnos_from_me: list[str]) -> dict[str, Any] | None:
    """Ficha da thread a partir das falas literais da vendedora. None = sem evidência."""
    precos_encontro: Counter[int] = Counter()
    precos_completo: Counter[int] = Counter()
    precos_30min: Counter[int] = Counter()
    nao_faz: set[str] = set()
    fetiches: set[str] = set()
    enderecos: Counter[str] = Counter()
    hoteis: Counter[str] = Counter()
    locais: Counter[str] = Counter()
    evid: dict[str, list[str]] = {}

    def anota(campo: str, trecho: str) -> None:
        evid.setdefault(campo, [])
        if len(evid[campo]) < 3:
            evid[campo].append(trecho.strip()[:80])

    for texto in turnos_from_me:
        for m in _PRECO_1H.finditer(texto):
            jan = _janela(texto, m.start(), m.end())
            if _UBER_PERTO.search(jan):
                continue  # preço externo (deslocamento), não é a linha do cardápio
            valor = int(m.group(1) or m.group(2))
            if not 100 <= valor <= 5000:
                continue
            if _COMPLETO_PERTO.search(jan):
                precos_completo[valor] += 1
                anota("programa_completo", jan)
            else:
                precos_encontro[valor] += 1
                anota("programa_encontro", jan)
        for m in _PRECO_1H_MIL.finditer(texto):
            jan = _janela(texto, m.start(), m.end())
            if _UBER_PERTO.search(jan):
                continue
            if _COMPLETO_PERTO.search(jan):
                precos_completo[1000] += 1
                anota("programa_completo", jan)
            else:
                precos_encontro[1000] += 1
                anota("programa_encontro", jan)
        for m in _PRECO_30MIN.finditer(texto):
            jan = _janela(texto, m.start(), m.end())
            if _UBER_PERTO.search(jan):
                continue
            valor = int(m.group(1) or m.group(2))
            if 100 <= valor <= 5000:
                precos_30min[valor] += 1
                anota("programa_30min", jan)
        if _NAO_FAZ_ANAL.search(texto):
            nao_faz.add("anal")
            anota("nao_faz", _NAO_FAZ_ANAL.search(texto).group(0))
        if _NAO_FAZ_NATURAL.search(texto):
            nao_faz.add("sem camisinha (natural)")
            anota("nao_faz", _NAO_FAZ_NATURAL.search(texto).group(0))
        if _BEIJO.search(texto):
            fetiches.add("beijo na boca")
            anota("fetiches", _BEIJO.search(texto).group(0))
        if _ORAL_SEM.search(texto):
            fetiches.add("Oral sem camisinha")
            anota("fetiches", _ORAL_SEM.search(texto).group(0))
        for m in _ENDERECO.finditer(texto):
            enderecos[m.group(0).strip()] += 1
            anota("endereco", m.group(0))
        for m in _HOTEL.finditer(texto):
            hoteis[m.group(0).strip()] += 1
            anota("local", m.group(0))
        for m in _LOCALIZACAO.finditer(texto):
            locais[m.group(1).strip()] += 1

    ficha: dict[str, Any] = {}

    # "não faço anal" na thread vence qualquer menção a completo (recusa > oferta ambígua)
    if "anal" in nao_faz:
        precos_completo.clear()

    def moda(c: Counter[int]) -> int:
        top = c.most_common()
        melhor_n = top[0][1]
        return max(v for v, n in top if n == melhor_n)  # empate → maior (base pré-desconto)

    programas: list[dict[str, Any]] = []
    if precos_encontro:
        programas.append(
            {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "ordem": 1,
             "preco": moda(precos_encontro)}
        )
    if precos_completo:
        programas.append(
            {"nome": "Completo", "duracao_nome": "1 hora", "horas": 1,
             "preco": moda(precos_completo)}
        )
    if precos_30min:
        programas.append(
            {"nome": "Encontro", "duracao_nome": "30 minutos", "horas": 0.5, "ordem": 0,
             "preco": moda(precos_30min)}
        )
    if programas:
        ficha["programas"] = programas
    if fetiches:
        ficha["fetiches"] = [
            {"nome": n, "preco": None, "cobra_por_pessoa": False} for n in sorted(fetiches)
        ]
    if nao_faz:
        ficha["nao_faz"] = sorted(nao_faz)  # seed ignora; auditoria + closed-world via ausência
    if enderecos:
        ficha["endereco_formatado"] = enderecos.most_common(1)[0][0]
    if hoteis and not enderecos:
        ficha["endereco_formatado"] = hoteis.most_common(1)[0][0]
    if locais:
        ficha["localizacao_operacional"] = locais.most_common(1)[0][0]

    if not ficha:
        return None
    ficha["_evidencias"] = {campo: {"n": len(ex), "exemplos": ex} for campo, ex in evid.items()}
    return ficha


async def _main(arquivos_pontos: list[str]) -> None:
    refs: set[str] = set()
    for arq in arquivos_pontos:
        caminho = Path(arq) if os.path.isabs(arq) else AQUI / "_dados_reais" / arq
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha:
                refs.add(json.loads(linha)["ref"])

    conn = await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"])
    await conn.set_read_only(True)
    fichas: dict[str, Any] = {}
    campos: Counter[str] = Counter()
    try:
        for ref in sorted(refs):
            instancia, remote_jid = ref.split(":", 1)
            cur = await conn.execute(
                """
                SELECT COALESCE(texto, '') AS texto FROM corpus.turnos
                WHERE instancia = %s AND remote_jid = %s AND from_me
                ORDER BY turno_idx
                """,
                (instancia, remote_jid),
            )
            falas = [r["texto"] if isinstance(r, dict) else r[0] for r in await cur.fetchall()]
            ficha = extrair_ficha([f for f in falas if f])
            if ficha:
                fichas[ref] = ficha
                for c in ficha:
                    if not c.startswith("_"):
                        campos[c] += 1
    finally:
        await conn.close()

    SAIDA.write_text(json.dumps(fichas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"threads: {len(refs)}  com ficha própria: {len(fichas)}  "
          f"fallback instância: {len(refs) - len(fichas)}")
    for campo, n in campos.most_common():
        print(f"  {campo:24s} {n}")
    print(f"-> {SAIDA}")


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:] or ["pontos_decisao_amostra.jsonl", "pontos_decisao_heldout.jsonl"]))
