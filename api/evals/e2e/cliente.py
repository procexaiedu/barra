"""Cliente simulado: protocolo + implementacao roteirizada (offline).

Decisao do dev: o cliente NUNCA e um 2o LLM (sem segunda chamada de API). Na corrida real o
cliente e o **Claude Code** conduzindo a conversa turno a turno via `sessao.py` — so o AGENTE
usa a API. Offline, `ClienteRoteirizado` reproduz falas fixas para validar o encanamento.

O cliente decide tambem QUANDO encerrar (sumiu/desistiu/combinou): `encerrou=True`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from evals.harness_fiel import BolhaCliente

# Uma fala do cliente = UMA bolha (str) ou VARIAS bolhas do mesmo burst (list[str]) — as duas
# seguidas, antes de a IA responder, que o debounce coalesce num unico turno. E a forma real do
# WhatsApp ("consigo 21h?" / "ou 22h se der melhor" em duas bolhas), e o rig ja a suportava do lado
# de baixo (`harness_fiel.rodar_turno_fiel` aceita `list[str | BolhaCliente]`) sem nenhum roteiro
# usa-la. `str` continua valendo em todo lugar: todo roteiro escrito antes desta chave e uma lista
# de strings e nao muda de comportamento.
#
# `BolhaCliente` entrou aqui em 14/08: o rig e2e so sabia emitir TEXTO, enquanto o parser do
# webhook aceita `texto | audio | imagem` (`webhook/parser.py`). Ou seja, STT e vision — os dois
# que ja cairam em prod — nunca tinham sido exercitados numa CONVERSA. O caminho de baixo ja
# aceitava a bolha de midia; o que faltava era o roteiro poder declara-la.
#
# ⚠️ FRONTEIRA (a mesma da docstring de `BolhaCliente`): isto cobre a midia que entra na JANELA e
# o LLM le via `traduzir_mensagens` — imagem com caption, audio ja transcrito. NAO cobre o
# comprovante de Pix nem a foto de portaria: essas sao roteadas por `workers/media.py::rotear_
# imagem` ANTES do turno de texto, e inserir uma imagem aqui nao reproduz esse desvio. Um cenario
# que precise DAQUELE caminho continua sem instrumento.
FalaDoCliente = str | BolhaCliente | list[str | BolhaCliente]


def _texto_da_bolha(b: str | BolhaCliente) -> str:
    """O que o AGENTE ve daquela bolha — nao a media_object_key nem o tipo.

    Numa bolha de midia o `conteudo` ja e o dado resolvido (caption da imagem, transcricao do
    audio), que e exatamente o que chega ao LLM em prod. Um check keyed por gatilho ("manda o
    endereco") tem de casar a fala dele esteja ela digitada ou falada.
    """
    return b if isinstance(b, str) else b.conteudo


def texto_do_burst(fala: FalaDoCliente) -> str:
    """As bolhas do burst como UM texto — a forma que os checks leem (`turnos_cliente`).

    Junta por linha em branco, o mesmo separador de bolha que os checks usam no texto da IA
    (`re.split(r"\\n\\s*\\n", ...)`): um gatilho declarado no cenario ("consigo 21h") continua
    casando a fala dele esteja ela sozinha ou no meio de um burst."""
    if isinstance(fala, str | BolhaCliente):
        return _texto_da_bolha(fala)
    return "\n\n".join(_texto_da_bolha(b) for b in fala)


@dataclass
class TurnoCliente:
    """A reacao do cliente a um turno da IA."""

    texto: FalaDoCliente | None  # None => cliente nao respondeu (sumiu)
    encerrou: bool = False  # True => fim da conversa (sumiu/combinou/desistiu)
    motivo: str = ""


class ClienteSimulado(Protocol):
    async def responder(self, *, texto_ia: str) -> TurnoCliente: ...


class ClienteRoteirizado:
    """Devolve as mensagens de `roteiro` em ordem; ao esgotar, encerra (cliente sumiu).

    Determinista e gratis: o conteudo textual nao precisa ser "inteligente", so coerente
    o bastante para o agente extrair. Usado na validacao offline do harness.

    Um item do roteiro pode ser uma `list[str]`: as bolhas do MESMO burst, entregues juntas ao
    turno (ver `FalaDoCliente`).
    """

    def __init__(self, roteiro: Sequence[FalaDoCliente]) -> None:
        self._fila: list[FalaDoCliente] = list(roteiro)
        self.recebidas: list[str] = []  # textos da IA, para auditoria

    async def responder(self, *, texto_ia: str) -> TurnoCliente:
        self.recebidas.append(texto_ia)
        if not self._fila:
            return TurnoCliente(texto=None, encerrou=True, motivo="roteiro_esgotado")
        return TurnoCliente(texto=self._fila.pop(0))
