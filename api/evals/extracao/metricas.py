"""Metricas da bancada: nivel campo (diagnostico) e nivel trajetoria (impacto).

Nivel campo, com a ASSIMETRIA declarada — cada campo tem um erro que doi mais:

  | campo             | metrica que manda | por que                                    |
  |-------------------|-------------------|--------------------------------------------|
  | aceite de valor   | precisao          | falso positivo trava a escada de desconto  |
  | intencao          | recall            | falso negativo trava o funil inteiro       |
  | horario desejado  | ambos + evidencia | fantasma queima slot; ausencia mata reserva|
  | tipo do encontro  | precisao          | flip indevido dispara Pix de deslocamento  |

Dois tipos de veredito, porque a assimetria muda o que conta como erro:

  - CLASSE (aceite, intencao, e os dois detectores deterministicos): ha uma classe positiva
    ('agendamento' na intencao, True nos booleanos) e prever uma classe MENOR quando o rotulo e a
    positiva e falso NEGATIVO — e o que trava o funil.
  - VALOR (horario, tipo): prever um valor diferente do rotulado e falso POSITIVO — e o flip que
    queima slot ou dispara Pix.

Nivel trajetoria: a sequencia de estados do Atendimento contra a rotulada. E o que traduz "campo
certo" em "a venda avancou" — so o nivel campo pode melhorar sem que nada mude no funil.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from .extrator import Variante
from .golden import ItemGolden
from .janela import CAMPOS_ECO, detectores_do_turno

# campo -> (tipo de veredito, metrica que manda). A ordem e a do relatorio.
CAMPOS: dict[str, tuple[str, str]] = {
    "aceita_valor": ("classe", "precisao"),
    "intencao": ("classe", "recall"),
    "horario_desejado": ("valor", "ambos"),
    "horario_evidenciado": ("classe", "ambos"),
    "tipo_atendimento": ("valor", "precisao"),
    "recuo": ("classe", "ambos"),
}

# Classe positiva de cada campo de veredito por CLASSE.
_CLASSE_POSITIVA: dict[str, Any] = {
    "aceita_valor": True,
    "intencao": "agendamento",
    "horario_evidenciado": True,
    "recuo": True,
}


@dataclass
class Contagem:
    """Matriz de confusao de um campo. `n` = itens rotulados naquele campo."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def precisao(self) -> float | None:
        base = self.tp + self.fp
        return self.tp / base if base else None

    @property
    def recall(self) -> float | None:
        base = self.tp + self.fn
        return self.tp / base if base else None


@dataclass
class Rodada:
    """Resultado de UMA passada da bancada sobre o golden set (uma repeticao)."""

    campos: dict[str, Contagem] = field(default_factory=dict)
    eco_itens: int = 0  # itens rotulados com `reenvio_esperado: false`
    eco_reenvios: int = 0  # campos reenviados sem nada novo na conversa

    @property
    def eco_pct(self) -> float | None:
        return 100.0 * self.eco_reenvios / self.eco_itens if self.eco_itens else None


def _hhmm(valor: Any) -> str | None:
    """Horario em qualquer forma ("18:00", "18:00:00", time) -> "HH:MM". None passa direto."""
    if valor is None:
        return None
    texto = valor.strftime("%H:%M") if hasattr(valor, "strftime") else str(valor)
    partes = texto.split(":")
    return f"{partes[0].zfill(2)}:{partes[1]}" if len(partes) >= 2 else texto


def previsto_do_payload(
    item: ItemGolden, payload: dict[str, Any], *, variante: Variante
) -> dict[str, Any]:
    """O que o extrator previu para cada campo medido, no turno do item.

    Os dois detectores (`horario_evidenciado`, `recuo`) NAO saem do payload: rodam sobre a conversa,
    como em prod. A `intencao` passa pela promocao derivada quando a variante a liga — mesma regra
    do dominio (`_promover_intencao_por_evidencia`): horario gravado + marca de evidencia sobem a
    intencao a 'agendamento'. O aceite desce com o recuo do turno (o dominio o rebaixa no merge dos
    sinais) e, na variante pre-patch-24/07, sobe tambem por `valor_acordado` gravado.
    """
    evidenciado, recuo = detectores_do_turno(item)
    intencao = payload.get("intencao")
    horario = _hhmm(payload.get("horario_desejado")) or _hhmm(
        item.registrado.get("horario_desejado")
    )
    marca = evidenciado or bool(item.registrado.get("horario_evidenciado"))
    if variante.promocao_intencao and horario is not None and marca:
        intencao = "agendamento"
    aceite = bool((payload.get("sinais_qualificacao") or {}).get("aceita_valor"))
    if variante.aceite_derivado_do_valor and payload.get("valor_acordado") is not None:
        aceite = True
    return {
        "aceita_valor": aceite and not recuo,
        "intencao": intencao,
        "horario_desejado": _hhmm(payload.get("horario_desejado")),
        "horario_evidenciado": evidenciado,
        "tipo_atendimento": payload.get("tipo_atendimento"),
        "recuo": recuo,
    }


def _veredito(campo: str, previsto: Any, rotulado: Any) -> str:
    """'tp' | 'fp' | 'fn' | 'tn' para um campo, no tipo de veredito declarado em `CAMPOS`."""
    tipo, _ = CAMPOS[campo]
    if tipo == "classe":
        positiva = _CLASSE_POSITIVA[campo]
        acertou_positiva = previsto == positiva
        rotulo_positivo = rotulado == positiva
        if acertou_positiva and rotulo_positivo:
            return "tp"
        if acertou_positiva:
            return "fp"
        return "fn" if rotulo_positivo else "tn"
    if previsto is None:
        return "fn" if rotulado is not None else "tn"
    if rotulado is not None and previsto == rotulado:
        return "tp"
    return "fp"


def _reenvios(item: ItemGolden, payload: dict[str, Any]) -> int:
    """Campos que o payload reenviou com o MESMO valor que ja estava no snapshot (o eco medido no
    piloto: 35% das extracoes nao traziam nenhum par novo)."""
    return sum(
        1
        for campo in CAMPOS_ECO
        if payload.get(campo) is not None
        and item.registrado.get(campo) is not None
        and str(payload[campo]) == str(item.registrado[campo])
    )


def avaliar(
    itens: list[ItemGolden], payloads: dict[str, dict[str, Any]], *, variante: Variante
) -> Rodada:
    """Uma passada: para cada item rotulado, o veredito de cada campo + a contagem de eco."""
    rodada = Rodada()
    for item in itens:
        payload = payloads.get(item.id, {})
        previsto = previsto_do_payload(item, payload, variante=variante)
        for campo in CAMPOS:
            if campo not in item.rotulo:
                continue  # campo nao rotulado neste item: nao entra na conta
            contagem = rodada.campos.setdefault(campo, Contagem())
            veredito = _veredito(campo, previsto[campo], item.rotulo[campo])
            setattr(contagem, veredito, getattr(contagem, veredito) + 1)
        if item.rotulo.get("reenvio_esperado") is False:
            rodada.eco_itens += 1
            rodada.eco_reenvios += _reenvios(item, payload)
    return rodada


@dataclass
class Dispersao:
    """Uma metrica ao longo das repeticoes: media + dispersao (nao so media)."""

    media: float
    minimo: float
    maximo: float
    desvio: float
    n_repeticoes: int

    def como_dict(self) -> dict[str, Any]:
        return {
            "media": round(self.media, 4),
            "min": round(self.minimo, 4),
            "max": round(self.maximo, 4),
            "desvio": round(self.desvio, 4),
            "repeticoes": self.n_repeticoes,
        }


def dispersao(valores: list[float | None]) -> Dispersao | None:
    """Agrega as repeticoes de uma metrica. None quando nenhuma repeticao pode calcula-la
    (denominador zero em todas — ex.: campo sem item rotulado)."""
    validos = [v for v in valores if v is not None]
    if not validos:
        return None
    return Dispersao(
        media=statistics.mean(validos),
        minimo=min(validos),
        maximo=max(validos),
        desvio=statistics.pstdev(validos) if len(validos) > 1 else 0.0,
        n_repeticoes=len(validos),
    )


def agregar(rodadas: list[Rodada]) -> dict[str, Any]:
    """Agrega as repeticoes num bloco de relatorio: por campo (metrica que manda + dispersao +
    contagem da 1a repeticao) e o eco. Uma repeticao so => dispersao zerada, nao ausente."""
    campos: dict[str, Any] = {}
    for campo, (_tipo, manda) in CAMPOS.items():
        contagens = [r.campos.get(campo) for r in rodadas]
        primeira = next((c for c in contagens if c is not None), None)
        precisao = dispersao([c.precisao if c else None for c in contagens])
        recall = dispersao([c.recall if c else None for c in contagens])
        campos[campo] = {
            "manda": manda,
            "precisao": precisao.como_dict() if precisao else None,
            "recall": recall.como_dict() if recall else None,
            "n": primeira.n if primeira else 0,
            "contagem": (
                f"{primeira.tp}/{primeira.fp}/{primeira.fn}/{primeira.tn}"
                if primeira
                else "0/0/0/0"
            ),
        }
    eco = dispersao([r.eco_pct for r in rodadas])
    return {
        "campos": campos,
        "eco": {
            "itens": rodadas[0].eco_itens if rodadas else 0,
            "reenvios": rodadas[0].eco_reenvios if rodadas else 0,
            "pct": eco.media if eco else None,
        },
    }


@dataclass
class ResultadoTrajetoria:
    """Comparacao da sequencia de estados prevista com a rotulada."""

    id: str
    prevista: list[str]
    rotulada: list[str]

    @property
    def igual(self) -> bool:
        return self.prevista == self.rotulada

    @property
    def prefixo_comum(self) -> int:
        """Quantos turnos a trajetoria acompanha antes de divergir."""
        n = 0
        for previsto, rotulado in zip(self.prevista, self.rotulada, strict=False):
            if previsto != rotulado:
                break
            n += 1
        return n

    @property
    def estado_final_igual(self) -> bool:
        return (
            bool(self.prevista) and bool(self.rotulada) and self.prevista[-1] == self.rotulada[-1]
        )

    def como_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prevista": self.prevista,
            "rotulada": self.rotulada,
            "igual": self.igual,
            "prefixo_comum": self.prefixo_comum,
            "estado_final_igual": self.estado_final_igual,
        }
