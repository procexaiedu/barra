"""O contrato do valor lido de uma imagem: TEXTO na ida, `Decimal` na volta, nunca 100x errado.

Os tres testes daqui nasceram de uma medicao com as fotos REAIS do Grupo financeiro (14/08/2026),
e cada um cobre uma falha que o provider comete em **200 OK** — sem excecao, sem log, sem nada que
apareca num gate que nao olhe para o dado:

* declarado como `number`, o campo virava LOOP DE DIGITOS e truncava 4 de 10 leituras;
* declarado como texto, um roteamento do mesmo modelo devolve "65807" para R$ 658,07;
* um comprovante ambiguo gasta ~700 tokens de raciocinio antes da primeira chave do JSON.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from barra.agente_financeiro.comprovante import ExtracaoDoComprovante
from barra.core.vision import MAX_TOKENS_PADRAO, MODELO_VISION_PADRAO
from barra.workers.pix import ExtracaoPix


def _schema_do_valor(modelo: type) -> dict:
    return dict(modelo.model_json_schema()["properties"]["valor"])


@pytest.mark.parametrize("esquema", [ExtracaoDoComprovante, ExtracaoPix])
def test_o_valor_sobe_ao_provider_como_texto_e_nunca_como_number(esquema: type) -> None:
    """`Decimal | None` gera `anyOf[number, ...]` sozinho — e e ai que o decodificador se perde.

    A gramatica de `number` aceita digito para sempre: o modelo emite
    `1200.000000000000227373675443232059478759765625e0000...`, bate no `max_tokens` e a leitura
    inteira se perde em `finish_reason=length`. Com texto de padrao fixo a gramatica TERMINA.
    """
    tipos = {ramo.get("type") for ramo in _schema_do_valor(esquema)["anyOf"]}
    assert tipos == {"string", "null"}, "valor voltou a ser number no schema do provider"


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("1200.00", Decimal("1200.00")),  # o formato que o prompt pede
        ("1.200,00", Decimal("1200.00")),  # o provider ignorou o padrao e escreveu em BR
        ("R$ 385,80", Decimal("385.80")),  # ... e ainda trouxe o simbolo
        (1200.5, Decimal("1200.5")),  # ... ou ignorou o "string" e mandou number
        (None, None),
        ("", None),
        ("ilegivel", None),  # prosa no lugar do numero nao pode derrubar a leitura
    ],
)
def test_o_que_o_provider_manda_vira_decimal_sem_nunca_levantar(
    bruto: object, esperado: Decimal | None
) -> None:
    lido = ExtracaoDoComprovante(e_comprovante=True, legivel=True, valor=bruto)  # type: ignore[arg-type]
    assert lido.valor == esperado


def test_valor_inteiro_sem_centavos_e_recusado_em_vez_de_virar_100x() -> None:
    """ "65807" e o que o roteamento Vertex do gemini-3.1-flash-lite devolve para R$ 658,07.

    E tambem a grafia legitima de R$ 65.807. Como nao da para decidir, a leitura morre: perder
    o comprovante custa um "reenvia?"; aceita-lo custa um abatimento 100x maior que a venda.
    """
    lido = ExtracaoDoComprovante(e_comprovante=True, legivel=True, valor="65807")  # type: ignore[arg-type]
    assert lido.valor is None


def test_o_teto_de_saida_cabe_o_raciocinio_invisivel_do_provider() -> None:
    """O JSON do comprovante cabe em ~110 tokens; o que estoura o teto e o que nao se ve.

    Medido: com 800, uma imagem ambigua (o QR da agencia) truncava 1 em 8; com 1600, 0 em 32.
    """
    assert MAX_TOKENS_PADRAO >= 1600


def test_o_nome_do_modelo_de_vision_mora_num_lugar_so() -> None:
    """Tres call sites repetiam o default. Trocar de modelo em dois deles e a pior forma de A/B:
    a que ninguem declarou e ninguem mede."""
    raiz = Path(__file__).resolve().parents[1] / "src" / "barra"
    chamadores = (
        "workers/pix.py",
        "workers/comprovante_fechamento.py",
        "agente_financeiro/comprovante.py",
    )
    espalhados = [
        caminho for caminho in chamadores if "google/gemini" in (raiz / caminho).read_text()
    ]
    assert espalhados == [], f"nome de modelo hardcoded fora de core/vision.py: {espalhados}"
    assert MODELO_VISION_PADRAO.startswith("google/gemini")
