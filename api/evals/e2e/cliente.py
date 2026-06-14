"""Cliente simulado: protocolo + implementacao roteirizada (offline).

Decisao do dev: o cliente NUNCA e um 2o LLM (sem segunda chamada de API). Na corrida real o
cliente e o **Claude Code** conduzindo a conversa turno a turno via `sessao.py` — so o AGENTE
usa a API. Offline, `ClienteRoteirizado` reproduz falas fixas para validar o encanamento.

O cliente decide tambem QUANDO encerrar (sumiu/desistiu/combinou): `encerrou=True`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class TurnoCliente:
    """A reacao do cliente a um turno da IA."""

    texto: str | None  # None => cliente nao respondeu (sumiu)
    encerrou: bool = False  # True => fim da conversa (sumiu/combinou/desistiu)
    motivo: str = ""


class ClienteSimulado(Protocol):
    async def responder(self, *, texto_ia: str) -> TurnoCliente: ...


class ClienteRoteirizado:
    """Devolve as mensagens de `roteiro` em ordem; ao esgotar, encerra (cliente sumiu).

    Determinista e gratis: o conteudo textual nao precisa ser "inteligente", so coerente
    o bastante para o agente extrair. Usado na validacao offline do harness.
    """

    def __init__(self, roteiro: list[str]) -> None:
        self._fila = list(roteiro)
        self.recebidas: list[str] = []  # textos da IA, para auditoria

    async def responder(self, *, texto_ia: str) -> TurnoCliente:
        self.recebidas.append(texto_ia)
        if not self._fila:
            return TurnoCliente(texto=None, encerrou=True, motivo="roteiro_esgotado")
        return TurnoCliente(texto=self._fila.pop(0))
