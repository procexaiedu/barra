"""Carrega as constantes de DADO REAL que estes harnesses usam — de fora do git.

Por que existe: os replays e os renderizadores apontam para threads REAIS do corpus, chaveadas
pelo `@lid` do cliente, e as fixtures reproduzem a ficha real da modelo (nome, endereço do
ponto de encontro, chave Pix). Isso é PII de cliente e de terceiros: **não pode ser versionado**.
O código pode, e deve — foi ele que fundamentou as decisões de prompt.

Então a seleção de threads e as fichas saíram do `.py` e viraram JSON em `_dados_reais/`, que o
`.gitignore` deste diretório exclui. O código versionado sabe carregar; o dado fica na máquina.

Onde procura, em ordem:
  1. `$EVAL_CORPUS_DADOS` (diretório)
  2. `<este diretório>/_dados_reais`

Arquivos, um por constante: `<modulo>.<CONSTANTE>.json`
(ex.: `replay_agente_terminal.MODELOS_REAIS.json`).

Se você clonou o repo numa máquina nova, esses JSONs não vêm junto — é de propósito. Regenere
a partir do corpus (`fichas_threads.jsonl` / `corpus.*`) ou copie da máquina que já os tem.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_PADRAO = Path(__file__).resolve().parent / "_dados_reais"


def diretorio() -> Path:
    return Path(os.environ["EVAL_CORPUS_DADOS"]) if os.environ.get("EVAL_CORPUS_DADOS") else _PADRAO


def carregar(modulo: str, constante: str) -> Any:
    """Devolve a constante gravada em `<modulo>.<constante>.json`."""
    caminho = diretorio() / f"{modulo}.{constante}.json"
    if not caminho.exists():
        raise RuntimeError(
            f"dado real ausente: {caminho}\n"
            f"`{constante}` de `{modulo}.py` aponta para threads/fichas reais do corpus (PII) e "
            "por isso NÃO é versionado. Copie o diretório `_dados_reais/` da máquina que o tem, "
            "ou aponte $EVAL_CORPUS_DADOS para onde ele estiver. Ver scripts/eval_corpus/README.md."
        )
    with caminho.open(encoding="utf-8") as fh:
        return json.load(fh)
