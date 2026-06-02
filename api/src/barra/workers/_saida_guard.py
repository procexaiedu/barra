"""Rede final de saída no `enviar_turno`: o último ponto antes da bolha ir ao cliente (SEC-OUT-01).

O `output_guard` (ADR 0016) é um nó do grafo — cobre só o caminho do LLM. Os despachos canned
(transcrição falhou, `coordenador`) e o reengajamento (`timeouts`) enfileiram `enviar_turno`
DIRETO, pulando o guard. Além disso, o `output_guard` não redige PII. Estas funções puras dão a
`enviar_turno` duas defesas independentes que valem para TODOS os caminhos:

- **Vazamento de IA** (`tem_marcador_ia`, reusado do `output_guard` — fonte única do regex): a bolha
  admite ser IA/bot/LLM. Match → o `enviar_turno` bloqueia o turno e escala (a bolha não sai).
- **Eco de PII** (`redigir_pii_eco`): a IA repete CPF/RG/telefone que o PRÓPRIO cliente mandou
  (SEC-PII-02). Redação é **por eco**: só mascara o token se ele também aparece no inbound recente
  do cliente. Isso é deliberado — a chave Pix da modelo (que pode ser CPF/telefone, `workers/pix.py`)
  NUNCA vem do cliente, então nunca é mascarada e o fluxo do Pix de deslocamento segue intacto.
  Endereço/CEP ficam de fora (a IA combina endereço de atendimento externo legitimamente).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from barra.agente.nos.output_guard import tem_marcador_ia

__all__ = ["extrair_tokens_pii", "redigir_pii_eco", "tem_marcador_ia"]

# PII do cliente que a IA não deve ecoar. Endereço/CEP de propósito fora (saída legítima). O `tipo`
# alimenta a métrica; em sobreposição de formato (telefone de 11 dígitos casa o shape de CPF) o
# rótulo pode ser impreciso, mas a redação — que é o que importa — acontece igual.
_PADROES_PII: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cpf", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("rg", re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-?[\dxX]\b")),
    # RG corrido (sem pontuacao): 9 digitos EXATOS. 9 (nao 8) evita colidir com CEP, que fica de
    # fora de proposito (endereco e saida legitima). CPF (11) e telefone (10-13) tem outros shapes,
    # entao o cerco de digito-vizinho impede sobreposicao.
    ("rg", re.compile(r"(?<!\d)\d{9}(?!\d)")),
    (
        "telefone",
        re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?[\s.\-]?9?\d{4}[\s.\-]?\d{4}(?!\d)"),
    ),
)

# Comprimentos válidos do token (só dígitos) por tipo — corta falso-positivo de número curto/longo.
# RG aceita 7 (dígito verificador 'X' some no strip de dígitos) a 9.
_TAMANHOS_VALIDOS: dict[str, set[int]] = {
    "cpf": {11},
    "rg": {7, 8, 9},
    "telefone": {10, 11, 12, 13},
}

_REDIGIDO = "***"


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _valido(tipo: str, digitos: str) -> bool:
    return len(digitos) in _TAMANHOS_VALIDOS[tipo]


def _chaves(tipo: str, digitos: str) -> set[str]:
    """Chaves de equivalência p/ casar eco apesar de variação de formato. Telefone também casa pela
    cauda de 8 dígitos (absorve prefixo +55/DDD entre cliente e IA)."""
    chaves = {digitos}
    if tipo == "telefone" and len(digitos) >= 8:
        chaves.add(digitos[-8:])
    return chaves


def extrair_tokens_pii(texto: str) -> set[str]:
    """Conjunto de chaves normalizadas de toda PII (CPF/RG/telefone) achada no texto.

    Usado tanto para montar o set do inbound do cliente quanto para o pre-check barato da saída
    (se a saída não tem nenhum shape de PII, o `enviar_turno` nem consulta o banco)."""
    tokens: set[str] = set()
    for tipo, padrao in _PADROES_PII:
        for m in padrao.finditer(texto):
            d = _digitos(m.group())
            if _valido(tipo, d):
                tokens |= _chaves(tipo, d)
    return tokens


def redigir_pii_eco(texto: str, tokens_cliente: set[str]) -> tuple[str, list[str]]:
    """Mascara em `texto` só a PII cujo token normalizado também está em `tokens_cliente` (eco).

    Devolve `(texto_redigido, tipos_redigidos)`. `tokens_cliente` vazio → nada muda.
    """
    if not tokens_cliente:
        return texto, []
    redigidos: list[str] = []

    def _substituir(tipo: str) -> Callable[[re.Match[str]], str]:
        def _f(m: re.Match[str]) -> str:
            d = _digitos(m.group())
            if _valido(tipo, d) and (_chaves(tipo, d) & tokens_cliente):
                redigidos.append(tipo)
                return _REDIGIDO
            return m.group()

        return _f

    for tipo, padrao in _PADROES_PII:
        texto = padrao.sub(_substituir(tipo), texto)
    return texto, redigidos
