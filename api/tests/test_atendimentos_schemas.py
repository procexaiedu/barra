"""Validacao de schemas Pydantic do contexto atendimentos."""

import pytest

from barra.dominio.atendimentos.schemas import EditarDadosRequest


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        (" Apartamento ", "apartamento"),
        ("", None),
        ("   ", None),
        (None, None),
        ("BALADA", "balada"),
    ],
)
def test_editar_dados_normaliza_tipo_local(entrada: str | None, esperado: str | None) -> None:
    req = EditarDadosRequest(tipo_local=entrada)
    assert req.tipo_local == esperado
