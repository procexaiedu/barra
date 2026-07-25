"""Golden set da bancada offline do extrator: rotulo HUMANO, versionado no repositorio.

O extrator nao precisa de LLM-judge: a saida e estruturada, o rotulo e um conjunto de pares
campo-valor e a metrica e igualdade. O que este modulo carrega e o gabarito — produzido a mao
sobre as Conversas cliente reais do piloto (`.scratch/extracao-eval-offline/golden-set-inicial.md`)
— na forma que a bancada consome.

Um ITEM e um turno decisivo: a tripla que o extrator le (conversa ate o instante, snapshot no
instante, agora) + o `gravado` (payload que a producao registrou naquele turno, baseline sem
credito) + o `rotulo` (o que ele DEVERIA ter registrado). So os campos presentes em `rotulo` sao
medidos — campo ausente nao entra na conta; `null` significa rotulado como AUSENTE.

Uma TRAJETORIA e um Atendimento inteiro: um cenario semeavel + os turnos em ordem + a sequencia de
estados rotulada. E o nivel de impacto (campo certo que nao faz o funil andar nao resolve o
problema do usuario).

O arquivo de dados vive ao lado (`golden_set.json`), e nao no diretorio da spec: e dado que o
codigo carrega e que o gate le, entao versiona junto do que o consome.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CAMINHO_PADRAO = Path(__file__).with_name("golden_set.json")

# Mesmo fuso da ancora temporal do turno (prepare_context._FUSO_BR): o `agora` do item viaja aware
# (clock injection) e vira BRT naive so na hora de renderizar a ancora.
_FUSO_BR = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class Fala:
    """Uma bolha da conversa reconstruida. `de` = "cliente" | "ia"."""

    de: str
    texto: str


@dataclass(frozen=True)
class ItemGolden:
    """Um turno decisivo rotulado.

    `registrado` e o snapshot que o turno leu (vira o bloco `<ja_registrado>`), com os campos do
    dominio + `aceita_valor` achatado (o sinal que separa cotado de aceito).
    """

    id: str
    atendimento: int
    descricao: str
    agora: datetime
    conversa: list[Fala]
    registrado: dict[str, Any]
    gravado: dict[str, Any]
    rotulo: dict[str, Any]

    @property
    def agora_brt(self) -> datetime:
        """Instante do turno em BRT naive — o formato que a ancora da extracao renderiza."""
        return self.agora.astimezone(_FUSO_BR).replace(tzinfo=None)


@dataclass(frozen=True)
class TrajetoriaGolden:
    """Um Atendimento inteiro: cenario semeavel + turnos em ordem + estados rotulados.

    `estados` tem um estado por turno — o que o Atendimento deve valer DEPOIS de cada extracao.
    """

    id: str
    atendimento: int
    descricao: str
    cenario: dict[str, Any]
    turnos: list[ItemGolden]
    estados: list[str]


@dataclass(frozen=True)
class GoldenSet:
    meta: dict[str, Any]
    itens: list[ItemGolden]
    trajetorias: list[TrajetoriaGolden]


def _item(bruto: dict[str, Any]) -> ItemGolden:
    return ItemGolden(
        id=bruto["id"],
        atendimento=int(bruto["atendimento"]),
        descricao=bruto.get("descricao", ""),
        agora=datetime.fromisoformat(bruto["agora"]),
        conversa=[Fala(de=f["de"], texto=f["texto"]) for f in bruto.get("conversa", [])],
        registrado=dict(bruto.get("registrado") or {}),
        gravado=dict(bruto.get("gravado") or {}),
        rotulo=dict(bruto.get("rotulo") or {}),
    )


def carregar_golden(caminho: Path | None = None) -> GoldenSet:
    """Le o golden set versionado. `caminho` None => `golden_set.json` deste diretorio."""
    dados = json.loads((caminho or CAMINHO_PADRAO).read_text(encoding="utf-8"))
    trajetorias = [
        TrajetoriaGolden(
            id=t["id"],
            atendimento=int(t["atendimento"]),
            descricao=t.get("descricao", ""),
            cenario=dict(t.get("cenario") or {}),
            turnos=[_item(x) for x in t.get("turnos", [])],
            estados=list(t.get("estados") or []),
        )
        for t in dados.get("trajetorias", [])
    ]
    return GoldenSet(
        meta=dict(dados.get("meta") or {}),
        itens=[_item(x) for x in dados.get("itens", [])],
        trajetorias=trajetorias,
    )
