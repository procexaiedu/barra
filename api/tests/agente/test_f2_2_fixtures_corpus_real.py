"""F2.2 — fixtures de gate apontam p/ conversas reais anonimizadas.

Gate determinístico **sem banco** (espelha F0.2/F0.10/F1.4 — regex/parse puro, roda no
`make test` padrão, não `needs_db`). Tranca o critério do roadmap F2.2:

  "Corpus curado de conversas reais substitui os 'templates ilustrativos' do README"
  → "diretórios de fixtures apontam p/ conversas reais anonimizadas"

O ponteiro já existe na convenção do repo: cada fixture crítica de gate
(`canonicos/scripted_5/`) destila um cenário real e **cita a conversa de origem** pelo
marcador `#NNN` no campo `descricao` (ex.: `#001` →
`docs/agente/conversas-reais/001-interno-confirmado-anal-recusa-desconto.md`). Este gate
prova que (1) o corpus é real e não-trivial, (2) **todo** `#NNN` citado por uma fixture
resolve a um arquivo real do corpus (zero ponteiro pendente/dangling) e o conjunto de
ponteiros é significativo, e (3) o README não regride à alegação obsoleta de "templates
ilustrativos" e aponta para o corpus real.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# api/tests/agente/test_*.py → parents: [0]=agente [1]=tests [2]=api [3]=raiz do repo
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_DIR = _REPO_ROOT / "docs" / "agente" / "conversas-reais"
_EVALS_DIR = _REPO_ROOT / "api" / "evals"
_README = _EVALS_DIR / "README.md"

# Conversa real anonimizada: NNN-<slug>.md (NNN = 3 dígitos). README.md/padroes não contam.
_ARQUIVO_CONVERSA = re.compile(r"^(\d{3})-.+\.md$")
# Marcador de origem que uma fixture usa p/ apontar a conversa: "#NNN".
_PONTEIRO_CORPUS = re.compile(r"#(\d{3})")
# Alegação obsoleta que F2.2 remove do README.
_ALEGACAO_OBSOLETA = "Esta sessão criou apenas templates ilustrativos"


def _numeros_do_corpus() -> dict[str, str]:
    """Mapa NNN → nome do arquivo, para as conversas reais do corpus."""
    mapa: dict[str, str] = {}
    for caminho in _CORPUS_DIR.glob("*.md"):
        m = _ARQUIVO_CONVERSA.match(caminho.name)
        if m:
            mapa[m.group(1)] = caminho.name
    return mapa


def _descricoes_das_fixtures() -> list[tuple[Path, str]]:
    """(caminho, descricao) de cada fixture .jsonl sob api/evals/ (uma fixture por linha)."""
    out: list[tuple[Path, str]] = []
    for caminho in _EVALS_DIR.rglob("*.jsonl"):
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                fixture = json.loads(linha)
            except json.JSONDecodeError:
                continue
            descricao = fixture.get("descricao")
            if isinstance(descricao, str):
                out.append((caminho, descricao))
    return out


def _ponteiros_das_fixtures() -> list[tuple[Path, str]]:
    """(caminho, NNN) de cada marcador #NNN citado no descricao de uma fixture."""
    return [
        (caminho, numero)
        for caminho, descricao in _descricoes_das_fixtures()
        for numero in _PONTEIRO_CORPUS.findall(descricao)
    ]


def test_corpus_real_existe_e_nao_e_trivial() -> None:
    """Âncora anti-vácuo: o corpus existe com ≥4 conversas reais não-vazias.

    Sem isso, "todo ponteiro resolve" seria verde-vazio (zero ponteiros, zero corpus).
    """
    assert _CORPUS_DIR.is_dir(), f"corpus ausente: {_CORPUS_DIR}"
    corpus = _numeros_do_corpus()
    assert len(corpus) >= 4, f"esperava ≥4 conversas reais, achei {sorted(corpus.values())}"
    for nome in corpus.values():
        conteudo = (_CORPUS_DIR / nome).read_text(encoding="utf-8")
        assert len(conteudo) > 500, (
            f"conversa {nome} suspeita de vazia/stub ({len(conteudo)} chars)"
        )


def test_todo_ponteiro_de_fixture_resolve_para_conversa_real() -> None:
    """Dentes: cada #NNN citado por uma fixture resolve a um arquivo real do corpus.

    Ponteiro pendente (fixture cita #009 sem `009-*.md`) reprova — "apontar p/ conversa
    real" deixa de ser folclore de comentário e vira invariante checada.
    """
    corpus = _numeros_do_corpus()
    ponteiros = _ponteiros_das_fixtures()

    dangling = [
        f"{caminho.relative_to(_REPO_ROOT)} cita #{numero} — sem {numero}-*.md no corpus"
        for caminho, numero in ponteiros
        if numero not in corpus
    ]
    assert not dangling, "ponteiros pendentes:\n" + "\n".join(dangling)


def test_corpus_lastreia_fixtures_de_gate_de_forma_significativa() -> None:
    """O lastro não é uma referência solta: ≥3 conversas reais distintas são citadas
    por fixtures de gate (`canonicos/scripted_5/`).

    Apagar a citação de origem das fixtures derruba o gate (não é vácuo aceitável).
    """
    referenciadas = {
        numero for caminho, numero in _ponteiros_das_fixtures() if "scripted_5" in caminho.parts
    }
    assert len(referenciadas) >= 3, (
        f"esperava ≥3 conversas reais distintas lastreando o gate scripted_5, "
        f"achei {sorted(referenciadas)}"
    )


def test_readme_nao_alega_templates_ilustrativos_e_aponta_corpus() -> None:
    """O README de evals não pode regredir à alegação obsoleta nem perder o ponteiro
    p/ o corpus real."""
    texto = _README.read_text(encoding="utf-8")
    assert _ALEGACAO_OBSOLETA not in texto, (
        f"README ainda alega {_ALEGACAO_OBSOLETA!r} — o corpus já foi curado (F2.2)"
    )
    assert "docs/agente/conversas-reais" in texto, (
        "README deve apontar p/ o corpus real em docs/agente/conversas-reais/"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
