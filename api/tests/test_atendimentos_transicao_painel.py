"""Maquina de estados manual do painel (kanban): validar_transicao_painel.

Defesa de servidor — o kanban ja bloqueia regressao e salto de coluna na UI, mas a regra
de negocio vive no service para que uma chamada direta a API nao a contorne. Em especial,
Aguardando_confirmacao (Pix / foto de portaria, controlada pelo agente) nunca pode ser pulada.
"""

import pytest

from barra.core.errors import ConflitoEstado
from barra.dominio.atendimentos.service import validar_transicao_painel


@pytest.mark.parametrize(
    ("atual", "destino"),
    [
        ("Novo", "Qualificado"),
        ("Novo", "Aguardando_confirmacao"),
        ("Triagem", "Aguardando_confirmacao"),
        ("Qualificado", "Aguardando_confirmacao"),
        ("Aguardando_confirmacao", "Em_execucao"),
        ("Confirmado", "Em_execucao"),
    ],
)
def test_transicoes_validas_nao_levantam(atual: str, destino: str) -> None:
    validar_transicao_painel(atual, destino)


@pytest.mark.parametrize(
    ("atual", "destino"),
    [
        # Pular Aguardando_confirmacao (Fernando "nao sabe" das etapas do agente).
        ("Novo", "Em_execucao"),
        ("Triagem", "Em_execucao"),
        ("Qualificado", "Em_execucao"),
        # Regressao.
        ("Aguardando_confirmacao", "Qualificado"),
        ("Em_execucao", "Aguardando_confirmacao"),
        ("Confirmado", "Qualificado"),
        # Sair de estado terminal ou de Em_execucao manualmente.
        ("Em_execucao", "Qualificado"),
        ("Fechado", "Qualificado"),
        ("Perdido", "Aguardando_confirmacao"),
    ],
)
def test_transicoes_invalidas_levantam_conflito(atual: str, destino: str) -> None:
    with pytest.raises(ConflitoEstado) as exc:
        validar_transicao_painel(atual, destino)
    assert exc.value.status_code == 409
    assert exc.value.details == {"estado_atual": atual, "estado_destino": destino}
