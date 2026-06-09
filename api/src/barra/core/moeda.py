"""Formatação monetária no padrão BR para as superfícies operacionais (cards e respostas de
comando do grupo de Coordenação). Fonte única do formato `R$ 1.500,00`.

Distinto do filtro `brl` da persona (`agente/persona.py`, `R$1.500` sem centavos): aquele é a voz
voltada ao cliente; este é a voz operacional interna (modelo/Fernando), que mostra os centavos.
"""

from decimal import Decimal
from typing import Any


def formatar_brl(valor: Any) -> str:
    """Formata um valor monetário como `R$ 1.500,00` (espaço, milhar com ponto, decimal com
    vírgula — UX §4 regra 6). O default Python `{:,.2f}` usa o locale americano (`1,500.00`); a
    troca de separadores converte para o padrão brasileiro."""
    return "R$ " + f"{Decimal(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
