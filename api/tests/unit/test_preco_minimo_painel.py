"""Contrato do `preco_minimo` na borda HTTP do painel (DTOs de `modelo_programas`).

O piso absoluto da linha (11/08/2026, ao subir a Catarina) é cadastrado por aqui. Dois pontos
que só o DTO garante e nenhum teste de agente pegaria: o 422 que espelha o CHECK da migration, e
a distinção omitido-vs-`null` que decide se um reajuste de preço PRESERVA ou APAGA o piso — se
apagar em silêncio, o guard volta a liberar os 25% cheios sobre um pacote cadastrado como mínimo.
Puro: sem DB, sem crédito.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from barra.dominio.modelos.schemas import AtualizarPrecoProgramaBody, VincularProgramaBody


def test_vinculo_aceita_piso_abaixo_do_preco() -> None:
    body = VincularProgramaBody(
        programa_id=uuid4(),
        duracao_id=uuid4(),
        preco=Decimal("400"),
        preco_minimo=Decimal("300"),
    )
    assert body.preco_minimo == Decimal("300")


def test_vinculo_aceita_linha_nao_descontavel() -> None:
    """`preco_minimo == preco` é o caso dos 30min da Catarina: 250 é o preço E o mínimo."""
    body = VincularProgramaBody(
        programa_id=uuid4(),
        duracao_id=uuid4(),
        preco=Decimal("250"),
        preco_minimo=Decimal("250"),
    )
    assert body.preco_minimo == body.preco


def test_piso_acima_do_preco_e_recusado() -> None:
    """Espelha o CHECK da tabela: a escada clampada devolveria um valor MAIOR que a tabela e a IA
    cotaria mais caro justamente ao dar desconto."""
    with pytest.raises(ValidationError):
        VincularProgramaBody(
            programa_id=uuid4(),
            duracao_id=uuid4(),
            preco=Decimal("250"),
            preco_minimo=Decimal("300"),
        )
    with pytest.raises(ValidationError):
        AtualizarPrecoProgramaBody(preco=Decimal("250"), preco_minimo=Decimal("300"))


def test_patch_sem_o_campo_nao_toca_o_piso() -> None:
    """Reajuste de preço puro: `preco_minimo` fora do corpo, e a rota preserva o cadastrado."""
    body = AtualizarPrecoProgramaBody(preco=Decimal("450"))
    assert "preco_minimo" not in body.model_fields_set


def test_patch_com_null_explicito_remove_o_piso() -> None:
    """`null` no corpo é intenção de limpar — o mesmo `preco_minimo is None` do default, separado
    dele só pelo `model_fields_set`."""
    body = AtualizarPrecoProgramaBody.model_validate({"preco": "450", "preco_minimo": None})
    assert "preco_minimo" in body.model_fields_set
    assert body.preco_minimo is None
